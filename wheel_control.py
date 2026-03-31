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
<html>
<head>
<title>SOOS-1 Control</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #0a0e17; color: #e0e6f0; min-height: 100vh; }
  .header { background: linear-gradient(135deg, #1a1f2e, #252b3b); padding: 12px 24px; border-bottom: 1px solid #2a3040; }
  .header-top { display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; }
  .header h1 { font-size: 20px; font-weight: 600; letter-spacing: -0.5px; }
  .conn-dots { display: flex; gap: 16px; align-items: center; font-size: 13px; }
  .status-dot { width: 8px; height: 8px; border-radius: 50%; display: inline-block; margin-right: 5px; }
  .status-dot.online { background: #22c55e; box-shadow: 0 0 6px #22c55e; }
  .status-dot.offline { background: #ef4444; box-shadow: 0 0 6px #ef4444; }
  .status-dot.arming { background: #f59e0b; box-shadow: 0 0 6px #f59e0b; animation: pulse 1s infinite; }
  @keyframes pulse { 0%,100% { opacity: 1; } 50% { opacity: 0.4; } }
  .header-body { display: flex; gap: 16px; align-items: flex-start; }
  .cam-wrap { flex: 0 0 400px; }
  .cam-wrap img { width: 100%; border-radius: 6px; background: #000; display: block; }
  .header-right { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 8px; }
  .stats-row { display: flex; gap: 12px; }
  .stat-card { background: #141824; border: 1px solid #1e2433; border-radius: 8px; padding: 8px 12px; flex: 1; }
  .stat-card h3 { font-size: 10px; text-transform: uppercase; letter-spacing: 0.8px; color: #6b7280; margin-bottom: 4px; }
  .stat-item { display: flex; justify-content: space-between; font-size: 12px; margin-bottom: 2px; }
  .stat-item .sl { color: #9ca3af; }
  .stat-item .sv { font-family: 'SF Mono','Fira Code',monospace; font-weight: 500; font-size: 12px; }
  .sensor-strip { background: #141824; border: 1px solid #1e2433; border-radius: 8px; padding: 8px 12px; display: flex; gap: 16px; flex-wrap: wrap; }
  .sensor-strip .sg { display: flex; gap: 8px; align-items: center; }
  .sensor-strip .sg-label { font-size: 10px; text-transform: uppercase; letter-spacing: 0.5px; color: #6b7280; margin-right: 2px; }
  .sensor-strip .sv { font-family: 'SF Mono',monospace; font-size: 12px; font-weight: 500; }
  .sv.x { color: #f87171; } .sv.y { color: #4ade80; } .sv.z { color: #60a5fa; }

  /* Tabs */
  .tab-bar { display: flex; gap: 0; background: #141824; border-bottom: 2px solid #1e2433; }
  .tab-btn { padding: 10px 24px; font-size: 13px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px; color: #6b7280; background: transparent; border: none; cursor: pointer; border-bottom: 2px solid transparent; margin-bottom: -2px; transition: all 0.15s; }
  .tab-btn:hover { color: #e0e6f0; }
  .tab-btn.active { color: #3b82f6; border-bottom-color: #3b82f6; }
  .tab-panel { display: none; }
  .tab-panel.active { display: block; }

  .container { max-width: 1200px; margin: 0 auto; padding: 16px; }
  .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-bottom: 16px; }
  .card { background: #141824; border: 1px solid #1e2433; border-radius: 10px; padding: 16px; }
  .card h2 { font-size: 12px; text-transform: uppercase; letter-spacing: 1px; color: #6b7280; margin-bottom: 12px; }
  .sensor-row { display: flex; justify-content: space-between; margin-bottom: 6px; }
  .sensor-label { color: #9ca3af; font-size: 13px; }
  .sensor-value { font-family: 'SF Mono', 'Fira Code', monospace; font-size: 14px; font-weight: 500; }
  .sensor-value.x { color: #f87171; }
  .sensor-value.y { color: #4ade80; }
  .sensor-value.z { color: #60a5fa; }
  .full-width { grid-column: 1 / -1; }
  .slider-container { display: flex; align-items: center; gap: 12px; margin-top: 6px; }
  .slider-container input[type=range] { flex: 1; -webkit-appearance: none; height: 6px; border-radius: 3px; background: #1e293b; outline: none; }
  .slider-container input[type=range]::-webkit-slider-thumb { -webkit-appearance: none; width: 20px; height: 20px; border-radius: 50%; background: #3b82f6; cursor: pointer; border: 2px solid #60a5fa; }
  .throttle-bar-bg { height: 6px; border-radius: 3px; background: #1e293b; position: relative; flex: 1; }
  .throttle-bar-target { height: 100%; border-radius: 3px; background: #334155; position: absolute; top: 0; left: 0; transition: width 0.1s; }
  .throttle-bar-current { height: 100%; border-radius: 3px; background: #3b82f6; position: absolute; top: 0; left: 0; transition: width 0.05s linear; }
  .btn-row { display: flex; gap: 8px; margin-top: 12px; flex-wrap: wrap; }
  .btn { padding: 8px 20px; border: none; border-radius: 6px; font-size: 13px; font-weight: 600; cursor: pointer; transition: all 0.15s; text-transform: uppercase; letter-spacing: 0.5px; }
  .btn-sm { padding: 5px 12px; font-size: 11px; }
  .btn-xs { padding: 3px 8px; font-size: 10px; }
  .btn-arm { background: #22c55e; color: #000; }
  .btn-arm:hover { background: #16a34a; }
  .btn-arm.armed { background: #ef4444; }
  .btn-arm.armed:hover { background: #dc2626; }
  .btn-arm.arming { background: #f59e0b; color: #000; pointer-events: none; }
  .btn-stop { background: #ef4444; color: #fff; }
  .btn-stop:hover { background: #dc2626; }
  .btn-reverse { background: #8b5cf6; color: #fff; }
  .btn-reverse:hover { background: #7c3aed; }
  .btn-hold { background: #f59e0b; color: #000; font-size: 16px; padding: 16px 32px; user-select: none; -webkit-user-select: none; touch-action: manipulation; width: 100%; }
  .btn-hold:hover { background: #d97706; }
  .btn-hold:active, .btn-hold.active { background: #22c55e; color: #000; box-shadow: 0 0 20px rgba(34,197,94,0.4); }
  .btn-hold.disabled { background: #334155; color: #6b7280; pointer-events: none; }
  .angle-display { position: relative; width: 140px; height: 140px; margin: 0 auto; }
  .angle-ring { width: 140px; height: 140px; border-radius: 50%; border: 3px solid #1e2433; position: relative; }
  .angle-needle { position: absolute; top: 50%; left: 50%; width: 3px; height: 50px; background: #f59e0b; transform-origin: bottom center; border-radius: 2px; margin-left: -1.5px; margin-top: -50px; transition: transform 0.033s linear; }
  .angle-center { position: absolute; top: 50%; left: 50%; width: 8px; height: 8px; background: #f59e0b; border-radius: 50%; margin: -4px 0 0 -4px; }
  .angle-text { text-align: center; margin-top: 8px; font-family: 'SF Mono', monospace; font-size: 20px; color: #f59e0b; }
  .motor-error { color: #ef4444; font-size: 11px; margin-top: 6px; font-family: monospace; }
  .ch-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(190px, 1fr)); gap: 10px; }
  .ch-item { background: #1e293b; border-radius: 8px; padding: 10px; }
  .ch-item .ch-name { font-weight: 600; font-size: 13px; margin-bottom: 6px; color: #e0e6f0; }
  .ch-item .ch-pin { font-size: 10px; color: #6b7280; }
  .ch-slider { width: 100%; margin: 6px 0 4px; }
  .ch-val { font-family: 'SF Mono', monospace; font-size: 12px; color: #94a3b8; }
  .ch-slider::-webkit-slider-thumb { -webkit-appearance: none; width: 16px; height: 16px; border-radius: 50%; background: #3b82f6; cursor: pointer; border: 2px solid #60a5fa; }
  .ch-slider::-webkit-slider-runnable-track { height: 5px; border-radius: 3px; background: #0f172a; }

  /* Gimbal-specific */
  .gimbal-drv-card { background: #1e293b; border-radius: 8px; padding: 12px; margin-bottom: 10px; border: 1px solid #2a3040; }
  .gimbal-drv-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; }
  .gimbal-drv-name { font-weight: 600; font-size: 14px; }
  .gimbal-drv-status { font-size: 12px; }
  .gimbal-drv-info { font-size: 11px; color: #6b7280; margin-bottom: 6px; }
  .gimbal-drv-controls { display: flex; gap: 4px; flex-wrap: wrap; align-items: center; }
  .gimbal-details { margin-top: 8px; padding-top: 8px; border-top: 1px solid #334155; font-size: 11px; color: #6b7280; display: none; }
  .gimbal-details.open { display: block; }
  .gimbal-detail-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 2px 12px; }
  .gimbal-detail-grid span:nth-child(odd) { color: #9ca3af; }
  .gimbal-toggle-details { font-size: 10px; color: #3b82f6; cursor: pointer; background: none; border: none; padding: 2px 0; text-transform: uppercase; letter-spacing: 0.5px; }
  .gimbal-toggle-details:hover { color: #60a5fa; }
  .speed-presets { display: flex; gap: 4px; }
  .current-input-group { display: flex; gap: 4px; align-items: center; }
  .num-input { width: 70px; background: #1e293b; color: #e0e6f0; border: 1px solid #334155; border-radius: 4px; padding: 4px 6px; font-family: monospace; font-size: 12px; }
  .warn-badge { display: inline-block; padding: 1px 5px; border-radius: 3px; font-size: 9px; font-weight: 700; margin-left: 4px; }
  .warn-ot { background: #ef4444; color: #fff; }
  .warn-otpw { background: #f59e0b; color: #000; }

  @media (max-width: 900px) {
    .grid { grid-template-columns: 1fr; }
    .header-body { flex-direction: column; }
    .cam-wrap { flex: 0 0 auto; max-width: 100%; }
    .stats-row { flex-direction: column; }
  }
</style>
</head>
<body>
<!-- HEADER: always visible -->
<div class="header">
  <div class="header-top">
    <h1>SOOS-1 Control</h1>
    <div class="conn-dots">
      <span><span class="status-dot" id="statusDot"></span><span id="statusText">Connecting...</span></span>
      <span><span class="status-dot" id="gimbalDot" class="offline"></span><span id="gimbalDotText">Gimbal...</span></span>
    </div>
  </div>
  <div class="header-body">
    <div class="cam-wrap">
      <img id="camFeed" src="/api/camera" alt="Camera feed">
    </div>
    <div class="header-right">
      <div class="stats-row">
        <div class="stat-card">
          <h3>Groundstation</h3>
          <div class="stat-item"><span class="sl">CPU</span><span class="sv" id="gsCpu">--%</span></div>
          <div class="stat-item"><span class="sl">Temp</span><span class="sv" id="gsTemp">--&deg;C</span></div>
          <div class="stat-item"><span class="sl">Load</span><span class="sv" id="gsLoad">--</span></div>
        </div>
        <div class="stat-card">
          <h3>GEO-DUDe</h3>
          <div class="stat-item"><span class="sl">CPU</span><span class="sv" id="gdCpu">--%</span></div>
          <div class="stat-item"><span class="sl">Temp</span><span class="sv" id="gdTemp">--&deg;C</span></div>
          <div class="stat-item"><span class="sl">Load</span><span class="sv" id="gdLoad">--</span></div>
        </div>
      </div>
      <div class="sensor-strip">
        <div class="sg"><span class="sg-label">Gyro</span><span class="sv x" id="gx">--</span><span class="sv y" id="gy">--</span><span class="sv z" id="gz">--</span><span style="font-size:10px;color:#6b7280">&deg;/s</span></div>
        <div class="sg"><span class="sg-label">Accel</span><span class="sv x" id="ax">--</span><span class="sv y" id="ay">--</span><span class="sv z" id="az">--</span><span style="font-size:10px;color:#6b7280">g</span></div>
        <div class="sg">
          <span class="sg-label">Enc</span>
          <span class="sv" id="angleText" style="color:#f59e0b">--</span>
          <span class="sv" id="rpmText" style="color:#3b82f6">0 RPM</span>
        </div>
      </div>
      <!-- Tiny encoder dial -->
      <div style="display:flex;justify-content:center;margin-top:4px">
        <div class="angle-display" style="width:80px;height:80px">
          <div class="angle-ring" style="width:80px;height:80px;border-width:2px">
            <div class="angle-needle" id="needle" style="height:30px;margin-top:-30px;width:2px;margin-left:-1px"></div>
            <div class="angle-center" style="width:6px;height:6px;margin:-3px 0 0 -3px"></div>
          </div>
        </div>
      </div>
    </div>
  </div>
</div>

<!-- TABS -->
<div class="tab-bar">
  <button class="tab-btn active" onclick="switchTab('geodude')">GEO-DUDe</button>
  <button class="tab-btn" onclick="switchTab('gimbal')">Gimbal</button>
  <button class="tab-btn" onclick="switchTab('servos')">Servos</button>
</div>

<div class="container">

  <!-- ========== GEO-DUDe TAB ========== -->
  <div class="tab-panel active" id="tab-geodude">
    <div class="grid">
      <div class="card full-width">
        <h2>MACE -- Reaction Wheel</h2>
        <div class="slider-container" style="margin-bottom:12px">
          <span class="sensor-label">Power:</span>
          <input type="range" id="holdPower" min="10" max="100" value="10" oninput="document.getElementById('holdPowerVal').textContent=this.value+'%'">
          <span class="sensor-value" id="holdPowerVal" style="min-width:50px;text-align:right">10%</span>
        </div>
        <div class="slider-container" style="margin-bottom:12px">
          <span class="sensor-label">Ramp:</span>
          <input type="range" id="rampRate" min="0.1" max="100" step="0.1" value="0.1" oninput="updateRampLabel(this.value); sendRampRate(this.value)">
          <span class="sensor-value" id="rampVal" style="min-width:100px;text-align:right">0.1%/s</span>
        </div>
        <div style="margin-bottom:12px">
          <div class="sensor-label" style="margin-bottom:4px;font-size:12px">Ramp progress:</div>
          <div class="throttle-bar-bg">
            <div class="throttle-bar-target" id="targetBar" style="width:0%"></div>
            <div class="throttle-bar-current" id="currentBar" style="width:0%"></div>
          </div>
        </div>
        <button class="btn btn-hold disabled" id="holdBtn"
          onmousedown="holdStart()" onmouseup="holdStop()" onmouseleave="holdStop()"
          ontouchstart="holdStart(event)" ontouchend="holdStop()" ontouchcancel="holdStop()">
          ARM FIRST
        </button>
        <div class="btn-row">
          <button class="btn btn-arm" id="armBtn" onclick="toggleArm()">ARM</button>
          <button class="btn" style="background:#f59e0b;color:#000" onclick="brake()">BRAKE</button>
          <button class="btn btn-reverse" onclick="toggleReverse()">REVERSE</button>
          <button class="btn" style="background:#334155;color:#94a3b8" onclick="startCalibrate()">CALIBRATE ESC</button>
        </div>
        <div style="margin-top:6px;font-size:10px;color:#6b7280">Brake = coast (ESC brake mode not enabled). Disarm cuts signal entirely.</div>
        <div id="calPanel" style="display:none;margin-top:12px;padding:12px;background:#1e293b;border-radius:8px;border:1px solid #334155">
          <div id="calStep" style="font-size:13px;line-height:1.5"></div>
          <div class="btn-row" id="calBtns"></div>
        </div>
      </div>

      <div class="card full-width" id="attitudeCard">
        <h2>Attitude Control</h2>
        <div id="attitudeBanner" style="display:none;background:#22c55e;color:#000;padding:6px 14px;border-radius:6px;margin-bottom:10px;font-weight:600;text-align:center;font-size:13px">ATTITUDE CONTROL ACTIVE -- Manual MACE disabled</div>
        <div class="grid" style="gap:12px;margin-bottom:12px">
          <div style="text-align:center">
            <svg width="160" height="160" viewBox="-90 -90 180 180" id="attDial">
              <circle cx="0" cy="0" r="80" fill="none" stroke="#1e2433" stroke-width="3"/>
              <line x1="0" y1="0" x2="0" y2="-70" stroke="#f59e0b" stroke-width="2" id="attSetpointNeedle" transform="rotate(0)"/>
              <line x1="0" y1="0" x2="0" y2="-70" stroke="#3b82f6" stroke-width="3" id="attAngleNeedle" transform="rotate(0)"/>
              <circle cx="0" cy="0" r="5" fill="#3b82f6"/>
              <text x="0" y="55" text-anchor="middle" fill="#6b7280" font-size="10" id="attRevs">0 rev</text>
            </svg>
            <div style="font-family:monospace;font-size:18px;color:#3b82f6" id="attAngleText">0.0&deg;</div>
            <div style="font-family:monospace;font-size:13px;color:#f59e0b" id="attSetpointText">SP: 0.0&deg;</div>
          </div>
          <div>
            <div class="sensor-row"><span class="sensor-label">Error</span><span class="sensor-value" id="attError">0.0&deg;</span></div>
            <div class="sensor-row"><span class="sensor-label">Output</span><span class="sensor-value" id="attOutput">0%</span></div>
            <div class="sensor-row"><span class="sensor-label">Motor</span><span class="sensor-value" id="attMotor">0%</span></div>
            <div class="sensor-row"><span class="sensor-label">PWM</span><span class="sensor-value" id="attPwm">1000us</span></div>
            <div class="sensor-row"><span class="sensor-label">Wheel RPM</span><span class="sensor-value" id="attRpm">0</span></div>
            <div class="sensor-row"><span class="sensor-label">Gz</span><span class="sensor-value" id="attGz">0.0 &deg;/s</span></div>
            <div class="sensor-row"><span class="sensor-label">Bias</span><span class="sensor-value" id="attBias">0.0</span></div>
            <div class="sensor-row"><span class="sensor-label">Saturation</span><span class="sensor-value" id="attSat" style="color:#22c55e">ok</span></div>
          </div>
        </div>
        <div style="margin-bottom:8px">
          <span class="sensor-label">Setpoint:</span>
          <input type="number" id="attSetpointInput" value="0" step="1" style="width:80px;background:#1e293b;color:#e0e6f0;border:1px solid #334155;border-radius:4px;padding:4px 8px;font-family:monospace;font-size:13px">
          <button class="btn btn-sm" style="background:#3b82f6;color:#fff;padding:4px 12px" onclick="attSetpoint()">SET</button>
        </div>
        <div class="btn-row" style="margin-bottom:8px">
          <button class="btn btn-sm" style="background:#334155;color:#94a3b8" onclick="attNudge(-90)">-90&deg;</button>
          <button class="btn btn-sm" style="background:#334155;color:#94a3b8" onclick="attNudge(-10)">-10&deg;</button>
          <button class="btn btn-sm" style="background:#334155;color:#94a3b8" onclick="attNudge(10)">+10&deg;</button>
          <button class="btn btn-sm" style="background:#334155;color:#94a3b8" onclick="attNudge(90)">+90&deg;</button>
        </div>
        <div class="slider-container" style="margin-bottom:6px">
          <span class="sensor-label">Kp:</span>
          <input type="range" min="0" max="10" step="0.1" value="1.5" id="attKp" oninput="attUpdateGain()">
          <span class="sensor-value" id="attKpVal" style="min-width:40px">1.5</span>
        </div>
        <div class="slider-container" style="margin-bottom:6px">
          <span class="sensor-label">Ki:</span>
          <input type="range" min="0" max="1" step="0.01" value="0.05" id="attKi" oninput="attUpdateGain()">
          <span class="sensor-value" id="attKiVal" style="min-width:40px">0.05</span>
        </div>
        <div class="slider-container" style="margin-bottom:6px">
          <span class="sensor-label">Kd:</span>
          <input type="range" min="0" max="5" step="0.1" value="0.8" id="attKd" oninput="attUpdateGain()">
          <span class="sensor-value" id="attKdVal" style="min-width:40px">0.8</span>
        </div>
        <div class="slider-container" style="margin-bottom:12px">
          <span class="sensor-label">Max %:</span>
          <input type="range" min="10" max="100" step="1" value="60" id="attMaxThrottle" oninput="attUpdateGain()">
          <span class="sensor-value" id="attMaxVal" style="min-width:40px">60</span>
        </div>
        <div class="btn-row">
          <button class="btn btn-arm" id="attEnableBtn" onclick="attToggleEnable()">ENABLE</button>
          <button class="btn btn-stop" onclick="attStop()">STOP</button>
          <button class="btn" style="background:#334155;color:#94a3b8" onclick="attZero()">ZERO</button>
          <button class="btn" style="background:#334155;color:#94a3b8" onclick="attRecalibrate()">RECALIBRATE</button>
        </div>
      </div>

      <div class="card">
        <h2>System</h2>
        <div class="sensor-row"><span class="sensor-label">Armed</span><span class="sensor-value" id="armedStatus" style="color:#ef4444">NO</span></div>
        <div class="sensor-row"><span class="sensor-label">Target</span><span class="sensor-value" id="targetStatus">0%</span></div>
        <div class="sensor-row"><span class="sensor-label">Throttle</span><span class="sensor-value" id="throttleStatus">0%</span></div>
        <div class="sensor-row"><span class="sensor-label">PWM</span><span class="sensor-value" id="pwmStatus">1000us</span></div>
        <div class="sensor-row"><span class="sensor-label">Direction</span><span class="sensor-value" id="dirStatus">FWD</span></div>
        <div class="sensor-row"><span class="sensor-label">Wheel RPM</span><span class="sensor-value" id="maceRpm">0</span></div>
        <div class="sensor-row"><span class="sensor-label">Saturated</span><span class="sensor-value" id="maceSat" style="color:#22c55e">NO</span></div>
        <div class="motor-error" id="motorError"></div>
      </div>

      <div class="card">
        <h2>Encoder</h2>
        <div class="angle-display">
          <div class="angle-ring">
            <div class="angle-needle" id="needleLarge"></div>
            <div class="angle-center"></div>
          </div>
        </div>
        <div class="angle-text" id="angleTextLarge">--</div>
        <div class="angle-text" id="rpmTextLarge" style="font-size:16px;color:#3b82f6;margin-top:4px">0 RPM</div>
      </div>
    </div>
  </div>

  <!-- ========== GIMBAL TAB ========== -->
  <div class="tab-panel" id="tab-gimbal">
    <div class="card" style="margin-bottom:16px">
      <h2>Gimbal -- Stepper Motors (TMC2209)</h2>
      <div id="gimbalStatus" style="margin-bottom:10px;font-size:13px;color:#6b7280">Connecting...</div>
      <div class="btn-row" style="margin-bottom:12px;margin-top:0">
        <button class="btn" style="background:#1e3a5f;color:#60a5fa" onclick="gimbalSetup()">SETUP DRIVERS</button>
        <button class="btn" style="background:#1e3a5f;color:#60a5fa" onclick="gimbalScan()">SCAN</button>
        <button class="btn btn-stop" onclick="gimbalStopAll()">STOP ALL</button>
      </div>

      <!-- Speed -->
      <div style="margin-bottom:12px">
        <div class="slider-container" style="margin-top:0">
          <span class="sensor-label">Speed:</span>
          <input type="range" id="gimbalSpeed" min="100" max="8000" step="100" value="2000" oninput="gimbalSetSpeed(this.value)">
          <span class="sensor-value" id="gimbalSpeedVal" style="min-width:70px;text-align:right">2000us</span>
        </div>
        <div class="speed-presets" style="margin-top:6px;margin-left:52px">
          <button class="btn btn-xs" style="background:#334155;color:#94a3b8" onclick="gimbalSetSpeedPreset(5000)">Slow 5000</button>
          <button class="btn btn-xs" style="background:#334155;color:#94a3b8" onclick="gimbalSetSpeedPreset(2000)">Med 2000</button>
          <button class="btn btn-xs" style="background:#334155;color:#94a3b8" onclick="gimbalSetSpeedPreset(500)">Fast 500</button>
        </div>
      </div>

      <!-- Current -->
      <div style="margin-bottom:16px">
        <div class="slider-container" style="margin-top:0">
          <span class="sensor-label">Current:</span>
          <input type="range" id="gimbalCurrent" min="50" max="2000" step="50" value="400" oninput="gimbalSetCurrent(this.value)">
          <span class="sensor-value" id="gimbalCurrentVal" style="min-width:70px;text-align:right">400mA</span>
        </div>
        <div class="current-input-group" style="margin-top:6px;margin-left:52px">
          <input type="number" id="gimbalCurrentInput" value="400" min="50" max="2000" step="50" class="num-input">
          <span style="font-size:11px;color:#6b7280">mA</span>
          <button class="btn btn-xs" style="background:#1e3a5f;color:#60a5fa" onclick="gimbalSetCurrentFromInput()">Set</button>
        </div>
      </div>
    </div>

    <!-- Driver cards -->
    <div id="gimbalDrivers"></div>
  </div>

  <!-- ========== SERVOS TAB ========== -->
  <div class="tab-panel" id="tab-servos">
    <div class="card">
      <h2>PCA9685 Channels</h2>
      <div style="margin-bottom:10px">
        <button class="btn btn-sm" style="background:#1e3a5f;color:#60a5fa" onclick="allChannelsCenter()">ALL CENTER</button>
      </div>
      <div class="ch-grid" id="chGrid"></div>
    </div>
  </div>

</div>

<script>
let reverse = false;
let holding = false;
let currentNeedleAngle = 0;
let isArmed = false;
let isArming = false;

const CHANNELS = {
  "W2B": {ch: 0, pin: 1},
  "W2A": {ch: 1, pin: 2},
  "W1B": {ch: 2, pin: 3},
  "W1A": {ch: 3, pin: 4},
  "E2":  {ch: 4, pin: 5},
  "E1":  {ch: 6, pin: 7},
  "MACE":{ch: 11, pin: 12},
  "S2":  {ch: 12, pin: 13},
  "B2":  {ch: 13, pin: 14},
  "S1":  {ch: 14, pin: 15},
  "B1":  {ch: 15, pin: 16},
};

// --- Tab switching ---
function switchTab(name) {
  document.querySelectorAll('.tab-btn').forEach(function(btn) { btn.classList.remove('active'); });
  document.querySelectorAll('.tab-panel').forEach(function(p) { p.classList.remove('active'); });
  document.getElementById('tab-' + name).classList.add('active');
  var btns = document.querySelectorAll('.tab-btn');
  var map = {'geodude': 0, 'gimbal': 1, 'servos': 2};
  if (map[name] !== undefined) btns[map[name]].classList.add('active');
}

// Build channel controls
const chOrder = ["B1","S1","B2","S2","MACE","E1","E2","W1A","W1B","W2A","W2B"];
const grid = document.getElementById('chGrid');
chOrder.forEach(name => {
  let c = CHANNELS[name];
  if (name === 'MACE') return; // controlled by main panel
  let minUs = 500;
  let maxUs = 2500;
  let div = document.createElement('div');
  div.className = 'ch-item';
  div.innerHTML = '<div class="ch-name">' + name + ' <span class="ch-pin">pin ' + c.pin + ' / ch ' + c.ch + '</span></div>' +
    '<input type="range" class="ch-slider" min="' + minUs + '" max="' + maxUs + '" step="10" value="1500" id="ch_' + name + '" oninput="chSlide(&quot;' + name + '&quot;, this.value)">' +
    '<div class="ch-val"><span id="chv_' + name + '">7.5% (1500us)</span> ' +
    '<button class="btn btn-sm" style="background:#1e3a5f;color:#60a5fa;padding:2px 8px;font-size:11px" onclick="chCenter(&quot;' + name + '&quot;)">7.5%</button></div>';
  grid.appendChild(div);
  // Prevent click-to-jump on slider track — only allow thumb drag
  let sl = document.getElementById('ch_' + name);
  sl.addEventListener('mousedown', function(e) {
    let rect = this.getBoundingClientRect();
    let pct = (this.value - this.min) / (this.max - this.min);
    let thumbX = rect.left + pct * rect.width;
    if (Math.abs(e.clientX - thumbX) > 15) e.preventDefault();
  });
  sl.addEventListener('touchstart', function(e) {
    let rect = this.getBoundingClientRect();
    let pct = (this.value - this.min) / (this.max - this.min);
    let thumbX = rect.left + pct * rect.width;
    if (Math.abs(e.touches[0].clientX - thumbX) > 25) e.preventDefault();
  }, {passive: false});
});

let chRampTimers = {};
const CH_RAMP_RATE = 20; // us per tick
const CH_RAMP_HZ = 30;

function usToDuty(us) {
  return (us / 20000 * 100).toFixed(1);
}

function chSlide(name, val) {
  val = parseInt(val);
  document.getElementById('chv_' + name).textContent = usToDuty(val) + '% (' + val + 'us)';
  fetch('/api/pwm', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({channel: name, pw: val})});
}

function chRampTo(name, target) {
  if (chRampTimers[name]) clearInterval(chRampTimers[name]);
  let slider = document.getElementById('ch_' + name);
  let label = document.getElementById('chv_' + name);
  chRampTimers[name] = setInterval(function() {
    let current = parseInt(slider.value);
    if (Math.abs(current - target) <= CH_RAMP_RATE) {
      slider.value = target;
      clearInterval(chRampTimers[name]);
      chRampTimers[name] = null;
    } else if (current < target) {
      slider.value = current + CH_RAMP_RATE;
    } else {
      slider.value = current - CH_RAMP_RATE;
    }
    let val = parseInt(slider.value);
    label.textContent = usToDuty(val) + '% (' + val + 'us)';
    fetch('/api/pwm', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({channel: name, pw: val})});
  }, 1000 / CH_RAMP_HZ);
}

function chCenter(name) {
  chRampTo(name, 1500);
}

function allChannelsCenter() {
  chOrder.forEach(name => {
    if (name === 'MACE') return;
    chRampTo(name, 1500);
  });
}

function updateRampLabel(val) {
  let pwr = parseInt(document.getElementById('holdPower').value);
  let secs = pwr > 0 ? (pwr / val).toFixed(1) : '0.0';
  document.getElementById('rampVal').textContent = val + '%/s (' + secs + 's)';
}

function sendRampRate(val) {
  fetch('/api/config', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({ramp_rate: parseFloat(val)})});
}

function holdStart(e) {
  if (e) e.preventDefault();
  if (!isArmed || isArming) return;
  if (!holding) {
    holding = true;
    document.getElementById('holdBtn').classList.add('active');
    let pwr = parseInt(document.getElementById('holdPower').value);
    fetch('/api/throttle', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({target: pwr, reverse: reverse})});
  }
}

function holdStop() {
  if (holding) {
    holding = false;
    document.getElementById('holdBtn').classList.remove('active');
    fetch('/api/throttle', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({target: 0, reverse: reverse})});
  }
}

function toggleArm() {
  if (isArming) return;
  fetch('/api/arm', {method:'POST'});
}

function emergencyStop() {
  holding = false;
  document.getElementById('holdBtn').classList.remove('active');
  fetch('/api/stop', {method:'POST'});
}

function brake() {
  holding = false;
  document.getElementById('holdBtn').classList.remove('active');
  fetch('/api/brake', {method:'POST'});
}

function toggleReverse() {
  reverse = !reverse;
  fetch('/api/throttle', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({target: 0, reverse: reverse})});
  document.getElementById('dirStatus').textContent = reverse ? 'REV' : 'FWD';
}

function startCalibrate() {
  let panel = document.getElementById('calPanel');
  panel.style.display = 'block';
  document.getElementById('calStep').innerHTML = '<strong>Step 1:</strong> Disconnect power from the ESC, then click Next.';
  document.getElementById('calBtns').innerHTML = '<button class="btn" style="background:#3b82f6;color:#fff" onclick="calStep2()">NEXT</button> <button class="btn" style="background:#334155;color:#94a3b8" onclick="calCancel()">CANCEL</button>';
}

function calStep2() {
  document.getElementById('calStep').innerHTML = '<strong>Step 2:</strong> Sending max signal (2000us)... Now plug in the ESC power. Wait for high-pitched beeps, then click Next.';
  fetch('/api/calibrate', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({step:'max'})});
  document.getElementById('calBtns').innerHTML = '<button class="btn" style="background:#3b82f6;color:#fff" onclick="calStep3()">NEXT (heard beeps)</button> <button class="btn" style="background:#334155;color:#94a3b8" onclick="calCancel()">CANCEL</button>';
}

function calStep3() {
  document.getElementById('calStep').innerHTML = '<strong>Step 3:</strong> Sending min signal (1000us)... Wait for low-pitched beeps confirming calibration.';
  fetch('/api/calibrate', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({step:'min'})});
  document.getElementById('calBtns').innerHTML = '<button class="btn" style="background:#22c55e;color:#000" onclick="calDone()">DONE</button>';
}

function calDone() {
  document.getElementById('calPanel').style.display = 'none';
}

function calCancel() {
  fetch('/api/calibrate', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({step:'cancel'})});
  document.getElementById('calPanel').style.display = 'none';
}

let lastArmState = null;
function updateArmUI(armed, arming) {
  let key = (arming ? 'arming' : armed ? 'armed' : 'off');
  if (key === lastArmState) return;
  lastArmState = key;
  isArmed = armed;
  isArming = arming;
  let armBtn = document.getElementById('armBtn');
  let holdBtn = document.getElementById('holdBtn');
  if (arming) {
    armBtn.textContent = 'ARMING...';
    armBtn.className = 'btn btn-arm arming';
    holdBtn.className = 'btn btn-hold disabled';
    holdBtn.textContent = 'ARMING...';
  } else if (armed) {
    armBtn.textContent = 'DISARM';
    armBtn.className = 'btn btn-arm armed';
    holdBtn.className = 'btn btn-hold';
    holdBtn.textContent = 'HOLD TO SPIN';
  } else {
    armBtn.textContent = 'ARM';
    armBtn.className = 'btn btn-arm';
    holdBtn.className = 'btn btn-hold disabled';
    holdBtn.textContent = 'ARM FIRST';
  }
}

function poll() {
  fetch('/api/sensors').then(r=>r.json()).then(d => {
    document.getElementById('gx').textContent = d.gyro.x.toFixed(1);
    document.getElementById('gy').textContent = d.gyro.y.toFixed(1);
    document.getElementById('gz').textContent = d.gyro.z.toFixed(1);
    document.getElementById('ax').textContent = d.accel.x.toFixed(3);
    document.getElementById('ay').textContent = d.accel.y.toFixed(3);
    document.getElementById('az').textContent = d.accel.z.toFixed(3);
    document.getElementById('angleText').textContent = d.encoder_angle.toFixed(1) + '\u00b0';
    let target = d.encoder_angle;
    let cur = ((currentNeedleAngle % 360) + 360) % 360;
    let delta = target - cur;
    if (delta > 180) delta -= 360;
    if (delta < -180) delta += 360;
    currentNeedleAngle += delta;
    document.getElementById('needle').style.transform = 'rotate(' + currentNeedleAngle + 'deg)';
    document.getElementById('rpmText').textContent = Math.round(d.rpm) + ' RPM';
    // Also update the large encoder dial on GEO-DUDe tab
    var nl = document.getElementById('needleLarge');
    if (nl) nl.style.transform = 'rotate(' + currentNeedleAngle + 'deg)';
    var atl = document.getElementById('angleTextLarge');
    if (atl) atl.textContent = d.encoder_angle.toFixed(1) + '\u00b0';
    var rtl = document.getElementById('rpmTextLarge');
    if (rtl) rtl.textContent = Math.round(d.rpm) + ' RPM';
    updateArmUI(d.armed, d.arming);
    document.getElementById('armedStatus').textContent = d.arming ? 'ARMING' : (d.armed ? 'YES' : 'NO');
    document.getElementById('armedStatus').style.color = d.arming ? '#f59e0b' : (d.armed ? '#22c55e' : '#ef4444');
    let thr = Math.round(d.throttle);
    let tgt = Math.round(d.target);
    document.getElementById('targetStatus').textContent = tgt + '%';
    document.getElementById('throttleStatus').textContent = thr + '%';
    let pw = d.reverse ? 1000 - thr * 10 : 1000 + thr * 10;
    document.getElementById('pwmStatus').textContent = pw + 'us';
    document.getElementById('dirStatus').textContent = d.reverse ? 'REV' : 'FWD';
    reverse = d.reverse;
    document.getElementById('targetBar').style.width = tgt + '%';
    document.getElementById('currentBar').style.width = thr + '%';
    let dot = document.getElementById('statusDot');
    let txt = document.getElementById('statusText');
    if (d.arming) { dot.className='status-dot arming'; txt.textContent='Arming ESC...'; }
    else if (d.connected) { dot.className='status-dot online'; txt.textContent='Geodude Online'; }
    else { dot.className='status-dot offline'; txt.textContent='Geodude Offline'; }
    document.getElementById('maceRpm').textContent = Math.round(d.rpm);
    let isSat = d.rpm >= 600;
    let satEl = document.getElementById('maceSat');
    satEl.textContent = isSat ? 'YES' : 'NO';
    satEl.style.color = isSat ? '#ef4444' : '#22c55e';
    let errEl = document.getElementById('motorError');
    if (d.motor_error) { errEl.textContent = 'Motor: ' + d.motor_error; }
    else { errEl.textContent = ''; }
  }).catch(() => {
    document.getElementById('statusDot').className='status-dot offline';
    document.getElementById('statusText').textContent='Server Unreachable';
  });
}

setInterval(poll, 100);

fetch('/api/sensors').then(r=>r.json()).then(d => {
  if (d.ramp_rate) {
    document.getElementById('rampRate').value = d.ramp_rate;
    updateRampLabel(d.ramp_rate);
  }
});
document.getElementById('holdPower').addEventListener('input', function() {
  updateRampLabel(document.getElementById('rampRate').value);
});

// Initialize all servo channels to center on page load
chOrder.forEach(name => {
  if (name === 'MACE') return;
  fetch('/api/pwm', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({channel: name, pw: 1500})});
});

// --- Attitude Control ---
let attEnabled = false;
let attGainTimeout = null;

function attToggleEnable() {
  if (attEnabled) {
    fetch('/api/attitude/disable', {method:'POST'});
  } else {
    fetch('/api/attitude/enable', {method:'POST'});
  }
}

function attStop() {
  fetch('/api/attitude/stop', {method:'POST'});
}

function attZero() {
  fetch('/api/attitude/zero', {method:'POST'});
}

function attRecalibrate() {
  fetch('/api/attitude/calibrate', {method:'POST'});
}

function attSetpoint() {
  let val = parseFloat(document.getElementById('attSetpointInput').value) || 0;
  fetch('/api/attitude/setpoint', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({angle: val})});
}

function attNudge(delta) {
  fetch('/api/attitude/nudge', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({delta: delta})});
}

function attUpdateGain() {
  document.getElementById('attKpVal').textContent = document.getElementById('attKp').value;
  document.getElementById('attKiVal').textContent = document.getElementById('attKi').value;
  document.getElementById('attKdVal').textContent = document.getElementById('attKd').value;
  document.getElementById('attMaxVal').textContent = document.getElementById('attMaxThrottle').value;
  if (attGainTimeout) clearTimeout(attGainTimeout);
  attGainTimeout = setTimeout(function() {
    fetch('/api/attitude/gains', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({
      Kp: parseFloat(document.getElementById('attKp').value),
      Ki: parseFloat(document.getElementById('attKi').value),
      Kd: parseFloat(document.getElementById('attKd').value),
      max_throttle: parseFloat(document.getElementById('attMaxThrottle').value)
    })});
  }, 200);
}

function attPoll() {
  fetch('/api/attitude/status').then(r => {
    if (!r.ok) return;
    return r.json();
  }).then(d => {
    if (!d) return;
    attEnabled = d.enabled;
    let btn = document.getElementById('attEnableBtn');
    if (d.calibrating) {
      btn.textContent = 'CALIBRATING...';
      btn.className = 'btn btn-arm arming';
    } else if (d.arming) {
      btn.textContent = 'ARMING...';
      btn.className = 'btn btn-arm arming';
    } else if (d.enabled) {
      btn.textContent = 'DISABLE';
      btn.className = 'btn btn-arm armed';
    } else {
      btn.textContent = 'ENABLE';
      btn.className = 'btn btn-arm';
    }
    // Banner and manual MACE disable
    let banner = document.getElementById('attitudeBanner');
    let maceCard = document.getElementById('holdBtn');
    if (d.enabled) {
      banner.style.display = 'block';
      if (maceCard) maceCard.classList.add('disabled');
    } else {
      banner.style.display = 'none';
      if (maceCard) maceCard.classList.remove('disabled');
    }
    // Angle display
    document.getElementById('attAngleText').innerHTML = d.body_angle.toFixed(1) + '&deg;';
    document.getElementById('attSetpointText').innerHTML = 'SP: ' + d.setpoint.toFixed(1) + '&deg;';
    let revs = Math.floor(Math.abs(d.body_angle) / 360);
    document.getElementById('attRevs').textContent = revs + ' rev';
    // Needles
    let angleDeg = ((d.body_angle % 360) + 360) % 360;
    let spDeg = ((d.setpoint % 360) + 360) % 360;
    document.getElementById('attAngleNeedle').setAttribute('transform', 'rotate(' + angleDeg + ')');
    document.getElementById('attSetpointNeedle').setAttribute('transform', 'rotate(' + spDeg + ')');
    // Status
    document.getElementById('attError').innerHTML = d.error.toFixed(1) + '&deg;';
    document.getElementById('attOutput').textContent = d.output.toFixed(1) + '%';
    document.getElementById('attMotor').textContent = d.motor_pct.toFixed(1) + '%';
    document.getElementById('attPwm').textContent = d.pwm + 'us';
    document.getElementById('attRpm').textContent = Math.round(d.wheel_rpm);
    document.getElementById('attGz').innerHTML = d.gz.toFixed(1) + ' &deg;/s';
    document.getElementById('attBias').textContent = d.gz_bias.toFixed(3);
    let satEl = document.getElementById('attSat');
    satEl.textContent = d.saturation;
    satEl.style.color = d.saturation === 'ok' ? '#22c55e' : d.saturation === 'warning' ? '#f59e0b' : '#ef4444';
    // Sync gain sliders if not being dragged
    if (!attGainTimeout) {
      document.getElementById('attKp').value = d.Kp;
      document.getElementById('attKpVal').textContent = d.Kp;
      document.getElementById('attKi').value = d.Ki;
      document.getElementById('attKiVal').textContent = d.Ki;
      document.getElementById('attKd').value = d.Kd;
      document.getElementById('attKdVal').textContent = d.Kd;
      document.getElementById('attMaxThrottle').value = d.max_throttle;
      document.getElementById('attMaxVal').textContent = d.max_throttle;
    }
    // Watchdog warning
    if (d.watchdog_triggered) {
      document.getElementById('attitudeBanner').textContent = 'WATCHDOG TRIGGERED — Controller disabled';
      document.getElementById('attitudeBanner').style.background = '#ef4444';
      document.getElementById('attitudeBanner').style.display = 'block';
    }
  }).catch(() => {});
}

setInterval(attPoll, 500);

function sysPoll() {
  fetch('/api/system').then(r=>r.json()).then(d => {
    document.getElementById('gsCpu').textContent = d.groundstation.cpu + '%';
    document.getElementById('gsTemp').innerHTML = d.groundstation.temp + '&deg;C';
    document.getElementById('gsLoad').textContent = d.groundstation.load;
    document.getElementById('gdCpu').textContent = d.geodude.cpu + '%';
    document.getElementById('gdTemp').innerHTML = d.geodude.temp + '&deg;C';
    document.getElementById('gdLoad').textContent = d.geodude.load;
  }).catch(()=>{});
}
setInterval(sysPoll, 2000);
sysPoll();

// --- Gimbal ---
function gimbalSetup() {
  fetch('/api/gimbal/setup', {method:'POST'}).then(r=>r.json()).then(d => {
    if (d.ok) gimbalPoll();
  });
}
function gimbalScan() {
  fetch('/api/gimbal/scan', {method:'POST'}).then(r=>r.json()).then(d => {
    gimbalPoll();
  });
}
function gimbalStopAll() {
  fetch('/api/gimbal/stop_all', {method:'POST'});
}
function gimbalMove(driver, steps) {
  fetch('/api/gimbal/move', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({driver: driver, steps: steps})});
}
function gimbalStop(driver) {
  fetch('/api/gimbal/stop', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({driver: driver})});
}
function gimbalSetSpeed(us) {
  document.getElementById('gimbalSpeedVal').textContent = us + 'us';
  fetch('/api/gimbal/speed', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({us: parseInt(us)})});
}
function gimbalSetCurrent(ma) {
  document.getElementById('gimbalCurrentVal').textContent = ma + 'mA';
  fetch('/api/gimbal/current', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({ma: parseInt(ma)})});
}

function gimbalSetSpeedPreset(us) {
  document.getElementById('gimbalSpeed').value = us;
  gimbalSetSpeed(us);
}

function gimbalSetCurrentFromInput() {
  var ma = parseInt(document.getElementById('gimbalCurrentInput').value) || 400;
  ma = Math.max(50, Math.min(2000, ma));
  document.getElementById('gimbalCurrent').value = ma;
  gimbalSetCurrent(ma);
}

function toggleDriverDetails(idx) {
  var el = document.getElementById('gimbal-details-' + idx);
  if (el) el.classList.toggle('open');
}

function gimbalPoll() {
  fetch('/api/gimbal/status').then(r=>r.json()).then(d => {
    let s = document.getElementById('gimbalStatus');
    let gDot = document.getElementById('gimbalDot');
    let gTxt = document.getElementById('gimbalDotText');
    if (d.error) {
      s.textContent = 'ESP32 Offline';
      s.style.color = '#ef4444';
      if (gDot) { gDot.className = 'status-dot offline'; }
      if (gTxt) { gTxt.textContent = 'Gimbal Offline'; }
      return;
    }
    s.innerHTML = '<strong>' + d.drivers_found + '</strong> driver(s) found | step delay <strong>' + d.step_delay + '</strong>us | <strong>' + d.current_ma + '</strong>mA' + (d.setup_done ? ' | <span style="color:#22c55e">Setup OK</span>' : ' | <span style="color:#f59e0b">click SETUP</span>');
    s.style.color = '#e0e6f0';
    if (gDot) { gDot.className = d.drivers_found > 0 ? 'status-dot online' : 'status-dot offline'; }
    if (gTxt) { gTxt.textContent = d.drivers_found > 0 ? 'Gimbal Online' : 'Gimbal No Drivers'; }
    document.getElementById('gimbalSpeed').value = d.step_delay;
    document.getElementById('gimbalSpeedVal').textContent = d.step_delay + 'us';
    document.getElementById('gimbalCurrent').value = d.current_ma;
    document.getElementById('gimbalCurrentVal').textContent = d.current_ma + 'mA';
    document.getElementById('gimbalCurrentInput').value = d.current_ma;
    let html = '';
    d.drivers.forEach(function(drv) {
      let statusHtml, statusColor;
      if (!drv.found) {
        statusHtml = '<span style="color:#ef4444">NOT FOUND</span>';
      } else if (drv.running) {
        statusHtml = '<span style="color:#22c55e">RUNNING ' + drv.dir + '</span>';
        if (drv.steps_remaining > 0) statusHtml += ' <span style="color:#6b7280;font-size:10px">(' + drv.steps_remaining + ' left)</span>';
      } else {
        statusHtml = '<span style="color:#6b7280">IDLE</span>';
      }
      // Warnings
      let warns = '';
      if (drv.ot) warns += '<span class="warn-badge warn-ot">OT</span>';
      if (drv.otpw) warns += '<span class="warn-badge warn-otpw">OTPW</span>';

      html += '<div class="gimbal-drv-card">';
      html += '<div class="gimbal-drv-header">';
      html += '<span class="gimbal-drv-name">' + drv.name + ' <span style="color:#6b7280;font-size:11px">(Driver ' + drv.index + ')</span></span>';
      html += '<span class="gimbal-drv-status">' + statusHtml + warns + '</span>';
      html += '</div>';
      if (drv.found) {
        html += '<div class="gimbal-drv-info">cs_actual=' + drv.cs_actual + ' | rms_current=' + drv.rms_current + 'mA' + (drv.standstill ? ' | standstill' : '') + '</div>';
      }
      html += '<div class="gimbal-drv-controls">';
      html += '<button class="btn btn-xs" style="background:#334155;color:#94a3b8" onclick="gimbalMove(' + drv.index + ',-5000)">-5000</button>';
      html += '<button class="btn btn-xs" style="background:#334155;color:#94a3b8" onclick="gimbalMove(' + drv.index + ',-1000)">-1000</button>';
      html += '<button class="btn btn-xs" style="background:#334155;color:#94a3b8" onclick="gimbalMove(' + drv.index + ',-200)">-200</button>';
      html += '<button class="btn btn-xs" style="background:#334155;color:#94a3b8" onclick="gimbalMove(' + drv.index + ',200)">+200</button>';
      html += '<button class="btn btn-xs" style="background:#334155;color:#94a3b8" onclick="gimbalMove(' + drv.index + ',1000)">+1000</button>';
      html += '<button class="btn btn-xs" style="background:#334155;color:#94a3b8" onclick="gimbalMove(' + drv.index + ',5000)">+5000</button>';
      html += '<input type="number" value="500" id="gsteps_' + drv.index + '" class="num-input" style="width:60px;margin-left:4px">';
      html += '<button class="btn btn-xs" style="background:#1e3a5f;color:#60a5fa" onclick="gimbalMove(' + drv.index + ',parseInt(document.getElementById(\'gsteps_' + drv.index + '\').value))">GO</button>';
      html += '<button class="btn btn-xs" style="background:#7f1d1d;color:#fca5a5" onclick="gimbalStop(' + drv.index + ')">STOP</button>';
      html += '</div>';
      // Collapsible details
      if (drv.found) {
        html += '<button class="gimbal-toggle-details" onclick="toggleDriverDetails(' + drv.index + ')">Driver Details</button>';
        html += '<div class="gimbal-details" id="gimbal-details-' + drv.index + '">';
        html += '<div class="gimbal-detail-grid">';
        html += '<span>Microsteps</span><span>' + drv.microsteps + '</span>';
        html += '<span>IRUN</span><span>' + drv.irun + '</span>';
        html += '<span>IHOLD</span><span>' + drv.ihold + '</span>';
        html += '<span>cs_actual</span><span>' + drv.cs_actual + '</span>';
        html += '<span>rms_current</span><span>' + drv.rms_current + 'mA</span>';
        html += '<span>Standstill</span><span>' + (drv.standstill ? 'yes' : 'no') + '</span>';
        html += '<span>OT (overtemp)</span><span style="color:' + (drv.ot ? '#ef4444' : '#22c55e') + '">' + (drv.ot ? 'YES' : 'no') + '</span>';
        html += '<span>OTPW (warning)</span><span style="color:' + (drv.otpw ? '#f59e0b' : '#22c55e') + '">' + (drv.otpw ? 'YES' : 'no') + '</span>';
        html += '</div></div>';
      }
      html += '</div>';
    });
    document.getElementById('gimbalDrivers').innerHTML = html;
  }).catch(() => {
    document.getElementById('gimbalStatus').textContent = 'ESP32 Offline';
    document.getElementById('gimbalStatus').style.color = '#ef4444';
    var gDot = document.getElementById('gimbalDot');
    var gTxt = document.getElementById('gimbalDotText');
    if (gDot) gDot.className = 'status-dot offline';
    if (gTxt) gTxt.textContent = 'Gimbal Offline';
  });
}
setInterval(gimbalPoll, 1000);
gimbalPoll();
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
