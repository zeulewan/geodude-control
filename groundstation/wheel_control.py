from flask import Flask, render_template, jsonify, request
import threading
import time
import json
import os
import select
import struct
import urllib.request

app = Flask(__name__)

GEODUDE_URL = "http://192.168.4.166:5000"
GIMBAL_URL = "http://192.168.4.222"
WATCHDOG_TIMEOUT = 3  # seconds — auto-stop if no frontend heartbeat
RAMP_HZ = 20  # ramp loop tick rate
CONTROLLER_HZ = 20
CONTROLLER_SCAN_INTERVAL = 2.0
CONTROLLER_LIMIT_US = 450
CONTROLLER_DEADZONE = 0.12
CONTROLLER_ACTIVE_THRESHOLD = 0.2
JS_EVENT_BUTTON = 0x01
JS_EVENT_AXIS = 0x02
JS_EVENT_INIT = 0x80


# PCA9685 channel mapping (pin - 1 = 0-indexed)
# MACE reaction wheel is no longer on PCA9685 — it is driven by Pi Pico via SimpleFOC
CHANNELS = {
    "B1":   15,
    "S1":   14,
    "B2":   13,
    "S2":   12,
    "E1":    6,
    "E2":    4,
    "W1A":   3,
    "W1B":   2,
    "W2A":   1,
    "W2B":   0,
}

# SimpleFOC velocity limits (rad/s)
MAX_VELOCITY = 20.0

mace = {
    "enabled": False,
    "target": 0.0,      # target velocity rad/s
    "velocity": 0.0,    # current velocity rad/s (reported by Pico)
    "connected": False, # Pico USB serial connected
    "error": None,
}

state = {
    "gyro": {"x": 0, "y": 0, "z": 0},
    "accel": {"x": 0, "y": 0, "z": 0},
    "encoder_angle": 0,
    "connected": False,
    "rpm": 0,
}

CONTROLLER_ARM_BINDINGS = {
    "left": {
        "lx": [{"channel": "B1", "scale": 1.0}],
        "ly": [{"channel": "S1", "scale": -1.0}],
        "ry": [{"channel": "E1", "scale": -1.0}],
        "rx": [
            {"channel": "W1A", "scale": 1.0},
            {"channel": "W1B", "scale": -1.0},
        ],
    },
    "right": {
        "lx": [{"channel": "B2", "scale": -1.0}],
        "ly": [{"channel": "S2", "scale": -1.0}],
        "ry": [{"channel": "E2", "scale": -1.0}],
        "rx": [
            {"channel": "W2A", "scale": -1.0},
            {"channel": "W2B", "scale": 1.0},
        ],
    },
}

CONTROLLER_AXIS_ORDER = {
    0: "lx",
    1: "ly",
    3: "rx",
    4: "ry",
}

CONTROLLER_LABELS = {
    "lx": "Left stick X -> base yaw (B1/B2)",
    "ly": "Left stick Y -> shoulder pair (S1/S2)",
    "ry": "Right stick Y -> elbow pair (E1/E2)",
    "rx": "Right stick X -> wrist pair (W1/W2)",
}

DEADMAN_BUTTONS = {4, 5}

controller_state = {
    "enabled": False,
    "connected": False,
    "active": False,
    "deadman": False,
    "device": None,
    "last_error": None,
    "axes": {name: 0.0 for name in CONTROLLER_LABELS},
    "buttons": {},
    "updated_at": 0.0,
    "selected_arm": "left",
}

SERVO_SETTINGS = {"speed": 50, "ramp": 20}
controller_channel_velocity = {name: 0.0 for name in CHANNELS if name != "MACE"}
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


def send_velocity(velocity):
    """Send velocity command (rad/s) to Pico via GEO-DUDe /simplefoc endpoint."""
    try:
        req = urllib.request.Request(
            f"{GEODUDE_URL}/simplefoc",
            data=json.dumps({"velocity": round(float(velocity), 4)}).encode(),
            headers={"Content-Type": "application/json"},
        )
        urllib.request.urlopen(req, timeout=3)
        with lock:
            mace["error"] = None
        return True
    except Exception as e:
        with lock:
            mace["error"] = str(e)
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



def clamp(value, lo, hi):
    return max(lo, min(hi, value))


def controller_axis_value(name):
    with lock:
        value = float(controller_state["axes"].get(name, 0.0))
    if abs(value) < CONTROLLER_DEADZONE:
        return 0.0
    return value


def controller_limits(channel):
    center = servo_neutral.get(channel)
    if center is None:
        center = servo_positions.get(channel, 1000)
    center = int(center)
    return (
        clamp(center - CONTROLLER_LIMIT_US, 500, 2500),
        clamp(center + CONTROLLER_LIMIT_US, 500, 2500),
    )


def controller_status_payload():
    with lock:
        axes = dict(controller_state["axes"])
        buttons = dict(controller_state["buttons"])
        payload = {
            "enabled": controller_state["enabled"],
            "connected": controller_state["connected"],
            "active": controller_state["active"],
            "deadman": controller_state["deadman"],
            "device": controller_state["device"],
            "last_error": controller_state["last_error"],
            "updated_at": controller_state["updated_at"],
        }
    payload["axes"] = axes
    payload["buttons"] = buttons
    payload["bindings"] = CONTROLLER_LABELS
    payload["selected_arm"] = controller_state["selected_arm"]
    return payload


def reset_controller_motion():
    for name in controller_channel_velocity:
        controller_channel_velocity[name] = 0.0


def set_controller_arm(selected_arm):
    with lock:
        controller_state["selected_arm"] = "right" if selected_arm == "right" else "left"
    reset_controller_motion()


def set_controller_enabled(enabled):
    with lock:
        controller_state["enabled"] = bool(enabled)
        controller_state["active"] = False
        controller_state["deadman"] = False
        controller_state["last_error"] = None
        for name in controller_state["axes"]:
            controller_state["axes"][name] = 0.0
    reset_controller_motion()


def controller_apply_outputs():
    with lock:
        enabled = controller_state["enabled"]
        buttons = dict(controller_state["buttons"])
        max_speed = int(SERVO_SETTINGS["speed"])
        accel = int(SERVO_SETTINGS["ramp"])
        selected_arm = controller_state["selected_arm"]
    if not enabled:
        reset_controller_motion()
        with lock:
            controller_state["active"] = False
            controller_state["deadman"] = False
        return

    deadman = any(buttons.get(btn, 0) for btn in DEADMAN_BUTTONS)
    active = False
    changed = False

    if not deadman:
        reset_controller_motion()
    else:
        arm_bindings = CONTROLLER_ARM_BINDINGS[selected_arm]
        for axis_name, bindings in arm_bindings.items():
            axis_value = controller_axis_value(axis_name)
            if abs(axis_value) >= CONTROLLER_ACTIVE_THRESHOLD:
                active = True
            for binding in bindings:
                channel = binding["channel"]
                current = int(servo_positions.get(channel, servo_neutral.get(channel, 1000)))
                lo, hi = controller_limits(channel)
                velocity = controller_channel_velocity.get(channel, 0.0)
                target_velocity = axis_value * binding["scale"] * max_speed
                if target_velocity > velocity:
                    velocity = min(velocity + accel, target_velocity)
                elif target_velocity < velocity:
                    velocity = max(velocity - accel, target_velocity)
                if abs(target_velocity) < 0.001 and abs(velocity) < accel:
                    velocity = 0.0
                controller_channel_velocity[channel] = velocity
                if abs(velocity) < 0.5:
                    continue
                step = int(round(velocity))
                if step == 0:
                    step = 1 if velocity > 0 else -1
                target = clamp(current + step, lo, hi)
                if target == current:
                    controller_channel_velocity[channel] = 0.0
                    continue
                if send_pwm(channel, target):
                    servo_positions[channel] = target
                    mark_positions_dirty()
                    changed = True

    with lock:
        controller_state["deadman"] = deadman
        controller_state["active"] = deadman and (active or changed)


def controller_loop():
    fd = None

    def close_device():
        nonlocal fd
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass
            fd = None
        with lock:
            controller_state["connected"] = False
            controller_state["device"] = None
            controller_state["active"] = False
            controller_state["deadman"] = False
            for name in controller_state["axes"]:
                controller_state["axes"][name] = 0.0
        reset_controller_motion()

    while True:
        with lock:
            enabled = controller_state["enabled"]
        if not enabled:
            close_device()
            time.sleep(0.25)
            continue

        if fd is None:
            try:
                fd = os.open('/dev/input/js0', os.O_RDONLY | os.O_NONBLOCK)
                with lock:
                    controller_state["connected"] = True
                    controller_state["device"] = '/dev/input/js0'
                    controller_state["last_error"] = None
                    controller_state["updated_at"] = time.time()
            except OSError as e:
                with lock:
                    controller_state["connected"] = False
                    controller_state["device"] = None
                    controller_state["last_error"] = str(e)
                time.sleep(CONTROLLER_SCAN_INTERVAL)
                continue

        try:
            ready, _, _ = select.select([fd], [], [], 1.0 / CONTROLLER_HZ)
            if ready:
                while True:
                    try:
                        event = os.read(fd, 8)
                    except BlockingIOError:
                        break
                    if len(event) != 8:
                        raise OSError('controller disconnected')
                    _, value, event_type, number = struct.unpack('IhBB', event)
                    if event_type & JS_EVENT_INIT:
                        continue
                    base_type = event_type & ~JS_EVENT_INIT
                    with lock:
                        controller_state["updated_at"] = time.time()
                        if base_type == JS_EVENT_AXIS and number in CONTROLLER_AXIS_ORDER:
                            controller_state["axes"][CONTROLLER_AXIS_ORDER[number]] = max(-1.0, min(1.0, value / 32767.0))
                        elif base_type == JS_EVENT_BUTTON:
                            controller_state["buttons"][number] = 1 if value else 0
            controller_apply_outputs()
        except OSError as e:
            with lock:
                controller_state["last_error"] = str(e)
            close_device()
            time.sleep(CONTROLLER_SCAN_INTERVAL)


def watchdog_loop():
    """Auto-stop motor if no frontend heartbeat within timeout."""
    while True:
        time.sleep(1)
        with lock:
            enabled = mace["enabled"]
            target = mace["target"]
        if enabled and target != 0.0:
            if time.monotonic() - last_heartbeat > WATCHDOG_TIMEOUT:
                with lock:
                    mace["target"] = 0.0
                    mace["velocity"] = 0.0
                    mace["enabled"] = False
                send_velocity(0.0)


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
        # Poll SimpleFOC status from GEO-DUDe (Pico connection + current target)
        try:
            resp = urllib.request.urlopen(f"{GEODUDE_URL}/simplefoc/status", timeout=2)
            sfoc = json.loads(resp.read().decode())
            with lock:
                mace["connected"] = sfoc.get("connected", False)
                t = sfoc.get("target")
                if t is not None:
                    mace["velocity"] = round(float(t), 4)
        except Exception:
            with lock:
                mace["connected"] = False
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


@app.route('/api/mace/status')
def mace_status():
    """Return current MACE state including encoder angle and RPM from sensor data."""
    with lock:
        payload = dict(mace)
        payload['encoder_angle'] = state.get('encoder_angle', 0)
        payload['rpm'] = state.get('rpm', 0)
    return jsonify(payload)


@app.route('/api/mace/enable', methods=['POST'])
def mace_enable():
    """Enable the reaction wheel motor."""
    with lock:
        mace["enabled"] = True
        mace["error"] = None
    return jsonify({"ok": True, "enabled": True})


@app.route('/api/mace/disable', methods=['POST'])
def mace_disable():
    """Disable the reaction wheel motor and stop it."""
    with lock:
        mace["enabled"] = False
        mace["target"] = 0.0
        mace["velocity"] = 0.0
    send_velocity(0.0)
    return jsonify({"ok": True, "enabled": False})


@app.route('/api/mace/velocity', methods=['POST'])
def mace_velocity():
    """Set target velocity in rad/s. Only works if motor is enabled."""
    global last_heartbeat
    last_heartbeat = time.monotonic()
    data = request.json
    v = max(-MAX_VELOCITY, min(MAX_VELOCITY, float(data.get("target", 0))))
    with lock:
        if not mace["enabled"]:
            return jsonify({"ok": False, "reason": "not enabled"})
        mace["target"] = v
    ok = send_velocity(v)
    return jsonify({"ok": ok})


@app.route('/api/mace/stop', methods=['POST'])
def mace_stop():
    """Immediate stop: send velocity 0 and disable motor."""
    with lock:
        mace["target"] = 0.0
        mace["velocity"] = 0.0
        mace["enabled"] = False
    send_velocity(0.0)
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


@app.route('/api/servo_settings')
def get_servo_settings():
    return jsonify(SERVO_SETTINGS)


@app.route('/api/servo_settings', methods=['POST'])
def set_servo_settings():
    data = request.json or {}
    with lock:
        if "speed" in data:
            SERVO_SETTINGS["speed"] = clamp(int(data["speed"]), 1, 200)
        if "ramp" in data:
            SERVO_SETTINGS["ramp"] = clamp(int(data["ramp"]), 1, 100)
        settings = dict(SERVO_SETTINGS)
    return jsonify(settings)


@app.route('/api/controller/status')
def controller_status():
    return jsonify(controller_status_payload())


@app.route('/api/controller/enable', methods=['POST'])
def controller_enable():
    data = request.json or {}
    enabled = bool(data.get('enabled', False))
    set_controller_enabled(enabled)
    return jsonify(controller_status_payload())


@app.route('/api/controller/arm', methods=['POST'])
def controller_select_arm():
    data = request.json or {}
    set_controller_arm(data.get('selected_arm', "left"))
    return jsonify(controller_status_payload())


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


if __name__ == '__main__':
    threading.Thread(target=sensor_loop, daemon=True).start()

    threading.Thread(target=controller_loop, daemon=True).start()
    threading.Thread(target=watchdog_loop, daemon=True).start()
    threading.Thread(target=positions_flush_loop, daemon=True).start()
    threading.Thread(target=restore_positions_loop, daemon=True).start()
    app.run(host='0.0.0.0', port=8080, threaded=True)
