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
      '<button class="btn btn-sm btn-dark" id="calibToggleBtn_' + name + '" onclick="calibToggle(&quot;' + name + '&quot;)">Calibrate</button>' +
      '</div>' +
      '<div class="servo-calib-mount" id="servoCalibMount_' + name + '"></div>';
    grid.appendChild(item);

    setTimeout(function() {
      var sl = document.getElementById('ch_' + name);
      if (sl) preventSliderJump(sl);
    }, 0);
  });
})();

/* ========== Joint Calibration UI ========== */
var calibCaptures = {};  // { name: {pw_A, angle_A_deg, pw_B, angle_B_deg} }
var calibDrafts = {};

function calibEnsureCh(name) {
  if (!calibCaptures[name]) calibCaptures[name] = {};
  return calibCaptures[name];
}

function calibEnsureDraft(name) {
  if (!calibDrafts[name]) calibDrafts[name] = {A: '', B: ''};
  return calibDrafts[name];
}

function calibDraftAngle(name, key, value) {
  var draft = calibEnsureDraft(name);
  draft[key] = value;
}

function calibCaptureA(name) {
  var slider = document.getElementById('ch_' + name);
  var angInp = document.getElementById('calibAngA_' + name);
  if (!slider || !angInp) return;
  var deg = parseFloat(angInp.value);
  if (isNaN(deg)) { alert('Enter angle A (degrees) first'); return; }
  var c = calibEnsureCh(name);
  calibEnsureDraft(name).A = angInp.value;
  c.pw_A = parseInt(slider.value);
  c.angle_A_deg = deg;
  renderCalibrationPanel();
}

function calibCaptureB(name) {
  var slider = document.getElementById('ch_' + name);
  var angInp = document.getElementById('calibAngB_' + name);
  if (!slider || !angInp) return;
  var deg = parseFloat(angInp.value);
  if (isNaN(deg)) { alert('Enter angle B (degrees) first'); return; }
  var c = calibEnsureCh(name);
  calibEnsureDraft(name).B = angInp.value;
  c.pw_B = parseInt(slider.value);
  c.angle_B_deg = deg;
  renderCalibrationPanel();
}

function calibSolve(name) {
  var c = calibCaptures[name];
  if (!c || c.pw_A == null || c.pw_B == null) {
    alert('Capture both A and B first');
    return;
  }
  fetch('/api/joint_calibration/solve', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({
      channel: name,
      pw_A: c.pw_A, angle_A_rad: degToRad(c.angle_A_deg),
      pw_B: c.pw_B, angle_B_rad: degToRad(c.angle_B_deg),
    })
  }).then(function(r) { return r.json(); }).then(function(d) {
    if (!d.ok) { alert('Solve failed: ' + (d.error || 'unknown')); return; }
    jointCal[name] = d.calibration;
    delete calibCaptures[name];
    delete calibDrafts[name];
    renderCalibrationPanel();
    // Update live angle labels with the new calibration.
    chOrder.forEach(function(n) {
      if (n === 'MACE') return;
      var slider = document.getElementById('ch_' + n);
      if (slider) chUpdateLabel(n, slider.value);
    });
  }).catch(function(e) { alert('Solve request failed: ' + e); });
}

function calibReset(name) {
  delete calibCaptures[name];
  delete calibDrafts[name];
  renderCalibrationPanel();
}

function calibPatch(name, field, value) {
  var body = {channel: name};
  body[field] = value;
  fetch('/api/joint_calibration', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(body)
  }).then(function(r) { return r.json(); }).then(function(d) {
    if (!d.ok) { alert('Update failed: ' + (d.error || 'unknown')); return; }
    jointCal[name] = d.calibration;
    renderCalibrationPanel();
  });
}

function renderCalibrationPanel() {
  var grid = document.getElementById('calibGrid');
  if (grid) {
    grid.innerHTML =
      '<div class="servo-inline-guide">' +
        '<div class="servo-inline-guide-title">Inline calibration</div>' +
        '<div class="servo-inline-guide-copy">Open a joint row to capture pose A and B, solve, then patch angle limits. Base 0° is forward. Shoulder and elbow 0° are extended. Wrist 0° is aligned with the bicep.</div>' +
      '</div>';
  }
  var expanded = calibExpanded;
  chOrder.forEach(function(name) {
    if (name === 'MACE') return;
    var c = calibCaptures[name] || {};
    var draft = calibEnsureDraft(name);
    var cal = jointCal[name] || {};
    var isOpen = expanded === name;
    var mount = document.getElementById('servoCalibMount_' + name);
    var item = document.getElementById('chitem_' + name);
    var toggleBtn = document.getElementById('calibToggleBtn_' + name);
    if (item) item.classList.toggle('servo-row-calibrating', isOpen);
    if (toggleBtn) {
      toggleBtn.textContent = isOpen ? 'Close' : 'Calibrate';
      toggleBtn.className = isOpen ? 'btn btn-sm btn-amber' : 'btn btn-sm btn-dark';
      toggleBtn.setAttribute('aria-expanded', isOpen ? 'true' : 'false');
    }
    if (!mount) return;
    if (!isOpen) {
      mount.innerHTML = '';
      return;
    }
    var neutralDeg = cal.neutral_angle_rad != null ? radToDeg(cal.neutral_angle_rad).toFixed(1) + '°' : '--';
    var minDeg = cal.min_angle_rad != null ? radToDeg(cal.min_angle_rad).toFixed(1) : '';
    var maxDeg = cal.max_angle_rad != null ? radToDeg(cal.max_angle_rad).toFixed(1) : '';
    var signStr = cal.sign != null ? (cal.sign > 0 ? '+' : '-') : '--';
    var usrStr = cal.us_per_rad != null ? cal.us_per_rad.toFixed(0) : '--';
    var capAstr = c.pw_A != null ? (c.pw_A + ' us -> ' + c.angle_A_deg + '°') : 'Not captured';
    var capBstr = c.pw_B != null ? (c.pw_B + ' us -> ' + c.angle_B_deg + '°') : 'Not captured';
    var canSolve = c.pw_A != null && c.pw_B != null;
    mount.innerHTML =
      '<div class="servo-calib-panel">' +
        '<div class="servo-calib-header">' +
          '<div>' +
            '<div class="servo-calib-title">Joint calibration</div>' +
            '<div class="servo-calib-subtitle">Live <span id="calibCur_' + name + '">--</span></div>' +
          '</div>' +
          '<div class="servo-calib-summary">' +
            '<span>' + usrStr + ' us/rad</span>' +
            '<span>sign ' + signStr + '</span>' +
            '<span>neutral ' + neutralDeg + '</span>' +
          '</div>' +
        '</div>' +
        '<div class="servo-calib-capture-grid">' +
          '<div class="servo-calib-capture-card">' +
            '<label class="servo-calib-field">' +
              '<span>Pose A angle</span>' +
              '<input type="number" step="1" id="calibAngA_' + name + '" value="' + draft.A + '" placeholder="deg" oninput="calibDraftAngle(\'' + name + '\', \'A\', this.value)">' +
            '</label>' +
            '<button class="btn btn-sm" onclick="calibCaptureA(\'' + name + '\')">Capture A</button>' +
            '<div class="servo-calib-capture-readout">' + capAstr + '</div>' +
          '</div>' +
          '<div class="servo-calib-capture-card">' +
            '<label class="servo-calib-field">' +
              '<span>Pose B angle</span>' +
              '<input type="number" step="1" id="calibAngB_' + name + '" value="' + draft.B + '" placeholder="deg" oninput="calibDraftAngle(\'' + name + '\', \'B\', this.value)">' +
            '</label>' +
            '<button class="btn btn-sm" onclick="calibCaptureB(\'' + name + '\')">Capture B</button>' +
            '<div class="servo-calib-capture-readout">' + capBstr + '</div>' +
          '</div>' +
        '</div>' +
        '<div class="servo-calib-footer">' +
          '<div class="servo-calib-button-row">' +
            '<button class="btn btn-sm btn-green" ' + (canSolve ? '' : 'disabled') + ' onclick="calibSolve(\'' + name + '\')">Solve</button>' +
            '<button class="btn btn-sm btn-dark" onclick="calibReset(\'' + name + '\')">Clear</button>' +
          '</div>' +
          '<div class="servo-calib-limit-row">' +
            '<label class="servo-calib-field servo-calib-field-small">' +
              '<span>Min deg</span>' +
              '<input type="number" step="1" value="' + minDeg + '" onchange="calibPatch(\'' + name + '\', \'min_angle_rad\', this.value === \'\' ? null : degToRad(parseFloat(this.value)))">' +
            '</label>' +
            '<label class="servo-calib-field servo-calib-field-small">' +
              '<span>Max deg</span>' +
              '<input type="number" step="1" value="' + maxDeg + '" onchange="calibPatch(\'' + name + '\', \'max_angle_rad\', this.value === \'\' ? null : degToRad(parseFloat(this.value)))">' +
            '</label>' +
          '</div>' +
        '</div>' +
      '</div>';
  });
  refreshCalibLive();
}

function refreshCalibLive() {
  chOrder.forEach(function(name) {
    if (name === 'MACE') return;
    var slider = document.getElementById('ch_' + name);
    var curEl = document.getElementById('calibCur_' + name);
    if (!slider || !curEl) return;
    var rad = pwToAngleRad(name, parseInt(slider.value));
    curEl.textContent = slider.value + ' us' + (rad == null ? '' : ' · ' + radToDeg(rad).toFixed(1) + '°');
  });
}

var calibExpanded = null;
function calibToggle(name) {
  calibExpanded = (calibExpanded === name) ? null : name;
  renderCalibrationPanel();
}

setInterval(function() {
  if (document.getElementById('calibGrid')) refreshCalibLive();
}, 500);

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
var maceJogHeartbeatTimer = null;
var maceJogReady = false;
var maceJogCalibrating = false;
var maceJogPendingDirection = null;
var maceJogRequestSeq = 0;

function maceCfg() {
  return {
    accel_ramp: parseFloat(document.getElementById('maceAccelRamp').value || '5') || 5,
    brake_ramp: parseFloat(document.getElementById('maceBrakeRamp').value || '12') || 12,
    max_voltage: parseFloat(document.getElementById('maceVoltage').value || '12') || 12
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

function maceStartHeartbeat(direction) {
  if (maceJogHeartbeatTimer) clearInterval(maceJogHeartbeatTimer);
  maceJogHeartbeatTimer = setInterval(function() {
    fetch('/api/mace/jog/heartbeat', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({direction: direction})
    }).catch(function() {});
  }, 100);
}

function maceStopHeartbeat() {
  if (maceJogHeartbeatTimer) clearInterval(maceJogHeartbeatTimer);
  maceJogHeartbeatTimer = null;
}

function maceJogStart(direction) {
  if (!maceJogReady || maceJogCalibrating) return;
  maceJogPendingDirection = direction;
  var reqSeq = ++maceJogRequestSeq;
  var cfg = maceCfg();
  fetch('/api/mace/jog/start', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({
      direction: direction,
      accel_ramp: cfg.accel_ramp,
      brake_ramp: cfg.brake_ramp,
      max_voltage: cfg.max_voltage
    })
  }).then(function(r) { return r.json(); }).then(function(d) {
    var note = document.getElementById('maceJogNote');
    if (reqSeq !== maceJogRequestSeq || maceJogPendingDirection !== direction) {
      fetch('/api/mace/jog/stop', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({})
      }).catch(function() {});
      return;
    }
    if (d.ok === false) {
      if (note) note.textContent = d.error || 'MACE jog start failed';
      maceJogActive = null;
      maceJogPendingDirection = null;
      maceSetButtons(null);
      maceStopHeartbeat();
      return;
    }
    maceJogActive = direction;
    maceJogPendingDirection = null;
    maceSetButtons(direction);
    maceStartHeartbeat(direction);
    maceRenderStatus(d);
  }).catch(function(err) {
    var note = document.getElementById('maceJogNote');
    if (note) note.textContent = 'MACE jog start failed: ' + err;
    maceJogActive = null;
    maceJogPendingDirection = null;
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

function maceJogStop() {
  maceJogRequestSeq += 1;
  maceJogPendingDirection = null;
  maceStopHeartbeat();
  fetch('/api/mace/jog/stop', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({})
  }).then(function(r) { return r.json(); }).then(function(d) {
    maceJogActive = null;
    maceSetButtons(null);
    maceRenderStatus(d);
  }).catch(function(err) {
    var note = document.getElementById('maceJogNote');
    maceJogActive = null;
    maceSetButtons(null);
    if (note) note.textContent = 'MACE jog stop failed: ' + err;
  });
}

function maceReleaseAll() {
  if (!maceJogActive && !maceJogPendingDirection) return;
  maceJogStop();
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
    if (ev && ev.pointerId != null && btn.setPointerCapture) btn.setPointerCapture(ev.pointerId);
    if (maceJogActive && maceJogActive !== direction) maceJogStop();
    if (maceJogActive === direction || maceJogPendingDirection === direction) return;
    maceJogStart(direction);
  }
  function release(ev) {
    if (ev) ev.preventDefault();
    if (activePointerId === null) return;
    if (ev && ev.pointerId != null && btn.releasePointerCapture) {
      try { btn.releasePointerCapture(ev.pointerId); } catch (e) {}
    }
    activePointerId = null;
    if (maceJogActive === direction || maceJogPendingDirection === direction) maceJogStop();
  }
  btn.addEventListener('pointerdown', press);
  btn.addEventListener('pointerup', release);
  btn.addEventListener('pointercancel', release);
  btn.addEventListener('lostpointercapture', release);
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
    if (typeof renderCalibrationPanel === 'function') renderCalibrationPanel();
  }).catch(function() {
    console.error('[cal] failed to fetch /api/joint_calibration');
  });

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
  maceUpdateLabels();
  maceBindMomentaryButton('maceBackwardBtn', 'backward');
  maceBindMomentaryButton('maceBrakeBtn', 'brake');
  maceBindMomentaryButton('maceForwardBtn', 'forward');
  var maceCalBtn = document.getElementById('maceCalibrateBtn');
  if (maceCalBtn) maceCalBtn.addEventListener('click', maceCalibrate);
  maceStatusPoll();
  window.addEventListener('blur', maceReleaseAll);
  window.addEventListener('mouseup', maceReleaseAll);
  window.addEventListener('touchend', maceReleaseAll, {passive: false});
  window.addEventListener('pointerup', maceReleaseAll);
  window.addEventListener('pointercancel', maceReleaseAll);
  if (hasArmVizUi) ikRefreshStatus();
  updateVisionUI();
  loadCameraStreamState();
  if (hasArmVizUi) armVizStart();
})();
