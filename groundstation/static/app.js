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
  "W2B": {ch: 0, pin: 1}, "W2A": {ch: 1, pin: 2}, "W1B": {ch: 2, pin: 3},
  "W1A": {ch: 3, pin: 4}, "E2": {ch: 4, pin: 5}, "E1": {ch: 6, pin: 7},
  "MACE": {ch: 11, pin: 12}, "S2": {ch: 12, pin: 13}, "B2": {ch: 13, pin: 14},
  "S1": {ch: 14, pin: 15}, "B1": {ch: 15, pin: 16}
};
var chOrder = ["B1","B2","S1","S2","E1","E2","W1A","W2A","W1B","W2B","MACE"];
var CH_RAMP_HZ = 30;
var chActual = {};  // actual PWM value sent to hardware per channel

/* Per-channel neutral positions (server-side, persisted to disk) */
var chNeutral = {};

var controllerStatus = {enabled: false};
var activePageTab = 'manual';
var missionPanelModes = {
  mission: {title: 'Mission Simulation', subtitle: 'Dev-only autonomous workflow sandbox.', badge: 'mizi-dev only'},
  competition: {title: 'MACE Competition', subtitle: 'Competition-mode autonomous workflow sandbox.', badge: 'mizi-dev only'}
};

function missionFlowSequence() {
  return activePageTab === 'competition' ? [1,2,3,4,5,6,7,8] : [1,2,3,4,5,6,7,8,9,10];
}

function missionNextStep(step) {
  var seq = missionFlowSequence();
  var idx = seq.indexOf(step);
  if (idx === -1) return seq[0];
  return seq[Math.min(seq.length - 1, idx + 1)];
}

function missionStepVisible(step) {
  return missionFlowSequence().indexOf(step) !== -1;
}

function missionDefaultState() {
  return {
    currentStep: 1,
    started: false,
    halted: false,
    armed: false,
    nominalCheckResolved: false,
    everythingNominalResolved: false,
    allIdentifiedResolved: false,
    dockingPoseResolved: false,
    undockingReadyResolved: false,
    aocsNominalResolved: false,
    aocsSlideOutResolved: false,
    aocsArmDetachResolved: false,
    maceState: 'SAFE',
    searchRotationSpeed: 1.5,
    searchLockError: null,
    searchLockCommand: 0.0,
    rotationEstimateRpm: null,
    rotationStableToleranceRpm: 3.0,
    rotationStableSeconds: 3.0,
    demoSequenceState: 'IDLE',
    demoCommandAngle: null,
    rotationMatchActive: false,
    rotationMatchTargetRpm: null,
    substeps: {
      2: { 'snoopy-detect': false, 'mace': false },
      4: { 'search-snoopy': false, 'snoopy-found': false, 'snoopy-lock': false },
      5: { 'rotation-finder-model': false, 'rotation-found': false },
      6: { '45-degree-commands': false, 'rotation-matching': false },
      7: {},
      8: {},
      9: { 'backed-away': false },
      10: {}
    }
  };
}

var missionFlowState = missionDefaultState();
var competitionSyncBusy = false;
var competitionInitialResetDone = false;

function missionFormatDetectionPoint(point) {
  if (!point || point.x == null || point.y == null) return '--';
  return 'x:' + point.x.toFixed(2) + ' y:' + point.y.toFixed(2);
}

function missionFormatDetectionSize(size) {
  if (!size || size.w == null || size.h == null) return '--';
  return 'w:' + size.w.toFixed(2) + ' h:' + size.h.toFixed(2);
}

function missionClamp01(value) {
  if (typeof value !== 'number' || !isFinite(value)) return 0;
  return Math.max(0, Math.min(1, value));
}

function missionSyncMlFeed() {
  var modelEl = document.getElementById('missionMlFeedModel');
  var stateEl = document.getElementById('missionMlFeedState');
  var classEl = document.getElementById('missionMlClass');
  var confidenceEl = document.getElementById('missionMlConfidence');
  var centerEl = document.getElementById('missionMlCenter');
  var sizeEl = document.getElementById('missionMlSize');
  var bboxEl = document.getElementById('missionMlBBox');
  var detection = missionFlowState.snoopyDetection || null;
  var activeModel = missionFlowState.activeVisionModel;
  var feedModelLabel = 'MODEL STANDBY';
  var feedStateLabel = 'IDLE';

  if (activePageTab === 'competition') {
    if (activeModel) {
      var activeModelName = visionState.models[activeModel - 1] || ('Model ' + activeModel);
      feedModelLabel = ('MODEL ' + activeModel + ' | ' + activeModelName).toUpperCase();
      feedStateLabel = (missionFlowState.visionState || 'IDLE').toUpperCase();
    }
  } else {
    if (visionState.status !== 'STANDBY') {
      feedModelLabel = missionCurrentModelLabel();
      feedStateLabel = visionState.status.toUpperCase();
    }
  }

  if (modelEl) modelEl.textContent = feedModelLabel;
  if (stateEl) stateEl.textContent = feedStateLabel;
  if (classEl) classEl.textContent = detection && detection.class_label ? detection.class_label.toUpperCase() : '--';
  if (confidenceEl) confidenceEl.textContent = detection && detection.confidence != null ? detection.confidence.toFixed(2) : '--';
  if (centerEl) centerEl.textContent = missionFormatDetectionPoint(detection && detection.bbox_center);
  if (sizeEl) sizeEl.textContent = missionFormatDetectionSize(detection && detection.bbox_size);

  if (!bboxEl) return;
  var center = detection && detection.bbox_center;
  var size = detection && detection.bbox_size;
  if (center && size && center.x != null && center.y != null && size.w != null && size.h != null) {
    var left = missionClamp01(center.x - (size.w / 2));
    var top = missionClamp01(center.y - (size.h / 2));
    var width = missionClamp01(size.w);
    var height = missionClamp01(size.h);
    bboxEl.style.left = (left * 100) + '%';
    bboxEl.style.top = (top * 100) + '%';
    bboxEl.style.width = (width * 100) + '%';
    bboxEl.style.height = (height * 100) + '%';
    bboxEl.classList.add('active');
  } else {
    bboxEl.classList.remove('active');
    bboxEl.style.left = '';
    bboxEl.style.top = '';
    bboxEl.style.width = '';
    bboxEl.style.height = '';
  }
}

function competitionSyncState(state) {
  if (!state) return;
  missionFlowState.currentStep = state.currentStep || 1;
  missionFlowState.started = !!state.started;
  missionFlowState.halted = !!state.halted;
  missionFlowState.armed = !!state.armed;
  missionFlowState.nominalCheckResolved = !!state.nominalCheckResolved;
  missionFlowState.everythingNominalResolved = !!state.everythingNominalResolved;
  missionFlowState.allIdentifiedResolved = !!state.allIdentifiedResolved;
  missionFlowState.dockingPoseResolved = !!state.dockingPoseResolved;
  missionFlowState.undockingReadyResolved = !!state.undockingReadyResolved;
  missionFlowState.aocsNominalResolved = !!state.aocsNominalResolved;
  missionFlowState.aocsSlideOutResolved = !!state.aocsSlideOutResolved;
  missionFlowState.aocsArmDetachResolved = !!state.aocsArmDetachResolved;
  missionFlowState.maceState = state.maceState || 'SAFE';
  missionFlowState.searchRotationSpeed = state.searchRotationSpeed != null ? state.searchRotationSpeed : 1.5;
  missionFlowState.searchLockError = state.searchLockError != null ? state.searchLockError : null;
  missionFlowState.searchLockCommand = state.searchLockCommand != null ? state.searchLockCommand : 0.0;
  missionFlowState.rotationEstimateRpm = state.rotationEstimateRpm != null ? state.rotationEstimateRpm : null;
  missionFlowState.rotationStableToleranceRpm = state.rotationStableToleranceRpm != null ? state.rotationStableToleranceRpm : 3.0;
  missionFlowState.rotationStableSeconds = state.rotationStableSeconds != null ? state.rotationStableSeconds : 3.0;
  missionFlowState.demoSequenceState = state.demoSequenceState || 'IDLE';
  missionFlowState.demoCommandAngle = state.demoCommandAngle != null ? state.demoCommandAngle : null;
  missionFlowState.rotationMatchActive = !!state.rotationMatchActive;
  missionFlowState.rotationMatchTargetRpm = state.rotationMatchTargetRpm != null ? state.rotationMatchTargetRpm : null;
  missionFlowState.activeVisionModel = state.activeVisionModel || null;
  missionFlowState.visionState = state.visionState || 'IDLE';
  missionFlowState.snoopyDetection = state.snoopyDetection || null;
  if (state.substeps) missionFlowState.substeps = state.substeps;
}

function competitionFetchStatus() {
  if (competitionSyncBusy) return;
  competitionSyncBusy = true;
  fetch('/api/competition/status').then(function(r) { return r.json(); }).then(function(state) {
    if (!competitionInitialResetDone &&
        state &&
        !state.armed &&
        !state.running &&
        (state.currentStep !== 1 ||
         state.started ||
         state.halted ||
         state.nominalCheckResolved ||
         state.everythingNominalResolved ||
         state.allIdentifiedResolved ||
         state.dockingPoseResolved ||
         state.undockingReadyResolved ||
         state.aocsNominalResolved ||
         state.aocsSlideOutResolved ||
         state.aocsArmDetachResolved)) {
      competitionInitialResetDone = true;
      return competitionPost('/api/competition/reset', {});
    }
    competitionSyncState(state);
    missionSyncSummary();
  }).catch(function() {
  }).finally(function() {
    competitionSyncBusy = false;
  });
}

function competitionPost(path, body) {
  return fetch(path, {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(body || {})
  }).then(function(r) { return r.json(); }).then(function(resp) {
    if (resp && resp.state) {
      competitionSyncState(resp.state);
      missionSyncSummary();
    }
    return resp;
  });
}

function showPageTab(tab) {
  activePageTab = (tab === 'mission' || tab === 'competition') ? tab : 'manual';
  var manualBtn = document.getElementById('pageTabManual');
  var missionBtn = document.getElementById('pageTabMission');
  var competitionBtn = document.getElementById('pageTabCompetition');
  var manualPanel = document.getElementById('pagePanelManual');
  var missionPanel = document.getElementById('pagePanelMission');
  if (manualBtn) manualBtn.classList.toggle('active', activePageTab === 'manual');
  if (missionBtn) missionBtn.classList.toggle('active', activePageTab === 'mission');
  if (competitionBtn) competitionBtn.classList.toggle('active', activePageTab === 'competition');
  if (manualPanel) manualPanel.classList.toggle('active', activePageTab === 'manual');
  if (missionPanel) missionPanel.classList.toggle('active', activePageTab === 'mission' || activePageTab === 'competition');
  var mode = missionPanelModes[activePageTab] || missionPanelModes.mission;
  var modelRow3 = document.getElementById('missionModelRow3');
  var missionArmCard = document.getElementById('missionArmVizCard');
  var missionStackCard = document.querySelector('.mission-stack-card');
  if (modelRow3) modelRow3.style.display = activePageTab === 'competition' ? 'none' : '';
  if (missionArmCard) missionArmCard.style.display = activePageTab === 'competition' ? 'none' : '';
  if (missionStackCard) missionStackCard.style.gridColumn = activePageTab === 'competition' ? '4 / span 2' : '5';
  if (activePageTab === 'competition' && missionFlowSequence().indexOf(missionFlowState.currentStep) === -1) missionFlowState.currentStep = 1;
  var title = document.getElementById('missionPanelTitle');
  var subtitle = document.getElementById('missionPanelSubtitle');
  var badge = document.getElementById('missionPanelBadge');
  if (title) title.textContent = mode.title;
  if (subtitle) subtitle.textContent = mode.subtitle;
  if (badge) badge.textContent = mode.badge;
  missionSyncSummary();
  if (activePageTab === 'competition') competitionFetchStatus();
}

function missionStepName(step) {
  if (activePageTab === 'competition') {
    var competitionNames = {
      1: 'MISSION START',
      2: 'STARTUP',
      3: 'EVERYTHING NOMINAL CHECK',
      4: 'FIND SNOOPY',
      5: 'SNOOPY ROTATION',
      6: 'MACE CAPABILITY DEMO',
      7: 'SATISFACTION CHECK',
      8: 'MISSION COMPLETE'
    };
    return competitionNames[step] || 'MISSION START';
  }
  var names = {
    1: 'MISSION START',
    2: 'ALL JOINTS NEUTRAL CHECK',
    3: 'EVERYTHING NOMINAL CHECK',
    4: 'ALL IDENTIFIED CHECK',
    5: 'APPROACH',
    6: 'DOCKING',
    7: 'UNDOCKING',
    8: 'AOCS MODULE ATTACH',
    9: 'BACK AWAY',
    10: 'MISSION COMPLETE'
  };
  return names[step] || 'MISSION START';
}

function missionCurrentModelLabel() {
  var modelEls = [1,2,3].map(function(i) { return document.getElementById('missionModel' + i); });
  var models = modelEls.map(function(el) { return el ? el.textContent : 'UNSET'; });
  if (activePageTab === 'competition') {
    if (missionFlowState.currentStep <= 4) return models[0] && models[0] !== 'UNSET' ? models[0] : 'MODEL 1 STANDBY';
    return models[1] && models[1] !== 'UNSET' ? models[1] : 'MODEL 2 UNSET';
  }
  if (missionFlowState.currentStep <= 3) return models[0] && models[0] !== 'UNSET' ? models[0] : 'MODEL 1 STANDBY';
  if (missionFlowState.currentStep <= 5) return models[0] && models[0] !== 'UNSET' ? models[0] : 'MODEL 1 UNSET';
  if (missionFlowState.currentStep <= 7) return models[1] && models[1] !== 'UNSET' ? models[1] : 'MODEL 2 UNSET';
  return models[2] && models[2] !== 'UNSET' ? models[2] : 'MODEL 3 UNSET';
}

function missionArmStatusText(side) {
  if (missionFlowState.halted) return 'STOPPED';
  if (!missionFlowState.armed) return 'STANDBY';
  var step = missionFlowState.currentStep;
  if (activePageTab === 'competition') {
    if (step === 2) return 'NEUTRAL CHECK';
    if (step === 3) return 'NOMINAL CHECK';
    if (step === 4) return 'SNOOPY SEARCH';
    if (step === 5) return 'ROTATION ANALYSIS';
    if (step === 6) return side === 'left' ? 'ANGLE COMMANDS' : 'ROTATION MATCHING';
    if (step === 7) return 'SATISFACTION CHECK';
    if (step === 8) return 'COMPLETE';
    return 'STANDBY';
  }
  if (step === 2) return 'NEUTRAL CHECK';
  if (step === 3) return 'NOMINAL CHECK';
  if (step === 4) return 'TARGET VERIFY';
  if (step === 5) return 'APPROACHING';
  if (step === 6) return 'DOCKING';
  if (step === 7) return 'UNDOCKING';
  if (step === 8) return side === 'left' ? 'AOCS ATTACHING' : 'STABILIZING';
  if (step === 9) return 'BACKING AWAY';
  if (step === 10) return 'COMPLETE';
  return 'STANDBY';
}

function missionToggleReady() {
  if (activePageTab === 'competition') {
    competitionPost('/api/competition/arm', {armed: !missionFlowState.armed});
    return;
  }
  missionFlowState.armed = !missionFlowState.armed;
  if (!missionFlowState.armed && !missionFlowState.halted) missionFlowState.currentStep = Math.max(1, missionFlowState.currentStep);
  missionSetState(missionFlowState.armed ? 'ARMED' : 'SAFE');
  missionRenderFlow();
}

function missionRunSimulation() {
  if (activePageTab === 'competition') {
    competitionPost('/api/competition/run', {});
    return;
  }
  if (!missionFlowState.armed || missionFlowState.halted) return;
  missionSetState('RUNNING');
}

function missionEmergencyStop() {
  if (activePageTab === 'competition') {
    competitionPost('/api/competition/estop', {});
    return;
  }
  missionFlowState.halted = true;
  missionFlowState.armed = false;
  missionSetState('STOPPED');
  missionRenderFlow();
}

function missionResetSimulation() {
  if (activePageTab === 'competition') {
    competitionPost('/api/competition/estop', {}).then(function() {
      return competitionPost('/api/competition/reset', {});
    });
    return;
  }
  missionEmergencyStop();
  missionFlowState = missionDefaultState();
  missionSetState('MISSION START');
  missionRenderFlow();
}

function missionIsStepComplete(step) {
  if (activePageTab === 'competition') {
    if (step === 1) return !!missionFlowState.nominalCheckResolved;
    if (step === 2) return missionFlowState.substeps[2]['snoopy-detect'] && missionFlowState.substeps[2]['mace'];
    if (step === 3) return !!missionFlowState.everythingNominalResolved;
    if (step === 4) return !!missionFlowState.allIdentifiedResolved && missionFlowState.substeps[4]['search-snoopy'] && missionFlowState.substeps[4]['snoopy-found'] && missionFlowState.substeps[4]['snoopy-lock'];
    if (step === 5) return !!missionFlowState.dockingPoseResolved && missionFlowState.substeps[5]['rotation-finder-model'] && missionFlowState.substeps[5]['rotation-found'];
    if (step === 6) return !!missionFlowState.undockingReadyResolved && !!missionFlowState.aocsNominalResolved && !!missionFlowState.aocsSlideOutResolved && missionFlowState.substeps[6]['45-degree-commands'] && missionFlowState.substeps[6]['rotation-matching'];
    if (step === 7) return !!missionFlowState.aocsArmDetachResolved;
    if (step === 8) return missionIsStepComplete(7);
  }
  if (step === 1) return !!missionFlowState.nominalCheckResolved;
  if (step === 3) return !!missionFlowState.everythingNominalResolved;
  if (step === 4) return !!missionFlowState.allIdentifiedResolved && missionFlowState.substeps[4]['client-rotation-model'] && missionFlowState.substeps[4]['client-rotation'] && missionFlowState.substeps[4]['docking-point'] && missionFlowState.substeps[4]['nozzle-identify-model'];
  if (step === 6) return !!missionFlowState.dockingPoseResolved && missionFlowState.substeps[6]['relative-motion-stabilized'] && missionFlowState.substeps[6]['nozzle-position-found'] && missionFlowState.substeps[6]['nozzle-ik-solved'] && missionFlowState.substeps[6]['docked'];
  if (step === 7) return !!missionFlowState.undockingReadyResolved && missionFlowState.substeps[7]['client-brought-to-geo'] && missionFlowState.substeps[7]['undocked'];
  if (step === 8) return !!missionFlowState.aocsNominalResolved && !!missionFlowState.aocsSlideOutResolved && !!missionFlowState.aocsArmDetachResolved && missionFlowState.substeps[8]['aocs-pose-ready'] && missionFlowState.substeps[8]['aocs-attach'];
  if (step === 10) return activePageTab === 'competition' ? missionIsStepComplete(8) : missionIsStepComplete(9);
  var substeps = missionFlowState.substeps[step] || {};
  var keys = Object.keys(substeps);
  return keys.length > 0 && keys.every(function(key) { return !!substeps[key]; });
}

function missionSetCheckpointActions(actionsEl, enabled) {
  if (!actionsEl) return;
  actionsEl.style.display = 'flex';
  actionsEl.querySelectorAll('button').forEach(function(btn) {
    btn.disabled = !enabled;
  });
}

function missionRenderFlow() {
  var checkpoint = document.getElementById('missionStartCheckpoint');
  var label = checkpoint ? checkpoint.querySelector('.mission-substep-label') : null;
  var actions = checkpoint ? checkpoint.querySelector('.mission-checkpoint-actions') : null;
  var checkpointTwo = document.getElementById('missionEverythingNominalCheckpoint');
  var labelTwo = checkpointTwo ? checkpointTwo.querySelector('.mission-substep-label') : null;
  var actionsTwo = checkpointTwo ? checkpointTwo.querySelector('.mission-checkpoint-actions') : null;
  var checkpointIdent = document.getElementById('missionAllIdentifiedCheckpoint');
  var labelIdent = checkpointIdent ? checkpointIdent.querySelector('.mission-substep-label') : null;
  var actionsIdent = checkpointIdent ? checkpointIdent.querySelector('.mission-checkpoint-actions') : null;
  var checkpointThree = document.getElementById('missionDockingPoseCheckpoint');
  var labelThree = checkpointThree ? checkpointThree.querySelector('.mission-substep-label') : null;
  var actionsThree = checkpointThree ? checkpointThree.querySelector('.mission-checkpoint-actions') : null;
  var checkpointFour = document.getElementById('missionUndockingReadyCheckpoint');
  var labelFour = checkpointFour ? checkpointFour.querySelector('.mission-substep-label') : null;
  var actionsFour = checkpointFour ? checkpointFour.querySelector('.mission-checkpoint-actions') : null;
  var checkpointFive = document.getElementById('missionAocsNominalCheckpoint');
  var labelFive = checkpointFive ? checkpointFive.querySelector('.mission-substep-label') : null;
  var actionsFive = checkpointFive ? checkpointFive.querySelector('.mission-checkpoint-actions') : null;
  var checkpointSix = document.getElementById('missionAocsSlideOutCheckpoint');
  var labelSix = checkpointSix ? checkpointSix.querySelector('.mission-substep-label') : null;
  var actionsSix = checkpointSix ? checkpointSix.querySelector('.mission-checkpoint-actions') : null;
  var checkpointSeven = document.getElementById('missionAocsArmDetachCheckpoint');
  var labelSeven = checkpointSeven ? checkpointSeven.querySelector('.mission-substep-label') : null;
  var actionsSeven = checkpointSeven ? checkpointSeven.querySelector('.mission-checkpoint-actions') : null;
  var missionStateEl = document.getElementById('missionState');
  var missionActiveVisionModelEl = document.getElementById('missionActiveVisionModel');
  var missionLeftArmStatusEl = document.getElementById('missionLeftArmStatus');
  var missionRightArmStatusEl = document.getElementById('missionRightArmStatus');
  var missionReadyBtn = document.getElementById('missionReadyBtn');
  var missionRunBtn = document.getElementById('missionRunBtn');
  if (missionStateEl) missionStateEl.textContent = missionFlowState.halted ? 'STOPPED AT ' + missionStepName(missionFlowState.currentStep) : missionStepName(missionFlowState.currentStep);
  if (missionActiveVisionModelEl) missionActiveVisionModelEl.textContent = missionCurrentModelLabel();
  if (missionLeftArmStatusEl) missionLeftArmStatusEl.textContent = missionArmStatusText('left');
  if (missionRightArmStatusEl) missionRightArmStatusEl.textContent = missionArmStatusText('right');
  if (missionReadyBtn) missionReadyBtn.textContent = missionFlowState.armed ? 'Armed' : 'Ready';
  if (missionRunBtn) missionRunBtn.disabled = !missionFlowState.armed || missionFlowState.halted;
  for (var i = 1; i <= 10; i += 1) {
    var step = document.getElementById('missionStep' + i);
    if (!step) continue;
    var visible = missionStepVisible(i);
    var isComplete = missionIsStepComplete(i);
    step.style.display = visible ? '' : 'none';
    step.classList.toggle('active', visible && i === missionFlowState.currentStep && !missionFlowState.halted && !isComplete);
    step.classList.toggle('completed', visible && isComplete);
    step.classList.toggle('blocked', visible && missionFlowState.halted && i === missionFlowState.currentStep);
  }
  if (label) {
    if (missionFlowState.halted) label.textContent = 'Nominal environment check failed';
    else if (missionFlowState.nominalCheckResolved) label.textContent = 'Nominal environment check cleared';
    else label.textContent = 'Nominal environment check';
  }
  if (checkpoint) {
    checkpoint.classList.toggle('active', missionFlowState.currentStep === 1 && !missionFlowState.nominalCheckResolved && !missionFlowState.halted);
    checkpoint.classList.toggle('completed', !!missionFlowState.nominalCheckResolved);
    checkpoint.classList.toggle('blocked', missionFlowState.halted && missionFlowState.currentStep === 1);
  }
  missionSetCheckpointActions(actions, activePageTab === 'competition'
    ? missionFlowState.currentStep === 1 && missionFlowState.armed && missionFlowState.started && !missionFlowState.nominalCheckResolved && !missionFlowState.halted
    : missionFlowState.currentStep === 1 && !missionFlowState.nominalCheckResolved && !missionFlowState.halted);
  if (labelTwo) {
    if (missionFlowState.halted && missionFlowState.currentStep === 3) labelTwo.textContent = 'Everything nominal check failed';
    else if (missionFlowState.everythingNominalResolved) labelTwo.textContent = 'Everything nominal check cleared';
    else labelTwo.textContent = 'Everything nominal?';
  }
  if (checkpointTwo) {
    checkpointTwo.classList.toggle('active', missionFlowState.currentStep === 3 && !missionFlowState.everythingNominalResolved && !missionFlowState.halted);
    checkpointTwo.classList.toggle('completed', !!missionFlowState.everythingNominalResolved);
    checkpointTwo.classList.toggle('blocked', missionFlowState.halted && missionFlowState.currentStep === 3);
  }
  missionSetCheckpointActions(actionsTwo, missionFlowState.currentStep === 3 && !missionFlowState.everythingNominalResolved && !missionFlowState.halted);
  if (labelIdent) {
    if (activePageTab === 'competition') {
      if (missionFlowState.halted && missionFlowState.currentStep === 4) labelIdent.textContent = 'Proceed denied';
      else if (missionFlowState.allIdentifiedResolved) labelIdent.textContent = 'Proceed';
      else labelIdent.textContent = 'Proceed';
    } else {
      if (missionFlowState.halted && missionFlowState.currentStep === 4) labelIdent.textContent = 'All identified check failed';
      else if (missionFlowState.allIdentifiedResolved) labelIdent.textContent = 'All identified';
      else labelIdent.textContent = 'All identified';
    }
  }
  if (checkpointIdent) {
    checkpointIdent.classList.toggle('active', activePageTab === 'competition'
      ? missionFlowState.currentStep === 4 && missionFlowState.substeps[4]['search-snoopy'] && missionFlowState.substeps[4]['snoopy-found'] && missionFlowState.substeps[4]['snoopy-lock'] && !missionFlowState.allIdentifiedResolved && !missionFlowState.halted
      : missionFlowState.currentStep === 4 && missionFlowState.substeps[4]['client-rotation-model'] && missionFlowState.substeps[4]['client-rotation'] && missionFlowState.substeps[4]['docking-point'] && missionFlowState.substeps[4]['nozzle-identify-model'] && !missionFlowState.allIdentifiedResolved && !missionFlowState.halted);
    checkpointIdent.classList.toggle('completed', !!missionFlowState.allIdentifiedResolved);
    checkpointIdent.classList.toggle('blocked', missionFlowState.halted && missionFlowState.currentStep === 4);
  }
  missionSetCheckpointActions(actionsIdent, activePageTab === 'competition'
    ? missionFlowState.currentStep === 4 && missionFlowState.substeps[4]['search-snoopy'] && missionFlowState.substeps[4]['snoopy-found'] && missionFlowState.substeps[4]['snoopy-lock'] && !missionFlowState.allIdentifiedResolved && !missionFlowState.halted
    : missionFlowState.currentStep === 4 && missionFlowState.substeps[4]['client-rotation-model'] && missionFlowState.substeps[4]['client-rotation'] && missionFlowState.substeps[4]['docking-point'] && missionFlowState.substeps[4]['nozzle-identify-model'] && !missionFlowState.allIdentifiedResolved && !missionFlowState.halted);
  if (labelThree) {
    if (activePageTab === 'competition') {
      if (missionFlowState.halted && missionFlowState.currentStep === 5) labelThree.textContent = 'Satisfaction check failed';
      else labelThree.textContent = 'Satisfied';
    } else {
      if (missionFlowState.halted && missionFlowState.currentStep === 6) labelThree.textContent = 'Docking arm pose confirmation failed';
      else if (missionFlowState.dockingPoseResolved) labelThree.textContent = 'Docking arm pose confirmed';
      else labelThree.textContent = 'Docking arm pose confirmed';
    }
  }
  if (checkpointThree) {
    checkpointThree.classList.toggle('active', activePageTab === 'competition'
      ? missionFlowState.currentStep === 5 && missionFlowState.substeps[5]['rotation-finder-model'] && missionFlowState.substeps[5]['rotation-found'] && !missionFlowState.dockingPoseResolved && !missionFlowState.halted
      : missionFlowState.currentStep === 6 && missionFlowState.substeps[6]['relative-motion-stabilized'] && missionFlowState.substeps[6]['nozzle-position-found'] && missionFlowState.substeps[6]['nozzle-ik-solved'] && !missionFlowState.dockingPoseResolved && !missionFlowState.halted);
    checkpointThree.classList.toggle('completed', !!missionFlowState.dockingPoseResolved);
    checkpointThree.classList.toggle('blocked', missionFlowState.halted && (missionFlowState.currentStep === 5 || missionFlowState.currentStep === 6));
  }
  missionSetCheckpointActions(actionsThree, activePageTab === 'competition'
    ? missionFlowState.currentStep === 5 && missionFlowState.substeps[5]['rotation-finder-model'] && missionFlowState.substeps[5]['rotation-found'] && !missionFlowState.dockingPoseResolved && !missionFlowState.halted
    : missionFlowState.currentStep === 6 && missionFlowState.substeps[6]['relative-motion-stabilized'] && missionFlowState.substeps[6]['nozzle-position-found'] && missionFlowState.substeps[6]['nozzle-ik-solved'] && !missionFlowState.dockingPoseResolved && !missionFlowState.halted);
  if (labelFour) {
    if (activePageTab === 'competition') {
      if (missionFlowState.halted && missionFlowState.currentStep === 6) labelFour.textContent = 'Start angle commands failed';
      else labelFour.textContent = 'Start angle commands';
    } else {
      if (missionFlowState.halted && missionFlowState.currentStep === 7) labelFour.textContent = 'Undocking readiness failed';
      else if (missionFlowState.undockingReadyResolved) labelFour.textContent = 'Ready to undock';
      else labelFour.textContent = 'Ready to undock';
    }
  }
  if (checkpointFour) {
    checkpointFour.classList.toggle('active', activePageTab === 'competition'
      ? missionFlowState.currentStep === 6 && !missionFlowState.undockingReadyResolved && !missionFlowState.halted
      : missionFlowState.currentStep === 7 && missionFlowState.substeps[7]['client-brought-to-geo'] && !missionFlowState.undockingReadyResolved && !missionFlowState.halted);
    checkpointFour.classList.toggle('completed', !!missionFlowState.undockingReadyResolved);
    checkpointFour.classList.toggle('blocked', missionFlowState.halted && (missionFlowState.currentStep === 6 || missionFlowState.currentStep === 7));
  }
  missionSetCheckpointActions(actionsFour, activePageTab === 'competition'
    ? missionFlowState.currentStep === 6 && !missionFlowState.undockingReadyResolved && !missionFlowState.halted
    : missionFlowState.currentStep === 7 && missionFlowState.substeps[7]['client-brought-to-geo'] && !missionFlowState.undockingReadyResolved && !missionFlowState.halted);
  if (labelFive) {
    if (activePageTab === 'competition') {
      if (missionFlowState.halted && missionFlowState.currentStep === 6) labelFive.textContent = 'Satisfaction check failed';
      else labelFive.textContent = 'Satisfied';
    } else {
      if (missionFlowState.halted && missionFlowState.currentStep === 8) labelFive.textContent = 'AOCS nominal check failed';
      else labelFive.textContent = 'Everything nominal';
    }
  }
  if (checkpointFive) {
    checkpointFive.classList.toggle('active', activePageTab === 'competition'
      ? missionFlowState.currentStep === 6 && missionFlowState.undockingReadyResolved && missionFlowState.substeps[6]['45-degree-commands'] && !missionFlowState.aocsNominalResolved && !missionFlowState.halted
      : missionFlowState.currentStep === 8 && missionFlowState.substeps[8]['aocs-pose-ready'] && !missionFlowState.aocsNominalResolved && !missionFlowState.halted);
    checkpointFive.classList.toggle('completed', !!missionFlowState.aocsNominalResolved);
    checkpointFive.classList.toggle('blocked', missionFlowState.halted && (missionFlowState.currentStep === 6 || missionFlowState.currentStep === 8));
  }
  missionSetCheckpointActions(actionsFive, activePageTab === 'competition'
    ? missionFlowState.currentStep === 6 && missionFlowState.undockingReadyResolved && missionFlowState.substeps[6]['45-degree-commands'] && !missionFlowState.aocsNominalResolved && !missionFlowState.halted
    : missionFlowState.currentStep === 8 && missionFlowState.substeps[8]['aocs-pose-ready'] && !missionFlowState.aocsNominalResolved && !missionFlowState.halted);
  if (labelSix) {
    if (activePageTab === 'competition') {
      if (missionFlowState.halted && missionFlowState.currentStep === 6) labelSix.textContent = 'Start rotation matching failed';
      else labelSix.textContent = 'Start rotation matching';
    } else {
      if (missionFlowState.halted && missionFlowState.currentStep === 8) labelSix.textContent = 'AOCS slide out failed';
      else labelSix.textContent = 'AOCS slide out';
    }
  }
  if (checkpointSix) {
    checkpointSix.classList.toggle('active', activePageTab === 'competition'
      ? missionFlowState.currentStep === 6 && missionFlowState.aocsNominalResolved && !missionFlowState.aocsSlideOutResolved && !missionFlowState.halted
      : missionFlowState.currentStep === 8 && missionFlowState.aocsNominalResolved && !missionFlowState.aocsSlideOutResolved && !missionFlowState.halted);
    checkpointSix.classList.toggle('completed', !!missionFlowState.aocsSlideOutResolved);
    checkpointSix.classList.toggle('blocked', missionFlowState.halted && (missionFlowState.currentStep === 6 || missionFlowState.currentStep === 8));
  }
  missionSetCheckpointActions(actionsSix, activePageTab === 'competition'
    ? missionFlowState.currentStep === 6 && missionFlowState.aocsNominalResolved && !missionFlowState.aocsSlideOutResolved && !missionFlowState.halted
    : missionFlowState.currentStep === 8 && missionFlowState.aocsNominalResolved && !missionFlowState.aocsSlideOutResolved && !missionFlowState.halted);
  if (labelSeven) {
    if (activePageTab === 'competition') {
      if (missionFlowState.halted && missionFlowState.currentStep === 7) labelSeven.textContent = 'Satisfaction check failed';
      else labelSeven.textContent = 'Satisfied';
    } else {
      if (missionFlowState.halted && missionFlowState.currentStep === 8) labelSeven.textContent = 'Arm detach failed';
      else labelSeven.textContent = 'Arm detach';
    }
  }
  if (checkpointSeven) {
    checkpointSeven.classList.toggle('active', activePageTab === 'competition'
      ? missionFlowState.currentStep === 7 && !missionFlowState.aocsArmDetachResolved && !missionFlowState.halted
      : missionFlowState.currentStep === 8 && missionFlowState.substeps[8]['aocs-attach'] && !missionFlowState.aocsArmDetachResolved && !missionFlowState.halted);
    checkpointSeven.classList.toggle('completed', !!missionFlowState.aocsArmDetachResolved);
    checkpointSeven.classList.toggle('blocked', missionFlowState.halted && (missionFlowState.currentStep === 7 || missionFlowState.currentStep === 8));
  }
  missionSetCheckpointActions(actionsSeven, activePageTab === 'competition'
    ? missionFlowState.currentStep === 7 && !missionFlowState.aocsArmDetachResolved && !missionFlowState.halted
    : missionFlowState.currentStep === 8 && missionFlowState.substeps[8]['aocs-attach'] && !missionFlowState.aocsArmDetachResolved && !missionFlowState.halted);
  Object.keys(missionFlowState.substeps).forEach(function(stepKey) {
    var stepNum = parseInt(stepKey, 10);
    var substeps = missionFlowState.substeps[stepNum];
    Object.keys(substeps).forEach(function(subKey) {
      var el = document.getElementById('missionSubstep-' + stepNum + '-' + subKey);
      if (!el) return;
      var complete = !!substeps[subKey];
      var active = missionFlowState.currentStep === stepNum && !missionFlowState.halted && !complete;
      if (activePageTab === 'competition') {
        if (stepNum === 4 && missionFlowState.allIdentifiedResolved) active = false;
        if (stepNum === 4 && (subKey === 'snoopy-found' || subKey === 'snoopy-lock')) active = false;
        if (stepNum === 5 && subKey === 'rotation-found') active = false;
        if (stepNum === 6 && subKey === '45-degree-commands') active = false;
        if (stepNum === 6 && subKey === 'rotation-matching') active = false;
        if (stepNum === 6 && subKey === '45-degree-commands' && !missionFlowState.undockingReadyResolved) active = false;
        if (stepNum === 6 && subKey === 'rotation-matching' && !missionFlowState.aocsSlideOutResolved) active = false;
      } else {
        if (stepNum === 4 && (subKey === 'client-rotation' || subKey === 'docking-point') && missionFlowState.allIdentifiedResolved) active = false;
        if (stepNum === 6 && subKey === 'docked' && !missionFlowState.dockingPoseResolved) active = false;
        if (stepNum === 7 && subKey === 'client-brought-to-geo' && missionFlowState.undockingReadyResolved) active = false;
        if (stepNum === 7 && subKey === 'undocked' && !missionFlowState.undockingReadyResolved) active = false;
        if (stepNum === 8 && subKey === 'aocs-pose-ready' && missionFlowState.aocsNominalResolved) active = false;
        if (stepNum === 8 && subKey === 'aocs-attach' && (!missionFlowState.aocsSlideOutResolved || missionFlowState.aocsArmDetachResolved)) active = false;
      }
      el.classList.toggle('active', active);
      el.classList.toggle('completed', complete);
      if (activePageTab === 'competition' && ((stepNum === 4 && (subKey === 'snoopy-found' || subKey === 'snoopy-lock')) || (stepNum === 5 && subKey === 'rotation-found') || (stepNum === 6 && (subKey === '45-degree-commands' || subKey === 'rotation-matching')))) {
        el.disabled = true;
      } else {
        el.disabled = !active && !complete;
      }
    });
  });
}

function missionAdvanceFrom(step) {
  var next = missionNextStep(step);
  var finalStep = missionFlowSequence()[missionFlowSequence().length - 1];
  missionFlowState.currentStep = next;
  if (next === finalStep && missionIsStepComplete(finalStep)) {
    missionSetState('MISSION COMPLETE');
    missionRenderFlow();
    return;
  }
  missionRenderFlow();
}

function missionGoToStep(step) {
  missionFlowState.currentStep = Math.max(1, Math.min(10, step));
  missionRenderFlow();
}

function missionCompleteSubstep(step, substep) {
  if (activePageTab === 'competition') {
    competitionPost('/api/competition/substep', {step: step, substep: substep});
    return;
  }
  if (missionFlowState.halted || missionFlowState.currentStep !== step) return;
  if (!missionFlowState.substeps[step] || !(substep in missionFlowState.substeps[step])) return;
  missionFlowState.substeps[step][substep] = true;
  if (missionIsStepComplete(step)) {
    if (step < 10) missionAdvanceFrom(step);
    else missionSetState('MISSION COMPLETE');
  } else {
    missionRenderFlow();
  }
}

function missionRespondNominalCheck(approved) {
  if (activePageTab === 'competition') {
    competitionPost('/api/competition/checkpoint', {checkpoint: 'nominal-environment', approved: approved});
    return;
  }
  missionFlowState.started = true;
  if (approved) {
    missionFlowState.nominalCheckResolved = true;
    missionFlowState.halted = false;
    missionSetState('STEP 2 READY');
    missionGoToStep(2);
  } else {
    missionFlowState.halted = true;
    missionSetState('STOPPED');
    missionRenderFlow();
  }
}

function missionRespondEverythingNominal(approved) {
  if (activePageTab === 'competition') {
    competitionPost('/api/competition/checkpoint', {checkpoint: 'everything-nominal', approved: approved});
    return;
  }
  missionFlowState.started = true;
  if (approved) {
    missionFlowState.everythingNominalResolved = true;
    missionFlowState.halted = false;
    missionSetState('STEP 4 READY');
    missionGoToStep(4);
  } else {
    missionFlowState.halted = true;
    missionSetState('STOPPED');
    missionRenderFlow();
  }
}

function missionRespondAllIdentified(approved) {
  if (activePageTab === 'competition') {
    competitionPost('/api/competition/checkpoint', {checkpoint: 'proceed', approved: approved});
    return;
  }
  missionFlowState.started = true;
  if (approved) {
    missionFlowState.allIdentifiedResolved = true;
    missionFlowState.halted = false;
    missionSetState(activePageTab === 'competition' ? 'STEP 5 READY' : 'STEP 5 READY');
    missionGoToStep(5);
  } else {
    missionFlowState.halted = true;
    missionSetState('STOPPED');
    missionRenderFlow();
  }
}

function missionRespondDockingPose(approved) {
  if (activePageTab === 'competition') {
    competitionPost('/api/competition/checkpoint', {checkpoint: 'rotation-satisfied', approved: approved});
    return;
  }
  missionFlowState.started = true;
  if (approved) {
    missionFlowState.dockingPoseResolved = true;
    missionFlowState.halted = false;
    if (missionIsStepComplete(5)) missionAdvanceFrom(5);
    else missionRenderFlow();
  } else {
    missionFlowState.halted = true;
    missionSetState('STOPPED');
    missionRenderFlow();
  }
}

function missionRespondUndockingReady(approved) {
  if (activePageTab === 'competition') {
    competitionPost('/api/competition/checkpoint', {checkpoint: 'start-angle-commands', approved: approved});
    return;
  }
  missionFlowState.started = true;
  if (approved) {
    missionFlowState.undockingReadyResolved = true;
    missionFlowState.halted = false;
    missionRenderFlow();
  } else {
    missionFlowState.halted = true;
    missionSetState('STOPPED');
    missionRenderFlow();
  }
}

function missionRespondAocsNominal(approved) {
  if (activePageTab === 'competition') {
    competitionPost('/api/competition/checkpoint', {checkpoint: 'demo-satisfied', approved: approved});
    return;
  }
  missionFlowState.started = true;
  if (approved) {
    missionFlowState.aocsNominalResolved = true;
    missionFlowState.halted = false;
    missionRenderFlow();
  } else {
    missionFlowState.halted = true;
    missionSetState('STOPPED');
    missionRenderFlow();
  }
}

function missionRespondAocsSlideOut(approved) {
  if (activePageTab === 'competition') {
    competitionPost('/api/competition/checkpoint', {checkpoint: 'start-rotation-matching', approved: approved});
    return;
  }
  missionFlowState.started = true;
  if (approved) {
    missionFlowState.aocsSlideOutResolved = true;
    missionFlowState.halted = false;
    missionRenderFlow();
  } else {
    missionFlowState.halted = true;
    missionSetState('STOPPED');
    missionRenderFlow();
  }
}

function missionRespondAocsArmDetach(approved) {
  if (activePageTab === 'competition') {
    competitionPost('/api/competition/checkpoint', {checkpoint: 'final-satisfied', approved: approved});
    return;
  }
  missionFlowState.started = true;
  if (approved) {
    missionFlowState.aocsArmDetachResolved = true;
    missionFlowState.halted = false;
    if (activePageTab === 'competition') {
      if (missionIsStepComplete(7)) missionAdvanceFrom(7);
      else missionRenderFlow();
    } else {
      if (missionIsStepComplete(8)) missionAdvanceFrom(8);
      else missionRenderFlow();
    }
  } else {
    missionFlowState.halted = true;
    missionSetState('STOPPED');
    missionRenderFlow();
  }
}

function missionSetState(state) {
  var el = document.getElementById('missionState');
  if (el) el.textContent = state;
  if (state === 'RUNNING') {
    missionFlowState.started = true;
    missionFlowState.halted = false;
    if (!missionFlowState.nominalCheckResolved) missionGoToStep(1);
    else missionRenderFlow();
  }
  if (state === 'CONFIGURING' || state === 'READY' || state === 'REVIEW') {
    missionFlowState.halted = false;
    if (!missionFlowState.nominalCheckResolved) missionGoToStep(1);
    else missionRenderFlow();
  }
}

function missionSyncSummary() {
  var names = visionState.models.map(function(name) { return name || 'UNSET'; });
  ['missionModel1','missionModel2','missionModel3'].forEach(function(id, index) {
    var el = document.getElementById(id);
    if (el) el.textContent = (names[index] || 'UNSET').toUpperCase();
  });
  ['missionModelFileName1','missionModelFileName2','missionModelFileName3'].forEach(function(id, index) {
    var el = document.getElementById(id);
    if (el) el.textContent = names[index] || 'No model selected';
  });
  var visionStateEl = document.getElementById('missionVisionState');
  var detClassEl = document.getElementById('missionDetectionClass');
  var detConfEl = document.getElementById('missionDetectionConfidence');
  var detCenterEl = document.getElementById('missionDetectionCenter');
  var detSizeEl = document.getElementById('missionDetectionSize');
  if (visionStateEl) visionStateEl.textContent = (missionFlowState.visionState || 'IDLE').toUpperCase();
  if (detClassEl) detClassEl.textContent = missionFlowState.snoopyDetection && missionFlowState.snoopyDetection.class_label ? missionFlowState.snoopyDetection.class_label.toUpperCase() : '--';
  if (detConfEl) detConfEl.textContent = missionFlowState.snoopyDetection && missionFlowState.snoopyDetection.confidence != null ? missionFlowState.snoopyDetection.confidence.toFixed(2) : '--';
  if (detCenterEl) detCenterEl.textContent = missionFormatDetectionPoint(missionFlowState.snoopyDetection && missionFlowState.snoopyDetection.bbox_center);
  if (detSizeEl) detSizeEl.textContent = missionFormatDetectionSize(missionFlowState.snoopyDetection && missionFlowState.snoopyDetection.bbox_size);
  var maceStateEl = document.getElementById('missionMaceState');
  if (maceStateEl) maceStateEl.textContent = (missionFlowState.maceState || 'SAFE').toUpperCase();
  var searchSpeedEl = document.getElementById('missionSearchRotationSpeed');
  if (searchSpeedEl && document.activeElement !== searchSpeedEl) searchSpeedEl.value = (missionFlowState.searchRotationSpeed != null ? missionFlowState.searchRotationSpeed : 1.5);
  missionSetTelemetryValue('missionSearchLockError', missionFlowState.searchLockError != null ? missionFlowState.searchLockError.toFixed(4) : '--');
  missionSetTelemetryValue('missionSearchLockCommand', missionFlowState.searchLockCommand != null ? missionFlowState.searchLockCommand.toFixed(3) + ' rad/s' : '--');
  missionSetTelemetryValue('missionRotationEstimate', missionFlowState.rotationEstimateRpm != null ? missionFlowState.rotationEstimateRpm.toFixed(2) + ' rpm' : '--');
  missionSetTelemetryValue('missionRotationStableWindow', missionFlowState.rotationStableSeconds.toFixed(1) + ' s / ' + missionFlowState.rotationStableToleranceRpm.toFixed(1) + ' rpm');
  missionSetTelemetryValue('missionDemoPhase', (missionFlowState.demoSequenceState || 'IDLE').toUpperCase());
  missionSetTelemetryValue('missionDemoAngle', missionFlowState.demoCommandAngle != null ? missionFlowState.demoCommandAngle.toFixed(0) + ' deg' : '--');
  missionSetTelemetryValue('missionRotationMatchTarget', missionFlowState.rotationMatchTargetRpm != null ? missionFlowState.rotationMatchTargetRpm.toFixed(2) + ' rpm' : '--');
  missionSyncMlFeed();
  missionRenderFlow();
}

function missionCompetitionConfigChanged() {
  if (activePageTab !== 'competition') return;
  var searchSpeedEl = document.getElementById('missionSearchRotationSpeed');
  competitionPost('/api/competition/config', {
    searchRotationSpeed: searchSpeedEl ? parseFloat(searchSpeedEl.value || '1.5') : 1.5
  });
}

function missionSetTelemetryValue(id, text) {
  var el = document.getElementById(id);
  if (el) el.textContent = text;
}

function missionSyncSensorTelemetry(d) {
  if (!d) return;
  missionSetTelemetryValue('missionMaceRpm', d.rpm != null ? String(d.rpm) : '--');
  missionSetTelemetryValue('missionMaceEncoderAngle', d.encoder_angle != null ? d.encoder_angle.toFixed(1) + ' deg' : '--');
  missionSetTelemetryValue('missionMaceGyroZ', d.gyro && d.gyro.z != null ? d.gyro.z.toFixed(2) + ' deg/s' : '--');
  if (activePageTab !== 'competition') {
    missionSetTelemetryValue('missionMaceState', d.armed ? 'ARMED' : 'SAFE');
  }
}

function missionAttToggleEnable() {
  attToggleEnable();
}

function missionAttStop() {
  attStop();
}

function missionAttZero() {
  attZero();
}

function missionAttSetpoint() {
  var input = document.getElementById('missionAttSetpointInput');
  var val = input ? parseFloat(input.value) || 0 : 0;
  fetch('/api/attitude/setpoint', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({angle: val})
  });
}

function missionSetGainPair(manualId, missionId, value) {
  var manual = document.getElementById(manualId);
  var mission = document.getElementById(missionId);
  if (manual) manual.value = value;
  if (mission) mission.value = value;
}

function missionSetGainLabelPair(manualId, missionId, value) {
  var manual = document.getElementById(manualId);
  var mission = document.getElementById(missionId);
  if (manual) manual.textContent = value;
  if (mission) mission.textContent = value;
}

function missionAttUpdateGain() {
  var kp = document.getElementById('missionAttKp').value;
  var ki = document.getElementById('missionAttKi').value;
  var kd = document.getElementById('missionAttKd').value;
  var max = document.getElementById('missionAttMaxThrottle').value;
  missionSetGainPair('attKp', 'missionAttKp', kp);
  missionSetGainPair('attKi', 'missionAttKi', ki);
  missionSetGainPair('attKd', 'missionAttKd', kd);
  missionSetGainPair('attMaxThrottle', 'missionAttMaxThrottle', max);
  missionSetGainLabelPair('attKpVal', 'missionAttKpVal', kp);
  missionSetGainLabelPair('attKiVal', 'missionAttKiVal', ki);
  missionSetGainLabelPair('attKdVal', 'missionAttKdVal', kd);
  missionSetGainLabelPair('attMaxVal', 'missionAttMaxVal', max);
  if (attGainTimer) clearTimeout(attGainTimer);
  attGainTimer = setTimeout(function() {
    fetch('/api/attitude/gains', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        kp: parseFloat(kp),
        ki: parseFloat(ki),
        kd: parseFloat(kd),
        max_throttle: parseFloat(max)
      })
    });
  }, 200);
}

function missionModelChanged(index, input) {
  visionModelChanged(index, input);
}

var ikStatus = null;
var ikLastResult = null;

function getIkOptimizerBias() {
  var el = document.getElementById('ikOptimizerBias');
  return el ? parseInt(el.value || '70', 10) : 70;
}

function updateIkOptimizerLabel(val) {
  var label = document.getElementById('ikOptimizerVal');
  if (label) label.textContent = parseInt(val || '70', 10) + ' / 100';
}

function ikSelectedArm() {
  return (controllerStatus && controllerStatus.selected_arm) ? controllerStatus.selected_arm : 'left';
}

function ikApplyPreviewToSliders(result) {
  if (!result || !result.ok || !result.target_pwms) return;
  Object.keys(result.target_pwms).forEach(function(channel) {
    var slider = document.getElementById('ch_' + channel);
    var value = result.target_pwms[channel];
    if (!slider || typeof value !== 'number') return;
    slider.value = value;
    chUpdateLabel(channel, value);
  });
}

function ikFormatPoint(point) {
  if (!point) return 'x:-- y:-- z:--';
  return ['x', 'y', 'z'].map(function(axis) {
    var value = point[axis];
    return axis + ':' + (typeof value === 'number' ? Math.round(value) : '--');
  }).join(' ');
}

function ikUpdateResult(result) {
  ikLastResult = result || null;
  var solverEl = document.getElementById('ikSolverState');
  var solvedTipEl = document.getElementById('ikSolvedTip');
  var noteEl = document.getElementById('ikNote');
  if (solverEl) {
    if (!result) {
      solverEl.textContent = 'IDLE';
      solverEl.style.color = '#9ca3af';
    } else if (result.ok) {
      solverEl.textContent = result.applied ? (result.reused_last_solution ? 'DRY RUN SOLVED' : 'DRY RUN MOVE') : 'SOLVED';
      solverEl.style.color = result.applied ? '#f59e0b' : '#22c55e';
    } else {
      solverEl.textContent = 'UNREACHABLE';
      solverEl.style.color = '#ef4444';
    }
  }
  if (solvedTipEl) solvedTipEl.textContent = ikFormatPoint(result && (result.tip_mm || result.target_mm));
  [['Base', 'base'], ['Shoulder', 'shoulder'], ['Elbow', 'elbow'], ['WristRoll', 'wrist_roll'], ['WristPitch', 'wrist_pitch']].forEach(function(entry) {
    var el = document.getElementById('ik' + entry[0] + 'Result');
    if (!el) return;
    if (result && result.angles_deg && typeof result.angles_deg[entry[1]] === 'number') {
      var angle = result.angles_deg[entry[1]].toFixed(1);
      var channel = null;
      if (result.target_pwms) {
        Object.keys(result.target_pwms).forEach(function(key) {
          if (channel) return;
          if ((entry[1] === 'base' && key[0] === 'B') ||
              (entry[1] === 'shoulder' && key[0] === 'S') ||
              (entry[1] === 'elbow' && key[0] === 'E') ||
              (entry[1] === 'wrist_roll' && key.indexOf('A') > 0) ||
              (entry[1] === 'wrist_pitch' && key.indexOf('B') > 0)) {
            channel = key + ': ' + result.target_pwms[key] + ' us';
          }
        });
      }
      el.textContent = angle + ' deg' + (channel ? ' / ' + channel : '');
    } else {
      el.textContent = '--';
    }
  });
  if (result && result.ok && armVizState.mode === 'test') {
    ikApplyPreviewToSliders(result);
  }
  if (noteEl) {
    noteEl.className = result && !result.ok ? 'ik-note error' : 'ik-note';
    if (!result) {
      noteEl.textContent = 'Solver uses the measured arm lengths in this branch. On the dev page, MOVE SOLVED POSE reuses the dashed solution and stays dry-run only until you explicitly choose otherwise.';
    } else if (!result.ok) {
      noteEl.textContent = 'Target is outside the current approximate IK workspace or joint limits. Adjust the target or tune the calibration constants in mizi-dev.';
    } else if (result.applied) {
      noteEl.textContent = result.reused_last_solution ? 'Dry-run solved pose move completed. The dashed pose was reused without re-solving, and this isolated instance is still not sending live actuator commands.' : 'Dry-run move completed on the dev page. The solver returned PWM targets, but this isolated instance is not sending live actuator commands.';
    } else if (armVizState.mode === 'test') {
      noteEl.textContent = 'Solve preview updated and applied to the TEST MOVES sliders for visualization only.';
    } else {
      noteEl.textContent = 'Solve preview updated. Wrist roll is included and the stiffness optimizer is biasing the solve toward lower shoulder/elbow load with more wrist usage.';
    }
  }
}

function ikUpdateStatus(status) {
  ikStatus = status || null;
  var arm = ikSelectedArm();
  var armLabel = document.getElementById('ikArmLabel');
  var currentTip = document.getElementById('ikCurrentTip');
  if (armLabel) {
    armLabel.textContent = arm.toUpperCase();
    armLabel.style.color = '#f59e0b';
  }
  if (currentTip && status && status.arms && status.arms[arm]) {
    currentTip.textContent = ikFormatPoint(status.arms[arm].tip_mm);
  }
  missionSyncSummary();
}

function ikRefreshStatus() {
  fetch('/api/ik/status').then(function(r) { return r.json(); }).then(function(d) {
    ikUpdateStatus(d);
  }).catch(function() {});
}

function ikLoadCurrentTip() {
  if (!ikStatus || !ikStatus.arms || !ikStatus.arms[ikSelectedArm()]) {
    ikRefreshStatus();
    return;
  }
  var tip = ikStatus.arms[ikSelectedArm()].tip_mm || {};
  ['x', 'y', 'z'].forEach(function(axis) {
    var input = document.getElementById('ikTarget' + axis.toUpperCase());
    if (input && typeof tip[axis] === 'number') input.value = Math.round(tip[axis]);
  });
  var armState = ikStatus && ikStatus.arms ? ikStatus.arms[ikSelectedArm()] : null;
  var wristRollInput = document.getElementById('ikTargetWristRoll');
  var wristRollDeg = armState && armState.angles_deg ? armState.angles_deg.wrist_roll : null;
  if (wristRollInput && typeof wristRollDeg === 'number') wristRollInput.value = wristRollDeg.toFixed(1);
}

function ikSolve(applyMove) {
  var payload = {
    arm: ikSelectedArm(),
    x: parseFloat(document.getElementById('ikTargetX').value || '0'),
    y: parseFloat(document.getElementById('ikTargetY').value || '0'),
    z: parseFloat(document.getElementById('ikTargetZ').value || '0'),
    wrist_roll_deg: parseFloat(document.getElementById('ikTargetWristRoll').value || '0'),
    optimizer_bias: getIkOptimizerBias(),
    apply: !!applyMove
  };
  if (applyMove && ikLastResult && ikLastResult.ok && ikLastResult.arm === ikSelectedArm()) {
    payload = {
      arm: ikSelectedArm(),
      apply: true,
      reuse_last_solution: true
    };
  }
  var solverEl = document.getElementById('ikSolverState');
  if (solverEl) {
    solverEl.textContent = payload.reuse_last_solution ? 'MOVING SOLVED' : 'SOLVING';
    solverEl.style.color = '#3b82f6';
  }
  fetch('/api/ik/solve', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(payload)
  }).then(function(r) { return r.json(); }).then(function(result) {
    ikUpdateResult(result);
    ikRefreshStatus();
  }).catch(function() {
    ikUpdateResult({ok: false});
  });
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
    var missionNameEl = document.getElementById('missionModelFileName' + (index + 1));
    if (missionNameEl) missionNameEl.textContent = name || 'No model selected';
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
  missionSyncSummary();
}

function visionProfileChanged(value) {
  visionState.profile = value || 'Docking';
  updateVisionUI();
  missionSyncSummary();
}

function visionModeChanged(value) {
  visionState.mode = value || 'Observe';
  updateVisionUI();
  missionSyncSummary();
}

function visionLoadModel() {
  if (!visionState.models.some(function(name) { return !!name; })) return;
  visionState.status = 'LOADED';
  updateVisionUI();
  missionSyncSummary();
}

function visionPreviewPipeline() {
  if (!visionState.models.some(function(name) { return !!name; })) return;
  visionState.status = 'PREVIEW';
  updateVisionUI();
  missionSyncSummary();
}

function visionStageAutonomy() {
  if (!visionState.models.some(function(name) { return !!name; })) return;
  visionState.status = 'STAGED';
  updateVisionUI();
  missionSyncSummary();
}

function visionReset() {
  visionState.models = ['', '', ''];
  visionState.status = 'STANDBY';
  visionState.profile = 'Docking';
  visionState.mode = 'Observe';
  [1, 2, 3].forEach(function(slot) {
    var input = document.getElementById('visionModelFile' + slot);
    if (input) input.value = '';
    var missionInput = document.getElementById('missionModelFile' + slot);
    if (missionInput) missionInput.value = '';
  });
  var profile = document.getElementById('visionProfileSelect');
  if (profile) profile.value = 'Docking';
  var mode = document.getElementById('visionRunMode');
  if (mode) mode.value = 'Observe';
  updateVisionUI();
  missionSyncSummary();
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
    var angle = ((pwm - neutral) / joint.us_per_rad) * joint.sign;
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

function missionArmVizShouldShowSolvedPose() {
  var step = missionFlowState.currentStep;
  if (step === 5) return missionFlowState.substeps[5]['docking-arm-position'] || missionFlowState.substeps[5]['aocs-arm-position'] || !missionIsStepComplete(5);
  if (step === 6) return missionFlowState.substeps[6]['nozzle-ik-solved'] || missionFlowState.dockingPoseResolved || missionFlowState.substeps[6]['docked'];
  if (step === 8) return missionFlowState.substeps[8]['aocs-pose-ready'] || missionFlowState.aocsNominalResolved || missionFlowState.aocsSlideOutResolved || missionFlowState.substeps[8]['aocs-attach'] || missionFlowState.aocsArmDetachResolved;
  return false;
}

function missionArmVizSolvedArm() {
  if (!missionArmVizShouldShowSolvedPose()) return null;
  if (ikLastResult && ikLastResult.ok && ikLastResult.arm && ikLastResult.angles_rad) {
    return armVizBuildArm(ikLastResult.arm, ikLastResult.angles_rad);
  }
  return null;
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
  armVizRenderCanvas(document.getElementById('missionArmVizCanvas'), {fallbackWidth: 720, fallbackHeight: 320, minWidth: 260, minHeight: 184, zoomMultiplier: 0.72, showTarget: false, showLegend: false, solvedArm: missionArmVizSolvedArm()});
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
  missionSyncSummary();
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
  var canvases = ['armVizCanvas', 'missionArmVizCanvas'];
  canvases.forEach(function(id) {
    var canvas = document.getElementById(id);
    if (canvas) canvas.classList.remove('dragging');
  });
  armVizState.activeCanvasId = null;
}

function armVizBindPointer() {
  ['armVizCanvas', 'missionArmVizCanvas'].forEach(function(id) {
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
  armVizLoadGeometry();
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
    if (name !== 'MACE') chGoNeutral(name);
  });
}

function startupNeutral() {
  chOrder.forEach(function(name) {
    if (name === 'MACE') return;
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
  ikUpdateStatus(ikStatus);
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
    missionSyncSensorTelemetry(d);
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
  missionSetGainPair('attKp', 'missionAttKp', document.getElementById('attKp').value);
  missionSetGainPair('attKi', 'missionAttKi', document.getElementById('attKi').value);
  missionSetGainPair('attKd', 'missionAttKd', document.getElementById('attKd').value);
  missionSetGainPair('attMaxThrottle', 'missionAttMaxThrottle', document.getElementById('attMaxThrottle').value);
  missionSetGainLabelPair('attKpVal', 'missionAttKpVal', document.getElementById('attKp').value);
  missionSetGainLabelPair('attKiVal', 'missionAttKiVal', document.getElementById('attKi').value);
  missionSetGainLabelPair('attKdVal', 'missionAttKdVal', document.getElementById('attKd').value);
  missionSetGainLabelPair('attMaxVal', 'missionAttMaxVal', document.getElementById('attMaxThrottle').value);
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
      missionSetTelemetryValue('missionMaceAttState', 'UNREACHABLE');
      missionSetTelemetryValue('missionMaceImuAngle', '--');
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
    var missionEnableBtn = document.getElementById('missionAttEnableBtn');
    if (missionEnableBtn) {
      missionEnableBtn.textContent = attEnabled ? 'Disable' : 'Enable';
      missionEnableBtn.className = attEnabled ? 'btn btn-sm btn-red' : 'btn btn-sm btn-green';
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
    missionSetTelemetryValue('missionMaceImuAngle', d.angle != null ? d.angle.toFixed(1) + ' deg' : '--');
    missionSetTelemetryValue('missionMaceGyroZ', d.gz != null ? d.gz.toFixed(2) + ' deg/s' : '--');
    missionSetTelemetryValue('missionMaceAttState', d.enabled ? 'ENABLED' : 'DISABLED');
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
      if (d.gains.kp != null) { missionSetGainPair('attKp', 'missionAttKp', d.gains.kp); missionSetGainLabelPair('attKpVal', 'missionAttKpVal', d.gains.kp); }
      if (d.gains.ki != null) { missionSetGainPair('attKi', 'missionAttKi', d.gains.ki); missionSetGainLabelPair('attKiVal', 'missionAttKiVal', d.gains.ki); }
      if (d.gains.kd != null) { missionSetGainPair('attKd', 'missionAttKd', d.gains.kd); missionSetGainLabelPair('attKdVal', 'missionAttKdVal', d.gains.kd); }
      if (d.gains.max_throttle != null) { missionSetGainPair('attMaxThrottle', 'missionAttMaxThrottle', d.gains.max_throttle); missionSetGainLabelPair('attMaxVal', 'missionAttMaxVal', d.gains.max_throttle); }
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
    missionSetTelemetryValue('missionMaceAttState', 'OFFLINE');
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
      if (name === 'MACE') return;
      var label = document.getElementById('chn_' + name);
      if (label) label.textContent = getNeutral(name) + ' us';
    });
  }).catch(function() {});

  /* Fetch last-known servo positions from server, fallback to neutral */
  fetch('/api/servo_positions').then(function(r) { return r.json(); }).then(function(positions) {
    chOrder.forEach(function(name) {
      if (name === 'MACE') return;
      var pw = positions[name] != null ? positions[name] : getNeutral(name);
      chActual[name] = pw;
      var slider = document.getElementById('ch_' + name);
      if (slider) slider.value = pw;
      chUpdateLabel(name, pw);
    });
  }).catch(function() {
    /* Server unreachable — default to neutral, do NOT send PWM */
    chOrder.forEach(function(name) {
      if (name === 'MACE') return;
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
  setInterval(attPoll, 500);
  setInterval(sysPoll, 2000);
  setInterval(gimbalPoll, 1000);
  setInterval(servoSyncPoll, 500);
  setInterval(controllerPoll, 250);
  setInterval(ikRefreshStatus, 1000);
  setInterval(function() {
    if (activePageTab === 'competition') competitionFetchStatus();
  }, 1000);

  /* Immediate calls */
  sysPoll();
  gimbalPoll();
  controllerPoll();
  ikRefreshStatus();
  updateIkOptimizerLabel(getIkOptimizerBias());
  updateVisionUI();
  missionSyncSummary();
  showPageTab('manual');
  loadCameraStreamState();
  armVizStart();
})();
