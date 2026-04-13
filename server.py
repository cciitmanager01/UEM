import datetime
from flask import Flask, render_template, request, jsonify, redirect
from supabase import create_client

app = Flask(__name__)

# --- CONFIGURATION ---
SUPABASE_URL = "https://wvpjnrzmpdswhjnkskbb.supabase.co"
# WARNING: Ensure this is your SERVICE_ROLE key (starts with 'ey'), not the publishable key.
SUPABASE_KEY = "sb_publishable_OLTq7mUEIiRSSZ09ZOud4g_HznmliBj"
API_SECRET_KEY = "7f9c2e4b8a1d5f306e92b8d4c1a7e5f93b0a2d6c4e8f1b9a7d3c5e0b2f4a6d8c"

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# In-memory storage for remote desktop frames
# Note: On Vercel (Serverless), this memory is temporary and resets frequently.
screen_cache = {}


# --- DASHBOARD LOGIC ---

@app.route('/')
def index():
    try:
        devices = supabase.table("devices").select("*").execute().data or []
        stats = {"total": len(devices), "online": 0, "win": 0, "mac": 0}
        now = datetime.datetime.now(datetime.timezone.utc)

        for d in devices:
            if d.get('platform') == 'Windows':
                stats['win'] += 1
            else:
                stats['mac'] += 1

            # Online check (Seen in last 10 minutes)
            if d.get('last_seen'):
                ls = datetime.datetime.fromisoformat(d['last_seen'].replace('Z', '+00:00'))
                if now - ls < datetime.timedelta(minutes=10):
                    stats['online'] += 1
                    d['is_online'] = True
                else:
                    d['is_online'] = False
            else:
                d['is_online'] = False

        return render_template('dashboard.html', devices=devices, stats=stats)
    except Exception as e:
        return f"Dashboard Error: {e}"


@app.route('/send-command', methods=['POST'])
def send_command():
    device_id = request.form.get('device_id')
    cmd = request.form.get('command')
    # Update the pending command in Supabase
    supabase.table("devices").update({"pending_command": cmd}).eq("id", device_id).execute()

    # Log the action
    supabase.table("command_logs").insert({
        "device_id": device_id,
        "command": cmd,
        "status": "queued"
    }).execute()
    return redirect('/')


# --- REMOTE DESKTOP ENDPOINTS ---

@app.route('/screen-upload', methods=['POST'])
def screen_upload():
    """Endpoint for the agent to upload Base64 screenshots"""
    if request.headers.get("X-API-KEY") != API_SECRET_KEY:
        return jsonify({"error": "Unauthorized"}), 401

    data = request.json
    device_id = data.get("id")
    image_data = data.get("image")

    if device_id and image_data:
        # Store image in memory (Slide-show mode)
        screen_cache[device_id] = image_data
        return jsonify({"status": "ok"})

    return jsonify({"error": "Invalid data"}), 400


@app.route('/get-screen/<device_id>')
def get_screen(device_id):
    """Endpoint for the dashboard to fetch the latest screenshot"""
    image_b64 = screen_cache.get(device_id)
    if image_b64:
        # Return as a data URL for easy display in <img> tags
        return f"data:image/jpeg;base64,{image_b64}"
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

    # If a command exists, clear it so it doesn't loop
    if cmd:
        supabase.table("devices").update({"pending_command": None}).eq("id", serial).execute()

    return jsonify({"command": cmd})


@app.route('/report-result', methods=['POST'])
def report_result():
    """Agent reports result of executed command"""
    if request.headers.get("X-API-KEY") != API_SECRET_KEY:
        return jsonify({"error": "Unauthorized"}), 401

    data = request.json
    supabase.table("command_logs").insert({
        "device_id": data.get("id"),
        "output": data.get("output"),
        "status": data.get("status"),
        "command": "Remote Execution"
    }).execute()
    return jsonify({"status": "ok"})


if __name__ == '__main__':
    app.run(debug=True)