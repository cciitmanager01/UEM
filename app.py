import datetime
from flask import Flask, render_template, request, jsonify, redirect, session, url_for
from supabase import create_client

app = Flask(__name__)
app.secret_key = "vault_secret_key"  # Change this!

# --- CONFIG ---
SUPABASE_URL = "https://wvpjnrzmpdswhjnkskbb.supabase.co"
SUPABASE_KEY = "sb_publishable_OLTq7mUEIiRSSZ09ZOud4g_HznmliBj"
API_SECRET_KEY = "7f9c2e4b8a1d5f306e92b8d4c1a7e5f93b0a2d6c4e8f1b9a7d3c5e0b2f4a6d8c"

PIN_CODE = "3300"
ADMIN_USER = "admin"
ADMIN_PASS = "admin123"  # Change this!

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)


# --- ACCESS CONTROL ---
@app.before_request
def restrict_access():
    allowed = ['pin_gate', 'login', 'checkin', 'static']
    if request.endpoint not in allowed:
        if not session.get('pin_ok'):
            return redirect(url_for('pin_gate'))
        if not session.get('logged_in'):
            return redirect(url_for('login'))


# --- AUTH ROUTES ---
@app.route('/verify-pin', methods=['GET', 'POST'])
def pin_gate():
    if request.method == 'POST':
        if request.form.get('pin') == PIN_CODE:
            session['pin_ok'] = True
            return redirect(url_for('login'))
        return render_template('pin.html', error="Invalid Access Pin")
    return render_template('pin.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if not session.get('pin_ok'): return redirect(url_for('pin_gate'))

    if request.method == 'POST':
        user = request.form.get('username')
        pw = request.form.get('password')
        if user == ADMIN_USER and pw == ADMIN_PASS:
            session['logged_in'] = True
            return redirect(url_for('index'))
        return render_template('login.html', error="Invalid Credentials")
    return render_template('login.html')


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('pin_gate'))


# --- MAIN DASHBOARD ---
@app.route('/')
def index():
    devices_resp = supabase.table("devices").select("*").execute()
    devices = devices_resp.data or []
    stats = {"total": len(devices), "online": 0}
    now = datetime.datetime.now(datetime.timezone.utc)

    for d in devices:
        if d.get('last_seen'):
            ls = datetime.datetime.fromisoformat(d['last_seen'].replace('Z', '+00:00'))
            d['is_online'] = (now - ls < datetime.timedelta(seconds=60))
            if d['is_online']: stats['online'] += 1

    return render_template('dashboard.html', devices=devices, stats=stats)


# --- AGENT API (Stays the same) ---
@app.route('/checkin', methods=['POST'])
def checkin():
    if request.headers.get("X-API-KEY") != API_SECRET_KEY: return "401", 401
    data = request.json
    data['last_seen'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    supabase.table("devices").upsert(data).execute()

    resp = supabase.table("devices").select("pending_command").eq("id", data.get("id")).single().execute()
    cmd = resp.data.get("pending_command") if resp.data else None
    if cmd: supabase.table("devices").update({"pending_command": None}).eq("id", data.get("id")).execute()
    return jsonify({"command": cmd})


@app.route('/send-command', methods=['POST'])
def send_command():
    supabase.table("devices").update({"pending_command": request.form.get('command')}).eq("id", request.form.get(
        'device_id')).execute()
    return "OK", 200


if __name__ == '__main__':
    app.run(debug=True)