"""
EchoMind Backend (Flask)

Entry point: creates the app, wires up the route blueprints and serves the
built React frontend. Gunicorn loads `app:app`.
"""

import logging
import os
import threading

from flask import Flask, jsonify, send_from_directory
from flask_cors import CORS
from werkzeug.exceptions import RequestEntityTooLarge

from config import CORS_ORIGINS, LOG_FILE, MAX_CONTENT_LENGTH, MAX_CONTENT_LENGTH_MB, TEMP_DIR
from routes.auth import auth_bp
from routes.jobs import jobs_bp
from routes.payments import payments_bp
from routes.support import support_bp
from routes.usage import usage_bp
from services.processing import preview_cleanup_loop, startup_cleanup

# ============================================================
# Setup
# ============================================================

os.makedirs(TEMP_DIR, exist_ok=True)
os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s]: %(message)s",
    handlers=[logging.FileHandler(LOG_FILE), logging.StreamHandler()]
)
logger = logging.getLogger("echomind")

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = MAX_CONTENT_LENGTH
app.config["SESSION_COOKIE_SAMESITE"] = "None"
app.config["SESSION_COOKIE_SECURE"] = os.getenv("COOKIE_SECURE", "true").lower() == "true"
CORS(app, supports_credentials=True, origins=CORS_ORIGINS)

for blueprint in (jobs_bp, auth_bp, usage_bp, payments_bp, support_bp):
    app.register_blueprint(blueprint)


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
    return jsonify({"error": f"File too large. Max {MAX_CONTENT_LENGTH_MB}MB."}), 413



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
    base_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "frontend", "dist"))
    if path != "" and os.path.exists(os.path.join(base_path, path)):
        return send_from_directory(base_path, path)
    else:
        return send_from_directory(base_path, "index.html")



# ============================================================
# Local Run (Dev only)
# ============================================================

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
