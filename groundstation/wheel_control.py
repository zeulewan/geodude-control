from flask import Flask, render_template, jsonify, request
import threading
import time
import json
import os
import urllib.request
import urllib.parse
import shutil
import importlib.util
from io import BytesIO

app = Flask(__name__)

GEODUDE_URL = os.environ.get("GEODUDE_URL", "http://192.168.4.166:5000")
ATTITUDE_URL = os.environ.get("ATTITUDE_URL", "http://192.168.4.166:5001")
GIMBAL_URL = os.environ.get("GIMBAL_URL", "http://192.168.4.222")
UPSTREAM_GROUNDSTATION_URL = os.environ.get("UPSTREAM_GROUNDSTATION_URL", "").rstrip("/")
WATCHDOG_TIMEOUT = 3  # seconds — auto-stop if no frontend heartbeat
MODELS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "uploaded_models")
os.makedirs(MODELS_DIR, exist_ok=True)

try:
    import numpy as np
except Exception:
    np = None

try:
    from PIL import Image
except Exception:
    Image = None

YOLO = None

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

camera_frame_state = {
    "jpeg": None,
    "updated_at": 0.0,
    "width": None,
    "height": None,
    "error": None,
}

vision_runtime = {
    "available": importlib.util.find_spec("ultralytics") is not None and np is not None and Image is not None,
    "reason": None if (importlib.util.find_spec("ultralytics") is not None and np is not None and Image is not None) else "Missing local ML runtime packages (ultralytics, numpy, pillow).",
    "slots": {
        1: {"filename": None, "path": None, "uploaded_at": None, "loaded": False, "error": None},
        2: {"filename": None, "path": None, "uploaded_at": None, "loaded": False, "error": None},
        3: {"filename": None, "path": None, "uploaded_at": None, "loaded": False, "error": None},
    },
    "models": {},
    "inference_enabled": True,
    "last_inference_at": None,
    "last_error": None,
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


def _proxy_json_get(url, timeout=3):
    resp = urllib.request.urlopen(url, timeout=timeout)
    return json.loads(resp.read().decode()), getattr(resp, "status", 200)


def _proxy_json_post(url, data=None, timeout=3):
    body = json.dumps(data or {}).encode()
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    resp = urllib.request.urlopen(req, timeout=timeout)
    return json.loads(resp.read().decode()), getattr(resp, "status", 200)


def _camera_stream_url():
    if UPSTREAM_GROUNDSTATION_URL:
        return f"{UPSTREAM_GROUNDSTATION_URL}/api/camera"
    return f"{GEODUDE_URL}/camera"


def _safe_filename(name):
    keep = "._-"
    cleaned = "".join(ch if ch.isalnum() or ch in keep else "_" for ch in (name or "model.pt"))
    return cleaned or "model.pt"


def _vision_slot_snapshot(slot):
    info = vision_runtime["slots"][slot]
    return {
        "slot": slot,
        "filename": info["filename"],
        "uploaded_at": info["uploaded_at"],
        "loaded": info["loaded"],
        "error": info["error"],
    }


def _vision_snapshot():
    return {
        "available": vision_runtime["available"],
        "reason": vision_runtime["reason"],
        "inference_enabled": vision_runtime["inference_enabled"],
        "last_inference_at": vision_runtime["last_inference_at"],
        "last_error": vision_runtime["last_error"],
        "slots": {str(slot): _vision_slot_snapshot(slot) for slot in vision_runtime["slots"]},
    }


def vision_init_from_disk():
    for slot in vision_runtime["slots"]:
        slot_dir = os.path.join(MODELS_DIR, f"slot_{slot}")
        if not os.path.isdir(slot_dir):
            continue
        files = [name for name in os.listdir(slot_dir) if name.lower().endswith(".pt")]
        if not files:
            continue
        files.sort()
        filename = files[-1]
        info = vision_runtime["slots"][slot]
        info["filename"] = filename
        info["path"] = os.path.join(slot_dir, filename)
        info["uploaded_at"] = int(os.path.getmtime(info["path"]))
        info["loaded"] = False
        info["error"] = None
        _vision_load_model(slot)


def _vision_load_model(slot):
    global YOLO
    info = vision_runtime["slots"][slot]
    vision_runtime["models"].pop(slot, None)
    info["loaded"] = False
    if not info["path"]:
        info["error"] = None
        return False
    if not vision_runtime["available"]:
        info["error"] = vision_runtime["reason"]
        return False
    try:
        if YOLO is None:
            from ultralytics import YOLO as _YOLO
            YOLO = _YOLO
        model = YOLO(info["path"])
        vision_runtime["models"][slot] = model
        info["loaded"] = True
        info["error"] = None
        vision_runtime["last_error"] = None
        return True
    except Exception as e:
        info["loaded"] = False
        info["error"] = str(e)
        vision_runtime["last_error"] = str(e)
        return False


def _vision_select_best_detection(result, target_label=None):
    boxes = getattr(result, "boxes", None)
    names = getattr(result, "names", {}) or {}
    if boxes is None or len(boxes) == 0:
        return None

    best = None
    best_conf = -1.0
    for idx in range(len(boxes)):
        conf = float(boxes.conf[idx].item()) if getattr(boxes, "conf", None) is not None else 0.0
        cls_idx = int(boxes.cls[idx].item()) if getattr(boxes, "cls", None) is not None else -1
        label = str(names.get(cls_idx, cls_idx)).lower()
        if target_label and label != target_label:
            continue
        xyxy = boxes.xyxy[idx].tolist()
        if conf > best_conf:
            best_conf = conf
            best = {"label": label, "conf": conf, "xyxy": xyxy}

    if best is None and target_label:
        return _vision_select_best_detection(result, None)
    return best


def _decode_jpeg_to_array(jpeg_bytes):
    if not jpeg_bytes or Image is None or np is None:
        return None, None, None
    img = Image.open(BytesIO(jpeg_bytes)).convert("RGB")
    width, height = img.size
    return np.array(img), width, height


def _capture_camera_frames_loop():
    while True:
        try:
            resp = urllib.request.urlopen(_camera_stream_url(), timeout=10)
            buf = b""
            while True:
                chunk = resp.read(4096)
                if not chunk:
                    break
                buf += chunk
                start = buf.find(b"\xff\xd8")
                end = buf.find(b"\xff\xd9")
                if start != -1 and end != -1 and end > start:
                    jpeg = buf[start:end + 2]
                    buf = buf[end + 2:]
                    width = None
                    height = None
                    if Image is not None:
                        try:
                            with Image.open(BytesIO(jpeg)) as img:
                                width, height = img.size
                        except Exception:
                            pass
                    with lock:
                        camera_frame_state["jpeg"] = jpeg
                        camera_frame_state["updated_at"] = time.monotonic()
                        camera_frame_state["width"] = width
                        camera_frame_state["height"] = height
                        camera_frame_state["error"] = None
        except Exception as e:
            with lock:
                camera_frame_state["error"] = str(e)
            time.sleep(1.0)


def _competition_handle_model_detection(slot, frame, width, height):
    model = vision_runtime["models"].get(slot)
    if model is None:
        return
    try:
        results = model(frame, verbose=False)
    except Exception as e:
        vision_runtime["last_error"] = str(e)
        vision_runtime["slots"][slot]["error"] = str(e)
        return

    vision_runtime["last_inference_at"] = time.time()
    if not results:
        return

    result = results[0]
    if slot == 1:
        det = _vision_select_best_detection(result, "snoopy")
        if det is None:
            return
        x1, y1, x2, y2 = det["xyxy"]
        payload = {
            "class_label": det["label"],
            "confidence": det["conf"],
            "bbox_center": {"x": (x1 + x2) / 2.0, "y": (y1 + y2) / 2.0},
            "bbox_size": {"w": max(0.0, x2 - x1), "h": max(0.0, y2 - y1)},
            "frame_width_px": width,
            "frame_height_px": height,
        }
        with lock:
            if competition_state["running"] and not competition_state["halted"]:
                _competition_apply_detection(payload)
    elif slot == 2:
        det = _vision_select_best_detection(result)
        if det is None:
            return
        with lock:
            if competition_state["running"] and not competition_state["halted"]:
                _competition_apply_rotation_estimate({"rpm": float(det["conf"]) * 100.0})


def _vision_inference_loop():
    while True:
        time.sleep(0.15)
        if not vision_runtime["inference_enabled"] or not vision_runtime["available"]:
            continue
        with lock:
            active_slot = competition_state["activeVisionModel"] if competition_state["running"] and not competition_state["halted"] else None
            jpeg = camera_frame_state["jpeg"]
        if active_slot not in (1, 2):
            continue
        if not vision_runtime["slots"][active_slot]["path"]:
            continue
        if active_slot not in vision_runtime["models"]:
            _vision_load_model(active_slot)
            continue
        frame, width, height = _decode_jpeg_to_array(jpeg)
        if frame is None:
            continue
        _competition_handle_model_detection(active_slot, frame, width, height)


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
        "searchLockMarginPx": 32.0,
        "searchFrameWidthPx": 640.0,
        "searchFrameHeightPx": 480.0,
        "searchLockDeadband": 0.05,
        "searchLockKp": 6.0,
        "searchLockMaxCommand": 2.0,
        "searchLockError": None,
        "searchLockCommand": 0.0,
        "searchAngleDeadbandDeg": 1.0,
        "searchAngleKp": 0.06,
        "searchAngleMaxCommand": 2.0,
        "model1AngleSetpointDeg": None,
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
        "searchScanActive": False,
        "snoopyDetection": {
            "active": False,
            "found": False,
            "bbox_center": {"x": None, "y": None},
            "bbox_size": {"w": None, "h": None},
            "bbox_center_px": {"x": None, "y": None},
            "bbox_size_px": {"w": None, "h": None},
            "frame_size_px": {"w": None, "h": None},
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
        "searchLockMarginPx": competition_state["searchLockMarginPx"],
        "searchFrameWidthPx": competition_state["searchFrameWidthPx"],
        "searchFrameHeightPx": competition_state["searchFrameHeightPx"],
        "searchLockDeadband": competition_state["searchLockDeadband"],
        "searchLockKp": competition_state["searchLockKp"],
        "searchLockMaxCommand": competition_state["searchLockMaxCommand"],
        "searchLockError": competition_state["searchLockError"],
        "searchLockCommand": competition_state["searchLockCommand"],
        "searchAngleDeadbandDeg": competition_state["searchAngleDeadbandDeg"],
        "searchAngleKp": competition_state["searchAngleKp"],
        "searchAngleMaxCommand": competition_state["searchAngleMaxCommand"],
        "model1AngleSetpointDeg": competition_state["model1AngleSetpointDeg"],
        "rotationEstimateRpm": competition_state["rotationEstimateRpm"],
        "rotationStableToleranceRpm": competition_state["rotationStableToleranceRpm"],
        "rotationStableSeconds": competition_state["rotationStableSeconds"],
        "demoSequenceState": competition_state["demoSequenceState"],
        "demoCommandAngle": competition_state["demoCommandAngle"],
        "rotationMatchActive": competition_state["rotationMatchActive"],
        "rotationMatchTargetRpm": competition_state["rotationMatchTargetRpm"],
        "activeVisionModel": competition_state["activeVisionModel"],
        "visionState": competition_state["visionState"],
        "searchScanActive": competition_state["searchScanActive"],
        "snoopyDetection": json.loads(json.dumps(competition_state["snoopyDetection"])),
        "substeps": json.loads(json.dumps(competition_state["substeps"])),
        "activeCheckpoint": _competition_active_checkpoint(),
        "last_event": competition_state["last_event"],
        "last_error": competition_state["last_error"],
        "complete": _competition_step_complete(8),
    }
    return snapshot


def _competition_fail(reason):
    _competition_safe_stop_mace()
    competition_state["halted"] = True
    competition_state["armed"] = False
    competition_state["running"] = False
    competition_state["maceState"] = "SAFE"
    competition_state["searchLockError"] = None
    competition_state["searchLockCommand"] = 0.0
    competition_state["model1AngleSetpointDeg"] = None
    competition_state["rotationEstimateRpm"] = None
    competition_state["rotationStableSince"] = None
    competition_state["demoSequenceState"] = "IDLE"
    competition_state["demoPhaseStartedAt"] = None
    competition_state["demoCommandAngle"] = None
    competition_state["rotationMatchActive"] = False
    competition_state["rotationMatchTargetRpm"] = None
    competition_state["searchScanActive"] = False
    competition_state["last_event"] = "halted"
    competition_state["last_error"] = reason


def _competition_allow_actions():
    return competition_state["armed"] and competition_state["running"] and not competition_state["halted"]


def _competition_safe_stop_mace():
    mace["target"] = 0.0
    mace["velocity"] = 0.0
    mace["enabled"] = False
    send_velocity(0.0)


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
        "bbox_center_px": {"x": None, "y": None},
        "bbox_size_px": {"w": None, "h": None},
        "frame_size_px": {
            "w": float(competition_state["searchFrameWidthPx"]),
            "h": float(competition_state["searchFrameHeightPx"]),
        },
        "confidence": None,
        "class_label": "snoopy",
    }
    competition_state["searchLockError"] = None
    competition_state["searchLockCommand"] = 0.0
    competition_state["model1AngleSetpointDeg"] = None


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
    _competition_safe_stop_mace()


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

    frame_width_px = float(
        payload.get("frame_width_px")
        or payload.get("image_width_px")
        or competition_state["searchFrameWidthPx"]
    )
    frame_height_px = float(
        payload.get("frame_height_px")
        or payload.get("image_height_px")
        or competition_state["searchFrameHeightPx"]
    )
    raw_center_x = float(center["x"])
    raw_center_y = float(center["y"])
    raw_size_w = float(size["w"])
    raw_size_h = float(size["h"])

    if raw_center_x > 1.0 or raw_center_y > 1.0:
        bbox_center_px = {"x": raw_center_x, "y": raw_center_y}
        bbox_center = {
            "x": raw_center_x / frame_width_px if frame_width_px else 0.0,
            "y": raw_center_y / frame_height_px if frame_height_px else 0.0,
        }
    else:
        bbox_center = {"x": raw_center_x, "y": raw_center_y}
        bbox_center_px = {
            "x": raw_center_x * frame_width_px,
            "y": raw_center_y * frame_height_px,
        }

    if raw_size_w > 1.0 or raw_size_h > 1.0:
        bbox_size_px = {"w": raw_size_w, "h": raw_size_h}
        bbox_size = {
            "w": raw_size_w / frame_width_px if frame_width_px else 0.0,
            "h": raw_size_h / frame_height_px if frame_height_px else 0.0,
        }
    else:
        bbox_size = {"w": raw_size_w, "h": raw_size_h}
        bbox_size_px = {
            "w": raw_size_w * frame_width_px,
            "h": raw_size_h * frame_height_px,
        }
    competition_state["snoopyDetection"] = {
        "active": True,
        "found": True,
        "bbox_center": bbox_center,
        "bbox_size": bbox_size,
        "bbox_center_px": bbox_center_px,
        "bbox_size_px": bbox_size_px,
        "frame_size_px": {"w": frame_width_px, "h": frame_height_px},
        "confidence": float(confidence),
        "class_label": "snoopy",
    }

    if not competition_state["substeps"]["4"]["snoopy-found"]:
        competition_state["substeps"]["4"]["snoopy-found"] = True
        competition_state["visionState"] = "FOUND"
        competition_state["maceState"] = "CENTERING"
        _competition_apply_mace_velocity(0.0)

    center_error_px = bbox_center_px["x"] - (frame_width_px / 2.0)
    competition_state["searchLockError"] = round(center_error_px, 2)
    competition_state["model1AngleSetpointDeg"] = None
    deadband_px = float(competition_state["searchLockMarginPx"])
    if abs(center_error_px) <= deadband_px:
        competition_state["substeps"]["4"]["snoopy-lock"] = True
        competition_state["visionState"] = "LOCKED"
        competition_state["maceState"] = "LOCKED"
        competition_state["searchLockCommand"] = 0.0
        competition_state["searchScanActive"] = False
        _competition_apply_mace_velocity(0.0)
    else:
        kp = float(competition_state["searchLockKp"])
        max_cmd = float(competition_state["searchLockMaxCommand"])
        correction = max(-max_cmd, min(max_cmd, -kp * (center_error_px / max(frame_width_px, 1.0))))
        competition_state["searchLockCommand"] = round(correction, 4)
        competition_state["visionState"] = "CENTERING"
        competition_state["maceState"] = "CENTERING"
        competition_state["searchScanActive"] = False
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
        mace["target"] = float(competition_state["searchRotationSpeed"])
        mace["velocity"] = float(competition_state["searchRotationSpeed"])
        mace["error"] = None
        competition_state["maceState"] = "SCANNING"
        competition_state["visionState"] = "SEARCHING"
        competition_state["searchScanActive"] = True
        competition_state["activeVisionModel"] = 1
        send_velocity(float(competition_state["searchRotationSpeed"]))
    elif step == "4" and substep == "search-snoopy":
        competition_state["activeVisionModel"] = 1
        competition_state["visionState"] = "SEARCHING"
        competition_state["maceState"] = "SEARCHING"
        competition_state["searchScanActive"] = True
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
        # Step 2 begins by starting the first model. Model 1 consumes camera frames.
        competition_state["substeps"]["2"]["snoopy-detect"] = True
        competition_state["activeVisionModel"] = 1
        competition_state["visionState"] = "MODEL_READY"
        _competition_reset_detection_tracking()
    elif checkpoint == "everything-nominal":
        competition_state["everythingNominalResolved"] = True
        competition_state["substeps"]["4"]["search-snoopy"] = True
        competition_state["activeVisionModel"] = 1
        competition_state["visionState"] = "SEARCHING"
        competition_state["maceState"] = "SEARCHING"
        competition_state["searchScanActive"] = True
        if competition_state["substeps"]["2"]["mace"]:
            _competition_apply_mace_velocity(competition_state["searchRotationSpeed"])
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
    _competition_safe_stop_mace()
    competition_state.clear()
    competition_state.update(competition_default_state())


def send_velocity(velocity):
    """Send velocity command (rad/s) to Pico via GEO-DUDe /simplefoc endpoint."""
    try:
        if UPSTREAM_GROUNDSTATION_URL:
            _proxy_json_post(f"{UPSTREAM_GROUNDSTATION_URL}/api/mace/enable", {})
            _proxy_json_post(f"{UPSTREAM_GROUNDSTATION_URL}/api/mace/velocity", {"target": round(float(velocity), 4)})
            mace["error"] = None
            return True
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
        if UPSTREAM_GROUNDSTATION_URL:
            _proxy_json_post(f"{UPSTREAM_GROUNDSTATION_URL}/api/pwm", {"channel": channel, "pw": pw})
            return True
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
        if UPSTREAM_GROUNDSTATION_URL:
            _proxy_json_post(f"{UPSTREAM_GROUNDSTATION_URL}/api/all_off", {})
            return True
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
            if UPSTREAM_GROUNDSTATION_URL:
                data, _ = _proxy_json_get(f"{UPSTREAM_GROUNDSTATION_URL}/api/sensors", timeout=2)
                with lock:
                    state["gyro"] = data.get("gyro", {"x": 0, "y": 0, "z": 0})
                    state["accel"] = data.get("accel", {"x": 0, "y": 0, "z": 0})
                    state["encoder_angle"] = data.get("encoder_angle", 0)
                    state["rpm"] = data.get("rpm", 0)
                    state["connected"] = bool(data.get("connected", False))
            else:
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
            if UPSTREAM_GROUNDSTATION_URL:
                sfoc, _ = _proxy_json_get(f"{UPSTREAM_GROUNDSTATION_URL}/api/mace/status", timeout=2)
            else:
                resp = urllib.request.urlopen(f"{GEODUDE_URL}/simplefoc/status", timeout=2)
                sfoc = json.loads(resp.read().decode())
            with lock:
                mace["connected"] = sfoc.get("connected", False)
                t = sfoc.get("target", sfoc.get("velocity"))
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
        if UPSTREAM_GROUNDSTATION_URL:
            upstream, _ = _proxy_json_get(f"{UPSTREAM_GROUNDSTATION_URL}/api/system", timeout=2)
            gd = upstream.get("geodude", upstream)
        else:
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
        resp = ur.urlopen(_camera_stream_url(), timeout=5)
        def generate():
            while True:
                chunk = resp.read(4096)
                if not chunk:
                    break
                yield chunk
        return app.response_class(generate(), mimetype=resp.headers.get('Content-Type', 'multipart/x-mixed-replace; boundary=frame'))
    except Exception as e:
        return jsonify({"error": str(e)}), 502


@app.route('/api/vision/status')
def vision_status():
    with lock:
        return jsonify(_vision_snapshot())


@app.route('/api/vision/upload', methods=['POST'])
def vision_upload():
    try:
        slot = int(request.form.get("slot", "0"))
    except Exception:
        slot = 0
    if slot not in vision_runtime["slots"]:
        return jsonify({"ok": False, "reason": "invalid slot", "vision": _vision_snapshot()}), 400
    if "model" not in request.files:
        return jsonify({"ok": False, "reason": "missing model file", "vision": _vision_snapshot()}), 400

    file = request.files["model"]
    filename = _safe_filename(file.filename or f"model_{slot}.pt")
    if not filename.lower().endswith(".pt"):
        return jsonify({"ok": False, "reason": "only .pt models are supported for backend inference", "vision": _vision_snapshot()}), 400

    slot_dir = os.path.join(MODELS_DIR, f"slot_{slot}")
    os.makedirs(slot_dir, exist_ok=True)
    for name in os.listdir(slot_dir):
        try:
            os.unlink(os.path.join(slot_dir, name))
        except Exception:
            pass
    target = os.path.join(slot_dir, filename)
    file.save(target)

    with lock:
        info = vision_runtime["slots"][slot]
        info["filename"] = filename
        info["path"] = target
        info["uploaded_at"] = int(time.time())
        info["error"] = None
        info["loaded"] = False
        loaded = _vision_load_model(slot)
        return jsonify({
            "ok": True,
            "slot": slot,
            "loaded": loaded,
            "vision": _vision_snapshot(),
        })


@app.route('/api/vision/clear', methods=['POST'])
def vision_clear():
    data = request.json or {}
    try:
        slot = int(data.get("slot", 0))
    except Exception:
        slot = 0
    if slot not in vision_runtime["slots"]:
        return jsonify({"ok": False, "reason": "invalid slot", "vision": _vision_snapshot()}), 400
    slot_dir = os.path.join(MODELS_DIR, f"slot_{slot}")
    if os.path.isdir(slot_dir):
        shutil.rmtree(slot_dir, ignore_errors=True)
    with lock:
        vision_runtime["models"].pop(slot, None)
        vision_runtime["slots"][slot] = {"filename": None, "path": None, "uploaded_at": None, "loaded": False, "error": None}
        return jsonify({"ok": True, "vision": _vision_snapshot()})


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
            if competition_state["searchScanActive"] and competition_state["currentStep"] in (2, 3, 4):
                _competition_apply_mace_velocity(competition_state["searchRotationSpeed"])
        if "searchLockMarginPx" in data:
            competition_state["searchLockMarginPx"] = max(2.0, min(200.0, float(data.get("searchLockMarginPx", 32.0))))
        if "searchFrameWidthPx" in data:
            competition_state["searchFrameWidthPx"] = max(64.0, min(4096.0, float(data.get("searchFrameWidthPx", 640.0))))
        if "searchFrameHeightPx" in data:
            competition_state["searchFrameHeightPx"] = max(64.0, min(4096.0, float(data.get("searchFrameHeightPx", 480.0))))
        if "searchLockDeadband" in data:
            competition_state["searchLockDeadband"] = max(0.005, min(0.25, float(data.get("searchLockDeadband", 0.05))))
        if "searchLockKp" in data:
            competition_state["searchLockKp"] = max(0.1, min(25.0, float(data.get("searchLockKp", 6.0))))
        if "searchLockMaxCommand" in data:
            competition_state["searchLockMaxCommand"] = max(0.1, min(8.0, float(data.get("searchLockMaxCommand", 2.0))))
        if "searchAngleDeadbandDeg" in data:
            competition_state["searchAngleDeadbandDeg"] = max(0.1, min(15.0, float(data.get("searchAngleDeadbandDeg", 1.0))))
        if "searchAngleKp" in data:
            competition_state["searchAngleKp"] = max(0.001, min(1.0, float(data.get("searchAngleKp", 0.06))))
        if "searchAngleMaxCommand" in data:
            competition_state["searchAngleMaxCommand"] = max(0.1, min(8.0, float(data.get("searchAngleMaxCommand", 2.0))))
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
            competition_state["searchScanActive"] = False
            _competition_safe_stop_mace()
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
        if UPSTREAM_GROUNDSTATION_URL:
            url = f"{UPSTREAM_GROUNDSTATION_URL}/api/attitude/{path}"
            if method == "POST":
                return _proxy_json_post(url, data, timeout=3)
            return _proxy_json_get(url, timeout=3)
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
        if UPSTREAM_GROUNDSTATION_URL:
            return _proxy_json_get(f"{UPSTREAM_GROUNDSTATION_URL}/api/gimbal/{path}", timeout=3)
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
