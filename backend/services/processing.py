"""
Job processing (Demucs splitting, previews, zips), rate limiting and temp file cleanup.
"""

import logging
import os
import shutil
import threading
import time
from collections import defaultdict, deque

from pydub import AudioSegment

from audio_splitter import split_audio
from config import JOB_EXPIRATION, MAX_DISK_USAGE_MB, MAX_JOBS_PER_IP, MAX_UPLOADS_PER_MIN, TEMP_DIR
from db import get_db_connection
from utils.helpers import log

logger = logging.getLogger("echomind")

# In memory state, shared by the routes in this worker
UPLOAD_HISTORY = defaultdict(lambda: deque())
active_processing = set()
active_downloading = set()
upload_history_lock = threading.Lock()
job_state_lock = threading.Lock()   # Protects active_processing / active_downloading


def startup_cleanup():
    """
    On boot: remove old temp files/folders > 1hr old.
    Prevents buildup if server restarts.
    """
    logger.info("Running startup cleanup of TEMP_DIR...")
    now = time.time()
    for job_id in os.listdir(TEMP_DIR):
        path = os.path.join(TEMP_DIR, job_id)
        try:
            if os.path.isdir(path):
                last_mod = os.path.getmtime(path)
                age = now - last_mod
                if age > 3600:
                    shutil.rmtree(path, ignore_errors=True)
                    logger.info(f"[BOOT CLEANUP] Removed old folder: {job_id}")
            else:
                os.remove(path)
        except Exception as e:
            logger.error(f"Startup cleanup error on {path}: {e}")


def cleanup_old_temp():
    """
    Periodically clean old temp folders if disk usage exceeds MAX_DISK_USAGE_MB.
    """
    try:
        total_size = 0
        folder_stats = []
        for root, dirs, files in os.walk(TEMP_DIR):
            for f in files:
                total_size += os.path.getsize(os.path.join(root, f))
            for d in dirs:
                folder_path = os.path.join(root, d)
                folder_size = sum(
                    os.path.getsize(os.path.join(dp, file))
                    for dp, dn, filenames in os.walk(folder_path) for file in filenames
                )
                last_modified = os.path.getmtime(folder_path)
                folder_stats.append((folder_path, folder_size, last_modified))

        if total_size / (1024 * 1024) > MAX_DISK_USAGE_MB:
            logger.warning("Disk usage exceeded, purging old temp folders...")
            for folder_path, _, _ in sorted(folder_stats, key=lambda x: (x[2], x[1])):
                folder_uuid = os.path.basename(folder_path)
                with job_state_lock:
                    if folder_uuid in active_processing or folder_uuid in active_downloading:
                        continue
                shutil.rmtree(folder_path, ignore_errors=True)
                logger.info(f"Purged job folder: {folder_path}")
    except Exception as e:
        logger.error(f"Cleanup error: {e}")


def process_job(job_id, upload_path, filename, selected_stems):
    """
    Process an uploaded audio file:
    - Run Demucs splitting
    - Export previews
    - Zip selected stems
    - Update DB status
    - Schedule auto-cleanup
    """
    start_time = time.time()
    try:
        log(job_id, "Starting Demucs split...")

        demucs_dir = os.path.join(TEMP_DIR, job_id, "stems")
        preview_dir = os.path.join(TEMP_DIR, job_id, "preview")
        os.makedirs(preview_dir, exist_ok=True)
        base_name = os.path.splitext(filename)[0]
        zip_output_path = os.path.join(TEMP_DIR, job_id, f"{base_name}_stems.zip")

        # Decide between 2-stem vs 4-stem based on requested stems
        use_two_stems = sorted(selected_stems) == ["other", "vocals"]
        track_dir = split_audio(
            upload_path,
            output_dir=demucs_dir,
            stem_type="2stems" if use_two_stems else "all",
            job_id=job_id,
            logger=logger
        )

        # Remove unrequested stems
        all_possible_stems = {"vocals", "drums", "bass", "other", "no_vocals"}
        for stem in all_possible_stems:
            if stem == "no_vocals" and "other" in selected_stems:
                continue
            if stem not in selected_stems:
                file_path = os.path.join(track_dir, f"{stem}.wav")
                if os.path.exists(file_path):
                    os.remove(file_path)

        # Export previews (30s MP3s)
        for stem in selected_stems:
            src = os.path.join(track_dir, f"{stem}.wav")
            if stem == "other" and not os.path.exists(src):
                fallback = os.path.join(track_dir, "no_vocals.wav")
                if os.path.exists(fallback):
                    src = fallback
            if os.path.exists(src):
                dst_preview = os.path.join(preview_dir, f"{stem}.mp3")
                audio = AudioSegment.from_wav(src)
                export_opts = {"format": "mp3", "bitrate": "192k"}
                (audio[:30_000] if len(audio) > 30_000 else audio).export(dst_preview, **export_opts)

        # Create zip
        shutil.make_archive(zip_output_path.replace(".zip", ""), 'zip', track_dir)

        # Clean original upload + demucs folder
        try:
            os.remove(upload_path)
        except:
            pass
        shutil.rmtree(demucs_dir, ignore_errors=True)

        # Update DB
        conn = None
        try:
            conn = get_db_connection()
            c = conn.cursor()
            c.execute(
                "UPDATE jobs SET status = ?, zip_path = ? WHERE id = ?",
                ("done", zip_output_path, job_id)
            )
            conn.commit()
        except Exception as e:
            log(job_id, f"Failed to update job status: {e}")
        finally:
            if conn:
                conn.close()

        duration = time.time() - start_time
        log(job_id, f"Processing time: {duration:.2f} seconds")
        log(job_id, "Job complete. ZIP ready.")

        # Schedule auto-cleanup after JOB_EXPIRATION
        def auto_cleanup():
            time.sleep(JOB_EXPIRATION)
            folder = os.path.join(TEMP_DIR, job_id)
            shutil.rmtree(folder, ignore_errors=True)
            conn = None
            try:
                conn = get_db_connection()
                c = conn.cursor()
                c.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
                conn.commit()
                logger.info(f"[CLEANUP] Auto-deleted job {job_id}")
            except Exception as e:
                logger.error(f"[CLEANUP ERROR] Could not delete job {job_id}: {e}")
            finally:
                if conn:
                    conn.close()

        threading.Thread(target=auto_cleanup, daemon=True).start()

    except Exception as e:
        log(job_id, f"Error during processing: {e}")
        conn = None
        try:
            conn = get_db_connection()
            c = conn.cursor()
            c.execute(
                "UPDATE jobs SET status = ?, zip_path = NULL WHERE id = ?",
                ("error", job_id)
            )
            conn.commit()
        except Exception as db_e:
            logger.error(f"Failed to update job error status: {db_e}")
        finally:
            if conn:
                conn.close()
    finally:
        # Mark job finished
        with job_state_lock:
            active_processing.discard(job_id)


def is_rate_limited(ip):
    """
    Apply per-IP rate limiting:
    - Track uploads per minute
    - Limit simultaneous jobs in DB
    """
    now = time.time()
    window = 60
    max_uploads = MAX_UPLOADS_PER_MIN

    with upload_history_lock:
        history = UPLOAD_HISTORY[ip]
        while history and now - history[0] > window:
            history.popleft()

        if len(history) >= max_uploads:
            return f"Upload rate limit exceeded ({max_uploads} per {window}s)."

        history.append(now)

    # Also check active jobs in DB
    conn = None
    try:
        conn = get_db_connection()
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM jobs WHERE ip = ? AND status = 'processing'", (ip,))
        active_jobs = c.fetchone()[0]

        if active_jobs >= MAX_JOBS_PER_IP:
            return f"Too many jobs processing (limit: {MAX_JOBS_PER_IP})."
    except Exception as e:
        logger.error(f"Rate limit DB check failed: {e}")
        return None
    finally:
        if conn:
            conn.close()

    return None


def preview_cleanup_loop():
    """
    Background loop:
    - Runs every hour
    - Deletes previews older than 1 hour
    - Frees space in TEMP_DIR
    """
    while True:
        time.sleep(3600)  # Run once per hour
        try:
            for job_id in os.listdir(TEMP_DIR):
                preview_dir = os.path.join(TEMP_DIR, job_id, "preview")
                if not os.path.exists(preview_dir):
                    continue
                age = time.time() - os.path.getmtime(preview_dir)
                if age > 3600:  # 1 hour old
                    shutil.rmtree(os.path.join(TEMP_DIR, job_id), ignore_errors=True)
                    logger.info(f"[CLEANUP] Removed expired preview: {job_id}")
        except Exception as e:
            logger.error(f"[CLEANUP] Error during preview cleanup: {e}")

