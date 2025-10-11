import time
import os
import smtplib
import ssl
import serial
import certifi
from email.mime.text import MIMEText

from dotenv import load_dotenv
from serial.serialutil import SerialException

load_dotenv()

# ====== Load .env ====================
SERIAL_PORT = os.getenv("SERIAL_PORT", "/dev/cu.usbserial-1110")
BAUD = int(os.getenv("BAUD", 115200))
COOLDOWN_S = int(os.getenv("COOLDOWN_S", 60))
FROM_EMAIL = os.getenv("FROM_EMAIL")
TO_EMAIL = os.getenv("TO_EMAIL")
APP_PASS = os.getenv("APP_PASS")
READ_TIMEOUT_S = 1
# ======================================

def parse_motion(line: str) -> dict | None:
    """
    Expect: MOTION:1;GAS=...;SND=...;WTR=...;TEMP=...;HUM=...
    Returns dict of fields if starts with MOTION:1, else None.
    """
    line = line.strip()
    if not line.startswith("MOTION:1"):
        return None
    parts = line.split(";")
    data = {}
    for p in parts[1:]:
        if "=" in p:
            k, v = p.split("=", 1)
            data[k.strip()] = v.strip()
    return data


def build_message(payload: dict) -> MIMEText:
    body = (
        "Motion detected by Arduino.\n\n"
        f"GAS:  {payload.get('GAS', '?')}\n"
        f"SND:  {payload.get('SND', '?')}\n"
        f"WTR:  {payload.get('WTR', '?')}\n"
        f"TEMP: {payload.get('TEMP', '?')} °C\n"
        f"HUM:  {payload.get('HUM', '?')} %\n"
        f"Time: {time.strftime('%Y-%m-%d %H:%M:%S')}\n"
    )
    msg = MIMEText(body)
    msg["Subject"] = "🔔 Motion Alert"
    msg["From"] = FROM_EMAIL
    msg["To"] = TO_EMAIL
    return msg


def send_mail(msg: MIMEText):
    ctx = ssl.create_default_context(cafile=certifi.where())
    with smtplib.SMTP("smtp.gmail.com", 587, timeout=20) as s:
        s.ehlo()
        s.starttls(context=ctx)
        s.ehlo()
        s.login(FROM_EMAIL, APP_PASS)
        s.send_message(msg)
    print("[MAIL] sent")


def open_serial_blocking() -> serial.Serial:
    while True:
        try:
            ser = serial.Serial(SERIAL_PORT, BAUD, timeout=READ_TIMEOUT_S)
            print(f"[SERIAL] Listening on {SERIAL_PORT} @ {BAUD}")
            return ser
        except SerialException as e:
            print(f"[SERIAL] Port not ready ({e}); retrying in 3s...")
            time.sleep(3)


def main():
    # Basic sanity checks
    if not FROM_EMAIL or not APP_PASS:
        print("[CONFIG] Please set FROM_EMAIL and APP_PASS (Gmail App Password).")
        return

    ser = open_serial_blocking()
    last_sent = 0.0
    buf = b""

    while True:
        try:
            chunk = ser.read(256)
            if chunk:
                buf += chunk
                # process full lines
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    try:
                        text = line.decode(errors="ignore").strip()
                    except Exception:
                        text = ""
                    if not text:
                        continue

                    print("[SERIAL]", text)
                    payload = parse_motion(text)
                    if payload is None:
                        continue

                    now = time.time()
                    if now - last_sent >= COOLDOWN_S:
                        try:
                            msg = build_message(payload)
                            send_mail(msg)
                            last_sent = now
                        except Exception as e:
                            print("[MAIL] error:", e)
                    else:
                        print("[MAIL] cooldown active")
            else:
                # no data this tick
                time.sleep(0.05)

        except SerialException as e:
            print(f"[SERIAL] lost connection ({e}); reopening...")
            try:
                ser.close()
            except Exception:
                pass
            time.sleep(2)
            ser = open_serial_blocking()
        except KeyboardInterrupt:
            print("\n[EXIT] Ctrl-C")
            try:
                ser.close()
            except Exception:
                pass
            break


if __name__ == "__main__":
    main()
