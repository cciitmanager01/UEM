import requests
import platform
import subprocess
import time
import os
import psutil
import pyautogui
import base64
from io import BytesIO
from PIL import Image

# ================= CONFIGURATION =================
SERVER_URL = "https://uem-ten.vercel.app"
API_SECRET_KEY = "7f9c2e4b8a1d5f306e92b8d4c1a7e5f93b0a2d6c4e8f1b9a7d3c5e0b2f4a6d8c"
# =================================================

# Global flag to control remote view
remote_view_active = False


def get_serial():
    """Gets the hardware serial number (Win/Mac)"""
    system = platform.system()
    try:
        if system == "Windows":
            cmd = "powershell (Get-CimInstance -ClassName Win32_BIOS).SerialNumber"
            return subprocess.check_output(cmd, shell=True).decode().strip()
        elif system == "Darwin":  # macOS
            cmd = "ioreg -l | grep IOPlatformSerialNumber | awk -F'\"' '{print $4}'"
            return subprocess.check_output(cmd, shell=True).decode().strip()
    except Exception as e:
        return f"UNKNOWN-{platform.node()}"


def get_telemetry():
    """Collects hardware stats"""
    try:
        cpu = psutil.cpu_percent(interval=None)  # Changed to None for faster response
        ram = psutil.virtual_memory().percent
        path = "C:\\" if platform.system() == "Windows" else "/"
        disk = psutil.disk_usage(path).percent
        battery = psutil.sensors_battery()
        bat_percent = battery.percent if battery else 100

        return {
            "cpu": int(cpu),
            "ram": int(ram),
            "disk": int(disk),
            "battery": int(bat_percent)
        }
    except Exception as e:
        return {"cpu": 0, "ram": 0, "disk": 0, "battery": 100}


def capture_screen_base64():
    """Captures screen, resizes, and converts to base64 string"""
    try:
        # Take screenshot
        screenshot = pyautogui.screenshot()
        # Resize to 800px width for fast upload to Vercel
        width, height = screenshot.size
        new_size = (800, int(800 * height / width))
        screenshot = screenshot.resize(new_size, Image.Resampling.LANCZOS)

        # Save to buffer as low-quality JPEG
        buffer = BytesIO()
        screenshot.save(buffer, format="JPEG", quality=40)
        return base64.b64encode(buffer.getvalue()).decode('utf-8')
    except Exception as e:
        print(f"Screenshot Error: {e}")
        return None


def remote_view_loop(serial):
    """Sends screen updates to the server for a limited time"""
    global remote_view_active
    print("🖥️ Starting Remote View Mode...")
    # Runs for roughly 2 minutes (60 frames) then auto-stops to save bandwidth
    for _ in range(60):
        if not remote_view_active: break

        img_b64 = capture_screen_base64()
        if img_b64:
            try:
                requests.post(f"{SERVER_URL}/screen-upload", json={
                    "id": serial,
                    "image": img_b64
                }, headers={"X-API-KEY": API_SECRET_KEY}, timeout=5)
            except:
                pass
        time.sleep(2)  # Send a frame every 2 seconds

    remote_view_active = False
    print("🖥️ Remote View Mode Stopped.")


def execute_task(serial, command):
    global remote_view_active

    # Handle Special Hard UEM Commands
    if command == "SCREEN_ON":
        if not remote_view_active:
            remote_view_active = True
            # We run this in a simple loop here.
            # In a pro version, we'd use a Thread.
            remote_view_loop(serial)
        return

    if command == "SCREEN_OFF":
        remote_view_active = False
        return

    print(f"🚀 EXECUTING COMMAND: {command}")
    try:
        process = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=30)
        output = process.stdout + process.stderr
        status = "success" if process.returncode == 0 else "failed"
        if not output: output = "Command finished with no text output."
    except Exception as e:
        output, status = str(e), "failed"

    try:
        requests.post(f"{SERVER_URL}/report-result", json={
            "id": serial, "output": output, "status": status
        }, headers={"X-API-KEY": API_SECRET_KEY}, timeout=10)
    except:
        pass


def main():
    serial = get_serial()
    print(f"--- Hard UEM Agent Active ---")
    print(f"Device ID: {serial}")
    print(f"Connecting to: {SERVER_URL}")

    while True:
        stats = get_telemetry()
        payload = {
            "id": serial,
            "hostname": platform.node(),
            "platform": "Windows" if platform.system() == "Windows" else "Mac",
            "cpu_usage": stats['cpu'],
            "ram_usage": stats['ram'],
            "disk_usage": stats['disk'],
            "battery_level": stats['battery']
        }

        try:
            print(f"[ {time.strftime('%H:%M:%S')} ] Checking in...")
            r = requests.post(f"{SERVER_URL}/checkin", json=payload,
                              headers={"X-API-KEY": API_SECRET_KEY}, timeout=30)

            if r.status_code == 200:
                cmd = r.json().get("command")
                if cmd:
                    execute_task(serial, cmd)
                else:
                    print("Idle (No pending commands)")
            else:
                print(f"Server Response: {r.status_code}")

        except Exception as e:
            print(f"Connection error: {e}")

        time.sleep(60)


if __name__ == "__main__":
    main()