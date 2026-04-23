/* ========== Snapshot ========== */
var cameraStreamEnabled = true;
var CAMERA_STREAM_STORAGE_KEY = 'cameraStreamEnabled';

function applyCameraStreamState() {
  var img = document.getElementById('camFeed');
  var wrapper = document.getElementById('camWrapper');
  var toggleBtn = document.getElementById('cameraToggleBtn');
  var statusLabel = document.getElementById('cameraStatusLabel');
  var snapshotBtn = document.getElementById('snapshotBtn');
  if (!img || !wrapper) return;
  if (cameraStreamEnabled) {
    if (img.dataset.streamSrc) {
      img.src = img.dataset.streamSrc;
    } else {
      img.src = '/api/camera';
      img.dataset.streamSrc = '/api/camera';
    }
  } else {
    if (!img.dataset.streamSrc) img.dataset.streamSrc = img.src || '/api/camera';
    img.removeAttribute('src');
  }
  wrapper.classList.toggle('stream-off', !cameraStreamEnabled);
  if (toggleBtn) toggleBtn.textContent = cameraStreamEnabled ? 'TURN OFF' : 'TURN ON';
  if (statusLabel) {
    statusLabel.textContent = cameraStreamEnabled ? 'STREAM ON' : 'STREAM OFF';
    statusLabel.style.color = cameraStreamEnabled ? '#22c55e' : '#94a3b8';
  }
  if (snapshotBtn) snapshotBtn.disabled = !cameraStreamEnabled;
}

function loadCameraStreamState() {
  try {
    var saved = localStorage.getItem(CAMERA_STREAM_STORAGE_KEY);
    if (saved != null) cameraStreamEnabled = saved !== '0';
  } catch (e) {}
  applyCameraStreamState();
}

function toggleCameraStream() {
  cameraStreamEnabled = !cameraStreamEnabled;
  try {
    localStorage.setItem(CAMERA_STREAM_STORAGE_KEY, cameraStreamEnabled ? '1' : '0');
  } catch (e) {}
  applyCameraStreamState();
}

function takeSnapshot() {
  if (!cameraStreamEnabled) return;
  var img = document.getElementById('camFeed');
  if (!img || !img.src) return;
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
  "B1": {ch: 0, pin: 1}, "S1": {ch: 1, pin: 2}, "B2": {ch: 2, pin: 3},
  "S2": {ch: 3, pin: 4}, "E1": {ch: 4, pin: 5}, "E2": {ch: 5, pin: 6},
  "W1A": {ch: 6, pin: 7}, "W1B": {ch: 7, pin: 8}, "W2A": {ch: 8, pin: 9},
  "W2B": {ch: 9, pin: 10}, "MACE": {ch: 11, pin: 12}
};
var chOrder = ["B1","B2","S1","S2","E1","E2","W1A","W2A","W1B","W2B","MACE"];
var CH_RAMP_HZ = 30;
var chActual = {};  // actual PWM value sent to hardware per channel

/* Per-channel neutral positions. AUTHORITY: server-side servo_neutral.json.
   Hydrated from /api/servo_neutral at page load (see init). Do NOT read
   this map before that fetch resolves -- empty {} is the safe state; any
   hardcoded fallback here will silently drive servos to stale positions
   after the operator re-measures neutrals. */
var chNeutral = {};
var chNeutralLoaded = false;

/* Per-channel joint calibration hydrated from /api/joint_calibration.
   Shape per channel:
     { us_per_rad, sign, neutral_angle_rad, min_angle_rad, max_angle_rad }
   pwToAngleRad() returns null until this loads -- callers treat null
   as "don't render an angle yet" (display '-'), not as 0. */
var jointCal = {};
var jointCalLoaded = false;

function pwToAngleRad(name, pw) {
  if (!jointCalLoaded) return null;
  var cal = jointCal[name];
  var neutral = chNeutral[name];
  if (!cal || neutral == null || !cal.us_per_rad) return null;
  var base = cal.neutral_angle_rad != null ? cal.neutral_angle_rad : 0;
  return base + (pw - neutral) / cal.us_per_rad * (cal.sign || 1);
}

function radToDeg(r) { return r * 180 / Math.PI; }
function degToRad(d) { return d * Math.PI / 180; }

var controllerStatus = {enabled: false};

/* IK status is only needed while the arm workspace view is mounted. */
var ikStatus = null;
var ikLastResult = null;

function ikRefreshStatus() {
  fetch('/api/ik/status').then(function(r) { return r.json(); }).then(function(status) {
    ikStatus = status;
  }).catch(function() {});
}

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

var armVizGeometryDefaults = {
  satWidth: 240,
  satLength: 240,
  satHeight: 300,
  attachBottom: 200,
  attachRear: 65,
  base: 103,
  upper: 310,
  forearm: 230,
  wristA: 55,
  tool: 75
};
var armVizGeometryStorageKey = 'armVizGeometryV2';
var armVizGeometry = Object.assign({}, armVizGeometryDefaults);
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
  mode: 'live',
  activeCanvasId: null
};

function armVizGeometryFields() {
  return {
    satWidth: 'armVizSatWidth',
    satLength: 'armVizSatLength',
    satHeight: 'armVizSatHeight',
    attachBottom: 'armVizAttachBottom',
    attachRear: 'armVizAttachRear',
    base: 'armVizLinkBase',
    upper: 'armVizLinkUpper',
    forearm: 'armVizLinkForearm',
    wristA: 'armVizLinkWristA',
    tool: 'armVizLinkTool'
  };
}

function armVizAnchorForSide(side) {
  return {
    x: side === 'left' ? -armVizGeometry.satWidth / 2 : armVizGeometry.satWidth / 2,
    y: -armVizGeometry.satHeight / 2 + armVizGeometry.attachBottom,
    z: -armVizGeometry.satLength / 2 + armVizGeometry.attachRear
  };
}

function armVizRefreshGeometryUI() {
  var fields = armVizGeometryFields();
  Object.keys(fields).forEach(function(key) {
    var input = document.getElementById(fields[key]);
    if (input && document.activeElement !== input) input.value = armVizGeometry[key];
  });
  var leftAnchor = armVizAnchorForSide('left');
  var rightAnchor = armVizAnchorForSide('right');
  var satSummary = document.getElementById('armVizSatSummary');
  var anchorSummary = document.getElementById('armVizAnchorSummary');
  var linkSummary = document.getElementById('armVizLinkSummary');
  var floorSummary = document.getElementById('armVizFloorSummary');
  if (satSummary) satSummary.textContent = armVizGeometry.satWidth + ' x ' + armVizGeometry.satLength + ' x ' + armVizGeometry.satHeight + ' mm';
  if (anchorSummary) anchorSummary.textContent = 'L(' + Math.round(leftAnchor.x) + ', ' + Math.round(leftAnchor.y) + ', ' + Math.round(leftAnchor.z) + ') R(' + Math.round(rightAnchor.x) + ', ' + Math.round(rightAnchor.y) + ', ' + Math.round(rightAnchor.z) + ')';
  if (linkSummary) linkSummary.textContent = [armVizGeometry.base, armVizGeometry.upper, armVizGeometry.forearm, armVizGeometry.wristA, armVizGeometry.tool].join(' / ') + ' mm';
  if (floorSummary) {
    var floorX = Math.round(armVizGeometry.satWidth + 2 * (armVizGeometry.base + armVizGeometry.upper + armVizGeometry.forearm + armVizGeometry.wristA + armVizGeometry.tool));
    var floorZ = Math.round(armVizGeometry.satLength + 2 * (armVizGeometry.base + armVizGeometry.upper + armVizGeometry.forearm + armVizGeometry.wristA + armVizGeometry.tool));
    floorSummary.textContent = floorX + ' x ' + floorZ + ' mm';
  }
}

function armVizLoadGeometry() {
  try {
    var saved = localStorage.getItem(armVizGeometryStorageKey);
    if (saved) {
      var parsed = JSON.parse(saved);
      Object.keys(armVizGeometryDefaults).forEach(function(key) {
        if (parsed[key] != null && !isNaN(parsed[key])) armVizGeometry[key] = parseFloat(parsed[key]);
      });
    }
  } catch (e) {}
  armVizRefreshGeometryUI();
}

function armVizGeometryChanged() {
  var fields = armVizGeometryFields();
  Object.keys(fields).forEach(function(key) {
    var input = document.getElementById(fields[key]);
    if (!input) return;
    var value = parseFloat(input.value);
    if (!isNaN(value)) armVizGeometry[key] = value;
  });
  try {
    localStorage.setItem(armVizGeometryStorageKey, JSON.stringify(armVizGeometry));
  } catch (e) {}
  armVizRefreshGeometryUI();
  armVizDrawScene();
}

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

function armVizConfigForSide(side) {
  return ikStatus && ikStatus.config && ikStatus.config.arms ? ikStatus.config.arms[side] : null;
}

function armVizSliderAngles(side) {
  var config = armVizConfigForSide(side);
  var suffix = side === 'left' ? '1' : '2';
  if (!config || !config.joints) {
    return {
      base: armVizNormalize('B' + suffix, 1.05) + (side === 'left' ? -0.08 : 0.08),
      shoulder: armVizNormalize('S' + suffix, 1.05) - 0.12,
      elbow: armVizNormalize('E' + suffix, 1.0) + 0.72,
      wrist_roll: armVizNormalize('W' + suffix + 'A', 0.8),
      wrist_pitch: armVizNormalize('W' + suffix + 'B', 0.75) - 0.25
    };
  }
  var mapping = {
    base: 'B' + suffix,
    shoulder: 'S' + suffix,
    elbow: 'E' + suffix,
    wrist_roll: 'W' + suffix + 'A',
    wrist_pitch: 'W' + suffix + 'B'
  };
  var angles = {};
  Object.keys(mapping).forEach(function(jointName) {
    var joint = config.joints[jointName];
    var channel = mapping[jointName];
    var pwm = armVizChannelValue(channel);
    var neutral = getNeutral(channel);
    if (!joint || typeof pwm !== 'number') {
      angles[jointName] = 0;
      return;
    }
    // angle = neutral_angle_rad + (pw - neutral_pw)/us_per_rad * sign
    // neutral_angle_rad defaults to 0 for old configs that don't carry it.
    var base = joint.neutral_angle_rad != null ? joint.neutral_angle_rad : 0;
    var angle = base + ((pwm - neutral) / joint.us_per_rad) * joint.sign;
    if (joint.min_angle != null) angle = Math.max(joint.min_angle, angle);
    if (joint.max_angle != null) angle = Math.min(joint.max_angle, angle);
    angles[jointName] = angle;
  });
  return angles;
}

function armVizNormalize(name, scale) {
  return ((armVizChannelValue(name) - getNeutral(name)) / 400) * scale;
}

function armVizLiveAngles(side) {
  if (ikStatus && ikStatus.arms && ikStatus.arms[side] && ikStatus.arms[side].angles_rad) {
    return ikStatus.arms[side].angles_rad;
  }
  return null;
}

function armVizBuildArm(side, overrideAngles) {
  var isLeft = side === 'left';
  var suffix = isLeft ? '1' : '2';
  var sideBias = isLeft ? -1 : 1;
  var anchor = armVizAnchorForSide(side);
  var liveAngles = armVizState.mode === 'live' ? armVizLiveAngles(side) : null;
  var sliderAngles = armVizState.mode === 'test' ? armVizSliderAngles(side) : null;
  var sourceAngles = overrideAngles || liveAngles || sliderAngles;
  var baseRoll = sourceAngles && typeof sourceAngles.base === 'number' ? sourceAngles.base : armVizNormalize('B' + suffix, 1.05) + (isLeft ? -0.08 : 0.08);
  var shoulderPitch = sourceAngles && typeof sourceAngles.shoulder === 'number' ? sourceAngles.shoulder : armVizNormalize('S' + suffix, 1.05) - 0.12;
  var elbowPitch = sourceAngles && typeof sourceAngles.elbow === 'number' ? sourceAngles.elbow : armVizNormalize('E' + suffix, 1.0) + 0.72;
  var wristRoll = sourceAngles && typeof sourceAngles.wrist_roll === 'number' ? sourceAngles.wrist_roll : armVizNormalize('W' + suffix + 'A', 0.8);
  var wristPitch = sourceAngles && typeof sourceAngles.wrist_pitch === 'number' ? sourceAngles.wrist_pitch : armVizNormalize('W' + suffix + 'B', 0.75) - 0.25;
  var baseLink = armVizGeometry.base;
  var upper = armVizGeometry.upper;
  var fore = armVizGeometry.forearm;
  var wrist = armVizGeometry.wristA;
  var tool = armVizGeometry.tool;

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
    side: side,
    color: isLeft ? '#38bdf8' : '#f59e0b',
    joints: [base, shoulderMount, elbowPoint, wristAPoint, wristBPoint, tipPoint],
    tip: tipPoint
  };
}

function armVizIkTargetPoint() {
  var x = parseFloat((document.getElementById('ikTargetX') || {}).value);
  var y = parseFloat((document.getElementById('ikTargetY') || {}).value);
  var z = parseFloat((document.getElementById('ikTargetZ') || {}).value);
  if (isNaN(x) || isNaN(y) || isNaN(z)) return null;
  return {x: x, y: y, z: z};
}

function armVizProject(point, width, height, azimuth, elevation, zoom) {
  var az = azimuth * Math.PI / 180;
  var el = elevation * Math.PI / 180;
  var x1 = point.x * Math.cos(az) - point.z * Math.sin(az);
  var z1 = point.x * Math.sin(az) + point.z * Math.cos(az);
  var y2 = point.y * Math.cos(el) - z1 * Math.sin(el);
  var z2 = point.y * Math.sin(el) + z1 * Math.cos(el);
  return {
    x: width / 2 + x1 * zoom,
    y: height / 2 - y2 * zoom,
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

function armVizDrawArm(ctx, width, height, arm, options) {
  options = options || {};
  var pts = arm.joints.map(function(point) {
    return armVizProject(point, width, height, armVizState.azimuth, armVizState.elevation, armVizState.zoom);
  });
  ctx.save();
  ctx.strokeStyle = options.stroke || arm.color;
  ctx.lineWidth = options.lineWidth || 3;
  ctx.setLineDash(options.dash || []);
  ctx.globalAlpha = options.opacity != null ? options.opacity : 1;
  ctx.beginPath();
  pts.forEach(function(point, index) {
    if (!index) ctx.moveTo(point.x, point.y); else ctx.lineTo(point.x, point.y);
  });
  ctx.stroke();
  ctx.setLineDash([]);
  pts.forEach(function(point, index) {
    var radius = index === pts.length - 1 ? (options.tipRadius || 5.5) : (options.jointRadius || 4.25);
    ctx.beginPath();
    ctx.fillStyle = index === pts.length - 1 ? (options.tipFill || '#e2e8f0') : (options.jointFill || arm.color);
    ctx.arc(point.x, point.y, radius, 0, Math.PI * 2);
    ctx.fill();
    if (index === pts.length - 1 || options.jointStroke) {
      ctx.strokeStyle = options.tipStroke || options.stroke || arm.color;
      ctx.lineWidth = options.tipStrokeWidth || 1.5;
      ctx.stroke();
    }
  });
  ctx.restore();
}

function armVizDrawTargetMarker(ctx, width, height, point) {
  if (!point) return;
  var projected = armVizProject(point, width, height, armVizState.azimuth, armVizState.elevation, armVizState.zoom);
  ctx.save();
  ctx.strokeStyle = 'rgba(34, 197, 94, 0.95)';
  ctx.fillStyle = 'rgba(34, 197, 94, 0.18)';
  ctx.lineWidth = 2;
  ctx.beginPath();
  ctx.arc(projected.x, projected.y, 8, 0, Math.PI * 2);
  ctx.fill();
  ctx.stroke();
  ctx.beginPath();
  ctx.moveTo(projected.x - 12, projected.y);
  ctx.lineTo(projected.x + 12, projected.y);
  ctx.moveTo(projected.x, projected.y - 12);
  ctx.lineTo(projected.x, projected.y + 12);
  ctx.stroke();
  ctx.font = '11px "SF Mono", "Fira Code", monospace';
  ctx.fillStyle = 'rgba(34, 197, 94, 0.95)';
  ctx.fillText('TARGET', projected.x + 12, projected.y - 10);
  ctx.restore();
}

function armVizRenderCanvas(canvas, options) {
  if (!canvas) return null;
  var rect = canvas.getBoundingClientRect();
  var fallbackWidth = options && options.fallbackWidth ? options.fallbackWidth : 960;
  var fallbackHeight = options && options.fallbackHeight ? options.fallbackHeight : 360;
  var minWidth = options && options.minWidth ? options.minWidth : 320;
  var minHeight = options && options.minHeight ? options.minHeight : 260;
  var width = Math.max(minWidth, Math.round(rect.width || fallbackWidth));
  var height = Math.max(minHeight, Math.round(rect.height || fallbackHeight));
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
  var renderZoom = armVizState.zoom * (options && options.zoomMultiplier ? options.zoomMultiplier : 1);
  var showTarget = !(options && options.showTarget === false);
  var showLegend = !(options && options.showLegend === false);
  var originalZoom = armVizState.zoom;
  armVizState.zoom = renderZoom;
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

  var satSize = {x: armVizGeometry.satWidth, y: armVizGeometry.satHeight, z: armVizGeometry.satLength};
  var floorSpan = armVizGeometry.base + armVizGeometry.upper + armVizGeometry.forearm + armVizGeometry.wristA + armVizGeometry.tool;
  var floorSize = {x: armVizGeometry.satWidth + (floorSpan * 2), y: 18, z: armVizGeometry.satLength + (floorSpan * 2)};
  armVizDrawBox(ctx, width, height, {x: 0, y: 0, z: 0}, satSize, armVizState.azimuth, armVizState.elevation, 'rgba(148, 163, 184, 0.9)', 'rgba(148, 163, 184, 0.08)');
  armVizDrawBox(ctx, width, height, {x: 0, y: (-armVizGeometry.satHeight / 2) - (floorSize.y / 2), z: 0}, floorSize, armVizState.azimuth, armVizState.elevation, 'rgba(239, 68, 68, 0.95)', 'rgba(239, 68, 68, 0.08)');

  var arms = [armVizBuildArm('left'), armVizBuildArm('right')];
  var ikTarget = showTarget ? armVizIkTargetPoint() : null;
  var solvedArm = options && Object.prototype.hasOwnProperty.call(options, 'solvedArm') ? options.solvedArm : null;
  if (solvedArm == null && ikLastResult && ikLastResult.ok && ikLastResult.arm && ikLastResult.angles_rad) {
    solvedArm = armVizBuildArm(ikLastResult.arm, ikLastResult.angles_rad);
  }

  arms.forEach(function(arm) {
    armVizDrawArm(ctx, width, height, arm);
  });
  if (solvedArm) {
    armVizDrawArm(ctx, width, height, solvedArm, {
      stroke: solvedArm.color,
      jointFill: solvedArm.color,
      tipFill: 'rgba(226, 232, 240, 0.55)',
      opacity: 0.38,
      dash: [10, 7],
      lineWidth: 2.5,
      jointRadius: 3.5,
      tipRadius: 5,
      tipStrokeWidth: 1.25
    });
  }
  armVizDrawTargetMarker(ctx, width, height, ikTarget);

  if (showLegend) {
    ctx.fillStyle = '#cbd5e1';
    ctx.font = '12px "SF Mono", "Fira Code", monospace';
    ctx.fillText('SAT KEEP-OUT', 18, 24);
    ctx.fillStyle = 'rgba(239, 68, 68, 0.95)';
    ctx.fillText('FLOOR KEEP-OUT', 18, 42);
    if (showTarget) {
      ctx.fillStyle = 'rgba(34, 197, 94, 0.95)';
      ctx.fillText('IK TARGET', 18, 60);
    }
    if (solvedArm) {
      ctx.fillStyle = 'rgba(226, 232, 240, 0.82)';
      ctx.fillText('SOLVED POSE', 18, showTarget ? 78 : 60);
    }
  }

  armVizState.zoom = originalZoom;
  return arms;
}

function armVizDrawScene() {
  var arms = armVizRenderCanvas(document.getElementById('armVizCanvas'), {fallbackWidth: 960, fallbackHeight: 420, minWidth: 320, minHeight: 260});
  if (!arms) return;
  var leftTip = document.getElementById('armVizLeftTip');
  var rightTip = document.getElementById('armVizRightTip');
  var leftText = ['x','y','z'].map(function(axis) { return axis + ':' + Math.round(arms[0].tip[axis]); }).join(' ');
  var rightText = ['x','y','z'].map(function(axis) { return axis + ':' + Math.round(arms[1].tip[axis]); }).join(' ');
  if (leftTip) leftTip.textContent = leftText;
  if (rightTip) rightTip.textContent = rightText;
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

function armVizResetTestSlidersToCenters() {
  chOrder.forEach(function(name) {
    if (name === 'MACE') return;
    var slider = document.getElementById('ch_' + name);
    var neutral = getNeutral(name);
    if (!slider || typeof neutral !== 'number' || isNaN(neutral)) return;
    slider.value = neutral;
    chUpdateLabel(name, neutral);
  });
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
  var nextMode = mode === 'test' ? 'test' : 'live';
  var changed = armVizState.mode !== nextMode;
  armVizState.mode = nextMode;
  if (changed && nextMode === 'test') {
    armVizResetTestSlidersToCenters();
  }
  armVizUpdateModeUI();
  armVizDrawScene();
}

function armVizPointerDown(event) {
  var canvas = event.currentTarget;
  if (!canvas) return;
  armVizState.dragging = true;
  armVizState.activeCanvasId = canvas.id || null;
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
  var canvases = ['armVizCanvas'];
  canvases.forEach(function(id) {
    var canvas = document.getElementById(id);
    if (canvas) canvas.classList.remove('dragging');
  });
  armVizState.activeCanvasId = null;
}

function armVizBindPointer() {
  ['armVizCanvas'].forEach(function(id) {
    var canvas = document.getElementById(id);
    if (!canvas || canvas.dataset.bound === '1') return;
    canvas.dataset.bound = '1';
    canvas.addEventListener('pointerdown', armVizPointerDown);
    canvas.addEventListener('wheel', armVizWheel, {passive: false});
  });
  if (!window.__armVizPointerBound) {
    window.__armVizPointerBound = true;
    window.addEventListener('pointermove', armVizPointerMove);
    window.addEventListener('pointerup', armVizPointerUp);
    window.addEventListener('pointercancel', armVizPointerUp);
  }
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
  if (!document.getElementById('armVizCanvas')) return;
  armVizLoadGeometry();
  armVizBindPointer();
  armVizUpdateModeUI();
  if (armVizState.rafId != null) return;
  armVizResetView();
  armVizState.rafId = window.requestAnimationFrame(armVizLoop);
}

function getNeutral(name) {
  // Safety: 1500us is the dangerous default per CLAUDE.md. If we haven't
  // loaded server neutrals yet, return null so callers can refuse to move.
  if (!chNeutralLoaded) return null;
  return chNeutral[name] != null ? chNeutral[name] : null;
}

function getServoSpeed() {
  var el = document.getElementById('servoSpeed');
  return el ? parseInt(el.value) : 10;
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
        // Clamp to current slider max (was 200, now 10)
        var v = Math.min(parseInt(s.speed) || 10, 10);
        if (el) { el.value = v; updateServoSpeedLabel(v); }
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
  // Server-side ramp cares only about step-size-per-tick (getServoSpeed).
  fetch('/api/servo_speed', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({us_per_tick: getServoSpeed()})
  }).catch(function() {});
}

function usToDuty(us) {
  return (us / 20000 * 100).toFixed(1);
}

function chUpdateLabel(name, val) {
  var el = document.getElementById('chv_' + name);
  if (el) {
    el.textContent = val + ' us';
    el.title = usToDuty(val) + '% duty cycle';
  }
  var angleEl = document.getElementById('changle_' + name);
  if (angleEl) {
    var rad = pwToAngleRad(name, parseInt(val));
    angleEl.textContent = rad == null ? '--' : radToDeg(rad).toFixed(1) + '°';
  }
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
  chSendPwm(name, val);  // server-side ramp handles step-capping
}

function chGoNeutral(name) {
  var target = getNeutral(name);
  if (target == null) {
    alert('Neutral positions not loaded from server yet. Refusing to move ' + name + '.');
    return;
  }
  var slider = document.getElementById('ch_' + name);
  if (slider) { slider.value = target; chUpdateLabel(name, target); }
  // L3: assigning .value does not fire the input event, so publish explicitly.
  chSendPwm(name, target);
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
    if (name !== 'MACE') chGoNeutral(name);
  });
}

function startupNeutral() {
  if (!chNeutralLoaded) {
    alert('Neutral positions not loaded from server yet. Refusing STARTUP.');
    return;
  }
  chOrder.forEach(function(name) {
    if (name === 'MACE') return;
    var pw = getNeutral(name);
    if (pw == null) return;
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

/* Sync servo sliders from authoritative server-side ramp state.
   Reads /api/servo_state which returns {target, actual, ...}. If another
   client has set a different target, update our slider (unless user is
   actively dragging). chActual mirrors the live ramp position for display. */
var chFrozenState = false;
var chFreezeThresholdS = 0.8;  // matches server's 1.0s heartbeat timeout with headroom

function servoSetHwLabel(name, text, tone) {
  var el = document.getElementById('chhw_' + name);
  if (!el) return;
  el.textContent = text;
  el.className = 'servo-chip-value';
  if (tone) el.classList.add('servo-chip-value-' + tone);
}

function servoSyncPoll() {
  fetch('/api/servo_state').then(function(r) { return r.json(); }).then(function(state) {
    var target = state.target || {};
    var actual = state.actual || {};
    var hbAge = state.heartbeat_age_s || 0;
    var rampAge = state.ramp_age_s || 0;

    // H2: detect freeze/recovery edges. If we were frozen and the heartbeat
    // came back, force every slider to the current server target regardless
    // of whether the user was dragging. This prevents a mid-drag slider
    // from causing the arm to jump to the pre-freeze value on release.
    var nowFrozen = hbAge > chFreezeThresholdS;
    var recovering = chFrozenState && !nowFrozen;
    chFrozenState = nowFrozen;

    // C5: alarm if the ramp thread is not ticking. ramp_age > 1s means the
    // daemon thread has stopped; any slider move would be silently ignored.
    var rampDead = rampAge > 1.0;
    var disarmed = !!state.disarmed;
    var statusDot = document.getElementById('statusDot');
    if (statusDot) {
      if (rampDead) {
        statusDot.className = 'status-dot';
        statusDot.title = 'Servo ramp thread stopped - sliders disabled';
      } else if (disarmed) {
        statusDot.className = 'status-dot';
        statusDot.title = 'Servos DISARMED - POST /api/arm to resume';
      } else if (nowFrozen) {
        statusDot.className = 'status-dot warn';
        statusDot.title = 'Heartbeat lost - targets frozen';
      } else {
        statusDot.title = '';
      }
    }
    // Disable sliders when the ramp is dead OR the arms are disarmed.
    chOrder.forEach(function(name) {
      if (name === 'MACE') return;
      var sl = document.getElementById('ch_' + name);
      if (sl) sl.disabled = (rampDead || disarmed);
    });

    var hw = state.hardware || {};
    chOrder.forEach(function(name) {
      if (name === 'MACE') return;
      if (actual[name] != null) chActual[name] = actual[name];
      var hwVal = hw[name];
      if (hwVal == null) {
        servoSetHwLabel(name, '?', 'warn');
      } else if (hwVal === 0) {
        // PCA output is 0us = no PWM = servo unpowered. Almost always
        // a boot-restore that never happened; flag it loudly.
        servoSetHwLabel(name, '0 us ERROR', 'error');
      } else {
        var mismatch = actual[name] != null && Math.abs(hwVal - actual[name]) > 5;
        servoSetHwLabel(name, hwVal + ' us', mismatch ? 'error' : '');
      }
      if (target[name] == null) return;
      var slider = document.getElementById('ch_' + name);
      if (!slider) return;
      var isActive = slider.matches(':active');
      // During recovery we force-update even if the user is dragging.
      if (isActive && !recovering) return;
      var localVal = parseInt(slider.value);
      if (localVal !== target[name]) {
        slider.value = target[name];
        chUpdateLabel(name, target[name]);
      }
    });
  }).catch(function() {});
}

// L6: pull per-channel min/max PW envelope from the server and apply to the
// UI sliders so the user cannot drag into a physically unsafe range.
function applyServoLimits() {
  fetch('/api/servo_limits').then(function(r) { return r.json(); }).then(function(limits) {
    Object.keys(limits || {}).forEach(function(name) {
      var slider = document.getElementById('ch_' + name);
      if (!slider) return;
      var lim = limits[name];
      if (lim && lim.min != null) slider.min = lim.min;
      if (lim && lim.max != null) slider.max = lim.max;
    });
  }).catch(function() {});
}

/* Client-side ramp loop removed: the ramp now runs on the groundstation
   backend so network drops between browser and groundstation cannot cause
   servo jumps. The client only publishes slider targets via chSendPwm. */
function startServoRampLoop() { /* server-side now; stub kept for compatibility */ }

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
  h1.className = 'ch-column-head';
  h1.textContent = 'Arm 1';
  grid.appendChild(h1);
  var h2 = document.createElement('div');
  h2.className = 'ch-column-head';
  h2.textContent = 'Arm 2';
  grid.appendChild(h2);
  chOrder.forEach(function(name) {
    if (name === 'MACE') return;
    var item = document.createElement('div');
    item.id = 'chitem_' + name;
    item.className = 'ch-item';
    var neutralVal = getNeutral(name);
    item.innerHTML = '<div class="servo-row-head">' +
      '<div class="servo-name-block">' +
        '<div class="servo-name-line">' +
          '<span class="ch-name">' + name + '</span>' +
          '<span class="servo-channel-meta">ch ' + CHANNELS[name].ch + ' / pin ' + CHANNELS[name].pin + '</span>' +
        '</div>' +
        '<div class="servo-readout">' +
          '<span class="ch-val" id="chv_' + name + '">-- us</span>' +
          '<span id="changle_' + name + '" class="servo-angle-readout">--</span>' +
        '</div>' +
      '</div>' +
      '<div class="servo-chip-row">' +
        '<span class="servo-chip"><span class="servo-chip-label">Neutral</span><span id="chn_' + name + '" class="servo-chip-value">' + (neutralVal == null ? '--' : neutralVal + ' us') + '</span></span>' +
        '<span class="servo-chip servo-chip-hw"><span class="servo-chip-label">HW:</span><span id="chhw_' + name + '" class="servo-chip-value servo-chip-value-warn">--</span></span>' +
      '</div>' +
      '</div>' +
      '<div class="servo-slider-row">' +
      '<input type="range" id="ch_' + name + '" min="500" max="2500" step="10" value="1500" ' +
      'oninput="chSliderInput(&quot;' + name + '&quot;, this.value)"></div>' +
      '<div class="servo-row-actions">' +
      '<button class="btn btn-sm" onclick="chGoNeutral(&quot;' + name + '&quot;)">Go to Neutral</button>' +
      '<button class="btn btn-sm btn-red" onclick="chSetNeutral(&quot;' + name + '&quot;)" title="Save current position as neutral">Set Neutral</button>' +
      '</div>';
    grid.appendChild(item);

    setTimeout(function() {
      var sl = document.getElementById('ch_' + name);
      if (sl) preventSliderJump(sl);
    }, 0);
  });
})();

/* ========== Polling ========== */
function controllerUnavailableMessage() {
  return 'Controller backend unavailable on this deployment.';
}

function updateControllerUI(status) {
  controllerStatus = status || {enabled: false};
  var unavailable = controllerStatus.available === false;
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
    modeEl.textContent = unavailable ? 'UNAVAILABLE' : (controllerStatus.enabled ? 'ON' : 'OFF');
    modeEl.style.color = unavailable ? '#f59e0b' : (controllerStatus.enabled ? '#22c55e' : '#9ca3af');
  }
  if (linkEl) {
    linkEl.textContent = unavailable ? 'NOT INSTALLED' : (controllerStatus.connected ? 'CONNECTED' : 'DISCONNECTED');
    linkEl.style.color = unavailable ? '#f59e0b' : (controllerStatus.connected ? '#22c55e' : '#ef4444');
  }
  if (armEl) {
    armEl.textContent = unavailable ? '--' : (controllerStatus.selected_arm || "left").toUpperCase();
    armEl.style.color = unavailable ? '#9ca3af' : '#f59e0b';
  }
  if (leftBtn) {
    leftBtn.className = (!unavailable && controllerStatus.selected_arm === "left") ? "btn btn-amber" : "btn btn-dark";
    leftBtn.disabled = unavailable;
  }
  if (rightBtn) {
    rightBtn.className = (!unavailable && controllerStatus.selected_arm === "right") ? "btn btn-amber" : "btn btn-dark";
    rightBtn.disabled = unavailable;
  }
  if (deadmanEl) {
    deadmanEl.textContent = unavailable ? '--' : (controllerStatus.deadman ? 'HELD' : 'RELEASED');
    deadmanEl.style.color = unavailable ? '#9ca3af' : (controllerStatus.deadman ? '#22c55e' : '#9ca3af');
  }
  if (activeEl) {
    activeEl.textContent = unavailable ? '--' : (controllerStatus.active ? 'MOVING' : 'IDLE');
    activeEl.style.color = unavailable ? '#9ca3af' : (controllerStatus.active ? '#3b82f6' : '#9ca3af');
  }
  if (errorEl) {
    var errorText = unavailable ? (controllerStatus.last_error || controllerUnavailableMessage()) : (controllerStatus.last_error || '');
    errorEl.textContent = errorText;
    errorEl.style.color = unavailable ? '#f59e0b' : '#ef4444';
    errorEl.style.display = errorText ? 'block' : 'none';
  }
  if (btn) {
    btn.textContent = unavailable ? 'CONTROLLER OFFLINE' : (controllerStatus.enabled ? 'DISABLE CONTROLLER' : 'ENABLE CONTROLLER');
    btn.className = unavailable ? 'btn btn-dark' : (controllerStatus.enabled ? 'btn btn-red' : 'btn btn-dark');
    btn.disabled = unavailable;
  }
}

function controllerPoll() {
  fetch('/api/controller/status').then(function(r) { return r.json(); }).then(function(d) {
    updateControllerUI(d);
  }).catch(function() {});
}

function setControllerArm(selectedArm) {
  if (controllerStatus.available === false) return;
  fetch('/api/controller/arm', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({selected_arm: selectedArm})
  }).then(function(r) { return r.json(); }).then(function(d) {
    updateControllerUI(d);
  });
}

function toggleControllerMode() {
  if (controllerStatus.available === false) return;
  var enable = !controllerStatus.enabled;
  fetch('/api/controller/enable', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({enabled: enable})
  }).then(function(r) { return r.json(); }).then(function(d) {
    updateControllerUI(d);
  });
}

var maceJogActive = null;
var maceJogActiveToken = null;
var maceJogHeartbeatTimer = null;
var maceJogReady = false;
var maceJogCalibrating = false;
var maceJogPendingDirection = null;
var maceJogPendingToken = null;
var maceJogRequestSeq = 0;
var maceJogTokenSeq = 0;
var maceHoldPointerId = null;
var MACE_DEFAULT_ACCEL_RAMP = 2000.0;
var MACE_DEFAULT_BRAKE_RAMP = 2000.0;
var MACE_DEFAULT_MAX_VOLTAGE = 24.0;

function maceApplyDefaultSettings() {
  var accel = document.getElementById('maceAccelRamp');
  var brake = document.getElementById('maceBrakeRamp');
  var volt = document.getElementById('maceVoltage');
  if (accel) accel.value = String(MACE_DEFAULT_ACCEL_RAMP);
  if (brake) brake.value = String(MACE_DEFAULT_BRAKE_RAMP);
  if (volt) volt.value = String(MACE_DEFAULT_MAX_VOLTAGE);
}

function maceCfg() {
  return {
    accel_ramp: parseFloat(document.getElementById('maceAccelRamp').value || String(MACE_DEFAULT_ACCEL_RAMP)) || MACE_DEFAULT_ACCEL_RAMP,
    brake_ramp: parseFloat(document.getElementById('maceBrakeRamp').value || String(MACE_DEFAULT_BRAKE_RAMP)) || MACE_DEFAULT_BRAKE_RAMP,
    max_voltage: parseFloat(document.getElementById('maceVoltage').value || String(MACE_DEFAULT_MAX_VOLTAGE)) || MACE_DEFAULT_MAX_VOLTAGE
  };
}

function maceUpdateLabels() {
  var cfg = maceCfg();
  var accel = document.getElementById('maceAccelRampVal');
  var brake = document.getElementById('maceBrakeRampVal');
  var volt = document.getElementById('maceVoltageVal');
  if (accel) accel.textContent = cfg.accel_ramp.toFixed(1) + ' rad/s²';
  if (brake) brake.textContent = cfg.brake_ramp.toFixed(1) + ' rad/s²';
  if (volt) volt.textContent = cfg.max_voltage.toFixed(1) + ' V';
}

function maceSetButtons(active) {
  var map = {
    backward: document.getElementById('maceBackwardBtn'),
    brake: document.getElementById('maceBrakeBtn'),
    forward: document.getElementById('maceForwardBtn')
  };
  Object.keys(map).forEach(function(key) {
    var btn = map[key];
    if (!btn) return;
    if (active === key) btn.classList.add('active');
    else btn.classList.remove('active');
  });
}

function maceSetHoldEnabled(enabled) {
  ['maceBackwardBtn', 'maceBrakeBtn', 'maceForwardBtn'].forEach(function(id) {
    var btn = document.getElementById(id);
    if (!btn) return;
    btn.disabled = !enabled;
  });
}

function maceSendHeartbeat(direction, holdToken) {
  var body = {direction: direction};
  if (holdToken != null) body.hold_token = holdToken;
  return fetch('/api/mace/jog/heartbeat', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(body)
  });
}

function maceStartHeartbeat(direction, holdToken) {
  if (maceJogHeartbeatTimer) clearInterval(maceJogHeartbeatTimer);
  maceSendHeartbeat(direction, holdToken).catch(function() {});
  maceJogHeartbeatTimer = setInterval(function() {
    maceSendHeartbeat(direction, holdToken).catch(function() {});
  }, 100);
}

function maceStopHeartbeat() {
  if (maceJogHeartbeatTimer) clearInterval(maceJogHeartbeatTimer);
  maceJogHeartbeatTimer = null;
}

function maceJogStart(direction) {
  if (!maceJogReady || maceJogCalibrating) return;
  var holdToken = String(++maceJogTokenSeq);
  maceJogPendingDirection = direction;
  maceJogPendingToken = holdToken;
  maceSetButtons(direction);
  maceStartHeartbeat(direction, holdToken);
  var reqSeq = ++maceJogRequestSeq;
  var cfg = maceCfg();
  fetch('/api/mace/jog/start', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({
      direction: direction,
      hold_token: holdToken,
      accel_ramp: cfg.accel_ramp,
      brake_ramp: cfg.brake_ramp,
      max_voltage: cfg.max_voltage
    })
  }).then(function(r) { return r.json(); }).then(function(d) {
    var note = document.getElementById('maceJogNote');
    if (reqSeq !== maceJogRequestSeq || maceJogPendingDirection !== direction || maceJogPendingToken !== holdToken) {
      fetch('/api/mace/jog/stop', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({hold_token: holdToken})
      }).catch(function() {});
      return;
    }
    if (d.ok === false) {
      if (maceJogPendingToken !== holdToken && maceJogActiveToken !== holdToken) return;
      if (note) note.textContent = d.error || 'MACE jog start failed';
      if (maceJogPendingToken === holdToken) {
        maceJogPendingToken = null;
        maceJogPendingDirection = null;
      }
      if (maceJogActiveToken === holdToken) {
        maceJogActiveToken = null;
        maceJogActive = null;
      }
      maceSetButtons(null);
      maceStopHeartbeat();
      return;
    }
    maceJogActive = direction;
    maceJogActiveToken = holdToken;
    maceJogPendingDirection = null;
    maceJogPendingToken = null;
    maceSetButtons(direction);
    maceRenderStatus(d);
  }).catch(function(err) {
    if (maceJogPendingToken !== holdToken && maceJogActiveToken !== holdToken) return;
    var note = document.getElementById('maceJogNote');
    if (note) note.textContent = 'MACE jog start failed: ' + err;
    if (maceJogPendingToken === holdToken) {
      maceJogPendingToken = null;
      maceJogPendingDirection = null;
    }
    if (maceJogActiveToken === holdToken) {
      maceJogActiveToken = null;
      maceJogActive = null;
    }
    maceSetButtons(null);
    maceStopHeartbeat();
  });
}

function maceCalibrate() {
  if (maceJogCalibrating) return;
  var note = document.getElementById('maceJogNote');
  fetch('/api/mace/calibrate', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({})
  }).then(function(r) { return r.json(); }).then(function(d) {
    maceRenderStatus(d);
    if (!d.ok && note) note.textContent = d.error || 'Calibration failed';
  }).catch(function(err) {
    if (note) note.textContent = 'Calibration failed: ' + err;
  });
}

function maceJogStop(holdToken) {
  var stopToken = holdToken || maceJogPendingToken || maceJogActiveToken;
  if (!stopToken && !maceJogActive && !maceJogPendingDirection) return;
  maceJogRequestSeq += 1;
  if (stopToken && maceJogPendingToken === stopToken) {
    maceJogPendingToken = null;
    maceJogPendingDirection = null;
  } else if (!holdToken) {
    maceJogPendingDirection = null;
  }
  if (stopToken && maceJogActiveToken === stopToken) {
    maceJogActiveToken = null;
    maceJogActive = null;
  } else if (!stopToken) {
    maceJogActive = null;
  }
  maceStopHeartbeat();
  maceSetButtons(null);
  fetch('/api/mace/jog/stop', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(stopToken ? {hold_token: stopToken} : {})
  }).then(function(r) { return r.json(); }).then(function(d) {
    maceRenderStatus(d);
  }).catch(function(err) {
    var note = document.getElementById('maceJogNote');
    if (note) note.textContent = 'MACE jog stop failed: ' + err;
  });
}

function maceReleaseAll() {
  if (!maceJogActive && !maceJogPendingDirection && !maceJogActiveToken && !maceJogPendingToken) return;
  maceJogStop(maceJogPendingToken || maceJogActiveToken);
}

function maceReleasePointer(ev) {
  if (maceHoldPointerId === null) return;
  if (ev && ev.pointerId != null && ev.pointerId !== maceHoldPointerId) return;
  maceHoldPointerId = null;
  maceReleaseAll();
}

function maceRenderStatus(d) {
  d = d || {};
  var status = document.getElementById('maceJogStatus');
  var cal = document.getElementById('maceCalStatus');
  var link = document.getElementById('maceJogLink');
  var target = document.getElementById('maceJogTarget');
  var rpm = document.getElementById('maceJogRpm');
  var note = document.getElementById('maceJogNote');
  var calBtn = document.getElementById('maceCalibrateBtn');
  maceJogReady = !!d.foc_ready;
  maceJogCalibrating = !!d.calibrating;
  maceSetHoldEnabled(maceJogReady && !maceJogCalibrating);
  if (status) status.textContent = (d.active || 'idle').toUpperCase() + ' / ' + String(d.status || 'idle').toUpperCase();
  if (cal) {
    if (maceJogCalibrating) cal.textContent = 'CALIBRATING';
    else cal.textContent = maceJogReady ? 'READY' : 'NOT READY';
    cal.style.color = maceJogCalibrating ? '#f59e0b' : (maceJogReady ? '#22c55e' : '#ef4444');
  }
  if (link) {
    var connected = !!d.connected;
    link.textContent = connected ? 'CONNECTED' : 'DISCONNECTED';
    link.style.color = connected ? '#22c55e' : '#ef4444';
  }
  if (target) {
    var val = Number(d.simplefoc_target || 0);
    target.textContent = val.toFixed(2) + ' rad/s';
  }
  if (rpm) {
    // Wheel RPM only. Body RPM (Pi I2C encoder) is a different sensor and
    // belongs on the main Encoder card, not here.
    if (d.wheel_rpm == null) rpm.textContent = '--';
    else rpm.textContent = Number(d.wheel_rpm).toFixed(1);
  }
  if (calBtn) calBtn.disabled = maceJogCalibrating || !d.connected;
  if (note) {
    if (d.error) note.textContent = d.error;
    else if (d.calibration_error) note.textContent = d.calibration_error;
    else if (maceJogCalibrating) note.textContent = 'Calibration running. Wait for READY before using hold controls.';
    else if (!maceJogReady) note.textContent = 'Click CALIBRATE before using the wheel controls.';
    else note.textContent = d.active ? ('Holding ' + d.active.toUpperCase() + '. Release to coast.') : 'Release any button to coast. Hold BRAKE for active stop.';
  }
}

function maceStatusPoll() {
  // Display-only. Do NOT mutate maceJogActive from the server snapshot:
  // the browser is authoritative about "finger is down", and the GEO-DUDe
  // watchdog is authoritative about "motor is coasting". Nulling local
  // state from a stale poll cancels live holds mid-press.
  fetch('/api/mace/jog/status').then(function(r) { return r.json(); }).then(function(d) {
    maceRenderStatus(d);
  }).catch(function() {});
}

function maceBindMomentaryButton(id, direction) {
  var btn = document.getElementById(id);
  if (!btn) return;
  var activePointerId = null;
  function press(ev) {
    if (ev) ev.preventDefault();
    if (btn.disabled) return;
    if (activePointerId !== null) return;
    activePointerId = ev && ev.pointerId != null ? ev.pointerId : 'mouse';
    maceHoldPointerId = activePointerId;
    if (ev && ev.pointerId != null && btn.setPointerCapture) btn.setPointerCapture(ev.pointerId);
    if (maceJogActive && maceJogActive !== direction) maceJogStop();
    if (maceJogActive === direction || maceJogPendingDirection === direction) return;
    maceJogStart(direction);
  }
  function release(ev) {
    if (ev) ev.preventDefault();
    if (activePointerId === null) return;
    if (ev && ev.pointerId != null && ev.pointerId !== activePointerId) return;
    if (ev && ev.pointerId != null && btn.releasePointerCapture) {
      try { btn.releasePointerCapture(ev.pointerId); } catch (e) {}
    }
    if (maceHoldPointerId === activePointerId) maceHoldPointerId = null;
    activePointerId = null;
    if (maceJogActive === direction || maceJogPendingDirection === direction) maceJogStop();
  }
  btn.addEventListener('pointerdown', press);
  btn.addEventListener('pointerup', release);
  btn.addEventListener('pointercancel', release);
}

function poll() {
  fetch('/api/sensors').then(function(r) { return r.json(); }).then(function(d) {
    /* Gyro */
    document.getElementById('gx').textContent = d.gyro.x.toFixed(1);
    document.getElementById('gy').textContent = d.gyro.y.toFixed(1);
    document.getElementById('gz').textContent = d.gyro.z.toFixed(1);
    /* Accel (removed from UI) */
    /* Encoder */
    var angle = d.encoder_angle;
    document.getElementById('angleText').innerHTML = angle.toFixed(1) + '&deg;';
    document.getElementById('rpmText').textContent = d.rpm;
    var needleAngle = (angle % 360);
    document.getElementById('needle').style.transform = 'rotate(' + needleAngle + 'deg)';
    var analog = d.analog_encoder || {};
    var analogVa = document.getElementById('analogVaText');
    var analogVb = document.getElementById('analogVbText');
    if (analogVa) analogVa.textContent = Number(analog.va || 0).toFixed(3);
    if (analogVb) analogVb.textContent = Number(analog.vb || 0).toFixed(3);
    /* Arm state */
    /* Status */
    var armed = !!d.armed;
    var target = Number(d.target || 0);
    var throttle = Number(d.throttle || 0);
    var reverse = !!d.reverse;
    var armedStatus = document.getElementById('armedStatus');
    if (armedStatus) {
      armedStatus.textContent = armed ? 'YES' : 'NO';
      armedStatus.style.color = armed ? '#22c55e' : '#ef4444';
    }
    var targetStatus = document.getElementById('targetStatus');
    if (targetStatus) targetStatus.textContent = target.toFixed(1) + '%';
    var throttleStatus = document.getElementById('throttleStatus');
    if (throttleStatus) throttleStatus.textContent = throttle.toFixed(1) + '%';
    var pw = reverse ? (1000 - Math.round(throttle) * 10) : (1000 + Math.round(throttle) * 10);
    var pwmStatus = document.getElementById('pwmStatus');
    if (pwmStatus) pwmStatus.textContent = pw + ' us';
    var dirStatus = document.getElementById('dirStatus');
    if (dirStatus) {
      dirStatus.textContent = reverse ? 'REV' : 'FWD';
      dirStatus.style.color = reverse ? '#f59e0b' : '#22c55e';
    }
    // Wheel RPM comes from the Nucleo encoder via /api/mace/jog/status, not
    // from the Pi's I2C body-encoder /api/sensors feed. Do NOT write it here.
    /* Throttle bars */
    var targetBar = document.getElementById('targetBar');
    var currentBar = document.getElementById('currentBar');
    if (targetBar) targetBar.style.width = target + '%';
    if (currentBar) currentBar.style.width = throttle + '%';
    /* Motor error */
    var errDiv = document.getElementById('motorError');
    if (errDiv) {
      if (d.motor_error) {
        errDiv.textContent = d.motor_error;
        errDiv.style.display = 'block';
      } else {
        errDiv.textContent = '';
        errDiv.style.display = 'none';
      }
    }
    /* Connection dot - green only if GEO-DUDe Pi is actually reachable */
    var dot = document.getElementById('statusDot');
    if (dot) dot.className = d.connected ? 'status-dot ok' : 'status-dot';
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
var GIMBAL_POLL_MS = 250;
var gimbalSetupDone = false;
var gimbalDriverCache = [];

function wrapDegrees360(deg) {
  var wrapped = deg % 360;
  if (wrapped < 0) wrapped += 360;
  return wrapped;
}

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

function gimbalSetZero(driver) {
  fetch('/api/gimbal/set_zero', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({driver: driver})
  }).then(function() {
    gimbalPoll();
  });
}

function gimbalClearZero(driver) {
  fetch('/api/gimbal/clear_zero', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({driver: driver})
  }).then(function() {
    gimbalPoll();
  });
}

function gimbalGoZero(driver) {
  fetch('/api/gimbal/go_zero', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({driver: driver})
  }).then(function() {
    gimbalPoll();
  });
}

function gimbalTumbleStart(driver) {
  var aEl = document.getElementById('motorTumbleA_' + driver);
  var bEl = document.getElementById('motorTumbleB_' + driver);
  var dwellEl = document.getElementById('motorTumbleDwell_' + driver);
  if (!aEl || !bEl || !dwellEl) return;
  var aValue = parseFloat(aEl.value);
  var bValue = parseFloat(bEl.value);
  var dwellMS = Math.round(parseFloat(dwellEl.value));
  if (!isFinite(aValue) || !isFinite(bValue) || !isFinite(dwellMS)) {
    document.getElementById('gimbalStatus').textContent = 'Tumble error: enter A, B, and dwell';
    return;
  }
  fetch('/api/gimbal/tumble_start', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({driver: driver, a: aValue, b: bValue, dwell_ms: dwellMS})
  }).then(function(r) {
    return r.json().then(function(d) { return {ok: r.ok, data: d}; });
  }).then(function(res) {
    if (!res.ok || !res.data || res.data.ok === false) {
      document.getElementById('gimbalStatus').textContent = 'Tumble error: ' + ((res.data && res.data.error) || 'unknown');
      gimbalPoll();
      return;
    }
    gimbalClearTumbleDraft(driver);
    gimbalPoll();
  }).catch(function(e) {
    document.getElementById('gimbalStatus').textContent = 'Tumble error: ' + e;
  });
}

function gimbalTumbleStop(driver) {
  fetch('/api/gimbal/tumble_stop', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({driver: driver})
  }).then(function() {
    gimbalPoll();
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

function gimbalSetMotorSpeed(driver, us) {
  us = parseInt(us);
  var label = document.getElementById('motorSpeedLabel_' + driver);
  if (label) label.textContent = us + ' us';
  fetch('/api/gimbal/motor_speed', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({driver: driver, us: us})
  });
}

function gimbalSetMotorRamp(driver, steps) {
  steps = parseInt(steps);
  var label = document.getElementById('motorRampLabel_' + driver);
  if (label) label.textContent = steps + ' steps';
  fetch('/api/gimbal/motor_ramp', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({driver: driver, steps: steps})
  });
}

function gimbalSetMotorStealthChop(driver, enabled) {
  fetch('/api/gimbal/motor_stealthchop', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({driver: driver, enabled: !!enabled})
  });
}

function gimbalSetMotorInterpolation(driver, enabled) {
  fetch('/api/gimbal/motor_interpolation', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({driver: driver, enabled: !!enabled})
  });
}

function gimbalSetMotorMultistepFilt(driver, enabled) {
  fetch('/api/gimbal/motor_multistep_filt', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({driver: driver, enabled: !!enabled})
  });
}

function gimbalUsesStepLimits(drv, driver) {
  if (drv && drv.limit_units) return drv.limit_units === 'steps';
  var name = (drv && drv.name) || GIMBAL_DRIVER_NAMES[driver] || '';
  return name.toLowerCase() === 'belt';
}

function gimbalDriverSupportsLimits(drv, driver) {
  if (drv && typeof drv.limits_supported === 'boolean') return drv.limits_supported;
  var name = (drv && drv.name) || GIMBAL_DRIVER_NAMES[driver] || '';
  return name.toLowerCase() !== 'roll';
}

function gimbalDriverSupportsTumble(drv, driver) {
  if (drv && typeof drv.tumble_supported === 'boolean') return drv.tumble_supported;
  var name = (drv && drv.name) || GIMBAL_DRIVER_NAMES[driver] || '';
  return name.toLowerCase() !== 'belt';
}

function gimbalFormatLimitValue(drv, driver, value) {
  if (value == null || isNaN(value)) return '';
  return gimbalUsesStepLimits(drv, driver) ? String(Math.round(value)) : Number(value).toFixed(1);
}

function gimbalFormatTumbleValue(value) {
  if (value == null || isNaN(value)) return '';
  return Number(value).toFixed(1);
}

function gimbalLimitInputStep(drv, driver) {
  return gimbalUsesStepLimits(drv, driver) ? '1' : '0.1';
}

var gimbalLimitDrafts = {};

function gimbalEnsureLimitDraft(driver) {
  if (!gimbalLimitDrafts[driver]) {
    gimbalLimitDrafts[driver] = {
      minDirty: false,
      maxDirty: false,
      minValue: '',
      maxValue: ''
    };
  }
  return gimbalLimitDrafts[driver];
}

function gimbalLimitDraft(driver, field, value) {
  var draft = gimbalEnsureLimitDraft(driver);
  if (field === 'min') {
    draft.minDirty = true;
    draft.minValue = value;
  } else if (field === 'max') {
    draft.maxDirty = true;
    draft.maxValue = value;
  }
}

function gimbalClearLimitDraft(driver) {
  delete gimbalLimitDrafts[driver];
}

var gimbalTumbleDrafts = {};

function gimbalEnsureTumbleDraft(driver) {
  if (!gimbalTumbleDrafts[driver]) {
    gimbalTumbleDrafts[driver] = {
      aDirty: false,
      bDirty: false,
      dwellDirty: false,
      aValue: '',
      bValue: '',
      dwellValue: ''
    };
  }
  return gimbalTumbleDrafts[driver];
}

function gimbalTumbleDraft(driver, field, value) {
  var draft = gimbalEnsureTumbleDraft(driver);
  if (field === 'a') {
    draft.aDirty = true;
    draft.aValue = value;
  } else if (field === 'b') {
    draft.bDirty = true;
    draft.bValue = value;
  } else if (field === 'dwell') {
    draft.dwellDirty = true;
    draft.dwellValue = value;
  }
}

function gimbalClearTumbleDraft(driver) {
  delete gimbalTumbleDrafts[driver];
}

function gimbalTumbleStateText(drv, driver) {
  if (!gimbalDriverSupportsTumble(drv, driver)) return '';
  var stateLabels = {
    off: 'OFF',
    to_a: 'TO A',
    dwell_a: 'DWELL A',
    to_b: 'TO B',
    dwell_b: 'DWELL B'
  };
  var parts = [stateLabels[drv.tumble_state] || 'OFF'];
  if (drv.tumble_a != null && drv.tumble_b != null) {
    parts.push(gimbalFormatTumbleValue(drv.tumble_a) + '\u00b0 \u2194 ' + gimbalFormatTumbleValue(drv.tumble_b) + '\u00b0');
  }
  if (drv.tumble_dwell_ms != null) {
    parts.push('dwell ' + drv.tumble_dwell_ms + ' ms');
  }
  if (!drv.position_trusted) {
    parts.push('waiting for trusted zero');
  } else if (!drv.enabled) {
    parts.push('enable axis to start');
  }
  return parts.join(' | ');
}

function gimbalSetMotorLimits(driver) {
  var drv = (gimbalDriverCache && gimbalDriverCache[driver]) || null;
  if (!gimbalDriverSupportsLimits(drv, driver)) {
    document.getElementById('gimbalStatus').textContent = 'Roll has no soft limits';
    return;
  }
  var minEl = document.getElementById('motorLimitMin_' + driver);
  var maxEl = document.getElementById('motorLimitMax_' + driver);
  if (!minEl || !maxEl) return;
  var minValue = parseFloat(minEl.value);
  var maxValue = parseFloat(maxEl.value);
  if (!isFinite(minValue) || !isFinite(maxValue)) {
    document.getElementById('gimbalStatus').textContent = 'Limit error: enter both min and max';
    return;
  }
  fetch('/api/gimbal/motor_limits', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({driver: driver, min: minValue, max: maxValue})
  }).then(function(r) {
    return r.json().then(function(d) { return {ok: r.ok, data: d}; });
  }).then(function(res) {
    if (!res.ok || !res.data || res.data.ok === false) {
      document.getElementById('gimbalStatus').textContent = 'Limit error: ' + ((res.data && res.data.error) || 'unknown');
      gimbalPoll();
      return;
    }
    gimbalClearLimitDraft(driver);
    gimbalPoll();
  }).catch(function(e) {
    document.getElementById('gimbalStatus').textContent = 'Limit error: ' + e;
  });
}

function gimbalPositionReasonText(reason, trusted) {
  if (trusted) return 'TRUSTED';
  if (reason === 'power_loss') return 'UNTRUSTED - 24V cycled';
  if (reason === 'disabled') return 'UNTRUSTED - driver disabled';
  if (reason === 'estop') return 'UNTRUSTED - estop';
  if (reason === 'cleared') return 'UNTRUSTED - zero cleared';
  return 'UNTRUSTED - set zero manually';
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
    statusParts.push('Setup: ' + (gimbalSetupDone ? 'YES' : 'NO'));
    document.getElementById('gimbalStatus').textContent = statusParts.join(' | ');

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
        var isRoll = (driverName.toLowerCase() === 'roll');
        var rampMax = (isBelt || isRoll) ? 5000 : 2000;
        var supportsLimits = gimbalDriverSupportsLimits(drv, i);
        var supportsTumble = gimbalDriverSupportsTumble(drv, i);
        var limitUnits = drv.limit_units || (isBelt ? 'steps' : 'deg');
        var limitMin = gimbalFormatLimitValue(drv, i, drv.soft_limit_min != null ? drv.soft_limit_min : drv.hard_limit_min);
        var limitMax = gimbalFormatLimitValue(drv, i, drv.soft_limit_max != null ? drv.soft_limit_max : drv.hard_limit_max);
        var hardMin = gimbalFormatLimitValue(drv, i, drv.hard_limit_min);
        var hardMax = gimbalFormatLimitValue(drv, i, drv.hard_limit_max);
        var limitStep = gimbalLimitInputStep(drv, i);
        var tumbleA = gimbalFormatTumbleValue(drv.tumble_a != null ? drv.tumble_a : -45.0);
        var tumbleB = gimbalFormatTumbleValue(drv.tumble_b != null ? drv.tumble_b : 45.0);
        var tumbleDwell = (drv.tumble_dwell_ms != null ? drv.tumble_dwell_ms : 500);

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
        html += '<div class="driver-debug" id="driverDebug_' + i + '"></div>';

        /* Current sliders */
        html += '<div class="motor-slider-group">';
        html += '<div class="motor-slider-label"><span class="label">Run Current</span><span class="value" id="motorRunLabel_' + i + '">' + (drv.current_ma || 400) + ' mA</span></div>';
        html += '<input type="range" id="motorRunSlider_' + i + '" min="50" max="2000" step="50" value="' + (drv.current_ma || 400) + '" oninput="gimbalSetMotorCurrent(' + i + ', this.value)">';
        html += '</div>';
        html += '<div class="motor-slider-group">';
        html += '<div class="motor-slider-label"><span class="label">Idle Current</span><span class="value" id="motorIholdLabel_' + i + '">' + (drv.ihold_ma || 0) + ' mA</span></div>';
        html += '<input type="range" id="motorIholdSlider_' + i + '" min="0" max="2000" step="10" value="' + (drv.ihold_ma || 0) + '" oninput="gimbalSetMotorIhold(' + i + ', this.value)">';
        html += '</div>';
        html += '<div class="motor-slider-group">';
        html += '<div class="motor-slider-label"><span class="label">Speed</span><span class="value" id="motorSpeedLabel_' + i + '">' + (drv.step_delay_us || 2000) + ' us</span></div>';
        html += '<input type="range" id="motorSpeedSlider_' + i + '" min="100" max="8000" step="50" value="' + (drv.step_delay_us || 2000) + '" oninput="gimbalSetMotorSpeed(' + i + ', this.value)">';
        html += '</div>';
        html += '<div class="motor-slider-group">';
        html += '<div class="motor-slider-label"><span class="label">Ramp</span><span class="value" id="motorRampLabel_' + i + '">' + (drv.ramp_steps || 0) + ' steps</span></div>';
        html += '<input type="range" id="motorRampSlider_' + i + '" min="0" max="' + rampMax + '" step="10" value="' + (drv.ramp_steps || 0) + '" oninput="gimbalSetMotorRamp(' + i + ', this.value)">';
        html += '</div>';
        html += '<div class="motor-mode-row">';
        html += '<div class="motor-mode-toggle"><span class="label">StealthChop</span><label class="toggle-switch"><input type="checkbox" id="motorStealthToggle_' + i + '"' + (drv.stealthchop !== false ? ' checked' : '') + ' onchange="gimbalSetMotorStealthChop(' + i + ', this.checked)"><span class="toggle-slider"></span></label></div>';
        html += '<div class="motor-mode-toggle"><span class="label">Interpolation</span><label class="toggle-switch"><input type="checkbox" id="motorInterpToggle_' + i + '"' + (drv.interpolation !== false ? ' checked' : '') + ' onchange="gimbalSetMotorInterpolation(' + i + ', this.checked)"><span class="toggle-slider"></span></label></div>';
        html += '<div class="motor-mode-toggle"><span class="label">Multi-Step Filter</span><label class="toggle-switch"><input type="checkbox" id="motorMsfToggle_' + i + '"' + (drv.multistep_filt !== false ? ' checked' : '') + ' onchange="gimbalSetMotorMultistepFilt(' + i + ', this.checked)"><span class="toggle-slider"></span></label></div>';
        html += '</div>';

        if (!isBelt) {
          /* Angle control */
          html += '<div class="motor-position-label">Position</div>';
          html += '<div class="motor-position" id="motorPos_' + i + '">UNTRUSTED</div>';
          html += '<div class="motor-position-note" id="motorPosState_' + i + '">UNTRUSTED - set zero manually</div>';
          html += '<div class="motor-zero-row">';
          html += '<button class="btn btn-sm" id="motorSetZeroBtn_' + i + '" onclick="gimbalSetZero(' + i + ')">SET ZERO</button>';
          html += '<button class="btn btn-sm btn-dark" id="motorGoZeroBtn_' + i + '" onclick="gimbalGoZero(' + i + ')">GO ZERO</button>';
          html += '<button class="btn btn-sm btn-dark" id="motorClearZeroBtn_' + i + '" onclick="gimbalClearZero(' + i + ')">UNTRUST</button>';
          html += '</div>';
          html += '<div class="gear-info" id="gearInfo_' + i + '"></div>';
          if (supportsLimits) {
            html += '<div class="motor-limit-group">';
            html += '<div class="motor-position-label">Soft Limits</div>';
            html += '<div class="motor-limit-row">';
            html += '<label class="motor-limit-field"><span>Min</span><input type="number" id="motorLimitMin_' + i + '" step="' + limitStep + '" value="' + limitMin + '" oninput="gimbalLimitDraft(' + i + ', &quot;min&quot;, this.value)"></label>';
            html += '<label class="motor-limit-field"><span>Max</span><input type="number" id="motorLimitMax_' + i + '" step="' + limitStep + '" value="' + limitMax + '" oninput="gimbalLimitDraft(' + i + ', &quot;max&quot;, this.value)"></label>';
            html += '<button class="btn btn-sm btn-dark" id="motorLimitSaveBtn_' + i + '" onclick="gimbalSetMotorLimits(' + i + ')">APPLY</button>';
            html += '</div>';
            html += '<div class="motor-limit-note" id="motorLimitNote_' + i + '">Hard ' + hardMin + ' to ' + hardMax + ' ' + limitUnits + ' from zero</div>';
            html += '</div>';
          }
          if (supportsTumble) {
            html += '<div class="motor-limit-group">';
            html += '<div class="motor-position-label">Tumble</div>';
            html += '<div class="motor-limit-row">';
            html += '<label class="motor-limit-field"><span>A</span><input type="number" id="motorTumbleA_' + i + '" step="0.1" value="' + tumbleA + '" oninput="gimbalTumbleDraft(' + i + ', &quot;a&quot;, this.value)"></label>';
            html += '<label class="motor-limit-field"><span>B</span><input type="number" id="motorTumbleB_' + i + '" step="0.1" value="' + tumbleB + '" oninput="gimbalTumbleDraft(' + i + ', &quot;b&quot;, this.value)"></label>';
            html += '<button class="btn btn-sm btn-dark" id="motorTumbleStartBtn_' + i + '" onclick="gimbalTumbleStart(' + i + ')">START</button>';
            html += '</div>';
            html += '<div class="motor-limit-row" style="margin-top:6px;">';
            html += '<label class="motor-limit-field"><span>Dwell ms</span><input type="number" id="motorTumbleDwell_' + i + '" min="0" max="600000" step="50" value="' + tumbleDwell + '" oninput="gimbalTumbleDraft(' + i + ', &quot;dwell&quot;, this.value)"></label>';
            html += '<div></div>';
            html += '<button class="btn btn-sm btn-red" id="motorTumbleStopBtn_' + i + '" onclick="gimbalTumbleStop(' + i + ')">STOP</button>';
            html += '</div>';
            html += '<div class="motor-limit-note" id="motorTumbleNote_' + i + '">' + gimbalTumbleStateText(drv, i) + '</div>';
            html += '</div>';
          }
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
          html += '<div class="motor-position-label">Position</div>';
          html += '<div class="motor-position" id="motorPos_' + i + '">UNTRUSTED</div>';
          html += '<div class="motor-position-note" id="motorPosState_' + i + '">UNTRUSTED - set zero manually</div>';
          html += '<div class="motor-zero-row">';
          html += '<button class="btn btn-sm" id="motorSetZeroBtn_' + i + '" onclick="gimbalSetZero(' + i + ')">SET ZERO</button>';
          html += '<button class="btn btn-sm btn-dark" id="motorGoZeroBtn_' + i + '" onclick="gimbalGoZero(' + i + ')">GO ZERO</button>';
          html += '<button class="btn btn-sm btn-dark" id="motorClearZeroBtn_' + i + '" onclick="gimbalClearZero(' + i + ')">UNTRUST</button>';
          html += '</div>';
          if (supportsLimits) {
            html += '<div class="motor-limit-group">';
            html += '<div class="motor-position-label">Soft Limits</div>';
            html += '<div class="motor-limit-row">';
            html += '<label class="motor-limit-field"><span>Min</span><input type="number" id="motorLimitMin_' + i + '" step="' + limitStep + '" value="' + limitMin + '" oninput="gimbalLimitDraft(' + i + ', &quot;min&quot;, this.value)"></label>';
            html += '<label class="motor-limit-field"><span>Max</span><input type="number" id="motorLimitMax_' + i + '" step="' + limitStep + '" value="' + limitMax + '" oninput="gimbalLimitDraft(' + i + ', &quot;max&quot;, this.value)"></label>';
            html += '<button class="btn btn-sm btn-dark" id="motorLimitSaveBtn_' + i + '" onclick="gimbalSetMotorLimits(' + i + ')">APPLY</button>';
            html += '</div>';
            html += '<div class="motor-limit-note" id="motorLimitNote_' + i + '">Hard ' + hardMin + ' to ' + hardMax + ' ' + limitUnits + ' from zero</div>';
            html += '</div>';
          }
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
      var supportsTumble = gimbalDriverSupportsTumble(drv, i);

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
      var setZeroBtn = document.getElementById('motorSetZeroBtn_' + i);
      if (setZeroBtn) setZeroBtn.disabled = !!drv.running;
      var goZeroBtn = document.getElementById('motorGoZeroBtn_' + i);
      if (goZeroBtn) goZeroBtn.disabled = !drv.position_trusted || !drv.enabled || !!drv.running;
      var clearZeroBtn = document.getElementById('motorClearZeroBtn_' + i);
      if (clearZeroBtn) clearZeroBtn.disabled = !!drv.running;
      var limitSaveBtn = document.getElementById('motorLimitSaveBtn_' + i);
      if (limitSaveBtn) limitSaveBtn.disabled = !!drv.running;
      var tumbleStartBtn = document.getElementById('motorTumbleStartBtn_' + i);
      if (tumbleStartBtn) tumbleStartBtn.disabled = !drv.enabled || !drv.position_trusted || !!drv.running || !!drv.tumble_active;
      var tumbleStopBtn = document.getElementById('motorTumbleStopBtn_' + i);
      if (tumbleStopBtn) tumbleStopBtn.disabled = !drv.tumble_active;

      /* Stats */
      var statsEl = document.getElementById('driverStats_' + i);
      if (statsEl && drv.found) {
        var parts = [];
        if (drv.cs_actual != null) parts.push('CS: ' + drv.cs_actual);
        if (drv.rms_current != null) parts.push('RMS: ' + drv.rms_current + 'mA');
        if (drv.current_ma != null) parts.push('iRun: ' + drv.current_ma + 'mA');
        if (drv.ihold_ma != null) parts.push('iHold: ' + drv.ihold_ma + 'mA');
        if (drv.step_delay_us != null) parts.push('Speed: ' + drv.step_delay_us + 'us');
        if (drv.ramp_steps != null) parts.push('Ramp: ' + drv.ramp_steps + 'st');
        if (drv.stealthchop != null) parts.push('SC: ' + (drv.stealthchop ? 'ON' : 'OFF'));
        if (drv.interpolation != null) parts.push('INTP: ' + (drv.interpolation ? 'ON' : 'OFF'));
        if (drv.multistep_filt != null) parts.push('MSF: ' + (drv.multistep_filt ? 'ON' : 'OFF'));
        if (drv.steps_remaining != null) parts.push('Rem: ' + drv.steps_remaining);
        if (drv.standstill != null) parts.push(drv.standstill ? 'STBY' : 'MOVE');
        statsEl.textContent = parts.join(' | ');
      } else if (statsEl) {
        statsEl.textContent = '';
      }
      var debugEl = document.getElementById('driverDebug_' + i);
      if (debugEl) {
        var debugParts = [];
        if (drv.target_step_hz != null) debugParts.push('Target ' + Math.round(drv.target_step_hz) + 'Hz');
        if (drv.actual_step_hz != null && drv.actual_step_hz > 0) debugParts.push('Actual ' + Math.round(drv.actual_step_hz) + 'Hz');
        if (drv.last_step_lag_us != null) debugParts.push('Lag ' + drv.last_step_lag_us + 'us');
        if (drv.last_step_interval_us != null && drv.last_step_interval_us > 0) debugParts.push('Dt ' + drv.last_step_interval_us + 'us');
        debugEl.textContent = debugParts.join(' | ');
      }

      var posEl = document.getElementById('motorPos_' + i);
      var posStateEl = document.getElementById('motorPosState_' + i);
      if (posEl) {
        if (drv.position_trusted) {
          if (isBelt) {
            posEl.textContent = (drv.position_steps || 0) + ' st';
          } else {
            var posDeg = drv.position_deg != null ? drv.position_deg : 0;
            var shownDeg = drv.display_wrap ? wrapDegrees360(posDeg) : posDeg;
            posEl.textContent = shownDeg.toFixed(1) + '\u00b0';
          }
        } else {
          posEl.textContent = 'UNTRUSTED';
        }
      }
      if (posStateEl) {
        posStateEl.textContent = gimbalPositionReasonText(drv.position_reason, !!drv.position_trusted);
      }
      var limitMinInput = document.getElementById('motorLimitMin_' + i);
      if (limitMinInput) {
        var limitDraft = gimbalEnsureLimitDraft(i);
        limitMinInput.step = gimbalLimitInputStep(drv, i);
        if (drv.hard_limit_min != null) limitMinInput.min = gimbalFormatLimitValue(drv, i, drv.hard_limit_min);
        if (drv.hard_limit_max != null) limitMinInput.max = gimbalFormatLimitValue(drv, i, drv.hard_limit_max);
        limitMinInput.disabled = !!drv.running;
        if (limitDraft.minDirty) {
          limitMinInput.value = limitDraft.minValue;
        } else if (!limitMinInput.matches(':focus') && drv.soft_limit_min != null) {
          limitMinInput.value = gimbalFormatLimitValue(drv, i, drv.soft_limit_min);
        }
      }
      var limitMaxInput = document.getElementById('motorLimitMax_' + i);
      if (limitMaxInput) {
        var limitDraftMax = gimbalEnsureLimitDraft(i);
        limitMaxInput.step = gimbalLimitInputStep(drv, i);
        if (drv.hard_limit_min != null) limitMaxInput.min = gimbalFormatLimitValue(drv, i, drv.hard_limit_min);
        if (drv.hard_limit_max != null) limitMaxInput.max = gimbalFormatLimitValue(drv, i, drv.hard_limit_max);
        limitMaxInput.disabled = !!drv.running;
        if (limitDraftMax.maxDirty) {
          limitMaxInput.value = limitDraftMax.maxValue;
        } else if (!limitMaxInput.matches(':focus') && drv.soft_limit_max != null) {
          limitMaxInput.value = gimbalFormatLimitValue(drv, i, drv.soft_limit_max);
        }
      }
      var limitNote = document.getElementById('motorLimitNote_' + i);
      if (limitNote) {
        var limitNoteParts = [];
        if (drv.hard_limit_min != null && drv.hard_limit_max != null) {
          limitNoteParts.push('Hard ' + gimbalFormatLimitValue(drv, i, drv.hard_limit_min) + ' to ' + gimbalFormatLimitValue(drv, i, drv.hard_limit_max) + ' ' + (drv.limit_units || (isBelt ? 'steps' : 'deg')) + ' from zero');
        }
        limitNoteParts.push(drv.limits_enforced ? 'active' : 'waiting for trusted zero');
        limitNote.textContent = limitNoteParts.join(' | ');
      }
      if (supportsTumble) {
        var tumbleADraft = gimbalEnsureTumbleDraft(i);
        var tumbleAInput = document.getElementById('motorTumbleA_' + i);
        if (tumbleAInput) {
          tumbleAInput.disabled = !!drv.tumble_active;
          if (tumbleADraft.aDirty) {
            tumbleAInput.value = tumbleADraft.aValue;
          } else if (!tumbleAInput.matches(':focus') && drv.tumble_a != null) {
            tumbleAInput.value = gimbalFormatTumbleValue(drv.tumble_a);
          }
        }
        var tumbleBInput = document.getElementById('motorTumbleB_' + i);
        if (tumbleBInput) {
          tumbleBInput.disabled = !!drv.tumble_active;
          if (tumbleADraft.bDirty) {
            tumbleBInput.value = tumbleADraft.bValue;
          } else if (!tumbleBInput.matches(':focus') && drv.tumble_b != null) {
            tumbleBInput.value = gimbalFormatTumbleValue(drv.tumble_b);
          }
        }
        var tumbleDwellInput = document.getElementById('motorTumbleDwell_' + i);
        if (tumbleDwellInput) {
          tumbleDwellInput.disabled = !!drv.tumble_active;
          if (tumbleADraft.dwellDirty) {
            tumbleDwellInput.value = tumbleADraft.dwellValue;
          } else if (!tumbleDwellInput.matches(':focus') && drv.tumble_dwell_ms != null) {
            tumbleDwellInput.value = drv.tumble_dwell_ms;
          }
        }
        var tumbleNote = document.getElementById('motorTumbleNote_' + i);
        if (tumbleNote) {
          tumbleNote.textContent = gimbalTumbleStateText(drv, i);
        }
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
      var speedSlider = document.getElementById('motorSpeedSlider_' + i);
      if (speedSlider && !speedSlider.matches(':active') && drv.step_delay_us != null) {
        speedSlider.value = drv.step_delay_us;
        var speedLabel = document.getElementById('motorSpeedLabel_' + i);
        if (speedLabel) speedLabel.textContent = drv.step_delay_us + ' us';
      }
      var rampSlider = document.getElementById('motorRampSlider_' + i);
      if (rampSlider && !rampSlider.matches(':active') && drv.ramp_steps != null) {
        rampSlider.value = drv.ramp_steps;
        var rampLabel = document.getElementById('motorRampLabel_' + i);
        if (rampLabel) rampLabel.textContent = drv.ramp_steps + ' steps';
      }
      var stealthToggle = document.getElementById('motorStealthToggle_' + i);
      if (stealthToggle && !stealthToggle.matches(':active') && drv.stealthchop != null) {
        stealthToggle.checked = !!drv.stealthchop;
      }
      var interpToggle = document.getElementById('motorInterpToggle_' + i);
      if (interpToggle && !interpToggle.matches(':active') && drv.interpolation != null) {
        interpToggle.checked = !!drv.interpolation;
      }
      var msfToggle = document.getElementById('motorMsfToggle_' + i);
      if (msfToggle && !msfToggle.matches(':active') && drv.multistep_filt != null) {
        msfToggle.checked = !!drv.multistep_filt;
      }

      /* Gear info */
      if (!isBelt) {
        var gearEl = document.getElementById('gearInfo_' + i);
        if (gearEl && drv.gear_ratio != null && drv.steps_per_deg != null) {
          gearEl.textContent = drv.gear_ratio + ':1 gear, ' + drv.steps_per_deg.toFixed(2) + ' steps/deg';
        }
      }
    });
  }).catch(function() {
    document.getElementById('gimbalDot').className = 'status-dot';
    document.getElementById('gimbalStatus').textContent = 'Not connected';
  });
}

/* ========== Setpoints ==========
   Named snapshots of all 10 servo targets. Server-authoritative
   (groundstation/servo_setpoints.json). Clicking a setpoint drives
   every channel toward the saved PW through the normal server-side
   ramp, so moves are envelope-clamped and rate-limited. */
var setpoints = [];

function setpointRefresh() {
  return fetch('/api/setpoints').then(function(r) { return r.json(); }).then(function(list) {
    setpoints = Array.isArray(list) ? list : [];
    setpointRender();
    if (Array.isArray(actions)) actionRender();
    if (typeof actionEditorState !== 'undefined' && actionEditorState) actionRenderEditor();
    if (Array.isArray(procedures)) procedureRender();
    if (typeof procedureEditorState !== 'undefined' && procedureEditorState) procedureRenderEditor();
  }).catch(function() {
    var el = document.getElementById('setpointList');
    if (el) el.textContent = 'Failed to load setpoints.';
  });
}

function setpointAdd() {
  var input = document.getElementById('setpointName');
  if (!input) return;
  var name = (input.value || '').trim();
  if (!name) { alert('Enter a name first.'); input.focus(); return; }
  fetch('/api/setpoints', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({name: name})
  }).then(function(r) { return r.json().then(function(d) { return {ok: r.ok, body: d}; }); })
    .then(function(res) {
      if (!res.ok || !res.body.ok) {
        alert('Save failed: ' + ((res.body && res.body.error) || 'unknown'));
        return;
      }
      input.value = '';
      setpointRefresh();
    })
    .catch(function(e) { alert('Save request failed: ' + e); });
}

function setpointGo(sid) {
  fetch('/api/setpoints/' + encodeURIComponent(sid) + '/go', {method: 'POST'})
    .then(function(r) { return r.json().then(function(d) { return {ok: r.ok, body: d}; }); })
    .then(function(res) {
      if (!res.ok || !res.body.ok) {
        alert('Go failed: ' + ((res.body && res.body.error) || 'unknown'));
      }
    })
    .catch(function(e) { alert('Go request failed: ' + e); });
}

function setpointDelete(sid, name) {
  if (!confirm('Delete setpoint "' + name + '"?')) return;
  fetch('/api/setpoints/' + encodeURIComponent(sid), {method: 'DELETE'})
    .then(function(r) { return r.json().then(function(d) { return {ok: r.ok, body: d}; }); })
    .then(function(res) {
      if (!res.ok || !res.body.ok) {
        alert('Delete failed: ' + ((res.body && res.body.error) || 'unknown'));
        return;
      }
      setpointRefresh();
    })
    .catch(function(e) { alert('Delete request failed: ' + e); });
}

function setpointRename(sid, currentName) {
  var next = prompt('Rename setpoint:', currentName);
  if (next == null) return;
  next = (next || '').trim();
  if (!next) { alert('Name required.'); return; }
  fetch('/api/setpoints/' + encodeURIComponent(sid), {
    method: 'PATCH',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({name: next})
  }).then(function(r) { return r.json().then(function(d) { return {ok: r.ok, body: d}; }); })
    .then(function(res) {
      if (!res.ok || !res.body.ok) {
        alert('Rename failed: ' + ((res.body && res.body.error) || 'unknown'));
        return;
      }
      setpointRefresh();
    })
    .catch(function(e) { alert('Rename request failed: ' + e); });
}

function setpointRender() {
  var el = document.getElementById('setpointList');
  if (!el) return;
  if (!setpoints.length) {
    el.innerHTML = '<div class="setpoint-empty">No setpoints yet. Set the arms where you want, name it, click Add.</div>';
    return;
  }
  var html = '';
  for (var i = 0; i < setpoints.length; i++) {
    var sp = setpoints[i];
    var sid = String(sp.id || '').replace(/[^a-f0-9]/gi, '');
    var safeName = String(sp.name || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    var jsName = safeName.replace(/'/g, "\\'");
    html += '<div class="setpoint-item">' +
      '<button class="btn btn-sm setpoint-go" onclick="setpointGo(\'' + sid + '\')" title="Drive arms to this pose">' + safeName + '</button>' +
      '<button class="btn btn-sm setpoint-rename" onclick="setpointRename(\'' + sid + '\', \'' + jsName + '\')" title="Rename">Edit</button>' +
      '<button class="btn btn-sm btn-red setpoint-del" onclick="setpointDelete(\'' + sid + '\', \'' + jsName + '\')" title="Delete">X</button>' +
      '</div>';
  }
  el.innerHTML = html;
}

/* ========== Actions ==========
   Ordered sequences of setpoints. Server plays them back through the
   ramp at the operator's servo speed. No pauses between steps except
   at user-tagged breakpoints (park there until /continue). */
var actions = [];
var actionState = {running: false, phase: 'idle'};
var actionEditorState = null;  // null | {id: string|null, name, steps, append_setpoint_id}

function htmlEscape(s) {
  return String(s || '')
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

function actionRefresh() {
  return fetch('/api/actions').then(function(r) { return r.json(); }).then(function(list) {
    actions = Array.isArray(list) ? list : [];
    actionRender();
  }).catch(function() { /* empty list on error */ });
}

function actionStatePoll() {
  fetch('/api/actions/state').then(function(r) { return r.json(); }).then(function(st) {
    actionState = st || {running: false, phase: 'idle'};
    actionRenderStatus();
  }).catch(function() {});
}

var ACTION_NEUTRAL_ID = '__neutral__';

function actionSetpointName(sid) {
  if (sid === ACTION_NEUTRAL_ID) return 'ALL NEUTRAL';
  var sp = setpoints.find(function(s) { return s.id === sid; });
  return sp ? sp.name : '(missing: ' + sid + ')';
}

// Build option list: ALL NEUTRAL pseudo-entry + real setpoints.
// selectedId is the currently-chosen id to mark with `selected`.
function actionBuildOptions(selectedId, includeBlankAppendOption) {
  var opts = '';
  if (includeBlankAppendOption) {
    opts += '<option value=""' + (!selectedId ? ' selected' : '') + '>(none)</option>';
  }
  var selNeutral = (selectedId === ACTION_NEUTRAL_ID) ? ' selected' : '';
  opts += '<option value="' + ACTION_NEUTRAL_ID + '"' + selNeutral + '>ALL NEUTRAL</option>';
  for (var i = 0; i < setpoints.length; i++) {
    var s = setpoints[i];
    var sel = (s.id === selectedId) ? ' selected' : '';
    opts += '<option value="' + htmlEscape(s.id) + '"' + sel + '>' + htmlEscape(s.name) + '</option>';
  }
  return opts;
}

function actionRender() {
  var el = document.getElementById('actionList');
  if (!el) return;
  if (!actions.length) {
    el.innerHTML = '<div class="setpoint-empty">No actions yet. Click New Action.</div>';
    return;
  }
  var html = '';
  for (var i = 0; i < actions.length; i++) {
    var a = actions[i];
    var aid = String(a.id).replace(/[^a-f0-9]/gi, '');
    var safeName = htmlEscape(a.name);
    var nSteps = (a.steps || []).length + (a.append_setpoint_id ? 1 : 0);
    var breakpoints = (a.steps || []).filter(function(s) { return s.breakpoint; }).length;
    var appendLabel = a.append_setpoint_id ? ' + ' + htmlEscape(actionSetpointName(a.append_setpoint_id)) : '';
    var summary = nSteps + ' step' + (nSteps === 1 ? '' : 's') + (breakpoints ? ', ' + breakpoints + ' breakpoint' + (breakpoints === 1 ? '' : 's') : '') + appendLabel;
    html += '<div class="action-item">' +
      '<div class="action-head">' +
        '<span class="action-name">' + safeName + '</span>' +
        '<span class="action-summary">' + summary + '</span>' +
      '</div>' +
      '<div class="action-buttons">' +
        '<button class="btn btn-sm btn-green" onclick="actionPlay(\'' + aid + '\')">Play</button>' +
        '<button class="btn btn-sm" onclick="actionOpenEditor(\'' + aid + '\')">Edit</button>' +
        '<button class="btn btn-sm btn-red" onclick="actionDelete(\'' + aid + '\', \'' + safeName.replace(/'/g, "\\'") + '\')">X</button>' +
      '</div>' +
      '</div>';
  }
  el.innerHTML = html;
}

function actionRenderStatus() {
  var el = document.getElementById('actionStatus');
  if (!el) return;
  if (!actionState.running && actionState.phase !== 'waiting-breakpoint') {
    el.innerHTML = '';
    el.className = 'action-status';
    return;
  }
  var name = htmlEscape(actionState.action_name || '');
  var progress = actionState.step_index + ' / ' + actionState.total_steps;
  var phaseLabel = {
    'running': 'Running',
    'waiting-breakpoint': 'At breakpoint',
    'error': 'Error',
    'stopped': 'Stopped',
    'done': 'Done'
  }[actionState.phase] || actionState.phase;
  var html = '<div class="action-status-body">' +
    '<span class="action-status-name">' + name + '</span>' +
    '<span class="action-status-phase">' + phaseLabel + ' · step ' + progress + '</span>';
  if (actionState.phase === 'waiting-breakpoint') {
    html += '<button class="btn btn-sm btn-green" onclick="actionContinue(\'' + actionState.action_id + '\')">Continue</button>';
  }
  if (actionState.running) {
    html += '<button class="btn btn-sm btn-red" onclick="actionStop()">Stop</button>';
  }
  if (actionState.phase === 'error' && actionState.error) {
    html += '<span class="action-status-error">' + htmlEscape(actionState.error) + '</span>';
  }
  html += '</div>';
  el.innerHTML = html;
  el.className = 'action-status action-status-active';
}

function actionPlay(aid) {
  fetch('/api/actions/' + encodeURIComponent(aid) + '/play', {method: 'POST'})
    .then(function(r) { return r.json().then(function(d) { return {ok: r.ok, body: d}; }); })
    .then(function(res) {
      if (!res.ok || !res.body.ok) {
        alert('Play failed: ' + ((res.body && res.body.error) || 'unknown'));
      }
      actionStatePoll();
    })
    .catch(function(e) { alert('Play request failed: ' + e); });
}

function actionContinue(aid) {
  fetch('/api/actions/' + encodeURIComponent(aid) + '/continue', {method: 'POST'})
    .then(function(r) { return r.json().then(function(d) { return {ok: r.ok, body: d}; }); })
    .then(function(res) {
      if (!res.ok || !res.body.ok) alert('Continue failed: ' + ((res.body && res.body.error) || 'unknown'));
    });
}

function actionStop() {
  fetch('/api/actions/stop', {method: 'POST'}).catch(function() {});
}

function actionDelete(aid, name) {
  if (!confirm('Delete action "' + name + '"?')) return;
  fetch('/api/actions/' + encodeURIComponent(aid), {method: 'DELETE'})
    .then(function(r) { return r.json().then(function(d) { return {ok: r.ok, body: d}; }); })
    .then(function(res) {
      if (!res.ok || !res.body.ok) {
        alert('Delete failed: ' + ((res.body && res.body.error) || 'unknown'));
        return;
      }
      actionRefresh();
    });
}

/* ---------- Action editor ---------- */

function actionOpenEditor(aid) {
  var editor = document.getElementById('actionEditor');
  if (!editor) return;
  if (aid) {
    var existing = actions.find(function(a) { return a.id === aid; });
    if (!existing) { alert('Action not found.'); return; }
    actionEditorState = {
      id: aid,
      name: existing.name,
      steps: (existing.steps || []).map(function(s) { return {setpoint_id: s.setpoint_id, breakpoint: !!s.breakpoint}; }),
      append_setpoint_id: existing.append_setpoint_id || null,
    };
  } else {
    actionEditorState = {id: null, name: '', steps: [], append_setpoint_id: null};
  }
  actionRenderEditor();
  editor.style.display = 'block';
}

function actionCloseEditor() {
  actionEditorState = null;
  var editor = document.getElementById('actionEditor');
  if (editor) { editor.style.display = 'none'; editor.innerHTML = ''; }
}

function actionEditorAddStep() {
  if (!actionEditorState) return;
  // Default to ALL NEUTRAL so an empty-setpoints install is still usable.
  var defaultId = setpoints.length ? setpoints[0].id : ACTION_NEUTRAL_ID;
  actionEditorState.steps.push({setpoint_id: defaultId, breakpoint: false});
  actionRenderEditor();
}

function actionEditorRemoveStep(idx) {
  if (!actionEditorState) return;
  actionEditorState.steps.splice(idx, 1);
  actionRenderEditor();
}

function actionEditorMove(idx, dir) {
  if (!actionEditorState) return;
  var j = idx + dir;
  if (j < 0 || j >= actionEditorState.steps.length) return;
  var tmp = actionEditorState.steps[idx];
  actionEditorState.steps[idx] = actionEditorState.steps[j];
  actionEditorState.steps[j] = tmp;
  actionRenderEditor();
}

function actionEditorSetStepSetpoint(idx, sid) {
  if (!actionEditorState || !actionEditorState.steps[idx]) return;
  actionEditorState.steps[idx].setpoint_id = sid;
}

function actionEditorSetBreakpoint(idx, flag) {
  if (!actionEditorState || !actionEditorState.steps[idx]) return;
  actionEditorState.steps[idx].breakpoint = !!flag;
}

function actionEditorSetAppend(sid) {
  if (!actionEditorState) return;
  actionEditorState.append_setpoint_id = sid || null;
}

function actionEditorSetName(name) {
  if (!actionEditorState) return;
  actionEditorState.name = name;
}

function actionRenderEditor() {
  var editor = document.getElementById('actionEditor');
  if (!editor || !actionEditorState) return;
  var st = actionEditorState;
  var appendOptions = actionBuildOptions(st.append_setpoint_id, true);
  var stepsHtml = '';
  if (!st.steps.length) {
    stepsHtml = '<div class="action-editor-empty">No steps. Click Add Step.</div>';
  } else {
    for (var i = 0; i < st.steps.length; i++) {
      var step = st.steps[i];
      var selOpts = actionBuildOptions(step.setpoint_id, false);
      stepsHtml += '<div class="action-step-row">' +
        '<span class="action-step-num">' + (i + 1) + '.</span>' +
        '<select onchange="actionEditorSetStepSetpoint(' + i + ', this.value)">' + selOpts + '</select>' +
        '<label class="action-step-bp"><input type="checkbox" ' + (step.breakpoint ? 'checked' : '') + ' onchange="actionEditorSetBreakpoint(' + i + ', this.checked)"> breakpoint</label>' +
        '<button class="btn btn-sm" onclick="actionEditorMove(' + i + ', -1)" ' + (i === 0 ? 'disabled' : '') + '>&uarr;</button>' +
        '<button class="btn btn-sm" onclick="actionEditorMove(' + i + ', 1)" ' + (i === st.steps.length - 1 ? 'disabled' : '') + '>&darr;</button>' +
        '<button class="btn btn-sm btn-red" onclick="actionEditorRemoveStep(' + i + ')">X</button>' +
      '</div>';
    }
  }
  editor.innerHTML =
    '<div class="action-editor-head">' +
      '<strong>' + (st.id ? 'Edit Action' : 'New Action') + '</strong>' +
      '<button class="btn btn-sm" onclick="actionCloseEditor()">Close</button>' +
    '</div>' +
    '<div class="action-editor-row">' +
      '<label>Name</label>' +
      '<input type="text" value="' + htmlEscape(st.name) + '" maxlength="64" oninput="actionEditorSetName(this.value)" style="flex:1;">' +
    '</div>' +
    '<div class="action-editor-steps">' + stepsHtml + '</div>' +
    '<div class="action-editor-row">' +
      '<button class="btn btn-sm" onclick="actionEditorAddStep()">Add Step</button>' +
    '</div>' +
    '<div class="action-editor-row">' +
      '<label>Append at end</label>' +
      '<select onchange="actionEditorSetAppend(this.value)">' + appendOptions + '</select>' +
    '</div>' +
    '<div class="action-editor-row">' +
      '<button class="btn btn-sm btn-green" onclick="actionEditorSave()">Save</button>' +
    '</div>';
}

function actionEditorSave() {
  if (!actionEditorState) return;
  var st = actionEditorState;
  var name = (st.name || '').trim();
  if (!name) { alert('Name required.'); return; }
  if (!st.steps.length) { alert('Add at least one step.'); return; }
  var body = {
    name: name,
    steps: st.steps.map(function(s) { return {setpoint_id: s.setpoint_id, breakpoint: !!s.breakpoint}; }),
    append_setpoint_id: st.append_setpoint_id || null,
  };
  var method, url;
  if (st.id) {
    method = 'PATCH';
    url = '/api/actions/' + encodeURIComponent(st.id);
  } else {
    method = 'POST';
    url = '/api/actions';
  }
  fetch(url, {
    method: method,
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(body),
  }).then(function(r) { return r.json().then(function(d) { return {ok: r.ok, body: d}; }); })
    .then(function(res) {
      if (!res.ok || !res.body.ok) {
        alert('Save failed: ' + ((res.body && res.body.error) || 'unknown'));
        return;
      }
      actionCloseEditor();
      actionRefresh();
    });
}

/* ========== Procedures ==========
   Checkpointed multi-system sequences. The server owns execution;
   this UI only edits config and advances operator prompts. */
var procedures = [];
var procedureState = {running: false, phase: 'idle'};
var procedureEditorState = null;
var PROCEDURE_DRIVER_LABELS = {0: 'Yaw', 1: 'Pitch', 2: 'Roll', 3: 'Belt'};
var PROCEDURE_ZERO_DRIVERS = [0, 1, 2, 3];

function procedureRefresh() {
  return fetch('/api/procedures').then(function(r) { return r.json(); }).then(function(list) {
    procedures = Array.isArray(list) ? list : [];
    procedureRender();
  }).catch(function() {
    var el = document.getElementById('procedureList');
    if (el) el.textContent = 'Failed to load procedures.';
  });
}

function procedureStatePoll() {
  fetch('/api/procedures/state').then(function(r) { return r.json(); }).then(function(st) {
    procedureState = st || {running: false, phase: 'idle'};
    procedureRenderStatus();
  }).catch(function() {});
}

function procedureDriverName(driver) {
  var idx = parseInt(driver, 10);
  if (!isNaN(idx) && gimbalDriverCache && gimbalDriverCache[idx] && gimbalDriverCache[idx].name) {
    return String(gimbalDriverCache[idx].name);
  }
  if (PROCEDURE_DRIVER_LABELS.hasOwnProperty(idx)) return PROCEDURE_DRIVER_LABELS[idx];
  return 'Driver ' + String(driver);
}

function procedureStepLabel(stepName) {
  return {
    'set-gimbal-zero-pose': 'Set zero pose',
    'capture-gimbal-zero': 'Capture zero',
    'manual-spin-window': 'Spin window',
    'start-spin-window': 'Start tumble',
    'stop-tumble': 'Stop tumble',
    'go-gimbal-zero': 'Go zero',
    'arm-pose-a': 'Arm pose A',
    'gantry-approach': 'Gantry approach',
    'arm-pose-b': 'Arm pose B',
    'dwell': 'Dwell',
    'gantry-home': 'Gantry home',
    'arm-neutral': 'Arm neutral'
  }[stepName] || stepName || '';
}

function procedurePhaseLabel(phase) {
  return {
    'idle': 'Idle',
    'waiting-operator': 'Waiting',
    'running': 'Running',
    'stopped': 'Stopped',
    'done': 'Done',
    'error': 'Error'
  }[phase] || String(phase || 'idle');
}

function procedureSummary(proc) {
  var zeroDrivers = (proc.gimbal_zero_drivers || []).map(function(driver) {
    return procedureDriverName(driver);
  });
  var zeroText = zeroDrivers.length ? zeroDrivers.join(', ') : 'none';
  return 'Zero ' + zeroText +
    ' | Belt 0→' + String(proc.gantry_approach_steps) +
    ' | tumble Yaw/Pitch/Roll (live gimbal settings)' +
    ' | dwell ' + String(proc.dwell_ms) + ' ms' +
    ' | x' + String(proc.repeat_count);
}

function procedureRender() {
  var el = document.getElementById('procedureList');
  if (!el) return;
  if (!procedures.length) {
    el.innerHTML = '<div class="setpoint-empty">No procedures yet. Click New Procedure.</div>';
    return;
  }
  var html = '';
  for (var i = 0; i < procedures.length; i++) {
    var proc = procedures[i];
    var pid = String(proc.id || '').replace(/[^a-f0-9]/gi, '');
    var rawName = String(proc.name || '');
    var safeName = htmlEscape(rawName);
    var jsName = rawName.replace(/\\/g, '\\\\').replace(/'/g, "\\'");
    html += '<div class="action-item">' +
      '<div class="action-head">' +
        '<span class="action-name">' + safeName + '</span>' +
        '<span class="action-summary">' + htmlEscape(procedureSummary(proc)) + '</span>' +
      '</div>' +
      '<div class="action-buttons">' +
        '<button class="btn btn-sm btn-green" onclick="procedureReady(\'' + pid + '\')">Ready</button>' +
        '<button class="btn btn-sm" onclick="procedureOpenEditor(\'' + pid + '\')">Edit</button>' +
        '<button class="btn btn-sm btn-red" onclick="procedureDelete(\'' + pid + '\', \'' + jsName + '\')">X</button>' +
      '</div>' +
      '</div>';
  }
  el.innerHTML = html;
}

function procedureRenderStatus() {
  var el = document.getElementById('procedureStatus');
  if (!el) return;
  if (!procedureState.running && (!procedureState.phase || procedureState.phase === 'idle')) {
    el.innerHTML = '';
    el.className = 'action-status';
    return;
  }
  var phase = procedurePhaseLabel(procedureState.phase);
  var stepLabel = procedureStepLabel(procedureState.step_name);
  var progress = '';
  if (procedureState.total_steps) {
    progress = 'step ' + String(procedureState.step_index || 0) + ' / ' + String(procedureState.total_steps || 0);
  }
  var cycleText = '';
  if (procedureState.total_cycles) {
    cycleText = 'cycle ' + String(procedureState.cycle_index || 0) + ' / ' + String(procedureState.total_cycles || 0);
  }
  var parts = [phase];
  if (stepLabel) parts.push(stepLabel);
  if (progress) parts.push(progress);
  if (cycleText) parts.push(cycleText);
  var html = '<div class="action-status-body">' +
    '<span class="action-status-name">' + htmlEscape(procedureState.procedure_name || '') + '</span>' +
    '<span class="action-status-phase">' + htmlEscape(parts.join(' · ')) + '</span>';
  if (procedureState.phase === 'waiting-operator' && procedureState.procedure_id) {
    html += '<button class="btn btn-sm btn-green" onclick="procedureContinue(\'' + htmlEscape(procedureState.procedure_id) + '\')">Continue</button>';
  }
  if (procedureState.running) {
    html += '<button class="btn btn-sm btn-red" onclick="procedureStop()">Stop</button>';
  }
  if (procedureState.error) {
    html += '<span class="action-status-error">' + htmlEscape(procedureState.error) + '</span>';
  }
  if (procedureState.operator_prompt) {
    html += '<span class="procedure-status-prompt">' + htmlEscape(procedureState.operator_prompt) + '</span>';
  }
  html += '</div>';
  el.innerHTML = html;
  el.className = 'action-status action-status-active';
}

function procedureReady(pid) {
  fetch('/api/procedures/' + encodeURIComponent(pid) + '/ready', {method: 'POST'})
    .then(function(r) { return r.json().then(function(d) { return {ok: r.ok, body: d}; }); })
    .then(function(res) {
      if (!res.ok || !res.body.ok) {
        alert('Ready failed: ' + ((res.body && res.body.error) || 'unknown'));
      }
      procedureStatePoll();
    })
    .catch(function(e) { alert('Ready request failed: ' + e); });
}

function procedureContinue(pid) {
  fetch('/api/procedures/' + encodeURIComponent(pid) + '/continue', {method: 'POST'})
    .then(function(r) { return r.json().then(function(d) { return {ok: r.ok, body: d}; }); })
    .then(function(res) {
      if (!res.ok || !res.body.ok) {
        alert('Continue failed: ' + ((res.body && res.body.error) || 'unknown'));
      }
      procedureStatePoll();
    })
    .catch(function(e) { alert('Continue request failed: ' + e); });
}

function procedureStop() {
  fetch('/api/procedures/stop', {method: 'POST'})
    .then(function() { procedureStatePoll(); })
    .catch(function() {});
}

function procedureDelete(pid, name) {
  if (!confirm('Delete procedure "' + name + '"?')) return;
  fetch('/api/procedures/' + encodeURIComponent(pid), {method: 'DELETE'})
    .then(function(r) { return r.json().then(function(d) { return {ok: r.ok, body: d}; }); })
    .then(function(res) {
      if (!res.ok || !res.body.ok) {
        alert('Delete failed: ' + ((res.body && res.body.error) || 'unknown'));
        return;
      }
      procedureRefresh();
    })
    .catch(function(e) { alert('Delete request failed: ' + e); });
}

function procedureDefaultSetpointId() {
  return setpoints.length ? setpoints[0].id : ACTION_NEUTRAL_ID;
}

function procedureDefaultEditorState() {
  return {
    id: null,
    name: '',
    gimbal_zero_drivers: [0, 1, 2],
    arm_pose_a_setpoint_id: procedureDefaultSetpointId(),
    arm_pose_b_setpoint_id: ACTION_NEUTRAL_ID,
    gantry_approach_steps: '0',
    dwell_ms: '1000',
    repeat_count: '1'
  };
}

function procedureOpenEditor(pid) {
  var editor = document.getElementById('procedureEditor');
  if (!editor) return;
  if (pid) {
    var existing = procedures.find(function(proc) { return proc.id === pid; });
    if (!existing) { alert('Procedure not found.'); return; }
    procedureEditorState = {
      id: existing.id,
      name: existing.name,
      gimbal_zero_drivers: (existing.gimbal_zero_drivers || []).map(function(driver) { return parseInt(driver, 10); }),
      arm_pose_a_setpoint_id: existing.arm_pose_a_setpoint_id,
      arm_pose_b_setpoint_id: existing.arm_pose_b_setpoint_id,
      gantry_approach_steps: String(existing.gantry_approach_steps),
      dwell_ms: String(existing.dwell_ms),
      repeat_count: String(existing.repeat_count)
    };
  } else {
    procedureEditorState = procedureDefaultEditorState();
  }
  procedureRenderEditor();
  editor.style.display = 'block';
}

function procedureCloseEditor() {
  procedureEditorState = null;
  var editor = document.getElementById('procedureEditor');
  if (editor) { editor.style.display = 'none'; editor.innerHTML = ''; }
}

function procedureEditorSetName(name) {
  if (!procedureEditorState) return;
  procedureEditorState.name = name;
}

function procedureEditorSetField(field, value) {
  if (!procedureEditorState) return;
  procedureEditorState[field] = value;
}

function procedureEditorToggleZeroDriver(driver, checked) {
  if (!procedureEditorState) return;
  var next = (procedureEditorState.gimbal_zero_drivers || []).slice();
  var idx = next.indexOf(driver);
  if (checked && idx === -1) next.push(driver);
  if (!checked && idx !== -1) next.splice(idx, 1);
  next.sort(function(a, b) { return a - b; });
  procedureEditorState.gimbal_zero_drivers = next;
}

function procedureBuildZeroDriverChecks(selectedDrivers) {
  var selected = selectedDrivers || [];
  var html = '';
  for (var i = 0; i < PROCEDURE_ZERO_DRIVERS.length; i++) {
    var driver = PROCEDURE_ZERO_DRIVERS[i];
    var checked = selected.indexOf(driver) !== -1 ? ' checked' : '';
    html += '<label class="procedure-driver-check">' +
      '<input type="checkbox"' + checked + ' onchange="procedureEditorToggleZeroDriver(' + driver + ', this.checked)">' +
      '<span>' + htmlEscape(procedureDriverName(driver)) + '</span>' +
      '</label>';
  }
  return html;
}

function procedureRenderEditor() {
  var editor = document.getElementById('procedureEditor');
  if (!editor || !procedureEditorState) return;
  var st = procedureEditorState;
  var poseAOptions = actionBuildOptions(st.arm_pose_a_setpoint_id, false);
  var poseBOptions = actionBuildOptions(st.arm_pose_b_setpoint_id, false);
  editor.innerHTML =
    '<div class="action-editor-head">' +
      '<strong>' + (st.id ? 'Edit Procedure' : 'New Procedure') + '</strong>' +
      '<button class="btn btn-sm" onclick="procedureCloseEditor()">Close</button>' +
    '</div>' +
    '<div class="action-editor-row">' +
      '<label>Name</label>' +
      '<input type="text" value="' + htmlEscape(st.name) + '" maxlength="64" oninput="procedureEditorSetName(this.value)" style="flex:1;">' +
    '</div>' +
    '<div class="action-editor-row">' +
      '<label>Zero drivers</label>' +
      '<div class="procedure-driver-checks">' + procedureBuildZeroDriverChecks(st.gimbal_zero_drivers) + '</div>' +
    '</div>' +
    '<div class="action-editor-empty">' +
      'Procedure tumble always uses the current Yaw, Pitch, and Roll settings from Gimbal Controls. Belt home is always zero.' +
    '</div>' +
    '<div class="procedure-editor-grid">' +
      '<label class="procedure-field"><span>Arm pose A</span><select onchange="procedureEditorSetField(\'arm_pose_a_setpoint_id\', this.value)">' + poseAOptions + '</select></label>' +
      '<label class="procedure-field"><span>Arm pose B</span><select onchange="procedureEditorSetField(\'arm_pose_b_setpoint_id\', this.value)">' + poseBOptions + '</select></label>' +
      '<label class="procedure-field"><span>Gantry approach steps</span><input type="number" step="1" value="' + htmlEscape(st.gantry_approach_steps) + '" oninput="procedureEditorSetField(\'gantry_approach_steps\', this.value)"></label>' +
      '<label class="procedure-field"><span>Dwell ms</span><input type="number" min="0" max="600000" step="50" value="' + htmlEscape(st.dwell_ms) + '" oninput="procedureEditorSetField(\'dwell_ms\', this.value)"></label>' +
      '<label class="procedure-field"><span>Repeat count</span><input type="number" min="1" max="1000" step="1" value="' + htmlEscape(st.repeat_count) + '" oninput="procedureEditorSetField(\'repeat_count\', this.value)"></label>' +
    '</div>' +
    '<div class="action-editor-row">' +
      '<button class="btn btn-sm btn-green" onclick="procedureEditorSave()">Save</button>' +
    '</div>';
}

function procedureEditorSave() {
  if (!procedureEditorState) return;
  var st = procedureEditorState;
  var name = (st.name || '').trim();
  if (!name) { alert('Name required.'); return; }
  if (!st.gimbal_zero_drivers || !st.gimbal_zero_drivers.length) {
    alert('Select at least one zero driver.');
    return;
  }
  if (!st.arm_pose_a_setpoint_id || !st.arm_pose_b_setpoint_id) {
    alert('Select both arm poses.');
    return;
  }

  var gantryApproach = parseInt(st.gantry_approach_steps, 10);
  var dwellMs = parseInt(st.dwell_ms, 10);
  var repeatCount = parseInt(st.repeat_count, 10);
  if (isNaN(gantryApproach) || isNaN(dwellMs) || isNaN(repeatCount)) {
    alert('Approach, dwell, and repeat fields must be integers.');
    return;
  }

  var body = {
    name: name,
    gimbal_zero_drivers: st.gimbal_zero_drivers.slice(),
    arm_pose_a_setpoint_id: st.arm_pose_a_setpoint_id,
    arm_pose_b_setpoint_id: st.arm_pose_b_setpoint_id,
    gantry_approach_steps: gantryApproach,
    dwell_ms: dwellMs,
    repeat_count: repeatCount
  };

  var method, url;
  if (st.id) {
    method = 'PATCH';
    url = '/api/procedures/' + encodeURIComponent(st.id);
  } else {
    method = 'POST';
    url = '/api/procedures';
  }
  fetch(url, {
    method: method,
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(body)
  }).then(function(r) { return r.json().then(function(d) { return {ok: r.ok, body: d}; }); })
    .then(function(res) {
      if (!res.ok || !res.body.ok) {
        alert('Save failed: ' + ((res.body && res.body.error) || 'unknown'));
        return;
      }
      procedureCloseEditor();
      procedureRefresh();
    })
    .catch(function(e) { alert('Save request failed: ' + e); });
}

setInterval(actionStatePoll, 500);
setInterval(procedureStatePoll, 500);

/* ========== Init ========== */
(function() {
  /* SAFETY: neutrals MUST be fetched from the server before any code path
     that can move a servo (Go to Neutral, STARTUP, slider init). Previously
     chNeutral was hardcoded in JS and silently drifted out of sync with
     servo_neutral.json after the operator re-measured -- Go to Neutral
     would then drive to stale old positions. */
  fetch('/api/servo_neutral').then(function(r) { return r.json(); }).then(function(neutrals) {
    chOrder.forEach(function(name) {
      if (name === 'MACE') return;
      if (neutrals && neutrals[name] != null) chNeutral[name] = neutrals[name];
      var label = document.getElementById('chn_' + name);
      if (label) label.textContent = (chNeutral[name] != null ? chNeutral[name] : '?') + ' us';
    });
    chNeutralLoaded = true;
  }).catch(function() {
    /* Server unreachable. Leave chNeutralLoaded=false so getNeutral() returns
       null and Go to Neutral / STARTUP refuse to move anything. */
    console.error('[servo] failed to fetch /api/servo_neutral -- Go to Neutral/STARTUP disabled until next refresh');
  });

  /* Joint calibration (PW <-> angle). Failure is non-fatal: live angle
     display just reads '-' and the arm viz falls back to pre-calibration
     scaling. */
  fetch('/api/joint_calibration').then(function(r) { return r.json(); }).then(function(cal) {
    if (cal && typeof cal === 'object') jointCal = cal;
    jointCalLoaded = true;
  }).catch(function() {
    console.error('[cal] failed to fetch /api/joint_calibration');
  });

  setpointRefresh().then(function() {
    actionRefresh();
    procedureRefresh();
  });
  actionStatePoll();
  procedureStatePoll();

  /* Fetch last-known servo positions from server. Safe even before neutrals
     load: positions come fully specified from the server, no neutral fallback. */
  fetch('/api/servo_positions').then(function(r) { return r.json(); }).then(function(positions) {
    chOrder.forEach(function(name) {
      if (name === 'MACE') return;
      var pw = positions[name];
      if (pw == null) return;  // no stored position; leave slider at default
      chActual[name] = pw;
      var slider = document.getElementById('ch_' + name);
      if (slider) slider.value = pw;
      chUpdateLabel(name, pw);
    });
  }).catch(function() {
    /* Server unreachable - do NOT send PWM and do NOT seed chActual. */
  });

  /* Restore speed settings from localStorage */
  loadServoSettings();
  sendServoSettings();

  /* Server-side ramp heartbeat. Without it, the ramp freezes in place. */
  setInterval(function() {
    fetch('/api/heartbeat', {method: 'POST'}).catch(function() {});
  }, 1000);

  /* Start servo ramp loop (rate-limits all servo movements) */
  startServoRampLoop();

  /* Start polling */
  var hasControllerUi = !!document.getElementById('controllerToggleBtn');
  var hasArmVizUi = !!document.getElementById('armVizCanvas');
  setInterval(poll, 100);
  setInterval(sysPoll, 2000);
  setInterval(gimbalPoll, GIMBAL_POLL_MS);
  applyServoLimits();
  setInterval(servoSyncPoll, 500);
  setInterval(maceStatusPoll, 500);
  if (hasControllerUi) setInterval(controllerPoll, 250);
  if (hasArmVizUi) setInterval(ikRefreshStatus, 1000);

  /* Immediate calls */
  sysPoll();
  gimbalPoll();
  if (hasControllerUi) controllerPoll();
  maceApplyDefaultSettings();
  maceUpdateLabels();
  maceBindMomentaryButton('maceBackwardBtn', 'backward');
  maceBindMomentaryButton('maceBrakeBtn', 'brake');
  maceBindMomentaryButton('maceForwardBtn', 'forward');
  var maceCalBtn = document.getElementById('maceCalibrateBtn');
  if (maceCalBtn) maceCalBtn.addEventListener('click', maceCalibrate);
  maceStatusPoll();
  window.addEventListener('blur', maceReleaseAll);
  document.addEventListener('visibilitychange', function() {
    if (document.hidden) maceReleaseAll();
  });
  if (hasArmVizUi) ikRefreshStatus();
  updateVisionUI();
  loadCameraStreamState();
  if (hasArmVizUi) armVizStart();
})();
