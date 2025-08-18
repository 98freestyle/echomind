import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')

import os, shutil, uuid, time, threading, subprocess, queue, logging, mimetypes, sqlite3, bcrypt
from flask import Flask, request, send_file, render_template, Response, jsonify, make_response
from flask_cors import CORS, cross_origin
from pydub import AudioSegment
from pydub.utils import mediainfo
from pathlib import Path
from audio_splitter import split_audio
from dotenv import load_dotenv
from werkzeug.exceptions import RequestEntityTooLarge
from werkzeug.utils import secure_filename
from collections import defaultdict, deque
from datetime import datetime, timedelta

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}}, supports_credentials=True)

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

def allowed_file(filename):
    return filename and Path(filename).suffix.lower() in ALLOWED_EXTENSIONS

def log(job_id, msg):
    logger.info(f"[{job_id}] {msg}")
    if job_id in JOBS:
        JOBS[job_id]["events"].put(msg)

def startup_cleanup():
    logger.info("Running startup cleanup of TEMP_DIR...")
    for item in os.listdir(TEMP_DIR):
        path = os.path.join(TEMP_DIR, item)
        try:
            if os.path.isdir(path):
                shutil.rmtree(path, ignore_errors=True)
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
    max_uploads = 2  # Your .env value

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
    ip = request.remote_addr
    rate_limit_msg = is_rate_limited(ip)
    if rate_limit_msg:
        return jsonify({"error": rate_limit_msg}), 429

    if "file" not in request.files:
        return jsonify({"error": "No file uploaded."}), 400

    file = request.files["file"]
    filename = secure_filename(file.filename)
    if not filename or not allowed_file(filename):
        return jsonify({"error": "Unsupported file type."}), 400

    # 👇 Calculate file size
    file.seek(0, os.SEEK_END)
    file_size_mb = round(file.tell() / (1024 * 1024), 2)
    file.seek(0)

    # 👇 Check account status
    email = request.headers.get("X-User-Email")
    user_id = None
    is_guest = True
    db_path = os.path.join(os.path.dirname(__file__), "db", "users.db")

    if email:
        try:
            conn = sqlite3.connect(db_path)
            c = conn.cursor()
            c.execute("SELECT id FROM users WHERE email = ?", (email,))
            result = c.fetchone()
            if result:
                user_id = result[0]
                is_guest = False
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
        weekly_usage = get_account_weekly_usage(user_id)
        cap = 500

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
            "INSERT INTO usage (user_id, ip, date, mb_used) VALUES (?, ?, ?, ?)",
            (user_id, ip, upload_date, file_size_mb)
        )
        conn.commit()
    except Exception as e:
        print("Failed to log usage:", e)
    finally:
        if conn:
            conn.close()

    with jobs_lock:
        JOBS[job_id] = {"status": "processing", "zip": None, "events": queue.Queue(), "ip": ip}

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
@cross_origin()
def preview(job_id, stem):
    preview_dir = os.path.join(TEMP_DIR, job_id, "preview")
    if not os.path.exists(preview_dir):
        return jsonify({"error": "Preview not found or expired."}), 404

    path = os.path.join(preview_dir, f"{stem}.mp3")
    if stem == "other" and not os.path.exists(path):
        fallback = os.path.join(preview_dir, "no_vocals.wav")
        if os.path.exists(fallback):
            path = fallback

    if os.path.exists(path):
        return send_file(path, mimetype="audio/mpeg")
    return jsonify({"error": "Stem not found."}), 404


# SIGNUP
@app.route("/signup", methods=["POST"])
@cross_origin()
def signup():
    data = request.json
    username = data.get("username")
    email = data.get("email")
    password = data.get("password")

    if not username or not email or not password:
        return jsonify({"error": "All fields are required."}), 400

    hashed_pw = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

    conn = None
    try:
        db_path = os.path.join(os.path.dirname(__file__), "db", "users.db")
        conn = sqlite3.connect(db_path)
        c = conn.cursor()
        c.execute("INSERT INTO users (username, email, password) VALUES (?, ?, ?)",
                  (username, email, hashed_pw))
        conn.commit()
        return jsonify({"success": True}), 201
    except sqlite3.IntegrityError:
        return jsonify({"error": "Username or email already exists."}), 409
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": f"Server error: {str(e)}"}), 500
    finally:
        if conn:
            conn.close()

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
        c.execute("SELECT password FROM users WHERE email = ?", (email,))
        result = c.fetchone()
        conn.close()

        if not result:
            return jsonify({"error": "Invalid credentials."}), 401

        stored_pw = result[0]
        if not bcrypt.checkpw(password.encode("utf-8"), stored_pw.encode("utf-8")):
            return jsonify({"error": "Invalid credentials."}), 401

        return jsonify({"success": True}), 200

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": f"Server error: {str(e)}"}), 500
    
def get_guest_weekly_usage(ip):
    try:
        db_path = os.path.join(os.path.dirname(__file__), "db", "users.db")
        conn = sqlite3.connect(db_path)
        c = conn.cursor()

        start_of_week = datetime.utcnow().date() - timedelta(days=datetime.utcnow().weekday())
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

        start_of_week = datetime.utcnow().date() - timedelta(days=datetime.utcnow().weekday())
        start_of_week_str = start_of_week.isoformat()

        c.execute("""
            SELECT SUM(mb_used) FROM usage
            WHERE user_id = ? AND date >= ?
        """, (user_id, start_of_week_str))

        result = c.fetchone()[0]
        return result or 0
    except Exception as e:
        print("Failed to fetch account usage:", e)
        return 0
    finally:
        if conn:
            conn.close()

    
@app.route("/usage", methods=["GET"])
@cross_origin()
def usage():
    ip = request.remote_addr
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
            limit = 150
        else:
            c.execute("""
                SELECT SUM(mb_used) FROM usage
                WHERE user_id = ? AND date >= ?
            """, (user_id, start_of_week_str))
            limit = 500  # Future: check is_premium flag

        used = c.fetchone()[0] or 0

        return jsonify({
            "used_mb": round(used, 2),
            "limit_mb": limit
        })

    except Exception as e:
        return jsonify({"error": "Failed to fetch usage"}), 500
    finally:
        if conn:
            conn.close()



@app.errorhandler(RequestEntityTooLarge)
def handle_large_file(e):
    return jsonify({"error": f"File too large. Max {MAX_CONTENT_LENGTH_MB}MB."}), 413

@app.errorhandler(Exception)
def handle_exception(e):
    logger.error(f"Unhandled error: {e}")
    return jsonify({"error": "Internal server error."}), 500

startup_cleanup()

@app.route("/", defaults={"path": ""})
@app.route("/<path:path>")
def serve_react(path):
    from flask import send_from_directory
    if path != "" and os.path.exists(f"../frontend/dist/{path}"):
        return send_from_directory("../frontend/dist", path)
    else:
        return send_from_directory("../frontend/dist", "index.html")


if __name__ == "__main__":
    app.run(debug=True, threaded=True)
