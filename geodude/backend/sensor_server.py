from flask import Flask, jsonify, request, Response
import smbus2
import subprocess
import threading
import time
import os
import serial
import math

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
    """Query current target velocity from Pico and return connection status.
    Sends 'T\\n' (Commander read) and reads the response line.
    """
    ser = get_pico()
    connected = ser is not None and ser.is_open
    target = None
    if connected:
        try:
            with pico_lock:
                ser.write(b"T\n")
                line = ser.readline().decode(errors="ignore").strip()
            # SimpleFOC Commander responds with the value (e.g. "5.0000")
            target = float(line) if line else None
        except Exception as e:
            global pico_serial
            with pico_lock:
                pico_serial = None
            connected = False
            print("SimpleFOC status read error: %s" % e, flush=True)
    return jsonify({"connected": connected, "target": target})

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
    pca_init(freq=50)
    # No pca_all_off() — groundstation sends neutral positions on connect
    threading.Thread(target=sensor_loop, daemon=True).start()
    threading.Thread(target=camera_reader_thread, daemon=True).start()
    app.run(host="0.0.0.0", port=5000, threaded=True)
