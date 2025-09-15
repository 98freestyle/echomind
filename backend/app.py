"""
EchoMind Backend (Flask)

Handles audio uploads, Demucs splitting jobs, previews, downloads,
authentication, usage tracking, and premium subscription integration.
"""

import sys
import os, shutil, uuid, time, threading, subprocess, logging, mimetypes, sqlite3, secrets, stripe, pytz
from flask import Flask, request, send_file, Response, jsonify, make_response, redirect, send_from_directory
from flask_cors import CORS, cross_origin
from pydub import AudioSegment
from pydub.utils import mediainfo
from pathlib import Path
from audio_splitter import split_audio
from dotenv import load_dotenv
from werkzeug.exceptions import RequestEntityTooLarge
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from disposable_email_domains import blocklist
from utils.email_utils import send_email
from zoneinfo import ZoneInfo


# ============================================================
# Config & Setup
# ============================================================

UTC = timezone.utc
app = Flask(__name__)

# CORS
cors_origins = os.getenv("CORS_ORIGINS", "").split(",")
CORS(app, supports_credentials=True, origins=cors_origins)

# Load environment variables
load_dotenv()

# Limits & config
MAX_CONTENT_LENGTH_MB = int(os.getenv("MAX_CONTENT_LENGTH_MB", 100))
MAX_CONTENT_LENGTH = MAX_CONTENT_LENGTH_MB * 1024 * 1024
MAX_DISK_USAGE_MB = int(os.getenv("MAX_DISK_USAGE_MB", 1000))
MAX_JOBS_PER_IP = int(os.getenv("MAX_JOBS_PER_IP", 2))
MAX_UPLOADS_PER_MIN = int(os.getenv("MAX_UPLOADS_PER_MIN", 5))
TEMP_DIR = os.getenv("TEMP_DIR", "temp")
LOG_FILE = os.getenv("LOG_FILE", "logs/app.log")
JOB_EXPIRATION = int(os.getenv("JOB_EXPIRATION", 300))  # seconds
BASE_URL = os.getenv("BASE_URL", "http://127.0.0.1:5000")
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:5173")
ADMIN_TOKEN = os.getenv("ADMIN_TOKEN")

# Stripe
stripe.api_key = os.getenv("STRIPE_SECRET_KEY")

# Allowed file types
ALLOWED_EXTENSIONS = {".mp3", ".wav", ".flac", ".m4a", ".aac", ".ogg", ".aiff", ".mp4"}

# App config
app.config["MAX_CONTENT_LENGTH"] = MAX_CONTENT_LENGTH
os.makedirs(TEMP_DIR, exist_ok=True)
os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)

# Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s]: %(message)s",
    handlers=[logging.FileHandler(LOG_FILE), logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

# State tracking
UPLOAD_HISTORY = defaultdict(lambda: deque())
active_processing = set()
active_downloading = set()
upload_history_lock = threading.Lock()
job_state_lock = threading.Lock()   # Protects active_processing / active_downloading


# ============================================================
# Helper Functions
# ============================================================

def get_db_connection():
    """
    Return a SQLite connection to the users.db file.
    Row factory is set to return dict-like rows.
    """
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    db_path = os.path.join(BASE_DIR, "db", "users.db")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def get_client_ip():
    """
    Extract real client IP from proxy headers or REMOTE_ADDR fallback.
    """
    try:
        cf = request.headers.get("CF-Connecting-IP")
        if cf:
            return cf.strip()

        xff = request.headers.get("X-Forwarded-For")
        if xff:
            return xff.split(",")[0].strip()

        xri = request.headers.get("X-Real-IP")
        if xri:
            return xri.strip()
    except Exception as e:
        logger.error(f"Failed to read IP headers: {e}")

    ip = request.environ.get("REMOTE_ADDR", "")
    if ip.startswith("::ffff:"):
        ip = ip.split("::ffff:")[-1]
    return ip


def allowed_file(filename):
    """Check if a file extension is allowed for upload."""
    return filename and Path(filename).suffix.lower() in ALLOWED_EXTENSIONS


def log(job_id, msg):
    """Log a message tied to a specific job ID."""
    logger.info(f"[{job_id}] {msg}")


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


# ============================================================
# Job Processing
# ============================================================

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
        # 🔒 mark job finished
        with job_state_lock:
            active_processing.discard(job_id)




# ============================================================
# Rate Limiting
# ============================================================

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


# ============================================================
# Job Routes
# ============================================================

@app.route("/upload", methods=["POST"])
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
    logger.debug(f"Client IP: {ip}")   # switched from print → logger
    rate_limit_msg = is_rate_limited(ip)
    if rate_limit_msg:
        return jsonify({"error": rate_limit_msg}), 429

    # Inspect size
    file.seek(0, os.SEEK_END)
    file_size_mb = round(file.tell() / (1024 * 1024), 2)
    file.seek(0)

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

    # Extract audio from MP4 → WAV
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





# ============================================================
# Job Streaming & Downloads
# ============================================================

@app.route("/stream/<job_id>")
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


@app.route("/download-link/<job_id>")
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


@app.route("/download-direct/<job_id>/<filename>")
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


@app.route("/preview/<job_id>/<stem>")
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




# ============================================================
# Authentication & Account Routes
# ============================================================

@app.route("/signup", methods=["POST"])
def signup():
    """
    Create a new user:
    - Validate email/password
    - Block disposable domains
    - Insert user (unverified)
    - Send email verification link
    """
    data = request.get_json()
    email = data.get("email")
    password = data.get("password")

    if not email or not password:
        return jsonify({"error": "All fields are required."}), 400

    # Block disposable email domains
    domain = email.split("@")[-1]
    if domain in blocklist:
        return jsonify({"error": "Disposable email addresses are not allowed."}), 400

    conn = None
    try:
        conn = get_db_connection()
        c = conn.cursor()

        ip = get_client_ip()
        c.execute("""
            SELECT * FROM signup_attempts
            WHERE ip_address = ? AND attempted_at >= datetime('now', '-7 days')
        """, (ip,))

        if c.fetchone():
            return jsonify({"error": "Too many signups from this IP. Try again in 7 days."}), 429


        # Ensure email not already taken
        c.execute("SELECT * FROM users WHERE email = ?", (email,))
        if c.fetchone():
            return jsonify({"error": "Email already in use."}), 409

        # Insert unverified user
        hashed_pw = generate_password_hash(password)
        c.execute("INSERT INTO users (email, password, is_verified) VALUES (?, ?, 0)", (email, hashed_pw))
        user_id = c.lastrowid

        # Record signup attempt
        c.execute("INSERT INTO signup_attempts (ip_address, attempted_at) VALUES (?, datetime('now'))", (ip,))

        # Create email verification token
        token = secrets.token_urlsafe(32)
        expires_at = (datetime.now(UTC) + timedelta(hours=24)).isoformat()
        c.execute(
            "INSERT INTO verification_tokens (user_id, token, expires_at, used) VALUES (?, ?, ?, 0)",
            (user_id, token, expires_at)
        )

        conn.commit()

        # Send verification email
        verify_link = f"{BASE_URL}/verify-email?token={token}"
        html_body = f"""
        <h3>Welcome to EchoMind</h3>
        <p>Click below to verify your EchoMind account:</p>
        <a href="{verify_link}">Verify Email</a>
        """
        send_email(email, "Verify your EchoMind account", html_body)

        return jsonify({"user": email, "verified": False}), 200
    except Exception as e:
        logger.error(f"Signup error: {e}")
        return jsonify({"error": "Server error during signup."}), 500
    finally:
        if conn:
            conn.close()


@app.route("/login", methods=["POST"])
@cross_origin()
def login():
    """
    Authenticate user:
    - Check credentials
    - Enforce email verification
    """
    data = request.json
    email = data.get("email")
    password = data.get("password")

    if not email or not password:
        return jsonify({"error": "Email and password required."}), 400

    conn = None
    try:
        conn = get_db_connection()
        c = conn.cursor()
        c.execute("SELECT password, is_verified FROM users WHERE email = ?", (email,))
        result = c.fetchone()

        if not result:
            return jsonify({"error": "Invalid credentials."}), 401

        stored_pw, is_verified = result
        if not check_password_hash(stored_pw, password):
            return jsonify({"error": "Invalid credentials."}), 401
        if not is_verified:
            return jsonify({"error": "Please verify your email before logging in."}), 403

        return jsonify({"success": True}), 200
    except Exception as e:
        logger.error(f"Login error: {e}")
        return jsonify({"error": f"Server error: {str(e)}"}), 500
    finally:
        if conn:
            conn.close()


@app.route("/job-history", methods=["GET"])
@cross_origin()
def job_history():
    """
    Return last 10 jobs for a given user.
    Requires `X-User-Email` header.
    """
    email = request.headers.get("X-User-Email")
    if not email:
        return jsonify({"error": "Email required"}), 400

    conn = None
    try:
        conn = get_db_connection()
        c = conn.cursor()
        c.execute("SELECT id FROM users WHERE email = ?", (email,))
        user = c.fetchone()
        if not user:
            return jsonify({"error": "User not found"}), 404

        user_id = user["id"]
        c.execute("""
            SELECT date, filename, stems, duration_min
            FROM usage
            WHERE user_id = ?
            ORDER BY id DESC
            LIMIT 10
        """, (user_id,))
        rows = c.fetchall()

        history = [{
            "date": row["date"],
            "filename": row["filename"],
            "stems": row["stems"],
            "duration": round(row["duration_min"], 2)
        } for row in rows]

        return jsonify(history)
    except Exception as e:
        logger.error(f"Job history error: {e}")
        return jsonify({"error": "Server error"}), 500
    finally:
        if conn:
            conn.close()


@app.route("/verify-email", methods=["GET"])
@cross_origin()
def verify_email():
    """
    Verify email with token from signup link.
    Marks user as verified and token as used.
    """
    token = request.args.get("token")
    conn = None
    try:
        conn = get_db_connection()
        c = conn.cursor()

        # Fetch token
        c.execute("SELECT user_id, expires_at, used FROM verification_tokens WHERE token = ?", (token,))
        result = c.fetchone()
        if not result:
            return jsonify({"error": "Invalid or expired token."}), 400

        user_id, expires_at, used = result
        if used:
            return jsonify({"error": "This token has already been used."}), 400
        if datetime.now(UTC) > datetime.fromisoformat(expires_at):
            return jsonify({"error": "Token has expired."}), 400

        # Mark user verified + token used
        c.execute("UPDATE users SET is_verified = 1 WHERE id = ?", (user_id,))
        c.execute("UPDATE verification_tokens SET used = 1 WHERE token = ?", (token,))
        conn.commit()

        return redirect(f"{FRONTEND_URL}/verified")
    except Exception as e:
        logger.error(f"Verify email error: {e}")
        return jsonify({"error": f"Server error: {str(e)}"}), 500
    finally:
        if conn:
            conn.close()

# ============================================================
# Support / Contact
# ============================================================

@app.route("/support-request", methods=["POST"])
def support_request():
    """
    Handle support contact form submissions from frontend.
    - Accepts name, email, and message
    - Logs the request
    - Sends to support inbox
    """
    data = request.get_json() or {}
    name = data.get("name", "").strip()
    email = data.get("email", "").strip()
    message = data.get("message", "").strip()

    if not name or not email or not message:
        return jsonify({"error": "All fields are required."}), 400

    logger.info(f"[SUPPORT] {name} <{email}>: {message}")

    # Construct HTML email body
    html_body = f"""
    <h3>New Support Request</h3>
    <p><strong>Name:</strong> {name}</p>
    <p><strong>Email:</strong> {email}</p>
    <p><strong>Message:</strong></p>
    <p>{message}</p>
    """

    try:
        send_email("support@echomind.cloud", f"Support request from {name}", html_body)
        return jsonify({"success": True, "message": "Your request has been sent. We'll get back to you shortly."})
    except Exception as e:
        logger.error(f"Support request email error: {e}")
        return jsonify({"error": "Failed to send support request."}), 500

    
# ============================================================
# Password Reset
# ============================================================

@app.route("/reset-password-request", methods=["POST"])
def reset_password_request():
    """
    Start password reset flow:
    - Validate email
    - Require verified account
    - Insert reset token (1hr expiry)
    - Send reset link via email
    """
    data = request.get_json()
    email = data.get("email")

    if not email:
        return jsonify({"error": "Email is required."}), 400

    conn = None
    try:
        conn = get_db_connection()
        c = conn.cursor()

        # Ensure user exists & verified
        c.execute("SELECT id, is_verified FROM users WHERE email = ?", (email,))
        user = c.fetchone()
        if not user:
            return jsonify({"error": "Email not found."}), 404
        if user["is_verified"] == 0:
            return jsonify({"error": "Please verify your email before resetting password."}), 403

        user_id = user["id"]

        # Create reset token
        token = secrets.token_urlsafe(32)
        expires_at = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
        c.execute(
            "INSERT INTO password_reset_tokens (user_id, token, expires_at, used) VALUES (?, ?, ?, 0)",
            (user_id, token, expires_at)
        )
        conn.commit()

        # Send reset email
        reset_link = f"{BASE_URL}/reset-password-confirm/{token}"
        html_body = f"""
        <h3>Password Reset Requested</h3>
        <p>If you didn't request this, ignore it. Otherwise click below to reset your password:</p>
        <a href="{reset_link}">Reset Password</a>
        """
        send_email(email, "Reset your EchoMind password", html_body)

        return jsonify({"message": "Password reset link sent to your email.", "success": True}), 200
    except Exception as e:
        logger.error(f"Reset password request error: {e}")
        return jsonify({"error": "Server error during password reset."}), 500
    finally:
        if conn:
            conn.close()


@app.route("/reset-password-confirm/<token>", methods=["POST"])
def reset_password(token):
    """
    Complete password reset:
    - Validate token
    - Ensure new password is valid & different
    - Update password, mark token used
    """
    data = request.get_json()
    new_password = data.get("new_password")

    if not new_password or len(new_password) < 6:
        return jsonify({"error": "Password must be at least 6 characters."}), 400

    conn = None
    try:
        conn = get_db_connection()
        c = conn.cursor()

        # Fetch reset token
        c.execute("""
            SELECT prt.id, prt.user_id, prt.expires_at, prt.used
            FROM password_reset_tokens prt
            WHERE prt.token = ?
        """, (token,))
        record = c.fetchone()
        if not record:
            return jsonify({"error": "Invalid or expired token."}), 400
        if record["used"]:
            return jsonify({"error": "This reset link has already been used."}), 400
        if datetime.now(UTC) > datetime.fromisoformat(record["expires_at"]):
            return jsonify({"error": "This reset link has expired."}), 400

        # Prevent reusing same password
        c.execute("SELECT password FROM users WHERE id = ?", (record["user_id"],))
        current_pw_hash = c.fetchone()["password"]
        if check_password_hash(current_pw_hash, new_password):
            return jsonify({"error": "New password must be different from the current one."}), 400

        # Update password + mark token used
        hashed_pw = generate_password_hash(new_password)
        c.execute("UPDATE users SET password = ? WHERE id = ?", (hashed_pw, record["user_id"]))
        c.execute("UPDATE password_reset_tokens SET used = 1 WHERE id = ?", (record["id"],))
        conn.commit()

        return jsonify({"success": True, "message": "Password reset successful."}), 200
    except Exception as e:
        logger.error(f"Reset password confirm error: {e}")
        return jsonify({"error": "Server error during password reset."}), 500
    finally:
        if conn:
            conn.close()




    
# ============================================================
# Usage Tracking
# ============================================================

def get_guest_weekly_usage(ip):
    """
    Calculate total minutes processed this week for a guest (IP-based).
    """
    conn = None
    try:
        conn = get_db_connection()
        c = conn.cursor()

        now = datetime.now(ZoneInfo("Australia/Sydney"))
        start_of_week = now.date() - timedelta(days=now.weekday())
        start_of_week_str = start_of_week.isoformat()

        c.execute("""
            SELECT SUM(duration_min) FROM usage
            WHERE ip = ? AND user_id IS NULL AND date >= ?
        """, (ip, start_of_week_str))

        result = c.fetchone()[0]
        return result or 0
    except Exception as e:
        logger.error(f"Failed to fetch guest usage: {e}")
        return 0
    finally:
        if conn:
            conn.close()


def get_account_weekly_usage(user_id):
    """
    Calculate total minutes processed this week for a registered user.
    Premium users get higher limits.
    """
    conn = None
    try:
        conn = get_db_connection()
        c = conn.cursor()

        now = datetime.now(ZoneInfo("Australia/Sydney"))
        start_of_week = now.date() - timedelta(days=now.weekday())
        start_of_week_str = start_of_week.isoformat()

        # Check premium status
        c.execute("SELECT is_premium FROM users WHERE id = ?", (user_id,))
        is_premium = c.fetchone()
        is_premium = is_premium[0] if is_premium else 0

        # Get minutes used
        c.execute("""
            SELECT SUM(duration_min) FROM usage
            WHERE user_id = ? AND date >= ?
        """, (user_id, start_of_week_str))
        used = c.fetchone()[0] or 0

        limit = 120 if is_premium else 30
        return used, limit
    except Exception as e:
        logger.error(f"Failed to fetch account usage: {e}")
        return 0, 30
    finally:
        if conn:
            conn.close()


@app.route("/usage", methods=["GET"])
@cross_origin()
def usage():
    """
    Return weekly usage for current user (or guest by IP).
    Response: { used_min, limit_min, is_premium }
    """
    ip = get_client_ip()
    email = request.headers.get("X-User-Email")
    is_guest = True
    user_id = None
    limit = 10  # default guest cap
    used = 0

    conn = None
    try:
        conn = get_db_connection()
        c = conn.cursor()

        start_of_week = datetime.now(UTC).date() - timedelta(days=datetime.now(UTC).weekday())
        start_of_week_str = start_of_week.isoformat()

        if email:
            c.execute("SELECT id FROM users WHERE email = ?", (email,))
            result = c.fetchone()
            if result:
                user_id = result[0]
                is_guest = False

        if is_guest:
            # Guest usage (IP-based)
            c.execute("""
                SELECT SUM(duration_min) FROM usage
                WHERE ip = ? AND user_id IS NULL AND date >= ?
            """, (ip, start_of_week_str))
            used = c.fetchone()[0] or 0
            limit = 10
            is_premium = False
        else:
            # Account usage
            c.execute("SELECT id, is_premium FROM users WHERE email = ?", (email,))
            result = c.fetchone()
            if result:
                user_id, is_premium = result
                limit = 120 if is_premium else 30
                c.execute("""
                    SELECT SUM(duration_min) FROM usage
                    WHERE user_id = ? AND date >= ?
                """, (user_id, start_of_week_str))
                used = c.fetchone()[0] or 0
            else:
                used = 0
                limit = 30
                is_premium = False

        return jsonify({
            "used_min": round(used, 2),
            "limit_min": limit,
            "is_premium": bool(is_premium) if not is_guest else False
        })
    except Exception as e:
        logger.error(f"Usage fetch error: {e}")
        return jsonify({"error": "Failed to fetch usage"}), 500
    finally:
        if conn:
            conn.close()


# ============================================================
# Premium / Stripe Integration
# ============================================================


@app.route("/promote-to-premium", methods=["POST"])
@cross_origin()
def promote_to_premium():
    """
    Manually promote a user to premium (admin-only via token).
    """
    # --- Admin token check ---
    token = request.headers.get("X-ADMIN-TOKEN")
    if token != ADMIN_TOKEN:
        return jsonify({"error": "Unauthorized"}), 403

    # --- Extract email ---
    data = request.get_json()
    email = data.get("email")
    if not email:
        return jsonify({"error": "Email is required."}), 400

    conn = None
    try:
        conn = get_db_connection()
        c = conn.cursor()

        # --- Check if user exists ---
        c.execute("SELECT is_premium FROM users WHERE email = ?", (email,))
        result = c.fetchone()
        if not result:
            return jsonify({"error": "User not found."}), 404
        if result[0] == 1:
            return jsonify({"message": f"{email} is already a premium user."}), 200

        # --- Promote user ---
        c.execute("UPDATE users SET is_premium = 1 WHERE email = ?", (email,))
        conn.commit()
        return jsonify({"success": True, "message": f"{email} promoted to premium."}), 200

    except Exception as e:
        logger.error(f"Promote to premium error: {e}")
        return jsonify({"error": f"Server error: {str(e)}"}), 500

    finally:
        if conn:
            conn.close()

@app.route("/create-checkout-session", methods=["POST"])
@cross_origin()
def create_checkout_session():
    """
    Create a Stripe Checkout session for one-time premium upgrade.
    """
    try:
        data = request.get_json()
        email = data.get("email")
        if not email:
            return jsonify({"error": "Email required"}), 400

        session = stripe.checkout.Session.create(
            payment_method_types=["card"],
            line_items=[{
                "price": os.getenv("STRIPE_PRICE_ID"),
                "quantity": 1,
            }],
            mode="payment",
            customer_email=email,
            success_url=f"{FRONTEND_URL}/premium-success?session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url=f"{FRONTEND_URL}/premium-cancelled",
        )
        return jsonify({"url": session.url})
    except Exception as e:
        logger.error(f"Create checkout session error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/webhook", methods=["POST"])
def stripe_webhook():
    """
    Handle Stripe webhook events (checkout.session.completed).
    Promotes user to premium and sends confirmation email.
    """
    payload = request.data
    sig_header = request.headers.get("stripe-signature")
    endpoint_secret = os.getenv("STRIPE_WEBHOOK_SECRET")

    try:
        event = stripe.Webhook.construct_event(payload, sig_header, endpoint_secret)
    except ValueError:
        return jsonify(success=False, error="Invalid payload"), 400
    except stripe.error.SignatureVerificationError:
        return jsonify(success=False, error="Invalid signature"), 400

    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]
        email = session.get("customer_email")

        if email:
            conn = None
            try:
                conn = get_db_connection()
                c = conn.cursor()
                c.execute("UPDATE users SET is_premium = 1 WHERE email = ?", (email,))
                conn.commit()

                # Send welcome email
                html_body = f"""
                <h3>Welcome to EchoMind Premium</h3>
                <p>Hi {email},</p>
                <p>Your premium upgrade was successful. You now have access to:</p>
                <ul>
                  <li>Higher upload limits</li>
                  <li>Faster splitting</li>
                  <li>Priority feature access</li>
                </ul>
                <p>Enjoy and thank you for supporting EchoMind.</p>
                """
                send_email(email, "You're now Premium on EchoMind", html_body)
            except Exception as e:
                logger.error(f"Webhook user promotion error: {e}")
            finally:
                if conn:
                    conn.close()

    return jsonify(success=True), 200


@app.route("/validate-session", methods=["POST"])
def validate_session():
    """
    Validate Stripe checkout session by session_id.
    Marks user premium if not already.
    """
    data = request.get_json() or {}
    session_id = data.get("session_id")
    if not session_id:
        return jsonify({"error": "session_id required"}), 400

    conn = None
    try:
        session = stripe.checkout.Session.retrieve(session_id)
        email = session.get("customer_email")
        if not email:
            return jsonify({"error": "No email on session"}), 400

        conn = get_db_connection()
        c = conn.cursor()
        c.execute("UPDATE users SET is_premium = 1 WHERE email = ?", (email,))
        conn.commit()

        return jsonify({"success": True, "email": email}), 200
    except Exception as e:
        logger.error(f"Validate session error: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        if conn:
            conn.close()
    
# ============================================================
# Background Cleanup
# ============================================================

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


# ============================================================
# Error Handlers
# ============================================================

@app.errorhandler(RequestEntityTooLarge)
def handle_large_file(e):
    """Handle Flask max-content-length errors (upload too large)."""
    return jsonify({"error": f"File too large. Max {MAX_CONTENT_LENGTH_MB}MB."}), 413


@app.errorhandler(Exception)
def handle_exception(e):
    """Catch-all error handler for uncaught exceptions."""
    logger.error(f"Unhandled error: {e}")
    return jsonify({"error": "Internal server error."}), 500


@app.errorhandler(413)
def handle_413(e):
    """Extra handler for HTTP 413 (payload too large)."""
    return jsonify({"error": "File too large. Max allowed is 200MB."}), 413


# ============================================================
# Startup Tasks
# ============================================================

def run_once_on_master():
    """
    Run only once per Gunicorn master process:
    - Cleanup old TEMP_DIR files
    - Start background preview cleanup loop
    """
    if os.getenv("RUN_MAIN") == "true":  # Gunicorn master only
        startup_cleanup()
        threading.Thread(target=preview_cleanup_loop, daemon=True).start()


run_once_on_master()


# ============================================================
# Frontend Serving
# ============================================================

@app.route("/", defaults={"path": ""})
@app.route("/<path:path>")
def serve_react(path):
    """
    Serve React frontend from built dist folder.
    Falls back to index.html for unknown paths.
    """
    from flask import send_from_directory
    base_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "frontend", "dist"))
    if path != "" and os.path.exists(os.path.join(base_path, path)):
        return send_from_directory(base_path, path)
    else:
        return send_from_directory(base_path, "index.html")


# ============================================================
# Session / Cookie Settings
# ============================================================

app.config['SESSION_COOKIE_SAMESITE'] = 'None'
app.config['SESSION_COOKIE_SECURE'] = os.getenv("COOKIE_SECURE", "true").lower() == "true"


# ============================================================
# Local Run (Dev only)
# ============================================================

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)