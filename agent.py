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
import hashlib

# --- CONFIGURATION ---
SERVER_URL = "https://uem-ten.vercel.app"
API_KEY = "7f9c2e4b8a1d5f306e92b8d4c1a7e5f93b0a2d6c4e8f1b9a7d3c5e0b2f4a6d8c"


def get_cpu_id():
    """Extracts unique physical CPU Signature identifier"""
    try:
        if platform.system() == "Windows":
            cmd = "(Get-CimInstance -ClassName Win32_Processor).ProcessorId"
            return subprocess.check_output(["powershell", "-Command", cmd], shell=True).decode().strip()
        elif platform.system() == "Darwin":
            return subprocess.check_output("sysctl -n machdep.cpu.signature", shell=True).decode().strip()
        else:
            return subprocess.check_output("grep -m1 'flags' /proc/cpuinfo", shell=True).decode().strip()
    except:
        return "N/A"


def get_hw_sensors():
    """ITAM / HWMonitor: Gathers system core thermal parameters"""
    sensors = {"temperatures": {}}
    try:
        if platform.system() == "Windows":
            try:
                # Queries physical ACPI thermal sensor zones
                cmd = "(Get-CimInstance -Namespace root/wmi -ClassName MsAcpi_ThermalZoneTemperature).CurrentTemperature"
                output = subprocess.check_output(["powershell", "-Command", cmd], shell=True).decode().strip()
                if output:
                    raw_temps = [float(p) for p in output.split() if p.isdigit()]
                    if raw_temps:
                        # Converts tenths of Kelvin into Celsius
                        celsius = round((raw_temps[0] / 10.0) - 273.15, 1)
                        sensors["temperatures"]["System Core"] = f"{celsius} °C"
            except:
                pass
        else:
            # POSIX fallback
            if hasattr(psutil, "sensors_temperatures"):
                temps = psutil.sensors_temperatures()
                for name, entries in temps.items():
                    if entries:
                        sensors["temperatures"][name] = f"{entries[0].current} °C"
    except Exception as e:
        print(f"Diagnostics Error: {e}")
    return sensors


def get_unique_id():
    try:
        if platform.system() == "Windows":
            cmd = "(Get-CimInstance -ClassName Win32_BIOS).SerialNumber"
            raw_serial = subprocess.check_output(["powershell", "-Command", cmd], shell=True).decode().strip()
        else:
            raw_serial = subprocess.check_output("ioreg -l | grep IOPlatformSerialNumber", shell=True).decode().split('"')[-2]

        if not raw_serial or any(x in raw_serial.upper() for x in ["0000", "O.E.M", "FILL"]):
            raw_serial = str(uuid.getnode())

        combined = f"{raw_serial}-{platform.node()}"
        unique_hash = hashlib.md5(combined.encode()).hexdigest()[:12].upper()
        return f"CCI-{unique_hash}"
    except:
        return f"CCI-TEMP-{platform.node()}"


def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        s.close()
        return local_ip
    except:
        return "127.0.0.1"


def get_public_ip():
    try:
        return requests.get('https://api.ipify.org', timeout=5).text
    except:
        return "Unknown"


def get_rustdesk_id():
    paths = [
        os.path.expandvars(r'C:\Windows\ServiceProfiles\LocalService\AppData\Roaming\RustDesk\config\core.toml'),
        os.path.expandvars(r'%APPDATA%\RustDesk\config\core.toml'),
        os.path.expandvars(r'C:\ProgramData\RustDesk\config\core.toml'),
        os.path.expanduser('~/.config/rustdesk/RustDesk2.toml'),
        os.path.expanduser('~/Library/Application Support/RustDesk/config/core.toml')
    ]
    for path in paths:
        if os.path.exists(path):
            try:
                with open(path, 'r') as f:
                    for line in f:
                        if 'id =' in line:
                            return line.split('=')[1].strip().replace('"', '').replace("'", "")
            except:
                continue
    return "Not Detected"


def get_software_list():
    apps = []
    try:
        if platform.system() == "Windows":
            cmd = 'powershell "Get-ItemProperty HKLM:\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\*, HKLM:\\SOFTWARE\\WOW6432Node\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\* | Select-Object DisplayName, DisplayVersion, Publisher | ConvertTo-Json"'
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
    try:
        if command == "REBOOT":
            subprocess.run("shutdown /r /t 10" if platform.system() == "Windows" else "reboot", shell=True)
            return
        elif command == "SHUTDOWN":
            subprocess.run("shutdown /s /t 10" if platform.system() == "Windows" else "shutdown -h now", shell=True)
            return
        elif command.startswith("INSTALL|"):
            pass
        else:
            proc = subprocess.run(command, shell=True, capture_output=True, text=True)
            output = proc.stdout if proc.stdout else proc.stderr
            session.post(f"{SERVER_URL}/report-result", json={
                "id": serial, "command": command, "output": output if output else "Done (No Output)"
            })
    except Exception as e:
        session.post(f"{SERVER_URL}/report-result", json={"id": serial, "command": command, "output": str(e)})


def get_detailed_info(machine_id):
    total_ram = round(psutil.virtual_memory().total / (1024 ** 3), 2)

    return {
        "id": machine_id,
        "rustdesk_id": get_rustdesk_id(),
        "hostname": platform.node(),
        "platform": f"{platform.system()} {platform.release()}",
        "os_version": platform.version(),
        "username": getpass.getuser(),
        "ip_address": get_local_ip(),
        "public_ip": get_public_ip(),
        "mac_address": ':'.join(['{:02x}'.format((uuid.getnode() >> ele) & 0xff) for ele in range(0, 8 * 6, 8)][::-1]),
        "cpu_model": platform.processor(),
        "cpu_id": get_cpu_id(),               # Added CPU ID
        "hw_sensors": get_hw_sensors(),       # Added thermal diagnostics
        "cpu_cores": psutil.cpu_count(logical=False),
        "ram_total": f"{total_ram} GB",
        "uptime": f"{int((time.time() - psutil.boot_time()) // 3600)}h",
        "cpu_usage": int(psutil.cpu_percent()),
        "ram_usage": int(psutil.virtual_memory().percent),
        "disk_usage": int(psutil.disk_usage('/').percent),
        "battery_level": int(psutil.sensors_battery().percent) if psutil.sensors_battery() else 100
    }


def main():
    machine_id = get_unique_id()
    print(f"CCI.UEM Agent Initialized. Identity: {machine_id}")
    print(f"CCI.UEM Agent Handshake established. Gateway target: {SERVER_URL}")

    session = requests.Session()
    session.headers.update({"X-API-KEY": API_KEY})

    last_software_scan = 0

    while True:
        try:
            payload = get_detailed_info(machine_id)

            if time.time() - last_software_scan > 3600:
                print("Performing Asset Software Audit...")
                payload["software_list"] = get_software_list()
                last_software_scan = time.time()

            r = session.post(f"{SERVER_URL}/checkin", json=payload, timeout=15)

            if r.status_code == 200:
                cmd = r.json().get("command")
                if cmd:
                    print(f"Protocol Received: {cmd}")
                    handle_uem_command(cmd, session, machine_id)
            else:
                print(f"Gateway Error Code: {r.status_code}")

        except requests.exceptions.ConnectionError:
            print("[WARNING] Connection lost to Vercel gateway. Retrying in 30 seconds...")
            time.sleep(10)
        except Exception as e:
            print(f"Handshake Interrupted: {e}")

        time.sleep(20)


if __name__ == "__main__":
    main()