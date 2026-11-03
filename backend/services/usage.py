"""
Weekly usage calculations for guests (by IP) and accounts.
"""

import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from db import get_db_connection

logger = logging.getLogger("echomind")


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

