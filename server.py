import datetime
import os
import jwt
import traceback
from flask import Flask, render_template, request, jsonify, redirect, session, url_for
from supabase import create_client
from functools import wraps

app = Flask(__name__)

# --- SECURITY CONFIGURATION ---
app.secret_key = "secure_uem_vault_key_99"
app.config['SESSION_PERMANENT'] = True
app.config['PERMANENT_SESSION_LIFETIME'] = datetime.timedelta(hours=8)

# --- SUPABASE CONFIGURATION ---
SUPABASE_URL = "https://wvpjnrzmpdswhjnkskbb.supabase.co"
# IMPORTANT: It is highly recommended to replace this with your 'service_role' key
# to bypass RLS and allow table writes on the Vercel server.
SUPABASE_KEY = "sb_publishable_OLTq7mUEIiRSSZ09ZOud4g_HznmliBj"
API_SECRET_KEY = "7f9c2e4b8a1d5f306e92b8d4c1a7e5f93b0a2d6c4e8f1b9a7d3c5e0b2f4a6d8c"

# MeshCentral (Optional)
MESH_SERVER_URL = "https://mesh.yourdomain.com"
MESH_TOKEN_KEY = "YourRandomSecretKey"

# LOGIN CREDENTIALS
ADMIN_USER = "admin"
ADMIN_PASS = "admin"
ADMIN_PIN = "3300"

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# --- AUTH DECORATORS ---

def pin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('pin_verified'):
            return redirect(url_for('verify_pin'))
        return f(*args, **kwargs)
    return decorated_function

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('pin_verified'):
            return redirect(url_for('verify_pin'))
        if not session.get('logged_in'):
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

# --- AUTH ROUTES ---

@app.route('/verify-pin', methods=['GET', 'POST'])
def verify_pin():
    if session.get('pin_verified'): return redirect(url_for('login'))
    error = None
    if request.method == 'POST':
        input_pin = request.form.get('pin')
        if str(input_pin) == str(ADMIN_PIN):
            session.permanent = True
            session['pin_verified'] = True
            return redirect(url_for('login'))
        error = "Invalid Security PIN"
    return render_template('pin.html', error=error)

@app.route('/login', methods=['GET', 'POST'])
@pin_required
def login():
    if session.get('logged_in'): return redirect(url_for('index'))
    error = None
    if request.method == 'POST':
        user = request.form.get('username')
        pw = request.form.get('password')
        if user == ADMIN_USER and pw == ADMIN_PASS:
            session['logged_in'] = True
            return redirect(url_for('index'))
        error = "Invalid Credentials"
    return render_template('login.html', error=error)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('verify_pin'))

# --- MAIN DASHBOARD & ASSET MANAGEMENT ---

@app.route('/')
@login_required
def index():
    try:
        devices_resp = supabase.table("devices").select("*").execute()
        devices = devices_resp.data or []

        # Stats logic
        stats = {"total": len(devices), "online": 0, "win": 0, "mac": 0}
        now = datetime.datetime.now(datetime.timezone.utc)

        for d in devices:
            plat = d.get('platform', '')
            if 'Windows' in plat:
                stats['win'] += 1
            elif 'Darwin' in plat.lower() or 'mac' in plat.lower():
                stats['mac'] += 1

            d['is_online'] = False
            if d.get('last_seen'):
                try:
                    ts_str = d['last_seen'].replace('Z', '+00:00')
                    ls = datetime.datetime.fromisoformat(ts_str)

                    if ls.tzinfo is None:
                        ls = ls.replace(tzinfo=datetime.timezone.utc)

                    # Online if heartbeat received within last 90 seconds
                    diff = (now - ls).total_seconds()
                    if diff < 90:
                        d['is_online'] = True
                        stats['online'] += 1
                except Exception as e:
                    print(f"Timestamp Parse Error for {d.get('hostname')}: {e}")

        # Fetch available software packages for the Auto-Installer
        packages = supabase.table("packages").select("*").execute().data or []

        return render_template('dashboard.html',
                               devices=devices,
                               stats=stats,
                               packages=packages,
                               page="dashboard")
    except Exception as e:
        print(traceback.format_exc())
        return f"Database Error: {e}"

# --- ITAM: SOFTWARE INVENTORY VIEW ---
@app.route('/device/<device_id>/software')
@login_required
def device_software(device_id):
    """Returns the list of installed software for a specific asset"""
    software = supabase.table("software_inventory").select("*").eq("device_id", device_id).execute()
    return jsonify(software.data)

# --- UEM: AUTO-INSTALLER DEPLOYMENT ---
@app.route('/deploy-package', methods=['POST'])
@login_required
def deploy_package():
    """Queues a software package for installation"""
    device_id = request.form.get('device_id')
    package_id = request.form.get('package_id')

    pkg = supabase.table("packages").select("*").eq("id", package_id).single().execute().data
    if not pkg: return "Package not found", 404

    install_cmd = f"INSTALL|{pkg['download_url']}|{pkg['silent_switch']}"
    supabase.table("devices").update({"pending_command": install_cmd}).eq("id", device_id).execute()

    supabase.table("deployment_logs").insert({
        "device_id": device_id,
        "package_name": pkg['name'],
        "status": "queued"
    }).execute()

    return "Deployment Queued", 200

# --- AGENT API (Telemetry & ITAM Upload) ---

@app.route('/checkin', methods=['POST'])
def checkin():
    if request.headers.get("X-API-KEY") != API_SECRET_KEY:
        return jsonify({"error": "Unauthorized"}), 401

    data = request.json
    serial = data.get("id")

    # 1. Update Hardware & Telemetry
    update_data = {
        "id": serial,
        "hostname": data.get("hostname"),
        "platform": data.get("platform"),
        "os_version": data.get("os_version"),
        "username": data.get("username"),
        "ip_address": data.get("ip_address"),
        "public_ip": data.get("public_ip"),
        "mac_address": data.get("mac_address"),
        "cpu_model": data.get("cpu_model"),
        "cpu_cores": data.get("cpu_cores"),
        "ram_total": data.get("ram_total"),
        "uptime": data.get("uptime"),
        "cpu_usage": data.get("cpu_usage"),
        "ram_usage": data.get("ram_usage"),
        "disk_usage": data.get("disk_usage"),
        "battery_level": data.get("battery_level"),
        "rustdesk_id": data.get("rustdesk_id"),
        "last_seen": datetime.datetime.now(datetime.timezone.utc).isoformat()
    }
    supabase.table("devices").upsert(update_data).execute()

    # 2. Update Software Inventory (If sent by agent)
    software_list = data.get("software_list")
    if software_list:
        supabase.table("software_inventory").delete().eq("device_id", serial).execute()
        for app_item in software_list:
            app_item['device_id'] = serial
        supabase.table("software_inventory").insert(software_list).execute()

    # 3. Check for Commands (Management)
    resp = supabase.table("devices").select("pending_command").eq("id", serial).single().execute()
    cmd = resp.data.get("pending_command") if resp.data else None

    if cmd:
        supabase.table("devices").update({"pending_command": None}).eq("id", serial).execute()

    return jsonify({"command": cmd})

@app.route('/report-result', methods=['POST'])
def report_result():
    data = request.json
    device_id = data.get("id")
    output = data.get("output")
    command = data.get("command")

    # 1. Save to Command History
    supabase.table("command_history").insert({
        "device_id": device_id,
        "command": command,
        "output": output
    }).execute()

    # 2. Update last output on device for quick view
    supabase.table("devices").update({"last_command_output": output}).eq("id", device_id).execute()
    return jsonify({"status": "ok"})

@app.route('/device/<device_id>/history')
@login_required
def device_history(device_id):
    resp = supabase.table("command_history").select("*").eq("device_id", device_id).order("executed_at", desc=True).limit(10).execute()
    return jsonify(resp.data)

@app.route('/broadcast', methods=['POST'])
@login_required
def broadcast():
    """Sends a command to EVERY online device"""
    cmd = request.form.get('command')

    supabase.table("devices").update({"pending_command": cmd}).execute()

    supabase.table("audit_logs").insert({
        "target_device": "ALL_NODES",
        "action_type": "BROADCAST",
        "details": cmd
    }).execute()

    return redirect(url_for('index'))

@app.route('/fleet')
@login_required
def fleet_page():
    try:
        devices_resp = supabase.table("devices").select("*").execute()
        devices = devices_resp.data or []
        return render_template('fleet.html', devices=devices, page="fleet")
    except Exception as e:
        return f"Fleet Error: {e}"

@app.route('/logs')
@login_required
def logs_page():
    """Dedicated page for the central audit trail"""
    logs = supabase.table("audit_logs").select("*").order("created_at", desc=True).limit(100).execute()
    return render_template('logs.html', logs=logs.data, page="logs")

@app.route('/send-command', methods=['POST'])
@login_required
def send_command():
    device_id = request.form.get('device_id')
    cmd = request.form.get('command')
    supabase.table("devices").update({"pending_command": cmd}).eq("id", device_id).execute()
    return redirect(url_for('index'))

# Keep the standard run block for local development fallback,
# but Vercel will ignore this and import the "app" object directly.
if __name__ == '__main__':
    app.run(debug=True, port=5000)