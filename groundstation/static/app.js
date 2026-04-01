/* ========== Snapshot ========== */
function takeSnapshot() {
  var img = document.getElementById('camFeed');
  var canvas = document.createElement('canvas');
  canvas.width = img.naturalWidth || img.width;
  canvas.height = img.naturalHeight || img.height;
  canvas.getContext('2d').drawImage(img, 0, 0);
  var a = document.createElement('a');
  a.href = canvas.toDataURL('image/jpeg', 0.95);
  var d = new Date();
  a.download = 'snapshot_' + d.getFullYear() + '-' + String(d.getMonth()+1).padStart(2,'0') + '-' + String(d.getDate()).padStart(2,'0') + '_' + String(d.getHours()).padStart(2,'0') + String(d.getMinutes()).padStart(2,'0') + String(d.getSeconds()).padStart(2,'0') + '.jpg';
  a.click();
}

/* ========== Channel controls ========== */
var CHANNELS = {
  "W2B": {ch: 0, pin: 1}, "W2A": {ch: 1, pin: 2}, "W1B": {ch: 2, pin: 3},
  "W1A": {ch: 3, pin: 4}, "E2": {ch: 4, pin: 5}, "E1": {ch: 6, pin: 7},
  "MACE": {ch: 11, pin: 12}, "S2": {ch: 12, pin: 13}, "B2": {ch: 13, pin: 14},
  "S1": {ch: 14, pin: 15}, "B1": {ch: 15, pin: 16}
};
var chOrder = ["B1","S1","B2","S2","MACE","E1","E2","W1A","W1B","W2A","W2B"];
var CH_RAMP_HZ = 30;
var chActual = {};  // actual PWM value sent to hardware per channel

/* Per-channel neutral positions (server-side, persisted to disk) */
var chNeutral = {};

function getNeutral(name) {
  return chNeutral[name] != null ? chNeutral[name] : 1500;
}

function getServoSpeed() {
  var el = document.getElementById('servoSpeed');
  return el ? parseInt(el.value) : 50;
}

function getServoRampRate() {
  var el = document.getElementById('servoRampRate');
  return el ? parseInt(el.value) : 20;
}

function loadServoSettings() {
  try {
    var saved = localStorage.getItem('servoSettings');
    if (saved) {
      var s = JSON.parse(saved);
      if (s.speed != null) {
        var el = document.getElementById('servoSpeed');
        if (el) { el.value = s.speed; updateServoSpeedLabel(s.speed); }
      }
      if (s.ramp != null) {
        var el = document.getElementById('servoRampRate');
        if (el) { el.value = s.ramp; updateServoRampLabel(s.ramp); }
      }
    }
  } catch(e) {}
}

function saveServoSettings() {
  try {
    localStorage.setItem('servoSettings', JSON.stringify({
      speed: getServoSpeed(),
      ramp: getServoRampRate()
    }));
  } catch(e) {}
}

function usToDuty(us) {
  return (us / 20000 * 100).toFixed(1);
}

function chUpdateLabel(name, val) {
  var el = document.getElementById('chv_' + name);
  if (el) el.textContent = val + ' us (' + usToDuty(val) + '%)';
}

function chSendPwm(name, val) {
  fetch('/api/pwm', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({channel: name, pw: val})
  });
}

function chSliderInput(name, val) {
  val = parseInt(val);
  chUpdateLabel(name, val);
  // Actual PWM is sent by the servo ramp loop, not here
}

function chCenter(name) {
  var slider = document.getElementById('ch_' + name);
  if (slider) { slider.value = 1500; chUpdateLabel(name, 1500); }
}

function chGoNeutral(name) {
  var target = getNeutral(name);
  var slider = document.getElementById('ch_' + name);
  if (slider) { slider.value = target; chUpdateLabel(name, target); }
}

function chSetNeutral(name) {
  var slider = document.getElementById('ch_' + name);
  var val = parseInt(slider.value);
  chNeutral[name] = val;
  var label = document.getElementById('chn_' + name);
  if (label) label.textContent = val + ' us';
  fetch('/api/servo_neutral', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({channel: name, pw: val})
  });
}

function allChannelsCenter() {
  chOrder.forEach(function(name) {
    if (name !== 'MACE') chCenter(name);
  });
}

function allChannelsNeutral() {
  chOrder.forEach(function(name) {
    if (name !== 'MACE') chGoNeutral(name);
  });
}

function updateServoSpeedLabel(val) {
  val = parseInt(val);
  var speed = (val * CH_RAMP_HZ).toFixed(0);
  document.getElementById('servoSpeedVal').textContent = val + ' us/tick (' + speed + ' us/s)';
}

function updateServoRampLabel(val) {
  val = parseInt(val);
  var speed = (val * CH_RAMP_HZ).toFixed(0);
  document.getElementById('servoRampVal').textContent = val + ' us/tick (' + speed + ' us/s)';
}

var chVelocity = {};  // current velocity per channel (us/tick, signed)

/* Sync servo sliders from server (multi-client support) */
function servoSyncPoll() {
  fetch('/api/servo_positions').then(function(r) { return r.json(); }).then(function(positions) {
    chOrder.forEach(function(name) {
      if (name === 'MACE') return;
      if (positions[name] == null) return;
      var serverPw = positions[name];
      var slider = document.getElementById('ch_' + name);
      if (!slider) return;
      // Don't override if user is actively dragging
      if (slider.matches(':active')) return;
      var localTarget = parseInt(slider.value);
      var localActual = chActual[name] != null ? chActual[name] : 1500;
      // If our local actual matches server, nothing to do
      if (localActual === serverPw) return;
      // If we're ramping toward a target, don't interrupt
      if (localTarget !== localActual) return;
      // Server has a different position than us — another client moved it
      slider.value = serverPw;
      chActual[name] = serverPw;
      chUpdateLabel(name, serverPw);
    });
  }).catch(function() {});
}

/* Servo ramp loop: trapezoidal velocity profile
   - Accelerates at ramp rate toward max servo speed
   - Decelerates as it approaches the target
*/
function startServoRampLoop() {
  setInterval(function() {
    var maxSpeed = getServoSpeed();
    var accel = getServoRampRate();
    chOrder.forEach(function(name) {
      if (name === 'MACE') return;
      var slider = document.getElementById('ch_' + name);
      if (!slider) return;
      var target = parseInt(slider.value);
      var actual = chActual[name] != null ? chActual[name] : 1500;
      if (actual === target) {
        chVelocity[name] = 0;
        return;
      }
      var diff = target - actual;
      var dir = diff > 0 ? 1 : -1;
      var dist = Math.abs(diff);
      var vel = chVelocity[name] || 0;

      // Decel distance: how far it takes to stop from current speed
      var absVel = Math.abs(vel);
      var decelDist = (absVel * (absVel + accel)) / (2 * accel);

      if (dist <= decelDist || dist <= accel) {
        // Decelerate
        absVel = Math.max(absVel - accel, 1);
      } else {
        // Accelerate toward max speed
        absVel = Math.min(absVel + accel, maxSpeed);
      }

      vel = dir * absVel;
      var step = Math.round(Math.abs(vel));
      if (step > dist) step = dist;

      actual += dir * step;
      chVelocity[name] = vel;
      chActual[name] = actual;
      chSendPwm(name, actual);
    });
  }, 1000 / CH_RAMP_HZ);
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
    var neutralVal = getNeutral(name);
    item.innerHTML = '<div class="ch-header">' +
      '<span class="ch-name">' + name + ' <span style="font-size:11px;color:#6b7280;">(ch ' + CHANNELS[name].ch + ', pin ' + CHANNELS[name].pin + ')</span></span>' +
      '<span class="ch-val" id="chv_' + name + '">1500 us (' + usToDuty(1500) + '%)</span>' +
      '</div>' +
      '<input type="range" id="ch_' + name + '" min="500" max="2500" step="10" value="1500" ' +
      'oninput="chSliderInput(&quot;' + name + '&quot;, this.value)">' +
      '<div class="ch-controls">' +
      '<button class="btn btn-sm btn-dark" onclick="chCenter(&quot;' + name + '&quot;)">Center</button>' +
      '<button class="btn btn-sm" onclick="chGoNeutral(&quot;' + name + '&quot;)">Go to Neutral</button>' +
      '<button class="btn btn-sm btn-red" onclick="chSetNeutral(&quot;' + name + '&quot;)" title="Save current position as neutral">Set Neutral</button>' +
      '<span style="font-size:11px;color:#6b7280;margin-left:4px;">N: <span id="chn_' + name + '">' + neutralVal + ' us</span></span>' +
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
var GIMBAL_DRIVER_NAMES = ['Yaw', 'Pitch', 'Roll', 'Belt'];
var motorPosition = [0, 0, 0, 0];
var gimbalSetupDone = false;
var gimbalDriverCache = [];

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

function gimbalEstop() {
  fetch('/api/gimbal/estop', {method: 'POST'});
}

function gimbalMove(driver, steps) {
  fetch('/api/gimbal/move', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({driver: driver, steps: steps})
  });
}

function gimbalMoveDeg(driver, deg) {
  fetch('/api/gimbal/move_deg', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({driver: driver, deg: deg})
  }).then(function() {
    motorPosition[driver] += deg;
    var el = document.getElementById('motorPos_' + driver);
    if (el) el.textContent = motorPosition[driver].toFixed(1) + '\u00b0';
  });
}

function gimbalMoveDegFromInput(driver) {
  var el = document.getElementById('gimbalDegInput_' + driver);
  if (!el) return;
  var deg = parseFloat(el.value) || 0;
  gimbalMoveDeg(driver, deg);
}

function gimbalMoveStepsFromInput(driver) {
  var el = document.getElementById('gimbalStepInput_' + driver);
  if (!el) return;
  var steps = parseInt(el.value) || 0;
  gimbalMove(driver, steps);
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
  var slider = document.getElementById('gimbalSpeed');
  if (slider) slider.value = us;
  var label = document.getElementById('gimbalSpeedVal');
  if (label) label.textContent = us + ' us';
  fetch('/api/gimbal/speed', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({us: us})
  });
}

function gimbalSetJerk(level) {
  level = parseInt(level);
  var label = document.getElementById('gimbalJerkVal');
  if (label) label.textContent = level;
  fetch('/api/gimbal/jerk', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({level: level})
  });
}

function gimbalEnable(driver) {
  fetch('/api/gimbal/enable', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({driver: driver})
  });
}

function gimbalDisable(driver) {
  fetch('/api/gimbal/disable', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({driver: driver})
  });
}

function gimbalToggleEnable(driver, checkbox) {
  if (checkbox.checked) {
    gimbalEnable(driver);
  } else {
    gimbalDisable(driver);
  }
}

function gimbalSetMotorCurrent(driver, ma) {
  ma = parseInt(ma);
  var label = document.getElementById('motorRunLabel_' + driver);
  if (label) label.textContent = ma + ' mA';
  fetch('/api/gimbal/motor_current', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({driver: driver, ma: ma})
  });
}

function gimbalSetMotorIhold(driver, ma) {
  ma = parseInt(ma);
  var label = document.getElementById('motorIholdLabel_' + driver);
  if (label) label.textContent = ma + ' mA';
  fetch('/api/gimbal/motor_ihold', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({driver: driver, ma: ma})
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
    gimbalDriverCache = drivers;
    gimbalSetupDone = d.setup_done || false;

    /* Global status */
    var statusParts = [];
    statusParts.push('Found: ' + (d.drivers_found != null ? d.drivers_found : drivers.length));
    if (d.step_delay != null) statusParts.push('Speed: ' + d.step_delay + ' us');
    if (d.jerk_level != null) statusParts.push('Jerk: ' + d.jerk_level);
    statusParts.push('Setup: ' + (gimbalSetupDone ? 'YES' : 'NO'));
    document.getElementById('gimbalStatus').textContent = statusParts.join(' | ');

    /* Sync speed slider */
    if (d.step_delay != null) {
      var speedSlider = document.getElementById('gimbalSpeed');
      if (speedSlider && !speedSlider.matches(':active')) {
        speedSlider.value = d.step_delay;
        document.getElementById('gimbalSpeedVal').textContent = d.step_delay + ' us';
      }
    }
    /* Sync jerk slider */
    if (d.jerk_level != null) {
      var jerkSlider = document.getElementById('gimbalJerk');
      if (jerkSlider && !jerkSlider.matches(':active')) {
        jerkSlider.value = d.jerk_level;
        document.getElementById('gimbalJerkVal').textContent = d.jerk_level;
      }
    }

    /* Render driver cards */
    var container = document.getElementById('gimbalDrivers');
    /* Only rebuild if driver count changed */
    if (container.getAttribute('data-count') !== String(drivers.length)) {
      container.setAttribute('data-count', String(drivers.length));
      container.innerHTML = '';
      var gridDiv = document.createElement('div');
      gridDiv.className = 'gimbal-driver-grid';
      gridDiv.id = 'gimbalDriverGrid';

      drivers.forEach(function(drv, i) {
        var card = document.createElement('div');
        card.className = 'driver-card';
        card.id = 'driverCard_' + i;
        var driverName = drv.name || GIMBAL_DRIVER_NAMES[i] || ('Driver ' + i);
        var isBelt = (driverName.toLowerCase() === 'belt');

        var html = '';
        /* Header with toggle */
        html += '<div class="driver-header">';
        html += '<span class="driver-name">' + driverName + ' <span style="font-size:11px;color:#6b7280;">#' + i + '</span></span>';
        html += '<div style="display:flex;align-items:center;gap:8px;">';
        html += '<span id="driverBadges_' + i + '"></span>';
        html += '<label class="toggle-switch"><input type="checkbox" id="driverToggle_' + i + '" onchange="gimbalToggleEnable(' + i + ', this)"><span class="toggle-slider"></span></label>';
        html += '</div></div>';

        /* Status indicators */
        html += '<div class="driver-status-row" id="driverStatusRow_' + i + '"></div>';

        /* Stats line */
        html += '<div class="driver-stats" id="driverStats_' + i + '"></div>';

        /* Current sliders */
        html += '<div class="motor-slider-group">';
        html += '<div class="motor-slider-label"><span class="label">Run Current</span><span class="value" id="motorRunLabel_' + i + '">' + (drv.current_ma || 400) + ' mA</span></div>';
        html += '<input type="range" id="motorRunSlider_' + i + '" min="50" max="2000" step="50" value="' + (drv.current_ma || 400) + '" oninput="gimbalSetMotorCurrent(' + i + ', this.value)">';
        html += '</div>';
        html += '<div class="motor-slider-group">';
        html += '<div class="motor-slider-label"><span class="label">Idle Current</span><span class="value" id="motorIholdLabel_' + i + '">' + (drv.ihold_ma || 0) + ' mA</span></div>';
        html += '<input type="range" id="motorIholdSlider_' + i + '" min="0" max="500" step="10" value="' + (drv.ihold_ma || 0) + '" oninput="gimbalSetMotorIhold(' + i + ', this.value)">';
        html += '</div>';

        if (!isBelt) {
          /* Angle control */
          html += '<div class="motor-position-label">Position</div>';
          html += '<div class="motor-position" id="motorPos_' + i + '">' + motorPosition[i].toFixed(1) + '\u00b0</div>';
          html += '<div class="gear-info" id="gearInfo_' + i + '"></div>';
          html += '<div class="move-input-row">';
          html += '<input type="number" id="gimbalDegInput_' + i + '" value="10" step="1" style="width:80px;">';
          html += '<button class="btn btn-sm" onclick="gimbalMoveDegFromInput(' + i + ')">GO</button>';
          html += '<button class="btn btn-sm btn-red" onclick="gimbalStop(' + i + ')">STOP</button>';
          html += '</div>';
          html += '<div class="angle-btns">';
          var angles = [-90, -45, -10, -5, -1, 1, 5, 10, 45, 90];
          for (var a = 0; a < angles.length; a++) {
            var prefix = angles[a] > 0 ? '+' : '';
            var cls = angles[a] > 0 ? 'btn btn-sm' : 'btn btn-sm btn-dark';
            html += '<button class="' + cls + '" onclick="gimbalMoveDeg(' + i + ', ' + angles[a] + ')">' + prefix + angles[a] + '</button>';
          }
          html += '</div>';
        } else {
          /* Step control for Belt */
          html += '<div class="motor-position-label">Steps Moved</div>';
          html += '<div class="motor-position" id="motorPos_' + i + '">' + motorPosition[i] + '</div>';
          html += '<div class="move-input-row">';
          html += '<input type="number" id="gimbalStepInput_' + i + '" value="1000" step="100" style="width:80px;">';
          html += '<button class="btn btn-sm" onclick="gimbalMoveStepsFromInput(' + i + ')">GO</button>';
          html += '<button class="btn btn-sm btn-red" onclick="gimbalStop(' + i + ')">STOP</button>';
          html += '</div>';
          html += '<div class="step-btns">';
          var steps = [-5000, -1000, -200, 200, 1000, 5000];
          for (var s = 0; s < steps.length; s++) {
            var sprefix = steps[s] > 0 ? '+' : '';
            var scls = steps[s] > 0 ? 'btn btn-sm' : 'btn btn-sm btn-dark';
            html += '<button class="' + scls + '" onclick="gimbalMove(' + i + ', ' + steps[s] + ')">' + sprefix + steps[s] + '</button>';
          }
          html += '</div>';
        }

        card.innerHTML = html;
        gridDiv.appendChild(card);
      });

      container.appendChild(gridDiv);
    }

    /* Update dynamic parts of each card */
    drivers.forEach(function(drv, i) {
      var driverName = drv.name || GIMBAL_DRIVER_NAMES[i] || ('Driver ' + i);
      var isBelt = (driverName.toLowerCase() === 'belt');

      /* Badges */
      var badgesEl = document.getElementById('driverBadges_' + i);
      if (badgesEl) {
        var badgeHtml = '';
        if (!drv.found) {
          badgeHtml += '<span class="driver-badge badge-notfound">NOT FOUND</span>';
        } else if (drv.running) {
          var dirText = drv.dir > 0 ? 'CW' : (drv.dir < 0 ? 'CCW' : '');
          badgeHtml += '<span class="driver-badge badge-running">RUNNING ' + dirText + '</span>';
        } else {
          badgeHtml += '<span class="driver-badge badge-idle">IDLE</span>';
        }
        if (drv.ot) badgeHtml += '<span class="driver-badge badge-warn">OT</span>';
        if (drv.otpw) badgeHtml += '<span class="driver-badge badge-warn">OTPW</span>';
        badgesEl.innerHTML = badgeHtml;
      }

      /* Toggle state */
      var toggle = document.getElementById('driverToggle_' + i);
      if (toggle && !toggle.matches(':active')) {
        toggle.checked = drv.enabled || false;
      }

      /* Stats */
      var statsEl = document.getElementById('driverStats_' + i);
      if (statsEl && drv.found) {
        var parts = [];
        if (drv.cs_actual != null) parts.push('CS: ' + drv.cs_actual);
        if (drv.rms_current != null) parts.push('RMS: ' + drv.rms_current + 'mA');
        if (drv.current_ma != null) parts.push('iRun: ' + drv.current_ma + 'mA');
        if (drv.ihold_ma != null) parts.push('iHold: ' + drv.ihold_ma + 'mA');
        if (drv.steps_remaining != null) parts.push('Rem: ' + drv.steps_remaining);
        if (drv.standstill != null) parts.push(drv.standstill ? 'STBY' : 'MOVE');
        statsEl.textContent = parts.join(' | ');
      } else if (statsEl) {
        statsEl.textContent = '';
      }

      /* Sync current sliders (only if not being dragged) */
      var runSlider = document.getElementById('motorRunSlider_' + i);
      if (runSlider && !runSlider.matches(':active') && drv.current_ma != null) {
        runSlider.value = drv.current_ma;
        var runLabel = document.getElementById('motorRunLabel_' + i);
        if (runLabel) runLabel.textContent = drv.current_ma + ' mA';
      }
      var iholdSlider = document.getElementById('motorIholdSlider_' + i);
      if (iholdSlider && !iholdSlider.matches(':active') && drv.ihold_ma != null) {
        iholdSlider.value = drv.ihold_ma;
        var iholdLabel = document.getElementById('motorIholdLabel_' + i);
        if (iholdLabel) iholdLabel.textContent = drv.ihold_ma + ' mA';
      }

      /* Gear info */
      if (!isBelt) {
        var gearEl = document.getElementById('gearInfo_' + i);
        if (gearEl && drv.gear_ratio != null && drv.steps_per_deg != null) {
          gearEl.textContent = drv.gear_ratio + ':1 gear, ' + drv.steps_per_deg.toFixed(2) + ' steps/deg';
        }
      }

      /* Track position from steps_remaining going to 0 */
      if (drv.running && drv.steps_remaining === 0) {
        /* Move completed — position already updated in gimbalMoveDeg callback */
      }
    });
  }).catch(function() {
    document.getElementById('gimbalDot').className = 'status-dot';
    document.getElementById('gimbalStatus').textContent = 'Not connected';
  });
}

/* ========== Sequence Programmer ========== */
var sequenceEntries = [];

function seqAddRow() {
  sequenceEntries.push({driver: 0, value: 0, time_ms: 0});
  seqRender();
}

function seqRemoveRow(index) {
  sequenceEntries.splice(index, 1);
  seqRender();
}

function seqClearAll() {
  sequenceEntries = [];
  seqRender();
}

function seqRender() {
  var tbody = document.getElementById('seqBody');
  if (!tbody) return;
  tbody.innerHTML = '';
  for (var i = 0; i < sequenceEntries.length; i++) {
    var entry = sequenceEntries[i];
    var tr = document.createElement('tr');
    /* Motor select */
    var motorOpts = '';
    for (var m = 0; m < GIMBAL_DRIVER_NAMES.length; m++) {
      var sel = (entry.driver === m) ? ' selected' : '';
      motorOpts += '<option value="' + m + '"' + sel + '>' + GIMBAL_DRIVER_NAMES[m] + '</option>';
    }
    tr.innerHTML = '<td><select onchange="sequenceEntries[' + i + '].driver = parseInt(this.value)">' + motorOpts + '</select></td>' +
      '<td><input type="number" value="' + entry.value + '" step="1" onchange="sequenceEntries[' + i + '].value = parseFloat(this.value)"></td>' +
      '<td><input type="number" value="' + entry.time_ms + '" step="100" min="0" onchange="sequenceEntries[' + i + '].time_ms = parseInt(this.value)"></td>' +
      '<td><button class="btn btn-sm btn-red" onclick="seqRemoveRow(' + i + ')">X</button></td>';
    tbody.appendChild(tr);
  }
}

function seqRun() {
  if (sequenceEntries.length === 0) return;
  var entries = [];
  for (var i = 0; i < sequenceEntries.length; i++) {
    var e = sequenceEntries[i];
    var driverName = GIMBAL_DRIVER_NAMES[e.driver] || '';
    var isBelt = (driverName.toLowerCase() === 'belt');
    var entry = {driver: e.driver, time_ms: e.time_ms};
    if (isBelt) {
      entry.steps = Math.round(e.value);
    } else {
      entry.deg = e.value;
    }
    entries.push(entry);
  }
  var statusEl = document.getElementById('seqStatus');
  if (statusEl) statusEl.textContent = 'Running sequence (' + entries.length + ' entries)...';
  fetch('/api/gimbal/sequence', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({entries: entries})
  }).then(function(r) { return r.json(); }).then(function(d) {
    if (statusEl) statusEl.textContent = 'Sequence started: ' + (d.entries || 0) + ' entries queued';
  }).catch(function() {
    if (statusEl) statusEl.textContent = 'Error sending sequence';
  });
}

/* ========== Init ========== */
(function() {
  /* Fetch neutral positions from server */
  fetch('/api/servo_neutral').then(function(r) { return r.json(); }).then(function(neutrals) {
    chNeutral = neutrals;
    chOrder.forEach(function(name) {
      if (name === 'MACE') return;
      var label = document.getElementById('chn_' + name);
      if (label) label.textContent = getNeutral(name) + ' us';
    });
  }).catch(function() {});

  /* Fetch last-known servo positions from server (survives reload) */
  fetch('/api/servo_positions').then(function(r) { return r.json(); }).then(function(positions) {
    chOrder.forEach(function(name) {
      if (name === 'MACE') return;
      var pw = positions[name] != null ? positions[name] : 1500;
      chActual[name] = pw;
      var slider = document.getElementById('ch_' + name);
      if (slider) slider.value = pw;
      chUpdateLabel(name, pw);
    });
  }).catch(function() {
    /* Server unreachable — set sliders to 1500 but do NOT send PWM */
    chOrder.forEach(function(name) {
      if (name === 'MACE') return;
      chActual[name] = 1500;
    });
  });

  /* Restore speed settings from localStorage */
  loadServoSettings();

  /* Start servo ramp loop (rate-limits all servo movements) */
  startServoRampLoop();

  /* Start polling */
  setInterval(poll, 100);
  setInterval(attPoll, 500);
  setInterval(sysPoll, 2000);
  setInterval(gimbalPoll, 1000);
  setInterval(servoSyncPoll, 500);

  /* Immediate calls */
  sysPoll();
  gimbalPoll();
})();
