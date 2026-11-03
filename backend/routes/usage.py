"""
Weekly usage route used by the usage bar.
"""

import logging
from datetime import datetime, timedelta

from flask import Blueprint, jsonify, request
from flask_cors import cross_origin

from config import UTC
from db import get_db_connection
from utils.helpers import get_client_ip

logger = logging.getLogger("echomind")
usage_bp = Blueprint("usage", __name__)


@usage_bp.route("/usage", methods=["GET"])
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

