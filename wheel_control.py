from flask import Flask, render_template_string, jsonify, request
import threading
import time
import json
import urllib.request

app = Flask(__name__)

GEODUDE_URL = "http://192.168.4.166:5000"
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


def ramp_loop():
    """Server-side ramp: smoothly moves throttle toward target at ramp_rate %/s."""
    last_pw = None
    while True:
        time.sleep(1.0 / RAMP_HZ)
        with lock:
            if not state["armed"] or state["arming"]:
                last_pw = None
                continue
            target = state["target"]
            current = state["throttle"]
            if abs(target - current) > 0.1:
                step = state["ramp_rate"] / RAMP_HZ
                diff = target - current
                if abs(diff) <= step:
                    state["throttle"] = target
                elif diff > 0:
                    state["throttle"] = current + step
                else:
                    state["throttle"] = current - step
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
                state["connected"] = True
        except Exception:
            with lock:
                state["connected"] = False
        time.sleep(0.1)


HTML = """
<!DOCTYPE html>
<html>
<head>
<title>GEO-DUDe Control</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #0a0e17; color: #e0e6f0; min-height: 100vh; }
  .header { background: linear-gradient(135deg, #1a1f2e, #252b3b); padding: 20px 30px; border-bottom: 1px solid #2a3040; display: flex; justify-content: space-between; align-items: center; }
  .header h1 { font-size: 22px; font-weight: 600; letter-spacing: -0.5px; }
  .status-dot { width: 10px; height: 10px; border-radius: 50%; display: inline-block; margin-right: 8px; }
  .status-dot.online { background: #22c55e; box-shadow: 0 0 8px #22c55e; }
  .status-dot.offline { background: #ef4444; box-shadow: 0 0 8px #ef4444; }
  .status-dot.arming { background: #f59e0b; box-shadow: 0 0 8px #f59e0b; animation: pulse 1s infinite; }
  @keyframes pulse { 0%,100% { opacity: 1; } 50% { opacity: 0.4; } }
  .container { max-width: 960px; margin: 0 auto; padding: 24px; }
  .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; margin-bottom: 20px; }
  .card { background: #141824; border: 1px solid #1e2433; border-radius: 12px; padding: 20px; }
  .card h2 { font-size: 13px; text-transform: uppercase; letter-spacing: 1px; color: #6b7280; margin-bottom: 16px; }
  .sensor-row { display: flex; justify-content: space-between; margin-bottom: 10px; }
  .sensor-label { color: #9ca3af; font-size: 14px; }
  .sensor-value { font-family: 'SF Mono', 'Fira Code', monospace; font-size: 16px; font-weight: 500; }
  .sensor-value.x { color: #f87171; }
  .sensor-value.y { color: #4ade80; }
  .sensor-value.z { color: #60a5fa; }
  .full-width { grid-column: 1 / -1; }
  .slider-container { display: flex; align-items: center; gap: 16px; margin-top: 10px; }
  .slider-container input[type=range] { flex: 1; -webkit-appearance: none; height: 8px; border-radius: 4px; background: #1e293b; outline: none; }
  .slider-container input[type=range]::-webkit-slider-thumb { -webkit-appearance: none; width: 24px; height: 24px; border-radius: 50%; background: #3b82f6; cursor: pointer; border: 2px solid #60a5fa; }
  .throttle-bar-bg { height: 8px; border-radius: 4px; background: #1e293b; position: relative; flex: 1; }
  .throttle-bar-target { height: 100%; border-radius: 4px; background: #334155; position: absolute; top: 0; left: 0; transition: width 0.1s; }
  .throttle-bar-current { height: 100%; border-radius: 4px; background: #3b82f6; position: absolute; top: 0; left: 0; transition: width 0.05s linear; }
  .btn-row { display: flex; gap: 12px; margin-top: 16px; flex-wrap: wrap; }
  .btn { padding: 12px 28px; border: none; border-radius: 8px; font-size: 14px; font-weight: 600; cursor: pointer; transition: all 0.15s; text-transform: uppercase; letter-spacing: 0.5px; }
  .btn-sm { padding: 6px 14px; font-size: 12px; }
  .btn-arm { background: #22c55e; color: #000; }
  .btn-arm:hover { background: #16a34a; }
  .btn-arm.armed { background: #ef4444; }
  .btn-arm.armed:hover { background: #dc2626; }
  .btn-arm.arming { background: #f59e0b; color: #000; pointer-events: none; }
  .btn-stop { background: #ef4444; color: #fff; }
  .btn-stop:hover { background: #dc2626; }
  .btn-reverse { background: #8b5cf6; color: #fff; }
  .btn-reverse:hover { background: #7c3aed; }
  .btn-hold { background: #f59e0b; color: #000; font-size: 18px; padding: 20px 40px; user-select: none; -webkit-user-select: none; touch-action: manipulation; width: 100%; }
  .btn-hold:hover { background: #d97706; }
  .btn-hold:active, .btn-hold.active { background: #22c55e; color: #000; box-shadow: 0 0 20px rgba(34,197,94,0.4); }
  .btn-hold.disabled { background: #334155; color: #6b7280; pointer-events: none; }
  .angle-display { position: relative; width: 160px; height: 160px; margin: 0 auto; }
  .angle-ring { width: 160px; height: 160px; border-radius: 50%; border: 3px solid #1e2433; position: relative; }
  .angle-needle { position: absolute; top: 50%; left: 50%; width: 3px; height: 60px; background: #f59e0b; transform-origin: bottom center; border-radius: 2px; margin-left: -1.5px; margin-top: -60px; transition: transform 0.1s linear; }
  .angle-center { position: absolute; top: 50%; left: 50%; width: 10px; height: 10px; background: #f59e0b; border-radius: 50%; margin: -5px 0 0 -5px; }
  .angle-text { text-align: center; margin-top: 12px; font-family: 'SF Mono', monospace; font-size: 24px; color: #f59e0b; }
  .motor-error { color: #ef4444; font-size: 12px; margin-top: 8px; font-family: monospace; }
  .ch-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 12px; }
  .ch-item { background: #1e293b; border-radius: 8px; padding: 12px; }
  .ch-item .ch-name { font-weight: 600; font-size: 14px; margin-bottom: 8px; color: #e0e6f0; }
  .ch-item .ch-pin { font-size: 11px; color: #6b7280; }
  .ch-slider { width: 100%; margin: 8px 0 4px; }
  .ch-val { font-family: 'SF Mono', monospace; font-size: 13px; color: #94a3b8; }
  .ch-slider::-webkit-slider-thumb { -webkit-appearance: none; width: 18px; height: 18px; border-radius: 50%; background: #3b82f6; cursor: pointer; border: 2px solid #60a5fa; }
  .ch-slider::-webkit-slider-runnable-track { height: 6px; border-radius: 3px; background: #0f172a; }
  @media (max-width: 640px) { .grid { grid-template-columns: 1fr; } }
</style>
</head>
<body>
<div class="header">
  <h1>GEO-DUDe Control</h1>
  <div><span class="status-dot" id="statusDot"></span><span id="statusText">Connecting...</span></div>
</div>
<div class="container">
  <div class="grid">
    <div class="card full-width">
      <h2>Camera</h2>
      <div style="text-align:center">
        <img id="camFeed" src="/api/camera" style="width:100%;max-width:640px;border-radius:8px;background:#000" alt="Camera feed">
      </div>
    </div>
    <div class="card">
      <h2>Gyroscope (deg/s)</h2>
      <div class="sensor-row"><span class="sensor-label">X</span><span class="sensor-value x" id="gx">--</span></div>
      <div class="sensor-row"><span class="sensor-label">Y</span><span class="sensor-value y" id="gy">--</span></div>
      <div class="sensor-row"><span class="sensor-label">Z</span><span class="sensor-value z" id="gz">--</span></div>
    </div>
    <div class="card">
      <h2>Accelerometer (g)</h2>
      <div class="sensor-row"><span class="sensor-label">X</span><span class="sensor-value x" id="ax">--</span></div>
      <div class="sensor-row"><span class="sensor-label">Y</span><span class="sensor-value y" id="ay">--</span></div>
      <div class="sensor-row"><span class="sensor-label">Z</span><span class="sensor-value z" id="az">--</span></div>
    </div>
    <div class="card">
      <h2>Encoder</h2>
      <div class="angle-display">
        <div class="angle-ring">
          <div class="angle-needle" id="needle"></div>
          <div class="angle-center"></div>
        </div>
      </div>
      <div class="angle-text" id="angleText">--</div>
    </div>
    <div class="card">
      <h2>System</h2>
      <div class="sensor-row"><span class="sensor-label">Armed</span><span class="sensor-value" id="armedStatus" style="color:#ef4444">NO</span></div>
      <div class="sensor-row"><span class="sensor-label">Target</span><span class="sensor-value" id="targetStatus">0%</span></div>
      <div class="sensor-row"><span class="sensor-label">Throttle</span><span class="sensor-value" id="throttleStatus">0%</span></div>
      <div class="sensor-row"><span class="sensor-label">PWM</span><span class="sensor-value" id="pwmStatus">1000us</span></div>
      <div class="sensor-row"><span class="sensor-label">Direction</span><span class="sensor-value" id="dirStatus">FWD</span></div>
      <div class="motor-error" id="motorError"></div>
    </div>
    <div class="card full-width">
      <h2>MACE — Reaction Wheel</h2>
      <div class="slider-container" style="margin-bottom:16px">
        <span class="sensor-label">Power:</span>
        <input type="range" id="holdPower" min="10" max="100" value="10" oninput="document.getElementById('holdPowerVal').textContent=this.value+'%'">
        <span class="sensor-value" id="holdPowerVal" style="min-width:50px;text-align:right">10%</span>
      </div>
      <div class="slider-container" style="margin-bottom:16px">
        <span class="sensor-label">Ramp:</span>
        <input type="range" id="rampRate" min="0.1" max="100" step="0.1" value="0.1" oninput="updateRampLabel(this.value); sendRampRate(this.value)">
        <span class="sensor-value" id="rampVal" style="min-width:100px;text-align:right">0.1%/s</span>
      </div>
      <div style="margin-bottom:16px">
        <div class="sensor-label" style="margin-bottom:6px">Ramp progress:</div>
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
        <button class="btn btn-stop" onclick="emergencyStop()">EMERGENCY STOP</button>
        <button class="btn btn-reverse" onclick="toggleReverse()">REVERSE</button>
        <button class="btn" style="background:#334155;color:#94a3b8" onclick="startCalibrate()">CALIBRATE ESC</button>
      </div>
      <div id="calPanel" style="display:none;margin-top:16px;padding:16px;background:#1e293b;border-radius:8px;border:1px solid #334155">
        <div id="calStep" style="font-size:14px;line-height:1.6"></div>
        <div class="btn-row" id="calBtns"></div>
      </div>
    </div>
    <div class="card full-width">
      <h2>PCA9685 Channels</h2>
      <div style="margin-bottom:12px">
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

function updateArmUI(armed, arming) {
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
    let delta = target - (currentNeedleAngle % 360);
    if (delta > 180) delta -= 360;
    if (delta < -180) delta += 360;
    currentNeedleAngle += delta;
    document.getElementById('needle').style.transform = 'rotate(' + currentNeedleAngle + 'deg)';
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


if __name__ == '__main__':
    threading.Thread(target=sensor_loop, daemon=True).start()
    threading.Thread(target=ramp_loop, daemon=True).start()
    threading.Thread(target=watchdog_loop, daemon=True).start()
    app.run(host='0.0.0.0', port=8080, threaded=True)
