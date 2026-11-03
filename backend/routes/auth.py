"""
Account routes: signup, login, email verification, password reset and job history.
"""

import logging
import secrets
from datetime import datetime, timedelta

from flask import Blueprint, jsonify, redirect, request
from flask_cors import cross_origin
from disposable_email_domains import blocklist
from werkzeug.security import check_password_hash, generate_password_hash

from config import BASE_URL, FRONTEND_URL, UTC
from db import get_db_connection
from utils.email_utils import send_email
from utils.helpers import get_client_ip

logger = logging.getLogger("echomind")
auth_bp = Blueprint("auth", __name__)


@auth_bp.route("/signup", methods=["POST"])
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


@auth_bp.route("/login", methods=["POST"])
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


@auth_bp.route("/job-history", methods=["GET"])
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


@auth_bp.route("/verify-email", methods=["GET"])
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


@auth_bp.route("/reset-password-request", methods=["POST"])
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


@auth_bp.route("/reset-password-confirm/<token>", methods=["POST"])
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

