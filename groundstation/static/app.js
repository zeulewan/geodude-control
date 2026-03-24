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
  "S2": {ch: 12, pin: 13}, "B2": {ch: 13, pin: 14},
  "S1": {ch: 14, pin: 15}, "B1": {ch: 15, pin: 16}
};
var chOrder = ["B1","B2","S1","S2","E1","E2","W1A","W2A","W1B","W2B"];
var CH_RAMP_HZ = 30;
var chActual = {};  // actual PWM value sent to hardware per channel

/* Per-channel neutral positions (server-side, persisted to disk) */
var chNeutral = {};

var controllerStatus = {enabled: false};

var visionState = {
  models: ['', '', ''],
  status: 'STANDBY',
  profile: 'Docking',
  mode: 'Observe'
};

function updateVisionUI() {
  var statusEl = document.getElementById('visionModelStatus');
  var countEl = document.getElementById('visionModelCount');
  var profileEl = document.getElementById('visionProfileStatus');
  var pipelineEl = document.getElementById('visionPipelineStatus');
  var noteEl = document.getElementById('visionNote');
  var loadBtn = document.getElementById('visionLoadBtn');
  var previewBtn = document.getElementById('visionPreviewBtn');
  var armBtn = document.getElementById('visionArmBtn');
  var loadedModels = visionState.models.filter(function(name) { return !!name; });
  var hasFile = loadedModels.length > 0;
  visionState.models.forEach(function(name, index) {
    var nameEl = document.getElementById('visionModelName' + (index + 1));
    if (nameEl) nameEl.textContent = name || 'No model selected';
  });
  if (statusEl) {
    statusEl.textContent = visionState.status;
    statusEl.style.color = visionState.status === 'STAGED' ? '#22c55e' : (visionState.status === 'PREVIEW' ? '#3b82f6' : (visionState.status === 'LOADED' ? '#f59e0b' : '#9ca3af'));
  }
  if (countEl) countEl.textContent = loadedModels.length + ' / 3';
  if (profileEl) profileEl.textContent = visionState.profile;
  if (pipelineEl) {
    pipelineEl.textContent = loadedModels.length ? loadedModels.join(' + ') : 'UNASSIGNED';
  }
  if (noteEl) {
    if (!hasFile) {
      noteEl.textContent = 'Frontend placeholder only. Choose up to three model files to stage the UI for future autonomous vision tools.';
    } else if (visionState.status === 'LOADED') {
      noteEl.textContent = 'Models selected in the GUI only: ' + loadedModels.join(', ') + '. No backend inference path is connected yet.';
    } else if (visionState.status === 'PREVIEW') {
      noteEl.textContent = 'Preview staged for ' + visionState.profile + ' in ' + visionState.mode + ' mode with ' + loadedModels.length + ' selected model(s). Camera integration is still backend-pending.';
    } else if (visionState.status === 'STAGED') {
      noteEl.textContent = 'Autonomy UI staged for ' + visionState.profile + ' with ' + loadedModels.join(', ') + '. This does not command hardware or start inference yet.';
    }
  }
  if (loadBtn) loadBtn.className = hasFile ? 'btn' : 'btn btn-dark';
  if (previewBtn) previewBtn.className = hasFile ? 'btn btn-dark' : 'btn btn-dark disabled';
  if (armBtn) armBtn.className = hasFile ? 'btn btn-amber' : 'btn btn-dark disabled';
}

function visionModelChanged(index, input) {
  var file = input && input.files && input.files[0] ? input.files[0] : null;
  visionState.models[index] = file ? file.name : '';
  visionState.status = visionState.models.some(function(name) { return !!name; }) ? 'LOADED' : 'STANDBY';
  updateVisionUI();
}

function visionProfileChanged(value) {
  visionState.profile = value || 'Docking';
  updateVisionUI();
}

function visionModeChanged(value) {
  visionState.mode = value || 'Observe';
  updateVisionUI();
}

function visionLoadModel() {
  if (!visionState.models.some(function(name) { return !!name; })) return;
  visionState.status = 'LOADED';
  updateVisionUI();
}

function visionPreviewPipeline() {
  if (!visionState.models.some(function(name) { return !!name; })) return;
  visionState.status = 'PREVIEW';
  updateVisionUI();
}

function visionStageAutonomy() {
  if (!visionState.models.some(function(name) { return !!name; })) return;
  visionState.status = 'STAGED';
  updateVisionUI();
}

function visionReset() {
  visionState.models = ['', '', ''];
  visionState.status = 'STANDBY';
  visionState.profile = 'Docking';
  visionState.mode = 'Observe';
  [1, 2, 3].forEach(function(slot) {
    var input = document.getElementById('visionModelFile' + slot);
    if (input) input.value = '';
  });
  var profile = document.getElementById('visionProfileSelect');
  if (profile) profile.value = 'Docking';
  var mode = document.getElementById('visionRunMode');
  if (mode) mode.value = 'Observe';
  updateVisionUI();
}

var armVizState = {
  azimuth: 28,
  elevation: 18,
  autoOrbit: false,
  orbitTick: 0,
  rafId: null,
  dragging: false,
  dragStartX: 0,
  dragStartY: 0,
  startAzimuth: 28,
  startElevation: 18,
  zoom: 1,
  startZoom: 1,
  mode: 'live'
};

function armVizChannelValue(name) {
  var slider = document.getElementById('ch_' + name);
  var sliderValue = slider ? parseInt(slider.value, 10) : null;
  var actualValue = (typeof chActual[name] === 'number' && !isNaN(chActual[name])) ? chActual[name] : null;
  if (armVizState.mode === 'test') {
    if (sliderValue != null && !isNaN(sliderValue)) return sliderValue;
    if (actualValue != null) return actualValue;
    return getNeutral(name);
  }
  if (actualValue != null) return actualValue;
  return getNeutral(name);
}

function armVizNormalize(name, scale) {
  return ((armVizChannelValue(name) - getNeutral(name)) / 400) * scale;
}

function armVizBuildArm(side) {
  var isLeft = side === 'left';
  var suffix = isLeft ? '1' : '2';
  var sideBias = isLeft ? -1 : 1;
  var anchor = {x: isLeft ? -120 : 120, y: 50, z: -5};
  var baseRoll = armVizNormalize('B' + suffix, 1.05) + (isLeft ? -0.08 : 0.08);
  var shoulderPitch = armVizNormalize('S' + suffix, 1.05) - 0.12;
  var elbowPitch = armVizNormalize('E' + suffix, 1.0) + 0.72;
  var wristRoll = armVizNormalize('W' + suffix + 'A', 0.8);
  var wristPitch = armVizNormalize('W' + suffix + 'B', 0.75) - 0.25;
  var baseLink = 103;
  var upper = 310;
  var fore = 230;
  var wrist = 55;
  var tool = 75;

  function rotateBaseAxis(vec, roll) {
    return {
      x: vec.x,
      y: vec.y * Math.cos(roll) - vec.z * Math.sin(roll),
      z: vec.y * Math.sin(roll) + vec.z * Math.cos(roll)
    };
  }

  function addPoint(a, b) {
    return {x: a.x + b.x, y: a.y + b.y, z: a.z + b.z};
  }

  function scaleVec(vec, scale) {
    return {x: vec.x * scale, y: vec.y * scale, z: vec.z * scale};
  }

  function normalizeVec(vec) {
    var mag = Math.sqrt(vec.x * vec.x + vec.y * vec.y + vec.z * vec.z) || 1;
    return {x: vec.x / mag, y: vec.y / mag, z: vec.z / mag};
  }

  function crossVec(a, b) {
    return {
      x: a.y * b.z - a.z * b.y,
      y: a.z * b.x - a.x * b.z,
      z: a.x * b.y - a.y * b.x
    };
  }

  function rotateAroundAxis(vec, axis, angle) {
    var unit = normalizeVec(axis);
    var cosA = Math.cos(angle);
    var sinA = Math.sin(angle);
    var dot = vec.x * unit.x + vec.y * unit.y + vec.z * unit.z;
    var cross = crossVec(unit, vec);
    return {
      x: vec.x * cosA + cross.x * sinA + unit.x * dot * (1 - cosA),
      y: vec.y * cosA + cross.y * sinA + unit.y * dot * (1 - cosA),
      z: vec.z * cosA + cross.z * sinA + unit.z * dot * (1 - cosA)
    };
  }

  function pitchDirection(pitch, roll) {
    return rotateBaseAxis({
      x: Math.cos(pitch) * sideBias,
      y: Math.sin(pitch),
      z: 0
    }, roll);
  }

  var base = anchor;
  var shoulderMount = addPoint(anchor, rotateBaseAxis({x: baseLink * sideBias, y: 0, z: 0}, baseRoll));
  var upperDir = pitchDirection(shoulderPitch, baseRoll);
  var elbowPoint = addPoint(shoulderMount, scaleVec(upperDir, upper));
  var foreDir = pitchDirection(shoulderPitch + elbowPitch, baseRoll);
  var wristAPoint = addPoint(elbowPoint, scaleVec(foreDir, fore));
  var wristBPoint = addPoint(wristAPoint, scaleVec(foreDir, wrist));

  var basePitchDir = pitchDirection(shoulderPitch + elbowPitch + wristPitch, baseRoll);
  var toolDir = rotateAroundAxis(basePitchDir, foreDir, wristRoll);
  var tipPoint = addPoint(wristBPoint, scaleVec(normalizeVec(toolDir), tool));

  return {
    color: isLeft ? '#38bdf8' : '#f59e0b',
    joints: [base, shoulderMount, elbowPoint, wristAPoint, wristBPoint, tipPoint],
    tip: tipPoint
  };
}

function armVizProject(point, width, height, azimuth, elevation, zoom) {
  var az = azimuth * Math.PI / 180;
  var el = elevation * Math.PI / 180;
  var x1 = point.x * Math.cos(az) - point.z * Math.sin(az);
  var z1 = point.x * Math.sin(az) + point.z * Math.cos(az);
  var y2 = point.y * Math.cos(el) - z1 * Math.sin(el);
  var z2 = point.y * Math.sin(el) + z1 * Math.cos(el);
  var perspective = 1 + (z2 / 650);
  return {
    x: width / 2 + x1 * perspective * zoom,
    y: height / 2 - y2 * perspective * zoom,
    depth: z2
  };
}

function armVizDrawBox(ctx, width, height, center, size, azimuth, elevation, stroke, fill) {
  var sx = size.x / 2;
  var sy = size.y / 2;
  var sz = size.z / 2;
  var corners = [
    {x: center.x - sx, y: center.y - sy, z: center.z - sz},
    {x: center.x + sx, y: center.y - sy, z: center.z - sz},
    {x: center.x + sx, y: center.y + sy, z: center.z - sz},
    {x: center.x - sx, y: center.y + sy, z: center.z - sz},
    {x: center.x - sx, y: center.y - sy, z: center.z + sz},
    {x: center.x + sx, y: center.y - sy, z: center.z + sz},
    {x: center.x + sx, y: center.y + sy, z: center.z + sz},
    {x: center.x - sx, y: center.y + sy, z: center.z + sz}
  ].map(function(point) {
    return armVizProject(point, width, height, azimuth, elevation, armVizState.zoom);
  });
  var edges = [[0,1],[1,2],[2,3],[3,0],[4,5],[5,6],[6,7],[7,4],[0,4],[1,5],[2,6],[3,7]];
  ctx.save();
  if (fill) {
    ctx.fillStyle = fill;
    ctx.beginPath();
    [0,1,2,3].forEach(function(index, i) {
      var p = corners[index];
      if (!i) ctx.moveTo(p.x, p.y); else ctx.lineTo(p.x, p.y);
    });
    ctx.closePath();
    ctx.fill();
  }
  ctx.strokeStyle = stroke;
  ctx.lineWidth = 1.25;
  edges.forEach(function(edge) {
    var a = corners[edge[0]];
    var b = corners[edge[1]];
    ctx.beginPath();
    ctx.moveTo(a.x, a.y);
    ctx.lineTo(b.x, b.y);
    ctx.stroke();
  });
  ctx.restore();
}

function armVizDrawScene() {
  var canvas = document.getElementById('armVizCanvas');
  if (!canvas) return;
  var rect = canvas.getBoundingClientRect();
  var width = Math.max(320, Math.round(rect.width || 960));
  var height = Math.max(260, Math.round(rect.height || 360));
  if (canvas.width !== width || canvas.height !== height) {
    canvas.width = width;
    canvas.height = height;
  }
  if (armVizState.autoOrbit) {
    armVizState.orbitTick += 0.35;
    armVizState.azimuth = 28 + Math.sin(armVizState.orbitTick * Math.PI / 180) * 32;
    var azEl = document.getElementById('armVizAzimuth');
    if (azEl) azEl.value = Math.round(armVizState.azimuth);
  }
  var ctx = canvas.getContext('2d');
  ctx.clearRect(0, 0, width, height);

  var gradient = ctx.createLinearGradient(0, 0, 0, height);
  gradient.addColorStop(0, 'rgba(15, 23, 42, 0.18)');
  gradient.addColorStop(1, 'rgba(15, 23, 42, 0.72)');
  ctx.fillStyle = gradient;
  ctx.fillRect(0, 0, width, height);

  ctx.strokeStyle = 'rgba(148, 163, 184, 0.18)';
  ctx.lineWidth = 1;
  for (var gx = 0; gx < 9; gx++) {
    var x = (gx / 8) * width;
    ctx.beginPath();
    ctx.moveTo(x, 0);
    ctx.lineTo(x, height);
    ctx.stroke();
  }
  for (var gy = 0; gy < 7; gy++) {
    var y = (gy / 6) * height;
    ctx.beginPath();
    ctx.moveTo(0, y);
    ctx.lineTo(width, y);
    ctx.stroke();
  }

  armVizDrawBox(ctx, width, height, {x: 0, y: 0, z: 0}, {x: 240, y: 300, z: 240}, armVizState.azimuth, armVizState.elevation, 'rgba(148, 163, 184, 0.9)', 'rgba(148, 163, 184, 0.08)');
  armVizDrawBox(ctx, width, height, {x: 0, y: -159, z: 0}, {x: 360, y: 18, z: 300}, armVizState.azimuth, armVizState.elevation, 'rgba(239, 68, 68, 0.95)', 'rgba(239, 68, 68, 0.08)');

  var arms = [armVizBuildArm('left'), armVizBuildArm('right')];
  arms.forEach(function(arm) {
    var pts = arm.joints.map(function(point) {
      return armVizProject(point, width, height, armVizState.azimuth, armVizState.elevation, armVizState.zoom);
    });
    ctx.strokeStyle = arm.color;
    ctx.lineWidth = 3;
    ctx.beginPath();
    pts.forEach(function(point, index) {
      if (!index) ctx.moveTo(point.x, point.y); else ctx.lineTo(point.x, point.y);
    });
    ctx.stroke();

    pts.forEach(function(point, index) {
      ctx.beginPath();
      ctx.fillStyle = index === pts.length - 1 ? '#e2e8f0' : arm.color;
      ctx.arc(point.x, point.y, index === pts.length - 1 ? 5.5 : 4.25, 0, Math.PI * 2);
      ctx.fill();
      if (index === pts.length - 1) {
        ctx.strokeStyle = arm.color;
        ctx.lineWidth = 1.5;
        ctx.stroke();
      }
    });
  });

  ctx.fillStyle = '#cbd5e1';
  ctx.font = '12px "SF Mono", "Fira Code", monospace';
  ctx.fillText('SAT KEEP-OUT', 18, 24);
  ctx.fillStyle = 'rgba(239, 68, 68, 0.95)';
  ctx.fillText('FLOOR KEEP-OUT', 18, 42);

  var leftTip = document.getElementById('armVizLeftTip');
  var rightTip = document.getElementById('armVizRightTip');
  if (leftTip) leftTip.textContent = ['x','y','z'].map(function(axis) { return axis + ':' + Math.round(arms[0].tip[axis]); }).join(' ');
  if (rightTip) rightTip.textContent = ['x','y','z'].map(function(axis) { return axis + ':' + Math.round(arms[1].tip[axis]); }).join(' ');
}

function armVizLoop() {
  armVizDrawScene();
  armVizState.rafId = window.requestAnimationFrame(armVizLoop);
}

function armVizSetView() {
  var az = document.getElementById('armVizAzimuth');
  var el = document.getElementById('armVizElevation');
  var zoom = document.getElementById('armVizZoom');
  if (az) armVizState.azimuth = parseInt(az.value, 10);
  if (el) armVizState.elevation = parseInt(el.value, 10);
  if (zoom) armVizState.zoom = parseInt(zoom.value, 10) / 100;
  armVizSyncControls();
  armVizDrawScene();
}

function armVizSyncControls() {
  var az = document.getElementById('armVizAzimuth');
  var el = document.getElementById('armVizElevation');
  var zoom = document.getElementById('armVizZoom');
  if (az) az.value = Math.round(armVizState.azimuth);
  if (el) el.value = Math.round(armVizState.elevation);
  if (zoom) zoom.value = Math.round(armVizState.zoom * 100);
}

function armVizUpdateModeUI() {
  var modeEl = document.getElementById('armVizModeStatus');
  var liveBtn = document.getElementById('armVizLiveBtn');
  var testBtn = document.getElementById('armVizTestBtn');
  if (modeEl) modeEl.textContent = armVizState.mode === 'live' ? 'LIVE' : 'TEST';
  if (liveBtn) liveBtn.className = armVizState.mode === 'live' ? 'btn btn-sm btn-green' : 'btn btn-sm btn-dark';
  if (testBtn) testBtn.className = armVizState.mode === 'test' ? 'btn btn-sm btn-amber' : 'btn btn-sm btn-dark';
}

function armVizSetMode(mode) {
  armVizState.mode = mode === 'test' ? 'test' : 'live';
  armVizUpdateModeUI();
  armVizDrawScene();
}

function armVizPointerDown(event) {
  var canvas = document.getElementById('armVizCanvas');
  if (!canvas) return;
  armVizState.dragging = true;
  armVizState.autoOrbit = false;
  armVizState.dragStartX = event.clientX;
  armVizState.dragStartY = event.clientY;
  armVizState.startAzimuth = armVizState.azimuth;
  armVizState.startElevation = armVizState.elevation;
  armVizState.startZoom = armVizState.zoom;
  canvas.classList.add('dragging');
  var btn = document.getElementById('armVizOrbitBtn');
  if (btn) btn.textContent = 'AUTO ORBIT';
}

function armVizPointerMove(event) {
  if (!armVizState.dragging) return;
  var dx = event.clientX - armVizState.dragStartX;
  var dy = event.clientY - armVizState.dragStartY;
  armVizState.azimuth = Math.max(-180, Math.min(180, armVizState.startAzimuth - dx * 0.45));
  armVizState.elevation = Math.max(-10, Math.min(70, armVizState.startElevation + dy * 0.22));
  armVizSyncControls();
  armVizDrawScene();
}

function armVizWheel(event) {
  event.preventDefault();
  var delta = event.deltaY > 0 ? -0.08 : 0.08;
  armVizState.zoom = Math.max(0.6, Math.min(1.8, armVizState.zoom + delta));
  armVizSyncControls();
  armVizDrawScene();
}

function armVizPointerUp() {
  if (!armVizState.dragging) return;
  armVizState.dragging = false;
  var canvas = document.getElementById('armVizCanvas');
  if (canvas) canvas.classList.remove('dragging');
}

function armVizBindPointer() {
  var canvas = document.getElementById('armVizCanvas');
  if (!canvas || canvas.dataset.bound === '1') return;
  canvas.dataset.bound = '1';
  canvas.addEventListener('pointerdown', armVizPointerDown);
  canvas.addEventListener('wheel', armVizWheel, {passive: false});
  window.addEventListener('pointermove', armVizPointerMove);
  window.addEventListener('pointerup', armVizPointerUp);
  window.addEventListener('pointercancel', armVizPointerUp);
}

function armVizToggleOrbit() {
  armVizState.autoOrbit = !armVizState.autoOrbit;
  var btn = document.getElementById('armVizOrbitBtn');
  if (btn) btn.textContent = armVizState.autoOrbit ? 'STOP ORBIT' : 'AUTO ORBIT';
  armVizDrawScene();
}

function armVizResetView() {
  armVizState.azimuth = 28;
  armVizState.elevation = 18;
  armVizState.zoom = 1;
  armVizState.autoOrbit = false;
  var az = document.getElementById('armVizAzimuth');
  var el = document.getElementById('armVizElevation');
  var zoom = document.getElementById('armVizZoom');
  var btn = document.getElementById('armVizOrbitBtn');
  if (az) az.value = 28;
  if (el) el.value = 18;
  if (zoom) zoom.value = 100;
  if (btn) btn.textContent = 'AUTO ORBIT';
  armVizDrawScene();
}

function armVizStart() {
  armVizBindPointer();
  armVizUpdateModeUI();
  if (armVizState.rafId != null) return;
  armVizResetView();
  armVizState.rafId = window.requestAnimationFrame(armVizLoop);
}

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

function sendServoSettings() {
  fetch('/api/servo_settings', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({speed: getServoSpeed(), ramp: getServoRampRate()})
  }).catch(function() {});
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

function allChannelsNeutral() {
  chOrder.forEach(function(name) {
    chGoNeutral(name);
  });
}

function startupNeutral() {
  chOrder.forEach(function(name) {
    var pw = getNeutral(name);
    chActual[name] = pw;
    chVelocity[name] = 0;
    var slider = document.getElementById('ch_' + name);
    if (slider) slider.value = pw;
    chUpdateLabel(name, pw);
    chSendPwm(name, pw);
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
  /* Column headers */
  var h1 = document.createElement('div');
  h1.style.cssText = 'font-size:12px;font-weight:700;text-transform:uppercase;letter-spacing:1px;color:#6b7280;padding:4px 0;';
  h1.textContent = 'Arm 1';
  grid.appendChild(h1);
  var h2 = document.createElement('div');
  h2.style.cssText = 'font-size:12px;font-weight:700;text-transform:uppercase;letter-spacing:1px;color:#6b7280;padding:4px 0;';
  h2.textContent = 'Arm 2';
  grid.appendChild(h2);
  chOrder.forEach(function(name) {
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

/* ========== MACE Controls (SimpleFOC / Pi Pico) ========== */

var _maceEnabled = false;

function maceUpdateSliderLabel(val) {
  val = parseFloat(val);
  document.getElementById('velSliderVal').textContent = val.toFixed(1) + ' rad/s';
}

function maceEnable() {
  fetch('/api/mace/enable', {method: 'POST'})
    .then(function(r) { return r.json(); })
    .then(function(d) { _maceUpdateUI(d.enabled); });
}

function maceDisable() {
  fetch('/api/mace/disable', {method: 'POST'})
    .then(function(r) { return r.json(); })
    .then(function(d) { _maceUpdateUI(d.enabled); });
}

function maceSetVelocity(v) {
  v = parseFloat(v) || 0;
  fetch('/api/mace/velocity', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({target: v})
  });
}

function maceStop() {
  fetch('/api/mace/stop', {method: 'POST'});
}

function maceSetPreset(v) {
  var slider = document.getElementById('velSlider');
  if (slider) { slider.value = v; maceUpdateSliderLabel(v); }
  maceSetVelocity(v);
}

function macePoll() {
  fetch('/api/mace/status').then(function(r) { return r.json(); }).then(function(d) {
    _maceEnabled = d.enabled || false;
    _maceUpdateUI(_maceEnabled);
    var picoEl = document.getElementById('picoConnected');
    if (picoEl) {
      picoEl.textContent = d.connected ? 'CONNECTED' : 'DISCONNECTED';
      picoEl.style.color = d.connected ? '#22c55e' : '#ef4444';
    }
    var enEl = document.getElementById('maceEnabled');
    if (enEl) {
      enEl.textContent = d.enabled ? 'YES' : 'NO';
      enEl.style.color = d.enabled ? '#22c55e' : '#ef4444';
    }
    var tgt = d.target != null ? d.target : 0;
    var vel = d.velocity != null ? d.velocity : 0;
    var tEl = document.getElementById('maceTarget');
    if (tEl) tEl.textContent = tgt.toFixed(2) + ' rad/s';
    var vEl = document.getElementById('maceVelocity');
    if (vEl) vEl.textContent = vel.toFixed(2) + ' rad/s';
    // Encoder angle from sensor data
    var angEl = document.getElementById('maceEncoderAngle');
    if (angEl) {
      var ang = d.encoder_angle != null ? d.encoder_angle : 0;
      angEl.textContent = ang.toFixed(1) + ' deg';
    }
    // Wheel RPM from sensor data (real encoder delta/dt, not velocity estimate)
    var rpm = d.rpm != null ? d.rpm : Math.round(vel * 60 / (2 * Math.PI));
    var rpmEl = document.getElementById('maceRpm');
    if (rpmEl) rpmEl.textContent = Math.round(rpm);
    var errEl = document.getElementById('maceError');
    if (errEl) {
      if (d.error) {
        errEl.textContent = d.error;
        errEl.style.display = 'block';
      } else {
        errEl.textContent = '';
        errEl.style.display = 'none';
      }
    }
  }).catch(function() {});
}

function maceToggle() {
  if (_maceEnabled) {
    maceDisable();
  } else {
    maceEnable();
  }
}

function _maceUpdateUI(enabled) {
  _maceEnabled = enabled;
  var btn = document.getElementById('maceToggleBtn');
  var setBtn = document.getElementById('maceSetVelBtn');
  if (btn) {
    btn.textContent = enabled ? 'DISABLE' : 'ENABLE';
    btn.className = enabled ? 'btn btn-red' : 'btn btn-green';
  }
  if (setBtn) {
    if (enabled) {
      setBtn.classList.remove('disabled');
    } else {
      setBtn.classList.add('disabled');
    }
  }
}

/* ========== Polling ========== */
function updateControllerUI(status) {
  controllerStatus = status || {enabled: false};
  var modeEl = document.getElementById('controllerMode');
  var linkEl = document.getElementById('controllerLink');
  var armEl = document.getElementById('controllerArm');
  var deadmanEl = document.getElementById('controllerDeadman');
  var activeEl = document.getElementById('controllerActivity');
  var errorEl = document.getElementById('controllerError');
  var btn = document.getElementById('controllerToggleBtn');
  var leftBtn = document.getElementById('controllerArmLeftBtn');
  var rightBtn = document.getElementById('controllerArmRightBtn');
  if (modeEl) {
    modeEl.textContent = controllerStatus.enabled ? 'ON' : 'OFF';
    modeEl.style.color = controllerStatus.enabled ? '#22c55e' : '#9ca3af';
  }
  if (linkEl) {
    linkEl.textContent = controllerStatus.connected ? 'CONNECTED' : 'DISCONNECTED';
    linkEl.style.color = controllerStatus.connected ? '#22c55e' : '#ef4444';
  }
  if (armEl) {
    armEl.textContent = (controllerStatus.selected_arm || "left").toUpperCase();
    armEl.style.color = "#f59e0b";
  }
  if (leftBtn) leftBtn.className = controllerStatus.selected_arm === "left" ? "btn btn-amber" : "btn btn-dark";
  if (rightBtn) rightBtn.className = controllerStatus.selected_arm === "right" ? "btn btn-amber" : "btn btn-dark";
  if (deadmanEl) {
    deadmanEl.textContent = controllerStatus.deadman ? 'HELD' : 'RELEASED';
    deadmanEl.style.color = controllerStatus.deadman ? '#22c55e' : '#9ca3af';
  }
  if (activeEl) {
    activeEl.textContent = controllerStatus.active ? 'MOVING' : 'IDLE';
    activeEl.style.color = controllerStatus.active ? '#3b82f6' : '#9ca3af';
  }
  if (errorEl) {
    errorEl.textContent = controllerStatus.last_error || '';
    errorEl.style.display = controllerStatus.last_error ? 'block' : 'none';
  }
  if (btn) {
    btn.textContent = controllerStatus.enabled ? 'DISABLE CONTROLLER' : 'ENABLE CONTROLLER';
    btn.className = controllerStatus.enabled ? 'btn btn-red' : 'btn btn-dark';
  }
}

function controllerPoll() {
  fetch('/api/controller/status').then(function(r) { return r.json(); }).then(function(d) {
    updateControllerUI(d);
  }).catch(function() {});
}

function setControllerArm(selectedArm) {
  fetch('/api/controller/arm', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({selected_arm: selectedArm})
  }).then(function(r) { return r.json(); }).then(function(d) {
    updateControllerUI(d);
  });
}

function toggleControllerMode() {
  var enable = !controllerStatus.enabled;
  fetch('/api/controller/enable', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({enabled: enable})
  }).then(function(r) { return r.json(); }).then(function(d) {
    updateControllerUI(d);
  });
}

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
    /* GEO-DUDe connection dot */
    var connected = d.connected || false;
    var dot = document.getElementById('statusDot');
    if (connected) {
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
      var label = document.getElementById('chn_' + name);
      if (label) label.textContent = getNeutral(name) + ' us';
    });
  }).catch(function() {});

  /* Fetch last-known servo positions from server, fallback to neutral */
  fetch('/api/servo_positions').then(function(r) { return r.json(); }).then(function(positions) {
    chOrder.forEach(function(name) {
      var pw = positions[name] != null ? positions[name] : getNeutral(name);
      chActual[name] = pw;
      var slider = document.getElementById('ch_' + name);
      if (slider) slider.value = pw;
      chUpdateLabel(name, pw);
    });
  }).catch(function() {
    /* Server unreachable — default to neutral, do NOT send PWM */
    chOrder.forEach(function(name) {
      chActual[name] = getNeutral(name);
    });
  });

  /* Restore speed settings from localStorage */
  loadServoSettings();
  sendServoSettings();

  /* Start servo ramp loop (rate-limits all servo movements) */
  startServoRampLoop();

  /* Start polling */
  setInterval(poll, 100);
  setInterval(macePoll, 250);
  setInterval(sysPoll, 2000);
  setInterval(gimbalPoll, 1000);
  setInterval(servoSyncPoll, 500);
  setInterval(controllerPoll, 250);

  /* Immediate calls */
  macePoll();
  sysPoll();
  gimbalPoll();
  controllerPoll();
  updateVisionUI();
  armVizStart();
})();
