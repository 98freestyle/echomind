import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import os

def send_email(to_email, subject, html_content):
    msg = MIMEMultipart()
    msg['From'] = os.getenv("MAIL_FROM")
    msg['To'] = to_email
    msg['Subject'] = subject

    msg.attach(MIMEText(html_content, 'html'))

    with smtplib.SMTP_SSL(os.getenv("MAIL_SERVER"), int(os.getenv("MAIL_PORT"))) as server:
        server.login(os.getenv("MAIL_USERNAME"), os.getenv("MAIL_PASSWORD"))
        server.send_message(msg)
        print(f"Email sent to {to_email}")