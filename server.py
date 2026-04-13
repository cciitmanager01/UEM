import datetime
import os
from flask import Flask, render_template, request, jsonify, redirect
from supabase import create_client

app = Flask(__name__)

# --- CONFIGURATION ---
SUPABASE_URL = "https://wvpjnrzmpdswhjnkskbb.supabase.co"
# !!! IMPORTANT: Replace this with your SERVICE_ROLE key (starts with 'ey')
# The 'sb_publishable' key you had before DOES NOT have permission to write to the database.
SUPABASE_KEY = "PASTE_YOUR_SERVICE_ROLE_KEY_HERE"
API_SECRET_KEY = "7f9c2e4b8a1d5f306e92b8d4c1a7e5f93b0a2d6c4e8f1b9a7d3c5e0b2f4a6d8c"

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)


# --- DASHBOARD LOGIC ---

@app.route('/')
def index():
    try:
        # 1. Fetch all devices
        devices_resp = supabase.table("devices").select("*").execute()
        devices = devices_resp.data or []

        # 2. Fetch last 10 logs for the Audit Trail
        logs_resp = supabase.table("command_logs").select("*").order("created_at", desc=True).limit(10).execute()
        logs = logs_resp.data or []

        stats = {"total": len(devices), "online": 0, "win": 0, "mac": 0}
        now = datetime.datetime.now(datetime.timezone.utc)

        for d in devices:
            if d.get('platform') == 'Windows':
                stats['win'] += 1
            else:
                stats['mac'] += 1

            # Online check (Seen in last 10 minutes)
            if d.get('last_seen'):
                # Clean timestamp for Python processing
                ls_str = d['last_seen'].replace('Z', '+00:00')
                ls = datetime.datetime.fromisoformat(ls_str)
                if now - ls < datetime.timedelta(minutes=10):
                    stats['online'] += 1
                    d['is_online'] = True
                else:
                    d['is_online'] = False
            else:
                d['is_online'] = False

        return render_template('dashboard.html', devices=devices, stats=stats, logs=logs)
    except Exception as e:
        return f"Dashboard Error: {e}"


@app.route('/send-command', methods=['POST'])
def send_command():
    device_id = request.form.get('device_id')
    cmd = request.form.get('command')

    # 1. Update the pending command in Supabase
    supabase.table("devices").update({"pending_command": cmd}).eq("id", device_id).execute()

    # 2. Log the action in the Audit Trail
    supabase.table("command_logs").insert({
        "device_id": device_id,
        "command": cmd,
        "status": "queued"
    }).execute()

    return redirect('/')


# --- REMOTE DESKTOP ENDPOINTS (Fixed for Vercel) ---

@app.route('/screen-upload', methods=['POST'])
def screen_upload():
    """Agent uploads Base64 screenshots directly to Supabase"""
    if request.headers.get("X-API-KEY") != API_SECRET_KEY:
        return jsonify({"error": "Unauthorized"}), 401

    data = request.json
    device_id = data.get("id")
    image_data = data.get("image")

    if device_id and image_data:
        # We save to the database because Vercel memory resets
        supabase.table("devices").update({"last_screen": image_data}).eq("id", device_id).execute()
        return jsonify({"status": "ok"})

    return jsonify({"error": "Invalid data"}), 400


@app.route('/get-screen/<device_id>')
def get_screen(device_id):
    """Dashboard fetches the latest screenshot from Supabase"""
    resp = supabase.table("devices").select("last_screen").eq("id", device_id).single().execute()
    if resp.data and resp.data.get('last_screen'):
        return f"data:image/jpeg;base64,{resp.data['last_screen']}"
    return ""


# --- AGENT API ---

@app.route('/checkin', methods=['POST'])
def checkin():
    """Agent reports stats and checks for new commands"""
    if request.headers.get("X-API-KEY") != API_SECRET_KEY:
        return jsonify({"error": "Unauthorized"}), 401

    data = request.json
    serial = data.get("id")

    # Update device telemetry
    supabase.table("devices").upsert({
        "id": serial,
        "hostname": data.get("hostname"),
        "platform": data.get("platform"),
        "cpu_usage": data.get("cpu_usage"),
        "ram_usage": data.get("ram_usage"),
        "disk_usage": data.get("disk_usage"),
        "battery_level": data.get("battery_level"),
        "last_seen": datetime.datetime.now(datetime.timezone.utc).isoformat()
    }).execute()

    # Get pending command
    resp = supabase.table("devices").select("pending_command").eq("id", serial).single().execute()
    cmd = resp.data.get("pending_command") if resp.data else None

    # Clear the command once retrieved
    if cmd:
        supabase.table("devices").update({"pending_command": None}).eq("id", serial).execute()

    return jsonify({"command": cmd})


@app.route('/report-result', methods=['POST'])
def report_result():
    if request.headers.get("X-API-KEY") != API_SECRET_KEY:
        return jsonify({"error": "Unauthorized"}), 401

    data = request.json
    supabase.table("command_logs").insert({
        "device_id": data.get("id"),
        "output": data.get("output"),
        "status": data.get("status"),
        "command": "Execution Result"
    }).execute()
    return jsonify({"status": "ok"})


if __name__ == '__main__':
    app.run(debug=True)