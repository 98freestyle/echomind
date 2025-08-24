from utils.email_utils import send_email

reset_link = f"https://echomind.cloud/reset-password?token={token}"
html_body = f"""
<h3>Password Reset Requested 🔐</h3>
<p>If you didn't request this, ignore it. Otherwise click below to reset your password:</p>
<a href="{reset_link}">Reset Password</a>
"""

send_email(email, "Reset your EchoMind password", html_body)
