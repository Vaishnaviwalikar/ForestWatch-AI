import os
import smtplib
from email.mime.text import MIMEText
from dotenv import load_dotenv

# Load credentials from .env file if available
load_dotenv()

EMAIL_SENDER = os.environ.get("EMAIL_SENDER", "").strip()
EMAIL_PASSWORD = os.environ.get("EMAIL_PASSWORD", "").strip()
EMAIL_RECIPIENT = os.environ.get("EMAIL_RECIPIENT", "").strip()
SMTP_HOST = os.environ.get("SMTP_HOST", "smtp.gmail.com").strip()
SMTP_PORT = int(os.environ.get("SMTP_PORT", "465"))

if not EMAIL_SENDER or not EMAIL_PASSWORD or not EMAIL_RECIPIENT:
    print("❌ ERROR: Email credentials not configured.")
    print("Please set EMAIL_SENDER, EMAIL_PASSWORD, and EMAIL_RECIPIENT in your environment or in a .env file.")
    print("Example in .env:")
    print("EMAIL_SENDER=your_email@gmail.com")
    print("EMAIL_PASSWORD=your_16_char_app_password")
    print("EMAIL_RECIPIENT=recipient@gmail.com")
    exit(1)

msg = MIMEText("This is a verified test email from your Sentinel-2 Forest Monitoring System.")
msg["Subject"] = "Sentinel-2 SMTP Diagnostic Test"
msg["From"] = EMAIL_SENDER
msg["To"] = EMAIL_RECIPIENT

try:
    print(f"Connecting to SMTP server {SMTP_HOST}:{SMTP_PORT} using SSL...")
    server = smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=10)
    server.login(EMAIL_SENDER, EMAIL_PASSWORD)
    print(f"Sending test email from {EMAIL_SENDER} to {EMAIL_RECIPIENT}...")
    server.sendmail(EMAIL_SENDER, EMAIL_RECIPIENT, msg.as_string())
    server.quit()
    print("✅ Test email sent successfully!")
except Exception as e:
    print(f"❌ Error sending test email: {e}")
