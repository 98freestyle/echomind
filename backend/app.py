import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')

import os, shutil, uuid, time, threading, subprocess, queue, logging, mimetypes, sqlite3, bcrypt, secrets, stripe, pytz
from flask import Flask, request, send_file, render_template, Response, jsonify, make_response, redirect, send_from_directory
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
from datetime import datetime, timedelta
from disposable_email_domains import blocklist
from datetime import datetime, timedelta
from utils.email_utils import send_email
from zoneinfo import ZoneInfo


app = Flask(__name__)
aest = datetime.now(pytz.timezone("Australia/Sydney")).date()
cors_origins = os.getenv("CORS_ORIGINS", "").split(",")
CORS(app, supports_credentials=True, origins=cors_origins)


load_dotenv()
def get_env_int(name, default):
    try:
        return int(os.getenv(name, default))
    except:
        return default
    
MAX_CONTENT_LENGTH_MB = int(os.getenv("MAX_CONTENT_LENGTH", 100))
MAX_CONTENT_LENGTH = MAX_CONTENT_LENGTH_MB * 1024 * 1024
MAX_DISK_USAGE_MB = int(os.getenv("MAX_DISK_USAGE_MB", 1000))
MAX_JOBS_PER_IP = int(os.getenv("MAX_JOBS_PER_IP", 2))
MAX_UPLOADS_PER_MIN = int(os.getenv("MAX_UPLOADS_PER_MIN", 5))
TEMP_DIR = os.getenv("TEMP_DIR", "temp")
LOG_FILE = os.getenv("LOG_FILE", "logs/app.log")
JOB_EXPIRATION = int(os.getenv("JOB_EXPIRATION", 300))  # fallback 5 min
BASE_URL = os.getenv("BASE_URL", "http://127.0.0.1:5000")
stripe.api_key = os.getenv("STRIPE_SECRET_KEY")
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:5173")



ALLOWED_EXTENSIONS = {".mp3", ".wav", ".flac", ".m4a", ".aac", ".ogg", ".aiff", ".mp4"}

app.config["MAX_CONTENT_LENGTH"] = MAX_CONTENT_LENGTH_MB * 1024 * 1024
os.makedirs(TEMP_DIR, exist_ok=True)
os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s]: %(message)s",
                    handlers=[logging.FileHandler(LOG_FILE), logging.StreamHandler()])
logger = logging.getLogger(__name__)

JOBS = {}
UPLOAD_HISTORY = defaultdict(lambda: deque())
active_processing = set()
active_downloading = set()
jobs_lock = threading.Lock()



def get_db_connection():
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    db_path = os.path.join(BASE_DIR, "db", "users.db")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn

def get_client_ip():
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
        print("Failed to read IP headers:", e)

    ip = request.environ.get("REMOTE_ADDR", "")
    if ip.startswith("::ffff:"):
        ip = ip.split("::ffff:")[-1]
    return ip

def allowed_file(filename):
    return filename and Path(filename).suffix.lower() in ALLOWED_EXTENSIONS

def log(job_id, msg):
    logger.info(f"[{job_id}] {msg}")
    if job_id in JOBS:
        JOBS[job_id]["events"].put(msg)

def startup_cleanup():
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
    try:
        total_size = 0
        folder_stats = []
        for root, dirs, files in os.walk(TEMP_DIR):
            for f in files:
                total_size += os.path.getsize(os.path.join(root, f))
            for d in dirs:
                folder_path = os.path.join(root, d)
                folder_size = sum(os.path.getsize(os.path.join(dp, file))
                                  for dp, dn, filenames in os.walk(folder_path) for file in filenames)
                last_modified = os.path.getmtime(folder_path)
                folder_stats.append((folder_path, folder_size, last_modified))

        if total_size / (1024 * 1024) > MAX_DISK_USAGE_MB:
            logger.warning("Disk usage exceeded, purging old temp folders...")
            for folder_path, _, _ in sorted(folder_stats, key=lambda x: (x[2], x[1])):
                folder_uuid = os.path.basename(folder_path)
                if folder_uuid in active_processing or folder_uuid in active_downloading:
                    continue
                shutil.rmtree(folder_path, ignore_errors=True)
                logger.info(f"Purged job folder: {folder_path}")
    except Exception as e:
        logger.error(f"Cleanup error: {e}")

def process_job(job_id, upload_path, filename, selected_stems):
    start_time = time.time()
    try:
        log(job_id, "Starting Demucs split...")

        demucs_dir = os.path.join(TEMP_DIR, job_id, "stems")
        preview_dir = os.path.join(TEMP_DIR, job_id, "preview")
        os.makedirs(preview_dir, exist_ok=True)
        base_name = os.path.splitext(filename)[0]
        zip_output_path = os.path.join(TEMP_DIR, job_id, f"{base_name}_stems.zip")

        use_two_stems = sorted(selected_stems) == ["other", "vocals"]
        track_dir = split_audio(
            upload_path,
            output_dir=demucs_dir,
            stem_type="2stems" if use_two_stems else "all",
            job_id=job_id,
            logger=logger
        )

        all_possible_stems = {"vocals", "drums", "bass", "other", "no_vocals"}
        for stem in all_possible_stems:
            if stem == "no_vocals":
                if "other" in selected_stems:
                    continue
            elif stem not in selected_stems:
                file_path = os.path.join(track_dir, f"{stem}.wav")
                if os.path.exists(file_path):
                    os.remove(file_path)

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
                if len(audio) > 30_000:
                    audio[:30_000].export(dst_preview, **export_opts)
                else:
                    audio.export(dst_preview, **export_opts)

        shutil.make_archive(zip_output_path.replace(".zip", ""), 'zip', track_dir)

        try:
            os.remove(upload_path)
        except Exception:
            pass
        shutil.rmtree(demucs_dir, ignore_errors=True)

        with jobs_lock:
            JOBS[job_id]["status"] = "done"
            JOBS[job_id]["zip"] = zip_output_path

        duration = time.time() - start_time
        log(job_id, f"Processing time: {duration:.2f} seconds")
        log(job_id, "Job complete. ZIP ready.")
        JOBS[job_id]["events"].put("Job complete")

        def auto_cleanup():
            time.sleep(JOB_EXPIRATION)
            with jobs_lock:
                if job_id in JOBS and JOBS[job_id]["status"] == "done":
                    folder = os.path.join(TEMP_DIR, job_id)
                    shutil.rmtree(folder, ignore_errors=True)
                    JOBS.pop(job_id, None)
                    logger.info(f"[CLEANUP] Auto-deleted job {job_id}")

        threading.Thread(target=auto_cleanup, daemon=True).start()

    except Exception as e:
        with jobs_lock:
            if job_id in JOBS:
                JOBS[job_id]["status"] = "error"
                JOBS[job_id]["zip"] = None
        log(job_id, f"Error: {e}")
    finally:
        active_processing.discard(job_id)



def is_rate_limited(ip):
    now = time.time()
    window = 60
    max_uploads = MAX_UPLOADS_PER_MIN

    with jobs_lock:
        history = UPLOAD_HISTORY[ip]

        # Remove expired timestamps
        while history and now - history[0] > window:
            history.popleft()

        # ✅ BLOCK if over frequency limit
        if len(history) >= max_uploads:
            return f"Upload rate limit exceeded ({max_uploads} per {window}s)."

        # ✅ Count this attempt no matter what
        history.append(now)

        # ✅ Then check active jobs
        active_jobs = sum(
            1 for job in JOBS.values()
            if job.get("ip") == ip and job.get("status") == "processing"
        )
        if active_jobs >= MAX_JOBS_PER_IP:
            return f"Too many jobs processing (limit: {MAX_JOBS_PER_IP})."

    return None

@app.route("/upload", methods=["POST"])
@cross_origin()
def upload():
    cleanup_old_temp()

    if "file" not in request.files:
        return jsonify({"error": "No file uploaded."}), 400

    file = request.files["file"]
    filename = secure_filename(file.filename)
    if not filename or not allowed_file(filename):
        return jsonify({"error": "Unsupported file type."}), 400

    # ✅ Only now is it safe to access headers
    ip = get_client_ip()
    print(f"👀 Client IP: {ip}")
    rate_limit_msg = is_rate_limited(ip)
    if rate_limit_msg:
        return jsonify({"error": rate_limit_msg}), 429

    # 👇 Calculate file size
    file.seek(0, os.SEEK_END)
    file_size_mb = round(file.tell() / (1024 * 1024), 2)
    file.seek(0)

    # 👇 Check account status
    email = request.headers.get("X-User-Email")
    user_id = None
    is_guest = True
    is_premium = False
    db_path = os.path.join(os.path.dirname(__file__), "db", "users.db")

    if email:
        try:
            conn = sqlite3.connect(db_path)
            c = conn.cursor()
            c.execute("SELECT id, is_premium FROM users WHERE email = ?", (email,))
            result = c.fetchone()
            if result:
                user_id, is_premium_flag = result
                is_guest = False
                is_premium = bool(is_premium_flag)
        except Exception as e:
            print("Failed to look up user:", e)
        finally:
            if conn:
                conn.close()

    # 👇 Usage check
    if is_guest:
        weekly_usage = get_guest_weekly_usage(ip)
        cap = 150
    else:
        weekly_usage, cap = get_account_weekly_usage(user_id)

    if weekly_usage + file_size_mb > cap:
        return jsonify({
            "error": f"Weekly limit exceeded ({cap}MB max). You’ve used {round(weekly_usage, 2)}MB."
        }), 403

    selected_stems = request.form.getlist("stems") or ["vocals", "other"]
    job_id = str(uuid.uuid4())
    active_processing.add(job_id)

    temp_upload_dir = os.path.join(TEMP_DIR, job_id)
    os.makedirs(temp_upload_dir, exist_ok=True)
    upload_path = os.path.join(temp_upload_dir, filename)
    file.save(upload_path)

    try:
        duration = float(mediainfo(upload_path).get("duration", "0"))
        if duration <= 0:
            raise ValueError("No valid audio stream")
        if duration > 600:
            raise ValueError("File too long")
    except Exception:
        shutil.rmtree(temp_upload_dir, ignore_errors=True)
        active_processing.discard(job_id)
        return jsonify({"error": "Invalid or corrupted audio file."}), 400

    if Path(filename).suffix.lower() == ".mp4":
        wav_path = os.path.join(temp_upload_dir, f"{Path(filename).stem}.wav")
        cmd = ["ffmpeg", "-i", upload_path, "-vn", "-acodec", "pcm_s16le", wav_path, "-y"]
        log(job_id, f"Extracting audio from MP4: {' '.join(cmd)}")
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if result.returncode != 0 or not os.path.exists(wav_path) or os.path.getsize(wav_path) < 4096:
            shutil.rmtree(temp_upload_dir, ignore_errors=True)
            active_processing.discard(job_id)
            return jsonify({"error": "Invalid or corrupted audio file."}), 400
        upload_path = wav_path
        log(job_id, "Extracted audio from MP4.")

    # 👇 Log usage to DB
    try:
        conn = sqlite3.connect(db_path)
        c = conn.cursor()
        upload_date = time.strftime("%Y-%m-%d")
        c.execute(
            "INSERT INTO usage (user_id, ip, date, mb_used, filename, stems) VALUES (?, ?, ?, ?, ?, ?)",
            (user_id, ip, upload_date, file_size_mb, filename, ",".join(selected_stems))
        )
        conn.commit()
    except Exception as e:
        print("Failed to log usage:", e)
    finally:
        if conn:
            conn.close()

    # ✅ Register job with priority flag
    with jobs_lock:
        JOBS[job_id] = {
            "status": "processing",
            "zip": None,
            "events": queue.Queue(),
            "ip": ip,
            "priority": is_premium
        }

    threading.Thread(target=process_job, args=(job_id, upload_path, filename, selected_stems)).start()
    return jsonify({"job_id": job_id})


@app.route("/stream/<job_id>")
@cross_origin()
def stream(job_id):
    def event_stream():
        q = JOBS.get(job_id, {}).get("events")
        if not q:
            yield "data: Job not found\n\n"
            return
        yield "data: Processing started...\n\n"
        while True:
            msg = q.get()
            yield f"data: {msg}\n\n"
            if "Job complete" in msg or "Error" in msg:
                break
    return Response(event_stream(), mimetype="text/event-stream")

@app.route("/download/<job_id>")
@cross_origin()
def download(job_id):
    job = JOBS.get(job_id)
    zip_path = job["zip"] if job else None

    if not job or not zip_path or not os.path.exists(zip_path):
        return jsonify({"error": "Download link expired. Please re-upload your file."}), 410

    temp_zip_path = zip_path + ".tmp"
    shutil.move(zip_path, temp_zip_path)
    folder_to_delete = os.path.dirname(temp_zip_path)
    active_downloading.add(job_id)

    with jobs_lock:
        JOBS.pop(job_id, None)

    filename = os.path.basename(zip_path)
    response = make_response(send_file(temp_zip_path, as_attachment=True))
    response.headers["Content-Type"] = mimetypes.guess_type(temp_zip_path)[0] or "application/octet-stream"
    response.headers["Content-Disposition"] = f'attachment; filename="{filename}"'
    response.headers["Access-Control-Expose-Headers"] = "Content-Disposition"

    def cleanup_job():
        time.sleep(2)
        active_downloading.discard(job_id)
        shutil.rmtree(folder_to_delete, ignore_errors=True)
        logger.info(f"Cleaned up temp folder: {folder_to_delete}")

    threading.Thread(target=cleanup_job).start()
    return response


@app.route("/preview/<job_id>/<stem>")
def preview(job_id, stem):
    preview_dir = os.path.join(TEMP_DIR, job_id, "preview")
    if not os.path.exists(preview_dir):
        return jsonify({"error": "Preview not found or expired."}), 404

    mp3_path = os.path.join(preview_dir, f"{stem}.mp3")
    if os.path.exists(mp3_path):
        return send_file(mp3_path, mimetype="audio/mpeg")

    wav_path = os.path.join(preview_dir, f"{stem}.wav")
    # fallback: some pipelines write "no_vocals.wav" instead of "other.wav"
    if stem == "other" and not os.path.exists(wav_path):
        wav_path = os.path.join(preview_dir, "no_vocals.wav")

    if os.path.exists(wav_path):
        return send_file(wav_path, mimetype="audio/wav")

    return jsonify({"error": "Stem not found."}), 404


# SIGNUP
@app.route("/signup", methods=["POST"])
def signup():
    data = request.get_json()
    email = data.get("email")
    password = data.get("password")

    if not email or not password:
        return jsonify({"error": "All fields are required."}), 400

    # Check for disposable email
    domain = email.split("@")[-1]
    if domain in blocklist:
        return jsonify({"error": "Disposable email addresses are not allowed."}), 400

    conn = get_db_connection()
    c = conn.cursor()

    # Check if IP has signed up in last 7 days // COMMENTING OUT JUST FOR TESTING LOCALLY 
    ip = get_client_ip()
    #c.execute('''
    #    SELECT * FROM signup_attempts
    #    WHERE ip_address = ? AND attempted_at >= datetime('now', '-7 days')
    #''', (ip,))
    #if c.fetchone():
    #    conn.close()
    #    return jsonify({"error": "Too many signups from this IP. Try again in 7 days."}), 429

    # Check if email already exists
    c.execute("SELECT * FROM users WHERE email = ?", (email,))
    if c.fetchone():
        conn.close()
        return jsonify({"error": "Email already in use."}), 409

    # Create user with is_verified = 0
    hashed_pw = generate_password_hash(password)
    c.execute("INSERT INTO users (email, password, is_verified) VALUES (?, ?, 0)",
            (email, hashed_pw))
    user_id = c.lastrowid

    # Insert into signup_attempts
    c.execute("INSERT INTO signup_attempts (ip_address, attempted_at) VALUES (?, datetime('now'))", (ip,))

    # Generate token
    token = secrets.token_urlsafe(32)
    expires_at = (datetime.utcnow() + timedelta(hours=24)).isoformat()
    c.execute('''
        INSERT INTO verification_tokens (user_id, token, expires_at, used)
        VALUES (?, ?, ?, 0)
    ''', (user_id, token, expires_at))

    conn.commit()
    conn.close()

    # Normally you'd send email here
    verify_link = f"{BASE_URL}/verify-email?token={token}"
    html_body = f"""
    <h3>Welcome to EchoMind 🎧</h3>
    <p>Click below to verify your EchoMind account:</p>
    <a href="{verify_link}">Verify Email</a>
    """

    send_email(email, "Verify your EchoMind account", html_body)

    return jsonify({
    "user": email,
    "verified": False
    }), 200

# LOGIN
@app.route("/login", methods=["POST"])
@cross_origin()
def login():
    data = request.json
    email = data.get("email")
    password = data.get("password")

    if not email or not password:
        return jsonify({"error": "Email and password required."}), 400

    try:
        db_path = os.path.join(os.path.dirname(__file__), "db", "users.db")
        conn = sqlite3.connect(db_path)
        c = conn.cursor()
        c.execute("SELECT password, is_verified FROM users WHERE email = ?", (email,))
        result = c.fetchone()
        conn.close()

        if not result:
            return jsonify({"error": "Invalid credentials."}), 401

        stored_pw, is_verified = result

        if not check_password_hash(stored_pw, password):
            return jsonify({"error": "Invalid credentials."}), 401

        #if not is_verified:
        #    return jsonify({"error": "Please verify your email before logging in."}), 403

        return jsonify({"success": True}), 200

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": f"Server error: {str(e)}"}), 500
    
@app.route("/job-history", methods=["GET"])
@cross_origin()
def job_history():
    email = request.headers.get("X-User-Email")
    if not email:
        return jsonify({"error": "Email required"}), 400

    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT id FROM users WHERE email = ?", (email,))
    user = c.fetchone()
    if not user:
        conn.close()
        return jsonify({"error": "User not found"}), 404

    user_id = user["id"]
    c.execute("""
        SELECT date, filename, stems, mb_used
        FROM usage
        WHERE user_id = ?
        ORDER BY id DESC
        LIMIT 10
    """, (user_id,))
    rows = c.fetchall()
    conn.close()

    history = [{
        "date": row["date"],
        "filename": row["filename"],
        "stems": row["stems"],
        "size": row["mb_used"]
    } for row in rows]

    return jsonify(history)    

@app.route("/verify-email", methods=["GET"])
@cross_origin()
def verify_email():
    token = request.args.get("token")
    try:
        db_path = os.path.join(os.path.dirname(__file__), "db", "users.db")
        conn = sqlite3.connect(db_path)
        c = conn.cursor()

        # Find token
        c.execute("SELECT user_id, expires_at, used FROM verification_tokens WHERE token = ?", (token,))
        result = c.fetchone()

        if not result:
            conn.close()
            return jsonify({"error": "Invalid or expired token."}), 400

        user_id, expires_at, used = result

        if used:
            conn.close()
            return jsonify({"error": "This token has already been used."}), 400

        if datetime.utcnow() > datetime.fromisoformat(expires_at):
            conn.close()
            return jsonify({"error": "Token has expired."}), 400

        # Mark user as verified
        c.execute("UPDATE users SET is_verified = 1 WHERE id = ?", (user_id,))
        c.execute("UPDATE verification_tokens SET used = 1 WHERE token = ?", (token,))
        conn.commit()
        conn.close()

        return redirect(f"{FRONTEND_URL}/verified")

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": f"Server error: {str(e)}"}), 500
    
@app.route("/reset-password-request", methods=["POST"])
def reset_password_request():
    data = request.get_json()
    email = data.get("email")

    if not email:
        return jsonify({"error": "Email is required."}), 400

    conn = get_db_connection()
    c = conn.cursor()

    # Check if user exists
    c.execute("SELECT id FROM users WHERE email = ?", (email,))
    user = c.fetchone()
    if not user:
        conn.close()
        return jsonify({"error": "Email not found."}), 404

    user_id = user[0]

    # Create reset token
    token = secrets.token_urlsafe(32)
    expires_at = (datetime.utcnow() + timedelta(hours=1)).isoformat()

    c.execute('''
        INSERT INTO password_reset_tokens (user_id, token, expires_at, used)
        VALUES (?, ?, ?, 0)
    ''', (user_id, token, expires_at))

    conn.commit()
    conn.close()

    # Normally send email
    reset_link = f"{BASE_URL}/reset-password-confirm/{token}"
    html_body = f"""
    <h3>Password Reset Requested 🔐</h3>
    <p>If you didn't request this, ignore it. Otherwise click below to reset your password:</p>
    <a href="{reset_link}">Reset Password</a>
    """

    send_email(email, "Reset your EchoMind password", html_body)

    return jsonify({
        "message": "Password reset link sent to your email.",
        "success": True
    }), 200


    
@app.route("/request-password-reset", methods=["POST"])
def request_password_reset():
    data = request.get_json()
    email = data.get("email")

    if not email:
        return jsonify({"error": "Email is required."}), 400

    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT id, is_verified FROM users WHERE email = ?", (email,))
    user = c.fetchone()

    if not user:
        conn.close()
        return jsonify({"error": "No user found with that email."}), 404

    if user["is_verified"] == 0:
        conn.close()
        return jsonify({"error": "Please verify your email before resetting password."}), 403

    token = secrets.token_urlsafe(32)
    expires_at = (datetime.utcnow() + timedelta(hours=1)).isoformat()

    c.execute('''
        INSERT INTO password_reset_tokens (user_id, token, expires_at)
        VALUES (?, ?, ?)
    ''', (user["id"], token, expires_at))

    conn.commit()
    conn.close()

    print(f"DEBUG: Password reset link → http://localhost:3000/reset-password/{token}")
    return jsonify({"message": "Reset link sent (check console)."}), 200

@app.route("/reset-password-confirm/<token>", methods=["POST"])
def reset_password(token):
    data = request.get_json()
    new_password = data.get("new_password")

    if not new_password or len(new_password) < 6:
        return jsonify({"error": "Password must be at least 6 characters."}), 400

    conn = get_db_connection()
    c = conn.cursor()
    c.execute('''
        SELECT prt.id, prt.user_id, prt.expires_at, prt.used
        FROM password_reset_tokens prt
        WHERE prt.token = ?
    ''', (token,))
    record = c.fetchone()

    if not record:
        conn.close()
        return jsonify({"error": "Invalid or expired token."}), 400

    if record["used"]:
        conn.close()
        return jsonify({"error": "This reset link has already been used."}), 400

    if datetime.utcnow() > datetime.fromisoformat(record["expires_at"]):
        conn.close()
        return jsonify({"error": "This reset link has expired."}), 400

    hashed_pw = generate_password_hash(new_password)

    # Update user's password
    c.execute("UPDATE users SET password = ? WHERE id = ?", (hashed_pw, record["user_id"]))
    c.execute("UPDATE password_reset_tokens SET used = 1 WHERE id = ?", (record["id"],))

    conn.commit()
    conn.close()

    return jsonify({"success": True, "message": "Password reset successful."}), 200


    
def get_guest_weekly_usage(ip):
    try:
        db_path = os.path.join(os.path.dirname(__file__), "db", "users.db")
        conn = sqlite3.connect(db_path)
        c = conn.cursor()

        # For zoneinfo
        now = datetime.now(ZoneInfo("Australia/Sydney"))
        # OR for pytz
        # now = datetime.now(pytz.timezone("Australia/Sydney"))

        start_of_week = now.date() - timedelta(days=now.weekday())
        start_of_week_str = start_of_week.isoformat()

        c.execute("""
            SELECT SUM(mb_used) FROM usage
            WHERE ip = ? AND user_id IS NULL AND date >= ?
        """, (ip, start_of_week_str))

        result = c.fetchone()[0]
        return result or 0
    except Exception as e:
        print("Failed to fetch guest usage:", e)
        return 0
    finally:
        if conn:
            conn.close()
    
def get_account_weekly_usage(user_id):
    try:
        db_path = os.path.join(os.path.dirname(__file__), "db", "users.db")
        conn = sqlite3.connect(db_path)
        c = conn.cursor()

        # For zoneinfo
        now = datetime.now(ZoneInfo("Australia/Sydney"))
        # OR for pytz
        # now = datetime.now(pytz.timezone("Australia/Sydney"))

        start_of_week = now.date() - timedelta(days=now.weekday())
        start_of_week_str = start_of_week.isoformat()

        # Fetch is_premium
        c.execute("SELECT is_premium FROM users WHERE id = ?", (user_id,))
        is_premium = c.fetchone()
        is_premium = is_premium[0] if is_premium else 0

        # Fetch usage
        c.execute("""
            SELECT SUM(mb_used) FROM usage
            WHERE user_id = ? AND date >= ?
        """, (user_id, start_of_week_str))

        used = c.fetchone()[0] or 0
        limit = 2000 if is_premium else 300

        return used, limit

    except Exception as e:
        print("Failed to fetch account usage:", e)
        return 0, 300  # fallback

    finally:
        if conn:
            conn.close()


    
@app.route("/usage", methods=["GET"])
@cross_origin()
def usage():
    ip = get_client_ip()
    email = request.headers.get("X-User-Email")
    is_guest = True
    user_id = None
    limit = 150
    used = 0

    try:
        db_path = os.path.join(os.path.dirname(__file__), "db", "users.db")
        conn = sqlite3.connect(db_path)
        c = conn.cursor()

        start_of_week = datetime.utcnow().date() - timedelta(days=datetime.utcnow().weekday())
        start_of_week_str = start_of_week.isoformat()

        if email:
            c.execute("SELECT id FROM users WHERE email = ?", (email,))
            result = c.fetchone()
            if result:
                user_id = result[0]
                is_guest = False

        if is_guest:
            c.execute("""
                SELECT SUM(mb_used) FROM usage
                WHERE ip = ? AND user_id IS NULL AND date >= ?
            """, (ip, start_of_week_str))
            used = c.fetchone()[0] or 0
            limit = 150
        else:
            c.execute("SELECT id, is_premium FROM users WHERE email = ?", (email,))
            result = c.fetchone()
            if result:
                user_id, is_premium = result
                limit = 2000 if is_premium else 300

                c.execute("""
                    SELECT SUM(mb_used) FROM usage
                    WHERE user_id = ? AND date >= ?
                """, (user_id, start_of_week_str))
                used = c.fetchone()[0] or 0
            else:
                used = 0
                limit = 300  # fallback

        return jsonify({
            "used_mb": round(used, 2),
            "limit_mb": limit,
            "is_premium": bool(is_premium) if not is_guest else False
        })

    except Exception as e:
        return jsonify({"error": "Failed to fetch usage"}), 500
    finally:
        if conn:
            conn.close()

@app.route("/promote-to-premium", methods=["POST"])
@cross_origin()
def promote_to_premium():
    data = request.get_json()
    email = data.get("email")

    if not email:
        return jsonify({"error": "Email is required."}), 400

    try:
        db_path = os.path.join(os.path.dirname(__file__), "db", "users.db")
        conn = sqlite3.connect(db_path)
        c = conn.cursor()

        # Check if user exists and premium status
        c.execute("SELECT is_premium FROM users WHERE email = ?", (email,))
        result = c.fetchone()

        if not result:
            conn.close()
            return jsonify({"error": "User not found."}), 404

        if result[0] == 1:
            conn.close()
            return jsonify({"message": f"{email} is already a premium user."}), 200

        # Promote to premium
        c.execute("UPDATE users SET is_premium = 1 WHERE email = ?", (email,))
        conn.commit()
        conn.close()

        return jsonify({"success": True, "message": f"{email} promoted to premium."}), 200

    except Exception as e:
        return jsonify({"error": f"Server error: {str(e)}"}), 500

@app.route("/create-checkout-session", methods=["POST"])
@cross_origin()
def create_checkout_session():
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
            success_url = f"{os.getenv('FRONTEND_URL')}/premium-success?session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url = f"{os.getenv('FRONTEND_URL')}/premium-cancelled",
        )
        return jsonify({"url": session.url})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/support-request", methods=["POST"])
def support_request():
    data = request.get_json()
    name = data.get("name")
    email = data.get("email")
    message = data.get("message")

    if not name or not email or not message:
        return jsonify(success=False, error="All fields are required."), 400

    html_body = f"""
    <h3>📩 New Support Request</h3>
    <p><strong>From:</strong> {name} ({email})</p>
    <p><strong>Message:</strong></p>
    <p>{message}</p>
    """

    try:
        send_email("support@echomind.cloud", f"Support Request from {name}", html_body)
        return jsonify(success=True), 200
    except Exception as e:
        print("❌ Failed to send support email:", e)
        return jsonify(success=False, error="Email sending failed."), 500


@app.route("/webhook", methods=["POST"])
def stripe_webhook():
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
            # Promote user to premium
            db_path = os.path.join(os.path.dirname(__file__), "db", "users.db")
            conn = sqlite3.connect(db_path)
            c = conn.cursor()
            c.execute("UPDATE users SET is_premium = 1 WHERE email = ?", (email,))
            conn.commit()
            conn.close()

            # Send premium email using same utility
            html_body = f"""
            <h3>Welcome to EchoMind Premium ✨</h3>
            <p>Hi {email},</p>
            <p>Your premium upgrade was successful. You now have access to:</p>
            <ul>
              <li>🔓 Higher upload limits</li>
              <li>⚡ Faster splitting</li>
              <li>🚀 Priority feature access</li>
            </ul>
            <p>Enjoy and thank you for supporting EchoMind.</p>
            """
            send_email(email, "You're now Premium on EchoMind", html_body)

    return jsonify(success=True), 200


@app.route("/validate-session", methods=["POST"])
def validate_session():
    data = request.get_json() or {}
    session_id = data.get("session_id")
    if not session_id:
        return jsonify({"error": "session_id required"}), 400

    try:
        session = stripe.checkout.Session.retrieve(session_id)
        email = session.get("customer_email")
        if not email:
            return jsonify({"error": "No email on session"}), 400

        # Mark premium (safe to call even if webhook already did it)
        conn = get_db_connection()
        c = conn.cursor()
        c.execute("UPDATE users SET is_premium = 1 WHERE email = ?", (email,))
        conn.commit()
        conn.close()

        return jsonify({"success": True, "email": email}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    
def preview_cleanup_loop():
    while True:
        time.sleep(3600)  # Run every hour
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


@app.errorhandler(RequestEntityTooLarge)
def handle_large_file(e):
    return jsonify({"error": f"File too large. Max {MAX_CONTENT_LENGTH_MB}MB."}), 413

@app.errorhandler(Exception)
def handle_exception(e):
    logger.error(f"Unhandled error: {e}")
    return jsonify({"error": "Internal server error."}), 500

@app.errorhandler(413)
def handle_413(e):
    return jsonify({"error": "File too large. Max allowed is 200MB."}), 413

startup_cleanup()
threading.Thread(target=preview_cleanup_loop, daemon=True).start()

@app.route("/", defaults={"path": ""})
@app.route("/<path:path>")
def serve_react(path):
    from flask import send_from_directory
    base_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "frontend", "dist"))
    if path != "" and os.path.exists(os.path.join(base_path, path)):
        return send_from_directory(base_path, path)
    else:
        return send_from_directory(base_path, "index.html")



app.config['SESSION_COOKIE_SAMESITE'] = 'None'
app.config['SESSION_COOKIE_SECURE'] = os.getenv("COOKIE_SECURE", "true").lower() == "true"

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
    
