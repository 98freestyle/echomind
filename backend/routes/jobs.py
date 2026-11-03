"""
Upload, progress stream, preview and download routes.
"""

import logging
import mimetypes
import os
import shutil
import subprocess
import threading
import time
import uuid
from pathlib import Path

from flask import Blueprint, Response, jsonify, make_response, request, send_file
from flask_cors import cross_origin
from pydub.utils import mediainfo
from werkzeug.utils import secure_filename

from config import TEMP_DIR
from db import get_db_connection
from services.processing import active_downloading, active_processing, cleanup_old_temp, is_rate_limited, job_state_lock, process_job
from services.usage import get_account_weekly_usage, get_guest_weekly_usage
from utils.helpers import allowed_file, get_client_ip, log

logger = logging.getLogger("echomind")
jobs_bp = Blueprint("jobs", __name__)


@jobs_bp.route("/upload", methods=["POST"])
@cross_origin()
def upload():
    """
    Handle audio upload:
    - Validate type
    - Apply rate limiting
    - Save to TEMP_DIR
    - Insert job in DB
    - Start async processing thread
    """
    cleanup_old_temp()

    if "file" not in request.files:
        return jsonify({"error": "No file uploaded."}), 400

    file = request.files["file"]
    filename = secure_filename(file.filename)
    if not filename or not allowed_file(filename):
        return jsonify({"error": "Unsupported file type."}), 400

    ip = get_client_ip()
    logger.debug(f"Client IP: {ip}")
    rate_limit_msg = is_rate_limited(ip)
    if rate_limit_msg:
        return jsonify({"error": rate_limit_msg}), 429

    # Determine user context
    email = request.headers.get("X-User-Email")
    user_id = None
    is_guest = True
    is_premium = False

    if email:
        conn = None
        try:
            conn = get_db_connection()
            c = conn.cursor()
            c.execute("SELECT id, is_premium FROM users WHERE email = ?", (email,))
            result = c.fetchone()
            if result:
                user_id, is_premium_flag = result
                is_guest = False
                is_premium = bool(is_premium_flag)
        except Exception as e:
            logger.error(f"Failed to look up user: {e}")
        finally:
            if conn:
                conn.close()

    # Save upload
    selected_stems = request.form.getlist("stems") or ["vocals", "other"]
    job_id = str(uuid.uuid4())
    with job_state_lock:
        active_processing.add(job_id)

    temp_upload_dir = os.path.join(TEMP_DIR, job_id)
    os.makedirs(temp_upload_dir, exist_ok=True)
    upload_path = os.path.join(temp_upload_dir, filename)
    file.save(upload_path)

    # Validate audio
    try:
        duration = float(mediainfo(upload_path).get("duration", "0"))
        if duration <= 0:
            raise ValueError("No valid audio stream")
        if duration > 600:  # 10 min hard cap
            raise ValueError("File too long")
    except Exception:
        shutil.rmtree(temp_upload_dir, ignore_errors=True)
        with job_state_lock:
            active_processing.discard(job_id)
        return jsonify({"error": "Invalid or corrupted audio file."}), 400

    # Extract audio from MP4 to WAV
    if Path(filename).suffix.lower() == ".mp4":
        wav_path = os.path.join(temp_upload_dir, f"{Path(filename).stem}.wav")
        cmd = ["ffmpeg", "-i", upload_path, "-vn", "-acodec", "pcm_s16le", wav_path, "-y"]
        log(job_id, f"Extracting audio from MP4: {' '.join(cmd)}")
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if result.returncode != 0 or not os.path.exists(wav_path) or os.path.getsize(wav_path) < 4096:
            shutil.rmtree(temp_upload_dir, ignore_errors=True)
            with job_state_lock:
                active_processing.discard(job_id)
            return jsonify({"error": "Invalid or corrupted audio file."}), 400
        upload_path = wav_path
        log(job_id, "Extracted audio from MP4.")

    duration_min = round(duration / 60, 2)

    # Apply weekly usage limits
    if is_guest:
        weekly_usage = get_guest_weekly_usage(ip)
        cap = 10  # guest cap = 10 min/week
    else:
        weekly_usage, cap = get_account_weekly_usage(user_id)

    if weekly_usage + duration_min > cap:
        return jsonify({
            "error": f"Weekly limit exceeded ({cap} min max). You've used {round(weekly_usage, 2)} min."
        }), 403

    # Log usage in DB
    conn = None
    try:
        conn = get_db_connection()
        c = conn.cursor()
        upload_date = time.strftime("%Y-%m-%d")
        c.execute(
            "INSERT INTO usage (user_id, ip, date, duration_min, filename, stems) VALUES (?, ?, ?, ?, ?, ?)",
            (user_id, ip, upload_date, duration_min, filename, ",".join(selected_stems))
        )
        conn.commit()
    except Exception as e:
        logger.error(f"Failed to log usage: {e}")
    finally:
        if conn:
            conn.close()

    # Insert job row
    conn = None
    try:
        conn = get_db_connection()
        c = conn.cursor()
        c.execute(
            "INSERT INTO jobs (id, ip, status, zip_path, priority) VALUES (?, ?, ?, ?, ?)",
            (job_id, ip, 'processing', None, int(is_premium))
        )
        conn.commit()
    except Exception as e:
        logger.error(f"Failed to insert job into DB: {e}")
    finally:
        if conn:
            conn.close()

    # Spawn async processor
    threading.Thread(target=process_job, args=(job_id, upload_path, filename, selected_stems)).start()
    return jsonify({"job_id": job_id})


@jobs_bp.route("/stream/<job_id>")
@cross_origin()
def stream(job_id):
    """
    Server-Sent Events (SSE) stream for job progress.
    Polls DB until job is 'done' or 'error'.
    """
    def event_stream():
        yield "data: Processing started...\n\n"
        while True:
            conn = None
            try:
                conn = get_db_connection()
                c = conn.cursor()
                c.execute("SELECT status FROM jobs WHERE id = ?", (job_id,))
                result = c.fetchone()
                if not result:
                    yield "data: Job not found\n\n"
                    break
                status = result["status"]
                if status == "done":
                    yield "data: Job complete\n\n"
                    break
                elif status == "error":
                    yield "data: Error\n\n"
                    break
                else:
                    time.sleep(2)
            except Exception as e:
                yield f"data: Error: {str(e)}\n\n"
                break
            finally:
                if conn:
                    conn.close()

    return Response(event_stream(), mimetype="text/event-stream")


@jobs_bp.route("/download-link/<job_id>")
@cross_origin()
def download_link(job_id):
    """
    Return a signed URL for direct download if job is complete.
    """
    conn = None
    try:
        conn = get_db_connection()
        c = conn.cursor()
        c.execute("SELECT zip_path FROM jobs WHERE id = ? AND status = 'done'", (job_id,))
        row = c.fetchone()

        if not row or not row["zip_path"] or not os.path.exists(row["zip_path"]):
            return jsonify({"error": "Download not ready or expired."}), 410

        zip_filename = os.path.basename(row["zip_path"])
        return jsonify({"url": f"/download-direct/{job_id}/{zip_filename}"})
    except Exception as e:
        logger.error(f"Download link error: {e}")
        return jsonify({"error": f"Server error: {str(e)}"}), 500
    finally:
        if conn:
            conn.close()


@jobs_bp.route("/download-direct/<job_id>/<filename>")
@cross_origin()
def download_direct(job_id, filename):
    """
    Direct file download endpoint:
    - Serves final ZIP
    - Schedules job cleanup after sending
    """
    conn = None
    try:
        conn = get_db_connection()
        c = conn.cursor()
        c.execute("SELECT zip_path FROM jobs WHERE id = ?", (job_id,))
        row = c.fetchone()

        if not row:
            return jsonify({"error": "Job not found."}), 404

        path = row["zip_path"]
        if not path or not os.path.exists(path):
            return jsonify({"error": "File missing."}), 410

        folder_to_delete = os.path.dirname(path)
        with job_state_lock:
            active_downloading.add(job_id)

        response = make_response(send_file(path, as_attachment=True))
        response.headers["Content-Type"] = mimetypes.guess_type(path)[0] or "application/zip"
        response.headers["Content-Disposition"] = f'attachment; filename="{filename}"'
        response.headers["Access-Control-Expose-Headers"] = "Content-Disposition"

        def cleanup_job():
            time.sleep(2)
            with job_state_lock:
                active_downloading.discard(job_id)
            shutil.rmtree(folder_to_delete, ignore_errors=True)
            conn_cleanup = None
            try:
                conn_cleanup = get_db_connection()
                c = conn_cleanup.cursor()
                c.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
                conn_cleanup.commit()
                logger.info(f"[CLEANUP] Removed job {job_id} and temp folder.")
            except Exception as e:
                logger.error(f"[CLEANUP ERROR] Could not delete job {job_id}: {e}")
            finally:
                if conn_cleanup:
                    conn_cleanup.close()

        threading.Thread(target=cleanup_job).start()
        return response
    except Exception as e:
        logger.error(f"Download direct error: {e}")
        return jsonify({"error": f"Server error: {str(e)}"}), 500
    finally:
        if conn:
            conn.close()


@jobs_bp.route("/preview/<job_id>/<stem>")
@cross_origin()
def preview(job_id, stem):
    """
    Serve a short preview (30s MP3/WAV) of a processed stem.
    """
    conn = None
    try:
        # Ensure job exists
        conn = get_db_connection()
        c = conn.cursor()
        c.execute("SELECT id FROM jobs WHERE id = ?", (job_id,))
        exists = c.fetchone()
        if not exists:
            return jsonify({"error": "Job not found."}), 404

        # Validate stem name
        stem = stem.lower()
        valid_stems = {"vocals", "drums", "bass", "other", "no_vocals"}
        if stem not in valid_stems:
            return jsonify({"error": "Invalid stem requested."}), 400

        preview_dir = os.path.join(TEMP_DIR, job_id, "preview")
        if not os.path.exists(preview_dir):
            return jsonify({"error": "Preview not found or expired."}), 404

        # Prefer MP3 preview
        mp3_path = os.path.join(preview_dir, f"{stem}.mp3")
        if os.path.exists(mp3_path):
            return send_file(mp3_path, mimetype="audio/mpeg")

        # Fallback to WAV
        wav_path = os.path.join(preview_dir, f"{stem}.wav")
        if stem == "other" and not os.path.exists(wav_path):
            wav_path = os.path.join(preview_dir, "no_vocals.wav")

        if os.path.exists(wav_path):
            return send_file(wav_path, mimetype="audio/wav")

        return jsonify({"error": "Stem not found."}), 404
    except Exception as e:
        logger.error(f"[PREVIEW ERROR] {e}")
        return jsonify({"error": "Server error."}), 500
    finally:
        if conn:
            conn.close()

