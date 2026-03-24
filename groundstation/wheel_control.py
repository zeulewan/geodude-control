from flask import Flask, render_template, jsonify, request
import threading
import time
import json
import os
import select
import struct
import urllib.request
import math

app = Flask(__name__)

GEODUDE_URL = "http://192.168.4.166:5000"
ATTITUDE_URL = "http://192.168.4.166:5001"
GIMBAL_URL = "http://192.168.4.222"
WATCHDOG_TIMEOUT = 3  # seconds — auto-stop if no frontend heartbeat
RAMP_HZ = 20  # ramp loop tick rate
CONTROLLER_HZ = 20
CONTROLLER_SCAN_INTERVAL = 2.0
CONTROLLER_LIMIT_US = 450
DEFAULT_PORT = int(os.environ.get("WHEEL_CONTROL_PORT", "8080"))
DRY_RUN = os.environ.get("WHEEL_CONTROL_DRY_RUN", "0").lower() in ("1", "true", "yes", "on")
RESTORE_ON_START = os.environ.get("WHEEL_CONTROL_RESTORE_ON_START", "1").lower() not in ("0", "false", "no", "off")
CONTROLLER_DEADZONE = 0.12
CONTROLLER_ACTIVE_THRESHOLD = 0.2
JS_EVENT_BUTTON = 0x01
JS_EVENT_AXIS = 0x02
JS_EVENT_INIT = 0x80

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

CONTROLLER_ARM_BINDINGS = {
    "left": {
        "lx": [{"channel": "B1", "scale": 1.0}],
        "ly": [{"channel": "S1", "scale": -1.0}],
        "ry": [{"channel": "E1", "scale": -1.0}],
        "rx": [
            {"channel": "W1A", "scale": 1.0},
            {"channel": "W1B", "scale": -1.0},
        ],
    },
    "right": {
        "lx": [{"channel": "B2", "scale": -1.0}],
        "ly": [{"channel": "S2", "scale": -1.0}],
        "ry": [{"channel": "E2", "scale": -1.0}],
        "rx": [
            {"channel": "W2A", "scale": -1.0},
            {"channel": "W2B", "scale": 1.0},
        ],
    },
}

CONTROLLER_AXIS_ORDER = {
    0: "lx",
    1: "ly",
    3: "rx",
    4: "ry",
}

CONTROLLER_LABELS = {
    "lx": "Left stick X -> base yaw (B1/B2)",
    "ly": "Left stick Y -> shoulder pair (S1/S2)",
    "ry": "Right stick Y -> elbow pair (E1/E2)",
    "rx": "Right stick X -> wrist pair (W1/W2)",
}

DEADMAN_BUTTONS = {4, 5}

controller_state = {
    "enabled": False,
    "connected": False,
    "active": False,
    "deadman": False,
    "device": None,
    "last_error": None,
    "axes": {name: 0.0 for name in CONTROLLER_LABELS},
    "buttons": {},
    "updated_at": 0.0,
    "selected_arm": "left",
}

IK_LINKS_MM = {
    "base": 103.0,
    "upper": 310.0,
    "forearm": 230.0,
    "wrist_a": 55.0,
    "tool": 75.0,
}
IK_NEUTRAL_PWM = {
    "B1": 1500, "S1": 1500, "E1": 1500, "W1A": 1500, "W1B": 1500,
    "B2": 1500, "S2": 1500, "E2": 1500, "W2A": 1500, "W2B": 1500,
}
IK_SOLVER_NOTES = [
    "Cartesian IK now optimizes base, shoulder, elbow, and wrist pitch against the measured link lengths.",
    "The dev solver keeps both wrist joints active: wrist roll auto-biases away from neutral and wrist pitch avoids straight-through poses.",
    "PWM-angle calibration is approximate and should be tuned on hardware before merge.",
]
IK_ARM_CONFIG = {
    "left": {
        "side_bias": -1.0,
        "anchor": {"x": -120.0, "y": 50.0, "z": -55.0},
        "joints": {
            "base": {"channel": "B1", "sign": 1.0, "us_per_rad": 320.0, "min_angle": -1.35, "max_angle": 1.35},
            "shoulder": {"channel": "S1", "sign": -1.0, "us_per_rad": 320.0, "min_angle": -1.2, "max_angle": 1.35},
            "elbow": {"channel": "E1", "sign": -1.0, "us_per_rad": 320.0, "min_angle": -0.2, "max_angle": 2.9},
            "wrist_roll": {"channel": "W1A", "sign": 1.0, "us_per_rad": 320.0, "min_angle": -1.5, "max_angle": 1.5},
            "wrist_pitch": {"channel": "W1B", "sign": -1.0, "us_per_rad": 320.0, "min_angle": -1.5, "max_angle": 1.5},
        },
    },
    "right": {
        "side_bias": 1.0,
        "anchor": {"x": 120.0, "y": 50.0, "z": -55.0},
        "joints": {
            "base": {"channel": "B2", "sign": -1.0, "us_per_rad": 320.0, "min_angle": -1.35, "max_angle": 1.35},
            "shoulder": {"channel": "S2", "sign": -1.0, "us_per_rad": 320.0, "min_angle": -1.2, "max_angle": 1.35},
            "elbow": {"channel": "E2", "sign": -1.0, "us_per_rad": 320.0, "min_angle": -0.2, "max_angle": 2.9},
            "wrist_roll": {"channel": "W2A", "sign": -1.0, "us_per_rad": 320.0, "min_angle": -1.5, "max_angle": 1.5},
            "wrist_pitch": {"channel": "W2B", "sign": 1.0, "us_per_rad": 320.0, "min_angle": -1.5, "max_angle": 1.5},
        },
    },
}
ik_state = {
    "last_solution": None,
}

SERVO_SETTINGS = {"speed": 50, "ramp": 20}
controller_channel_velocity = {name: 0.0 for name in CHANNELS if name != "MACE"}
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


def send_motor(pw):
    """Send PWM to MACE channel via legacy /motor endpoint."""
    if DRY_RUN:
        return True
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
    if DRY_RUN:
        return True
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
    if DRY_RUN:
        return True
    try:
        req = urllib.request.Request(f"{GEODUDE_URL}/pwm/off", method="POST")
        urllib.request.urlopen(req, timeout=3)
        return True
    except Exception:
        return False


def clamp(value, lo, hi):
    return max(lo, min(hi, value))


def controller_axis_value(name):
    with lock:
        value = float(controller_state["axes"].get(name, 0.0))
    if abs(value) < CONTROLLER_DEADZONE:
        return 0.0
    return value


def controller_limits(channel):
    center = servo_neutral.get(channel)
    if center is None:
        center = servo_positions.get(channel, 1000)
    center = int(center)
    return (
        clamp(center - CONTROLLER_LIMIT_US, 500, 2500),
        clamp(center + CONTROLLER_LIMIT_US, 500, 2500),
    )


def ik_joint_names():
    return ("base", "shoulder", "elbow", "wrist_roll", "wrist_pitch")


def ik_arm_name(selected_arm):
    return "right" if selected_arm == "right" else "left"


def ik_joint_config(selected_arm, joint_name):
    return IK_ARM_CONFIG[ik_arm_name(selected_arm)]["joints"][joint_name]


def ik_joint_neutral(channel):
    neutral = IK_NEUTRAL_PWM.get(channel)
    if neutral is None:
        neutral = servo_neutral.get(channel)
    if neutral is None:
        neutral = servo_positions.get(channel, 1500)
    return int(neutral)


def ik_angle_from_pwm(selected_arm, joint_name, pw=None):
    config = ik_joint_config(selected_arm, joint_name)
    channel = config["channel"]
    neutral = ik_joint_neutral(channel)
    if pw is None:
        pw = servo_positions.get(channel, neutral)
    pw = int(pw)
    angle = ((pw - neutral) / float(config["us_per_rad"])) * float(config["sign"])
    return clamp(angle, config["min_angle"], config["max_angle"])


def ik_pwm_from_angle(selected_arm, joint_name, angle):
    config = ik_joint_config(selected_arm, joint_name)
    angle = clamp(float(angle), config["min_angle"], config["max_angle"])
    neutral = ik_joint_neutral(config["channel"])
    target = neutral + int(round(angle * float(config["us_per_rad"]) * float(config["sign"])))
    return clamp(target, 500, 2500)


def ik_pose_from_angles(selected_arm, angles):
    arm = IK_ARM_CONFIG[ik_arm_name(selected_arm)]
    side_bias = float(arm["side_bias"])
    anchor = dict(arm["anchor"])
    base = float(angles["base"])
    shoulder = float(angles["shoulder"])
    elbow = float(angles["elbow"])
    wrist_roll = float(angles["wrist_roll"])
    wrist_pitch = float(angles["wrist_pitch"])

    def rotate_base_axis(vec, roll):
        return {
            "x": vec["x"],
            "y": vec["y"] * math.cos(roll) - vec["z"] * math.sin(roll),
            "z": vec["y"] * math.sin(roll) + vec["z"] * math.cos(roll),
        }

    def add_point(a, b):
        return {"x": a["x"] + b["x"], "y": a["y"] + b["y"], "z": a["z"] + b["z"]}

    def scale_vec(vec, scale):
        return {"x": vec["x"] * scale, "y": vec["y"] * scale, "z": vec["z"] * scale}

    def normalize_vec(vec):
        mag = math.sqrt(vec["x"] * vec["x"] + vec["y"] * vec["y"] + vec["z"] * vec["z"]) or 1.0
        return {"x": vec["x"] / mag, "y": vec["y"] / mag, "z": vec["z"] / mag}

    def cross_vec(a, b):
        return {
            "x": a["y"] * b["z"] - a["z"] * b["y"],
            "y": a["z"] * b["x"] - a["x"] * b["z"],
            "z": a["x"] * b["y"] - a["y"] * b["x"],
        }

    def rotate_around_axis(vec, axis, angle):
        unit = normalize_vec(axis)
        cos_a = math.cos(angle)
        sin_a = math.sin(angle)
        dot = vec["x"] * unit["x"] + vec["y"] * unit["y"] + vec["z"] * unit["z"]
        cross = cross_vec(unit, vec)
        return {
            "x": vec["x"] * cos_a + cross["x"] * sin_a + unit["x"] * dot * (1.0 - cos_a),
            "y": vec["y"] * cos_a + cross["y"] * sin_a + unit["y"] * dot * (1.0 - cos_a),
            "z": vec["z"] * cos_a + cross["z"] * sin_a + unit["z"] * dot * (1.0 - cos_a),
        }

    def pitch_direction(pitch, roll):
        return rotate_base_axis({
            "x": math.cos(pitch) * side_bias,
            "y": math.sin(pitch),
            "z": 0.0,
        }, roll)

    shoulder_mount = add_point(anchor, rotate_base_axis({"x": IK_LINKS_MM["base"] * side_bias, "y": 0.0, "z": 0.0}, base))
    upper_dir = pitch_direction(shoulder, base)
    elbow_point = add_point(shoulder_mount, scale_vec(upper_dir, IK_LINKS_MM["upper"]))
    fore_dir = pitch_direction(shoulder + elbow, base)
    wrist_a_point = add_point(elbow_point, scale_vec(fore_dir, IK_LINKS_MM["forearm"]))
    wrist_b_point = add_point(wrist_a_point, scale_vec(fore_dir, IK_LINKS_MM["wrist_a"]))
    final_dir = pitch_direction(shoulder + elbow + wrist_pitch, base)
    tool_dir = rotate_around_axis(final_dir, fore_dir, wrist_roll)
    tip_point = add_point(wrist_b_point, scale_vec(normalize_vec(tool_dir), IK_LINKS_MM["tool"]))
    return {
        "anchor": anchor,
        "shoulder_mount": shoulder_mount,
        "elbow": elbow_point,
        "wrist_a": wrist_a_point,
        "wrist_b": wrist_b_point,
        "tip": tip_point,
    }


def ik_current_angles(selected_arm):
    return {joint: ik_angle_from_pwm(selected_arm, joint) for joint in ik_joint_names()}


def ik_current_pose(selected_arm):
    return ik_pose_from_angles(selected_arm, ik_current_angles(selected_arm))


def ik_config_payload():
    return {
        "links_mm": dict(IK_LINKS_MM),
        "notes": list(IK_SOLVER_NOTES),
        "arms": {
            arm_name: {
                "anchor": dict(config["anchor"]),
                "joints": {
                    joint_name: {
                        "channel": joint_cfg["channel"],
                        "sign": joint_cfg["sign"],
                        "us_per_rad": joint_cfg["us_per_rad"],
                        "min_angle": joint_cfg["min_angle"],
                        "max_angle": joint_cfg["max_angle"],
                    }
                    for joint_name, joint_cfg in config["joints"].items()
                },
            }
            for arm_name, config in IK_ARM_CONFIG.items()
        },
    }


def ik_status_payload():
    with lock:
        selected_arm = controller_state["selected_arm"]
        last_solution = ik_state["last_solution"]
    arms = {}
    for arm_name in IK_ARM_CONFIG:
        angles = ik_current_angles(arm_name)
        pose = ik_pose_from_angles(arm_name, angles)
        target_pwms = {
            ik_joint_config(arm_name, joint_name)["channel"]: int(servo_positions.get(ik_joint_config(arm_name, joint_name)["channel"], ik_joint_neutral(ik_joint_config(arm_name, joint_name)["channel"])))
            for joint_name in ik_joint_names()
        }
        arms[arm_name] = {
            "angles_rad": {joint: round(value, 5) for joint, value in angles.items()},
            "angles_deg": {joint: round(math.degrees(value), 3) for joint, value in angles.items()},
            "tip_mm": {axis: round(pose["tip"][axis], 2) for axis in ("x", "y", "z")},
            "target_pwms": target_pwms,
        }
    return {
        "selected_arm": selected_arm,
        "arms": arms,
        "config": ik_config_payload(),
        "last_solution": last_solution,
    }


def ik_solve_arm(selected_arm, target_xyz, wrist_roll_deg=None):
    arm_name = ik_arm_name(selected_arm)
    arm = IK_ARM_CONFIG[arm_name]
    side_bias = float(arm["side_bias"])
    anchor = arm["anchor"]
    target = {axis: float(target_xyz[axis]) for axis in ("x", "y", "z")}
    rel_x = target["x"] - float(anchor["x"])
    rel_y = target["y"] - float(anchor["y"])
    rel_z = target["z"] - float(anchor["z"])
    upper_len = IK_LINKS_MM["upper"]
    fore_len = IK_LINKS_MM["forearm"] + IK_LINKS_MM["wrist_a"] + IK_LINKS_MM["tool"]
    plane_x = side_bias * rel_x - IK_LINKS_MM["base"]
    base_limits = ik_joint_config(arm_name, "base")
    desired_base = math.atan2(rel_z, rel_y) if abs(rel_y) > 1e-9 or abs(rel_z) > 1e-9 else ik_angle_from_pwm(arm_name, "base")
    base_angle = clamp(desired_base, base_limits["min_angle"], base_limits["max_angle"])
    plane_y = rel_y * math.cos(base_angle) + rel_z * math.sin(base_angle)
    plane_side_error = -rel_y * math.sin(base_angle) + rel_z * math.cos(base_angle)
    planar_distance = math.hypot(plane_x, plane_y)
    max_reach = upper_len + fore_len - 1e-6
    min_reach = abs(upper_len - fore_len) + 1e-6
    requested_wrist_roll_deg = None if wrist_roll_deg is None else round(float(wrist_roll_deg), 3)
    if planar_distance > max_reach or planar_distance < min_reach:
        return {
            "ok": False,
            "arm": arm_name,
            "reason": "unreachable",
            "distance_mm": round(planar_distance, 3),
            "reachable_range_mm": [round(min_reach, 3), round(max_reach, 3)],
            "target_mm": {axis: round(target[axis], 3) for axis in ("x", "y", "z")},
            "requested_wrist_roll_deg": requested_wrist_roll_deg,
        }

    cos_elbow = (planar_distance * planar_distance - upper_len * upper_len - fore_len * fore_len) / (2.0 * upper_len * fore_len)
    cos_elbow = clamp(cos_elbow, -1.0, 1.0)
    elbow_candidates = [math.acos(cos_elbow), -math.acos(cos_elbow)]
    wrist_roll_cfg = ik_joint_config(arm_name, "wrist_roll")
    auto_wrist_roll_angle = 0.45 * side_bias
    if wrist_roll_deg is None or abs(float(wrist_roll_deg)) < 1.0:
        wrist_roll_angle = auto_wrist_roll_angle
    else:
        wrist_roll_angle = math.radians(float(wrist_roll_deg))
    wrist_roll_angle = clamp(wrist_roll_angle, wrist_roll_cfg["min_angle"], wrist_roll_cfg["max_angle"])
    min_active_wrist_pitch = 0.3

    def within_limits(joint_name, angle):
        cfg = ik_joint_config(arm_name, joint_name)
        return cfg["min_angle"] - 1e-6 <= angle <= cfg["max_angle"] + 1e-6

    def make_candidate(base, shoulder, elbow, wrist_pitch):
        candidate = {
            "base": clamp(base, ik_joint_config(arm_name, "base")["min_angle"], ik_joint_config(arm_name, "base")["max_angle"]),
            "shoulder": clamp(shoulder, ik_joint_config(arm_name, "shoulder")["min_angle"], ik_joint_config(arm_name, "shoulder")["max_angle"]),
            "elbow": clamp(elbow, ik_joint_config(arm_name, "elbow")["min_angle"], ik_joint_config(arm_name, "elbow")["max_angle"]),
            "wrist_roll": wrist_roll_angle,
            "wrist_pitch": clamp(wrist_pitch, ik_joint_config(arm_name, "wrist_pitch")["min_angle"], ik_joint_config(arm_name, "wrist_pitch")["max_angle"]),
        }
        if abs(candidate["wrist_pitch"]) < min_active_wrist_pitch:
            candidate["wrist_pitch"] = math.copysign(min_active_wrist_pitch, candidate["wrist_pitch"] if abs(candidate["wrist_pitch"]) > 1e-6 else (-shoulder - elbow) or side_bias)
        return candidate if all(within_limits(name, candidate[name]) for name in ("base", "shoulder", "elbow", "wrist_roll", "wrist_pitch")) else None

    def evaluate(candidate):
        if candidate is None:
            return None
        pose = ik_pose_from_angles(arm_name, candidate)
        error = math.sqrt(sum((pose["tip"][axis] - target[axis]) ** 2 for axis in ("x", "y", "z")))
        stiffness_cost = (
            52.0 * (candidate["shoulder"] ** 2)
            + 38.0 * (candidate["elbow"] ** 2)
            + 8.0 * (candidate["base"] ** 2)
            + 0.8 * (candidate["wrist_pitch"] ** 2)
        )
        wrist_usage_bonus = 8.0 * abs(candidate["wrist_pitch"]) + 2.0 * abs(candidate["wrist_roll"])
        neutral_penalty = 18.0 if abs(candidate["wrist_pitch"]) < 0.36 else 0.0
        score = (error * 180.0) ** 2 + stiffness_cost - wrist_usage_bonus + neutral_penalty
        return {"angles": candidate, "pose": pose, "tip_error": error, "score": score}

    def optimize(seed):
        best = evaluate(seed)
        if best is None:
            return None
        step_plan = {
            "base": [0.35, 0.18, 0.08, 0.04],
            "shoulder": [0.5, 0.25, 0.12, 0.06],
            "elbow": [0.6, 0.3, 0.14, 0.07],
            "wrist_pitch": [0.8, 0.4, 0.2, 0.1],
        }
        for _ in range(4):
            improved = False
            for joint_name in ("base", "shoulder", "elbow", "wrist_pitch"):
                for step in step_plan[joint_name]:
                    for direction in (-1.0, 1.0):
                        trial_angles = dict(best["angles"])
                        trial_angles[joint_name] += direction * step
                        trial = evaluate(make_candidate(
                            trial_angles["base"],
                            trial_angles["shoulder"],
                            trial_angles["elbow"],
                            trial_angles["wrist_pitch"],
                        ))
                        if trial and trial["score"] + 1e-9 < best["score"]:
                            best = trial
                            improved = True
            coupled_steps = [
                ("shoulder", -1.0, "wrist_pitch", 1.0),
                ("shoulder", 1.0, "wrist_pitch", -1.0),
                ("elbow", -1.0, "wrist_pitch", 1.0),
                ("elbow", 1.0, "wrist_pitch", -1.0),
                ("shoulder", -1.0, "elbow", -1.0),
                ("shoulder", 1.0, "elbow", 1.0),
            ]
            for joint_a, sign_a, joint_b, sign_b in coupled_steps:
                for step_a in step_plan[joint_a]:
                    for step_b in step_plan[joint_b]:
                        trial_angles = dict(best["angles"])
                        trial_angles[joint_a] += sign_a * step_a
                        trial_angles[joint_b] += sign_b * step_b
                        trial = evaluate(make_candidate(
                            trial_angles["base"],
                            trial_angles["shoulder"],
                            trial_angles["elbow"],
                            trial_angles["wrist_pitch"],
                        ))
                        if trial and trial["score"] + 1e-9 < best["score"]:
                            best = trial
                            improved = True
            if not improved:
                break
        return best

    seed_states = []
    current = ik_current_angles(arm_name)
    seed_states.append(make_candidate(current["base"], current["shoulder"], current["elbow"], current["wrist_pitch"]))
    for elbow_angle in elbow_candidates:
        shoulder_angle = math.atan2(plane_y, plane_x) - math.atan2(fore_len * math.sin(elbow_angle), upper_len + fore_len * math.cos(elbow_angle))
        for wrist_pitch in (0.0, -0.45, 0.45, -0.9, 0.9, -1.2, 1.2):
            seed_states.append(make_candidate(base_angle, shoulder_angle, elbow_angle, wrist_pitch))
            for shoulder_scale, elbow_scale in ((0.9, 0.8), (0.82, 0.7), (0.7, 0.55), (0.55, 0.42)):
                scaled_shoulder = shoulder_angle * shoulder_scale
                scaled_elbow = elbow_angle * elbow_scale
                seed_states.append(make_candidate(base_angle, scaled_shoulder, scaled_elbow, wrist_pitch))
                seed_states.append(make_candidate(base_angle, scaled_shoulder, scaled_elbow, -(scaled_shoulder + scaled_elbow) * 0.8))
                seed_states.append(make_candidate(base_angle, scaled_shoulder, scaled_elbow, -(scaled_shoulder + scaled_elbow)))

    best = None
    for seed in seed_states:
        result = optimize(seed)
        if result is None:
            continue
        if best is None or result["score"] < best["score"]:
            best = result

    if best is None or best["tip_error"] > 12.0:
        return {
            "ok": False,
            "arm": arm_name,
            "reason": "joint_limits",
            "target_mm": {axis: round(target[axis], 3) for axis in ("x", "y", "z")},
            "requested_wrist_roll_deg": requested_wrist_roll_deg,
            "notes": list(IK_SOLVER_NOTES),
        }

    angles = best["angles"]
    pose = best["pose"]
    target_pwms = {
        ik_joint_config(arm_name, joint_name)["channel"]: ik_pwm_from_angle(arm_name, joint_name, angle)
        for joint_name, angle in angles.items()
    }
    return {
        "ok": True,
        "arm": arm_name,
        "angles_rad": {joint: round(value, 6) for joint, value in angles.items()},
        "angles_deg": {joint: round(math.degrees(value), 3) for joint, value in angles.items()},
        "target_mm": {axis: round(target[axis], 3) for axis in ("x", "y", "z")},
        "requested_wrist_roll_deg": requested_wrist_roll_deg,
        "tip_mm": {axis: round(pose["tip"][axis], 3) for axis in ("x", "y", "z")},
        "target_pwms": target_pwms,
        "tip_error_mm": round(best["tip_error"], 3),
        "optimization_score": round(best["score"], 3),
        "plane_side_error_mm": round(plane_side_error, 3),
        "notes": list(IK_SOLVER_NOTES),
    }


def controller_status_payload():
    with lock:
        axes = dict(controller_state["axes"])
        buttons = dict(controller_state["buttons"])
        payload = {
            "enabled": controller_state["enabled"],
            "connected": controller_state["connected"],
            "active": controller_state["active"],
            "deadman": controller_state["deadman"],
            "device": controller_state["device"],
            "last_error": controller_state["last_error"],
            "updated_at": controller_state["updated_at"],
        }
    payload["axes"] = axes
    payload["buttons"] = buttons
    payload["bindings"] = CONTROLLER_LABELS
    payload["selected_arm"] = controller_state["selected_arm"]
    return payload


def reset_controller_motion():
    for name in controller_channel_velocity:
        controller_channel_velocity[name] = 0.0


def set_controller_arm(selected_arm):
    with lock:
        controller_state["selected_arm"] = "right" if selected_arm == "right" else "left"
    reset_controller_motion()


def set_controller_enabled(enabled):
    with lock:
        controller_state["enabled"] = bool(enabled)
        controller_state["active"] = False
        controller_state["deadman"] = False
        controller_state["last_error"] = None
        for name in controller_state["axes"]:
            controller_state["axes"][name] = 0.0
    reset_controller_motion()


def controller_apply_outputs():
    with lock:
        enabled = controller_state["enabled"]
        buttons = dict(controller_state["buttons"])
        max_speed = int(SERVO_SETTINGS["speed"])
        accel = int(SERVO_SETTINGS["ramp"])
        selected_arm = controller_state["selected_arm"]
    if not enabled:
        reset_controller_motion()
        with lock:
            controller_state["active"] = False
            controller_state["deadman"] = False
        return

    deadman = any(buttons.get(btn, 0) for btn in DEADMAN_BUTTONS)
    active = False
    changed = False

    if not deadman:
        reset_controller_motion()
    else:
        arm_bindings = CONTROLLER_ARM_BINDINGS[selected_arm]
        for axis_name, bindings in arm_bindings.items():
            axis_value = controller_axis_value(axis_name)
            if abs(axis_value) >= CONTROLLER_ACTIVE_THRESHOLD:
                active = True
            for binding in bindings:
                channel = binding["channel"]
                current = int(servo_positions.get(channel, servo_neutral.get(channel, 1000)))
                lo, hi = controller_limits(channel)
                velocity = controller_channel_velocity.get(channel, 0.0)
                target_velocity = axis_value * binding["scale"] * max_speed
                if target_velocity > velocity:
                    velocity = min(velocity + accel, target_velocity)
                elif target_velocity < velocity:
                    velocity = max(velocity - accel, target_velocity)
                if abs(target_velocity) < 0.001 and abs(velocity) < accel:
                    velocity = 0.0
                controller_channel_velocity[channel] = velocity
                if abs(velocity) < 0.5:
                    continue
                step = int(round(velocity))
                if step == 0:
                    step = 1 if velocity > 0 else -1
                target = clamp(current + step, lo, hi)
                if target == current:
                    controller_channel_velocity[channel] = 0.0
                    continue
                if send_pwm(channel, target):
                    servo_positions[channel] = target
                    mark_positions_dirty()
                    changed = True

    with lock:
        controller_state["deadman"] = deadman
        controller_state["active"] = deadman and (active or changed)


def controller_loop():
    fd = None

    def close_device():
        nonlocal fd
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass
            fd = None
        with lock:
            controller_state["connected"] = False
            controller_state["device"] = None
            controller_state["active"] = False
            controller_state["deadman"] = False
            for name in controller_state["axes"]:
                controller_state["axes"][name] = 0.0
        reset_controller_motion()

    while True:
        with lock:
            enabled = controller_state["enabled"]
        if not enabled:
            close_device()
            time.sleep(0.25)
            continue

        if fd is None:
            try:
                fd = os.open('/dev/input/js0', os.O_RDONLY | os.O_NONBLOCK)
                with lock:
                    controller_state["connected"] = True
                    controller_state["device"] = '/dev/input/js0'
                    controller_state["last_error"] = None
                    controller_state["updated_at"] = time.time()
            except OSError as e:
                with lock:
                    controller_state["connected"] = False
                    controller_state["device"] = None
                    controller_state["last_error"] = str(e)
                time.sleep(CONTROLLER_SCAN_INTERVAL)
                continue

        try:
            ready, _, _ = select.select([fd], [], [], 1.0 / CONTROLLER_HZ)
            if ready:
                while True:
                    try:
                        event = os.read(fd, 8)
                    except BlockingIOError:
                        break
                    if len(event) != 8:
                        raise OSError('controller disconnected')
                    _, value, event_type, number = struct.unpack('IhBB', event)
                    if event_type & JS_EVENT_INIT:
                        continue
                    base_type = event_type & ~JS_EVENT_INIT
                    with lock:
                        controller_state["updated_at"] = time.time()
                        if base_type == JS_EVENT_AXIS and number in CONTROLLER_AXIS_ORDER:
                            controller_state["axes"][CONTROLLER_AXIS_ORDER[number]] = max(-1.0, min(1.0, value / 32767.0))
                        elif base_type == JS_EVENT_BUTTON:
                            controller_state["buttons"][number] = 1 if value else 0
            controller_apply_outputs()
        except OSError as e:
            with lock:
                controller_state["last_error"] = str(e)
            close_device()
            time.sleep(CONTROLLER_SCAN_INTERVAL)


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



@app.route('/')
def index():
    return render_template('index.html')


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


@app.route('/api/servo_settings')
def get_servo_settings():
    return jsonify(SERVO_SETTINGS)


@app.route('/api/servo_settings', methods=['POST'])
def set_servo_settings():
    data = request.json or {}
    with lock:
        if "speed" in data:
            SERVO_SETTINGS["speed"] = clamp(int(data["speed"]), 1, 200)
        if "ramp" in data:
            SERVO_SETTINGS["ramp"] = clamp(int(data["ramp"]), 1, 100)
        settings = dict(SERVO_SETTINGS)
    return jsonify(settings)


@app.route('/api/controller/status')
def controller_status():
    return jsonify(controller_status_payload())


@app.route('/api/controller/enable', methods=['POST'])
def controller_enable():
    data = request.json or {}
    enabled = bool(data.get('enabled', False))
    set_controller_enabled(enabled)
    return jsonify(controller_status_payload())


@app.route('/api/controller/arm', methods=['POST'])
def controller_select_arm():
    data = request.json or {}
    set_controller_arm(data.get('selected_arm', "left"))
    return jsonify(controller_status_payload())


@app.route('/api/ik/status')
def ik_status():
    return jsonify(ik_status_payload())


@app.route('/api/ik/solve', methods=['POST'])
def ik_solve():
    data = request.json or {}
    with lock:
        selected_arm = controller_state["selected_arm"]
    arm_name = ik_arm_name(data.get("arm", selected_arm))
    target_xyz = {
        "x": float(data.get("x", 0.0)),
        "y": float(data.get("y", 0.0)),
        "z": float(data.get("z", 0.0)),
    }
    wrist_roll_deg = data.get("wrist_roll_deg")
    result = ik_solve_arm(arm_name, target_xyz, wrist_roll_deg)
    apply_move = bool(data.get("apply", False))
    if result.get("ok") and apply_move:
        applied = {}
        ok = True
        for channel, target in result["target_pwms"].items():
            sent = send_pwm(channel, target)
            applied[channel] = sent
            if sent:
                servo_positions[channel] = target
            ok = ok and sent
        if ok:
            mark_positions_dirty()
        result["applied"] = applied
        result["ok"] = ok
        if not ok:
            result["reason"] = "send_failed"
    result["selected_arm"] = arm_name
    with lock:
        ik_state["last_solution"] = result
    return jsonify(result)


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
    threading.Thread(target=controller_loop, daemon=True).start()
    threading.Thread(target=ramp_loop, daemon=True).start()
    threading.Thread(target=watchdog_loop, daemon=True).start()
    threading.Thread(target=positions_flush_loop, daemon=True).start()
    if RESTORE_ON_START:
        threading.Thread(target=restore_positions_loop, daemon=True).start()
    app.run(host='0.0.0.0', port=DEFAULT_PORT, threaded=True)
