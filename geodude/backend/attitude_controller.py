#!/usr/bin/env python3
"""Attitude controller for GEO-DUDe reaction wheel.

Single PID: angle error -> voltage command (1.5V-12V).
Pico must be in torque mode (M1) for voltage commands to work.
Port 5001. Separate from sensor_server.py (port 5000).
"""

from flask import Flask, jsonify, request
import threading
import time
import math
import json
import urllib.request

app = Flask(__name__)

SENSOR_URL = "http://127.0.0.1:5000"
LOOP_HZ = 50
WATCHDOG_TIMEOUT = 5.0

lock = threading.Lock()
state = {
    # Controller
    "enabled": False,
    "calibrating": False,
    "body_angle": 0.0,
    "setpoint": 0.0,
    "error": 0.0,
    # Feedback
    "gz": 0.0,
    "gz_bias": 0.0,
    "ax": 0.0, "ay": 0.0, "az": 0.0,
    # Output
    "voltage_cmd": 0.0,
    "integral": 0.0,
    # Wheel
    "wheel_rpm": 0.0,
    "control_mode": 0,
    # PID gains (angle -> voltage)
    "Kp": 0.5,
    "Ki": 0.02,
    "Kd": 0.3,
    # Limits
    "voltage_max": 12.0,
    "voltage_min": 1.5,
    "integral_limit": 10.0,
    # Safety
    "watchdog_triggered": False,
}

last_heartbeat = time.monotonic()


def clamp(x, lo, hi):
    return max(lo, min(hi, x))


def send_command(cmd):
    try:
        req = urllib.request.Request(
            f"{SENSOR_URL}/simplefoc",
            data=json.dumps({"command": cmd}).encode(),
            headers={"Content-Type": "application/json"},
        )
        urllib.request.urlopen(req, timeout=1)
    except Exception:
        pass


def read_sensors():
    try:
        resp = urllib.request.urlopen(f"{SENSOR_URL}/simplefoc/status", timeout=1)
        return json.loads(resp.read().decode())
    except Exception:
        return None


def calibrate_gyro(duration=2.0):
    """Sample gz while stationary to estimate bias."""
    samples = []
    t_end = time.monotonic() + duration
    while time.monotonic() < t_end:
        data = read_sensors()
        if data and "gz" in data:
            samples.append(data["gz"])
        time.sleep(0.02)
    return sum(samples) / len(samples) if samples else 0.0


def control_loop():
    body_angle = 0.0
    integral = 0.0
    prev_error = 0.0
    last_time = time.monotonic()

    while True:
        loop_start = time.monotonic()
        dt = loop_start - last_time
        last_time = loop_start
        dt = clamp(dt, 0.001, 0.1)

        with lock:
            enabled = state["enabled"]
            calibrating = state["calibrating"]

        if not enabled or calibrating:
            integral = 0.0
            prev_error = 0.0
            body_angle = 0.0
            time.sleep(1.0 / LOOP_HZ)
            continue

        data = read_sensors()
        if data is None:
            time.sleep(1.0 / LOOP_HZ)
            continue

        with lock:
            gz_bias = state["gz_bias"]

        gz_raw = data.get("gz", 0.0)
        gz = gz_raw - gz_bias  # deg/s, bias corrected
        wheel_rpm = data.get("rpm", 0.0)
        cm = data.get("cm", 0)

        # Integrate body angle (degrees)
        body_angle += gz * dt

        with lock:
            setpoint = state["setpoint"]
            Kp = state["Kp"]
            Ki = state["Ki"]
            Kd = state["Kd"]
            voltage_max = state["voltage_max"]
            voltage_min = state["voltage_min"]
            integral_limit = state["integral_limit"]

        # PID: angle error -> voltage
        error = setpoint - body_angle

        # P
        P = Kp * error

        # I with anti-windup
        candidate_integral = integral + Ki * error * dt

        # D on measurement (use -gz to avoid derivative kick)
        D = -Kd * (gz * math.pi / 180.0)  # gz is deg/s, convert to rad/s for D

        V_cmd_raw = P + candidate_integral + D

        # Clamp voltage
        V_cmd = clamp(V_cmd_raw, -voltage_max, voltage_max)

        # Deadband: overcome cogging
        if abs(V_cmd) > 0.01 and abs(V_cmd) < voltage_min:
            V_cmd = math.copysign(voltage_min, V_cmd)

        # Anti-windup: only integrate when not saturating
        if V_cmd_raw == clamp(V_cmd_raw, -voltage_max, voltage_max):
            integral = clamp(candidate_integral, -integral_limit, integral_limit)

        prev_error = error

        # Send voltage command
        send_command("U%.4f" % V_cmd)

        with lock:
            state["body_angle"] = round(body_angle, 2)
            state["gz"] = round(gz, 2)
            state["error"] = round(error, 2)
            state["voltage_cmd"] = round(V_cmd, 3)
            state["integral"] = round(integral, 4)
            state["wheel_rpm"] = round(wheel_rpm, 1)
            state["control_mode"] = cm
            state["ax"] = data.get("ax", 0.0)
            state["ay"] = data.get("ay", 0.0)
            state["az"] = data.get("az", 0.0)

        elapsed = time.monotonic() - loop_start
        sleep_time = (1.0 / LOOP_HZ) - elapsed
        if sleep_time > 0:
            time.sleep(sleep_time)


def enable_sequence():
    with lock:
        state["calibrating"] = True

    # Auto-calibrate gyro bias (2s, must be stationary)
    bias = calibrate_gyro(2.0)

    # Enable motor and switch to torque mode
    send_command("E")
    time.sleep(0.1)
    send_command("M1")

    with lock:
        state["gz_bias"] = bias
        state["calibrating"] = False
        state["body_angle"] = 0.0
        state["setpoint"] = 0.0
        state["integral"] = 0.0
        state["error"] = 0.0
        state["voltage_cmd"] = 0.0
        state["enabled"] = True
        state["watchdog_triggered"] = False


def disable_controller():
    with lock:
        state["enabled"] = False
        state["calibrating"] = False
        state["integral"] = 0.0
        state["voltage_cmd"] = 0.0
    # Zero voltage, switch back to velocity mode, disable motor
    send_command("U0")
    time.sleep(0.05)
    send_command("M0")
    time.sleep(0.05)
    send_command("D")  # fully disable motor - MACE must re-enable


def watchdog_loop():
    global last_heartbeat
    while True:
        time.sleep(1)
        with lock:
            enabled = state["enabled"]
        if enabled and (time.monotonic() - last_heartbeat > WATCHDOG_TIMEOUT):
            with lock:
                state["watchdog_triggered"] = True
            disable_controller()


# --- API ---

@app.route("/attitude/status")
def status():
    global last_heartbeat
    last_heartbeat = time.monotonic()
    with lock:
        return jsonify(state)


@app.route("/attitude/enable", methods=["POST"])
def enable():
    with lock:
        if state["enabled"] or state["calibrating"]:
            return jsonify({"ok": False, "reason": "already active"})
    threading.Thread(target=enable_sequence, daemon=True).start()
    return jsonify({"ok": True, "status": "calibrating"})


@app.route("/attitude/disable", methods=["POST"])
def disable():
    disable_controller()
    return jsonify({"ok": True})


@app.route("/attitude/setpoint", methods=["POST"])
def setpoint_ep():
    data = request.json
    angle = float(data.get("angle", 0))
    with lock:
        state["setpoint"] = angle
    return jsonify({"ok": True, "setpoint": angle})


@app.route("/attitude/nudge", methods=["POST"])
def nudge():
    data = request.json
    delta = float(data.get("delta", 0))
    with lock:
        state["setpoint"] += delta
        sp = state["setpoint"]
    return jsonify({"ok": True, "setpoint": sp})


@app.route("/attitude/zero", methods=["POST"])
def zero():
    with lock:
        state["body_angle"] = 0.0
        state["setpoint"] = 0.0
        state["integral"] = 0.0
    return jsonify({"ok": True})


@app.route("/attitude/gains", methods=["POST"])
def gains():
    data = request.json
    with lock:
        for key in ["Kp", "Ki", "Kd", "voltage_max", "voltage_min", "integral_limit"]:
            if key in data:
                state[key] = float(data[key])
        result = {k: state[k] for k in ["Kp", "Ki", "Kd", "voltage_max", "voltage_min", "integral_limit"]}
    return jsonify({"ok": True, **result})


@app.route("/attitude/stop", methods=["POST"])
def stop():
    disable_controller()
    send_command("D")
    return jsonify({"ok": True})


@app.route("/attitude/health")
def health():
    global last_heartbeat
    last_heartbeat = time.monotonic()
    return jsonify({"ok": True})


if __name__ == "__main__":
    threading.Thread(target=control_loop, daemon=True).start()
    threading.Thread(target=watchdog_loop, daemon=True).start()
    app.run(host="0.0.0.0", port=5001, threaded=True)
