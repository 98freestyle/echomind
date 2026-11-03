"""
Premium upgrades: Stripe checkout, webhook, session validation and admin promotion.
"""

import logging
import os

import stripe
from flask import Blueprint, jsonify, request
from flask_cors import cross_origin

from config import ADMIN_TOKEN, FRONTEND_URL
from db import get_db_connection
from utils.email_utils import send_email

logger = logging.getLogger("echomind")
payments_bp = Blueprint("payments", __name__)

stripe.api_key = os.getenv("STRIPE_SECRET_KEY")


@payments_bp.route("/promote-to-premium", methods=["POST"])
@cross_origin()
def promote_to_premium():
    """
    Manually promote a user to premium (admin-only via token).
    """
    # --- Admin token check ---
    token = request.headers.get("X-ADMIN-TOKEN")
    if not ADMIN_TOKEN or token != ADMIN_TOKEN:
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


@payments_bp.route("/create-checkout-session", methods=["POST"])
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


@payments_bp.route("/webhook", methods=["POST"])
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


@payments_bp.route("/validate-session", methods=["POST"])
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

