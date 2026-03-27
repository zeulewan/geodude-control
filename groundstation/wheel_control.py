from flask import Flask, render_template, jsonify, request
import threading
import time
import json
import os
import urllib.request

app = Flask(__name__)
APP_DIR = os.path.dirname(os.path.abspath(__file__))
GROUNDSTATION_DIR = APP_DIR

GEODUDE_URL = "http://192.168.4.166:5000"
GIMBAL_URL = "http://192.168.4.222"

# PCA9685 channel mapping (pin - 1 = 0-indexed)
CHANNELS = {
    "B1":   0,   # SV1
    "S1":   1,   # SV2
    "B2":   2,   # SV3
    "S2":   3,   # SV4
    "E1":   4,   # SV5
    "E2":   5,   # SV6
    "W1A":  6,   # SV7
    "W1B":  7,   # SV8
    "W2A":  8,   # SV9
    "W2B":  9,   # SV10
}


state = {
    "gyro": {"x": 0, "y": 0, "z": 0},
    "accel": {"x": 0, "y": 0, "z": 0},
    "encoder_angle": 0,
    "connected": False,
    "rpm": 0,
    "analog_encoder": {
        "va": 0,
        "vb": 0,
        "electrical_deg": 0,
        "mechanical_deg": 0,
    },
    "i2c": {"ok": False, "ads_ok": False, "imu_ok": False},
}

# Server-side servo position tracking — persisted to disk, survives reboots
POSITIONS_FILE = os.path.join(GROUNDSTATION_DIR, "servo_positions.json")

def load_positions():
    try:
        with open(POSITIONS_FILE) as f:
            return json.load(f)
    except Exception:
        return {}

def save_positions():
    with open(POSITIONS_FILE, "w") as f:
        json.dump(servo_positions, f)

servo_positions = load_positions()
_positions_dirty = False
_positions_last_change = 0

def mark_positions_dirty():
    global _positions_dirty, _positions_last_change
    _positions_dirty = True
    _positions_last_change = time.monotonic()

def positions_flush_loop():
    """Write positions to disk 1s after last change. Runs in background."""
    global _positions_dirty
    while True:
        time.sleep(1)
        if _positions_dirty and time.monotonic() - _positions_last_change >= 1.0:
            _positions_dirty = False
            save_positions()

# Neutral positions — persisted to disk, survives reboots
NEUTRAL_FILE = os.path.join(GROUNDSTATION_DIR, "servo_neutral.json")

def load_neutral():
    try:
        with open(NEUTRAL_FILE) as f:
            return json.load(f)
    except Exception:
        return {}

def save_neutral(data):
    with open(NEUTRAL_FILE, "w") as f:
        json.dump(data, f)

servo_neutral = load_neutral()

lock = threading.Lock()


def send_pwm(channel, pw):
    """Send PWM pulse width to a named PCA9685 channel."""
    try:
        req = urllib.request.Request(
            f"{GEODUDE_URL}/pwm",
            data=json.dumps({"channel": channel, "pw": pw}).encode(),
            headers={"Content-Type": "application/json"},
        )
        urllib.request.urlopen(req, timeout=3)
        return True
    except Exception:
        return False


def send_all_off():
    """Turn all PCA9685 channels off."""
    try:
        req = urllib.request.Request(f"{GEODUDE_URL}/pwm/off", method="POST")
        urllib.request.urlopen(req, timeout=3)
        return True
    except Exception:
        return False


def sensor_loop():
    while True:
        try:
            resp = urllib.request.urlopen(f"{GEODUDE_URL}/sensors", timeout=2)
            data = json.loads(resp.read().decode())
            with lock:
                state["gyro"] = {"x": data["gx"], "y": data["gy"], "z": data["gz"]}
                state["accel"] = {"x": data["ax"], "y": data["ay"], "z": data["az"]}
                state["encoder_angle"] = data["angle"]
                state["rpm"] = data.get("rpm", 0)
                state["analog_encoder"] = {
                    "va": data.get("analog_va", 0),
                    "vb": data.get("analog_vb", 0),
                    "electrical_deg": data.get("analog_electrical_deg", 0),
                    "mechanical_deg": data.get("analog_mechanical_deg", data.get("angle", 0)),
                }
                state["i2c"] = {
                    "ok": data.get("i2c_ok", False),
                    "ads_ok": data.get("ads_ok", False),
                    "imu_ok": data.get("imu_ok", False),
                }
                state["connected"] = True
        except Exception:
            with lock:
                state["connected"] = False

        time.sleep(0.1)


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/api/sensors')
def sensors():
    with lock:
        return jsonify(state)


@app.route('/api/pwm', methods=['POST'])
def pwm():
    """Proxy per-channel PWM to GEO-DUDe."""
    data = request.json
    name = data.get("channel", "")
    pw = int(data.get("pw", 0))
    ok = send_pwm(name, pw)
    if ok and name in CHANNELS:
        servo_positions[name] = pw
        mark_positions_dirty()
    return jsonify({"ok": ok})


@app.route('/api/servo_positions')
def get_servo_positions():
    """Return last-known servo positions (survives page reload)."""
    return jsonify(servo_positions)


@app.route('/api/servo_neutral')
def get_servo_neutral():
    """Return neutral positions (persisted to disk)."""
    return jsonify(servo_neutral)


@app.route('/api/servo_neutral', methods=['POST'])
def set_servo_neutral():
    """Set neutral position for a channel. Body: {"channel": "B1", "pw": 1500}"""
    data = request.json
    name = data.get("channel", "")
    pw = int(data.get("pw", 1500))
    if name in CHANNELS:
        servo_neutral[name] = pw
        save_neutral(servo_neutral)
    return jsonify({"ok": True})


@app.route('/api/all_off', methods=['POST'])
def all_off():
    """Turn all PCA9685 channels off."""
    ok = send_all_off()
    return jsonify({"ok": ok})


@app.route('/api/system')
def system_stats():
    """System stats for both Pis."""
    # Groundstation stats
    gs = {}
    try:
        with open("/sys/class/thermal/thermal_zone0/temp") as f:
            gs["temp"] = round(int(f.read().strip()) / 1000.0, 1)
    except Exception:
        gs["temp"] = 0
    try:
        with open("/proc/loadavg") as f:
            gs["load"] = round(float(f.read().split()[0]), 2)
    except Exception:
        gs["load"] = 0
    try:
        with open("/proc/stat") as f:
            line = f.readline()
            parts = line.split()
            idle = int(parts[4])
            total = sum(int(x) for x in parts[1:])
        if not hasattr(system_stats, "_gs_prev"):
            system_stats._gs_prev = (total, idle)
        pt, pi = system_stats._gs_prev
        dt = total - pt
        di = idle - pi
        gs["cpu"] = round((1.0 - di / dt) * 100, 1) if dt > 0 else 0
        system_stats._gs_prev = (total, idle)
    except Exception:
        gs["cpu"] = 0
    # GEO-DUDe stats
    gd = {}
    try:
        resp = urllib.request.urlopen(f"{GEODUDE_URL}/system", timeout=2)
        gd = json.loads(resp.read().decode())
    except Exception:
        gd = {"temp": 0, "cpu": 0, "load": 0}
    return jsonify({"groundstation": gs, "geodude": gd})


@app.route('/api/camera')
def camera():
    """Proxy MJPEG stream from GEO-DUDe."""
    import urllib.request as ur
    try:
        resp = ur.urlopen(f"{GEODUDE_URL}/camera", timeout=5)
        def generate():
            while True:
                chunk = resp.read(4096)
                if not chunk:
                    break
                yield chunk
        return app.response_class(generate(), mimetype=resp.headers.get('Content-Type', 'multipart/x-mixed-replace; boundary=frame'))
    except Exception as e:
        return jsonify({"error": str(e)}), 502


# --- Attitude controller proxy ---


# --- Gimbal proxy ---

def gimbal_get(path):
    """GET request to gimbal ESP32."""
    try:
        resp = urllib.request.urlopen(f"{GIMBAL_URL}/{path}", timeout=3)
        return json.loads(resp.read().decode()), resp.status
    except Exception as e:
        return {"error": str(e)}, 502


@app.route('/api/gimbal/status')
def gimbal_status():
    data, code = gimbal_get("status")
    return jsonify(data), code


@app.route('/api/gimbal/scan', methods=['POST'])
def gimbal_scan():
    data, code = gimbal_get("scan")
    return jsonify(data), code


@app.route('/api/gimbal/setup', methods=['POST'])
def gimbal_setup():
    data, code = gimbal_get("setup")
    return jsonify(data), code


@app.route('/api/gimbal/move', methods=['POST'])
def gimbal_move():
    d = request.json.get("driver", 0)
    steps = request.json.get("steps", 0)
    data, code = gimbal_get(f"move?d={d}&steps={steps}")
    return jsonify(data), code


@app.route('/api/gimbal/stop', methods=['POST'])
def gimbal_stop_motor():
    d = request.json.get("driver", 0)
    data, code = gimbal_get(f"stop?d={d}")
    return jsonify(data), code


@app.route('/api/gimbal/stop_all', methods=['POST'])
def gimbal_stop_all():
    data, code = gimbal_get("stop_all")
    return jsonify(data), code


@app.route('/api/gimbal/speed', methods=['POST'])
def gimbal_speed():
    us = request.json.get("us", 2000)
    data, code = gimbal_get(f"speed?us={us}")
    return jsonify(data), code


@app.route('/api/gimbal/current', methods=['POST'])
def gimbal_current():
    ma = request.json.get("ma", 400)
    data, code = gimbal_get(f"current?ma={ma}")
    return jsonify(data), code


@app.route('/api/gimbal/move_deg', methods=['POST'])
def gimbal_move_deg():
    d = request.json.get("driver", 0)
    deg = request.json.get("deg", 0)
    data, code = gimbal_get(f"move_deg?d={d}&deg={deg}")
    return jsonify(data), code


@app.route('/api/gimbal/enable', methods=['POST'])
def gimbal_enable():
    d = request.json.get("driver", 0)
    data, code = gimbal_get(f"enable?d={d}")
    return jsonify(data), code


@app.route('/api/gimbal/disable', methods=['POST'])
def gimbal_disable():
    d = request.json.get("driver", 0)
    data, code = gimbal_get(f"disable?d={d}")
    return jsonify(data), code


@app.route('/api/gimbal/motor_current', methods=['POST'])
def gimbal_motor_current():
    d = request.json.get("driver", 0)
    ma = request.json.get("ma", 400)
    data, code = gimbal_get(f"motor_current?d={d}&ma={ma}")
    return jsonify(data), code


@app.route('/api/gimbal/motor_ihold', methods=['POST'])
def gimbal_motor_ihold():
    d = request.json.get("driver", 0)
    ma = request.json.get("ma", 0)
    data, code = gimbal_get(f"motor_ihold?d={d}&ma={ma}")
    return jsonify(data), code


@app.route('/api/gimbal/estop', methods=['POST'])
def gimbal_estop():
    data, code = gimbal_get("estop")
    return jsonify(data), code


@app.route('/api/gimbal/sequence', methods=['POST'])
def gimbal_sequence():
    """Execute a timed sequence of gimbal movements."""
    entries = request.json.get("entries", [])
    entries.sort(key=lambda e: e.get("time_ms", 0))
    threading.Thread(target=_run_gimbal_sequence, args=(entries,), daemon=True).start()
    return jsonify({"ok": True, "entries": len(entries)})


def _run_gimbal_sequence(entries):
    """Execute sequence entries at their scheduled times."""
    start = time.monotonic()
    for entry in entries:
        target_time = start + entry.get("time_ms", 0) / 1000.0
        now = time.monotonic()
        if target_time > now:
            time.sleep(target_time - now)
        d = entry.get("driver", 0)
        if "deg" in entry:
            gimbal_get(f"move_deg?d={d}&deg={entry['deg']}")
        elif "steps" in entry:
            gimbal_get(f"move?d={d}&steps={entry['steps']}")


def restore_positions_loop():
    """On startup, wait for GEO-DUDe to come online, then restore last-known positions."""
    if not servo_positions:
        return
    # Wait for GEO-DUDe to be reachable
    for _ in range(60):
        try:
            urllib.request.urlopen(f"{GEODUDE_URL}/sensors", timeout=2)
            break
        except Exception:
            time.sleep(2)
    else:
        return  # gave up after 2 minutes
    # Restore last-known positions (where servos were before shutdown)
    for name, pw in servo_positions.items():
        if name in CHANNELS:
            send_pwm(name, pw)
            time.sleep(0.05)


def start_background_threads():
    threading.Thread(target=sensor_loop, daemon=True).start()
    threading.Thread(target=positions_flush_loop, daemon=True).start()
    threading.Thread(target=restore_positions_loop, daemon=True).start()


def main(port=8080):
    dev = os.environ.get('WHEEL_CONTROL_DEV') == '1'
    is_reloader_child = os.environ.get('WERKZEUG_RUN_MAIN') == 'true'
    if not dev or is_reloader_child:
        start_background_threads()
    if dev:
        import glob
        static_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static')
        templates_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'templates')
        extra = glob.glob(os.path.join(static_dir, '**/*'), recursive=True) + glob.glob(os.path.join(templates_dir, '**/*'), recursive=True)
        app.config['TEMPLATES_AUTO_RELOAD'] = True
        app.run(host='0.0.0.0', port=port, threaded=True, debug=True, use_reloader=True, extra_files=extra)
    else:
        app.run(host='0.0.0.0', port=port, threaded=True)


if __name__ == '__main__':
    port = int(os.environ.get('WHEEL_CONTROL_PORT', '8080'))
    main(port=port)
