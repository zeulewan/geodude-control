from flask import Flask, render_template_string, jsonify, request
import threading
import time
import json
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


HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>SOOS-1 Control</title>
<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body {
  background: #0a0e17;
  color: #e0e6f0;
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
  min-height: 100vh;
}
.header {
  background: #141824;
  border-bottom: 1px solid #1e2433;
  padding: 12px 24px;
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.header h1 {
  font-size: 20px;
  font-weight: 700;
  letter-spacing: 1px;
}
.header-status {
  display: flex;
  gap: 20px;
  align-items: center;
}
.status-indicator {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  color: #9ca3af;
}
.status-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: #ef4444;
  transition: background 0.3s;
}
.status-dot.ok { background: #22c55e; }
.status-dot.warn { background: #f59e0b; }

/* Sections */
.section-title { font-size: 12px; text-transform: uppercase; letter-spacing: 1px; color: #6b7280; margin: 24px 0 12px; padding-bottom: 8px; border-bottom: 1px solid #1e2433; }

.container {
  max-width: 1100px;
  margin: 0 auto;
  padding: 20px;
}
.two-col {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 20px;
}
.card {
  background: #141824;
  border: 1px solid #1e2433;
  border-radius: 12px;
  padding: 20px;
  margin-bottom: 20px;
}
.card h3 {
  font-size: 13px;
  text-transform: uppercase;
  letter-spacing: 1px;
  color: #6b7280;
  margin-bottom: 16px;
  font-weight: 600;
}
.inner {
  background: #1e293b;
  border-radius: 8px;
  padding: 12px;
}
.inner + .inner { margin-top: 10px; }

/* Camera */
.cam-wrapper {
  background: #000;
  border-radius: 8px;
  overflow: hidden;
  line-height: 0;
}
.cam-wrapper img {
  width: 100%;
  max-width: 100%;
  border-radius: 8px;
}

/* Sensor values */
.sensor-row {
  display: flex;
  gap: 12px;
  margin-bottom: 8px;
}
.sensor-val {
  flex: 1;
  text-align: center;
}
.sensor-val .label {
  font-size: 11px;
  color: #6b7280;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}
.sensor-val .value {
  font-family: 'SF Mono', 'Fira Code', monospace;
  font-size: 18px;
  font-weight: 600;
  margin-top: 2px;
}
.sensor-val .value.red { color: #ef4444; }
.sensor-val .value.green { color: #22c55e; }
.sensor-val .value.blue { color: #3b82f6; }

/* Encoder dial */
.encoder-section {
  display: flex;
  align-items: center;
  gap: 20px;
  margin-top: 12px;
}
.dial-wrapper {
  position: relative;
  width: 80px;
  height: 80px;
}
.dial-ring {
  width: 80px;
  height: 80px;
  border-radius: 50%;
  border: 3px solid #1e2433;
  position: relative;
}
.dial-center {
  position: absolute;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  width: 8px;
  height: 8px;
  background: #3b82f6;
  border-radius: 50%;
}
#needle {
  position: absolute;
  top: 50%;
  left: 50%;
  width: 2px;
  height: 32px;
  background: #3b82f6;
  transform-origin: 50% 0%;
  transform: rotate(0deg);
  border-radius: 1px;
}
.encoder-text {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.encoder-text .value {
  font-family: 'SF Mono', 'Fira Code', monospace;
  font-size: 24px;
  font-weight: 700;
}
.encoder-text .sub {
  font-size: 13px;
  color: #9ca3af;
}

/* System stats */
.sys-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}
.sys-item {
  display: flex;
  justify-content: space-between;
  padding: 6px 0;
  font-size: 13px;
}
.sys-item .label { color: #6b7280; }
.sys-item .value {
  font-family: 'SF Mono', 'Fira Code', monospace;
  font-weight: 600;
}

/* MACE status */
.status-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 6px 16px;
}
.status-row {
  display: flex;
  justify-content: space-between;
  font-size: 13px;
  padding: 4px 0;
}
.status-row .label { color: #6b7280; }
.status-row .value {
  font-family: 'SF Mono', 'Fira Code', monospace;
  font-weight: 600;
}
#motorError {
  color: #ef4444;
  font-size: 12px;
  margin-top: 8px;
  font-family: 'SF Mono', 'Fira Code', monospace;
  word-break: break-all;
}

/* Buttons */
.btn {
  display: inline-block;
  padding: 10px 20px;
  border: none;
  border-radius: 8px;
  font-size: 13px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  cursor: pointer;
  transition: background 0.2s, opacity 0.2s;
  color: #fff;
  background: #3b82f6;
}
.btn:hover { opacity: 0.85; }
.btn:active { opacity: 0.7; }
.btn-green { background: #22c55e; }
.btn-red { background: #ef4444; }
.btn-amber { background: #f59e0b; color: #000; }
.btn-dark { background: #1e293b; color: #9ca3af; }
.btn-sm { padding: 6px 12px; font-size: 12px; }
.btn.disabled {
  opacity: 0.4;
  pointer-events: none;
}
.btn-row {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
  margin-top: 12px;
}

/* Hold button */
.btn-hold {
  width: 100%;
  padding: 20px;
  font-size: 18px;
  letter-spacing: 2px;
  background: #1e293b;
  color: #6b7280;
  border: 2px solid #1e2433;
  margin-top: 16px;
  user-select: none;
  -webkit-user-select: none;
  touch-action: none;
}
.btn-hold.armed {
  background: #1e3a5f;
  color: #3b82f6;
  border-color: #3b82f6;
}
.btn-hold.armed:hover { background: #1e4a7f; }
.btn-hold.active-spin {
  background: #3b82f6;
  color: #fff;
  border-color: #60a5fa;
}

/* Sliders */
input[type="range"] {
  -webkit-appearance: none;
  appearance: none;
  width: 100%;
  height: 6px;
  background: #1e293b;
  border-radius: 3px;
  outline: none;
}
input[type="range"]::-webkit-slider-thumb {
  -webkit-appearance: none;
  appearance: none;
  width: 20px;
  height: 20px;
  background: #3b82f6;
  border-radius: 50%;
  cursor: pointer;
}
input[type="range"]::-moz-range-thumb {
  width: 20px;
  height: 20px;
  background: #3b82f6;
  border-radius: 50%;
  border: none;
  cursor: pointer;
}

.slider-group {
  margin-bottom: 16px;
}
.slider-label {
  display: flex;
  justify-content: space-between;
  font-size: 13px;
  margin-bottom: 6px;
}
.slider-label .label { color: #6b7280; }
.slider-label .value {
  font-family: 'SF Mono', 'Fira Code', monospace;
  color: #e0e6f0;
}

/* Throttle bar */
.throttle-bar-bg {
  width: 100%;
  height: 24px;
  background: #1e293b;
  border-radius: 6px;
  position: relative;
  overflow: hidden;
  margin: 12px 0;
}
#targetBar {
  position: absolute;
  top: 0;
  left: 0;
  height: 100%;
  background: rgba(59, 130, 246, 0.25);
  border-radius: 6px;
  transition: width 0.1s;
}
#currentBar {
  position: absolute;
  top: 0;
  left: 0;
  height: 100%;
  background: #3b82f6;
  border-radius: 6px;
  transition: width 0.15s;
}

/* Calibration panel */
#calPanel {
  background: #1e293b;
  border-radius: 8px;
  padding: 16px;
  margin-top: 12px;
}
#calPanel p {
  font-size: 14px;
  margin-bottom: 12px;
}

/* Attitude control */
.att-cols {
  display: grid;
  grid-template-columns: auto 1fr;
  gap: 24px;
  align-items: start;
}
.att-dial-section {
  text-align: center;
}
.att-stats {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 6px 16px;
}
.att-stat {
  display: flex;
  justify-content: space-between;
  font-size: 13px;
  padding: 4px 0;
}
.att-stat .label { color: #6b7280; }
.att-stat .value {
  font-family: 'SF Mono', 'Fira Code', monospace;
  font-weight: 600;
}
#attitudeBanner {
  background: #f59e0b;
  color: #000;
  padding: 8px 16px;
  border-radius: 8px;
  font-size: 13px;
  font-weight: 600;
  margin-bottom: 12px;
  text-align: center;
}
.att-setpoint-row {
  display: flex;
  gap: 10px;
  align-items: center;
  margin-top: 16px;
}
.att-setpoint-row input[type="number"] {
  background: #1e293b;
  border: 1px solid #1e2433;
  border-radius: 8px;
  color: #e0e6f0;
  padding: 8px 12px;
  font-size: 14px;
  font-family: 'SF Mono', 'Fira Code', monospace;
  width: 120px;
}

/* Gimbal */
.gimbal-status-line {
  font-size: 13px;
  color: #9ca3af;
  margin-bottom: 12px;
  font-family: 'SF Mono', 'Fira Code', monospace;
}
.driver-card {
  background: #1e293b;
  border-radius: 8px;
  padding: 16px;
  margin-bottom: 12px;
}
.driver-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 10px;
}
.driver-name {
  font-weight: 700;
  font-size: 15px;
}
.driver-badge {
  padding: 3px 10px;
  border-radius: 12px;
  font-size: 11px;
  font-weight: 700;
  text-transform: uppercase;
}
.badge-running { background: #22c55e; color: #000; }
.badge-idle { background: #6b7280; color: #fff; }
.badge-notfound { background: #ef4444; color: #fff; }
.badge-warn { background: #f59e0b; color: #000; margin-left: 6px; }
.driver-stats {
  font-size: 12px;
  color: #9ca3af;
  font-family: 'SF Mono', 'Fira Code', monospace;
  margin-bottom: 10px;
}
.driver-btns {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
  align-items: center;
}
.driver-btns input[type="number"] {
  background: #141824;
  border: 1px solid #1e2433;
  border-radius: 6px;
  color: #e0e6f0;
  padding: 6px 8px;
  font-size: 12px;
  width: 80px;
  font-family: 'SF Mono', 'Fira Code', monospace;
}

/* Servo channels */
.ch-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}
.ch-item {
  background: #1e293b;
  border-radius: 8px;
  padding: 14px;
}
.ch-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}
.ch-name {
  font-weight: 700;
  font-size: 14px;
}
.ch-val {
  font-family: 'SF Mono', 'Fira Code', monospace;
  font-size: 13px;
  color: #3b82f6;
}
.ch-controls {
  display: flex;
  gap: 8px;
  align-items: center;
  margin-top: 8px;
}
.ch-controls input[type="range"] {
  flex: 1;
}

/* Number input */
input[type="number"] {
  background: #1e293b;
  border: 1px solid #1e2433;
  border-radius: 6px;
  color: #e0e6f0;
  padding: 6px 10px;
  font-size: 13px;
  font-family: 'SF Mono', 'Fira Code', monospace;
}
input[type="number"]::-webkit-inner-spin-button,
input[type="number"]::-webkit-outer-spin-button {
  opacity: 1;
}

/* Responsive */
@media (max-width: 768px) {
  .two-col { grid-template-columns: 1fr; }
  .att-cols { grid-template-columns: 1fr; }
  .sys-grid { grid-template-columns: 1fr; }
  .ch-grid { grid-template-columns: 1fr; }
  .status-grid { grid-template-columns: 1fr; }
  .att-stats { grid-template-columns: 1fr; }
}
</style>
</head>
<body>

<!-- Header -->
<div class="header">
  <h1>SOOS-1 Control</h1>
  <div class="header-status">
    <div class="status-indicator">
      <div class="status-dot" id="statusDot"></div>
      <span id="statusText">GEO-DUDe</span>
    </div>
    <div class="status-indicator">
      <div class="status-dot" id="gimbalDot"></div>
      <span id="gimbalDotText">Gimbal</span>
    </div>
  </div>
</div>

<div class="container">

<div class="two-col">
  <!-- Left Column -->
  <div>
    <!-- Camera -->
    <div class="card">
      <h3>Camera</h3>
      <div class="cam-wrapper">
        <img id="camFeed" src="/api/camera" alt="Camera Feed">
      </div>
    </div>

    <!-- Sensors -->
    <div class="card">
      <h3>Sensors</h3>

      <div class="inner">
        <div style="font-size:11px;color:#6b7280;text-transform:uppercase;letter-spacing:0.5px;margin-bottom:8px;">Gyroscope (deg/s)</div>
        <div class="sensor-row">
          <div class="sensor-val">
            <div class="label">X</div>
            <div class="value red" id="gx">0.0</div>
          </div>
          <div class="sensor-val">
            <div class="label">Y</div>
            <div class="value green" id="gy">0.0</div>
          </div>
          <div class="sensor-val">
            <div class="label">Z</div>
            <div class="value blue" id="gz">0.0</div>
          </div>
        </div>
      </div>

      <div class="inner">
        <div style="font-size:11px;color:#6b7280;text-transform:uppercase;letter-spacing:0.5px;margin-bottom:8px;">Accelerometer (g)</div>
        <div class="sensor-row">
          <div class="sensor-val">
            <div class="label">X</div>
            <div class="value red" id="ax">0.0</div>
          </div>
          <div class="sensor-val">
            <div class="label">Y</div>
            <div class="value green" id="ay">0.0</div>
          </div>
          <div class="sensor-val">
            <div class="label">Z</div>
            <div class="value blue" id="az">0.0</div>
          </div>
        </div>
      </div>

      <div class="inner">
        <div style="font-size:11px;color:#6b7280;text-transform:uppercase;letter-spacing:0.5px;margin-bottom:8px;">Encoder</div>
        <div class="encoder-section">
          <div class="dial-wrapper">
            <div class="dial-ring">
              <div id="needle"></div>
              <div class="dial-center"></div>
            </div>
          </div>
          <div class="encoder-text">
            <div class="value" id="angleText">0.0&deg;</div>
            <div class="sub"><span id="rpmText">0</span> RPM</div>
          </div>
        </div>
      </div>
    </div>
  </div>

  <!-- Right Column -->
  <div>
    <!-- System Stats -->
    <div class="card">
      <h3>System Stats</h3>
      <div class="sys-grid">
        <div class="inner">
          <div style="font-size:11px;color:#6b7280;text-transform:uppercase;letter-spacing:0.5px;margin-bottom:8px;">Groundstation</div>
          <div class="sys-item"><span class="label">CPU</span><span class="value" id="gsCpu">--</span></div>
          <div class="sys-item"><span class="label">Temp</span><span class="value" id="gsTemp">--</span></div>
          <div class="sys-item"><span class="label">Load</span><span class="value" id="gsLoad">--</span></div>
        </div>
        <div class="inner">
          <div style="font-size:11px;color:#6b7280;text-transform:uppercase;letter-spacing:0.5px;margin-bottom:8px;">GEO-DUDe</div>
          <div class="sys-item"><span class="label">CPU</span><span class="value" id="gdCpu">--</span></div>
          <div class="sys-item"><span class="label">Temp</span><span class="value" id="gdTemp">--</span></div>
          <div class="sys-item"><span class="label">Load</span><span class="value" id="gdLoad">--</span></div>
        </div>
      </div>
    </div>

    <!-- MACE Status -->
    <div class="card">
      <h3>MACE Status</h3>
      <div class="status-grid">
        <div class="status-row"><span class="label">Armed</span><span class="value" id="armedStatus">NO</span></div>
        <div class="status-row"><span class="label">Target</span><span class="value" id="targetStatus">0%</span></div>
        <div class="status-row"><span class="label">Throttle</span><span class="value" id="throttleStatus">0%</span></div>
        <div class="status-row"><span class="label">PWM</span><span class="value" id="pwmStatus">0 us</span></div>
        <div class="status-row"><span class="label">Direction</span><span class="value" id="dirStatus">FWD</span></div>
        <div class="status-row"><span class="label">Wheel RPM</span><span class="value" id="maceRpm">0</span></div>
        <div class="status-row"><span class="label">Saturated</span><span class="value" id="maceSat">NO</span></div>
      </div>
      <div id="motorError"></div>
    </div>
  </div>
</div>

<!-- MACE Reaction Wheel (full width) -->
<div class="card">
  <h3>MACE Reaction Wheel</h3>

  <div class="slider-group">
    <div class="slider-label">
      <span class="label">Power</span>
      <span class="value" id="holdPowerVal">10%</span>
    </div>
    <input type="range" id="holdPower" min="10" max="100" value="10"
           oninput="document.getElementById('holdPowerVal').textContent = this.value + '%'">
  </div>

  <div class="slider-group">
    <div class="slider-label">
      <span class="label">Ramp Rate</span>
      <span class="value" id="rampVal">0.1%/s (1000.0s)</span>
    </div>
    <input type="range" id="rampRate" min="0.1" max="100" step="0.1" value="0.1"
           oninput="updateRampLabel(this.value); sendRampRate(this.value)">
  </div>

  <div class="throttle-bar-bg">
    <div id="targetBar" style="width:0%"></div>
    <div id="currentBar" style="width:0%"></div>
  </div>

  <button class="btn btn-hold disabled" id="holdBtn"
          onmousedown="holdStart()" onmouseup="holdStop()" onmouseleave="holdStop()"
          ontouchstart="holdStart(event)" ontouchend="holdStop()" ontouchcancel="holdStop()">
    HOLD TO SPIN
  </button>

  <div class="btn-row">
    <button class="btn btn-green" id="armBtn" onclick="toggleArm()">ARM</button>
    <button class="btn btn-amber" onclick="brake()">BRAKE</button>
    <button class="btn btn-dark" onclick="toggleReverse()">REVERSE</button>
    <button class="btn btn-dark" onclick="startCalibrate()">CALIBRATE ESC</button>
  </div>

  <div id="calPanel" style="display:none">
    <div id="calStep"></div>
    <div id="calBtns" class="btn-row"></div>
  </div>
</div>

<!-- Attitude Control (full width) -->
<div class="card" id="attitudeCard">
  <h3>Attitude Control</h3>
  <div id="attitudeBanner" style="display:none"></div>

  <div class="att-cols">
    <!-- Left: dial -->
    <div class="att-dial-section">
      <svg id="attDial" width="160" height="160" viewBox="0 0 160 160">
        <circle cx="80" cy="80" r="70" fill="none" stroke="#1e2433" stroke-width="4"/>
        <circle cx="80" cy="80" r="3" fill="#6b7280"/>
        <!-- Setpoint needle (amber) -->
        <line id="attSetpointNeedle" x1="80" y1="80" x2="80" y2="16" stroke="#f59e0b" stroke-width="2" stroke-linecap="round"/>
        <!-- Angle needle (blue) -->
        <line id="attAngleNeedle" x1="80" y1="80" x2="80" y2="16" stroke="#3b82f6" stroke-width="3" stroke-linecap="round"/>
        <text id="attRevs" x="80" y="125" text-anchor="middle" fill="#6b7280" font-size="11" font-family="'SF Mono','Fira Code',monospace">0 rev</text>
      </svg>
      <div style="margin-top:8px;">
        <div style="font-family:'SF Mono','Fira Code',monospace;font-size:20px;font-weight:700;" id="attAngleText">0.0&deg;</div>
        <div style="font-size:12px;color:#9ca3af;margin-top:2px;">Setpoint: <span id="attSetpointText">0.0&deg;</span></div>
      </div>
    </div>

    <!-- Right: stats -->
    <div>
      <div class="att-stats">
        <div class="att-stat"><span class="label">Error</span><span class="value" id="attError">--</span></div>
        <div class="att-stat"><span class="label">Output</span><span class="value" id="attOutput">--</span></div>
        <div class="att-stat"><span class="label">Motor</span><span class="value" id="attMotor">--</span></div>
        <div class="att-stat"><span class="label">PWM</span><span class="value" id="attPwm">--</span></div>
        <div class="att-stat"><span class="label">Wheel RPM</span><span class="value" id="attRpm">--</span></div>
        <div class="att-stat"><span class="label">Gz</span><span class="value" id="attGz">--</span></div>
        <div class="att-stat"><span class="label">Bias</span><span class="value" id="attBias">--</span></div>
        <div class="att-stat"><span class="label">Saturation</span><span class="value" id="attSat">--</span></div>
      </div>

      <div class="att-setpoint-row">
        <input type="number" id="attSetpointInput" placeholder="Angle" step="1" value="0">
        <button class="btn btn-sm" onclick="attSetpoint()">SET</button>
      </div>

      <div class="btn-row">
        <button class="btn btn-sm btn-dark" onclick="attNudge(-90)">-90</button>
        <button class="btn btn-sm btn-dark" onclick="attNudge(-10)">-10</button>
        <button class="btn btn-sm btn-dark" onclick="attNudge(10)">+10</button>
        <button class="btn btn-sm btn-dark" onclick="attNudge(90)">+90</button>
      </div>

      <div style="margin-top:16px;">
        <div class="slider-group">
          <div class="slider-label"><span class="label">Kp</span><span class="value" id="attKpVal">0</span></div>
          <input type="range" id="attKp" min="0" max="50" step="0.1" value="0" oninput="attUpdateGain()">
        </div>
        <div class="slider-group">
          <div class="slider-label"><span class="label">Ki</span><span class="value" id="attKiVal">0</span></div>
          <input type="range" id="attKi" min="0" max="10" step="0.01" value="0" oninput="attUpdateGain()">
        </div>
        <div class="slider-group">
          <div class="slider-label"><span class="label">Kd</span><span class="value" id="attKdVal">0</span></div>
          <input type="range" id="attKd" min="0" max="50" step="0.1" value="0" oninput="attUpdateGain()">
        </div>
        <div class="slider-group">
          <div class="slider-label"><span class="label">Max %</span><span class="value" id="attMaxVal">0</span></div>
          <input type="range" id="attMaxThrottle" min="0" max="100" step="1" value="0" oninput="attUpdateGain()">
        </div>
      </div>

      <div class="btn-row">
        <button class="btn btn-green" id="attEnableBtn" onclick="attToggleEnable()">ENABLE</button>
        <button class="btn btn-red" onclick="attStop()">STOP</button>
        <button class="btn btn-dark" onclick="attZero()">ZERO</button>
        <button class="btn btn-dark" onclick="attRecalibrate()">RECALIBRATE</button>
      </div>
    </div>
  </div>
</div>

<div class="section-title">Gimbal</div>

<div class="card">
  <h3>Gimbal Settings</h3>
  <div class="gimbal-status-line" id="gimbalStatus">Not connected</div>
  <div class="btn-row" style="margin-top:0">
    <button class="btn btn-sm" onclick="gimbalSetup()">SETUP DRIVERS</button>
    <button class="btn btn-sm btn-dark" onclick="gimbalScan()">SCAN</button>
    <button class="btn btn-sm btn-red" onclick="gimbalStopAll()">STOP ALL</button>
  </div>

  <div style="margin-top:16px;">
    <div class="slider-group">
      <div class="slider-label"><span class="label">Speed</span><span class="value" id="gimbalSpeedVal">2000 us</span></div>
      <input type="range" id="gimbalSpeed" min="100" max="8000" value="2000"
             oninput="gimbalSetSpeed(this.value)">
    </div>
    <div class="btn-row" style="margin-top:0">
      <button class="btn btn-sm btn-dark" onclick="gimbalSetSpeed(5000)">Slow (5000us)</button>
      <button class="btn btn-sm btn-dark" onclick="gimbalSetSpeed(2000)">Medium (2000us)</button>
      <button class="btn btn-sm btn-dark" onclick="gimbalSetSpeed(500)">Fast (500us)</button>
    </div>
  </div>

  <div style="margin-top:16px;">
    <div class="slider-group">
      <div class="slider-label"><span class="label">Current</span><span class="value" id="gimbalCurrentVal">400 mA</span></div>
      <input type="range" id="gimbalCurrent" min="50" max="2000" step="50" value="400"
             oninput="gimbalSetCurrent(this.value)">
    </div>
    <div class="btn-row" style="margin-top:0;align-items:center;">
      <input type="number" id="gimbalCurrentInput" value="400" min="50" max="2000" step="50" style="width:100px;">
      <button class="btn btn-sm" onclick="gimbalSetCurrent(document.getElementById('gimbalCurrentInput').value)">Set</button>
    </div>
  </div>
</div>

<div id="gimbalDrivers"></div>

<div class="section-title">Servos</div>

<div class="card">
  <h3>PCA9685 Channels</h3>
  <div style="margin-bottom:16px;">
    <button class="btn btn-dark" onclick="allChannelsCenter()">ALL CENTER</button>
  </div>
  <div class="ch-grid" id="chGrid"></div>
</div>

</div><!-- end container -->

<script>
/* ========== Channel controls ========== */
var CHANNELS = {
  "W2B": {ch: 0, pin: 1}, "W2A": {ch: 1, pin: 2}, "W1B": {ch: 2, pin: 3},
  "W1A": {ch: 3, pin: 4}, "E2": {ch: 4, pin: 5}, "E1": {ch: 6, pin: 7},
  "MACE": {ch: 11, pin: 12}, "S2": {ch: 12, pin: 13}, "B2": {ch: 13, pin: 14},
  "S1": {ch: 14, pin: 15}, "B1": {ch: 15, pin: 16}
};
var chOrder = ["B1","S1","B2","S2","MACE","E1","E2","W1A","W1B","W2A","W2B"];
var CH_RAMP_RATE = 20;
var CH_RAMP_HZ = 30;
var chRampTimers = {};

function usToDuty(us) {
  return (us / 20000 * 100).toFixed(1);
}

function chSlide(name, val) {
  val = parseInt(val);
  document.getElementById('chv_' + name).textContent = val + ' us (' + usToDuty(val) + '%)';
  fetch('/api/pwm', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({channel: name, pw: val})
  });
}

function chRampTo(name, target) {
  if (chRampTimers[name]) clearInterval(chRampTimers[name]);
  target = parseInt(target);
  chRampTimers[name] = setInterval(function() {
    var slider = document.getElementById('ch_' + name);
    var current = parseInt(slider.value);
    if (current === target) {
      clearInterval(chRampTimers[name]);
      chRampTimers[name] = null;
      return;
    }
    var step = CH_RAMP_RATE;
    if (Math.abs(target - current) < step) step = Math.abs(target - current);
    if (target > current) current += step;
    else current -= step;
    slider.value = current;
    chSlide(name, current);
  }, 1000 / CH_RAMP_HZ);
}

function chCenter(name) {
  chRampTo(name, 1500);
}

function allChannelsCenter() {
  chOrder.forEach(function(name) {
    if (name !== 'MACE') chCenter(name);
  });
}

function preventSliderJump(slider) {
  function handler(e) {
    var rect = slider.getBoundingClientRect();
    var x = (e.touches ? e.touches[0].clientX : e.clientX) - rect.left;
    var pct = x / rect.width;
    var min = parseFloat(slider.min);
    var max = parseFloat(slider.max);
    var val = min + pct * (max - min);
    var thumbVal = parseFloat(slider.value);
    var range = max - min;
    var threshold = range * 0.05;
    if (Math.abs(val - thumbVal) > threshold) {
      e.preventDefault();
    }
  }
  slider.addEventListener('mousedown', handler);
  slider.addEventListener('touchstart', handler, {passive: false});
}

/* Build servo channel UI */
(function() {
  var grid = document.getElementById('chGrid');
  chOrder.forEach(function(name) {
    if (name === 'MACE') return;
    var item = document.createElement('div');
    item.className = 'ch-item';
    item.innerHTML = '<div class="ch-header">' +
      '<span class="ch-name">' + name + ' <span style="font-size:11px;color:#6b7280;">(ch ' + CHANNELS[name].ch + ', pin ' + CHANNELS[name].pin + ')</span></span>' +
      '<span class="ch-val" id="chv_' + name + '">1500 us (' + usToDuty(1500) + '%)</span>' +
      '</div>' +
      '<input type="range" id="ch_' + name + '" min="500" max="2500" step="10" value="1500" ' +
      'oninput="chSlide(&quot;' + name + '&quot;, this.value)">' +
      '<div class="ch-controls">' +
      '<button class="btn btn-sm btn-dark" onclick="chCenter(&quot;' + name + '&quot;)">Center</button>' +
      '</div>';
    grid.appendChild(item);

    setTimeout(function() {
      var sl = document.getElementById('ch_' + name);
      if (sl) preventSliderJump(sl);
    }, 0);
  });
})();

/* ========== MACE Controls ========== */
var isReverse = false;
var isHolding = false;

function updateRampLabel(val) {
  val = parseFloat(val);
  var power = parseInt(document.getElementById('holdPower').value);
  var t = val > 0 ? (power / val).toFixed(1) : 'inf';
  document.getElementById('rampVal').textContent = val + '%/s (' + t + 's)';
}

function sendRampRate(val) {
  fetch('/api/config', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({ramp_rate: parseFloat(val)})
  });
}

function holdStart(e) {
  if (e && e.preventDefault) e.preventDefault();
  isHolding = true;
  var power = parseInt(document.getElementById('holdPower').value);
  var btn = document.getElementById('holdBtn');
  btn.classList.add('active-spin');
  fetch('/api/throttle', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({target: power, reverse: isReverse})
  });
}

function holdStop() {
  if (!isHolding) return;
  isHolding = false;
  var btn = document.getElementById('holdBtn');
  btn.classList.remove('active-spin');
  fetch('/api/throttle', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({target: 0, reverse: isReverse})
  });
}

function toggleArm() {
  fetch('/api/arm', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'}
  }).then(function(r) { return r.json(); }).then(function(d) {
    updateArmUI(d.armed, d.arming);
  });
}

function brake() {
  fetch('/api/brake', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'}
  });
}

function toggleReverse() {
  isReverse = !isReverse;
  fetch('/api/throttle', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({target: 0, reverse: isReverse})
  });
}

function updateArmUI(armed, arming) {
  var armBtn = document.getElementById('armBtn');
  var holdBtn = document.getElementById('holdBtn');
  if (arming) {
    armBtn.textContent = 'ARMING...';
    armBtn.className = 'btn btn-amber';
    holdBtn.classList.add('disabled');
    holdBtn.classList.remove('armed');
  } else if (armed) {
    armBtn.textContent = 'DISARM';
    armBtn.className = 'btn btn-red';
    holdBtn.classList.remove('disabled');
    holdBtn.classList.add('armed');
  } else {
    armBtn.textContent = 'ARM';
    armBtn.className = 'btn btn-green';
    holdBtn.classList.add('disabled');
    holdBtn.classList.remove('armed');
  }
}

/* ========== Calibration ========== */
function startCalibrate() {
  var panel = document.getElementById('calPanel');
  panel.style.display = 'block';
  document.getElementById('calStep').innerHTML = '<p><strong>Step 1:</strong> Disconnect ESC power, then click SEND MAX.</p>';
  document.getElementById('calBtns').innerHTML = '<button class="btn btn-sm" onclick="calStep2()">SEND MAX</button>' +
    '<button class="btn btn-sm btn-dark" onclick="calCancel()">Cancel</button>';
}

function calStep2() {
  fetch('/api/calibrate', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({step: 'max'})
  });
  document.getElementById('calStep').innerHTML = '<p><strong>Step 2:</strong> Connect ESC power. Wait for beeps, then click SEND MIN.</p>';
  document.getElementById('calBtns').innerHTML = '<button class="btn btn-sm" onclick="calStep3()">SEND MIN</button>' +
    '<button class="btn btn-sm btn-dark" onclick="calCancel()">Cancel</button>';
}

function calStep3() {
  fetch('/api/calibrate', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({step: 'min'})
  });
  document.getElementById('calStep').innerHTML = '<p><strong>Step 3:</strong> Wait for confirmation beeps, then click DONE.</p>';
  document.getElementById('calBtns').innerHTML = '<button class="btn btn-sm btn-green" onclick="calDone()">DONE</button>' +
    '<button class="btn btn-sm btn-dark" onclick="calCancel()">Cancel</button>';
}

function calDone() {
  document.getElementById('calPanel').style.display = 'none';
}

function calCancel() {
  fetch('/api/calibrate', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({step: 'cancel'})
  });
  document.getElementById('calPanel').style.display = 'none';
}

/* ========== Polling ========== */
function poll() {
  fetch('/api/sensors').then(function(r) { return r.json(); }).then(function(d) {
    /* Gyro */
    document.getElementById('gx').textContent = d.gyro.x.toFixed(1);
    document.getElementById('gy').textContent = d.gyro.y.toFixed(1);
    document.getElementById('gz').textContent = d.gyro.z.toFixed(1);
    /* Accel */
    document.getElementById('ax').textContent = d.accel.x.toFixed(2);
    document.getElementById('ay').textContent = d.accel.y.toFixed(2);
    document.getElementById('az').textContent = d.accel.z.toFixed(2);
    /* Encoder */
    var angle = d.encoder_angle;
    document.getElementById('angleText').innerHTML = angle.toFixed(1) + '&deg;';
    document.getElementById('rpmText').textContent = d.rpm;
    var needleAngle = (angle % 360);
    document.getElementById('needle').style.transform = 'rotate(' + needleAngle + 'deg)';
    /* Arm state */
    updateArmUI(d.armed, d.arming);
    /* Status */
    document.getElementById('armedStatus').textContent = d.armed ? 'YES' : 'NO';
    document.getElementById('armedStatus').style.color = d.armed ? '#22c55e' : '#ef4444';
    document.getElementById('targetStatus').textContent = d.target.toFixed(1) + '%';
    document.getElementById('throttleStatus').textContent = d.throttle.toFixed(1) + '%';
    var pw = d.reverse ? (1000 - Math.round(d.throttle) * 10) : (1000 + Math.round(d.throttle) * 10);
    document.getElementById('pwmStatus').textContent = pw + ' us';
    document.getElementById('dirStatus').textContent = d.reverse ? 'REV' : 'FWD';
    document.getElementById('dirStatus').style.color = d.reverse ? '#f59e0b' : '#22c55e';
    document.getElementById('maceRpm').textContent = d.rpm;
    var sat = d.rpm >= 600;
    document.getElementById('maceSat').textContent = sat ? 'YES' : 'NO';
    document.getElementById('maceSat').style.color = sat ? '#ef4444' : '#22c55e';
    /* Throttle bars */
    document.getElementById('targetBar').style.width = d.target + '%';
    document.getElementById('currentBar').style.width = d.throttle + '%';
    /* Motor error */
    var errDiv = document.getElementById('motorError');
    if (d.motor_error) {
      errDiv.textContent = d.motor_error;
      errDiv.style.display = 'block';
    } else {
      errDiv.textContent = '';
      errDiv.style.display = 'none';
    }
    /* Connection dot */
    var dot = document.getElementById('statusDot');
    if (d.connected) {
      dot.className = 'status-dot ok';
    } else {
      dot.className = 'status-dot';
    }
  }).catch(function() {
    document.getElementById('statusDot').className = 'status-dot';
  });
}

function sysPoll() {
  fetch('/api/system').then(function(r) { return r.json(); }).then(function(d) {
    var gs = d.groundstation || {};
    var gd = d.geodude || {};
    document.getElementById('gsCpu').textContent = (gs.cpu || 0) + '%';
    document.getElementById('gsTemp').textContent = (gs.temp || 0) + ' C';
    document.getElementById('gsLoad').textContent = (gs.load || 0);
    document.getElementById('gdCpu').textContent = (gd.cpu || 0) + '%';
    document.getElementById('gdTemp').textContent = (gd.temp || 0) + ' C';
    document.getElementById('gdLoad').textContent = (gd.load || 0);
  }).catch(function() {});
}

/* ========== Attitude Control ========== */
var attEnabled = false;
var attGainTimer = null;
var attGainsSynced = false;

function attToggleEnable() {
  var url = attEnabled ? '/api/attitude/disable' : '/api/attitude/enable';
  fetch(url, {method: 'POST'}).then(function(r) { return r.json(); }).then(function(d) {
    if (!d.error) attEnabled = !attEnabled;
  });
}

function attStop() {
  fetch('/api/attitude/stop', {method: 'POST'});
}

function attZero() {
  fetch('/api/attitude/zero', {method: 'POST'});
}

function attRecalibrate() {
  fetch('/api/attitude/calibrate', {method: 'POST'});
}

function attSetpoint() {
  var val = parseFloat(document.getElementById('attSetpointInput').value) || 0;
  fetch('/api/attitude/setpoint', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({angle: val})
  });
}

function attNudge(delta) {
  fetch('/api/attitude/nudge', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({delta: delta})
  });
}

function attUpdateGain() {
  document.getElementById('attKpVal').textContent = document.getElementById('attKp').value;
  document.getElementById('attKiVal').textContent = document.getElementById('attKi').value;
  document.getElementById('attKdVal').textContent = document.getElementById('attKd').value;
  document.getElementById('attMaxVal').textContent = document.getElementById('attMaxThrottle').value;
  if (attGainTimer) clearTimeout(attGainTimer);
  attGainTimer = setTimeout(function() {
    fetch('/api/attitude/gains', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        kp: parseFloat(document.getElementById('attKp').value),
        ki: parseFloat(document.getElementById('attKi').value),
        kd: parseFloat(document.getElementById('attKd').value),
        max_throttle: parseFloat(document.getElementById('attMaxThrottle').value)
      })
    });
  }, 200);
}

var attLastPoll = 0;
function attPoll() {
  fetch('/api/attitude/status').then(function(r) { return r.json(); }).then(function(d) {
    if (d.error) {
      document.getElementById('attitudeBanner').style.display = 'block';
      document.getElementById('attitudeBanner').textContent = 'Attitude controller not reachable';
      return;
    }
    attLastPoll = Date.now();
    /* Update enabled state */
    attEnabled = d.enabled || false;
    var eb = document.getElementById('attEnableBtn');
    if (attEnabled) {
      eb.textContent = 'DISABLE';
      eb.className = 'btn btn-red';
    } else {
      eb.textContent = 'ENABLE';
      eb.className = 'btn btn-green';
    }
    /* Stats */
    document.getElementById('attError').textContent = (d.error_deg != null ? d.error_deg.toFixed(1) + ' deg' : '--');
    document.getElementById('attOutput').textContent = (d.output != null ? d.output.toFixed(1) + '%' : '--');
    document.getElementById('attMotor').textContent = (d.motor_throttle != null ? d.motor_throttle.toFixed(1) + '%' : '--');
    document.getElementById('attPwm').textContent = (d.motor_pw != null ? d.motor_pw + ' us' : '--');
    document.getElementById('attRpm').textContent = (d.rpm != null ? d.rpm : '--');
    document.getElementById('attGz').textContent = (d.gz != null ? d.gz.toFixed(2) + ' deg/s' : '--');
    document.getElementById('attBias').textContent = (d.gyro_bias != null ? d.gyro_bias.toFixed(4) : '--');
    document.getElementById('attSat').textContent = (d.saturated ? 'YES' : 'NO');
    document.getElementById('attSat').style.color = d.saturated ? '#ef4444' : '#22c55e';
    /* Angle + setpoint */
    var angle = d.angle || 0;
    var setpoint = d.setpoint || 0;
    document.getElementById('attAngleText').innerHTML = angle.toFixed(1) + '&deg;';
    document.getElementById('attSetpointText').innerHTML = setpoint.toFixed(1) + '&deg;';
    /* Dial needles */
    var aNorm = angle % 360;
    var sNorm = setpoint % 360;
    document.getElementById('attAngleNeedle').setAttribute('transform', 'rotate(' + aNorm + ' 80 80)');
    document.getElementById('attSetpointNeedle').setAttribute('transform', 'rotate(' + sNorm + ' 80 80)');
    /* Revs */
    var revs = Math.floor(angle / 360);
    document.getElementById('attRevs').textContent = revs + ' rev';
    /* Sync gains once */
    if (!attGainsSynced && d.gains) {
      attGainsSynced = true;
      if (d.gains.kp != null) { document.getElementById('attKp').value = d.gains.kp; document.getElementById('attKpVal').textContent = d.gains.kp; }
      if (d.gains.ki != null) { document.getElementById('attKi').value = d.gains.ki; document.getElementById('attKiVal').textContent = d.gains.ki; }
      if (d.gains.kd != null) { document.getElementById('attKd').value = d.gains.kd; document.getElementById('attKdVal').textContent = d.gains.kd; }
      if (d.gains.max_throttle != null) { document.getElementById('attMaxThrottle').value = d.gains.max_throttle; document.getElementById('attMaxVal').textContent = d.gains.max_throttle; }
    }
    /* Banner: watchdog */
    var banner = document.getElementById('attitudeBanner');
    if (d.watchdog_triggered) {
      banner.style.display = 'block';
      banner.textContent = 'WATCHDOG TRIGGERED - Motor stopped';
      banner.style.background = '#ef4444';
      banner.style.color = '#fff';
    } else {
      banner.style.display = 'none';
    }
  }).catch(function() {
    /* Check stale */
    if (attLastPoll > 0 && Date.now() - attLastPoll > 5000) {
      document.getElementById('attitudeBanner').style.display = 'block';
      document.getElementById('attitudeBanner').textContent = 'Attitude controller connection lost';
    }
  });
}

/* ========== Gimbal ========== */
var gimbalPollTimer = null;

function gimbalSetup() {
  fetch('/api/gimbal/setup', {method: 'POST'}).then(function(r) { return r.json(); }).then(function() {
    gimbalPoll();
  });
}

function gimbalScan() {
  fetch('/api/gimbal/scan', {method: 'POST'}).then(function(r) { return r.json(); }).then(function() {
    gimbalPoll();
  });
}

function gimbalStopAll() {
  fetch('/api/gimbal/stop_all', {method: 'POST'});
}

function gimbalMove(driver, steps) {
  fetch('/api/gimbal/move', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({driver: driver, steps: steps})
  });
}

function gimbalStop(driver) {
  fetch('/api/gimbal/stop', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({driver: driver})
  });
}

function gimbalSetSpeed(us) {
  us = parseInt(us);
  document.getElementById('gimbalSpeed').value = us;
  document.getElementById('gimbalSpeedVal').textContent = us + ' us';
  fetch('/api/gimbal/speed', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({us: us})
  });
}

function gimbalSetCurrent(ma) {
  ma = parseInt(ma);
  document.getElementById('gimbalCurrent').value = ma;
  document.getElementById('gimbalCurrentVal').textContent = ma + ' mA';
  document.getElementById('gimbalCurrentInput').value = ma;
  fetch('/api/gimbal/current', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({ma: ma})
  });
}

function gimbalPoll() {
  fetch('/api/gimbal/status').then(function(r) { return r.json(); }).then(function(d) {
    if (d.error) {
      document.getElementById('gimbalStatus').textContent = 'Error: ' + d.error;
      document.getElementById('gimbalDot').className = 'status-dot';
      return;
    }
    document.getElementById('gimbalDot').className = 'status-dot ok';
    var drivers = d.drivers || [];
    var statusParts = [];
    statusParts.push('Drivers: ' + drivers.length);
    if (d.speed_us != null) statusParts.push('Speed: ' + d.speed_us + ' us');
    if (d.current_ma != null) statusParts.push('Current: ' + d.current_ma + ' mA');
    document.getElementById('gimbalStatus').textContent = statusParts.join(' | ');

    var container = document.getElementById('gimbalDrivers');
    container.innerHTML = '';
    drivers.forEach(function(drv, i) {
      var card = document.createElement('div');
      card.className = 'driver-card';

      var statusClass = 'badge-notfound';
      var statusText = 'NOT FOUND';
      if (drv.found) {
        statusClass = drv.running ? 'badge-running' : 'badge-idle';
        statusText = drv.running ? 'RUNNING' : 'IDLE';
      }

      var badgesHtml = '';
      if (drv.found) {
        if (drv.ot) badgesHtml += '<span class="driver-badge badge-warn">OT</span>';
        if (drv.otpw) badgesHtml += '<span class="driver-badge badge-warn">OTPW</span>';
      }

      var statsHtml = '';
      if (drv.found) {
        statsHtml = '<div class="driver-stats">' +
          'CS actual: ' + (drv.cs_actual != null ? drv.cs_actual : '--') +
          ' | RMS current: ' + (drv.rms_current != null ? drv.rms_current + ' mA' : '--') +
          '</div>';
      }

      var inputId = 'gimbalCustom_' + i;
      card.innerHTML = '<div class="driver-header">' +
        '<span class="driver-name">Driver ' + i + (drv.name ? ' (' + drv.name + ')' : '') + '</span>' +
        '<span><span class="driver-badge ' + statusClass + '">' + statusText + '</span>' + badgesHtml + '</span>' +
        '</div>' +
        statsHtml +
        '<div class="driver-btns">' +
        '<button class="btn btn-sm" onclick="gimbalMove(' + i + ', 200)">+200</button>' +
        '<button class="btn btn-sm" onclick="gimbalMove(' + i + ', 1000)">+1000</button>' +
        '<button class="btn btn-sm" onclick="gimbalMove(' + i + ', 5000)">+5000</button>' +
        '<button class="btn btn-sm btn-dark" onclick="gimbalMove(' + i + ', -200)">-200</button>' +
        '<button class="btn btn-sm btn-dark" onclick="gimbalMove(' + i + ', -1000)">-1000</button>' +
        '<button class="btn btn-sm btn-dark" onclick="gimbalMove(' + i + ', -5000)">-5000</button>' +
        '<input type="number" id="' + inputId + '" value="1000" style="width:80px;">' +
        '<button class="btn btn-sm" onclick="gimbalMove(' + i + ', parseInt(document.getElementById(&quot;' + inputId + '&quot;).value))">GO</button>' +
        '<button class="btn btn-sm btn-red" onclick="gimbalStop(' + i + ')">STOP</button>' +
        '</div>';
      container.appendChild(card);
    });
  }).catch(function() {
    document.getElementById('gimbalDot').className = 'status-dot';
    document.getElementById('gimbalStatus').textContent = 'Not connected';
  });
}

/* ========== Init ========== */
(function() {
  /* Init all servos to 1500us */
  chOrder.forEach(function(name) {
    if (name === 'MACE') return;
    fetch('/api/pwm', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({channel: name, pw: 1500})
    });
  });

  /* Start polling */
  setInterval(poll, 100);
  setInterval(attPoll, 500);
  setInterval(sysPoll, 2000);
  setInterval(gimbalPoll, 1000);

  /* Immediate calls */
  sysPoll();
  gimbalPoll();
})();
</script>
</body>
</html>
"""


@app.route('/')
def index():
    return render_template_string(HTML)


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
    return jsonify({"ok": ok})


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


if __name__ == '__main__':
    threading.Thread(target=sensor_loop, daemon=True).start()
    threading.Thread(target=ramp_loop, daemon=True).start()
    threading.Thread(target=watchdog_loop, daemon=True).start()
    app.run(host='0.0.0.0', port=8080, threaded=True)
