#!/usr/bin/env python3
"""Closed-loop attitude controller for GEO-DUDe reaction wheel (MACE).

Runs on GEO-DUDe Pi. Reads IMU gz for body rate, integrates for body angle,
PID controls the reaction wheel to hold a setpoint angle.

Bidirectional ESC: 1500us = stop, >1500 = forward, <1500 = reverse.

Port 5001. Separate from sensor_server.py (port 5000).
"""

from flask import Flask, jsonify, request
import smbus2
import threading
import time
import os

app = Flask(__name__)

# --- Hardware constants ---
PCA9685_ADDR = 0x40
IMU_ADDR = 0x69
ENCODER_ADDR = 0x36
MACE_CHANNEL = 11
LED0_ON_L = 0x06

# --- ESC mode ---
# Set to True when the bidirectional ESC is installed, False for old Drfeify
BIDIRECTIONAL_ESC = True

# --- Control constants ---
LOOP_HZ = 100
MAX_RAMP_RATE = 40.5        # %/s max throttle change rate
MAX_STEP_PER_TICK = MAX_RAMP_RATE / LOOP_HZ  # 0.405% per tick
MOTOR_MIN_PCT = 10.0        # ESC deadband floor
MOTOR_OUTPUT_THRESHOLD = 2.0  # PID output below this -> coast
WATCHDOG_TIMEOUT = 5.0      # seconds without status poll -> auto-disable
FLAG_FILE = "/tmp/attitude_active"

# --- Shared state ---
state_lock = threading.Lock()
state = {
    # Controller
    "enabled": False,
    "calibrating": False,
    "arming": False,
    "body_angle": 0.0,
    "setpoint": 0.0,
    "error": 0.0,
    "output": 0.0,
    "motor_pct": 0.0,
    "pwm": 1500,
    # Sensors
    "gz": 0.0,
    "gz_bias": 0.0,
    # Wheel
    "wheel_angle": 0.0,
    "wheel_rpm": 0.0,
    "saturation": "ok",
    # PID gains
    "Kp": 1.5,
    "Ki": 0.05,
    "Kd": 0.8,
    "integral_limit": 30.0,
    "max_throttle": 60.0,
    # Internal
    "integral": 0.0,
    "watchdog_triggered": False,
}

last_heartbeat = time.monotonic()


# --- I2C helpers ---

def r16(bus, addr, reg):
    h = bus.read_byte_data(addr, reg)
    l = bus.read_byte_data(addr, reg + 1)
    v = (h << 8) | l
    return v - 65536 if v > 32767 else v


def pca_set_pulse_us(bus, channel, pulse_us):
    period_us = 1_000_000 / 50  # 50Hz
    counts = int(pulse_us / period_us * 4096)
    counts = max(0, min(4095, counts))
    reg = LED0_ON_L + 4 * channel
    bus.write_i2c_block_data(PCA9685_ADDR, reg, [
        0, 0, counts & 0xFF, (counts >> 8) & 0xFF,
    ])


def pca_off(bus, channel):
    reg = LED0_ON_L + 4 * channel
    bus.write_i2c_block_data(PCA9685_ADDR, reg, [0, 0, 0, 0])


def set_motor(bus, pw):
    """Set MACE motor PWM. 0 = signal off.
    Bidirectional: 1500=stop, 1100-1900=active.
    Uni-directional (old): 1000=idle, 1000-2000=active."""
    if pw == 0:
        pca_off(bus, MACE_CHANNEL)
    elif BIDIRECTIONAL_ESC:
        pw = max(1100, min(1900, pw))
        pca_set_pulse_us(bus, MACE_CHANNEL, pw)
    else:
        pw = max(1000, min(2000, pw))
        pca_set_pulse_us(bus, MACE_CHANNEL, pw)


# --- Gyro calibration ---

def calibrate_gyro(bus, samples=200, delay=0.01):
    """Sample gz while stationary to estimate bias. ~2 seconds."""
    total = 0.0
    for _ in range(samples):
        gz = r16(bus, IMU_ADDR, 0x37) / 131.0
        total += gz
        time.sleep(delay)
    return total / samples


# --- Rate limiter ---

def rate_limit(current_pct, desired_pct):
    delta = desired_pct - current_pct
    if abs(delta) <= MAX_STEP_PER_TICK:
        return desired_pct
    elif delta > 0:
        return current_pct + MAX_STEP_PER_TICK
    else:
        return current_pct - MAX_STEP_PER_TICK


# --- Deadband mapping ---

def pid_to_motor(output):
    """Map PID output [-100, 100] to motor [-100%, 100%], skipping deadband.
    Below threshold in either direction -> 0 (coast at 1500us)."""
    if abs(output) < MOTOR_OUTPUT_THRESHOLD:
        return 0.0
    sign = 1.0 if output > 0 else -1.0
    magnitude = abs(output)
    range_in = 100.0 - MOTOR_OUTPUT_THRESHOLD
    range_out = 100.0 - MOTOR_MIN_PCT
    motor_pct = MOTOR_MIN_PCT + (magnitude - MOTOR_OUTPUT_THRESHOLD) / range_in * range_out
    return sign * motor_pct


# --- Wheel saturation ---

MAX_WHEEL_RPM = 600

def check_saturation(rpm):
    abs_rpm = abs(rpm)
    if abs_rpm > MAX_WHEEL_RPM * 0.95:
        return "saturated"
    if abs_rpm > MAX_WHEEL_RPM * 0.85:
        return "warning"
    return "ok"


# --- Control loop ---

def control_loop():
    bus = smbus2.SMBus(1)

    # Initialize IMU
    bus.write_byte_data(IMU_ADDR, 0x06, 0x01)
    time.sleep(0.05)

    # Send stop signal on startup
    set_motor(bus, 1500 if BIDIRECTIONAL_ESC else 1000)

    body_angle = 0.0
    integral = 0.0
    current_motor_pct = 0.0
    last_time = time.monotonic()

    # Encoder RPM tracking
    last_wheel_angle = None
    last_wheel_time = None
    rpm_buf = []

    while True:
        loop_start = time.monotonic()
        dt = loop_start - last_time
        last_time = loop_start

        with state_lock:
            enabled = state["enabled"]
            calibrating = state["calibrating"]
            arming = state["arming"]

        if not enabled or calibrating or arming:
            # Not active: reset, don't touch motor
            integral = 0.0
            current_motor_pct = 0.0
            elapsed = time.monotonic() - loop_start
            sleep_time = (1.0 / LOOP_HZ) - elapsed
            if sleep_time > 0:
                time.sleep(sleep_time)
            continue

        # 1. Read sensors
        gz_raw = r16(bus, IMU_ADDR, 0x37) / 131.0
        with state_lock:
            gz_bias = state["gz_bias"]
        gz = gz_raw - gz_bias

        # Read encoder
        eh = bus.read_byte_data(ENCODER_ADDR, 0x0c)
        el = bus.read_byte_data(ENCODER_ADDR, 0x0d)
        wheel_angle = ((eh & 0x0F) << 8 | el) / 4096.0 * 360

        # Wheel RPM
        now = time.monotonic()
        wheel_rpm = 0.0
        if last_wheel_angle is not None and last_wheel_time is not None:
            wdt = now - last_wheel_time
            if wdt > 0:
                wdelta = wheel_angle - last_wheel_angle
                if wdelta > 180: wdelta -= 360
                if wdelta < -180: wdelta += 360
                rpm_buf.append(wdelta / wdt / 6.0)  # signed RPM
                if len(rpm_buf) > 10:
                    rpm_buf.pop(0)
                wheel_rpm = sum(rpm_buf) / len(rpm_buf)
        last_wheel_angle = wheel_angle
        last_wheel_time = now

        # 2. Integrate body angle
        body_angle += gz * dt

        # 3. PID
        with state_lock:
            setpoint = state["setpoint"]
            Kp = state["Kp"]
            Ki = state["Ki"]
            Kd = state["Kd"]
            integral_limit = state["integral_limit"]
            max_throttle = state["max_throttle"]

        error = setpoint - body_angle

        P = Kp * error
        D = Kd * (-gz)  # derivative on measurement
        output_raw = P + Ki * integral + D
        output_clamped = max(-max_throttle, min(max_throttle, output_raw))

        # Anti-windup: only integrate if not saturated
        if output_clamped == output_raw:
            integral += error * dt
            integral = max(-integral_limit, min(integral_limit, integral))

        # Saturation protection: hard limit at MAX_WHEEL_RPM
        sat = check_saturation(wheel_rpm)
        if sat == "saturated":
            integral *= 0.95  # slowly bleed integral
            output_clamped = 0  # force coast — do not push past RPM limit

        # 4. Map to motor
        if BIDIRECTIONAL_ESC:
            # Bidirectional: positive = forward, negative = reverse
            desired_motor_pct = pid_to_motor(output_clamped)
        else:
            # Uni-directional: positive = throttle, negative = coast
            if output_clamped > 0:
                desired_motor_pct = pid_to_motor(output_clamped)
            else:
                desired_motor_pct = 0.0

        # 5. Rate limit
        current_motor_pct = rate_limit(current_motor_pct, desired_motor_pct)

        # 6. Convert to PWM
        if BIDIRECTIONAL_ESC:
            if abs(current_motor_pct) < 1.0:
                pw = 1500  # stop
            else:
                pw = 1500 + int(current_motor_pct * 4)
                pw = max(1100, min(1900, pw))
        else:
            if current_motor_pct < 1.0:
                pw = 1000  # coast
            else:
                pw = 1000 + int(current_motor_pct * 10)
                pw = max(1000, min(2000, pw))

        set_motor(bus, pw)

        # 7. Update shared state
        with state_lock:
            state["body_angle"] = round(body_angle, 2)
            state["gz"] = round(gz, 2)
            state["error"] = round(error, 2)
            state["output"] = round(output_clamped, 2)
            state["motor_pct"] = round(current_motor_pct, 1)
            state["pwm"] = pw
            state["integral"] = round(integral, 3)
            state["wheel_angle"] = round(wheel_angle, 1)
            state["wheel_rpm"] = round(wheel_rpm, 1)
            state["saturation"] = sat

        # 8. Sleep remainder
        elapsed = time.monotonic() - loop_start
        sleep_time = (1.0 / LOOP_HZ) - elapsed
        if sleep_time > 0:
            time.sleep(sleep_time)


# --- Enable/disable sequences ---

def enable_sequence():
    """Calibrate gyro and start controller. Bidirectional ESC needs no arming."""
    bus = smbus2.SMBus(1)
    stop_pw = 1500 if BIDIRECTIONAL_ESC else 1000

    # Calibrate gyro
    with state_lock:
        state["calibrating"] = True
    bias = calibrate_gyro(bus)
    with state_lock:
        state["gz_bias"] = bias
        state["calibrating"] = False

    if BIDIRECTIONAL_ESC:
        # No arming needed — just ensure stopped
        set_motor(bus, stop_pw)
    else:
        # Old ESC needs 3s arming at 1000us
        with state_lock:
            state["arming"] = True
        set_motor(bus, 1000)
        time.sleep(3)
        with state_lock:
            state["arming"] = False

    # Zero angle and enable
    with state_lock:
        state["body_angle"] = 0.0
        state["setpoint"] = 0.0
        state["integral"] = 0.0
        state["error"] = 0.0
        state["output"] = 0.0
        state["motor_pct"] = 0.0
        state["enabled"] = True
        state["arming"] = False
        state["watchdog_triggered"] = False

    # Create flag file
    open(FLAG_FILE, "w").close()
    bus.close()


def disable_controller():
    """Stop controller, coast motor."""
    with state_lock:
        state["enabled"] = False
        state["calibrating"] = False
        state["arming"] = False
        state["integral"] = 0.0

    # Remove flag file
    try:
        os.remove(FLAG_FILE)
    except FileNotFoundError:
        pass


# --- Watchdog ---

def watchdog_loop():
    global last_heartbeat
    stop_pw = 1500 if BIDIRECTIONAL_ESC else 1000
    while True:
        time.sleep(1)
        with state_lock:
            enabled = state["enabled"]
        if enabled and (time.monotonic() - last_heartbeat > WATCHDOG_TIMEOUT):
            with state_lock:
                state["watchdog_triggered"] = True
            disable_controller()
            try:
                bus = smbus2.SMBus(1)
                set_motor(bus, stop_pw)
                bus.close()
            except Exception:
                pass


# --- API ---

@app.route("/status")
def status():
    global last_heartbeat
    last_heartbeat = time.monotonic()
    with state_lock:
        return jsonify(state)


@app.route("/enable", methods=["POST"])
def enable():
    with state_lock:
        if state["enabled"] or state["calibrating"] or state["arming"]:
            return jsonify({"ok": False, "reason": "already active"})
    threading.Thread(target=enable_sequence, daemon=True).start()
    return jsonify({"ok": True, "status": "calibrating"})


@app.route("/disable", methods=["POST"])
def disable():
    disable_controller()
    try:
        bus = smbus2.SMBus(1)
        set_motor(bus, 1500 if BIDIRECTIONAL_ESC else 1000)
        bus.close()
    except Exception:
        pass
    return jsonify({"ok": True})


@app.route("/setpoint", methods=["POST"])
def setpoint():
    data = request.json
    angle = float(data.get("angle", 0))
    with state_lock:
        state["setpoint"] = angle
    return jsonify({"ok": True, "setpoint": angle})


@app.route("/nudge", methods=["POST"])
def nudge():
    data = request.json
    delta = float(data.get("delta", 0))
    with state_lock:
        state["setpoint"] += delta
        sp = state["setpoint"]
    return jsonify({"ok": True, "setpoint": sp})


@app.route("/zero", methods=["POST"])
def zero():
    with state_lock:
        state["body_angle"] = 0.0
        state["setpoint"] = 0.0
        state["integral"] = 0.0
    return jsonify({"ok": True})


@app.route("/gains", methods=["POST"])
def gains():
    data = request.json
    with state_lock:
        if "Kp" in data:
            state["Kp"] = max(0, float(data["Kp"]))
        if "Ki" in data:
            state["Ki"] = max(0, float(data["Ki"]))
        if "Kd" in data:
            state["Kd"] = max(0, float(data["Kd"]))
        if "integral_limit" in data:
            state["integral_limit"] = max(0, float(data["integral_limit"]))
        if "max_throttle" in data:
            state["max_throttle"] = max(0, min(100, float(data["max_throttle"])))
        result = {k: state[k] for k in ["Kp", "Ki", "Kd", "integral_limit", "max_throttle"]}
    return jsonify({"ok": True, **result})


@app.route("/calibrate", methods=["POST"])
def recalibrate():
    """Re-run gyro bias calibration. Must be stationary. Pauses control for ~2s."""
    with state_lock:
        was_enabled = state["enabled"]
        state["enabled"] = False
        state["calibrating"] = True

    bus = smbus2.SMBus(1)
    set_motor(bus, 1500 if BIDIRECTIONAL_ESC else 1000)  # stop during calibration
    bias = calibrate_gyro(bus)
    bus.close()

    with state_lock:
        state["gz_bias"] = bias
        state["calibrating"] = False
        state["enabled"] = was_enabled
    return jsonify({"ok": True, "bias": bias})


@app.route("/stop", methods=["POST"])
def stop():
    """Emergency stop: disable everything, stop motor."""
    disable_controller()
    try:
        bus = smbus2.SMBus(1)
        set_motor(bus, 1500 if BIDIRECTIONAL_ESC else 1000)
        time.sleep(0.5)
        set_motor(bus, 0)  # signal off
        bus.close()
    except Exception:
        pass
    return jsonify({"ok": True})


@app.route("/health")
def health():
    global last_heartbeat
    last_heartbeat = time.monotonic()
    return jsonify({"ok": True})


if __name__ == "__main__":
    # Remove stale flag file
    try:
        os.remove(FLAG_FILE)
    except FileNotFoundError:
        pass

    # Start control loop thread
    threading.Thread(target=control_loop, daemon=True).start()
    threading.Thread(target=watchdog_loop, daemon=True).start()

    app.run(host="0.0.0.0", port=5001, threaded=True)
