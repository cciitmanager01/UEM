import requests
import platform
import subprocess
import time
import os
import psutil

# ================= CONFIGURATION =================
# 1. Your Vercel URL (NO trailing slash)
SERVER_URL = "https://your-project-name.vercel.app"

# 2. This MUST match the API_SECRET_KEY in your server.py exactly
API_SECRET_KEY = "7f9c2e4b8a1d5f306e92b8d4c1a7e5f93b0a2d6c4e8f1b9a7d3c5e0b2f4a6d8c"


# =================================================

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
        cpu = psutil.cpu_percent(interval=1)
        ram = psutil.virtual_memory().percent

        # Disk detection
        path = "C:\\" if platform.system() == "Windows" else "/"
        disk = psutil.disk_usage(path).percent

        # Battery detection
        battery = psutil.sensors_battery()
        bat_percent = battery.percent if battery else 100

        return {
            "cpu": int(cpu),
            "ram": int(ram),
            "disk": int(disk),
            "battery": int(bat_percent)
        }
    except Exception as e:
        print(f"Telemetry Error: {e}")
        return {"cpu": 0, "ram": 0, "disk": 0, "battery": 100}


def execute_task(serial, command):
    """Runs a command from the dashboard and reports the result"""
    print(f"🚀 EXECUTING COMMAND: {command}")
    try:
        # Run command with 30-second timeout
        process = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=30)
        output = process.stdout + process.stderr
        status = "success" if process.returncode == 0 else "failed"
        if not output: output = "Command finished with no text output."
    except Exception as e:
        output = str(e)
        status = "failed"

    # Report back to Vercel
    try:
        headers = {"X-API-KEY": API_SECRET_KEY}
        requests.post(f"{SERVER_URL}/report-result", json={
            "id": serial,
            "output": output,
            "status": status
        }, headers=headers, timeout=10)
        print("✅ Result reported to dashboard.")
    except:
        print("❌ Failed to send result report.")


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
            print(f"\n[ {time.strftime('%H:%M:%S')} ] Checking in...")
            headers = {"X-API-KEY": API_SECRET_KEY}

            # Note: Timeout is 30s because Vercel "Cold Starts" take time
            r = requests.post(f"{SERVER_URL}/checkin", json=payload, headers=headers, timeout=30)

            print(f"Response Code: {r.status_code}")

            if r.status_code == 200:
                data = r.json()
                cmd = data.get("command")
                if cmd:
                    execute_task(serial, cmd)
                else:
                    print("Idle (No pending commands)")
            elif r.status_code == 401:
                print("❌ ERROR: API Secret Key mismatch! Check your keys.")
            else:
                print(f"❌ SERVER ERROR: {r.text}")

        except requests.exceptions.Timeout:
            print("❌ TIMEOUT: Vercel is waking up, will retry...")
        except Exception as e:
            print(f"❌ CONNECTION ERROR: {e}")

        # Wait 60 seconds
        time.sleep(60)


if __name__ == "__main__":
    main()