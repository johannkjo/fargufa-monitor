#!/usr/bin/env python3
import os
import re
import sys
import smtplib
import ssl
from email.message import EmailMessage
from datetime import datetime, time, timezone
import requests
from bs4 import BeautifulSoup

URL = os.getenv("FARGUFA_URL", "https://fargufa.is/")
TARGET_LOCATION = os.getenv("TARGET_LOCATION", "Gufunes")
REGEX = re.compile(r"\b(\d+)\s*pláss\b", re.IGNORECASE)

# Quiet hours in UTC/Reykjavík (same): from 01:00 (inclusive) to 06:30 (exclusive)
QUIET_START = time(1, 0)   # 01:00
QUIET_END   = time(6, 30)  # 06:30

def in_quiet_hours(now_utc: datetime) -> bool:
    t = now_utc.time()
    return QUIET_START <= t < QUIET_END

def fetch_html(url: str) -> str:
    headers = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }
    r = requests.get(url, headers=headers, timeout=30)
    r.raise_for_status()
    return r.text

def find_gufunes_section(html: str) -> str | None:
    soup = BeautifulSoup(html, "lxml")
    candidates = soup.find_all(string=re.compile(rf"\b{re.escape(TARGET_LOCATION)}\b", re.IGNORECASE))
    for node in candidates:
        parent = getattr(node, "parent", None)
        for _ in range(4):
            if parent and parent.parent:
                parent = parent.parent
        if not parent:
            continue
        text_block = parent.get_text(separator=" ", strip=True)
        if re.search(rf"\b{re.escape(TARGET_LOCATION)}\b", text_block, re.IGNORECASE):
            return text_block
    return soup.get_text(separator=" ", strip=True)

def parse_availability(text_block: str):
    m = REGEX.search(text_block)
    if not m:
        return None
    places = int(m.group(1))
    time_matches = re.findall(r"\b([01]?\d|2[0-3]):[0-5]\d\b", text_block)
    times = sorted(set(time_matches))
    return {"places": places, "times": times}

def send_email(subject: str, body: str):
    user = os.getenv("GMAIL_USER")
    pwd = os.getenv("GMAIL_PASS")
    to   = os.getenv("TO_EMAIL")
    if not (user and pwd and to):
        print("Email not configured; skipping.", file=sys.stderr)
        return
    msg = EmailMessage()
    msg["From"] = user
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    ctx = ssl.create_default_context()
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ctx) as s:
        s.login(user, pwd)
        s.send_message(msg)

def send_sms(message: str):
    sid   = os.getenv("TWILIO_SID")
    token = os.getenv("TWILIO_TOKEN")
    from_ = os.getenv("TWILIO_FROM")
    to    = os.getenv("TO_SMS")
    if not (sid and token and from_ and to):
        print("SMS not configured; skipping.", file=sys.stderr)
        return
    url = f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json"
    data = {"From": from_, "To": to, "Body": message}
    r = requests.post(url, data=data, auth=(sid, token), timeout=30)
    r.raise_for_status()

def main():
    now_utc = datetime.utcnow().replace(tzinfo=timezone.utc)
    now_str = now_utc.strftime("%Y-%m-%d %H:%M UTC")

    if in_quiet_hours(now_utc):
        print(f"In quiet hours (01:00–06:30 UTC). Skipping notifications at {now_str}.")
        return 0

    try:
        html = fetch_html(URL)
        block = find_gufunes_section(html)
        if not block:
            print("Could not locate Gufunes section; exiting silently.")
            return 0
        avail = parse_availability(block)
        if not avail:
            print("No availability; silent.")
            return 0

        places = avail["places"]
        times  = ", ".join(avail["times"]) if avail["times"] else "—"
        subject = f"LAUST: Gufunes – {places} pláss"
        body = (f"🔥 Laust í Gufunes!\n"
                f"Pláss: {places}\n"
                f"Tímar: {times}\n"
                f"Slóð: {URL}\n"
                f"Staðfest: {now_str}")
        print(body)
        try:
            send_email(subject, body)
        except Exception as e:
            print(f"Email error: {e}", file=sys.stderr)
        try:
            send_sms(f"Gufunes: {places} pláss. Tímar: {times}. {URL}")
        except Exception as e:
            print(f"SMS error: {e}", file=sys.stderr)
        return 0
    except Exception as e:
        print(f"Checker error: {e}", file=sys.stderr)
        return 1

if __name__ == "__main__":
    sys.exit(main())
