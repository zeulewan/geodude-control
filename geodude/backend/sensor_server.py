from flask import Flask, jsonify, request, Response
import smbus2
import subprocess
import threading
import time
import os
import serial
import math
import json

app = Flask(__name__)
bus = smbus2.SMBus(1)
lock = threading.Lock()

# --- SimpleFOC serial (Pi Pico over USB) ---

PICO_PORT = "/dev/ttyACM0"
PICO_BAUD = 115200
pico_serial = None
pico_lock = threading.Lock()

def get_pico():
    """Return open serial port to Pico, opening it lazily if needed."""
    global pico_serial
    with pico_lock:
        if pico_serial is None or not pico_serial.is_open:
            try:
                pico_serial = serial.Serial(PICO_PORT, PICO_BAUD, timeout=0.5)
            except Exception as e:
                print("SimpleFOC serial open error: %s" % e, flush=True)
                pico_serial = None
        return pico_serial

def simplefoc_send(cmd):
    """Send a raw SimpleFOC Commander command (e.g. 'T5\\n'). Returns True on success."""
    try:
        ser = get_pico()
        if ser is None:
            return False, "serial not available"
        with pico_lock:
            ser.write((cmd.rstrip("\n") + "\n").encode())
        print("SimpleFOC: sent %r" % cmd.strip(), flush=True)
        return True, None
    except Exception as e:
        # Reset so next call retries open
        global pico_serial
        with pico_lock:
            pico_serial = None
        print("SimpleFOC serial error: %s" % e, flush=True)
        return False, str(e)

sensor_data = {
    "ax": 0, "ay": 0, "az": 0,
    "gx": 0, "gy": 0, "gz": 0,
    "angle": 0, "rpm": 0,
    "analog_va": 0, "analog_vb": 0,
    "analog_electrical_deg": 0, "analog_mechanical_deg": 0,
    "i2c_ok": False, "ads_ok": False, "imu_ok": False,
}

# --- PCA9685 PWM driver ---

PCA9685_ADDR = 0x40
MODE1 = 0x00
PRESCALE = 0xFE
LED0_ON_L = 0x06

# Channel mapping (pin - 1 = 0-indexed)
# MACE reaction wheel is no longer on PCA9685 — it is driven by Pi Pico via SimpleFOC
CHANNELS = {
    "B1":   0,
    "S1":   1,
    "E1":   2,
    "W1A":  3,
    "W1B":  4,
    "B2":   5,
    "S2":   6,
    "E2":   7,
    "W2A":  8,
    "W2B":  9,
}

def pca_init(freq=50):
    # Sleep to change prescale
    bus.write_byte_data(PCA9685_ADDR, MODE1, 0x10)  # SLEEP
    prescale = round(25_000_000 / (4096 * freq)) - 1
    bus.write_byte_data(PCA9685_ADDR, PRESCALE, prescale)
    # Wake: clear SLEEP, enable auto-increment + RESTART
    bus.write_byte_data(PCA9685_ADDR, MODE1, 0x00)  # wake
    time.sleep(0.005)
    bus.write_byte_data(PCA9685_ADDR, MODE1, 0xA0)  # RESTART + AI

def pca_set_pulse_us(channel, pulse_us, freq=50):
    period_us = 1_000_000 / freq
    counts = int(pulse_us / period_us * 4096)
    counts = max(0, min(4095, counts))
    reg = LED0_ON_L + 4 * channel
    with lock:
        bus.write_i2c_block_data(PCA9685_ADDR, reg, [
            0, 0, counts & 0xFF, (counts >> 8) & 0xFF,
        ])

def pca_off(channel):
    reg = LED0_ON_L + 4 * channel
    with lock:
        bus.write_i2c_block_data(PCA9685_ADDR, reg, [0, 0, 0, 0])

def pca_all_off():
    with lock:
        for ch in range(16):
            reg = LED0_ON_L + 4 * ch
            bus.write_i2c_block_data(PCA9685_ADDR, reg, [0, 0, 0, 0])

# --- Sensor reading ---

ADS1115_ADDR = 0x48
MAGNET_COUNT = 32
ANALOG_POLE_PAIRS = MAGNET_COUNT // 2
SENSOR_SUPPLY_V = 3.3
OFFSET_A_V = SENSOR_SUPPLY_V * 0.5
OFFSET_B_V = SENSOR_SUPPLY_V * 0.5
AMP_ALPHA = 0.01
MIN_SIGNAL_V = 0.02
ANGLE_HOLD_THRESHOLD_V = 0.01


def _i16(msb, lsb):
    value = (msb << 8) | lsb
    return value - 0x10000 if value & 0x8000 else value


def _wrap_delta_deg(delta):
    while delta > 180.0:
        delta -= 360.0
    while delta < -180.0:
        delta += 360.0
    return delta


class ADS1115:
    REG_CONVERSION = 0x00
    REG_CONFIG = 0x01
    OS_SINGLE = 0x8000
    MUX_SINGLE = (0x4000, 0x5000, 0x6000, 0x7000)
    PGA_4V096 = 0x0200
    MODE_SINGLE = 0x0100
    DATA_RATE_860 = 0x00E0
    COMP_DISABLE = 0x0003

    def __init__(self, bus_obj, address=ADS1115_ADDR):
        self.bus = bus_obj
        self.address = address

    def read_raw(self, channel):
        config = (
            self.OS_SINGLE
            | self.MUX_SINGLE[channel]
            | self.PGA_4V096
            | self.MODE_SINGLE
            | self.DATA_RATE_860
            | self.COMP_DISABLE
        )
        self.bus.write_i2c_block_data(self.address, self.REG_CONFIG, [(config >> 8) & 0xFF, config & 0xFF])
        time.sleep(0.002)
        msb, lsb = self.bus.read_i2c_block_data(self.address, self.REG_CONVERSION, 2)
        return _i16(msb, lsb)

    def read_voltage(self, channel):
        return self.read_raw(channel) * (4.096 / 32768.0)


def r16(addr, reg):
    h = bus.read_byte_data(addr, reg)
    l = bus.read_byte_data(addr, reg + 1)
    v = (h << 8) | l
    return v - 65536 if v > 32767 else v

def sensor_loop():
    ads = ADS1115(bus, ADS1115_ADDR)
    with lock:
        bus.write_byte_data(0x69, 0x06, 0x01)
    time.sleep(0.05)
    offset_a = OFFSET_A_V
    offset_b = OFFSET_B_V
    amp_a = 1.0
    amp_b = 1.0
    prev_electrical_deg = None
    continuous_electrical_deg = 0.0
    last_mechanical_deg = None
    last_time = None
    rpm_buf = []
    while True:
        try:
            with lock:
                ax = r16(0x69, 0x2D) / 16384.0
                ay = r16(0x69, 0x2F) / 16384.0
                az = r16(0x69, 0x31) / 16384.0
                gx = r16(0x69, 0x33) / 131.0
                gy = r16(0x69, 0x35) / 131.0
                gz = r16(0x69, 0x37) / 131.0
                va = ads.read_voltage(0)
                vb = ads.read_voltage(1)
            centered_a = va - offset_a
            centered_b = vb - offset_b
            amp_a = max(MIN_SIGNAL_V, (1.0 - AMP_ALPHA) * amp_a + AMP_ALPHA * abs(centered_a))
            amp_b = max(MIN_SIGNAL_V, (1.0 - AMP_ALPHA) * amp_b + AMP_ALPHA * abs(centered_b))
            norm_a = centered_a / amp_a
            norm_b = centered_b / amp_b

            electrical_deg = math.degrees(math.atan2(norm_b, norm_a))
            if electrical_deg < 0.0:
                electrical_deg += 360.0

            magnitude_v = math.sqrt(centered_a * centered_a + centered_b * centered_b)
            if magnitude_v >= ANGLE_HOLD_THRESHOLD_V:
                if prev_electrical_deg is None:
                    continuous_electrical_deg = electrical_deg
                else:
                    continuous_electrical_deg += _wrap_delta_deg(electrical_deg - prev_electrical_deg)
                prev_electrical_deg = electrical_deg
            elif prev_electrical_deg is None:
                prev_electrical_deg = electrical_deg

            continuous_mechanical_deg = continuous_electrical_deg / ANALOG_POLE_PAIRS
            angle = continuous_mechanical_deg % 360.0
            # Compute RPM from encoder at 100Hz
            now = time.monotonic()
            rpm = 0.0
            if last_mechanical_deg is not None and last_time is not None:
                dt = now - last_time
                if dt > 0:
                    delta = continuous_mechanical_deg - last_mechanical_deg
                    dps = delta / dt
                    rpm_buf.append(dps / 6.0)  # signed RPM
                    if len(rpm_buf) > 10:
                        rpm_buf.pop(0)
                    rpm = sum(rpm_buf) / len(rpm_buf)
            last_mechanical_deg = continuous_mechanical_deg
            last_time = now
            sensor_data.update({
                "ax": round(ax, 3), "ay": round(ay, 3), "az": round(az, 3),
                "gx": round(gx, 1), "gy": round(gy, 1), "gz": round(gz, 1),
                "angle": round(angle, 1),
                "rpm": round(rpm, 1),
                "analog_va": round(va, 5),
                "analog_vb": round(vb, 5),
                "analog_electrical_deg": round(electrical_deg, 2),
                "analog_mechanical_deg": round(angle, 2),
                "i2c_ok": True,
                "ads_ok": True,
                "imu_ok": True,
            })
        except Exception as e:
            print("sensor_loop error: %s" % e, flush=True)
            sensor_data.update({"i2c_ok": False, "ads_ok": False, "imu_ok": False})
        time.sleep(0.033)

# --- API ---

@app.route("/sensors")
def sensors():
    if os.path.exists("/tmp/motor_heartbeat"):
        os.utime("/tmp/motor_heartbeat", None)
    else:
        open("/tmp/motor_heartbeat","w").close()
    with lock:
        return jsonify(sensor_data)

@app.route("/system")
def system_stats():
    """CPU usage and temperature."""
    try:
        with open("/sys/class/thermal/thermal_zone0/temp") as f:
            temp = int(f.read().strip()) / 1000.0
    except Exception:
        temp = 0
    try:
        with open("/proc/loadavg") as f:
            load = float(f.read().split()[0])
    except Exception:
        load = 0
    try:
        with open("/proc/stat") as f:
            line = f.readline()
            parts = line.split()
            idle = int(parts[4])
            total = sum(int(x) for x in parts[1:])
        if not hasattr(system_stats, "_prev"):
            system_stats._prev = (total, idle)
        prev_total, prev_idle = system_stats._prev
        dt = total - prev_total
        di = idle - prev_idle
        cpu_pct = round((1.0 - di / dt) * 100, 1) if dt > 0 else 0
        system_stats._prev = (total, idle)
    except Exception:
        cpu_pct = 0
    return jsonify({"temp": round(temp, 1), "cpu": cpu_pct, "load": round(load, 2)})

@app.route("/simplefoc", methods=["POST"])
def simplefoc():
    """Send a velocity command to the Pico (SimpleFOC Commander protocol).
    Body: {"velocity": 5.0}  — sets target velocity in rad/s
       or {"command": "T5"} — sends a raw commander command
    """
    if os.path.exists("/tmp/attitude_active"):
        return jsonify({"ok": False, "error": "attitude controller active"}), 409
    data = request.json
    if "command" in data:
        cmd = str(data["command"])
    elif "velocity" in data:
        v = float(data["velocity"])
        cmd = "T%.4f" % v
    else:
        return jsonify({"ok": False, "error": "missing velocity or command"}), 400
    ok, err = simplefoc_send(cmd)
    if ok:
        return jsonify({"ok": True, "cmd": cmd})
    return jsonify({"ok": False, "error": err}), 502

@app.route("/simplefoc/status")
def simplefoc_status():
    """Query STM32 connection/target without fighting active live control."""
    ser = get_pico()
    connected = ser is not None and ser.is_open
    target = None
    if simplefoc_live_state.get("enabled") or simplefoc_live_state.get("sweep_busy"):
        return jsonify({
            "connected": connected,
            "target": simplefoc_live_state.get("rate_target_rpm"),
            "live": True,
        })
    if connected:
        try:
            with pico_lock:
                ser.write(b"S\n")
                deadline = time.time() + 0.25
                line = ""
                while time.time() < deadline:
                    line = ser.readline().decode(errors="ignore").strip()
                    if line.startswith("{") and line.endswith("}"):
                        break
            if line.startswith("{") and line.endswith("}"):
                status = json.loads(line)
                target = status.get("target", status.get("run_target"))
        except Exception as e:
            print("SimpleFOC status read error: %s" % e, flush=True)
    return jsonify({"connected": connected, "target": target})


# --- SimpleFOC autonomous profile tuning/logging ---

simplefoc_profile_lock = threading.Lock()
simplefoc_profile_stop_requested = False
simplefoc_profile_state = {
    "status": "idle",
    "busy": False,
    "last_status": None,
    "last_log": [],
    "raw": [],
    "error": None,
}


def _profile_add_raw(line):
    with simplefoc_profile_lock:
        simplefoc_profile_state["raw"].append(str(line))
        simplefoc_profile_state["raw"] = simplefoc_profile_state["raw"][-500:]


def _profile_set(**kwargs):
    with simplefoc_profile_lock:
        simplefoc_profile_state.update(kwargs)


def _profile_parse_status(line):
    if not line.startswith("{"):
        return None
    try:
        obj = json.loads(line)
    except Exception:
        return None
    _profile_set(last_status=obj)
    return obj


def _profile_send_locked(ser, cmd, read_for=0.3):
    cmd = str(cmd).strip()
    if not cmd:
        return []
    _profile_add_raw("TX " + cmd)
    ser.write((cmd + "\n").encode())
    ser.flush()
    lines = []
    end = time.time() + read_for
    while time.time() < end:
        line = ser.readline().decode(errors="ignore").strip()
        if not line:
            continue
        _profile_add_raw(line)
        _profile_parse_status(line)
        lines.append(line)
        if line.startswith("ERR"):
            break
    return lines


def _profile_read_until_locked(ser, deadline, stop_pred=None):
    lines = []
    while time.time() < deadline:
        with simplefoc_profile_lock:
            stop_requested = simplefoc_profile_stop_requested
        if stop_requested:
            _profile_send_locked(ser, "D", 0.2)
            _profile_add_raw("STOP_REQUESTED")
            break
        line = ser.readline().decode(errors="ignore").strip()
        if not line:
            continue
        _profile_add_raw(line)
        _profile_parse_status(line)
        lines.append(line)
        if line.startswith("ERR"):
            break
        if stop_pred and stop_pred(line):
            break
    return lines


def _profile_parse_log(lines):
    out = []
    in_log = False
    prev_t_s = None
    prev_rpm = None
    for line in lines:
        if line.startswith("LOG_BEGIN"):
            in_log = True
            continue
        if line.startswith("LOG_END"):
            break
        if not in_log or not line[:1].isdigit():
            continue
        parts = line.split(",")
        if len(parts) not in (4, 8):
            continue
        try:
            t_ms = float(parts[0])
            target = float(parts[1])
            enc_rpm = float(parts[2])
            uq = float(parts[3])
            ia = float(parts[4]) if len(parts) >= 8 else 0.0
            ib = float(parts[5]) if len(parts) >= 8 else 0.0
            ic_est = float(parts[6]) if len(parts) >= 8 else 0.0
            idc = float(parts[7]) if len(parts) >= 8 else 0.0
        except ValueError:
            continue
        target_rpm = target * 60.0 / (2.0 * math.pi)
        t_s = t_ms / 1000.0
        wheel_alpha = 0.0
        if prev_t_s is not None and prev_rpm is not None:
            dt = t_s - prev_t_s
            if dt > 0:
                wheel_alpha = (enc_rpm - prev_rpm) / dt
        prev_t_s = t_s
        prev_rpm = enc_rpm
        out.append({
            "t_ms": t_ms,
            "target": target,
            "target_rpm": target_rpm,
            "enc_rpm": enc_rpm,
            "enc_rpm_abs": abs(enc_rpm),
            "wheel_alpha_rpm_s": wheel_alpha,
            "wheel_alpha_abs": abs(wheel_alpha),
            "uq": uq,
            "ia": ia,
            "ib": ib,
            "ic_est": ic_est,
            "idc": idc,
            "ia_abs": abs(ia),
            "ib_abs": abs(ib),
            "ic_est_abs": abs(ic_est),
            "idc_abs": abs(idc),
            "rpm_error": abs(enc_rpm) - target_rpm,
            "rpm_error_abs": abs(abs(enc_rpm) - target_rpm),
        })
    return out


def _profile_begin(status):
    global simplefoc_profile_stop_requested
    with simplefoc_profile_lock:
        if simplefoc_profile_state["busy"]:
            return False
        simplefoc_profile_stop_requested = False
        simplefoc_profile_state.update({
            "busy": True,
            "status": status,
            "error": None,
            "raw": [],
        })
    return True


def _profile_finish(status=None, error=None):
    with simplefoc_profile_lock:
        if status is not None:
            simplefoc_profile_state["status"] = status
        simplefoc_profile_state["error"] = error
        simplefoc_profile_state["busy"] = False


def _profile_run_worker(params):
    if not _profile_begin("running"):
        return
    try:
        p = float(params.get("p", 0.2))
        i = float(params.get("i", 1.0))
        lpf = float(params.get("l", 0.05))
        voltage = float(params.get("v", 4.0))
        target = max(-52.36, min(float(params.get("target", 10.472)), 52.36))
        ramp = float(params.get("r", 2.0))
        hold = float(params.get("h", 5.0))
        ser = get_pico()
        if ser is None:
            raise RuntimeError("serial not available")
        with pico_lock:
            for cmd, delay in [
                ("D", 0.3),
                (f"P{p}", 0.2),
                (f"I{i}", 0.2),
                (f"L{lpf}", 0.2),
                (f"V{voltage}", 0.2),
                (f"R{ramp}", 0.2),
                (f"T{target}", 0.2),
                (f"H{hold}", 0.2),
            ]:
                lines = _profile_send_locked(ser, cmd, delay)
                if any(line.startswith("ERR") for line in lines):
                    _profile_send_locked(ser, "D", 0.2)
                    _profile_finish(lines[-1] if lines else "setup rejected")
                    return
            lines = _profile_send_locked(ser, "RUN", 0.2)
            if any(line.startswith("ERR") for line in lines):
                _profile_send_locked(ser, "D", 0.2)
                _profile_finish(lines[-1] if lines else "run rejected")
                return
            _profile_set(status="motion running, serial quiet")
            max_time = abs(target / max(ramp, 0.01)) + hold + abs(target / max(ramp, 0.01)) + 4
            lines = _profile_read_until_locked(
                ser,
                time.time() + max_time,
                lambda line: "RUN_DONE" in line or '"event":"done"' in line,
            )
            if any(line.startswith("ERR") for line in lines):
                _profile_send_locked(ser, "D", 0.2)
                _profile_finish(lines[-1])
                return
            _profile_set(status="dumping log")
            lines = _profile_send_locked(ser, "DUMP", 0.05)
            lines += _profile_read_until_locked(ser, time.time() + 8, lambda line: line.startswith("LOG_END"))
            with simplefoc_profile_lock:
                simplefoc_profile_state["last_log"] = _profile_parse_log(lines)
                count = len(simplefoc_profile_state["last_log"])
            _profile_send_locked(ser, "D", 0.3)
            _profile_finish(f"done, {count} log samples")
    except Exception as exc:
        _profile_finish("error", repr(exc))


def _profile_cmd_worker(cmds):
    if not _profile_begin("sending command"):
        return
    try:
        ser = get_pico()
        if ser is None:
            raise RuntimeError("serial not available")
        with pico_lock:
            for cmd, delay in cmds:
                _profile_send_locked(ser, cmd, delay)
        _profile_finish("idle")
    except Exception as exc:
        _profile_finish("error", repr(exc))


def _profile_dump_worker():
    if not _profile_begin("dumping"):
        return
    try:
        ser = get_pico()
        if ser is None:
            raise RuntimeError("serial not available")
        with pico_lock:
            lines = _profile_send_locked(ser, "DUMP", 0.05)
            lines += _profile_read_until_locked(ser, time.time() + 8, lambda line: line.startswith("LOG_END"))
        with simplefoc_profile_lock:
            simplefoc_profile_state["last_log"] = _profile_parse_log(lines)
            count = len(simplefoc_profile_state["last_log"])
        _profile_finish(f"done, {count} log samples")
    except Exception as exc:
        _profile_finish("error", repr(exc))


simplefoc_live_lock = threading.Lock()
simplefoc_live_stop = False
simplefoc_live_state = {
    "enabled": False,
    "mode": "angle",
    "status": "idle",
    "error": None,
    "body_angle": 0.0,
    "body_rate": 0.0,
    "body_zero": 0.0,
    "angle_target": 0.0,
    "rate_target_rpm": 0.0,
    "body_rate_target_dps": 0.0,
    "uq": 0.0,
    "kp": 3.0,
    "ki": 0.0,
    "kd": 0.8,
    "min_uq": 2.0,
    "max_uq": 5.0,
    "voltage": 12.0,
    "rate_ramp": 5.0,
    "angle_deadband": 0.3,
    "sweep_busy": False,
    "sweep_log": [],
    "angle_log": [],
    "min_wheel_uq": None,
    "min_body_uq": None,
    "wheel_rpm": 0.0,
    "wheel_alpha_rpm_s": 0.0,
    "gyro_zero_z": 0.0,
    "gyro_rate_z": 0.0,
}

simplefoc_torque_state = {
    "status": "idle",
    "busy": False,
    "error": None,
    "last_log": [],
    "body_log": [],
    "summary": {},
    "raw": [],
}


def _torque_set(**kwargs):
    with simplefoc_profile_lock:
        simplefoc_torque_state.update(kwargs)


def _torque_snapshot():
    with simplefoc_profile_lock:
        return dict(simplefoc_torque_state)


def _gyro_rate_z_dps():
    return float(sensor_data.get("gz", 0.0)) - float(simplefoc_live_state.get("gyro_zero_z", 0.0))


def _torque_run_worker(params):
    with simplefoc_profile_lock:
        if simplefoc_profile_state["busy"] or simplefoc_torque_state["busy"] or simplefoc_live_state.get("enabled"):
            simplefoc_torque_state.update({"status": "error", "error": "profile/control busy"})
            return
        simplefoc_torque_state.update({
            "status": "running",
            "busy": True,
            "error": None,
            "last_log": [],
            "body_log": [],
            "summary": {},
            "raw": [],
        })
    try:
        uq = max(-24.0, min(float(params.get("u", 1.0)), 24.0))
        voltage = max(0.0, min(float(params.get("v", simplefoc_live_state["voltage"])), 24.0))
        hold = max(0.1, min(float(params.get("h", 2.0)), 10.0))
        zero_body = bool(params.get("zero_body", True))
        zero_gyro = bool(params.get("zero_gyro", True))
        body_zero = _body_angle_raw() if zero_body else float(simplefoc_live_state.get("body_zero", _body_angle_raw()))
        gyro_zero = _live_calibrate_bias(0.5) if zero_gyro else float(simplefoc_live_state.get("gyro_zero_z", 0.0))
        _live_set(body_zero=body_zero, gyro_zero_z=gyro_zero)
        body_log = []
        ser = get_pico()
        if ser is None:
            raise RuntimeError("serial not available")
        with pico_lock:
            for cmd, delay in [
                ("D", 0.2),
                (f"V{voltage:.3f}", 0.2),
                (f"U{uq:.4f}", 0.2),
                (f"H{hold:.3f}", 0.2),
            ]:
                lines = _profile_send_locked(ser, cmd, delay)
                simplefoc_torque_state["raw"] = simplefoc_torque_state["raw"][-500:] + lines
                if any(line.startswith("ERR") for line in lines):
                    raise RuntimeError(lines[-1] if lines else "setup rejected")
            lines = _profile_send_locked(ser, "TU", 0.1)
            if any(line.startswith("ERR") for line in lines):
                raise RuntimeError(lines[-1] if lines else "torque rejected")
            start = time.monotonic()
            deadline = start + hold + 2.0
            prev_body = _body_angle_raw()
            prev_t = start
            done_lines = []
            old_timeout = ser.timeout
            ser.timeout = 0.001
            try:
                while time.monotonic() < deadline:
                    now = time.monotonic()
                    body_raw = _body_angle_raw()
                    body_angle = _wrap_delta_deg(body_raw - body_zero)
                    dt = max(0.001, now - prev_t)
                    body_rate_enc = _wrap_delta_deg(body_raw - prev_body) / dt
                    body_log.append({
                        "t": round(now - start, 4),
                        "body_angle": round(body_angle, 4),
                        "body_rate_enc": round(body_rate_enc, 4),
                        "body_rate_ads": round(_body_rate_dps(), 4),
                        "gyro_z": round(float(sensor_data.get("gz", 0.0)), 4),
                        "gyro_z_zeroed": round(float(sensor_data.get("gz", 0.0)) - gyro_zero, 4),
                        "uq": round(uq, 4),
                    })
                    prev_body = body_raw
                    prev_t = now
                    line = ser.readline().decode(errors="ignore").strip()
                    if line:
                        done_lines.append(line)
                        _profile_add_raw(line)
                        if "TORQUE_DONE" in line or '"event":"torque_done"' in line:
                            break
                    time.sleep(0.02)
            finally:
                ser.timeout = old_timeout
            lines = _profile_send_locked(ser, "DUMP", 0.05)
            lines += _profile_read_until_locked(ser, time.time() + 8, lambda line: line.startswith("LOG_END"))
            wheel_log = _profile_parse_log(lines)
            _profile_send_locked(ser, "D", 0.2)
        # The first encoder velocity sample after enabling can occasionally contain
        # SimpleFOC's stale velocity estimate. Keep it in the raw log but exclude
        # physically absurd spikes from the control summary.
        valid_wheel_log = [
            x for x in wheel_log[1:]
            if abs(x.get("enc_rpm", 0.0)) < 3000.0 and abs(x.get("wheel_alpha_rpm_s", 0.0)) < 20000.0
        ]
        max_wheel_alpha = max((abs(x.get("wheel_alpha_rpm_s", 0.0)) for x in valid_wheel_log), default=0.0)
        max_wheel_rpm = max((abs(x.get("enc_rpm", 0.0)) for x in valid_wheel_log), default=0.0)
        body_delta = 0.0
        if body_log:
            body_delta = body_log[-1]["body_angle"] - body_log[0]["body_angle"]
        max_body_rate = max((abs(x.get("body_rate_enc", 0.0)) for x in body_log), default=0.0)
        max_gyro = max((abs(x.get("gyro_z_zeroed", 0.0)) for x in body_log), default=0.0)
        _torque_set(
            status="done",
            busy=False,
            error=None,
            last_log=wheel_log,
            body_log=body_log,
            summary={
                "uq": uq,
                "voltage": voltage,
                "hold_s": hold,
                "max_wheel_alpha_rpm_s": max_wheel_alpha,
                "max_wheel_rpm": max_wheel_rpm,
                "body_delta_deg": body_delta,
                "max_body_rate_dps": max_body_rate,
                "max_gyro_z_dps": max_gyro,
                "gyro_zero_z": gyro_zero,
            },
        )
    except Exception as exc:
        try:
            _live_send("U0")
            _live_send("D")
        except Exception:
            pass
        _torque_set(status="error", busy=False, error=repr(exc))


def _live_set(**kwargs):
    with simplefoc_live_lock:
        simplefoc_live_state.update(kwargs)


def _live_snapshot():
    with simplefoc_live_lock:
        return dict(simplefoc_live_state)


def _live_send_locked(ser, cmd):
    ser.write((cmd.rstrip("\n") + "\n").encode())


def _live_send(cmd):
    ser = get_pico()
    if ser is None:
        raise RuntimeError("serial not available")
    with pico_lock:
        _live_send_locked(ser, cmd)


def _live_calibrate_bias(duration=1.0):
    samples = []
    deadline = time.time() + duration
    while time.time() < deadline:
        samples.append(float(sensor_data.get("gz", 0.0)))
        time.sleep(0.02)
    return sum(samples) / len(samples) if samples else 0.0


def _body_angle_raw():
    return float(sensor_data.get("analog_mechanical_deg", sensor_data.get("angle", 0.0)))


def _body_angle_from_zero(zero):
    return _wrap_delta_deg(_body_angle_raw() - zero)


def _body_rate_dps():
    return float(sensor_data.get("rpm", 0.0)) * 6.0


def _read_stm_status_locked(ser, read_for=0.25):
    ser.write(b"S\n")
    deadline = time.time() + read_for
    last = None
    while time.time() < deadline:
        line = ser.readline().decode(errors="ignore").strip()
        if not line:
            continue
        if line.startswith("{") and line.endswith("}"):
            try:
                last = json.loads(line)
            except Exception:
                pass
    return last or {}


def _breakaway_sweep_worker(config):
    if simplefoc_live_state.get("enabled"):
        _live_set(status="error", error="stop angle/rate control before sweep")
        return
    with simplefoc_profile_lock:
        if simplefoc_profile_state["busy"]:
            _live_set(status="error", error="profile runner busy")
            return
    start = abs(float(config.get("start", 0.1)))
    stop = abs(float(config.get("stop", 3.0)))
    step = abs(float(config.get("step", 0.05)))
    pulse_s = max(0.1, min(float(config.get("pulse_s", 0.5)), 2.0))
    rest_s = max(0.1, min(float(config.get("rest_s", 0.5)), 2.0))
    voltage = max(0.0, min(float(config.get("voltage", simplefoc_live_state["voltage"])), 24.0))
    wheel_rpm_threshold = abs(float(config.get("wheel_rpm_threshold", 2.0)))
    body_delta_threshold = abs(float(config.get("body_delta_threshold", 0.2)))
    body_rate_threshold = abs(float(config.get("body_rate_threshold", 1.0)))
    direction = 1.0 if float(config.get("direction", 1.0)) >= 0 else -1.0
    out = []
    min_wheel = None
    min_body = None
    _live_set(
        sweep_busy=True, status="breakaway sweep", error=None,
        sweep_log=[], min_wheel_uq=None, min_body_uq=None,
    )
    try:
        ser = get_pico()
        if ser is None:
            raise RuntimeError("serial not available")
        with pico_lock:
            _live_send_locked(ser, "D")
            time.sleep(0.2)
            _live_send_locked(ser, f"V{voltage:.3f}")
            _live_send_locked(ser, "MA")
            _live_send_locked(ser, "U0")
            _live_send_locked(ser, "E")
            uq = start
            while uq <= stop + 1e-9:
                signed_uq = direction * uq
                body_start = _body_angle_raw()
                st0 = _read_stm_status_locked(ser, 0.15)
                rpm_start = float(st0.get("enc_rpm", 0.0) or 0.0)
                _live_send_locked(ser, f"U{signed_uq:.4f}")
                max_wheel_rpm = 0.0
                max_body_rate = 0.0
                prev_body = body_start
                prev_t = time.monotonic()
                deadline = time.time() + pulse_s
                while time.time() < deadline:
                    time.sleep(0.04)
                    body_now = _body_angle_raw()
                    now = time.monotonic()
                    dt = max(0.001, now - prev_t)
                    body_rate = _wrap_delta_deg(body_now - prev_body) / dt
                    max_body_rate = max(max_body_rate, abs(body_rate))
                    prev_body = body_now
                    prev_t = now
                    st = _read_stm_status_locked(ser, 0.04)
                    rpm_now = float(st.get("enc_rpm", 0.0) or 0.0)
                    max_wheel_rpm = max(max_wheel_rpm, abs(rpm_now - rpm_start))
                body_end = _body_angle_raw()
                body_delta = _wrap_delta_deg(body_end - body_start)
                _live_send_locked(ser, "U0")
                moved_wheel = max_wheel_rpm >= wheel_rpm_threshold
                moved_body = (
                    abs(body_delta) >= body_delta_threshold
                    or (abs(body_delta) >= body_delta_threshold * 0.25 and max_body_rate >= body_rate_threshold)
                )
                if min_wheel is None and moved_wheel:
                    min_wheel = uq
                if min_body is None and moved_body:
                    min_body = uq
                out.append({
                    "uq": round(signed_uq, 4),
                    "max_wheel_rpm_delta": round(max_wheel_rpm, 3),
                    "body_delta_deg": round(body_delta, 4),
                    "max_body_rate_dps": round(max_body_rate, 4),
                    "wheel_breakaway": moved_wheel,
                    "body_response": moved_body,
                })
                _live_set(sweep_log=list(out), min_wheel_uq=min_wheel, min_body_uq=min_body)
                time.sleep(rest_s)
                if min_wheel is not None and min_body is not None:
                    break
                uq += step
            _live_send_locked(ser, "U0")
            _live_send_locked(ser, "D")
        _live_set(status="sweep done")
    except Exception as exc:
        _live_set(status="error", error=repr(exc))
        try:
            _live_send("U0")
            _live_send("D")
        except Exception:
            pass
    finally:
        _live_set(sweep_busy=False, enabled=False, uq=0.0)


def _simplefoc_live_worker(config):
    global simplefoc_live_stop
    with simplefoc_profile_lock:
        if simplefoc_profile_state["busy"]:
            _live_set(status="error", error="profile runner busy")
            return
    mode = str(config.get("mode", "angle"))
    voltage = float(config.get("voltage", simplefoc_live_state["voltage"]))
    rate_ramp = float(config.get("rate_ramp", simplefoc_live_state["rate_ramp"]))
    angle_target = float(config.get("angle_target", simplefoc_live_state["angle_target"]))
    rate_target_rpm = max(-1000.0, min(float(config.get("rate_target_rpm", simplefoc_live_state["rate_target_rpm"])), 1000.0))
    body_rate_target_dps = max(-60.0, min(float(config.get("body_rate_target_dps", simplefoc_live_state.get("body_rate_target_dps", 0.0))), 60.0))
    kp = float(config.get("kp", simplefoc_live_state["kp"]))
    ki = float(config.get("ki", simplefoc_live_state["ki"]))
    kd = float(config.get("kd", simplefoc_live_state["kd"]))
    min_uq = abs(float(config.get("min_uq", simplefoc_live_state["min_uq"])))
    max_uq = abs(float(config.get("max_uq", simplefoc_live_state["max_uq"])))
    angle_deadband = abs(float(config.get("angle_deadband", simplefoc_live_state.get("angle_deadband", 1.0))))
    max_uq = max(0.1, min(max_uq, 24.0))
    min_uq = min(min_uq, max_uq)
    voltage = max(0.0, min(voltage, 24.0))
    rate_ramp = max(0.01, min(rate_ramp, 50.0))
    rate_target_rads = rate_target_rpm * 2.0 * math.pi / 60.0

    simplefoc_live_stop = False
    body_zero = float(config.get("body_zero", simplefoc_live_state.get("body_zero", _body_angle_raw())))
    prev_body_raw = _body_angle_raw()
    body_angle_unwrapped = _wrap_delta_deg(prev_body_raw - body_zero)
    prev_body_angle = body_angle_unwrapped
    integral = 0.0
    last = time.monotonic()
    last_send = 0.0
    last_status_poll = 0.0
    last_wheel_rpm_sample_t = 0.0
    last_voltage_send = 0.0
    open_start_voltage = 3.0
    open_spool_seconds = 5.0
    open_boost_seconds = 2.0
    open_spool_rpm = 10.0
    body_rate_ref = 0.0
    last_uq_cmd = 0.0
    body_rate_filt = 0.0
    breakaway_until = 0.0
    wheel_rpm = 0.0
    wheel_alpha_rpm_s = 0.0
    breakaway_used = False
    try:
        ser = get_pico()
        if ser is None:
            raise RuntimeError("serial not available")
        with pico_lock:
            _live_send_locked(ser, "D")
            if mode == "rate":
                _live_send_locked(ser, f"V{voltage:.3f}")
                _live_send_locked(ser, "MR")
                _live_send_locked(ser, f"R{rate_ramp:.3f}")
                _live_send_locked(ser, f"T{rate_target_rads:.5f}")
            elif mode in ("angle_open", "body_rate_open"):
                _live_send_locked(ser, f"V{min(voltage, open_start_voltage):.3f}")
                _live_send_locked(ser, "MO")
                _live_send_locked(ser, f"R{rate_ramp:.3f}")
                _live_send_locked(ser, "T0")
            else:
                _live_send_locked(ser, f"V{voltage:.3f}")
                _live_send_locked(ser, "MA")
                _live_send_locked(ser, "U0")
            _live_send_locked(ser, "E")
        _live_set(
            enabled=True, mode=mode, status="running", error=None,
            body_angle=prev_body_angle, body_rate=0.0, body_zero=body_zero, angle_target=angle_target,
            rate_target_rpm=rate_target_rpm, body_rate_target_dps=body_rate_target_dps, uq=0.0,
            kp=kp, ki=ki, kd=kd, min_uq=min_uq, max_uq=max_uq,
            voltage=voltage, rate_ramp=rate_ramp, angle_log=[],
        )
        angle_log = []
        run_start = time.monotonic()

        while True:
            with simplefoc_live_lock:
                if simplefoc_live_stop:
                    break
                # Allow live retuning from config endpoint.
                angle_target = float(simplefoc_live_state["angle_target"])
                rate_target_rpm = max(-1000.0, min(float(simplefoc_live_state["rate_target_rpm"]), 1000.0))
                body_rate_target_dps = max(-60.0, min(float(simplefoc_live_state.get("body_rate_target_dps", body_rate_target_dps)), 60.0))
                kp = float(simplefoc_live_state["kp"])
                ki = float(simplefoc_live_state["ki"])
                kd = float(simplefoc_live_state["kd"])
                min_uq = abs(float(simplefoc_live_state["min_uq"]))
                max_uq = max(0.1, abs(float(simplefoc_live_state["max_uq"])))
                min_uq = min(min_uq, max_uq)
                angle_deadband = abs(float(simplefoc_live_state.get("angle_deadband", angle_deadband)))
            now = time.monotonic()
            dt = max(0.001, min(now - last, 0.1))
            last = now
            body_raw = _body_angle_raw()
            body_delta = _wrap_delta_deg(body_raw - prev_body_raw)
            prev_body_raw = body_raw
            body_angle_unwrapped += body_delta
            body_angle = body_angle_unwrapped
            encoder_rate_raw = body_delta / dt
            ads_rate_raw = _body_rate_dps()
            gyro_rate_z = _gyro_rate_z_dps()
            # Body-rate control needs to react to the actual base encoder
            # motion. Keep gyro in the blend, but make the encoder derivative
            # the primary signal so Uq follows measured body rate error.
            body_rate_raw = 0.65 * encoder_rate_raw + 0.25 * gyro_rate_z + 0.10 * ads_rate_raw
            alpha_rate = min(1.0, dt / (0.10 + dt))
            body_rate_filt += alpha_rate * (body_rate_raw - body_rate_filt)
            body_rate = body_rate_filt
            prev_body_angle = body_angle
            uq = 0.0
            if mode == "angle":
                error = angle_target - body_angle
                # Cascaded controller after old MACE code:
                # outer angle loop -> body-rate reference, inner rate loop -> motor effort.
                # The reference code's signed PWM effort maps most directly to
                # SimpleFOC signed Uq voltage, not wheel velocity.
                # Positive body angle requires negative wheel torque on this rig.
                rate_cap = 10.0
                rate_slew = 18.0
                desired_body_rate = max(-rate_cap, min(kp * error - kd * body_rate, rate_cap))
                max_rate_step = rate_slew * dt
                body_rate_ref += max(-max_rate_step, min(desired_body_rate - body_rate_ref, max_rate_step))
                rate_error = body_rate_ref - body_rate
                moving_target = abs(error) > angle_deadband or abs(body_rate_ref) > 0.5
                if abs(error) <= angle_deadband and abs(body_rate) < 2.0:
                    integral = 0.0
                    body_rate_ref = 0.0
                    uq = 0.0
                else:
                    overspeed_same_direction = (
                        abs(body_rate_ref) > 0.2
                        and body_rate_ref * body_rate > 0.0
                        and abs(body_rate) > abs(body_rate_ref)
                    )
                    if overspeed_same_direction:
                        # Coast rather than hammering reverse torque. The base
                        # breaks loose abruptly, and hard braking caused the
                        # visible snap-back.
                        integral *= max(0.0, 1.0 - 5.0 * dt)
                        raw_uq = 0.0
                    else:
                        integral += rate_error * dt
                        integral = max(-20.0, min(integral, 20.0))
                        raw_uq = -((0.18 * kp) * rate_error + (0.05 * ki) * integral)
                        if moving_target and abs(rate_error) > 0.4 and abs(raw_uq) < min_uq:
                            raw_uq = math.copysign(min_uq, raw_uq if abs(raw_uq) > 1e-6 else -rate_error)
                    uq = max(-max_uq, min(raw_uq, max_uq))
                max_uq_step = 8.0 * dt
                uq = last_uq_cmd + max(-max_uq_step, min(uq - last_uq_cmd, max_uq_step))
                last_uq_cmd = uq
                if now - last_send >= 0.04:
                    _live_send(f"U{uq:.3f}")
                    last_send = now
            elif mode == "body_rate":
                body_rate_ref = body_rate_target_dps
                rate_error = body_rate_ref - body_rate
                if abs(body_rate_ref) <= 0.2 and abs(body_rate) < 1.0:
                    integral = 0.0
                    raw_uq = 0.0
                else:
                    integral += rate_error * dt
                    integral = max(-40.0, min(integral, 40.0))
                    # Reference-style inner rate loop -> signed motor effort.
                    # Positive body rate needs negative wheel torque here.
                    raw_uq = -((0.55 * kp) * rate_error + (0.18 * ki) * integral)
                    # Deadband compensation only helps overcome the base
                    # bearing. It must not replace the PI output once the error
                    # grows large enough to demand more effort.
                    if abs(body_rate_ref) > 0.2 and abs(rate_error) > 0.4 and abs(raw_uq) < min_uq:
                        raw_uq = math.copysign(min_uq, raw_uq if abs(raw_uq) > 1e-6 else -rate_error)
                    # Avoid violent reverse braking when it is already moving
                    # faster than the requested rate. Bleed the integral and
                    # let the base coast unless the overspeed is large.
                    if (
                        abs(body_rate_ref) > 0.2
                        and body_rate_ref * body_rate > 0.0
                        and abs(body_rate) > abs(body_rate_ref) + 1.5
                        and raw_uq * body_rate > 0.0
                    ):
                        integral *= max(0.0, 1.0 - 6.0 * dt)
                        raw_uq = 0.0
                uq = max(-max_uq, min(raw_uq, max_uq))
                max_uq_step = 8.0 * dt
                uq = last_uq_cmd + max(-max_uq_step, min(uq - last_uq_cmd, max_uq_step))
                last_uq_cmd = uq
                if now - last_send >= 0.04:
                    _live_send(f"U{uq:.3f}")
                    last_send = now
            elif mode in ("angle_open", "body_rate_open"):
                # Start open-loop wheel velocity gently: the old MACE output was
                # motor effort, not a full-strength velocity target. Ramping
                # voltage separately avoids snapping the wheel before the base
                # has started moving.
                elapsed = now - run_start
                if elapsed < open_spool_seconds:
                    open_voltage = open_start_voltage
                else:
                    # Raise voltage before asking for the heavy speed ramp.
                    # Otherwise open-loop velocity can outrun the loaded wheel
                    # while the phase voltage is still too low, which just
                    # makes the motor whirr/slip.
                    open_voltage = min(voltage, open_start_voltage + 4.0 * (elapsed - open_spool_seconds))
                if now - last_voltage_send >= 0.2:
                    _live_send(f"V{open_voltage:.3f}")
                    last_voltage_send = now
                if mode == "angle_open":
                    error = angle_target - body_angle
                    integral += error * dt
                    integral = max(-100.0, min(integral, 100.0))
                    rate_cap = 14.0
                    rate_slew = 30.0
                    desired_body_rate = max(-rate_cap, min(kp * error - kd * body_rate, rate_cap))
                    max_rate_step = rate_slew * dt
                    body_rate_ref += max(-max_rate_step, min(desired_body_rate - body_rate_ref, max_rate_step))
                else:
                    body_rate_ref = body_rate_target_dps

                rate_error = body_rate_ref - body_rate
                # Match the old MACE structure: inner rate controller creates a
                # signed motor effort. Here that effort maps to open-loop wheel
                # velocity instead of brushed PWM duty. Positive body-rate demand
                # needs negative wheel velocity on this rig.
                integral += rate_error * dt
                integral = max(-100.0, min(integral, 100.0))
                effort = kp * 0.35 * rate_error + ki * 0.05 * integral
                effort = max(-1.0, min(effort, 1.0))
                if abs(rate_error) < 0.5:
                    effort = 0.0
                wheel_rpm_cmd = -effort * max(50.0, abs(rate_target_rpm))
                if (
                    mode == "angle_open"
                    and elapsed < open_spool_seconds + open_boost_seconds
                    and abs(angle_target - body_angle) > angle_deadband
                ):
                    # Give the loaded wheel a short low-power spool before the
                    # angle loop is allowed to demand the heavy correction. Then
                    # hold the same low speed briefly while voltage catches up.
                    # The direction matches the current angle error mapping.
                    wheel_rpm_cmd = -math.copysign(open_spool_rpm, angle_target - body_angle)
                rate_target_rads = wheel_rpm_cmd * 2.0 * math.pi / 60.0
                last_uq_cmd = wheel_rpm_cmd
                if now - last_send >= 0.04:
                    _live_send(f"T{rate_target_rads:.5f}")
                    last_send = now
            elif now - last_send >= 0.2:
                rate_target_rads = rate_target_rpm * 2.0 * math.pi / 60.0
                _live_send(f"T{rate_target_rads:.5f}")
                last_send = now
            if now - last_status_poll >= 0.2:
                try:
                    ser_status = get_pico()
                    if ser_status is not None:
                        with pico_lock:
                            st = _read_stm_status_locked(ser_status, 0.03)
                        if st:
                            rpm_now = float(st.get("enc_rpm", wheel_rpm) or 0.0)
                            if last_wheel_rpm_sample_t > 0.0:
                                sample_dt = max(1e-3, now - last_wheel_rpm_sample_t)
                                wheel_alpha_rpm_s = (rpm_now - wheel_rpm) / sample_dt
                            wheel_rpm = rpm_now
                            last_wheel_rpm_sample_t = now
                    last_status_poll = now
                except Exception:
                    last_status_poll = now
            if mode in ("angle", "body_rate", "angle_open", "body_rate_open"):
                angle_log.append({
                    "t": round(now - run_start, 3),
                    "target": round(angle_target, 3),
                    "body_angle": round(body_angle, 3),
                    "body_raw": round(body_raw, 3),
                    "body_rate": round(body_rate, 3),
                    "body_rate_raw": round(body_rate_raw, 3),
                    "gyro_rate_z": round(gyro_rate_z, 3),
                    "body_rate_ref": round(body_rate_ref, 3),
                    "wheel_alpha_cmd": round(last_uq_cmd, 3) if mode in ("body_rate", "angle_open", "body_rate_open") else 0.0,
                    "wheel_rpm": round(wheel_rpm, 3),
                    "wheel_alpha_rpm_s": round(wheel_alpha_rpm_s, 3),
                    "error": round(angle_target - body_angle, 3) if mode == "angle" else round(body_rate_ref - body_rate, 3),
                    "uq": round(uq, 4),
                })
                if len(angle_log) > 1500:
                    angle_log = angle_log[-1500:]
                if len(angle_log) % 5 == 0:
                    _live_set(angle_log=list(angle_log))
            _live_set(body_angle=round(body_angle, 3), body_rate=round(body_rate, 3), gyro_rate_z=round(gyro_rate_z, 3), wheel_rpm=round(wheel_rpm, 3), wheel_alpha_rpm_s=round(wheel_alpha_rpm_s, 3), uq=round(uq, 4))
            time.sleep(0.02)
    except Exception as exc:
        _live_set(status="error", error=repr(exc))
    finally:
        try:
            _live_send("U0")
            _live_send("T0")
            _live_send("D")
        except Exception:
            pass
        _live_set(enabled=False, status="idle")


@app.route("/simplefoc/profile/state")
def simplefoc_profile_state_route():
    with simplefoc_profile_lock:
        return jsonify(dict(simplefoc_profile_state))


@app.route("/simplefoc/profile/run", methods=["POST"])
def simplefoc_profile_run_route():
    with simplefoc_profile_lock:
        if simplefoc_profile_state["busy"]:
            return jsonify({"ok": False, "error": "busy"}), 409
    threading.Thread(target=_profile_run_worker, args=(request.json or {},), daemon=True).start()
    return jsonify({"ok": True})


@app.route("/simplefoc/profile/calibrate", methods=["POST"])
def simplefoc_profile_calibrate_route():
    with simplefoc_profile_lock:
        if simplefoc_profile_state["busy"]:
            return jsonify({"ok": False, "error": "busy"}), 409
    threading.Thread(target=_profile_cmd_worker, args=([("D", 0.3), ("G", 8.0), ("S", 0.3)],), daemon=True).start()
    return jsonify({"ok": True})


@app.route("/simplefoc/profile/stop", methods=["POST"])
def simplefoc_profile_stop_route():
    global simplefoc_profile_stop_requested
    with simplefoc_profile_lock:
        busy = simplefoc_profile_state["busy"]
        simplefoc_profile_stop_requested = True
    if not busy:
        threading.Thread(target=_profile_cmd_worker, args=([("D", 0.3)],), daemon=True).start()
    return jsonify({"ok": True})


@app.route("/simplefoc/profile/dump", methods=["POST"])
def simplefoc_profile_dump_route():
    with simplefoc_profile_lock:
        if simplefoc_profile_state["busy"]:
            return jsonify({"ok": False, "error": "busy"}), 409
    threading.Thread(target=_profile_dump_worker, daemon=True).start()
    return jsonify({"ok": True})


@app.route("/simplefoc/control/state")
def simplefoc_control_state_route():
    return jsonify(_live_snapshot())


@app.route("/simplefoc/control/start", methods=["POST"])
def simplefoc_control_start_route():
    with simplefoc_live_lock:
        if simplefoc_live_state["enabled"]:
            return jsonify({"ok": False, "error": "control already running"}), 409
    threading.Thread(target=_simplefoc_live_worker, args=(request.json or {},), daemon=True).start()
    return jsonify({"ok": True})


@app.route("/simplefoc/control/config", methods=["POST"])
def simplefoc_control_config_route():
    data = request.json or {}
    allowed = {
        "mode", "angle_target", "rate_target_rpm", "body_rate_target_dps", "kp", "ki", "kd",
        "min_uq", "max_uq", "voltage", "rate_ramp",
    }
    update = {k: data[k] for k in allowed if k in data}
    _live_set(**update)
    return jsonify({"ok": True, **_live_snapshot()})


@app.route("/simplefoc/control/zero", methods=["POST"])
def simplefoc_control_zero_route():
    zero = _body_angle_raw()
    gyro_zero = _live_calibrate_bias(0.8)
    _live_set(body_angle=0.0, body_rate=0.0, gyro_rate_z=0.0, body_zero=zero, gyro_zero_z=gyro_zero, uq=0.0)
    return jsonify({"ok": True, **_live_snapshot()})


@app.route("/simplefoc/control/stop", methods=["POST"])
def simplefoc_control_stop_route():
    global simplefoc_live_stop
    with simplefoc_live_lock:
        simplefoc_live_stop = True
    try:
        _live_send("U0")
        _live_send("T0")
        _live_send("D")
    except Exception:
        pass
    _live_set(enabled=False, status="idle", uq=0.0)
    return jsonify({"ok": True, **_live_snapshot()})


@app.route("/simplefoc/control/breakaway", methods=["POST"])
def simplefoc_control_breakaway_route():
    with simplefoc_live_lock:
        if simplefoc_live_state.get("sweep_busy"):
            return jsonify({"ok": False, "error": "sweep busy"}), 409
        if simplefoc_live_state.get("enabled"):
            return jsonify({"ok": False, "error": "stop control first"}), 409
    threading.Thread(target=_breakaway_sweep_worker, args=(request.json or {},), daemon=True).start()
    return jsonify({"ok": True})


@app.route("/simplefoc/torque/state")
def simplefoc_torque_state_route():
    return jsonify(_torque_snapshot())


@app.route("/simplefoc/torque/run", methods=["POST"])
def simplefoc_torque_run_route():
    threading.Thread(target=_torque_run_worker, args=(request.json or {},), daemon=True).start()
    return jsonify({"ok": True})


@app.route("/pwm", methods=["POST"])
def pwm():
    """Set PWM pulse width on any named channel.
    Body: {"channel": "B1", "pw": 1500} or {"channel": "B1", "pw": 0} to turn off.
    """
    data = request.json
    name = data.get("channel", "").upper()
    pw = int(data.get("pw", 0))
    if name not in CHANNELS:
        return jsonify({"ok": False, "error": f"unknown channel: {name}"}), 400
    ch = CHANNELS[name]
    pw = max(0, min(2500, pw))
    if pw == 0:
        pca_off(ch)
    else:
        pca_set_pulse_us(ch, pw)
    return jsonify({"ok": True, "channel": name, "ch": ch, "pw": pw})

@app.route("/pwm/off", methods=["POST"])
def pwm_all_off():
    """Turn all PCA9685 channels off."""
    pca_all_off()
    return jsonify({"ok": True})

@app.route("/channels")
def channels():
    """Return channel mapping."""
    return jsonify(CHANNELS)

# --- Camera MJPEG stream (fan-out to multiple clients) ---

camera_proc = None
camera_lock = threading.Lock()
camera_frame = None        # latest JPEG frame bytes
camera_frame_id = 0        # increments each new frame
camera_cond = threading.Condition()

def camera_reader_thread():
    """Single thread reads from rpicam-vid and buffers the latest frame."""
    global camera_proc, camera_frame, camera_frame_id
    while True:
        with camera_lock:
            if camera_proc is None or camera_proc.poll() is not None:
                camera_proc = subprocess.Popen([
                    "rpicam-vid", "-t", "0",
                    "--codec", "mjpeg",
                    "--width", "640", "--height", "480",
                    "--framerate", "10",
                    "--quality", "50",
                    "--vflip", "--hflip",
                    "--inline",
                    "-o", "-",
                ], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
            proc = camera_proc
        buf = b""
        while True:
            chunk = proc.stdout.read(4096)
            if not chunk:
                break
            buf += chunk
            while True:
                start = buf.find(b"\xff\xd8")
                if start == -1:
                    buf = b""
                    break
                end = buf.find(b"\xff\xd9", start + 2)
                if end == -1:
                    buf = buf[start:]
                    break
                with camera_cond:
                    camera_frame = buf[start:end + 2]
                    camera_frame_id += 1
                    camera_cond.notify_all()
                buf = buf[end + 2:]
        time.sleep(1)  # restart delay if process dies

def mjpeg_fanout():
    """Generator that yields MJPEG frames from the shared buffer."""
    last_id = 0
    while True:
        with camera_cond:
            camera_cond.wait(timeout=2)
            fid = camera_frame_id
            frame = camera_frame
        if fid != last_id and frame is not None:
            last_id = fid
            yield (b"--frame\r\n"
                   b"Content-Type: image/jpeg\r\n\r\n" + frame + b"\r\n")

@app.route("/camera")
def camera():
    return Response(mjpeg_fanout(),
                    mimetype="multipart/x-mixed-replace; boundary=frame")

if __name__ == "__main__":
    try:
        pca_init(freq=50)
    except Exception as e:
        print("PCA9685 init failed; continuing without PCA init: %s" % e, flush=True)
    # No pca_all_off() — groundstation sends neutral positions on connect
    threading.Thread(target=sensor_loop, daemon=True).start()
    threading.Thread(target=camera_reader_thread, daemon=True).start()
    app.run(host="0.0.0.0", port=5000, threaded=True)
