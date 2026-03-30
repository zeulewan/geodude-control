from flask import Flask, jsonify, request, Response
import smbus2
import subprocess
import threading
import time
import os

app = Flask(__name__)
bus = smbus2.SMBus(1)
lock = threading.Lock()

sensor_data = {"ax":0,"ay":0,"az":0,"gx":0,"gy":0,"gz":0,"angle":0}

# --- PCA9685 PWM driver ---

PCA9685_ADDR = 0x40
MODE1 = 0x00
PRESCALE = 0xFE
LED0_ON_L = 0x06

# Channel mapping (pin - 1 = 0-indexed)
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

def r16(addr, reg):
    h = bus.read_byte_data(addr, reg)
    l = bus.read_byte_data(addr, reg + 1)
    v = (h << 8) | l
    return v - 65536 if v > 32767 else v

def sensor_loop():
    with lock:
        bus.write_byte_data(0x69, 0x06, 0x01)
    time.sleep(0.05)
    while True:
        try:
            with lock:
                ax = r16(0x69, 0x2D) / 16384.0
                ay = r16(0x69, 0x2F) / 16384.0
                az = r16(0x69, 0x31) / 16384.0
                gx = r16(0x69, 0x33) / 131.0
                gy = r16(0x69, 0x35) / 131.0
                gz = r16(0x69, 0x37) / 131.0
                eh = bus.read_byte_data(0x36, 0x0c)
                el = bus.read_byte_data(0x36, 0x0d)
            angle = ((eh & 0x0F) << 8 | el) / 4096.0 * 360
            sensor_data.update({"ax":round(ax,3),"ay":round(ay,3),"az":round(az,3),"gx":round(gx,1),"gy":round(gy,1),"gz":round(gz,1),"angle":round(angle,1)})
        except:
            pass
        time.sleep(0.05)

# --- API ---

@app.route("/sensors")
def sensors():
    if os.path.exists("/tmp/motor_heartbeat"):
        os.utime("/tmp/motor_heartbeat", None)
    else:
        open("/tmp/motor_heartbeat","w").close()
    with lock:
        return jsonify(sensor_data)

@app.route("/motor", methods=["POST"])
def motor():
    """Legacy endpoint — controls MACE channel."""
    data = request.json
    pw = int(data.get("pw", 1000))
    pw = max(0, min(2000, pw))
    ch = CHANNELS["MACE"]
    if pw == 0:
        pca_off(ch)
        print("MOTOR: ch%d OFF" % ch, flush=True)
    else:
        pca_set_pulse_us(ch, pw)
        # Read back register to verify
        reg = LED0_ON_L + 4 * ch
        with lock:
            d = bus.read_i2c_block_data(PCA9685_ADDR, reg, 4)
        off_val = d[2] | (d[3] << 8)
        mode1 = bus.read_byte_data(PCA9685_ADDR, 0x00)
        print("MOTOR: ch%d pw=%d counts=%d readback=%d MODE1=0x%02X" % (ch, pw, int(pw/20000.0*4096), off_val, mode1), flush=True)
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

# --- Camera MJPEG stream ---

camera_proc = None
camera_lock = threading.Lock()

def get_camera_proc():
    global camera_proc
    with camera_lock:
        if camera_proc is None or camera_proc.poll() is not None:
            camera_proc = subprocess.Popen([
                "rpicam-vid", "-t", "0",
                "--codec", "mjpeg",
                "--width", "640", "--height", "480",
                "--framerate", "15",
                "--inline",
                "-o", "-",
            ], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        return camera_proc

def mjpeg_frames():
    proc = get_camera_proc()
    buf = b""
    while True:
        chunk = proc.stdout.read(4096)
        if not chunk:
            break
        buf += chunk
        # JPEG frames start with FF D8, end with FF D9
        while True:
            start = buf.find(b"\xff\xd8")
            if start == -1:
                buf = b""
                break
            end = buf.find(b"\xff\xd9", start + 2)
            if end == -1:
                buf = buf[start:]
                break
            frame = buf[start:end + 2]
            buf = buf[end + 2:]
            yield (b"--frame\r\n"
                   b"Content-Type: image/jpeg\r\n\r\n" + frame + b"\r\n")

@app.route("/camera")
def camera():
    return Response(mjpeg_frames(),
                    mimetype="multipart/x-mixed-replace; boundary=frame")

if __name__ == "__main__":
    pca_init(freq=50)
    pca_all_off()
    threading.Thread(target=sensor_loop, daemon=True).start()
    app.run(host="0.0.0.0", port=5000, threaded=True)
