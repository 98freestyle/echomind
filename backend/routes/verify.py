from utils.email_utils import send_email

verify_link = f"https://echomind.cloud/verify-email?token={token}"
html_body = f"""
<h3>Welcome to EchoMind 🎧</h3>
<p>Click below to verify your EchoMind account:</p>
<a href="{verify_link}">Verify Email</a>
"""

send_email(email, "Verify your EchoMind account", html_body)
