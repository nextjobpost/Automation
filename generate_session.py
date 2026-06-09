import os
import sys

# Fix Windows console encoding
if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from telethon.sync import TelegramClient
from telethon.sessions import StringSession
from dotenv import load_dotenv

load_dotenv()

API_ID = os.getenv("API_ID")
API_HASH = os.getenv("API_HASH")

if not API_ID or not API_HASH:
    print("ERROR: API_ID or API_HASH not found in .env")
    exit()

print("Starting Telegram Session Generator...")
print("Enter your phone number (with country code, e.g. +91XXXXXXXXXX) and the OTP you receive.")

with TelegramClient(StringSession(), API_ID, API_HASH) as client:
    session_string = client.session.save()
    print("\n" + "="*60)
    print("YOUR SESSION STRING (copy everything between the lines):")
    print("="*60)
    print(f"\n{session_string}\n")
    print("="*60)
    print("Add this to Railway as environment variable:")
    print("Key:   TELEGRAM_SESSION_STRING")
    print("Value: (the long string above)")
    print("="*60)
