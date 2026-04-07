"""GEO-DUDe sensor server.

Reads streaming JSON from STM32 Nucleo F446RE (SimpleFOC + IMU + encoder)
over USB serial. Serves Flask API for ground station.
"""
from flask import Flask, jsonify, request, Response
import subprocess
import threading
import time
import os
import json
import serial

app = Flask(__name__)

SERIAL_PORT = "/dev/ttyACM0"
SERIAL_BAUD = 115200
nucleo_serial = None
nucleo_write_lock = threading.Lock()
nucleo_connected = False
nucleo_last_line_time = 0

sensor_data = {
    "ax": 0, "ay": 0, "az": 0,
    "gx": 0, "gy": 0, "gz": 0,
    "angle": 0, "rpm": 0,
    "target": 0.0, "vel": 0, "ft": 0, "lpf": 0, "rmp": 0,
    "kd": 0, "ki": 0, "kp": 0, "sl": 0, "vl": 0,
    "sp": 0, "rt": 0,
    "en": 0, "me": 0, "p1": 0, "p2": 0, "p3": 0,
    "cm": 0, "tv": 0, "ii": -1,
}

def serial_reader_thread():
    global nucleo_serial, nucleo_connected, nucleo_last_line_time
    while True:
        try:
            if nucleo_serial is None or not nucleo_serial.is_open:
                try:
                    nucleo_serial = serial.Serial(SERIAL_PORT, SERIAL_BAUD, timeout=1)
                    nucleo_serial.dtr = False
                    nucleo_serial.rts = False
                    time.sleep(0.5)
                    nucleo_serial.reset_input_buffer()
                    print(f"Serial: opened {SERIAL_PORT}", flush=True)
                except Exception as e:
                    nucleo_connected = False
                    time.sleep(2)
                    continue
            line = nucleo_serial.readline()
            if not line:
                if time.monotonic() - nucleo_last_line_time > 5:
                    nucleo_connected = False
                    try: nucleo_serial.close()
                    except: pass
                    nucleo_serial = None
                    print("Serial: timeout, reopening", flush=True)
                continue
            line = line.decode(errors="ignore").strip()
            if not line.startswith("{"):
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue
            nucleo_connected = True
            nucleo_last_line_time = time.monotonic()
            sensor_data.update({
                "ax": round(data.get("ax", 0), 3),
                "ay": round(data.get("ay", 0), 3),
                "az": round(data.get("az", 0), 3),
                "gx": round(data.get("gx", 0), 1),
                "gy": round(data.get("gy", 0), 1),
                "gz": round(data.get("gz", 0), 1),
                "angle": round(data.get("enc", 0), 1),
                "rpm": round(data.get("rpm", 0), 1),
                "target": data.get("t", 0),
                "vel": data.get("vel", 0),
                "ft": data.get("ft", 0),
                "lpf": data.get("lpf", 0),
                "rmp": data.get("rmp", 0),
                "kd": data.get("kd", 0),
                "ki": data.get("ki", 0),
                "kp": data.get("kp", 0),
                "sl": data.get("sl", 0),
                "vl": data.get("vl", 0),
                "sp": data.get("sp", 0),
                "rt": data.get("rt", 0),
                "en": data.get("en", 0),
                "me": data.get("me", 0),
                "p1": data.get("da", 0),
                "p2": data.get("db", 0),
                "p3": data.get("dc", 0),
                "cm": data.get("cm", 0),
                "tv": data.get("tv", 0),
                "ii": data.get("ii", -1),
            })
        except serial.SerialException as e:
            print(f"Serial error: {e}", flush=True)
            nucleo_serial = None
            nucleo_connected = False
            time.sleep(1)
        except Exception as e:
            print(f"Reader error: {e}", flush=True)
            time.sleep(0.1)

def serial_send(cmd):
    global nucleo_serial, nucleo_connected
    with nucleo_write_lock:
        try:
            if nucleo_serial and nucleo_serial.is_open:
                nucleo_serial.write((cmd.strip() + "\n").encode())
                return True, None
            return False, "not connected"
        except Exception as e:
            nucleo_serial = None
            nucleo_connected = False
            return False, str(e)

# --- PCA9685 (optional) ---
PCA9685_ADDR = 0x40
MODE1 = 0x00
PRESCALE = 0xFE
LED0_ON_L = 0x06
pca_bus = None
CHANNELS = {
    "B1": 15, "S1": 14, "B2": 13, "S2": 12,
    "E1": 6, "E2": 4, "W1A": 3, "W1B": 2, "W2A": 1, "W2B": 0,
}

def pca_init(freq=50):
    global pca_bus
    try:
        import smbus2
        pca_bus = smbus2.SMBus(1)
        pca_bus.write_byte_data(PCA9685_ADDR, MODE1, 0x10)
        prescale = round(25_000_000 / (4096 * freq)) - 1
        pca_bus.write_byte_data(PCA9685_ADDR, PRESCALE, prescale)
        pca_bus.write_byte_data(PCA9685_ADDR, MODE1, 0x00)
        time.sleep(0.005)
        pca_bus.write_byte_data(PCA9685_ADDR, MODE1, 0xA0)
        print("PCA9685 initialized", flush=True)
    except Exception as e:
        pca_bus = None
        print(f"PCA9685 not found, skipping: {e}", flush=True)

def pca_set_pulse_us(channel, pulse_us, freq=50):
    if not pca_bus: return
    period_us = 1_000_000 / freq
    counts = int(pulse_us / period_us * 4096)
    counts = max(0, min(4095, counts))
    reg = LED0_ON_L + 4 * channel
    pca_bus.write_i2c_block_data(PCA9685_ADDR, reg, [0, 0, counts & 0xFF, (counts >> 8) & 0xFF])

def pca_off(channel):
    if not pca_bus: return
    reg = LED0_ON_L + 4 * channel
    pca_bus.write_i2c_block_data(PCA9685_ADDR, reg, [0, 0, 0, 0])

def pca_all_off():
    if not pca_bus: return
    for ch in range(16):
        reg = LED0_ON_L + 4 * ch
        pca_bus.write_i2c_block_data(PCA9685_ADDR, reg, [0, 0, 0, 0])

# --- API ---
@app.route("/sensors")
def sensors():
    return jsonify(sensor_data)

@app.route("/simplefoc/status")
def simplefoc_status():
    return jsonify({"connected": nucleo_connected, **sensor_data})

@app.route("/simplefoc", methods=["POST"])
def simplefoc_cmd():
    data = request.json
    if "velocity" in data:
        ok, err = serial_send("T%s" % data["velocity"])
    elif "command" in data:
        ok, err = serial_send(data["command"])
    else:
        return jsonify({"ok": False, "error": "need velocity or command"}), 400
    return jsonify({"ok": ok, "error": err})

@app.route("/system")
def system_stats():
    try:
        with open("/sys/class/thermal/thermal_zone0/temp") as f:
            temp = int(f.read().strip()) / 1000.0
    except: temp = 0
    try:
        with open("/proc/loadavg") as f:
            load_val = float(f.read().split()[0])
    except: load_val = 0
    try:
        with open("/proc/stat") as f:
            line = f.readline(); parts = line.split()
            idle = int(parts[4]); total = sum(int(x) for x in parts[1:])
        if not hasattr(system_stats, "_prev"): system_stats._prev = (total, idle)
        pt, pi = system_stats._prev
        dt = total - pt; di = idle - pi
        cpu_pct = round((1.0 - di / dt) * 100, 1) if dt > 0 else 0
        system_stats._prev = (total, idle)
    except: cpu_pct = 0
    return jsonify({"temp": round(temp, 1), "cpu": cpu_pct, "load": round(load_val, 2)})

@app.route("/uptime")
def uptime():
    try:
        with open("/proc/uptime") as f:
            secs = round(float(f.read().split()[0]))
        return jsonify({"uptime": secs})
    except: return jsonify({"uptime": 0})

@app.route("/pwm", methods=["POST"])
def pwm():
    data = request.json
    name = data.get("channel", "").upper()
    pw = int(data.get("pw", 0))
    if name not in CHANNELS:
        return jsonify({"ok": False, "error": "unknown channel: %s" % name}), 400
    ch = CHANNELS[name]
    pw = max(0, min(2500, pw))
    if pw == 0: pca_off(ch)
    else: pca_set_pulse_us(ch, pw)
    return jsonify({"ok": True, "channel": name, "ch": ch, "pw": pw})

@app.route("/pwm/off", methods=["POST"])
def pwm_all_off():
    pca_all_off()
    return jsonify({"ok": True})

@app.route("/channels")
def channels():
    return jsonify(CHANNELS)

# --- Camera ---
camera_proc = None
camera_lock = threading.Lock()
camera_frame = None
camera_frame_id = 0
camera_cond = threading.Condition()

def camera_reader_thread():
    global camera_proc, camera_frame, camera_frame_id
    while True:
        with camera_lock:
            if camera_proc is None or camera_proc.poll() is not None:
                camera_proc = subprocess.Popen([
                    "rpicam-vid", "-t", "0", "--codec", "mjpeg",
                    "--width", "640", "--height", "480", "--framerate", "10",
                    "--quality", "50", "--vflip", "--hflip", "--inline", "-o", "-",
                ], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
            proc = camera_proc
        buf = b""
        while True:
            chunk = proc.stdout.read(4096)
            if not chunk: break
            buf += chunk
            while True:
                start = buf.find(b"\xff\xd8")
                if start == -1: buf = b""; break
                end = buf.find(b"\xff\xd9", start + 2)
                if end == -1: buf = buf[start:]; break
                with camera_cond:
                    camera_frame = buf[start:end + 2]
                    camera_frame_id += 1
                    camera_cond.notify_all()
                buf = buf[end + 2:]
        time.sleep(1)

def mjpeg_fanout():
    last_id = 0
    while True:
        with camera_cond:
            camera_cond.wait(timeout=2)
            fid = camera_frame_id; frame = camera_frame
        if fid != last_id and frame is not None:
            last_id = fid
            yield (b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + frame + b"\r\n")

@app.route("/camera")
def camera():
    return Response(mjpeg_fanout(), mimetype="multipart/x-mixed-replace; boundary=frame")

if __name__ == "__main__":
    pca_init(freq=50)
    threading.Thread(target=serial_reader_thread, daemon=True).start()
    threading.Thread(target=camera_reader_thread, daemon=True).start()
    app.run(host="0.0.0.0", port=5000, threaded=True)
