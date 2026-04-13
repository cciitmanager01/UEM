import datetime
from flask import Flask, render_template, request, jsonify, redirect
from supabase import create_client

app = Flask(__name__)

# --- CONFIGURATION ---
SUPABASE_URL = "https://wvpjnrzmpdswhjnkskbb.supabase.co"
SUPABASE_KEY = "sb_publishable_OLTq7mUEIiRSSZ09ZOud4g_HznmliBj"  # The 'ey' key from Supabase API settings
API_SECRET_KEY = "7f9c2e4b8a1d5f306e92b8d4c1a7e5f93b0a2d6c4e8f1b9a7d3c5e0b2f4a6d8c"

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)


# --- DASHBOARD LOGIC ---

@app.route('/')
def index():
    try:
        devices = supabase.table("devices").select("*").execute().data or []
        stats = {"total": len(devices), "online": 0, "win": 0, "mac": 0}
        now = datetime.datetime.now(datetime.timezone.utc)

        for d in devices:
            if d['platform'] == 'Windows':
                stats['win'] += 1
            else:
                stats['mac'] += 1

            # Online if seen in last 10 minutes (Vercel cold starts need more padding)
            ls = datetime.datetime.fromisoformat(d['last_seen'].replace('Z', '+00:00'))
            if now - ls < datetime.timedelta(minutes=10):
                stats['online'] += 1
                d['is_online'] = True
            else:
                d['is_online'] = False

        return render_template('dashboard.html', devices=devices, stats=stats)
    except Exception as e:
        return f"Dashboard Error: {e}"


@app.route('/send-command', methods=['POST'])
def send_command():
    device_id = request.form.get('device_id')
    cmd = request.form.get('command')
    supabase.table("devices").update({"pending_command": cmd}).eq("id", device_id).execute()
    return redirect('/')


# --- AGENT API ---

@app.route('/checkin', methods=['POST'])
def checkin():
    if request.headers.get("X-API-KEY") != API_SECRET_KEY:
        return jsonify({"error": "Unauthorized"}), 401

    data = request.json
    serial = data.get("id")

    # Upsert telemetry
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

    # Get and clear command
    resp = supabase.table("devices").select("pending_command").eq("id", serial).single().execute()
    cmd = resp.data.get("pending_command") if resp.data else None
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
        "status": data.get("status")
    }).execute()
    return jsonify({"status": "ok"})