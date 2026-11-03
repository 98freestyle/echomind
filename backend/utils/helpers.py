"""
Small request and logging helpers shared across routes.
"""

import logging
from pathlib import Path

from flask import request

from config import ALLOWED_EXTENSIONS

logger = logging.getLogger("echomind")


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

