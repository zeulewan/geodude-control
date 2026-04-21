from flask import Flask, render_template, jsonify, request
import threading
import time
import json
import os
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
    with open(NEUTRAL_FILE, "w") as f:
        json.dump(data, f)

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
# Commands that would drive a joint past its envelope are clamped to the
# edge before even reaching the ramp. This prevents a buggy UI or a
# typo from driving a servo into a mechanical stop.
#
# Defaults = neutral +/- 600 us, clamped to [500, 2500]. Override per joint
# by placing groundstation/servo_limits.json with {"B1": {"min": 1000, "max": 2000}, ...}.

LIMITS_FILE = os.path.join(GROUNDSTATION_DIR, "servo_limits.json")


def _default_servo_limits():
    limits = {}
    for name in CHANNELS:
        neutral = servo_neutral.get(name, 1500)
        limits[name] = {
            "min": max(500, neutral - 600),
            "max": min(2500, neutral + 600),
        }
    return limits


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
SERVO_HEARTBEAT_TIMEOUT_S = 1.0

_servo_target_pw = {}
_servo_actual_pw = {}
_servo_seq = {}
_servo_speed_per_tick = SERVO_MAX_STEP_US_PER_TICK
_servo_last_heartbeat = 0.0
_servo_ramp_last_tick_mono = 0.0
_servo_disarmed = False  # H2: reject /api/pwm after emergency stop
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
    return render_template('index.html')


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
    # M2: neutral changed -> envelope may be re-centered; reload limits.
    global servo_limits
    try:
        servo_limits = _load_servo_limits()
    except Exception as e:
        print(f"[servo] servo_limits reload after neutral edit failed: {e}", flush=True)
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

def _servo_bootstrap_seed():
    """On boot, seed GEO-DUDe's _servo_last_pw for any channel that is at
    0/None, using our saved neutral. Prevents the 50us staircase slam on
    first user jog.

    Runs once at startup, AFTER _servo_init_state. Only touches channels
    that GEO-DUDe reports as unseeded; armed/moving channels are left
    alone (/pwm_seed rejects them anyway).
    """
    snap = _fetch_geodude_last_pw()
    if snap is None:
        print("[servo bootstrap] GEO-DUDe unreachable; skipping seed", flush=True)
        return
    for name in CHANNELS:
        hw = snap.get(name)
        if hw not in (None, 0):
            continue  # live signal, leave it alone
        neutral = servo_neutral.get(name, 1500)
        if neutral <= 0 or neutral > 2500:
            continue
        try:
            body = json.dumps({"channel": name, "pw": int(neutral)}).encode()
            req = urllib.request.Request(
                f"{GEODUDE_URL}/pwm_seed",
                data=body,
                headers={"Content-Type": "application/json"},
            )
            resp = urllib.request.urlopen(req, timeout=2.0)
            if resp.status == 200:
                # Our belief already matches neutral; just mirror into hw cache.
                with _servo_hardware_pw_lock:
                    _servo_hardware_pw[name] = int(neutral)
                print(f"[servo bootstrap] seeded {name} -> {neutral}us", flush=True)
            else:
                print(f"[servo bootstrap] seed {name} rejected: HTTP {resp.status}", flush=True)
        except Exception as e:
            print(f"[servo bootstrap] seed {name} failed: {e!r}", flush=True)


def start_background_threads():
    _servo_init_state()
    _servo_bootstrap_seed()
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
