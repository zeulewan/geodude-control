from flask import Flask, render_template, jsonify, request
import threading
import time
import json
import os
import urllib.error
import urllib.request

app = Flask(__name__)
APP_DIR = os.path.dirname(os.path.abspath(__file__))
GROUNDSTATION_DIR = APP_DIR

GEODUDE_URL = "http://192.168.4.166:5000"
GIMBAL_URL = "http://192.168.4.222"

# PCA9685 channel mapping (pin - 1 = 0-indexed)
CHANNELS = {
    "B1":   0,   # SV1
    "S1":   1,   # SV2
    "B2":   2,   # SV3
    "S2":   3,   # SV4
    "E1":   4,   # SV5
    "E2":   5,   # SV6
    "W1A":  6,   # SV7
    "W1B":  7,   # SV8
    "W2A":  8,   # SV9
    "W2B":  9,   # SV10
}


state = {
    "gyro": {"x": 0, "y": 0, "z": 0},
    "accel": {"x": 0, "y": 0, "z": 0},
    "encoder_angle": 0,
    "connected": False,
    "rpm": 0,
    "analog_encoder": {
        "va": 0,
        "vb": 0,
        "electrical_deg": 0,
        "mechanical_deg": 0,
    },
    "i2c": {"ok": False, "ads_ok": False, "imu_ok": False},
}

MACE_JOG_MAX_RPM = 500.0
MACE_JOG_MAX_RAD_S = MACE_JOG_MAX_RPM * 2.0 * 3.141592653589793 / 60.0
MACE_JOG_MIN_VOLTAGE = 0.5
MACE_JOG_MAX_VOLTAGE = 24.0
MACE_JOG_MIN_RAMP = 0.1
MACE_JOG_MAX_RAMP = 2000.0  # ~30ms to full target = effectively a step

# Authoritative jog state lives on GEO-DUDe. This dict only caches the last
# error surfaced to the UI. No watchdog here — GEO-DUDe owns the failsafe
# (coast via D on heartbeat timeout).
mace_jog_lock = threading.Lock()
mace_jog_state = {
    "status": "idle",
    "error": None,
    "last_command_at": 0.0,
}

# Server-side servo position tracking — persisted to disk, survives reboots
POSITIONS_FILE = os.path.join(GROUNDSTATION_DIR, "servo_positions.json")

def load_positions():
    try:
        with open(POSITIONS_FILE) as f:
            return json.load(f)
    except Exception:
        return {}

def save_positions():
    """Persist servo positions atomically (tmp-file + fsync + rename)."""
    try:
        tmp = f"{POSITIONS_FILE}.{os.getpid()}.tmp"
        # H5: snapshot under the state lock so we don't iterate a mutating dict.
        with _servo_positions_lock:
            snapshot = dict(servo_positions)
        with open(tmp, "w") as f:
            json.dump(snapshot, f)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, POSITIONS_FILE)
    except Exception as e:
        print(f"servo_positions save failed: {e}", flush=True)

servo_positions = load_positions()
_servo_positions_lock = threading.Lock()
_positions_dirty = False
_positions_last_change = 0.0

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
NEUTRAL_FILE = os.path.join(GROUNDSTATION_DIR, "servo_neutral.json")

def load_neutral():
    try:
        with open(NEUTRAL_FILE) as f:
            return json.load(f)
    except Exception:
        return {}

def save_neutral(data):
    # Atomic write: power loss during a direct `open("w")` could truncate
    # servo_neutral.json, and the boot guard then refuses to start the
    # service. Write to a temp file and os.replace(). Matches the pattern
    # save_positions() already uses.
    tmp = f"{NEUTRAL_FILE}.{os.getpid()}.tmp"
    with open(tmp, "w") as f:
        json.dump(data, f)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, NEUTRAL_FILE)

servo_neutral = load_neutral()
if os.path.exists(NEUTRAL_FILE) and not servo_neutral:
    # L-D: file exists but parsed to empty; fail fast rather than silently
    # default every servo to 1500us (which the docs flag as DANGEROUS).
    raise RuntimeError(
        f"{NEUTRAL_FILE} exists but is empty/corrupt. Refuse to start with"
        " default 1500us neutrals -- operator must fix the file."
    )

# --- L6: Per-channel servo PW envelope (mechanical safety) ---
#
# Commands outside a channel's envelope are clamped before the ramp, so a
# buggy UI/typo can't drive a servo into a mechanical stop.
#
# Defaults are the full 500..2500 us pulse window -- no assumption about
# where the joint's real mechanical limits are. To tighten per joint (once
# you've measured real stops), drop a groundstation/servo_limits.json with
# e.g. {"B1": {"min": 1000, "max": 2000}, ...}.
#
# Previously defaults were neutral +/- 600 us, which silently chopped half
# of travel whenever a neutral was a joint-extended position rather than a
# mechanical center. Slew-rate safety (SERVO_MAX_DELTA_US) already handles
# bad single commands; mechanical-stop safety needs measured limits, not
# guessed ones.

LIMITS_FILE = os.path.join(GROUNDSTATION_DIR, "servo_limits.json")


def _default_servo_limits():
    return {name: {"min": 500, "max": 2500} for name in CHANNELS}


def _load_servo_limits():
    defaults = _default_servo_limits()
    try:
        with open(LIMITS_FILE) as f:
            user_limits = json.load(f)
        for name, bounds in (user_limits or {}).items():
            if name not in defaults:
                continue
            lo = int(bounds.get("min", defaults[name]["min"]))
            hi = int(bounds.get("max", defaults[name]["max"]))
            lo = max(500, min(lo, 2500))
            hi = max(500, min(hi, 2500))
            if lo <= hi:
                defaults[name] = {"min": lo, "max": hi}
    except FileNotFoundError:
        pass
    except Exception as e:
        print(f"[servo] servo_limits.json parse failed, using defaults: {e}", flush=True)
    return defaults


servo_limits = _load_servo_limits()


# --- Joint calibration (PW <-> angle mapping) ---
#
# Per-channel linear calibration:
#   angle_rad = neutral_angle_rad + (pw - neutral_pw) / us_per_rad * sign
#
# neutral_pw lives in servo_neutral.json (rest pose). This file is the
# separate concern of "what does PW mean physically":
#   - us_per_rad: slope. 270deg servos over 500..2500us default to ~424.
#   - sign: +1 or -1. Decided during 2-point calibration.
#   - neutral_angle_rad: angle of the joint when PW = neutral_pw.
#       Base / wrists: 0 (neutral is angle zero).
#       Shoulder / Elbow: pi/2 (neutral is folded 90deg off the
#         "fully extended" zero reference).
#   - min_angle_rad / max_angle_rad: null = no clamp; set after measuring
#     mechanical stops.
#
# Stored in groundstation/joint_calibration.json. Missing file = defaults.
# Atomic writes. Bad file = log + fall back to defaults, never crash.
import math
JOINT_CAL_FILE = os.path.join(GROUNDSTATION_DIR, "joint_calibration.json")
JOINT_CAL_FIELDS = ("us_per_rad", "sign", "neutral_angle_rad", "min_angle_rad", "max_angle_rad")


def _default_joint_calibration():
    """270deg servo over 500..2500us => 2000us / (3*pi/2) = ~424 us/rad.
    Conventions per user:
      - Base (B*) / Wrists (W*): neutral_angle_rad = 0
      - Shoulder (S*) / Elbow (E*): neutral_angle_rad = pi/2
    Signs default to +1; will flip during calibration if needed.
    """
    cal = {}
    for name in CHANNELS:
        if name.startswith("S") or name.startswith("E"):
            nrad = math.pi / 2
        else:
            nrad = 0.0
        cal[name] = {
            "us_per_rad": 424.0,
            "sign": 1,
            "neutral_angle_rad": nrad,
            "min_angle_rad": None,
            "max_angle_rad": None,
        }
    return cal


def _sanitize_joint_cal_entry(raw, fallback):
    """Merge a user-supplied entry onto a default, with type/range guards.
    Invalid fields fall back silently to the default rather than crashing."""
    out = dict(fallback)
    if not isinstance(raw, dict):
        return out
    try:
        if "us_per_rad" in raw:
            v = float(raw["us_per_rad"])
            if 1.0 <= v <= 100000.0:
                out["us_per_rad"] = v
        if "sign" in raw:
            s = int(raw["sign"])
            if s in (-1, 1):
                out["sign"] = s
        if "neutral_angle_rad" in raw:
            v = float(raw["neutral_angle_rad"])
            if -10.0 <= v <= 10.0:
                out["neutral_angle_rad"] = v
        for k in ("min_angle_rad", "max_angle_rad"):
            if k in raw:
                v = raw[k]
                if v is None:
                    out[k] = None
                else:
                    v = float(v)
                    if -10.0 <= v <= 10.0:
                        out[k] = v
    except (TypeError, ValueError):
        pass
    return out


def load_joint_calibration():
    defaults = _default_joint_calibration()
    try:
        with open(JOINT_CAL_FILE) as f:
            user = json.load(f)
    except FileNotFoundError:
        return defaults
    except Exception as e:
        print(f"[cal] joint_calibration.json parse failed, using defaults: {e}", flush=True)
        return defaults
    out = {}
    for name in CHANNELS:
        out[name] = _sanitize_joint_cal_entry(
            (user or {}).get(name), defaults[name]
        )
    return out


def save_joint_calibration(data):
    # Atomic: temp + fsync + os.replace. Matches save_neutral/save_positions.
    tmp = f"{JOINT_CAL_FILE}.{os.getpid()}.tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2, sort_keys=True)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, JOINT_CAL_FILE)


joint_calibration = load_joint_calibration()
_joint_cal_lock = threading.Lock()


def _pw_to_angle_rad(name, pw):
    """Convert PW to joint angle. Returns None if the channel is unknown
    or calibration is degenerate."""
    cal = joint_calibration.get(name)
    neutral_pw = servo_neutral.get(name)
    if not cal or neutral_pw is None:
        return None
    us_per_rad = cal.get("us_per_rad")
    if not us_per_rad or us_per_rad <= 0:
        return None
    return cal["neutral_angle_rad"] + (pw - neutral_pw) / us_per_rad * cal["sign"]


def _clamp_to_envelope(name, pw):
    """Clamp a requested pw to the channel's envelope. pw=0 (off) passes through."""
    if pw == 0:
        return 0
    lim = servo_limits.get(name)
    if not lim:
        return pw
    return max(lim["min"], min(lim["max"], pw))



lock = threading.Lock()


# L-B: legacy send_pwm removed. All servo traffic must go through the
# server-side ramp and /api/pwm (which calls _servo_set_target).


def _mace_clamp_voltage(value):
    return max(MACE_JOG_MIN_VOLTAGE, min(float(value), MACE_JOG_MAX_VOLTAGE))


def _mace_clamp_ramp(value):
    return max(MACE_JOG_MIN_RAMP, min(float(value), MACE_JOG_MAX_RAMP))


def _mace_post_simplefoc(payload):
    body = json.dumps(payload).encode()
    req = urllib.request.Request(
        f"{GEODUDE_URL}/simplefoc",
        data=body,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=2.0) as resp:
        data = json.loads(resp.read().decode())
        if not data.get("ok"):
            raise RuntimeError(data.get("error", "simplefoc command failed"))
        return data


def _mace_post_jog(path, payload=None):
    body = json.dumps(payload or {}).encode()
    req = urllib.request.Request(
        f"{GEODUDE_URL}{path}",
        data=body,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=2.0) as resp:
        data = json.loads(resp.read().decode())
        if not data.get("ok"):
            raise RuntimeError(data.get("error", "MACE jog command failed"))
        return data


def _mace_fetch_status():
    with urllib.request.urlopen(f"{GEODUDE_URL}/simplefoc/jog/status", timeout=2.0) as resp:
        return json.loads(resp.read().decode())


def _mace_fetch_calibrate_state():
    with urllib.request.urlopen(f"{GEODUDE_URL}/simplefoc/calibrate/state", timeout=2.0) as resp:
        return json.loads(resp.read().decode())


def _mace_start_calibration():
    # Dedicated calibrate route — decoupled from the profile/tuning state
    # machine so jog/start is no longer blocked by tuning busy flags.
    return _mace_post_jog("/simplefoc/calibrate")


def _mace_disable():
    return _mace_post_jog("/simplefoc/jog/stop")


def _mace_snapshot():
    with mace_jog_lock:
        snap = dict(mace_jog_state)
    with lock:
        snap["body_rpm"] = state.get("rpm", 0)
    try:
        sfoc = _mace_fetch_status()
    except Exception as exc:
        snap["connected"] = False
        snap["simplefoc_error"] = str(exc)
        return snap
    snap["connected"] = bool(sfoc.get("connected"))
    snap["simplefoc_target"] = sfoc.get("target")
    snap["wheel_rpm"] = sfoc.get("wheel_rpm")
    snap["simplefoc_live"] = bool(sfoc.get("live"))
    snap["foc_ready"] = bool(sfoc.get("foc_ready"))
    for key in ("active", "status", "error", "max_voltage", "accel_ramp", "brake_ramp"):
        if key in sfoc:
            snap[key] = sfoc.get(key)
    # Only fetch calibrate state when we actually care (UI shows CALIBRATING).
    # Cheap enough to always include; single extra HTTP hop. Fold into the
    # same request-side try so a geodude blip doesn't kill the snapshot.
    try:
        cal = _mace_fetch_calibrate_state()
    except Exception as exc:
        cal = {"busy": False, "status": "error", "error": str(exc)}
    snap["calibrating"] = bool(cal.get("busy"))
    snap["calibration_status"] = cal.get("status")
    snap["calibration_error"] = cal.get("error")
    return snap


def send_all_off():
    """Emergency disable of every PCA channel.

    Returns (ok_all, failures) where failures is a list of channel names
    that did NOT confirm zero. The disarm flag is only raised if every
    channel was successfully stopped; a partial failure leaves the system
    in its previous armed state and the operator is expected to deal with
    it (power-cycle the PCA rail).
    """
    global _servo_disarmed
    failures = []
    for name in CHANNELS:
        ok, _ = _servo_send_to_geodude(name, 0, bypass_clamp=True)
        if not ok:
            failures.append(name)
    with _servo_state_lock:
        if not failures:
            for name in CHANNELS:
                _servo_target_pw[name] = 0
                _servo_actual_pw[name] = 0
            _servo_disarmed = True
    return (len(failures) == 0, failures)


# --- Servo safety state ---
SERVO_RAMP_HZ = 30
SERVO_MAX_SEQ = 2**53  # L5: JS-safe integer max; unreachable at 30 Hz
SERVO_MAX_STEP_US_PER_TICK = 10
SERVO_HEARTBEAT_TIMEOUT_S = 3.0  # Was 1.0: razor-thin vs the client's 1Hz
# heartbeat interval -- a single late heartbeat froze the ramp mid-move, so
# a multi-second ALL NEUTRAL / setpoint Go arrived partially and needed
# repeated clicks. 3s gives 3x margin while still failing servos safe
# within a few seconds if the browser dies.

_servo_target_pw = {}
_servo_actual_pw = {}
_servo_seq = {}
_servo_speed_per_tick = SERVO_MAX_STEP_US_PER_TICK
_servo_last_heartbeat = 0.0
_servo_ramp_last_tick_mono = 0.0
_servo_disarmed = False  # H2: reject /api/pwm after emergency stop
# True once _servo_bootstrap_loop has confirmed every channel is either
# live on GEO-DUDe or freshly seeded. Until then, in-memory targets may
# have come from fallback paths and should not be captured as setpoints.
_servo_bootstrap_complete = False
_servo_state_lock = threading.Lock()
_servo_seq_locks = {name: threading.Lock() for name in CHANNELS}  # C1/N1: per-channel seq locks, built at import


def _servo_init_state():
    """Seed ramp state from last-known positions on disk. Must be called
    before the ramp thread starts. Actual==Target so nothing moves."""
    global _servo_last_heartbeat
    for name in CHANNELS:
        pw = servo_positions.get(name, servo_neutral.get(name, 1500))
        _servo_actual_pw[name] = pw
        _servo_target_pw[name] = pw
        _servo_seq[name] = 0
    _servo_last_heartbeat = time.monotonic()


def _servo_send_to_geodude(name, pw, bypass_clamp=False):
    """Send one PWM to GEO-DUDe with the next seq number for this channel.

    Returns (ok, accepted_pw). Seq read/modify/write is serialized per
    channel via _servo_seq_locks[name] so concurrent callers (ramp thread,
    send_all_off, or a future path) cannot mint duplicate seqs and
    mutually lock each other out of GEO-DUDe.
    """
    with _servo_seq_locks[name]:
        seq = _servo_seq[name] + 1
        if seq > SERVO_MAX_SEQ:
            print(f"[servo] {name} seq overflow; refusing to send", flush=True)
            return False, None
        payload = {"channel": name, "pw": pw, "seq": seq}
        if bypass_clamp:
            payload["bypass_clamp"] = True
        try:
            body = json.dumps(payload).encode()
            req = urllib.request.Request(
                f"{GEODUDE_URL}/pwm",
                data=body,
                headers={"Content-Type": "application/json"},
            )
            resp = urllib.request.urlopen(req, timeout=1.0)
            result = json.loads(resp.read().decode()) if resp.status == 200 else None
            if result and result.get("ok"):
                _servo_seq[name] = seq
                return True, int(result.get("pw", pw))
        except urllib.error.HTTPError as e:
            if e.code == 409:
                try:
                    err = json.loads(e.read().decode())
                    server_last = int(err.get("last_seq", -1))
                    if server_last > _servo_seq[name]:
                        _servo_seq[name] = server_last
                        print(f"[servo] {name} seq resync to {server_last}", flush=True)
                except Exception:
                    pass
        except Exception:
            pass
        return False, None


def _servo_ramp_loop():
    """Authoritative ramp at SERVO_RAMP_HZ.

    Safety properties:
      - Body is wrapped in try/except so one exception cannot silently kill
        the thread (C5).
      - _servo_actual_pw is only advanced AFTER a successful PWM was
        accepted by GEO-DUDe, so on failure we do NOT drift away from
        reality (C2). Next tick retries the same step.
      - _servo_ramp_last_tick_mono is updated every tick so the UI can
        detect a hung ramp.
      - Heartbeat watchdog freezes targets to current actual if the
        client has gone silent for SERVO_HEARTBEAT_TIMEOUT_S.
    """
    global _servo_ramp_last_tick_mono
    period = 1.0 / SERVO_RAMP_HZ
    while True:
        start = time.monotonic()
        try:
            _servo_ramp_last_tick_mono = start
            with _servo_state_lock:
                # L1: if disarmed, skip this tick entirely. send_all_off
                # already zeroed target/actual; belt and suspenders.
                if _servo_disarmed:
                    elapsed = time.monotonic() - start
                    if elapsed < period:
                        time.sleep(period - elapsed)
                    continue
                # Heartbeat watchdog.
                if start - _servo_last_heartbeat > SERVO_HEARTBEAT_TIMEOUT_S:
                    for name in CHANNELS:
                        # H-B: clamp to envelope so we never freeze to an
                        # out-of-envelope value (if actual drifted or limits
                        # were narrowed post-startup).
                        frozen = _servo_actual_pw[name]
                        if frozen != 0:
                            frozen = _clamp_to_envelope(name, frozen)
                        _servo_target_pw[name] = frozen
                        _servo_actual_pw[name] = frozen

                # H1: read step cap under the lock.
                step_cap = max(1, min(_servo_speed_per_tick, SERVO_MAX_STEP_US_PER_TICK))

                moves = []
                for name in CHANNELS:
                    target = _servo_target_pw[name]
                    actual = _servo_actual_pw[name]
                    if target == actual:
                        continue
                    delta = target - actual
                    step = step_cap if delta > 0 else -step_cap
                    if abs(delta) < step_cap:
                        step = delta
                    new_actual = actual + step
                    # DO NOT advance _servo_actual_pw yet. Wait for success.
                    moves.append((name, actual, new_actual))

            # Send outside the state lock (slow HTTP must not block targets).
            for name, prev_actual, new_actual in moves:
                ok, accepted_pw = _servo_send_to_geodude(name, new_actual)
                if not ok:
                    # _servo_actual_pw stays at prev_actual; retry next tick.
                    continue
                # Sanity-check GEO-DUDes echo. Three ways it can be bad:
                #   1. Outside [0..2500] range                -> reject, alarm.
                #   2. Further from prev_actual than we asked -> reject (this
                #      is the C-A case: the remote cannot legitimately push
                #      the servo past where we requested).
                #   3. Outside our per-channel envelope       -> reject. We
                #      do NOT silently clamp into the envelope because that
                #      would make groundstations belief diverge from the
                #      physical servo state (H1). Instead: alarm and stall.
                bad = False
                reason = ""
                ap = int(accepted_pw)
                if ap < 0 or ap > 2500:
                    bad = True; reason = f"out of range [{ap}]"
                elif abs(ap - prev_actual) > abs(new_actual - prev_actual) + 1:
                    bad = True; reason = f"echo={ap} > requested={new_actual}"
                elif ap != 0:
                    lim = servo_limits.get(name)
                    if lim:
                        # Allow echoes below envelope.min while we are ramping
                        # up from below (post-disarm or first startup), and allow
                        # echoes above envelope.max while ramping down from above
                        # (envelope narrowed mid-motion). In both cases the
                        # 50us/tick hardware clamp bounds travel speed, so the
                        # groundstation-side envelope check is redundant until
                        # we re-enter the envelope.
                        lo, hi = lim["min"], lim["max"]
                        was_below = prev_actual < lo
                        was_above = prev_actual > hi
                        if ap < lo and not was_below:
                            bad = True; reason = f"echo={ap} below envelope min={lo}"
                        elif ap > hi and not was_above:
                            bad = True; reason = f"echo={ap} above envelope max={hi}"
                if bad:
                    print(f"[servo] {name} remote echo looks wrong: {reason}; holding actual at {prev_actual}", flush=True)
                    # Do not advance _servo_actual_pw. Next tick retries the
                    # same step honestly and GEO-DUDes 50us clamp is still
                    # the physical safety net.
                    continue
                with _servo_state_lock:
                    _servo_actual_pw[name] = ap
                with _servo_positions_lock:
                    servo_positions[name] = ap
                mark_positions_dirty()
        except Exception as e:
            print(f"[servo ramp] exception: {e!r}", flush=True)

        # ~2 Hz refresh of GEO-DUDe hardware-pw snapshot for the UI.
        if start - _servo_hardware_last_fetch > 0.5:
            try:
                _refresh_hardware_pw()
            except Exception as e:
                print(f"[servo ramp] hw pw refresh failed: {e!r}", flush=True)

        elapsed = time.monotonic() - start
        if elapsed < period:
            time.sleep(period - elapsed)


# _servo_set_target inlined into /api/pwm in v6; function removed.


def _servo_heartbeat():
    global _servo_last_heartbeat
    # C-B: take the state lock so the ramp thread cannot tear-read this.
    with _servo_state_lock:
        _servo_last_heartbeat = time.monotonic()


def _servo_snapshot():
    now = time.monotonic()
    with _servo_hardware_pw_lock:
        hw = dict(_servo_hardware_pw)
    with _servo_state_lock:
        return {
            "target": dict(_servo_target_pw),
            "actual": dict(_servo_actual_pw),
            "hardware": hw,
            "speed_per_tick": _servo_speed_per_tick,
            "heartbeat_age_s": now - _servo_last_heartbeat,
            "ramp_age_s": now - _servo_ramp_last_tick_mono,
            "seq": dict(_servo_seq),
            "disarmed": _servo_disarmed,
        }




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
                state["analog_encoder"] = {
                    "va": data.get("analog_va", 0),
                    "vb": data.get("analog_vb", 0),
                    "electrical_deg": data.get("analog_electrical_deg", 0),
                    "mechanical_deg": data.get("analog_mechanical_deg", data.get("angle", 0)),
                }
                state["i2c"] = {
                    "ok": data.get("i2c_ok", False),
                    "ads_ok": data.get("ads_ok", False),
                    "imu_ok": data.get("imu_ok", False),
                }
                state["connected"] = True
        except Exception:
            with lock:
                state["connected"] = False

        time.sleep(0.1)


@app.route('/')
def index():
    def static_rev(name):
        try:
            return int(os.path.getmtime(os.path.join(app.static_folder, name)))
        except OSError:
            return 0
    return render_template(
        'index.html',
        style_rev=static_rev('style.css'),
        app_rev=static_rev('app.js'),
    )


@app.route('/api/sensors')
def sensors():
    with lock:
        return jsonify(state)


@app.route('/api/pwm', methods=['POST'])
def pwm():
    """Set a servo TARGET. The background ramp thread moves toward it
    safely, step-capped, sequence-numbered, and heartbeat-gated.

    Body: {"channel": "B1", "pw": 1500}

    Rejected with 409 while the arms are disarmed (after /api/all_off).
    Operator must POST /api/arm to resume.
    """
    data = request.json or {}
    name = data.get("channel", "")
    pw = int(data.get("pw", 0))
    if name not in CHANNELS:
        return jsonify({"ok": False, "error": "unknown channel"}), 400
    # M1: set target and heartbeat in a single critical section so the
    # ramp thread cannot tick between them and freeze the just-posted
    # target based on a stale heartbeat.
    global _servo_last_heartbeat
    pw = max(0, min(2500, int(pw)))
    pw = _clamp_to_envelope(name, pw)
    with _servo_state_lock:
        if _servo_disarmed:
            return jsonify({"ok": False, "error": "disarmed; POST /api/arm first"}), 409
        _servo_target_pw[name] = pw
        _servo_last_heartbeat = time.monotonic()
    return jsonify({"ok": True})


@app.route('/api/servo_state')
def servo_state():
    """Live ramp state for the UI (target, actual, speed, heartbeat age)."""
    return jsonify(_servo_snapshot())


# --- Setpoints: named snapshots of all 10 servo targets ---
#
# Stored in groundstation/servo_setpoints.json as an ordered list.
# Each entry: {id, name, positions:{B1..W2B}, created_at}.
# Saving captures the current _servo_target_pw (what the ramp is
# aiming for). Clicking a setpoint writes those back into
# _servo_target_pw so the existing ramp loop drives the move gently,
# respects envelope limits, disarm state, and per-channel seq.
SETPOINTS_FILE = os.path.join(GROUNDSTATION_DIR, "servo_setpoints.json")
_setpoints_lock = threading.Lock()


def load_setpoints():
    try:
        with open(SETPOINTS_FILE) as f:
            data = json.load(f)
    except FileNotFoundError:
        return []
    except Exception as e:
        print(f"[setpoints] parse failed, using empty list: {e}", flush=True)
        return []
    if not isinstance(data, list):
        return []
    out = []
    for raw in data:
        if not isinstance(raw, dict):
            continue
        sid = str(raw.get("id", "")).strip()
        name = str(raw.get("name", "")).strip()
        positions = raw.get("positions") or {}
        if not sid or not name or not isinstance(positions, dict):
            continue
        clean_pos = {}
        for ch, pw in positions.items():
            if ch in CHANNELS:
                try:
                    clean_pos[ch] = max(0, min(2500, int(pw)))
                except (TypeError, ValueError):
                    continue
        out.append({
            "id": sid,
            "name": name,
            "positions": clean_pos,
            "created_at": float(raw.get("created_at", 0.0)),
        })
    return out


def save_setpoints(data):
    tmp = f"{SETPOINTS_FILE}.{os.getpid()}.tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, SETPOINTS_FILE)


servo_setpoints = load_setpoints()


def _new_setpoint_id():
    import secrets
    return secrets.token_hex(6)


@app.route('/api/setpoints')
def setpoints_list():
    with _setpoints_lock:
        return jsonify(list(servo_setpoints))


@app.route('/api/setpoints', methods=['POST'])
def setpoints_create():
    """Capture all 10 current servo TARGETS under a named setpoint."""
    data = request.json or {}
    name = str(data.get("name", "")).strip()
    if not name:
        return jsonify({"ok": False, "error": "name required"}), 400
    if len(name) > 64:
        return jsonify({"ok": False, "error": "name too long (max 64)"}), 400
    # Safety: refuse capture until bootstrap restore has completed. Before
    # that, _servo_target_pw may hold values from the 1500us fallback path
    # (if both servo_positions.json and servo_neutral.json were missing) or
    # seeded-but-unconfirmed values. Snapshotting those and replaying them
    # later would command hardware to unverified PW.
    if not _servo_bootstrap_complete:
        return jsonify({
            "ok": False,
            "error": "bootstrap not complete; wait a moment and try again",
        }), 409
    with _servo_state_lock:
        targets = dict(_servo_target_pw)
    missing = [ch for ch in CHANNELS if ch not in targets or targets[ch] is None]
    if missing:
        return jsonify({"ok": False, "error": f"no target for: {','.join(missing)}"}), 409
    # CRITICAL safety check: pw < 500 means PCA is emitting no PWM on that
    # channel (pw=0 is how all_off kills output). A servo with power but no
    # PWM has zero holding torque -- capturing that and replaying it later
    # would relax the servo and drop the arm. Require every channel to have
    # a valid pulse target before we allow the snapshot.
    unpowered = [ch for ch in CHANNELS if int(targets[ch]) < 500]
    if unpowered:
        return jsonify({
            "ok": False,
            "error": (
                "refusing to capture unpowered channels: "
                + ",".join(unpowered)
                + ". Drive every slider to a live position first."
            ),
        }), 409
    positions = {ch: int(targets[ch]) for ch in CHANNELS}
    entry = {
        "id": _new_setpoint_id(),
        "name": name,
        "positions": positions,
        "created_at": time.time(),
    }
    with _setpoints_lock:
        servo_setpoints.append(entry)
        snapshot = list(servo_setpoints)
    try:
        save_setpoints(snapshot)
    except Exception as e:
        with _setpoints_lock:
            try:
                servo_setpoints.remove(entry)
            except ValueError:
                pass
        return jsonify({"ok": False, "error": f"save failed: {e}"}), 500
    return jsonify({"ok": True, "setpoint": entry})


@app.route('/api/setpoints/<sid>', methods=['PATCH'])
def setpoints_rename(sid):
    data = request.json or {}
    name = str(data.get("name", "")).strip()
    if not name:
        return jsonify({"ok": False, "error": "name required"}), 400
    if len(name) > 64:
        return jsonify({"ok": False, "error": "name too long (max 64)"}), 400
    with _setpoints_lock:
        for sp in servo_setpoints:
            if sp["id"] == sid:
                sp["name"] = name
                snapshot = list(servo_setpoints)
                entry = dict(sp)
                break
        else:
            return jsonify({"ok": False, "error": "not found"}), 404
    try:
        save_setpoints(snapshot)
    except Exception as e:
        return jsonify({"ok": False, "error": f"save failed: {e}"}), 500
    return jsonify({"ok": True, "setpoint": entry})


@app.route('/api/setpoints/<sid>', methods=['DELETE'])
def setpoints_delete(sid):
    # Block if any action references this setpoint. The action's playback
    # would otherwise error mid-sequence with a dangling reference.
    used_by = _setpoints_used_by_actions(sid)
    if used_by:
        return jsonify({
            "ok": False,
            "error": "in use by action(s): " + ", ".join(used_by),
        }), 409
    with _setpoints_lock:
        before = len(servo_setpoints)
        servo_setpoints[:] = [sp for sp in servo_setpoints if sp["id"] != sid]
        if len(servo_setpoints) == before:
            return jsonify({"ok": False, "error": "not found"}), 404
        snapshot = list(servo_setpoints)
    try:
        save_setpoints(snapshot)
    except Exception as e:
        return jsonify({"ok": False, "error": f"save failed: {e}"}), 500
    return jsonify({"ok": True})


@app.route('/api/setpoints/<sid>/go', methods=['POST'])
def setpoints_go(sid):
    """Drive all 10 servos toward a saved setpoint via the normal ramp."""
    global _servo_last_heartbeat
    with _setpoints_lock:
        entry = next((sp for sp in servo_setpoints if sp["id"] == sid), None)
    if entry is None:
        return jsonify({"ok": False, "error": "not found"}), 404
    positions = entry.get("positions") or {}
    missing = [ch for ch in CHANNELS if ch not in positions]
    if missing:
        return jsonify({
            "ok": False,
            "error": f"setpoint missing channels: {','.join(missing)}",
        }), 409
    # CRITICAL safety check: never drive any channel below the valid pulse
    # window. pw<500 = PCA stops emitting PWM = servo relaxes under power =
    # arm drops. Block here defensively even if the file was hand-edited
    # or came from an older capture path.
    unpowered = [ch for ch in CHANNELS if int(positions[ch]) < 500]
    if unpowered:
        return jsonify({
            "ok": False,
            "error": (
                "setpoint contains unpowered channels ("
                + ",".join(unpowered)
                + "); refusing to drop the arm. Delete and re-capture."
            ),
        }), 409
    # Block direct Go while an action is playing so two movement sources
    # can't fight over the targets.
    if _action_state.get("running"):
        return jsonify({
            "ok": False,
            "error": "action running; stop it first",
        }), 409
    with _servo_state_lock:
        if _servo_disarmed:
            return jsonify({"ok": False, "error": "disarmed; POST /api/arm first"}), 409
        for ch in CHANNELS:
            pw = max(0, min(2500, int(positions[ch])))
            pw = _clamp_to_envelope(ch, pw)
            _servo_target_pw[ch] = pw
        _servo_last_heartbeat = time.monotonic()
    return jsonify({"ok": True, "id": sid, "name": entry["name"]})


# --- Actions: ordered sequences of setpoints ---
#
# Schema (servo_actions.json):
#   [{"id": "<12hex>",
#     "name": "<label>",
#     "steps": [{"setpoint_id": "<sp>", "breakpoint": bool}, ...],
#     "append_setpoint_id": "<sp or null>",
#     "created_at": <epoch>}, ...]
#
# Playback model: one action at a time. For each step, write that
# setpoint's positions to _servo_target_pw and wait until every channel
# satisfies actual == target (arrival). If the step has breakpoint=True,
# park there until /continue is POSTed. Stop freezes targets to current
# actuals and exits.
#
# No pause between steps: as soon as one arrives, the next step's targets
# are written so the ramp flows continuously at the operator's servo
# speed. The normal ramp loop's step_cap IS the speed profile -- there's
# no separate accel/decel, just constant velocity between targets.
ACTIONS_FILE = os.path.join(GROUNDSTATION_DIR, "servo_actions.json")
_actions_lock = threading.Lock()
_action_play_lock = threading.Lock()
_action_state = {
    "running": False,
    "action_id": None,
    "action_name": None,
    "step_index": 0,      # 1-based step number currently executing (0 = idle)
    "total_steps": 0,     # includes appended home step if any
    "phase": "idle",      # idle | running | waiting-breakpoint | done | error
    "error": None,
}
_action_stop_flag = threading.Event()
_action_continue_flag = threading.Event()
ACTION_ARRIVAL_POLL_S = 0.1
ACTION_ARRIVAL_TIMEOUT_S = 60.0  # per step


def load_actions():
    try:
        with open(ACTIONS_FILE) as f:
            data = json.load(f)
    except FileNotFoundError:
        return []
    except Exception as e:
        print(f"[actions] parse failed, using empty list: {e}", flush=True)
        return []
    if not isinstance(data, list):
        return []
    out = []
    for raw in data:
        if not isinstance(raw, dict):
            continue
        aid = str(raw.get("id", "")).strip()
        name = str(raw.get("name", "")).strip()
        steps_raw = raw.get("steps") or []
        if not aid or not name or not isinstance(steps_raw, list):
            continue
        steps = []
        for s in steps_raw:
            if not isinstance(s, dict):
                continue
            sp_id = str(s.get("setpoint_id", "")).strip()
            if not sp_id:
                continue
            steps.append({
                "setpoint_id": sp_id,
                "breakpoint": bool(s.get("breakpoint", False)),
            })
        append_id = raw.get("append_setpoint_id")
        if append_id:
            append_id = str(append_id).strip() or None
        else:
            append_id = None
        out.append({
            "id": aid,
            "name": name,
            "steps": steps,
            "append_setpoint_id": append_id,
            "created_at": float(raw.get("created_at", 0.0)),
        })
    return out


def save_actions(data):
    tmp = f"{ACTIONS_FILE}.{os.getpid()}.tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, ACTIONS_FILE)


servo_actions = load_actions()


def _new_action_id():
    import secrets
    return secrets.token_hex(6)


def _setpoints_used_by_actions(sp_id):
    """Return list of action names that reference sp_id. Used to block
    setpoint delete when an action depends on it."""
    with _actions_lock:
        snapshot = list(servo_actions)
    used = []
    for a in snapshot:
        if a.get("append_setpoint_id") == sp_id:
            used.append(a["name"])
            continue
        for s in a.get("steps") or []:
            if s.get("setpoint_id") == sp_id:
                used.append(a["name"])
                break
    return used


def _validate_setpoint_for_playback(sp_id):
    """Resolve setpoint id to its positions dict, or return (None, error)."""
    with _setpoints_lock:
        sp = next((s for s in servo_setpoints if s["id"] == sp_id), None)
    if sp is None:
        return None, f"setpoint {sp_id} not found"
    positions = sp.get("positions") or {}
    missing = [ch for ch in CHANNELS if ch not in positions]
    if missing:
        return None, f"setpoint {sp['name']} missing channels: {','.join(missing)}"
    unpowered = [ch for ch in CHANNELS if int(positions[ch]) < 500]
    if unpowered:
        return None, f"setpoint {sp['name']} has unpowered channels ({','.join(unpowered)})"
    return sp, None


def _action_state_snapshot():
    with _actions_lock:
        return dict(_action_state)


def _action_apply_setpoint(positions):
    """Write a setpoint's positions into _servo_target_pw. Returns
    (True, None) on success, (False, reason) on refusal. Callers
    should freeze-to-actual on refusal so a partial apply can't
    strand the arm.

    Belt-and-suspenders: re-checks pw >= 500 per channel even though
    _validate_setpoint_for_playback catches it upstream. Any path that
    calls this directly still gets the no-arm-drop guarantee."""
    global _servo_last_heartbeat
    for ch in CHANNELS:
        pw = int(positions[ch])
        if pw < 500 or pw > 2500:
            return False, f"channel {ch} pw={pw} outside 500..2500 (would drop arm)"
    with _servo_state_lock:
        if _servo_disarmed:
            return False, "disarmed"
        for ch in CHANNELS:
            pw = max(500, min(2500, int(positions[ch])))
            pw = _clamp_to_envelope(ch, pw)
            _servo_target_pw[ch] = pw
        _servo_last_heartbeat = time.monotonic()
    return True, None


def _action_wait_arrival(deadline):
    """Block until every channel's actual matches its target, stop flag
    fires, or deadline passes. Returns 'arrived' | 'stopped' | 'timeout'.
    Also refreshes the heartbeat so the ramp doesn't freeze mid-move:
    the playback thread is effectively a surrogate client during an
    action, responsible for keeping motion alive."""
    global _servo_last_heartbeat
    while time.monotonic() < deadline:
        if _action_stop_flag.is_set():
            return "stopped"
        with _servo_state_lock:
            _servo_last_heartbeat = time.monotonic()
            done = all(
                _servo_actual_pw.get(ch) == _servo_target_pw.get(ch)
                for ch in CHANNELS
            )
        if done:
            return "arrived"
        time.sleep(ACTION_ARRIVAL_POLL_S)
    return "timeout"


def _action_freeze_to_actual():
    """Stop behavior: set every target to the current actual so the ramp
    halts cleanly where the arms currently are, instead of snapping back
    to whatever the last setpoint commanded."""
    global _servo_last_heartbeat
    with _servo_state_lock:
        for ch in CHANNELS:
            a = _servo_actual_pw.get(ch)
            if a is not None:
                _servo_target_pw[ch] = a
        _servo_last_heartbeat = time.monotonic()


def _action_playback_worker(action):
    """Run one action to completion (or stop / error). Sole writer of
    _action_state while playing. Locks are narrow to avoid holding
    _actions_lock across blocking waits."""
    def set_state(**kwargs):
        with _actions_lock:
            _action_state.update(kwargs)

    # Build the flat step list: action.steps + optional appended step.
    flat_steps = []
    for s in action.get("steps") or []:
        flat_steps.append({
            "setpoint_id": s["setpoint_id"],
            "breakpoint": bool(s.get("breakpoint", False)),
        })
    if action.get("append_setpoint_id"):
        flat_steps.append({
            "setpoint_id": action["append_setpoint_id"],
            "breakpoint": False,
        })
    if not flat_steps:
        set_state(running=False, phase="error", error="action has no steps")
        return

    set_state(
        running=True,
        action_id=action["id"],
        action_name=action["name"],
        step_index=0,
        total_steps=len(flat_steps),
        phase="running",
        error=None,
    )

    try:
        for idx, step in enumerate(flat_steps, start=1):
            if _action_stop_flag.is_set():
                set_state(phase="stopped")
                return

            sp, err = _validate_setpoint_for_playback(step["setpoint_id"])
            if err:
                _action_freeze_to_actual()
                set_state(phase="error", error=err)
                return

            set_state(step_index=idx, phase="running")
            applied, apply_err = _action_apply_setpoint(sp["positions"])
            if not applied:
                _action_freeze_to_actual()
                set_state(phase="error", error=apply_err or "apply failed")
                return

            result = _action_wait_arrival(time.monotonic() + ACTION_ARRIVAL_TIMEOUT_S)
            if result == "stopped":
                _action_freeze_to_actual()
                set_state(phase="stopped")
                return
            if result == "timeout":
                _action_freeze_to_actual()
                set_state(phase="error", error=f"step {idx} did not arrive within {ACTION_ARRIVAL_TIMEOUT_S:.0f}s")
                return

            if step["breakpoint"]:
                _action_continue_flag.clear()
                # Re-check stop AFTER clearing continue. Otherwise a /stop
                # that had set both flags in the narrow window between
                # arrival and this clear would look ignored for up to one
                # poll interval.
                if _action_stop_flag.is_set():
                    _action_freeze_to_actual()
                    set_state(phase="stopped")
                    return
                set_state(phase="waiting-breakpoint")
                # Keep heartbeat fresh so the ramp (at rest) doesn't
                # hit the watchdog while we sit at the breakpoint.
                while not _action_continue_flag.is_set():
                    if _action_stop_flag.is_set():
                        _action_freeze_to_actual()
                        set_state(phase="stopped")
                        return
                    with _servo_state_lock:
                        globals()["_servo_last_heartbeat"] = time.monotonic()
                    time.sleep(0.2)
                set_state(phase="running")

        set_state(phase="done")
    finally:
        # Always clear the running flag so the UI stops thinking an action
        # is active and other endpoints unblock.
        with _actions_lock:
            _action_state["running"] = False


@app.route('/api/actions')
def actions_list():
    with _actions_lock:
        return jsonify(list(servo_actions))


@app.route('/api/actions', methods=['POST'])
def actions_create():
    data = request.json or {}
    name = str(data.get("name", "")).strip()
    if not name:
        return jsonify({"ok": False, "error": "name required"}), 400
    if len(name) > 64:
        return jsonify({"ok": False, "error": "name too long (max 64)"}), 400
    steps_raw = data.get("steps")
    if not isinstance(steps_raw, list) or not steps_raw:
        return jsonify({"ok": False, "error": "need at least one step"}), 400
    with _setpoints_lock:
        known_sp_ids = {s["id"] for s in servo_setpoints}
    steps = []
    for s in steps_raw:
        if not isinstance(s, dict):
            return jsonify({"ok": False, "error": "bad step"}), 400
        sp_id = str(s.get("setpoint_id", "")).strip()
        if sp_id not in known_sp_ids:
            return jsonify({"ok": False, "error": f"unknown setpoint: {sp_id}"}), 400
        steps.append({"setpoint_id": sp_id, "breakpoint": bool(s.get("breakpoint", False))})
    append_id = data.get("append_setpoint_id")
    if append_id:
        append_id = str(append_id).strip() or None
        if append_id and append_id not in known_sp_ids:
            return jsonify({"ok": False, "error": f"unknown append setpoint: {append_id}"}), 400
    entry = {
        "id": _new_action_id(),
        "name": name,
        "steps": steps,
        "append_setpoint_id": append_id,
        "created_at": time.time(),
    }
    with _actions_lock:
        servo_actions.append(entry)
        snapshot = list(servo_actions)
    try:
        save_actions(snapshot)
    except Exception as e:
        with _actions_lock:
            try:
                servo_actions.remove(entry)
            except ValueError:
                pass
        return jsonify({"ok": False, "error": f"save failed: {e}"}), 500
    return jsonify({"ok": True, "action": entry})


@app.route('/api/actions/<aid>', methods=['PATCH'])
def actions_update(aid):
    if _action_state.get("running"):
        return jsonify({"ok": False, "error": "action running; stop it first"}), 409
    data = request.json or {}
    with _setpoints_lock:
        known_sp_ids = {s["id"] for s in servo_setpoints}
    with _actions_lock:
        action = next((a for a in servo_actions if a["id"] == aid), None)
        if action is None:
            return jsonify({"ok": False, "error": "not found"}), 404
        if "name" in data:
            name = str(data["name"]).strip()
            if not name or len(name) > 64:
                return jsonify({"ok": False, "error": "bad name"}), 400
            action["name"] = name
        if "steps" in data:
            steps_raw = data["steps"]
            if not isinstance(steps_raw, list) or not steps_raw:
                return jsonify({"ok": False, "error": "need at least one step"}), 400
            steps = []
            for s in steps_raw:
                if not isinstance(s, dict):
                    return jsonify({"ok": False, "error": "bad step"}), 400
                sp_id = str(s.get("setpoint_id", "")).strip()
                if sp_id not in known_sp_ids:
                    return jsonify({"ok": False, "error": f"unknown setpoint: {sp_id}"}), 400
                steps.append({"setpoint_id": sp_id, "breakpoint": bool(s.get("breakpoint", False))})
            action["steps"] = steps
        if "append_setpoint_id" in data:
            append_id = data["append_setpoint_id"]
            if append_id is None or append_id == "":
                action["append_setpoint_id"] = None
            else:
                append_id = str(append_id).strip()
                if append_id not in known_sp_ids:
                    return jsonify({"ok": False, "error": f"unknown append setpoint: {append_id}"}), 400
                action["append_setpoint_id"] = append_id
        snapshot = list(servo_actions)
        entry = dict(action)
    try:
        save_actions(snapshot)
    except Exception as e:
        return jsonify({"ok": False, "error": f"save failed: {e}"}), 500
    return jsonify({"ok": True, "action": entry})


@app.route('/api/actions/<aid>', methods=['DELETE'])
def actions_delete(aid):
    # Block delete while ANY action is playing, not just this one. Rationale:
    # deleting action B removes its setpoint references, which might then
    # unblock deletion of setpoints that action A (the one playing) depends
    # on. Forcing a stop first sidesteps the cascade.
    if _action_state.get("running"):
        return jsonify({"ok": False, "error": "an action is playing; stop it first"}), 409
    with _actions_lock:
        before = len(servo_actions)
        servo_actions[:] = [a for a in servo_actions if a["id"] != aid]
        if len(servo_actions) == before:
            return jsonify({"ok": False, "error": "not found"}), 404
        snapshot = list(servo_actions)
    try:
        save_actions(snapshot)
    except Exception as e:
        return jsonify({"ok": False, "error": f"save failed: {e}"}), 500
    return jsonify({"ok": True})


@app.route('/api/actions/state')
def actions_state():
    return jsonify(_action_state_snapshot())


@app.route('/api/actions/<aid>/play', methods=['POST'])
def actions_play(aid):
    if not _servo_bootstrap_complete:
        return jsonify({"ok": False, "error": "bootstrap not complete"}), 409
    with _servo_state_lock:
        if _servo_disarmed:
            return jsonify({"ok": False, "error": "disarmed; POST /api/arm first"}), 409
    # Serialize play attempts. First acquire beats duplicate clicks.
    if not _action_play_lock.acquire(blocking=False):
        return jsonify({"ok": False, "error": "an action is already running"}), 409
    try:
        with _actions_lock:
            action = next((a for a in servo_actions if a["id"] == aid), None)
            if action is None:
                return jsonify({"ok": False, "error": "not found"}), 404
            # Deep copy so later in-place mutations to servo_actions (via
            # PATCH) can't be observed mid-playback. dict() alone would
            # share the nested steps list.
            import copy as _copy
            action_copy = _copy.deepcopy(action)
        _action_stop_flag.clear()
        _action_continue_flag.clear()

        def runner():
            try:
                _action_playback_worker(action_copy)
            finally:
                _action_play_lock.release()

        threading.Thread(target=runner, daemon=True).start()
    except Exception:
        _action_play_lock.release()
        raise
    return jsonify({"ok": True, "id": aid, "name": action_copy["name"]})


@app.route('/api/actions/<aid>/continue', methods=['POST'])
def actions_continue(aid):
    snap = _action_state_snapshot()
    if not snap.get("running") or snap.get("action_id") != aid:
        return jsonify({"ok": False, "error": "no running action with that id"}), 409
    if snap.get("phase") != "waiting-breakpoint":
        return jsonify({"ok": False, "error": "action is not at a breakpoint"}), 409
    _action_continue_flag.set()
    return jsonify({"ok": True})


@app.route('/api/actions/stop', methods=['POST'])
def actions_stop():
    _action_stop_flag.set()
    _action_continue_flag.set()  # unblock breakpoint wait
    return jsonify({"ok": True})


@app.route('/api/servo_speed', methods=['POST'])
def servo_speed():
    """Set ramp step size (us/tick, capped at SERVO_MAX_STEP_US_PER_TICK)."""
    global _servo_speed_per_tick
    data = request.json or {}
    step = int(data.get("us_per_tick", SERVO_MAX_STEP_US_PER_TICK))
    new_val = max(1, min(step, SERVO_MAX_STEP_US_PER_TICK))
    with _servo_state_lock:
        _servo_speed_per_tick = new_val
    return jsonify({"ok": True, "us_per_tick": new_val})




@app.route('/api/servo_limits/reload', methods=['POST'])
def servo_limits_reload():
    """H-A: reload servo_limits.json from disk. Operators tighten the
    envelope by editing the file and hitting this endpoint; new limits
    are applied to targets going forward."""
    global servo_limits
    servo_limits = _load_servo_limits()
    return jsonify({"ok": True, "limits": servo_limits})


@app.route('/api/servo_limits')
def servo_limits_route():
    """Per-channel {min, max} PW envelope. The UI uses this to set slider
    bounds so a user can never drag outside a mechanically-safe range."""
    return jsonify(servo_limits)


@app.route('/api/joint_calibration')
def joint_calibration_route():
    """Per-channel linear calibration: us_per_rad, sign, neutral_angle_rad,
    min/max_angle_rad. UI and arm viz use this to convert PW <-> angle."""
    with _joint_cal_lock:
        return jsonify(dict(joint_calibration))


@app.route('/api/joint_calibration', methods=['POST'])
def joint_calibration_update():
    """Update one channel's calibration fields. Body:
    {"channel": "B1", "us_per_rad": 420, "sign": 1,
     "neutral_angle_rad": 0, "min_angle_rad": -1.5, "max_angle_rad": 1.5}
    Any subset is accepted; missing fields keep their current values.
    Invalid values are silently ignored (logged server-side)."""
    data = request.json or {}
    name = str(data.get("channel", "")).upper()
    if name not in CHANNELS:
        return jsonify({"ok": False, "error": f"unknown channel: {name}"}), 400
    with _joint_cal_lock:
        current = joint_calibration.get(name) or _default_joint_calibration()[name]
        merged = _sanitize_joint_cal_entry(data, current)
        joint_calibration[name] = merged
        snapshot = dict(joint_calibration)
    try:
        save_joint_calibration(snapshot)
    except Exception as e:
        print(f"[cal] save failed: {e}", flush=True)
        return jsonify({"ok": False, "error": "save failed"}), 500
    return jsonify({"ok": True, "channel": name, "calibration": merged})


@app.route('/api/joint_calibration/solve', methods=['POST'])
def joint_calibration_solve():
    """Two-point calibration solver. Body:
    {"channel": "B1", "pw_A": 1000, "angle_A_rad": 0,
                      "pw_B": 2000, "angle_B_rad": 1.5708}
    Computes us_per_rad, sign, neutral_angle_rad from the two points and
    this channel's current servo_neutral[name]. Saves via the same atomic
    write. Does NOT touch min/max_angle_rad -- user sets those separately."""
    data = request.json or {}
    name = str(data.get("channel", "")).upper()
    if name not in CHANNELS:
        return jsonify({"ok": False, "error": f"unknown channel: {name}"}), 400
    try:
        pw_a = float(data["pw_A"])
        pw_b = float(data["pw_B"])
        ang_a = float(data["angle_A_rad"])
        ang_b = float(data["angle_B_rad"])
    except (KeyError, TypeError, ValueError):
        return jsonify({"ok": False, "error": "need pw_A, pw_B, angle_A_rad, angle_B_rad"}), 400
    dpw = pw_b - pw_a
    dang = ang_b - ang_a
    if abs(dang) < 1e-4:
        return jsonify({"ok": False, "error": "angle_A and angle_B must differ"}), 400
    if abs(dpw) < 1.0:
        return jsonify({"ok": False, "error": "pw_A and pw_B must differ"}), 400
    # Solve: angle = neutral_angle + (pw - neutral_pw)/us_per_rad * sign
    # Pick us_per_rad > 0 and fold direction into sign.
    us_per_rad = abs(dpw / dang)
    sign = 1 if (dpw * dang) > 0 else -1
    neutral_pw = servo_neutral.get(name)
    if neutral_pw is None:
        return jsonify({"ok": False, "error": f"no neutral for {name}; set one first"}), 400
    neutral_angle = ang_a + (neutral_pw - pw_a) / us_per_rad * sign
    with _joint_cal_lock:
        current = joint_calibration.get(name) or _default_joint_calibration()[name]
        merged = dict(current)
        merged["us_per_rad"] = us_per_rad
        merged["sign"] = sign
        merged["neutral_angle_rad"] = neutral_angle
        joint_calibration[name] = merged
        snapshot = dict(joint_calibration)
    try:
        save_joint_calibration(snapshot)
    except Exception as e:
        return jsonify({"ok": False, "error": f"save failed: {e}"}), 500
    return jsonify({
        "ok": True, "channel": name,
        "us_per_rad": us_per_rad, "sign": sign,
        "neutral_angle_rad": neutral_angle,
        "calibration": merged,
    })


def _joint_config_for_armviz():
    """Shape the calibration the way the viz expects:
    config.arms[side].joints[joint_name] = {us_per_rad, sign,
                                            neutral_angle_rad,
                                            min_angle, max_angle}.
    Side 'left' = *1 channels; 'right' = *2 channels."""
    mapping = {
        "base":        "B",
        "shoulder":    "S",
        "elbow":       "E",
        "wrist_roll":  "WA",  # W1A, W2A
        "wrist_pitch": "WB",  # W1B, W2B
    }
    def joints_for(suffix):
        out = {}
        with _joint_cal_lock:
            cal_snap = dict(joint_calibration)
        for jname, prefix in mapping.items():
            if prefix == "WA":
                ch = f"W{suffix}A"
            elif prefix == "WB":
                ch = f"W{suffix}B"
            else:
                ch = f"{prefix}{suffix}"
            c = cal_snap.get(ch)
            if not c:
                continue
            out[jname] = {
                "channel": ch,
                "us_per_rad": c["us_per_rad"],
                "sign": c["sign"],
                "neutral_angle_rad": c["neutral_angle_rad"],
                "min_angle": c["min_angle_rad"],
                "max_angle": c["max_angle_rad"],
            }
        return out
    return {
        "config": {
            "arms": {
                "left":  {"joints": joints_for("1")},
                "right": {"joints": joints_for("2")},
            }
        }
    }


@app.route('/api/ik/status')
def ik_status_route():
    """Arm geometry + joint calibration, shaped for the arm viz. Replaces
    the earlier stub that 404'd and left the viz falling back to a
    hardcoded (wrong) scaling."""
    return jsonify(_joint_config_for_armviz())


@app.route('/api/arm', methods=['POST'])
def servo_arm():
    """Clear the disarmed flag after an all_off. Targets and actuals have
    already been reset to 0 by send_all_off, so nothing moves on re-arm;
    the operator must set new targets explicitly. This is the only way to
    resume motion after an emergency stop."""
    global _servo_disarmed
    with _servo_state_lock:
        _servo_disarmed = False
    _servo_heartbeat()
    return jsonify({"ok": True, "disarmed": False})


@app.route('/api/heartbeat', methods=['POST'])
def heartbeat():
    """Client heartbeat. If this stops arriving for SERVO_HEARTBEAT_TIMEOUT_S,
    the ramp freezes targets wherever the servos actually are."""
    _servo_heartbeat()
    return jsonify({"ok": True})


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
    """Emergency stop. Returns 503 with the list of failed channels if
    any channel did not confirm zero. The client MUST surface this to the
    operator; a partial failure means the physical servos may still be
    energized even though /api/all_off returned.
    """
    ok, failures = send_all_off()
    if not ok:
        return jsonify({
            "ok": False,
            "error": "partial failure; power-cycle PCA rail",
            "failures": failures,
        }), 503
    return jsonify({"ok": True, "disarmed": True})


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


@app.route('/api/mace/jog/status')
def mace_jog_status():
    return jsonify(_mace_snapshot())


@app.route('/api/mace/jog/start', methods=['POST'])
def mace_jog_start():
    data = request.json or {}
    direction = str(data.get("direction", "")).lower()
    if direction not in ("forward", "backward", "brake"):
        return jsonify({"ok": False, "error": "direction must be forward/backward/brake"}), 400
    max_voltage = _mace_clamp_voltage(data.get("max_voltage", 12.0))
    accel_ramp = _mace_clamp_ramp(data.get("accel_ramp", 5.0))
    brake_ramp = _mace_clamp_ramp(data.get("brake_ramp", 12.0))
    try:
        remote = _mace_post_jog("/simplefoc/jog/start", {
            "direction": direction,
            "max_voltage": max_voltage,
            "accel_ramp": accel_ramp,
            "brake_ramp": brake_ramp,
        })
    except Exception as exc:
        with mace_jog_lock:
            mace_jog_state["status"] = "error"
            mace_jog_state["error"] = str(exc)
            mace_jog_state["last_command_at"] = time.monotonic()
        return jsonify({"ok": False, "error": str(exc)}), 502
    with mace_jog_lock:
        mace_jog_state["status"] = "running"
        mace_jog_state["error"] = None
        mace_jog_state["last_command_at"] = time.monotonic()
    snap = _mace_snapshot()
    if isinstance(remote, dict):
        snap["geodude"] = remote
    return jsonify({"ok": True, **snap})


@app.route('/api/mace/calibrate', methods=['POST'])
def mace_calibrate():
    try:
        remote = _mace_start_calibration()
    except Exception as exc:
        with mace_jog_lock:
            mace_jog_state["status"] = "error"
            mace_jog_state["error"] = str(exc)
        return jsonify({"ok": False, "error": str(exc)}), 502
    snap = _mace_snapshot()
    if isinstance(remote, dict):
        snap["geodude"] = remote
    return jsonify({"ok": True, **snap})


@app.route('/api/mace/jog/heartbeat', methods=['POST'])
def mace_jog_heartbeat():
    # Groundstation is a dumb proxy for heartbeats: forward to GEO-DUDe which
    # owns the watchdog. No local "active" mirror — the browser and the
    # watchdog are authoritative.
    data = request.json or {}
    direction = str(data.get("direction", "")).lower()
    try:
        remote = _mace_post_jog("/simplefoc/jog/heartbeat", {"direction": direction})
    except Exception as exc:
        with mace_jog_lock:
            mace_jog_state["status"] = "error"
            mace_jog_state["error"] = str(exc)
            mace_jog_state["last_command_at"] = time.monotonic()
        return jsonify({"ok": False, "error": str(exc)}), 502
    return jsonify({"ok": True, "remote_status": remote.get("status")})


@app.route('/api/mace/jog/stop', methods=['POST'])
def mace_jog_stop():
    try:
        _mace_disable()
        error = None
    except Exception as exc:
        error = str(exc)
    with mace_jog_lock:
        mace_jog_state["status"] = "idle" if error is None else "error"
        mace_jog_state["error"] = error
        mace_jog_state["last_command_at"] = time.monotonic()
    if error is not None:
        return jsonify({"ok": False, "error": error}), 502
    return jsonify({"ok": True, **_mace_snapshot()})


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


# --- Attitude controller proxy ---


@app.route('/api/controller/status')
def controller_status():
    """Report controller availability for frontend feature gating."""
    return jsonify({
        "available": False,
        "enabled": False,
        "connected": False,
        "selected_arm": "left",
        "deadman": False,
        "active": False,
        "last_error": "Controller backend unavailable on this deployment.",
    })


# --- Gimbal proxy ---

def gimbal_get(path):
    """GET request to gimbal ESP32."""
    try:
        resp = urllib.request.urlopen(f"{GIMBAL_URL}/{path}", timeout=3)
        return json.loads(resp.read().decode()), resp.status
    except urllib.error.HTTPError as e:
        try:
            body = e.read().decode().strip()
        except Exception:
            body = ""
        if body:
            try:
                data = json.loads(body)
            except Exception:
                data = {"error": body}
        else:
            data = {"error": str(e)}
        if "error" not in data:
            data["error"] = str(e)
        return data, e.code
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


@app.route('/api/gimbal/motor_speed', methods=['POST'])
def gimbal_motor_speed():
    d = request.json.get("driver", 0)
    us = request.json.get("us", 2000)
    data, code = gimbal_get(f"motor_speed?d={d}&us={us}")
    return jsonify(data), code


@app.route('/api/gimbal/motor_ramp', methods=['POST'])
def gimbal_motor_ramp():
    d = request.json.get("driver", 0)
    steps = request.json.get("steps", 0)
    data, code = gimbal_get(f"motor_ramp?d={d}&steps={steps}")
    return jsonify(data), code


@app.route('/api/gimbal/motor_stealthchop', methods=['POST'])
def gimbal_motor_stealthchop():
    d = request.json.get("driver", 0)
    enabled = 1 if request.json.get("enabled", True) else 0
    data, code = gimbal_get(f"motor_stealthchop?d={d}&enabled={enabled}")
    return jsonify(data), code


@app.route('/api/gimbal/motor_interpolation', methods=['POST'])
def gimbal_motor_interpolation():
    d = request.json.get("driver", 0)
    enabled = 1 if request.json.get("enabled", True) else 0
    data, code = gimbal_get(f"motor_interpolation?d={d}&enabled={enabled}")
    return jsonify(data), code


@app.route('/api/gimbal/motor_multistep_filt', methods=['POST'])
def gimbal_motor_multistep_filt():
    d = request.json.get("driver", 0)
    enabled = 1 if request.json.get("enabled", True) else 0
    data, code = gimbal_get(f"motor_multistep_filt?d={d}&enabled={enabled}")
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


@app.route('/api/gimbal/set_zero', methods=['POST'])
def gimbal_set_zero():
    d = request.json.get("driver", 0)
    data, code = gimbal_get(f"set_zero?d={d}")
    return jsonify(data), code


@app.route('/api/gimbal/clear_zero', methods=['POST'])
def gimbal_clear_zero():
    d = request.json.get("driver", 0)
    data, code = gimbal_get(f"clear_zero?d={d}")
    return jsonify(data), code


@app.route('/api/gimbal/go_zero', methods=['POST'])
def gimbal_go_zero():
    d = request.json.get("driver", 0)
    data, code = gimbal_get(f"go_zero?d={d}")
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


@app.route('/api/gimbal/motor_limits', methods=['POST'])
def gimbal_motor_limits():
    d = request.json.get("driver", 0)
    min_value = request.json.get("min", 0)
    max_value = request.json.get("max", 0)
    data, code = gimbal_get(f"motor_limits?d={d}&min={min_value}&max={max_value}")
    return jsonify(data), code


@app.route('/api/gimbal/tumble_start', methods=['POST'])
def gimbal_tumble_start():
    d = request.json.get("driver", 0)
    a_value = request.json.get("a", 0)
    b_value = request.json.get("b", 0)
    dwell_ms = request.json.get("dwell_ms", 0)
    data, code = gimbal_get(f"tumble_start?d={d}&a={a_value}&b={b_value}&dwell_ms={dwell_ms}")
    return jsonify(data), code


@app.route('/api/gimbal/tumble_stop', methods=['POST'])
def gimbal_tumble_stop():
    d = request.json.get("driver", 0)
    data, code = gimbal_get(f"tumble_stop?d={d}")
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




# Cached hardware-pw snapshot from GEO-DUDe's /pwm_health. Refreshed by the
# ramp thread at ~2 Hz so /api/servo_state can serve it without each browser
# poll hammering the Pi.
_servo_hardware_pw = {name: None for name in CHANNELS}
_servo_hardware_pw_lock = threading.Lock()
_servo_hardware_last_fetch = 0.0

def _fetch_geodude_last_pw():
    """Pull _servo_last_pw from GEO-DUDe. Returns dict or None on failure."""
    try:
        req = urllib.request.Request(f"{GEODUDE_URL}/pwm_health")
        resp = urllib.request.urlopen(req, timeout=1.0)
        if resp.status != 200:
            return None
        body = json.loads(resp.read().decode())
        return body.get("last_pw") or None
    except Exception:
        return None

def _refresh_hardware_pw():
    """Update _servo_hardware_pw from GEO-DUDe. Called by the ramp thread."""
    global _servo_hardware_last_fetch
    snap = _fetch_geodude_last_pw()
    if snap is None:
        return
    with _servo_hardware_pw_lock:
        for name in CHANNELS:
            if name in snap:
                _servo_hardware_pw[name] = snap[name]
        _servo_hardware_last_fetch = time.monotonic()

def _servo_bootstrap_seed_once():
    """One pass: seed every unpowered channel on GEO-DUDe to its saved
    position (fallback neutral, then 1500). Returns True once every
    channel is either live or successfully seeded, so the caller can
    stop retrying.

    /pwm_seed writes the PCA register directly and updates
    _servo_last_pw in one step, avoiding the 50us staircase from 0.
    Armed/moving channels are left alone (pwm_seed rejects them).
    """
    snap = _fetch_geodude_last_pw()
    if snap is None:
        return False
    all_done = True
    for name in CHANNELS:
        hw = snap.get(name)
        if hw not in (None, 0):
            continue  # already live; leave alone
        # Prefer last-known position so reboot restores where we were.
        # Fall back to neutral, then 1500 (dangerous default, but bounded
        # by /pwm_seed's 0<pw<=2500 check).
        target = servo_positions.get(name) or servo_neutral.get(name, 1500)
        if target <= 0 or target > 2500:
            all_done = False
            continue
        try:
            body = json.dumps({"channel": name, "pw": int(target)}).encode()
            req = urllib.request.Request(
                f"{GEODUDE_URL}/pwm_seed",
                data=body,
                headers={"Content-Type": "application/json"},
            )
            resp = urllib.request.urlopen(req, timeout=2.0)
            if resp.status == 200:
                with _servo_hardware_pw_lock:
                    _servo_hardware_pw[name] = int(target)
                # Keep ramp state consistent with hardware so the next
                # user slider doesn't staircase.
                with _servo_state_lock:
                    _servo_actual_pw[name] = int(target)
                    _servo_target_pw[name] = int(target)
                print(f"[servo bootstrap] seeded {name} -> {target}us", flush=True)
            else:
                print(f"[servo bootstrap] seed {name} rejected: HTTP {resp.status}", flush=True)
                all_done = False
        except Exception as e:
            print(f"[servo bootstrap] seed {name} failed: {e!r}", flush=True)
            all_done = False
    return all_done


def _servo_bootstrap_loop():
    """Retry seed until GEO-DUDe answers and every channel is seeded.
    Handles the case where groundstation boots before GEO-DUDe (or
    vice versa). Sleeps 2s between attempts; exits on success."""
    global _servo_bootstrap_complete
    attempt = 0
    while True:
        attempt += 1
        if _servo_bootstrap_seed_once():
            _servo_bootstrap_complete = True
            print(f"[servo bootstrap] complete after {attempt} attempt(s)", flush=True)
            return
        time.sleep(2.0)


def start_background_threads():
    _servo_init_state()
    threading.Thread(target=_servo_bootstrap_loop, daemon=True).start()
    threading.Thread(target=_servo_ramp_loop, daemon=True).start()
    threading.Thread(target=sensor_loop, daemon=True).start()
    threading.Thread(target=positions_flush_loop, daemon=True).start()

def main(port=8080):
    dev = os.environ.get('WHEEL_CONTROL_DEV') == '1'
    is_reloader_child = os.environ.get('WERKZEUG_RUN_MAIN') == 'true'
    if not dev or is_reloader_child:
        start_background_threads()
    if dev:
        import glob
        static_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static')
        templates_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'templates')
        extra = glob.glob(os.path.join(static_dir, '**/*'), recursive=True) + glob.glob(os.path.join(templates_dir, '**/*'), recursive=True)
        app.config['TEMPLATES_AUTO_RELOAD'] = True
        app.run(host='0.0.0.0', port=port, threaded=True, debug=True, use_reloader=True, extra_files=extra)
    else:
        app.run(host='0.0.0.0', port=port, threaded=True)


if __name__ == '__main__':
    port = int(os.environ.get('WHEEL_CONTROL_PORT', '8080'))
    main(port=port)
