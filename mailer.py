#!/usr/bin/env python3
import os, time, json, threading, ssl, smtplib, serial, certifi
from collections import deque
from email.mime.text import MIMEText
from datetime import datetime
import matplotlib
from serial.serialutil import SerialException
from dotenv import load_dotenv
import matplotlib.pyplot as plt
from matplotlib.animation import FuncAnimation

# matplotlib.use("TkAgg")
matplotlib.use("MacOSX")

# ====== .env ======
load_dotenv()
SERIAL_PORT = os.getenv("SERIAL_PORT", "/dev/cu.usbserial-110")
BAUD = int(os.getenv("BAUD", 115200))
COOLDOWN_S = int(os.getenv("COOLDOWN_S", 60))
FROM_EMAIL = os.getenv("FROM_EMAIL")
TO_EMAIL = os.getenv("TO_EMAIL", FROM_EMAIL)
APP_PASS = os.getenv("APP_PASS")
READ_TIMEOUT = 1
WINDOW_SEC = int(os.getenv("WINDOW_SEC", "300"))

# ====== ALERT THRESHOLDS ======
ALERT_THRESHOLDS = {
    "gas": 300,
    "sound": 500,
    "water": 300,
    "vibration": 1,
    "temp_high": 35,
    "temp_low": 10,
    "humidity_high": 80,
    "humidity_low": 20
}

# ====== GLOBAL STATE ======
maxlen = WINDOW_SEC
ts = deque(maxlen=maxlen)
gas = deque(maxlen=maxlen)
snd = deque(maxlen=maxlen)
wtr = deque(maxlen=maxlen)
tmpC = deque(maxlen=maxlen)
hum = deque(maxlen=maxlen)
mot = deque(maxlen=maxlen)
vib = deque(maxlen=maxlen)

start_time = time.time()
last_email = 0.0
alert_history = []

def check_alerts(payload: dict) -> list:
    """Check sensor data against all thresholds and return triggered alerts"""
    alerts = []

    if payload.get('gas', 0) > ALERT_THRESHOLDS['gas']:
        alerts.append(f"HIGH GAS: {payload['gas']}")

    if payload.get('sound', 0) > ALERT_THRESHOLDS['sound']:
        alerts.append(f"HIGH SOUND: {payload['sound']}")

    if payload.get('water', 0) > ALERT_THRESHOLDS['water']:
        alerts.append(f"HIGH WATER: {payload['water']}")

    if payload.get('vibration', 0) == 1:
        alerts.append("VIBRATION DETECTED")

    temp = payload.get('temp')
    if temp is not None:
        if temp > ALERT_THRESHOLDS['temp_high']:
            alerts.append(f"HIGH TEMP: {temp}°C")
        elif temp < ALERT_THRESHOLDS['temp_low']:
            alerts.append(f"LOW TEMP: {temp}°C")

    humidity = payload.get('humidity')
    if humidity is not None:
        if humidity > ALERT_THRESHOLDS['humidity_high']:
            alerts.append(f"HIGH HUMIDITY: {humidity}%")
        elif humidity < ALERT_THRESHOLDS['humidity_low']:
            alerts.append(f"LOW HUMIDITY: {humidity}%")

    if payload.get('motion', 0) == 1:
        alerts.append("MOTION DETECTED")

    return alerts

def send_mail(payload: dict, alerts: list):
    """Send email with detailed alert information"""
    if not FROM_EMAIL or not APP_PASS:
        return

    if any("GAS" in alert or "VIBRATION" in alert for alert in alerts):
        subject = "CRITICAL ALERT - Multiple Sensors Triggered!"
    elif any("SOUND" in alert or "WATER" in alert for alert in alerts):
        subject = "WARNING - Sensor Thresholds Exceeded!"
    else:
        subject = "Sensor Alert"

    body = f"""
ARDUINO SENSOR ALERT SYSTEM
Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

TRIGGERED ALERTS:
{chr(10).join(f"- {alert}" for alert in alerts)}

CURRENT SENSOR READINGS:
- Gas:        {payload.get('gas', 'N/A')}
- Sound:      {payload.get('sound', 'N/A')} 
- Water:      {payload.get('water', 'N/A')}
- Vibration:  {payload.get('vibration', 'N/A')}
- Temperature: {payload.get('temp', 'N/A')} °C
- Humidity:   {payload.get('humidity', 'N/A')} %
- Motion:     {payload.get('motion', 'N/A')}

System Status: Active
Cooldown: {COOLDOWN_S} seconds
"""

    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = FROM_EMAIL
    msg["To"] = TO_EMAIL

    try:
        ctx = ssl.create_default_context(cafile=certifi.where())
        with smtplib.SMTP("smtp.gmail.com", 587, timeout=20) as s:
            s.ehlo()
            s.starttls(context=ctx)
            s.ehlo()
            s.login(FROM_EMAIL, APP_PASS)
            s.send_message(msg)
        print(f"[MAIL] Alert email sent: {subject}")
        alert_history.append({
            'timestamp': datetime.now(),
            'alerts': alerts,
            'payload': payload
        })
    except Exception as e:
        print(f"[MAIL] Error sending email: {e}")

def open_serial_blocking() -> serial.Serial:
    """Open serial connection with retry logic"""
    while True:
        try:
            ser = serial.Serial(SERIAL_PORT, BAUD, timeout=READ_TIMEOUT)
            print(f"[SERIAL] Listening on {SERIAL_PORT} @ {BAUD}")
            return ser
        except SerialException as e:
            print(f"[SERIAL] Port not ready ({e}); retrying in 3s...")
            time.sleep(3)

def parse_json_line(text: str) -> dict | None:
    """Parse JSON line from Arduino, handling NaN values"""
    t = text.strip()
    if not t or t[0] != "{":
        return None
    t = t.replace("nan", "null")
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        return None

def reader_thread():
    """Main thread for reading Arduino data and triggering alerts"""
    global last_email
    ser = open_serial_blocking()
    buf = b""

    print(f"[ALERTS] Alert system active with thresholds: {ALERT_THRESHOLDS}")

    while True:
        try:
            chunk = ser.read(256)
            if chunk:
                buf += chunk
                while b"\n" in buf:
                    raw, buf = buf.split(b"\n", 1)
                    text = raw.decode(errors="ignore").strip()
                    if not text:
                        continue

                    data = parse_json_line(text)
                    if not data:
                        print("[SERIAL RAW]", text)
                        continue

                    # Append to buffers
                    tsec = time.time() - start_time
                    ts.append(tsec)
                    gas.append(float(data.get("gas", 0) or 0))
                    snd.append(float(data.get("sound", 0) or 0))
                    wtr.append(float(data.get("water", 0) or 0))
                    vib.append(int(data.get("vibration", 0) or 0))
                    tc = data.get("temp", None)
                    hm = data.get("humidity", None)
                    tmpC.append(float(tc) if tc is not None else None)
                    hum.append(float(hm) if hm is not None else None)
                    mv = int(data.get("motion", 0) or 0)
                    mot.append(mv)

                    # Check all alert conditions
                    current_alerts = check_alerts(data)

                    # Send email if any alerts and cooldown period has passed
                    if (current_alerts and
                            (time.time() - last_email >= COOLDOWN_S) and
                            FROM_EMAIL and APP_PASS):
                        try:
                            send_mail(data, current_alerts)
                            last_email = time.time()
                            print(f"[ALERT] Triggered: {', '.join(current_alerts)}")
                        except Exception as e:
                            print(f"[MAIL] Error: {e}")

                    # Print sensor readings - vibration as number only
                    print(f"[DATA] G:{data.get('gas'):3.0f} "
                          f"S:{data.get('sound'):3.0f} "
                          f"W:{data.get('water'):3.0f} "
                          f"V:{data.get('vibration', 0):1.0f} "
                          f"T:{data.get('temp', 0):4.1f} "
                          f"H:{data.get('humidity', 0):3.0f} "
                          f"M:{data.get('motion', 0):1.0f}")

            else:
                time.sleep(0.02)
        except SerialException as e:
            print(f"[SERIAL] Lost connection ({e}); reopening...")
            try:
                ser.close()
            except Exception:
                pass
            time.sleep(2)
            ser = open_serial_blocking()
        except Exception as e:
            print(f"[SERIAL] Unexpected error: {e}")

# ====== PLOTTING ======
plt.style.use("dark_background")
fig = plt.figure(figsize=(14, 10), constrained_layout=True)
gs = fig.add_gridspec(3, 2)

# Create subplots
ax1 = fig.add_subplot(gs[0, :])  # Gas, Sound, Water
ax2 = fig.add_subplot(gs[1, 0])  # Temperature
ax3 = fig.add_subplot(gs[1, 1])  # Humidity
ax4 = fig.add_subplot(gs[2, :])  # Motion + Vibration

# Plot 1: Combined sensors
gas_line, = ax1.plot([], [], 'r-', label="Gas", linewidth=2)
snd_line, = ax1.plot([], [], 'y-', label="Sound", linewidth=2)
wtr_line, = ax1.plot([], [], 'c-', label="Water", linewidth=2)
ax1.set_title("Gas / Sound / Water")
ax1.set_xlabel("Time (s)")
ax1.set_ylabel("Sensor Values")
ax1.legend()
ax1.grid(True, alpha=0.3)

# Add threshold lines
ax1.axhline(y=ALERT_THRESHOLDS['gas'], color='r', linestyle='--', alpha=0.7)
ax1.axhline(y=ALERT_THRESHOLDS['sound'], color='y', linestyle='--', alpha=0.7)
ax1.axhline(y=ALERT_THRESHOLDS['water'], color='c', linestyle='--', alpha=0.7)

# Plot 2: Temperature
temp_line, = ax2.plot([], [], 'orange', label="Temperature", linewidth=2)
ax2.set_title("Temperature")
ax2.set_xlabel("Time (s)")
ax2.set_ylabel("°C")
ax2.legend()
ax2.grid(True, alpha=0.3)
ax2.axhline(y=ALERT_THRESHOLDS['temp_high'], color='red', linestyle='--', alpha=0.7)
ax2.axhline(y=ALERT_THRESHOLDS['temp_low'], color='blue', linestyle='--', alpha=0.7)

# Plot 3: Humidity
hum_line, = ax3.plot([], [], 'b', label="Humidity", linewidth=2)
ax3.set_title("Humidity")
ax3.set_xlabel("Time (s)")
ax3.set_ylabel("%")
ax3.legend()
ax3.grid(True, alpha=0.3)
ax3.axhline(y=ALERT_THRESHOLDS['humidity_high'], color='red', linestyle='--', alpha=0.7)
ax3.axhline(y=ALERT_THRESHOLDS['humidity_low'], color='blue', linestyle='--', alpha=0.7)

# Plot 4: Motion + Vibration
mot_line, = ax4.plot([], [], 'g-', label="Motion", linewidth=2)
vib_line, = ax4.plot([], [], 'm-', label="Vibration", linewidth=2)
ax4.set_title("Motion & Vibration Events")
ax4.set_xlabel("Time (s)")
ax4.set_ylabel("State (0/1)")
ax4.legend()
ax4.set_ylim(-0.1, 1.1)
ax4.grid(True, alpha=0.3)

def update(_):
    """Update all plots with new data"""
    if not ts:
        return gas_line, snd_line, wtr_line, temp_line, hum_line, mot_line, vib_line

    x = list(ts)
    current_time = x[-1] if x else 0

    # Update combined sensors plot
    gas_line.set_data(x, list(gas))
    snd_line.set_data(x, list(snd))
    wtr_line.set_data(x, list(wtr))

    # Auto-scale combined plot
    all_vals = list(gas) + list(snd) + list(wtr)
    if all_vals:
        y_min = min(all_vals)
        y_max = max(all_vals)
        padding = max(10, (y_max - y_min) * 0.1)
        ax1.set_ylim(y_min - padding, y_max + padding)
        ax1.set_xlim(max(0, current_time - WINDOW_SEC), current_time + 1)

    # Update temperature plot
    y_temp = [v if v is not None else float("nan") for v in tmpC]
    temp_line.set_data(x, y_temp)
    if any(v == v for v in y_temp):
        valid_temp = [v for v in y_temp if v == v]
        if valid_temp:
            ax2.set_ylim(min(valid_temp) - 2, max(valid_temp) + 2)
    ax2.set_xlim(max(0, current_time - WINDOW_SEC), current_time + 1)

    # Update humidity plot
    y_hum = [v if v is not None else float("nan") for v in hum]
    hum_line.set_data(x, y_hum)
    if any(v == v for v in y_hum):
        valid_hum = [v for v in y_hum if v == v]
        if valid_hum:
            ax3.set_ylim(max(0, min(valid_hum) - 5), min(100, max(valid_hum) + 5))
    ax3.set_xlim(max(0, current_time - WINDOW_SEC), current_time + 1)

    # Update events plot
    mot_line.set_data(x, list(mot))
    vib_line.set_data(x, list(vib))
    ax4.set_xlim(max(0, current_time - WINDOW_SEC), current_time + 1)

    return gas_line, snd_line, wtr_line, temp_line, hum_line, mot_line, vib_line

def main():
    """Main function to start the monitoring system"""
    print("Starting Arduino Sensor Monitor...")
    print(f"Email: {FROM_EMAIL} -> {TO_EMAIL}")
    print(f"Alert thresholds: {ALERT_THRESHOLDS}")
    print(f"Cooldown: {COOLDOWN_S}s")
    print("Press Ctrl+C to stop")

    # Start serial reader thread
    threading.Thread(target=reader_thread, daemon=True).start()

    # Start animation
    ani = FuncAnimation(fig, update, interval=1000, cache_frame_data=False, save_count=300)

    try:
        plt.show()
    except KeyboardInterrupt:
        print("Monitoring stopped")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    main()