from flask import Flask, render_template, jsonify, request
import threading
import time
import json
import os
import urllib.request

app = Flask(__name__)

GEODUDE_URL = "http://192.168.4.166:5000"
ATTITUDE_URL = "http://192.168.4.166:5001"
GIMBAL_URL = "http://192.168.4.222"
WATCHDOG_TIMEOUT = 3  # seconds — auto-stop if no frontend heartbeat

# PCA9685 channel mapping (pin - 1 = 0-indexed)
# MACE reaction wheel is no longer on PCA9685 — it is driven by Pi Pico via SimpleFOC
CHANNELS = {
    "B1":   15,
    "S1":   14,
    "B2":   13,
    "S2":   12,
    "E1":    6,
    "E2":    4,
    "W1A":   3,
    "W1B":   2,
    "W2A":   1,
    "W2B":   0,
}

# SimpleFOC velocity limits (rad/s)
MAX_VELOCITY = 20.0

mace = {
    "enabled": False,
    "target": 0.0,      # target velocity rad/s
    "velocity": 0.0,    # current velocity rad/s (reported by Pico)
    "connected": False, # Pico USB serial connected
    "error": None,
}

state = {
    "gyro": {"x": 0, "y": 0, "z": 0},
    "accel": {"x": 0, "y": 0, "z": 0},
    "encoder_angle": 0,
    "connected": False,
    "rpm": 0,
}

# Server-side servo position tracking — persisted to disk, survives reboots
POSITIONS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "servo_positions.json")

def load_positions():
    try:
        with open(POSITIONS_FILE) as f:
            return json.load(f)
    except Exception:
        return {}

def save_positions():
    with open(POSITIONS_FILE, "w") as f:
        json.dump(servo_positions, f)

servo_positions = load_positions()
_positions_dirty = False
_positions_last_change = 0

def mark_positions_dirty():
    global _positions_dirty, _positions_last_change
    _positions_dirty = True
    _positions_last_change = time.monotonic()

def positions_flush_loop():
    """Write positions to disk 1s after last change. Runs in background."""
    global _positions_dirty
    while True:
        time.sleep(1)
        if _positions_dirty and time.monotonic() - _positions_last_change >= 1.0:
            _positions_dirty = False
            save_positions()

# Neutral positions — persisted to disk, survives reboots
NEUTRAL_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "servo_neutral.json")

def load_neutral():
    try:
        with open(NEUTRAL_FILE) as f:
            return json.load(f)
    except Exception:
        return {}

def save_neutral(data):
    with open(NEUTRAL_FILE, "w") as f:
        json.dump(data, f)

servo_neutral = load_neutral()

lock = threading.Lock()
last_heartbeat = time.monotonic()


COMPETITION_STEPS = [1, 2, 3, 4, 5, 6, 7, 8]
COMPETITION_STEP_NAMES = {
    1: "MISSION START",
    2: "STARTUP",
    3: "EVERYTHING NOMINAL CHECK",
    4: "FIND SNOOPY",
    5: "SNOOPY ROTATION",
    6: "MACE CAPABILITY DEMO",
    7: "SATISFACTION CHECK",
    8: "MISSION COMPLETE",
}


def competition_default_state():
    return {
        "mode": "competition",
        "currentStep": 1,
        "started": False,
        "running": False,
        "halted": False,
        "armed": False,
        # Reuse frontend field names so the renderer can adopt backend state directly.
        "nominalCheckResolved": False,
        "everythingNominalResolved": False,
        "allIdentifiedResolved": False,
        "dockingPoseResolved": False,
        "undockingReadyResolved": False,
        "aocsNominalResolved": False,
        "aocsSlideOutResolved": False,
        "aocsArmDetachResolved": False,
        "maceState": "SAFE",
        "searchRotationSpeed": 1.5,
        "searchLockDeadband": 0.05,
        "searchLockKp": 6.0,
        "searchLockMaxCommand": 2.0,
        "searchLockError": None,
        "searchLockCommand": 0.0,
        "rotationEstimateRpm": None,
        "rotationStableToleranceRpm": 3.0,
        "rotationStableSeconds": 3.0,
        "rotationStableSince": None,
        "demoSequenceState": "IDLE",
        "demoPhaseStartedAt": None,
        "demoCommandAngle": None,
        "rotationMatchActive": False,
        "rotationMatchTargetRpm": None,
        "activeVisionModel": None,
        "visionState": "IDLE",
        "snoopyDetection": {
            "active": False,
            "found": False,
            "bbox_center": {"x": None, "y": None},
            "bbox_size": {"w": None, "h": None},
            "confidence": None,
            "class_label": None,
        },
        "substeps": {
            "2": {"snoopy-detect": False, "mace": False},
            "4": {"search-snoopy": False, "snoopy-found": False, "snoopy-lock": False},
            "5": {"rotation-finder-model": False, "rotation-found": False},
            "6": {"45-degree-commands": False, "rotation-matching": False},
            "7": {},
            "8": {},
        },
        "last_event": "initialized",
        "last_error": None,
    }


competition_state = competition_default_state()


def _competition_step_name(step):
    return COMPETITION_STEP_NAMES.get(step, "MISSION START")


def _competition_active_checkpoint():
    if competition_state["halted"]:
        return None
    step = competition_state["currentStep"]
    substeps = competition_state["substeps"]
    if step == 1 and not competition_state["nominalCheckResolved"]:
        return "nominal-environment"
    if step == 3 and not competition_state["everythingNominalResolved"]:
        return "everything-nominal"
    if step == 4 and substeps["4"]["search-snoopy"] and substeps["4"]["snoopy-found"] and substeps["4"]["snoopy-lock"] and not competition_state["allIdentifiedResolved"]:
        return "proceed"
    if step == 5 and substeps["5"]["rotation-finder-model"] and substeps["5"]["rotation-found"] and not competition_state["dockingPoseResolved"]:
        return "rotation-satisfied"
    if step == 6 and not competition_state["undockingReadyResolved"]:
        return "start-angle-commands"
    if step == 6 and competition_state["undockingReadyResolved"] and substeps["6"]["45-degree-commands"] and not competition_state["aocsNominalResolved"]:
        return "demo-satisfied"
    if step == 6 and competition_state["aocsNominalResolved"] and not competition_state["aocsSlideOutResolved"]:
        return "start-rotation-matching"
    if step == 7 and not competition_state["aocsArmDetachResolved"]:
        return "final-satisfied"
    return None


def _competition_step_complete(step):
    substeps = competition_state["substeps"]
    if step == 1:
        return competition_state["nominalCheckResolved"]
    if step == 2:
        return substeps["2"]["snoopy-detect"] and substeps["2"]["mace"]
    if step == 3:
        return competition_state["everythingNominalResolved"]
    if step == 4:
        return substeps["4"]["search-snoopy"] and substeps["4"]["snoopy-found"] and substeps["4"]["snoopy-lock"] and competition_state["allIdentifiedResolved"]
    if step == 5:
        return substeps["5"]["rotation-finder-model"] and substeps["5"]["rotation-found"] and competition_state["dockingPoseResolved"]
    if step == 6:
        return (
            competition_state["undockingReadyResolved"]
            and substeps["6"]["45-degree-commands"]
            and competition_state["aocsNominalResolved"]
            and competition_state["aocsSlideOutResolved"]
            and substeps["6"]["rotation-matching"]
        )
    if step == 7:
        return competition_state["aocsArmDetachResolved"]
    if step == 8:
        return _competition_step_complete(7)
    return False


def _competition_refresh_current_step():
    for step in COMPETITION_STEPS:
        if not _competition_step_complete(step):
            competition_state["currentStep"] = step
            return
    competition_state["currentStep"] = 8


def _competition_snapshot():
    _competition_tick()
    snapshot = {
        "mode": competition_state["mode"],
        "currentStep": competition_state["currentStep"],
        "currentStepName": _competition_step_name(competition_state["currentStep"]),
        "started": competition_state["started"],
        "running": competition_state["running"],
        "halted": competition_state["halted"],
        "armed": competition_state["armed"],
        "nominalCheckResolved": competition_state["nominalCheckResolved"],
        "everythingNominalResolved": competition_state["everythingNominalResolved"],
        "allIdentifiedResolved": competition_state["allIdentifiedResolved"],
        "dockingPoseResolved": competition_state["dockingPoseResolved"],
        "undockingReadyResolved": competition_state["undockingReadyResolved"],
        "aocsNominalResolved": competition_state["aocsNominalResolved"],
        "aocsSlideOutResolved": competition_state["aocsSlideOutResolved"],
        "aocsArmDetachResolved": competition_state["aocsArmDetachResolved"],
        "maceState": competition_state["maceState"],
        "searchRotationSpeed": competition_state["searchRotationSpeed"],
        "searchLockDeadband": competition_state["searchLockDeadband"],
        "searchLockKp": competition_state["searchLockKp"],
        "searchLockMaxCommand": competition_state["searchLockMaxCommand"],
        "searchLockError": competition_state["searchLockError"],
        "searchLockCommand": competition_state["searchLockCommand"],
        "rotationEstimateRpm": competition_state["rotationEstimateRpm"],
        "rotationStableToleranceRpm": competition_state["rotationStableToleranceRpm"],
        "rotationStableSeconds": competition_state["rotationStableSeconds"],
        "demoSequenceState": competition_state["demoSequenceState"],
        "demoCommandAngle": competition_state["demoCommandAngle"],
        "rotationMatchActive": competition_state["rotationMatchActive"],
        "rotationMatchTargetRpm": competition_state["rotationMatchTargetRpm"],
        "activeVisionModel": competition_state["activeVisionModel"],
        "visionState": competition_state["visionState"],
        "snoopyDetection": json.loads(json.dumps(competition_state["snoopyDetection"])),
        "substeps": json.loads(json.dumps(competition_state["substeps"])),
        "activeCheckpoint": _competition_active_checkpoint(),
        "last_event": competition_state["last_event"],
        "last_error": competition_state["last_error"],
        "complete": _competition_step_complete(8),
    }
    return snapshot


def _competition_fail(reason):
    mace["target"] = 0.0
    mace["velocity"] = 0.0
    mace["enabled"] = False
    send_velocity(0.0)
    competition_state["halted"] = True
    competition_state["armed"] = False
    competition_state["running"] = False
    competition_state["maceState"] = "SAFE"
    competition_state["searchLockError"] = None
    competition_state["searchLockCommand"] = 0.0
    competition_state["rotationEstimateRpm"] = None
    competition_state["rotationStableSince"] = None
    competition_state["demoSequenceState"] = "IDLE"
    competition_state["demoPhaseStartedAt"] = None
    competition_state["demoCommandAngle"] = None
    competition_state["rotationMatchActive"] = False
    competition_state["rotationMatchTargetRpm"] = None
    competition_state["last_event"] = "halted"
    competition_state["last_error"] = reason


def _competition_allow_actions():
    return competition_state["armed"] and competition_state["running"] and not competition_state["halted"]


def _competition_apply_mace_velocity(target_velocity):
    target_velocity = float(target_velocity)
    mace["enabled"] = True
    mace["target"] = target_velocity
    mace["velocity"] = target_velocity
    send_velocity(target_velocity)


def _competition_reset_detection_tracking():
    competition_state["snoopyDetection"] = {
        "active": True,
        "found": False,
        "bbox_center": {"x": None, "y": None},
        "bbox_size": {"w": None, "h": None},
        "confidence": None,
        "class_label": "snoopy",
    }
    competition_state["searchLockError"] = None
    competition_state["searchLockCommand"] = 0.0


def _competition_reset_rotation_tracking():
    competition_state["rotationEstimateRpm"] = None
    competition_state["rotationStableSince"] = None


def _competition_start_demo_sequence():
    competition_state["demoSequenceState"] = "TO_POSITIVE_45"
    competition_state["demoPhaseStartedAt"] = time.monotonic()
    competition_state["demoCommandAngle"] = 45
    competition_state["maceState"] = "ANGLE_DEMO"
    competition_state["visionState"] = "ANGLE_DEMO"


def _competition_start_rotation_match():
    competition_state["rotationMatchActive"] = True
    competition_state["rotationMatchTargetRpm"] = competition_state["rotationEstimateRpm"]
    competition_state["substeps"]["6"]["rotation-matching"] = True
    competition_state["maceState"] = "RPM_MATCHING"
    competition_state["visionState"] = "RPM_MATCHING"


def _competition_stop_rotation_match():
    competition_state["rotationMatchActive"] = False
    competition_state["rotationMatchTargetRpm"] = None
    competition_state["maceState"] = "COMPLETE"
    competition_state["visionState"] = "RPM_MATCHED"


def _competition_tick():
    if competition_state["halted"]:
        return
    if competition_state["currentStep"] != 6:
        return
    if not competition_state["undockingReadyResolved"]:
        return
    if competition_state["substeps"]["6"]["45-degree-commands"]:
        return
    phase = competition_state["demoSequenceState"]
    phase_started = competition_state["demoPhaseStartedAt"]
    if phase == "IDLE" or phase_started is None:
        return
    elapsed = time.monotonic() - phase_started
    if phase == "TO_POSITIVE_45" and elapsed >= 1.0:
        competition_state["demoSequenceState"] = "TO_NEGATIVE_45"
        competition_state["demoPhaseStartedAt"] = time.monotonic()
        competition_state["demoCommandAngle"] = -45
    elif phase == "TO_NEGATIVE_45" and elapsed >= 1.2:
        competition_state["demoSequenceState"] = "RETURN_TO_LOCK"
        competition_state["demoPhaseStartedAt"] = time.monotonic()
        competition_state["demoCommandAngle"] = 0
    elif phase == "RETURN_TO_LOCK" and elapsed >= 1.6:
        competition_state["demoSequenceState"] = "COMPLETE"
        competition_state["demoPhaseStartedAt"] = None
        competition_state["demoCommandAngle"] = 0
        competition_state["substeps"]["6"]["45-degree-commands"] = True
        competition_state["maceState"] = "LOCKED"
        competition_state["visionState"] = "LOCKED"
        competition_state["last_event"] = "demo:complete"
        competition_state["last_error"] = None
        _competition_refresh_current_step()


def _competition_apply_rotation_estimate(payload):
    if not _competition_allow_actions():
        return False, "mission not armed or already halted"
    if competition_state["currentStep"] != 5:
        return False, "rotation step is not active"
    if not competition_state["substeps"]["5"]["rotation-finder-model"]:
        return False, "rotation finder model has not started"

    rpm = payload.get("rpm")
    if rpm is None:
        return False, "missing rpm"
    rpm = float(rpm)
    now = time.monotonic()
    previous = competition_state["rotationEstimateRpm"]
    tolerance = float(competition_state["rotationStableToleranceRpm"])
    stable_since = competition_state["rotationStableSince"]

    competition_state["rotationEstimateRpm"] = round(rpm, 2)
    competition_state["activeVisionModel"] = 2
    competition_state["visionState"] = "ROTATION_SEARCHING"

    if previous is None or abs(rpm - float(previous)) > tolerance:
        competition_state["rotationStableSince"] = now
    else:
        if stable_since is None:
            competition_state["rotationStableSince"] = now
        elif (now - stable_since) >= float(competition_state["rotationStableSeconds"]):
            competition_state["substeps"]["5"]["rotation-found"] = True
            competition_state["visionState"] = "ROTATION_LOCKED"
            competition_state["last_event"] = "rotation:stable"
            competition_state["last_error"] = None
            _competition_refresh_current_step()
            return True, None

    competition_state["last_event"] = "rotation:estimate"
    competition_state["last_error"] = None
    _competition_refresh_current_step()
    return True, None


def _competition_apply_detection(payload):
    if not _competition_allow_actions():
        return False, "mission not armed or already halted"
    if competition_state["currentStep"] != 4:
        return False, "search step is not active"
    if not competition_state["substeps"]["4"]["search-snoopy"]:
        return False, "search has not started"

    class_label = str(payload.get("class_label", "")).strip().lower()
    confidence = payload.get("confidence")
    center = payload.get("bbox_center") or {}
    size = payload.get("bbox_size") or {}
    if class_label != "snoopy":
        return False, "unsupported class label"
    if confidence is None or float(confidence) <= 0:
        return False, "invalid confidence"
    if center.get("x") is None or center.get("y") is None:
        return False, "missing bbox center"
    if size.get("w") is None or size.get("h") is None:
        return False, "missing bbox size"

    bbox_center = {"x": float(center["x"]), "y": float(center["y"])}
    bbox_size = {"w": float(size["w"]), "h": float(size["h"])}
    competition_state["snoopyDetection"] = {
        "active": True,
        "found": True,
        "bbox_center": bbox_center,
        "bbox_size": bbox_size,
        "confidence": float(confidence),
        "class_label": "snoopy",
    }

    if not competition_state["substeps"]["4"]["snoopy-found"]:
        competition_state["substeps"]["4"]["snoopy-found"] = True
        competition_state["visionState"] = "FOUND"
        competition_state["maceState"] = "CENTERING"
        _competition_apply_mace_velocity(0.0)

    x_error = bbox_center["x"] - 0.5
    competition_state["searchLockError"] = round(x_error, 4)
    deadband = float(competition_state["searchLockDeadband"])
    if abs(x_error) <= deadband:
        competition_state["substeps"]["4"]["snoopy-lock"] = True
        competition_state["visionState"] = "LOCKED"
        competition_state["maceState"] = "LOCKED"
        competition_state["searchLockCommand"] = 0.0
        _competition_apply_mace_velocity(0.0)
    else:
        kp = float(competition_state["searchLockKp"])
        max_cmd = float(competition_state["searchLockMaxCommand"])
        correction = max(-max_cmd, min(max_cmd, -kp * x_error))
        competition_state["searchLockCommand"] = round(correction, 4)
        competition_state["visionState"] = "CENTERING"
        competition_state["maceState"] = "CENTERING"
        _competition_apply_mace_velocity(correction)

    competition_state["last_event"] = "detection:snoopy"
    competition_state["last_error"] = None
    _competition_refresh_current_step()
    return True, None


def _competition_complete_substep(step, substep):
    step = str(step)
    expected_step = competition_state["currentStep"]
    if not _competition_allow_actions():
        return False, "mission not armed or already halted"
    if expected_step != int(step):
        return False, "step is not active"
    if _competition_active_checkpoint() is not None:
        return False, "checkpoint approval required before continuing"
    if step not in competition_state["substeps"] or substep not in competition_state["substeps"][step]:
        return False, "unknown substep"
    if step == "4" and substep in ("snoopy-found", "snoopy-lock"):
        return False, "substep is controlled by model detections"
    if step == "5" and substep == "rotation-found":
        return False, "substep is controlled by model estimates"
    competition_state["started"] = True
    competition_state["running"] = True
    competition_state["substeps"][step][substep] = True
    if step == "2" and substep == "mace":
        mace["enabled"] = True
        mace["target"] = 0.0
        mace["velocity"] = 0.0
        mace["error"] = None
        send_velocity(0.0)
        competition_state["maceState"] = "PRIMED"
    elif step == "4" and substep == "search-snoopy":
        competition_state["activeVisionModel"] = 1
        competition_state["visionState"] = "SEARCHING"
        competition_state["maceState"] = "SEARCHING"
        _competition_reset_detection_tracking()
        _competition_apply_mace_velocity(competition_state["searchRotationSpeed"])
    elif step == "5" and substep == "rotation-finder-model":
        competition_state["activeVisionModel"] = 2
        competition_state["visionState"] = "ROTATION_SEARCHING"
        _competition_reset_rotation_tracking()
    competition_state["last_event"] = "substep:%s:%s" % (step, substep)
    competition_state["last_error"] = None
    _competition_refresh_current_step()
    return True, None


def _competition_respond(checkpoint, approved):
    if not _competition_allow_actions():
        return False, "mission not running or already halted"
    active = _competition_active_checkpoint()
    if checkpoint != active:
        return False, "checkpoint is not active"
    competition_state["started"] = True
    competition_state["running"] = True
    if not approved:
        _competition_fail("checkpoint denied: %s" % checkpoint)
        return True, None
    if checkpoint == "nominal-environment":
        competition_state["nominalCheckResolved"] = True
        # Step 2 begins by starting the first model automatically.
        competition_state["substeps"]["2"]["snoopy-detect"] = True
        competition_state["activeVisionModel"] = 1
        competition_state["visionState"] = "SEARCHING"
        _competition_reset_detection_tracking()
    elif checkpoint == "everything-nominal":
        competition_state["everythingNominalResolved"] = True
    elif checkpoint == "proceed":
        competition_state["allIdentifiedResolved"] = True
    elif checkpoint == "rotation-satisfied":
        competition_state["dockingPoseResolved"] = True
    elif checkpoint == "start-angle-commands":
        competition_state["undockingReadyResolved"] = True
        _competition_start_demo_sequence()
    elif checkpoint == "demo-satisfied":
        competition_state["aocsNominalResolved"] = True
    elif checkpoint == "start-rotation-matching":
        competition_state["aocsSlideOutResolved"] = True
        _competition_start_rotation_match()
    elif checkpoint == "final-satisfied":
        competition_state["aocsArmDetachResolved"] = True
        _competition_stop_rotation_match()
    else:
        return False, "unknown checkpoint"
    competition_state["last_event"] = "checkpoint:%s" % checkpoint
    competition_state["last_error"] = None
    _competition_refresh_current_step()
    return True, None


def _competition_reset():
    mace["target"] = 0.0
    mace["velocity"] = 0.0
    mace["enabled"] = False
    send_velocity(0.0)
    competition_state.clear()
    competition_state.update(competition_default_state())


def send_velocity(velocity):
    """Send velocity command (rad/s) to Pico via GEO-DUDe /simplefoc endpoint."""
    try:
        req = urllib.request.Request(
            f"{GEODUDE_URL}/simplefoc",
            data=json.dumps({"velocity": round(float(velocity), 4)}).encode(),
            headers={"Content-Type": "application/json"},
        )
        urllib.request.urlopen(req, timeout=3)
        mace["error"] = None
        return True
    except Exception as e:
        mace["error"] = str(e)
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


def watchdog_loop():
    """Auto-stop motor if no frontend heartbeat within timeout."""
    while True:
        time.sleep(1)
        with lock:
            enabled = mace["enabled"]
            target = mace["target"]
        if enabled and target != 0.0:
            if time.monotonic() - last_heartbeat > WATCHDOG_TIMEOUT:
                with lock:
                    mace["target"] = 0.0
                    mace["velocity"] = 0.0
                    mace["enabled"] = False
                send_velocity(0.0)


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
        # Poll SimpleFOC status from GEO-DUDe (Pico connection + current target)
        try:
            resp = urllib.request.urlopen(f"{GEODUDE_URL}/simplefoc/status", timeout=2)
            sfoc = json.loads(resp.read().decode())
            with lock:
                mace["connected"] = sfoc.get("connected", False)
                t = sfoc.get("target")
                if t is not None:
                    mace["velocity"] = round(float(t), 4)
        except Exception:
            with lock:
                mace["connected"] = False
        time.sleep(0.1)



@app.route('/')
def index():
    return render_template('index.html')


@app.route('/api/sensors')
def sensors():
    global last_heartbeat
    last_heartbeat = time.monotonic()
    with lock:
        return jsonify(state)


@app.route('/api/mace/status')
def mace_status():
    """Return current MACE state."""
    with lock:
        return jsonify(dict(mace))


@app.route('/api/mace/enable', methods=['POST'])
def mace_enable():
    """Enable the reaction wheel motor."""
    with lock:
        mace["enabled"] = True
        mace["error"] = None
    return jsonify({"ok": True, "enabled": True})


@app.route('/api/mace/disable', methods=['POST'])
def mace_disable():
    """Disable the reaction wheel motor and stop it."""
    with lock:
        mace["enabled"] = False
        mace["target"] = 0.0
        mace["velocity"] = 0.0
    send_velocity(0.0)
    return jsonify({"ok": True, "enabled": False})


@app.route('/api/mace/velocity', methods=['POST'])
def mace_velocity():
    """Set target velocity in rad/s. Only works if motor is enabled."""
    global last_heartbeat
    last_heartbeat = time.monotonic()
    data = request.json
    v = max(-MAX_VELOCITY, min(MAX_VELOCITY, float(data.get("target", 0))))
    with lock:
        if not mace["enabled"]:
            return jsonify({"ok": False, "reason": "not enabled"})
        mace["target"] = v
    ok = send_velocity(v)
    return jsonify({"ok": ok})


@app.route('/api/mace/stop', methods=['POST'])
def mace_stop():
    """Immediate stop: send velocity 0 and disable motor."""
    with lock:
        mace["target"] = 0.0
        mace["velocity"] = 0.0
        mace["enabled"] = False
    send_velocity(0.0)
    return jsonify({"ok": True})


@app.route('/api/pwm', methods=['POST'])
def pwm():
    """Proxy per-channel PWM to GEO-DUDe."""
    data = request.json
    name = data.get("channel", "")
    pw = int(data.get("pw", 0))
    ok = send_pwm(name, pw)
    if ok and name in CHANNELS:
        servo_positions[name] = pw
        mark_positions_dirty()
    return jsonify({"ok": ok})


@app.route('/api/servo_positions')
def get_servo_positions():
    """Return last-known servo positions (survives page reload)."""
    return jsonify(servo_positions)


@app.route('/api/servo_neutral')
def get_servo_neutral():
    """Return neutral positions (persisted to disk)."""
    return jsonify(servo_neutral)


@app.route('/api/servo_neutral', methods=['POST'])
def set_servo_neutral():
    """Set neutral position for a channel. Body: {"channel": "B1", "pw": 1500}"""
    data = request.json
    name = data.get("channel", "")
    pw = int(data.get("pw", 1500))
    if name in CHANNELS:
        servo_neutral[name] = pw
        save_neutral(servo_neutral)
    return jsonify({"ok": True})


@app.route('/api/all_off', methods=['POST'])
def all_off():
    """Turn all PCA9685 channels off."""
    ok = send_all_off()
    return jsonify({"ok": ok})


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


@app.route('/api/competition/status')
def competition_status():
    with lock:
        return jsonify(_competition_snapshot())


@app.route('/api/competition/config', methods=['POST'])
def competition_config():
    data = request.json or {}
    with lock:
        if "searchRotationSpeed" in data:
            competition_state["searchRotationSpeed"] = max(0.0, min(12.0, float(data.get("searchRotationSpeed", 0.0))))
        if "searchLockDeadband" in data:
            competition_state["searchLockDeadband"] = max(0.005, min(0.25, float(data.get("searchLockDeadband", 0.05))))
        if "searchLockKp" in data:
            competition_state["searchLockKp"] = max(0.1, min(25.0, float(data.get("searchLockKp", 6.0))))
        if "searchLockMaxCommand" in data:
            competition_state["searchLockMaxCommand"] = max(0.1, min(8.0, float(data.get("searchLockMaxCommand", 2.0))))
        competition_state["last_event"] = "config"
        competition_state["last_error"] = None
        return jsonify({"ok": True, "state": _competition_snapshot()})


@app.route('/api/competition/reset', methods=['POST'])
def competition_reset():
    with lock:
        _competition_reset()
        return jsonify({"ok": True, "state": _competition_snapshot()})


@app.route('/api/competition/arm', methods=['POST'])
def competition_arm():
    data = request.json or {}
    armed = bool(data.get("armed", False))
    with lock:
        competition_state["armed"] = armed
        if not armed:
            competition_state["running"] = False
        competition_state["last_event"] = "armed" if armed else "disarmed"
        competition_state["last_error"] = None
        return jsonify({"ok": True, "state": _competition_snapshot()})


@app.route('/api/competition/run', methods=['POST'])
def competition_run():
    with lock:
        if not competition_state["armed"]:
            return jsonify({"ok": False, "reason": "mission not armed", "state": _competition_snapshot()}), 409
        if competition_state["halted"]:
            return jsonify({"ok": False, "reason": "mission halted", "state": _competition_snapshot()}), 409
        if competition_state["running"]:
            return jsonify({"ok": True, "state": _competition_snapshot()})
        competition_state["started"] = True
        competition_state["running"] = True
        competition_state["last_event"] = "run"
        competition_state["last_error"] = None
        _competition_refresh_current_step()
        return jsonify({"ok": True, "state": _competition_snapshot()})


@app.route('/api/competition/estop', methods=['POST'])
def competition_estop():
    with lock:
        _competition_fail("manual emergency stop")
        return jsonify({"ok": True, "state": _competition_snapshot()})


@app.route('/api/competition/substep', methods=['POST'])
def competition_substep():
    data = request.json or {}
    step = int(data.get("step", 0))
    substep = data.get("substep", "")
    with lock:
        ok, reason = _competition_complete_substep(step, substep)
        status = 200 if ok else 409
        return jsonify({"ok": ok, "reason": reason, "state": _competition_snapshot()}), status


@app.route('/api/competition/checkpoint', methods=['POST'])
def competition_checkpoint():
    data = request.json or {}
    checkpoint = data.get("checkpoint", "")
    approved = bool(data.get("approved", False))
    with lock:
        ok, reason = _competition_respond(checkpoint, approved)
        status = 200 if ok else 409
        return jsonify({"ok": ok, "reason": reason, "state": _competition_snapshot()}), status


@app.route('/api/competition/detection', methods=['POST'])
def competition_detection():
    data = request.json or {}
    with lock:
        ok, reason = _competition_apply_detection(data)
        status = 200 if ok else 409
        return jsonify({"ok": ok, "reason": reason, "state": _competition_snapshot()}), status


@app.route('/api/competition/rotation_estimate', methods=['POST'])
def competition_rotation_estimate():
    data = request.json or {}
    with lock:
        ok, reason = _competition_apply_rotation_estimate(data)
        status = 200 if ok else 409
        return jsonify({"ok": ok, "reason": reason, "state": _competition_snapshot()}), status


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


@app.route('/api/gimbal/move_deg', methods=['POST'])
def gimbal_move_deg():
    d = request.json.get("driver", 0)
    deg = request.json.get("deg", 0)
    data, code = gimbal_get(f"move_deg?d={d}&deg={deg}")
    return jsonify(data), code


@app.route('/api/gimbal/enable', methods=['POST'])
def gimbal_enable():
    d = request.json.get("driver", 0)
    data, code = gimbal_get(f"enable?d={d}")
    return jsonify(data), code


@app.route('/api/gimbal/disable', methods=['POST'])
def gimbal_disable():
    d = request.json.get("driver", 0)
    data, code = gimbal_get(f"disable?d={d}")
    return jsonify(data), code


@app.route('/api/gimbal/motor_current', methods=['POST'])
def gimbal_motor_current():
    d = request.json.get("driver", 0)
    ma = request.json.get("ma", 400)
    data, code = gimbal_get(f"motor_current?d={d}&ma={ma}")
    return jsonify(data), code


@app.route('/api/gimbal/motor_ihold', methods=['POST'])
def gimbal_motor_ihold():
    d = request.json.get("driver", 0)
    ma = request.json.get("ma", 0)
    data, code = gimbal_get(f"motor_ihold?d={d}&ma={ma}")
    return jsonify(data), code


@app.route('/api/gimbal/estop', methods=['POST'])
def gimbal_estop():
    data, code = gimbal_get("estop")
    return jsonify(data), code


@app.route('/api/gimbal/sequence', methods=['POST'])
def gimbal_sequence():
    """Execute a timed sequence of gimbal movements."""
    entries = request.json.get("entries", [])
    entries.sort(key=lambda e: e.get("time_ms", 0))
    threading.Thread(target=_run_gimbal_sequence, args=(entries,), daemon=True).start()
    return jsonify({"ok": True, "entries": len(entries)})


def _run_gimbal_sequence(entries):
    """Execute sequence entries at their scheduled times."""
    start = time.monotonic()
    for entry in entries:
        target_time = start + entry.get("time_ms", 0) / 1000.0
        now = time.monotonic()
        if target_time > now:
            time.sleep(target_time - now)
        d = entry.get("driver", 0)
        if "deg" in entry:
            gimbal_get(f"move_deg?d={d}&deg={entry['deg']}")
        elif "steps" in entry:
            gimbal_get(f"move?d={d}&steps={entry['steps']}")


def restore_positions_loop():
    """On startup, wait for GEO-DUDe to come online, then restore last-known positions."""
    if not servo_positions:
        return
    # Wait for GEO-DUDe to be reachable
    for _ in range(60):
        try:
            urllib.request.urlopen(f"{GEODUDE_URL}/sensors", timeout=2)
            break
        except Exception:
            time.sleep(2)
    else:
        return  # gave up after 2 minutes
    # Restore last-known positions (where servos were before shutdown)
    for name, pw in servo_positions.items():
        if name in CHANNELS:
            send_pwm(name, pw)
            time.sleep(0.05)


if __name__ == '__main__':
    threading.Thread(target=sensor_loop, daemon=True).start()
    threading.Thread(target=watchdog_loop, daemon=True).start()
    threading.Thread(target=positions_flush_loop, daemon=True).start()
    threading.Thread(target=restore_positions_loop, daemon=True).start()
    app.run(host='0.0.0.0', port=8080, threaded=True)
