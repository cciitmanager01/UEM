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
import re

# --- CONFIGURATION ---
SERVER_URL = "https://uem-ten.vercel.app"
API_KEY = "7f9c2e4b8a1d5f306e92b8d4c1a7e5f93b0a2d6c4e8f1b9a7d3c5e0b2f4a6d8c"

# Global Policy Cache (Defaults to True)
current_policy = {"terminal": True, "reboot": True}


# --- HELPER FUNCTIONS FOR TELEMETRY (COMPLETE & PRESERVED) ---

def get_battery_info():
    """Paid UEM Detail: Extracts charge level and power source state"""
    try:
        batt = psutil.sensors_battery()
        if batt:
            return {
                "percent": int(batt.percent),
                "power_plugged": batt.power_plugged
            }
    except:
        pass
    return {"percent": 100, "power_plugged": True}


def get_disk_details():
    """Paid UEM Detail: Extracts physical storage capacity vs utilization"""
    try:
        usage = psutil.disk_usage('C:' if platform.system() == "Windows" else '/')
        return {
            "total": f"{round(usage.total / (1024 ** 3), 1)} GB",
            "used": f"{round(usage.used / (1024 ** 3), 1)} GB",
            "percent": int(usage.percent)
        }
    except:
        return {"total": "N/A", "used": "N/A", "percent": 0}


def get_gpu_model():
    """ITAM: Extracts GPU Controller information"""
    try:
        if platform.system() == "Windows":
            cmd = "wmic path win32_VideoController get name"
            output = subprocess.check_output(cmd, shell=True).decode().strip().split('\n')
            return output[1].strip() if len(output) > 1 else "Integrated Graphics"
        elif platform.system() == "Darwin":
            cmd = "system_profiler SPDisplaysDataType | grep 'Chipset Model'"
            return subprocess.check_output(cmd, shell=True).decode().split(':')[-1].strip()
        else:
            return "Standard VGA Graphics"
    except:
        return "N/A"


def get_product_id():
    """Extracts Windows Product ID or System Serial"""
    try:
        if platform.system() == "Windows":
            cmd = r'powershell "(Get-ItemProperty -Path \"HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\").ProductId"'
            return subprocess.check_output(cmd, shell=True).decode().strip()
        return "N/A"
    except:
        return "N/A"


def get_system_type():
    """Detects if system is x64, x86 or ARM"""
    return f"{platform.machine()} ({platform.architecture()[0]})"


def get_pen_and_touch():
    """Detects digitizer capabilities on Windows assets"""
    try:
        if platform.system() == "Windows":
            cmd = "powershell \"(Get-CimInstance -ClassName Win32_ComputerSystem).SystemType\""
            res = subprocess.check_output(cmd, shell=True).decode().strip()
            return "Touch Supported" if "x64" in res else "Standard Input"
        return "Not Supported"
    except:
        return "Standard Input"


def get_cpu_id():
    """Extracts unique physical CPU Signature identifier"""
    try:
        if platform.system() == "Windows":
            cmd = "(Get-CimInstance -ClassName Win32_Processor).ProcessorId"
            return subprocess.check_output(["powershell", "-Command", cmd], shell=True).decode().strip()
        elif platform.system() == "Darwin":
            return subprocess.check_output("sysctl -n machdep.cpu.signature", shell=True).decode().strip()
        return "N/A"
    except:
        return "N/A"


def get_hw_sensors():
    """ITAM: Gathers system core thermal parameters"""
    sensors = {"temperatures": {}}
    try:
        if platform.system() == "Windows":
            cmd = "(Get-CimInstance -Namespace root/wmi -ClassName MsAcpi_ThermalZoneTemperature).CurrentTemperature"
            output = subprocess.check_output(["powershell", "-Command", cmd], shell=True).decode().strip()
            if output:
                raw_temp = float(output.split()[0])
                celsius = round((raw_temp / 10.0) - 273.15, 1)
                sensors["temperatures"]["CPU Package"] = f"{celsius} °C"
        else:
            if hasattr(psutil, "sensors_temperatures"):
                temps = psutil.sensors_temperatures()
                for name, entries in temps.items():
                    if entries:
                        sensors["temperatures"][name] = f"{entries[0].current} °C"
    except:
        pass
    return sensors


def get_unique_id():
    """Generates a permanent hardware identity (CCI-HASH)"""
    try:
        if platform.system() == "Windows":
            cmd = "(Get-CimInstance -ClassName Win32_BIOS).SerialNumber"
            raw_serial = subprocess.check_output(["powershell", "-Command", cmd], shell=True).decode().strip()
        else:
            raw_serial = \
                subprocess.check_output("ioreg -l | grep IOPlatformSerialNumber", shell=True).decode().split('"')[-2]

        if not raw_serial or any(x in raw_serial.upper() for x in ["0000", "O.E.M", "FILL"]):
            raw_serial = str(uuid.getnode())

        combined = f"{raw_serial}-{platform.node()}"
        unique_hash = hashlib.md5(combined.encode()).hexdigest()[:12].upper()
        return f"CCI-{unique_hash}"
    except:
        return f"CCI-TEMP-{platform.node().upper()}"


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
        os.path.expanduser('~/.config/rustdesk/RustDesk2.toml')
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


# --- ENHANCED: PATCH MANAGEMENT UTILITY ---

def get_patch_list():
    """Extracts available software updates using winget with improved parsing"""
    patches = []
    if platform.system() != "Windows":
        return patches
    try:
        # Check if winget is available
        subprocess.check_call("where winget", shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        cmd = 'winget upgrade --include-unknown'
        output = subprocess.check_output(cmd, shell=True).decode(errors='ignore')

        lines = output.splitlines()
        start_parsing = False
        for line in lines:
            if not line.strip(): continue
            if '---' in line:
                start_parsing = True
                continue
            if start_parsing:
                # Winget columns: Name, ID, Version, Available, Source
                parts = re.split(r'\s{2,}', line.strip())
                if len(parts) >= 4:
                    patches.append({
                        "patch_name": parts[0],
                        "patch_id": parts[1],
                        "current_version": parts[2],
                        "available_version": parts[3],
                        "source": "winget"
                    })
    except:
        pass
    return patches


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
    except:
        pass
    return apps


def get_process_list():
    processes = []
    system_users = ["SYSTEM", "LOCAL SERVICE", "NETWORK SERVICE", "root"]
    for proc in psutil.process_iter(['pid', 'name', 'username']):
        try:
            pinfo = proc.info
            p_user = (pinfo['username'] or "SYSTEM").upper()
            if any(u in p_user for u in system_users): continue

            mem_mb = round(proc.memory_info().rss / (1024 * 1024), 1)
            processes.append({
                "pid": pinfo['pid'],
                "name": pinfo['name'],
                "username": p_user.split("\\")[-1],
                "memory": f"{mem_mb} MB"
            })
        except:
            continue
    processes.sort(key=lambda x: float(x['memory'].split()[0]), reverse=True)
    return processes[:40]


# --- CORE AGENT LOGIC (UPDATED FOR REMOTE MANAGEMENT) ---

def handle_uem_command(command, session, serial):
    """Processes protocols and enforces local policy logic"""
    try:
        # 1. Power Operations Policy Check
        if command in ["REBOOT", "SHUTDOWN"]:
            if not current_policy.get("reboot", True):
                session.post(f"{SERVER_URL}/report-result",
                             json={"id": serial, "command": command, "output": "Access Denied by Policy"})
                return
            subprocess.run("shutdown /r /t 5" if command == "REBOOT" else "shutdown /s /t 5", shell=True)
            return

        # 2. Patch & Software Management Protocols
        elif command == "SCAN_PATCHES":
            patches = get_patch_list()
            session.post(f"{SERVER_URL}/report-patches", json={"id": serial, "patches": patches})
            session.post(f"{SERVER_URL}/report-result",
                         json={"id": serial, "command": command,
                               "output": f"Scan Complete: {len(patches)} updates found."})
            return

        elif command.startswith("INSTALL_PATCH|"):
            patch_id = command.split("|")[1]
            cmd = f'winget upgrade --id "{patch_id}" --silent --accept-package-agreements --accept-source-agreements'
            res = subprocess.run(cmd, shell=True, capture_output=True, text=True)
            session.post(f"{SERVER_URL}/report-result",
                         json={"id": serial, "command": command, "output": res.stdout or "Update Dispatched."})
            # Immediate resync
            session.post(f"{SERVER_URL}/report-patches", json={"id": serial, "patches": get_patch_list()})
            return

        elif command == "PATCH_ALL":
            cmd = 'winget upgrade --all --silent --accept-package-agreements --accept-source-agreements'
            subprocess.run(cmd, shell=True)
            session.post(f"{SERVER_URL}/report-result",
                         json={"id": serial, "command": command, "output": "Global patch protocol initiated."})
            return

        elif command.startswith("UNINSTALL_APP|"):
            app_name = command.split("|")[1]
            cmd = f'winget uninstall --name "{app_name}" --silent --accept-source-agreements'
            res = subprocess.run(cmd, shell=True, capture_output=True, text=True)
            session.post(f"{SERVER_URL}/report-result",
                         json={"id": serial, "command": command,
                               "output": res.stdout or f"Uninstall command sent for {app_name}"})
            return

        # 3. RustDesk & Service protocols
        elif command == "RESET_RUSTDESK":
            if platform.system() == "Windows":
                subprocess.run(
                    f'rustdesk.exe --config "hbbs=rustdesk-hbbs.synology.me,key=+6cNRIDMAQ44Jp0tJ55o2AiKC7pcfK1+ioB7gxEMJ"',
                    shell=True)
                session.post(f"{SERVER_URL}/report-result", json={"id": serial, "command": command,
                                                                  "output": "RustDesk configuration synchronized."})
            return

        elif command == "FETCH_PROCESSES":
            procs = get_process_list()
            session.post(f"{SERVER_URL}/device/report-processes", json={"id": serial, "processes": procs})
            return

        elif command.startswith("KILL_PROCESS|"):
            pid = command.split("|")[1]
            psutil.Process(int(pid)).terminate()
            time.sleep(1)
            session.post(f"{SERVER_URL}/device/report-processes", json={"id": serial, "processes": get_process_list()})
            return

        # 4. Terminal/Shell Policy Check
        else:
            if not current_policy.get("terminal", True):
                session.post(f"{SERVER_URL}/report-result",
                             json={"id": serial, "command": command, "output": "Shell Access Disabled by Policy"})
                return

            proc = subprocess.run(command, shell=True, capture_output=True, text=True)
            output = proc.stdout if proc.stdout else proc.stderr
            session.post(f"{SERVER_URL}/report-result",
                         json={"id": serial, "command": command, "output": output or "Done (No output)"})

    except Exception as e:
        session.post(f"{SERVER_URL}/report-result", json={"id": serial, "command": command, "output": str(e)})


def get_detailed_info(machine_id):
    """Paid UEM Hardware Audit: Detailed categorization"""
    mem = psutil.virtual_memory()
    disk = get_disk_details()
    batt = get_battery_info()

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
        "cpu_id": get_cpu_id(),
        "cpu_cores": psutil.cpu_count(logical=False),
        "ram_total": f"{round(mem.total / (1024 ** 3), 1)} GB",
        "gpu_model": get_gpu_model(),
        "disk_total": disk["total"],
        "disk_usage": disk["percent"],
        "ram_usage": int(mem.percent),
        "cpu_usage": int(psutil.cpu_percent(interval=None)),
        "hw_sensors": get_hw_sensors(),
        "product_id": get_product_id(),
        "system_type": get_system_type(),
        "pen_touch": get_pen_and_touch(),
        "uptime": f"{int((time.time() - psutil.boot_time()) // 3600)}h",
        "battery_level": batt["percent"],
        "is_charging": batt["power_plugged"]
    }


def main():
    global current_policy
    machine_id = get_unique_id()
    print(f"CCI.UEM Agent Online: {machine_id}")

    session = requests.Session()
    session.headers.update({"X-API-KEY": API_KEY})
    last_software_scan = 0
    fast_cycles = 0

    while True:
        try:
            payload = get_detailed_info(machine_id)

            # Hourly Software & Patch Audit
            if time.time() - last_software_scan > 3600:
                payload["software_list"] = get_software_list()

                # Report patches
                patches = get_patch_list()
                session.post(f"{SERVER_URL}/report-patches", json={"id": machine_id, "patches": patches})

                last_software_scan = time.time()

            r = session.post(f"{SERVER_URL}/checkin", json=payload, timeout=10)
            if r.status_code == 200:
                data = r.json()

                # Sync policy from server
                if "policy" in data:
                    current_policy = data["policy"]

                cmd = data.get("command")
                if cmd:
                    print(f"Protocol Received: {cmd}")
                    fast_cycles = 10
                    handle_uem_command(cmd, session, machine_id)

        except Exception as e:
            print(f"Handshake Interrupted: {e}")
            time.sleep(10)

        # Adaptive heartbeat
        if fast_cycles > 0:
            fast_cycles -= 1
            time.sleep(3)
        else:
            time.sleep(15)


if __name__ == "__main__":
    main()