import requests
import platform
import subprocess
import time
import os
import psutil

# --- CONFIG ---
# If running on the same computer as server.py, use "http://127.0.0.1:5000"
# If running on a different computer, use "http://SERVER_IP_ADDRESS:5000"
SERVER_URL = "http://127.0.0.1:5000"

# MUST match your server.py key exactly
API_SECRET_KEY = "7f9c2e4b8a1d5f306e92b8d4c1a7e5f93b0a2d6c4e8f1b9a7d3c5e0b2f4a6d8c"


def get_serial():
    system = platform.system()
    try:
        if system == "Windows":
            # Using a more robust PowerShell command for Windows Serial
            cmd = "powershell (Get-CimInstance -ClassName Win32_BIOS).SerialNumber"
            return subprocess.check_output(cmd, shell=True).decode().strip()
        elif system == "Darwin":  # macOS
            cmd = "ioreg -l | grep IOPlatformSerialNumber | awk -F'\"' '{print $4}'"
            return subprocess.check_output(cmd, shell=True).decode().strip()
    except:
        return "UNKNOWN_SERIAL"


def get_telemetry():
    """Collects the 'Hard UEM' stats for the dashboard"""
    # CPU usage over 1 second
    cpu = psutil.cpu_percent(interval=1)

    # RAM usage percentage
    ram = psutil.virtual_memory().percent

    # DISK usage percentage
    # Windows needs C:\\, Mac/Linux needs /
    path = "C:\\" if platform.system() == "Windows" else "/"
    try:
        disk = psutil.disk_usage(path).percent
    except:
        disk = 0

    # Battery percentage
    battery = psutil.sensors_battery()
    bat_percent = battery.percent if battery and battery.percent else 100

    return {
        "cpu": int(cpu),
        "ram": int(ram),
        "disk": int(disk),
        "battery": int(bat_percent)
    }


def run_command_and_report(serial, command):
    """Runs a command and sends the text output back to the server"""
    print(f"Executing: {command}")
    try:
        # Capture the output (stdout) and errors (stderr)
        process = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=30)
        output = process.stdout + process.stderr
        status = "success" if process.returncode == 0 else "failed"

        if not output:
            output = "Command executed (No output)"

    except Exception as e:
        output = str(e)
        status = "failed"

    # Report back the result of the command
    try:
        headers = {"X-API-KEY": API_SECRET_KEY}
        requests.post(f"{SERVER_URL}/report-result", json={
            "id": serial,
            "output": output,
            "status": status
        }, headers=headers)
    except:
        print("Could not send command report to server.")


def main():
    serial = get_serial()
    print(f"Hard UEM Agent Active. ID: {serial}")

    while True:
        # 1. Get Telemetry
        stats = get_telemetry()

        # 2. Build Check-in Payload
        payload = {
            "id": serial,
            "hostname": platform.node(),
            "platform": "Windows" if platform.system() == "Windows" else "Mac",
            "os_version": platform.platform(),
            "cpu_usage": stats['cpu'],
            "ram_usage": stats['ram'],
            "disk_usage": stats['disk'],
            "battery_level": stats['battery']
        }

        try:
            # 3. Check-in to Server
            headers = {"X-API-KEY": API_SECRET_KEY}
            r = requests.post(f"{SERVER_URL}/checkin", json=payload, headers=headers, timeout=10)

            if r.status_code == 200:
                cmd = r.json().get("command")
                if cmd:
                    run_command_and_report(serial, cmd)
            else:
                print(f"Check-in failed with status: {r.status_code}")

        except Exception as e:
            print(f"Connection Error: {e}")

        # Wait 60 seconds (1 minute) before next check-in
        time.sleep(60)


if __name__ == "__main__":
    main()