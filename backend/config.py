"""
Settings loaded from the environment (.env).
"""

import os
from datetime import timezone
from dotenv import load_dotenv

load_dotenv()

UTC = timezone.utc

# Limits
MAX_CONTENT_LENGTH_MB = int(os.getenv("MAX_CONTENT_LENGTH_MB", 100))
MAX_CONTENT_LENGTH = MAX_CONTENT_LENGTH_MB * 1024 * 1024
MAX_DISK_USAGE_MB = int(os.getenv("MAX_DISK_USAGE_MB", 1000))
MAX_JOBS_PER_IP = int(os.getenv("MAX_JOBS_PER_IP", 2))
MAX_UPLOADS_PER_MIN = int(os.getenv("MAX_UPLOADS_PER_MIN", 5))
JOB_EXPIRATION = int(os.getenv("JOB_EXPIRATION", 300))  # seconds

# Paths
TEMP_DIR = os.getenv("TEMP_DIR", "temp")
LOG_FILE = os.getenv("LOG_FILE", "logs/app.log")

# URLs and access
BASE_URL = os.getenv("BASE_URL", "http://127.0.0.1:5000")
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:5173")
CORS_ORIGINS = os.getenv("CORS_ORIGINS", "").split(",")
ADMIN_TOKEN = os.getenv("ADMIN_TOKEN")

# Allowed upload types
ALLOWED_EXTENSIONS = {".mp3", ".wav", ".flac", ".m4a", ".aac", ".ogg", ".aiff", ".mp4"}
