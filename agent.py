import requests
import platform
import subprocess
import time
import psutil
import socket
import getpass
import uuid
import os
import json

# --- CONFIGURATION ---
SERVER_URL = "https://uem-ten.vercel.app"
API_KEY = "7f9c2e4b8a1d5f306e92b8d4c1a7e5f93b0a2d6c4e8f1b9a7d3c5e0b2f4a6d8c"


def get_serial():
    try:
        if platform.system() == "Windows":
            return subprocess.check_output("powershell (Get-CimInstance -ClassName Win32_BIOS).SerialNumber",
                                           shell=True).decode().strip()
        return subprocess.check_output("ioreg -l | grep IOPlatformSerialNumber", shell=True).decode().split('"')[-2]
    except:
        return f"ID-{platform.node()}"


def get_rustdesk_id():
    """Finds the RustDesk ID from local configuration files"""
    paths = [
        os.path.expandvars(r'C:\Windows\ServiceProfiles\LocalService\AppData\Roaming\RustDesk\config\core.toml'),
        os.path.expandvars(r'%APPDATA%\RustDesk\config\core.toml'),
        os.path.expandvars(r'C:\ProgramData\RustDesk\config\core.toml'),
        os.path.expanduser('~/.config/rustdesk/RustDesk2.toml'),  # Linux
        os.path.expanduser('~/Library/Application Support/RustDesk/config/core.toml')  # macOS
    ]
    for path in paths:
        if os.path.exists(path):
            try:
                with open(path, 'r') as f:
                    for line in f:
                        if 'id =' in line:
                            # Extracts value between quotes or after equals sign
                            return line.split('=')[1].strip().replace('"', '').replace("'", "")
            except:
                continue
    return "Not Detected"


def get_software_list():
    """ITAM: Scans for installed software"""
    apps = []
    try:
        if platform.system() == "Windows":
            cmd = 'powershell "Get-ItemProperty HKLM:\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\* | Select-Object DisplayName, DisplayVersion, Publisher | ConvertTo-Json"'
            output = subprocess.check_output(cmd, shell=True).decode(errors='ignore')
            if output:
                raw_apps = json.loads(output)
                if isinstance(raw_apps, dict): raw_apps = [raw_apps]
                for app in raw_apps:
                    if app.get("DisplayName"):
                        apps.append({
                            "app_name": app.get("DisplayName"),
                            "version": app.get("DisplayVersion"),
                            "publisher": app.get("Publisher")
                        })
    except Exception as e:
        print(f"Software Scan Error: {e}")
    return apps


def handle_uem_command(command, session, serial):
    """Processes Remote Ops, Auto-Installers, and Terminal Feedback"""
    try:
        # 1. Remote Power Ops
        if command == "REBOOT":
            print("UEM: System Reboot Initiated...")
            subprocess.run("shutdown /r /t 10" if platform.system() == "Windows" else "reboot", shell=True)
            return

        elif command == "SHUTDOWN":
            print("UEM: System Shutdown Initiated...")
            subprocess.run("shutdown /s /t 10" if platform.system() == "Windows" else "shutdown -h now", shell=True)
            return

        # 2. Auto-Installer Logic
        elif command.startswith("INSTALL|"):
            _, url, silent_switch = command.split("|")
            filename = url.split("/")[-1]
            temp_path = os.path.join(os.environ.get('TEMP', '/tmp'), filename)

            print(f"UEM: Downloading {filename}...")
            r = requests.get(url)
            with open(temp_path, 'wb') as f:
                f.write(r.content)

            print(f"UEM: Executing Silent Install...")
            full_cmd = f'"{temp_path}" {silent_switch}'
            subprocess.run(full_cmd, shell=True)

            # Report result
            session.post(f"{SERVER_URL}/report-result", json={
                "id": serial, "command": f"Install {filename}", "output": "Installation process executed."
            })
            return

        # 3. Standard Terminal Commands with Feedback
        else:
            print(f"UEM: Executing Shell Command -> {command}")
            proc = subprocess.run(command, shell=True, capture_output=True, text=True)
            output = proc.stdout if proc.stdout else proc.stderr

            # Post the terminal output back to the server for the dashboard
            session.post(f"{SERVER_URL}/report-result", json={
                "id": serial,
                "command": command,
                "output": output if output else "Command executed (No output)."
            })
            print(f"UEM: Result reported to server.")

    except Exception as e:
        error_msg = f"Execution Error: {str(e)}"
        session.post(f"{SERVER_URL}/report-result", json={"id": serial, "command": command, "output": error_msg})


def get_detailed_info():
    """Telemetry: Gathers PC details including RustDesk ID"""
    total_ram = round(psutil.virtual_memory().total / (1024 ** 3), 2)
    mac = ':'.join(['{:02x}'.format((uuid.getnode() >> ele) & 0xff) for ele in range(0, 8 * 6, 8)][::-1])

    return {
        "id": get_serial(),
        "rustdesk_id": get_rustdesk_id(),  # Added for the Dashboard Remote Link
        "hostname": platform.node(),
        "platform": f"{platform.system()} {platform.release()}",
        "os_version": platform.version(),
        "username": getpass.getuser(),
        "ip_address": socket.gethostbyname(socket.gethostname()),
        "mac_address": mac,
        "cpu_model": platform.processor(),
        "cpu_cores": psutil.cpu_count(logical=False),
        "ram_total": f"{total_ram} GB",
        "uptime": f"{int((time.time() - psutil.boot_time()) // 3600)}h",
        "cpu_usage": int(psutil.cpu_percent()),
        "ram_usage": int(psutil.virtual_memory().percent),
        "disk_usage": int(psutil.disk_usage('/').percent),
        "battery_level": int(psutil.sensors_battery().percent) if psutil.sensors_battery() else 100
    }


def main():
    print(f"CCI.UEM Agent Active. Node: {platform.node()}")
    session = requests.Session()
    session.headers.update({"X-API-KEY": API_KEY})

    last_software_scan = 0
    serial = get_serial()

    while True:
        try:
            payload = get_detailed_info()

            # ITAM: Full scan every hour
            if time.time() - last_software_scan > 3600:
                payload["software_list"] = get_software_list()
                last_software_scan = time.time()

            # Heartbeat check-in
            r = session.post(f"{SERVER_URL}/checkin", json=payload, timeout=15)

            # Handle commands if any
            cmd = r.json().get("command")
            if cmd:
                handle_uem_command(cmd, session, serial)

        except Exception as e:
            print(f"Server Offline or Connection Error: {e}")

        time.sleep(20)


if __name__ == "__main__":
    main()