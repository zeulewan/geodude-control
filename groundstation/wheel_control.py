from flask import Flask, render_template, jsonify, request
import threading
import time
import json
import os
import urllib.request

app = Flask(__name__)

GEODUDE_URL = "http://192.168.4.166:5000"
ATTITUDE_URL = "http://192.168.4.166:5001"
GIMBAL_URL = "http://192.168.4.222"
WATCHDOG_TIMEOUT = 3  # seconds — auto-stop if no frontend heartbeat
RAMP_HZ = 20  # ramp loop tick rate

# PCA9685 channel mapping (pin - 1 = 0-indexed)
CHANNELS = {
    "B1":   15,
    "S1":   14,
    "B2":   13,
    "S2":   12,
    "MACE": 11,
    "E1":    6,
    "E2":    4,
    "W1A":   3,
    "W1B":   2,
    "W2A":   1,
    "W2B":   0,
}

state = {
    "armed": False,
    "arming": False,
    "throttle": 0.0,       # current throttle (ramped)
    "target": 0.0,         # target throttle
    "ramp_rate": 0.1,      # %/s — how fast throttle moves toward target
    "reverse": False,
    "gyro": {"x": 0, "y": 0, "z": 0},
    "accel": {"x": 0, "y": 0, "z": 0},
    "encoder_angle": 0,
    "connected": False,
    "motor_error": None,
    "rpm": 0,
}

# Server-side servo position tracking — persisted to disk, survives reboots
POSITIONS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "servo_positions.json")

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
NEUTRAL_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "servo_neutral.json")

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
last_heartbeat = time.monotonic()


def send_motor(pw):
    """Send PWM to MACE channel via legacy /motor endpoint."""
    try:
        req = urllib.request.Request(
            f"{GEODUDE_URL}/motor",
            data=json.dumps({"pw": pw}).encode(),
            headers={"Content-Type": "application/json"},
        )
        urllib.request.urlopen(req, timeout=3)
        with lock:
            state["motor_error"] = None
        return True
    except Exception as e:
        with lock:
            state["motor_error"] = str(e)
        return False


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


def throttle_to_pw(throttle, reverse):
    """Convert throttle 0-100 and direction to PWM pulse width."""
    t = int(round(throttle))
    if reverse:
        pw = 1000 - t * 10
    else:
        pw = 1000 + t * 10
    return max(0, min(2000, pw))


MAX_WHEEL_RPM = 600
RPM_RESUME_PCT = 0.7  # resume throttle when RPM drops to 70% of max

def ramp_loop():
    """Server-side ramp: smoothly moves throttle toward target at ramp_rate %/s."""
    last_pw = None
    saturated = False
    while True:
        time.sleep(1.0 / RAMP_HZ)
        with lock:
            if not state["armed"] or state["arming"]:
                last_pw = None
                saturated = False
                continue
            rpm = state.get("rpm", 0)
            target = state["target"]
            current = state["throttle"]

            # RPM saturation check with hysteresis
            if rpm >= MAX_WHEEL_RPM:
                saturated = True
            elif saturated and rpm < MAX_WHEEL_RPM * RPM_RESUME_PCT:
                saturated = False

            if saturated:
                # Coast until RPM drops
                state["throttle"] = 0.0
                pw = 1000
            elif abs(target - current) > 0.1:
                step = state["ramp_rate"] / RAMP_HZ
                diff = target - current
                if abs(diff) <= step:
                    state["throttle"] = target
                elif diff > 0:
                    state["throttle"] = current + step
                else:
                    state["throttle"] = current - step
                pw = throttle_to_pw(state["throttle"], state["reverse"])
            else:
                state["throttle"] = target
                pw = throttle_to_pw(state["throttle"], state["reverse"])
        # Only send if pw changed (avoid flooding)
        if pw != last_pw:
            send_motor(pw)
            last_pw = pw


def watchdog_loop():
    """Auto-stop motor if no frontend heartbeat within timeout."""
    while True:
        time.sleep(1)
        with lock:
            armed = state["armed"]
            throttle = state["throttle"]
        if armed and throttle > 0:
            if time.monotonic() - last_heartbeat > WATCHDOG_TIMEOUT:
                with lock:
                    state["throttle"] = 0.0
                    state["target"] = 0.0
                    state["armed"] = False
                send_motor(1000)
                time.sleep(0.5)
                send_motor(0)


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
    global last_heartbeat
    last_heartbeat = time.monotonic()
    with lock:
        return jsonify(state)


@app.route('/api/config', methods=['POST'])
def config():
    data = request.json
    with lock:
        if "ramp_rate" in data:
            state["ramp_rate"] = max(0.1, min(100.0, float(data["ramp_rate"])))
    return jsonify({"ok": True})


@app.route('/api/arm', methods=['POST'])
def arm():
    with lock:
        if state["arming"]:
            return jsonify({"armed": state["armed"], "arming": True})
        if not state["armed"]:
            state["arming"] = True
            threading.Thread(target=arm_async, args=(True,), daemon=True).start()
        else:
            state["armed"] = False
            state["throttle"] = 0.0
            state["target"] = 0.0
            threading.Thread(target=arm_async, args=(False,), daemon=True).start()
    return jsonify({"armed": state["armed"], "arming": state["arming"]})


def arm_async(do_arm):
    if do_arm:
        send_motor(1000)
        time.sleep(3)
        with lock:
            state["arming"] = False
            state["armed"] = True
    else:
        send_motor(1000)
        time.sleep(0.5)
        send_motor(0)


@app.route('/api/throttle', methods=['POST'])
def throttle():
    global last_heartbeat
    last_heartbeat = time.monotonic()
    data = request.json
    t = max(0.0, min(100.0, float(data.get("target", 0))))
    rev = data.get("reverse", False)
    with lock:
        if state["arming"]:
            return jsonify({"ok": False, "reason": "arming"})
        state["target"] = t
        state["reverse"] = rev
        # Release = immediate idle, let wheel coast
        if t == 0:
            state["throttle"] = 0.0
            send_idle = True
        else:
            # Jump to 10% floor so motor starts immediately
            if state["throttle"] < 10.0:
                state["throttle"] = 10.0
            send_idle = False
    if send_idle:
        send_motor(1000)
    return jsonify({"ok": True})


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


@app.route('/api/brake', methods=['POST'])
def brake():
    """Brake: set throttle to 0 but stay armed, hold 1000us (ESC brake)."""
    with lock:
        state["throttle"] = 0.0
        state["target"] = 0.0
    send_motor(1000)
    return jsonify({"ok": True})


@app.route('/api/calibrate', methods=['POST'])
def calibrate():
    data = request.json
    step = data.get("step", "")
    if step == "max":
        send_motor(2000)
    elif step == "min":
        send_motor(1000)
    elif step == "cancel":
        send_motor(1000)
        time.sleep(0.5)
        send_motor(0)
    return jsonify({"ok": True})


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


@app.route('/api/stop', methods=['POST'])
def stop():
    with lock:
        state["throttle"] = 0.0
        state["target"] = 0.0
        state["armed"] = False
        state["arming"] = False
    send_motor(1000)
    time.sleep(0.5)
    send_motor(0)
    return jsonify({"ok": True})


# --- Attitude controller proxy ---

def attitude_proxy(path, method="GET", data=None):
    """Proxy requests to the attitude controller on GEO-DUDe:5001."""
    try:
        if method == "POST":
            body = json.dumps(data).encode() if data else b""
            req = urllib.request.Request(
                f"{ATTITUDE_URL}/{path}",
                data=body,
                headers={"Content-Type": "application/json"},
            )
        else:
            req = urllib.request.Request(f"{ATTITUDE_URL}/{path}")
        resp = urllib.request.urlopen(req, timeout=3)
        return json.loads(resp.read().decode()), resp.status
    except Exception as e:
        return {"error": str(e)}, 502


@app.route('/api/attitude/status')
def attitude_status():
    data, code = attitude_proxy("status")
    return jsonify(data), code


@app.route('/api/attitude/enable', methods=['POST'])
def attitude_enable():
    data, code = attitude_proxy("enable", "POST")
    return jsonify(data), code


@app.route('/api/attitude/disable', methods=['POST'])
def attitude_disable():
    data, code = attitude_proxy("disable", "POST")
    return jsonify(data), code


@app.route('/api/attitude/setpoint', methods=['POST'])
def attitude_setpoint():
    data, code = attitude_proxy("setpoint", "POST", request.json)
    return jsonify(data), code


@app.route('/api/attitude/nudge', methods=['POST'])
def attitude_nudge():
    data, code = attitude_proxy("nudge", "POST", request.json)
    return jsonify(data), code


@app.route('/api/attitude/zero', methods=['POST'])
def attitude_zero():
    data, code = attitude_proxy("zero", "POST")
    return jsonify(data), code


@app.route('/api/attitude/gains', methods=['POST'])
def attitude_gains():
    data, code = attitude_proxy("gains", "POST", request.json)
    return jsonify(data), code


@app.route('/api/attitude/calibrate', methods=['POST'])
def attitude_calibrate():
    data, code = attitude_proxy("calibrate", "POST")
    return jsonify(data), code


@app.route('/api/attitude/stop', methods=['POST'])
def attitude_stop():
    data, code = attitude_proxy("stop", "POST")
    return jsonify(data), code


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


@app.route('/api/gimbal/jerk', methods=['POST'])
def gimbal_jerk():
    level = request.json.get("level", 5)
    data, code = gimbal_get(f"jerk?level={level}")
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


if __name__ == '__main__':
    threading.Thread(target=sensor_loop, daemon=True).start()
    threading.Thread(target=ramp_loop, daemon=True).start()
    threading.Thread(target=watchdog_loop, daemon=True).start()
    threading.Thread(target=positions_flush_loop, daemon=True).start()
    threading.Thread(target=restore_positions_loop, daemon=True).start()
    app.run(host='0.0.0.0', port=8080, threaded=True)
