import datetime
import os
from flask import Flask, render_template, request, jsonify, redirect
from supabase import create_client, Client

app = Flask(__name__)

# ================= CONFIGURATION =================
# Based on your database string, this is your project URL:
SUPABASE_URL = "https://wvpjnrzmpdswhjnkskbb.supabase.co"

# ACTION REQUIRED: Go to Supabase > Settings > API > service_role key
# Paste that long key (starts with 'ey') below:
SUPABASE_KEY = "sb_secret_x-EOXT6MXV2WaMVyIIjOQQ_5oFczrim"

# This must match the key inside your agent.py
API_SECRET_KEY = "7f9c2e4b8a1d5f306e92b8d4c1a7e5f93b0a2d6c4e8f1b9a7d3c5e0b2f4a6d8c"

# Initialize Supabase Client
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
# =================================================

@app.route('/')
def index():
    """Main Dashboard View"""
    try:
        # Fetch all devices
        response = supabase.table("devices").select("*").execute()
        devices = response.data if response.data else []

        # Fetch recent command logs
        logs_resp = supabase.table("command_logs").select("*").order("created_at", desc=True).limit(10).execute()
        logs = logs_resp.data if logs_resp.data else []

        # Calculate Dashboard Stats
        stats = {"total": len(devices), "online": 0, "windows": 0, "mac": 0}
        now = datetime.datetime.now(datetime.timezone.utc)

        for d in devices:
            # Platform Count
            if d.get('platform') == 'Windows':
                stats['windows'] += 1
            else:
                stats['mac'] += 1

            # Online Check (seen in last 5 minutes)
            if d.get('last_seen'):
                # Handle timestamp format
                ls_str = d['last_seen'].replace('Z', '+00:00')
                last_seen = datetime.datetime.fromisoformat(ls_str)
                if now - last_seen < datetime.timedelta(minutes=5):
                    stats['online'] += 1

        return render_template('dashboard.html', devices=devices, stats=stats, logs=logs)
    except Exception as e:
        # This will now show you more detail if the connection fails
        return f"Database Error: {str(e)}", 500


@app.route('/send-command', methods=['POST'])
def send_command():
    """Queue a command for an agent"""
    device_id = request.form.get('device_id')
    cmd_text = request.form.get('command')

    if not device_id or not cmd_text:
        return "Missing data", 400

    supabase.table("devices").update({"pending_command": cmd_text}).eq("id", device_id).execute()

    supabase.table("command_logs").insert({
        "device_id": device_id,
        "command": cmd_text,
        "status": "pending"
    }).execute()

    return redirect('/')


@app.route('/checkin', methods=['POST'])
def checkin():
    """Agent reports stats and fetches commands"""
    if request.headers.get("X-API-KEY") != API_SECRET_KEY:
        return jsonify({"error": "Unauthorized"}), 401

    data = request.json
    serial = data.get("id")

    supabase.table("devices").upsert({
        "id": serial,
        "hostname": data.get("hostname"),
        "platform": data.get("platform"),
        "os_version": data.get("os_version"),
        "cpu_usage": data.get("cpu_usage", 0),
        "ram_usage": data.get("ram_usage", 0),
        "disk_usage": data.get("disk_usage", 0),
        "battery_level": data.get("battery_level", 100),
        "last_seen": datetime.datetime.now(datetime.timezone.utc).isoformat()
    }).execute()

    response = supabase.table("devices").select("pending_command").eq("id", serial).single().execute()
    pending_cmd = response.data.get("pending_command") if response.data else None

    if pending_cmd:
        supabase.table("devices").update({"pending_command": None}).eq("id", serial).execute()

    return jsonify({"status": "ok", "command": pending_cmd})


@app.route('/report-result', methods=['POST'])
def report_result():
    """Agent reports back the text output of a command"""
    if request.headers.get("X-API-KEY") != API_SECRET_KEY:
        return jsonify({"error": "Unauthorized"}), 401

    data = request.json
    supabase.table("command_logs").insert({
        "device_id": data.get("id"),
        "output": data.get("output"),
        "status": data.get("status"),
        "command": "Remote Execution Result"
    }).execute()

    return jsonify({"status": "received"})


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)