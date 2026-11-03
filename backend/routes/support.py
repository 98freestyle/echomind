"""
Support contact form route.
"""

import logging

from flask import Blueprint, jsonify, request

from utils.email_utils import send_email

logger = logging.getLogger("echomind")
support_bp = Blueprint("support", __name__)


@support_bp.route("/support-request", methods=["POST"])
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

