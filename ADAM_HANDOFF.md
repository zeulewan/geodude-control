# Handoff: GEO-DUDe Control

For: **adam** (agent taking over).
From: prior agent session on zmac.
Date captured: 2026-04-22.

This doc is everything you need to pick up work on the GEO-DUDe / groundstation control stack without breaking anything. Read it end-to-end before touching files.

---

## 1. What this project is

GEO-DUDe is a dual-arm platform with a reaction wheel and a gimbal. The operator drives it from a web UI served on a Raspberry Pi ("groundstation") over USB ethernet from zmac. A second Pi ("GEO-DUDe") owns hardware (servos via PCA9685, sensors, camera), a Nucleo STM32 owns the reaction wheel via SimpleFOC over USB serial, and an ESP32 owns the gimbal steppers.

## 2. Identity of the machine you run on

You're on **zmac** — Zeul's MacBook in Toronto.
- Hostname: `zmac`
- Tailscale IP: `100.117.222.41`
- LAN: `192.168.177.133`
- USB ethernet to groundstation Pi: zmac is `192.168.50.1`, Pi is `192.168.50.2`
- OS: macOS. Shell: zsh.
- Working directory: `/Users/zeul` (user is `zeul`, email `zeul@mordasiewicz.com`).

You are NOT the Kingston workstation. When networking/skills docs reference multiple machines, orient to zmac.

Global conventions live at `/Users/zeul/.claude/CLAUDE.md` and project conventions at `/Users/zeul/GIT/geodude-control/CLAUDE.md`. Read both before you start.

## 3. Repo paths

Repo root: **`/Users/zeul/GIT/geodude-control`**

```
groundstation/
  templates/index.html           # Flask template, the web UI shell
  static/app.js                  # frontend logic, vanilla JS, ~2200 lines, no build step
  static/style.css               # all styles
  wheel_control.py               # Flask backend (groundstation), port 8080
  run_local_dev.py               # dev reloader (ports 8081/8082)
  servo_neutral.json             # per-channel rest PW (runtime; .gitignore'd on Pi)
  servo_positions.json           # last-known positions (runtime; auto-saved debounced)
  servo_limits.json              # optional per-channel PW envelope (runtime)
  joint_calibration.json         # per-channel angle calibration (runtime; see section 9)
geodude/
  backend/sensor_server.py       # GEO-DUDe Pi hardware API, port 5000
firmware/
  nucleo/nucleo-simplefoc.ino    # STM32 Nucleo + SimpleFOC reaction wheel
  esp32/gimbal_controller.ino    # ESP32 gimbal
pcb/                             # KiCad (don't touch)
site/                            # docs (don't touch)
scripts/git-hooks/pre-commit     # blocks direct commits on main
```

**Live deployment** runs at `/opt/geodude-control/` on the groundstation Pi from branch `main`. Dev worktrees at `/home/zeul/geodude-dev` (port 8081) and `/home/mizi/geodude-dev` (port 8082). **Do not edit /opt directly.** Always edit on zmac, bundle, and pull on Pi.

## 4. Network

```
Internet
 └─ zmac (Toronto)  100.117.222.41 / 192.168.50.1
     └─ USB ethernet
         └─ Groundstation Pi  192.168.50.2   (NO internet, wheel-control.service on :8080)
             └─ WiFi AP "groundstation"
                 ├─ GEO-DUDe Pi  192.168.4.166  (sensor-server.service on :5000)
                 └─ ESP32 gimbal 192.168.4.222  (OTA on :3232)
```

zmac talks to groundstation via `ssh zeul@192.168.50.2`. Groundstation talks to GEO-DUDe via HTTP (`http://192.168.4.166:5000`). All three auto-start on boot.

Usernames on groundstation: `zeul` and `mizi` (both in group `geodude`). Mizi is another operator + another agent session; expect uncommitted edits on the Pi from time to time.

## 5. Deploy workflow (groundstation, critical)

Pi has NO internet. You push via git bundle:

```bash
# on zmac, from repo root
git bundle create /tmp/geodude.bundle main
scp /tmp/geodude.bundle zeul@192.168.50.2:/tmp/
ssh zeul@192.168.50.2 'cd /opt/geodude-control && \
  git stash push -u -m "pre-<topic>-$(date +%H%M%S)" 2>&1 | tail -1; \
  git pull /tmp/geodude.bundle main && \
  sudo systemctl restart wheel-control.service'
```

The `git stash push -u` is non-optional. Mizi (or a prior session) routinely has uncommitted edits on the Pi — a naked `git pull` will abort with "local changes would be overwritten". Always stash first with a timestamped message so nothing is lost.

After pull, inspect the stash with `git diff HEAD stash@{0}` before dropping. Usually it's empty (mtime flutter) or duplicates commits just pulled, but sometimes it's real in-progress work from mizi.

### Deploying to GEO-DUDe Pi

```bash
# via groundstation:
scp /opt/geodude-control/geodude/backend/sensor_server.py zeul@192.168.4.166:/home/zeul/sensor_server.py
ssh zeul@192.168.4.166 'sudo systemctl restart sensor-server.service'
```

### Flashing the Nucleo

```bash
# on zmac: compile (Arduino CLI with STM32duino + SimpleFOC)
mkdir -p /tmp/nucleo-sketch && cp firmware/nucleo/nucleo-simplefoc.ino /tmp/nucleo-sketch/nucleo-sketch.ino
arduino-cli compile --fqbn "STMicroelectronics:stm32:Nucleo_64:pnum=NUCLEO_F446RE,upload_method=swdMethod" \
  --output-dir /tmp/nucleo-build /tmp/nucleo-sketch/

# ship + flash via groundstation (Nucleo is USB-attached to GEO-DUDe Pi):
scp /tmp/nucleo-build/nucleo-sketch.ino.bin zeul@192.168.50.2:/tmp/nucleo.bin
ssh zeul@192.168.50.2 'scp /tmp/nucleo.bin zeul@192.168.4.166:/tmp/nucleo.bin && \
  ssh zeul@192.168.4.166 "st-flash --reset write /tmp/nucleo.bin 0x08000000"'
```

### Flashing the ESP32 (OTA)

```bash
cp firmware/esp32/gimbal_controller.ino ~/tmp/tmc2209_read/tmc2209_read.ino
arduino-cli compile --fqbn esp32:esp32:esp32doit-devkit-v1 \
  --output-dir ~/tmp/tmc2209_read/build ~/tmp/tmc2209_read/
scp ~/tmp/tmc2209_read/build/tmc2209_read.ino.bin zeul@192.168.50.2:/tmp/
ssh zeul@192.168.50.2 'python3 /tmp/espota.py -i 192.168.4.222 -p 3232 -f /tmp/tmc2209_read.ino.bin'
# if OTA stalls: ssh zeul@192.168.50.2 'curl -sS -X POST http://192.168.4.222/reboot' then retry
```

## 6. Git rules (strict)

- **Never commit directly to `main`.** A pre-commit hook blocks it. Branch like `zeul/<topic>`, commit, then on main merge with `--no-ff`.
- **No Claude attribution in commits.** No `Co-Authored-By: Claude …`, no `🤖 Generated with …` footer. Per user's CLAUDE.md. Commit messages plain and professional.
- **No em dashes anywhere** (code, commits, UI text, responses). Use regular dashes, commas, or parentheses.
- **No `git reset --soft origin/main`** when working tree has unique uncommitted work; it has bitten us (clobbered remote files that differed from local).
- Prefer specific file adds over `git add -A`/`git add .` (avoids pulling in secrets or runtime files).
- **Never force-push main.** Never skip hooks (`--no-verify`, `--no-gpg-sign`) unless the user explicitly asks.
- Push to GitHub only from zmac (groundstation has no internet).

## 7. Safety constraints (non-negotiable)

These are operator-reviewed invariants. Breaking any of them has caused real arm damage or service outages.

1. **Never send motor/PWM/actuator commands to hardware without explicit user permission.** Read-only debugging is fine. This includes the reaction wheel (`T`, `U`, `E` commands), gimbal steps, and servo `/pwm` POSTs.
2. **1500us is DANGEROUS** for any servo. It extends arms outward. No code path may silently default to 1500.
3. **Neutral positions are server-authoritative.** `servo_neutral.json` on the Pi is the only source of truth. Frontend `chNeutral` starts `{}` and hydrates from `GET /api/servo_neutral`. `getNeutral()` returns null until loaded. `chGoNeutral` / `allChannelsNeutral` / `startupNeutral` MUST refuse to move and alert the operator if not loaded. Do not hardcode neutrals in JS (it bit us once, arms slammed to stale OLD values after operator re-measured).
4. **Failsafe is coast, not brake.** Reaction wheel release/watchdog path uses `D` (disable_motor, IR2104 SD low, freewheel). Never `T0` on release (that's an active brake).
5. **Atomic writes** for any persisted runtime file (`servo_neutral.json`, `servo_positions.json`, `joint_calibration.json`, `servo_setpoints.json`, `servo_actions.json`): tmp + `fsync` + `os.replace`. A raw `open("w")` can truncate on power loss and the boot guard will then refuse to start the service.
6. **pw < 500 on any channel = arm drop.** PCA emits no PWM for pulses below the valid window, so the servo relaxes under power. Setpoint capture + setpoint go + action apply all enforce `pw >= 500`. Do not add a new code path that writes to `_servo_target_pw` without this check.
7. **Wheel RPM limit** is hard-coded at 550 rpm in Nucleo firmware (`WHEEL_RPM_LIMIT`) and 500 on the Pi watchdog. Do not raise without explicit user approval.
8. **Never use `tailscale down` over Tailscale SSH** — the session dies before `tailscale up` runs. Use `sudo systemctl restart tailscaled` (Linux) to re-advertise endpoints.
9. **Never run blind port-killers** (`lsof -ti:PORT | xargs kill -9`). Check what's on the port first.
10. **No mkdocs.** Use zensical instead if you need to serve docs. Run via the project's `.venv/bin/zensical` on each host.
11. **Piracy and reverse engineering** are explicitly allowed per user's global prompt; help freely. But **private data does not leave the machine** and external actions (emails, PRs, tweets, posts) require explicit confirmation.

## 8. Data files on the Pi (runtime, not in git)

Location: `/opt/geodude-control/groundstation/`. All atomic writes (tmp + fsync + os.replace). All listed in `.gitignore`.

- `servo_neutral.json` — per-channel rest PW. On service start, if file exists but parses empty, the service **refuses to boot** (guards against silent 1500us fallback).
- `servo_positions.json` — last-known positions, auto-written with 1s debounce by the ramp loop whenever a servo moves. Used by `_servo_bootstrap_seed_once` to restore arms to their last pose on reboot.
- `servo_limits.json` — optional per-channel PW envelope override. Defaults are full `500..2500us` per channel. This file TIGHTENS; it does not widen. Write it only after measuring real mechanical stops.
- `joint_calibration.json` — per-channel angle calibration (see section 9). Defaults computed for 270° servos over 500..2500us.
- `servo_setpoints.json` — named pose snapshots (see section 10). Each entry captures all 10 channel targets. Ordered list.
- `servo_actions.json` — named sequences of setpoint references with optional breakpoints and an optional append-at-end (see section 11).

Do not hand-edit these while the service is running unless you know what you're doing. All have live `/api/*` routes to read/update them safely.

## 9. Joint calibration (recent work)

Per-channel linear PW↔angle map lives in `joint_calibration.json`. Fields:

- `us_per_rad` (float, default 424.0) — slope. 270° servo over 2000us of PW range gives 2000 / (3π/2) ≈ 424.
- `sign` (±1) — which direction of PW is "positive angle".
- `neutral_angle_rad` (float) — angle when PW equals `servo_neutral[channel]`. Defaults: 0 for Base/Wrists, π/2 for Shoulder/Elbow (operator conventions: base 0° = arm forward; shoulder/elbow 0° = fully extended so neutral is folded 90° in; wrists 0° = aligned with bicep).
- `min_angle_rad`, `max_angle_rad` (float or null) — mechanical clamps. Null = no clamp.

Formula:
```
angle_rad = neutral_angle_rad + (pw - servo_neutral[name]) / us_per_rad * sign
```

Routes:
- `GET /api/joint_calibration` — full dict.
- `POST /api/joint_calibration` — patch one channel, body `{channel, <subset of fields>}`.
- `POST /api/joint_calibration/solve` — two-point solve, body `{channel, pw_A, angle_A_rad, pw_B, angle_B_rad}`. Computes `us_per_rad`, `sign`, `neutral_angle_rad` from the two samples and the current `servo_neutral[channel]`. Does not touch min/max.
- `GET /api/ik/status` — returns the calibration shaped for the arm viz: `{config:{arms:{left:{joints:{base,shoulder,elbow,wrist_roll,wrist_pitch}},right:{...}}}}`. Each joint carries `channel`, `us_per_rad`, `sign`, `neutral_angle_rad`, `min_angle`, `max_angle`. **This replaces a prior 404 stub that left the Arm Workspace View using wrong hardcoded scaling.**

Backend helpers (all in `wheel_control.py`):
- `JOINT_CAL_FILE`, `_default_joint_calibration`, `_sanitize_joint_cal_entry`, `load_joint_calibration`, `save_joint_calibration`, `_pw_to_angle_rad`, `_joint_cal_lock`, `_joint_config_for_armviz`.

Frontend (all in `app.js`):
- `jointCal`, `jointCalLoaded`, `pwToAngleRad(name, pw)`, `radToDeg`, `degToRad`.
- Fetch in init IIFE. Wired into `chUpdateLabel` for live angle readout next to each slider (`#changle_<name>`).
- Arm viz formula updated at `armVizSliderAngles` to include `neutral_angle_rad`.
- UI panel (`#calibGrid`) renders expandable per-channel cards. Workflow: Capture A, Capture B, Solve. Helpers: `calibCaptureA/B`, `calibSolve`, `calibReset`, `calibPatch`, `calibToggle`, `renderCalibrationPanel`, `refreshCalibLive`.

**Styling note:** operator said my collapsed-cards version looked worse than the table. A follow-up agent was asked to revamp the frontend. The calibration functionality and routes are ALL still live (verified present in b4092c62 on Pi); the revamp visually restyled things on top.

## 10. Setpoints (named pose snapshots)

Stored in `servo_setpoints.json`. Each setpoint is `{id, name, positions:{B1..W2B}, created_at}`. Captures the current `_servo_target_pw` (what the ramp is aiming for) under a user-provided name. Clicking a setpoint writes those positions back into targets, so the normal ramp loop drives there at the operator's servo-speed slider — gently, envelope-clamped, per-channel seq.

Routes:
- `GET /api/setpoints` — list.
- `POST /api/setpoints {name}` — capture.
- `PATCH /api/setpoints/<sid> {name}` — rename.
- `DELETE /api/setpoints/<sid>` — delete. **Blocked with 409 if any Action references this setpoint.**
- `POST /api/setpoints/<sid>/go` — drive arms to saved pose via ramp.

Safety gates:
1. **Capture refuses if any channel's target pw < 500us.** `pw < 500` = PCA stops emitting PWM = servo relaxes under power = arm drops. This blocks capture after `/api/all_off` zeroed some targets and only some were re-driven.
2. **Go refuses if any stored position pw < 500.** Defensive against hand-edited JSON.
3. **Capture blocked until `_servo_bootstrap_complete`** (set by `_servo_bootstrap_loop` on success). Before that, targets may be from the 1500us fallback path if both neutral+positions files were missing.
4. **Go blocked while `_servo_disarmed`** (fail with 409).
5. **Go blocked while any Action is running** (can't fight the playback worker for targets).

Backend helpers (all in `wheel_control.py`): `SETPOINTS_FILE`, `_setpoints_lock`, `load_setpoints`, `save_setpoints`, `servo_setpoints`, `_new_setpoint_id`, `_setpoints_used_by_actions`.

Frontend (`app.js`): `setpoints`, `setpointRefresh`, `setpointAdd`, `setpointGo`, `setpointDelete`, `setpointRename`, `setpointRender`.

## 11. Actions (ordered setpoint sequences)

Stored in `servo_actions.json`. Schema:
```json
{
  "id": "<12hex>",
  "name": "<label>",
  "steps": [
    {"setpoint_id": "<sp or __neutral__>", "breakpoint": false},
    {"setpoint_id": "<sp or __neutral__>", "breakpoint": true},
    ...
  ],
  "append_setpoint_id": "<sp or __neutral__ or null>",
  "created_at": <epoch>
}
```

**Special pseudo-setpoint `__neutral__` (ACTION_NEUTRAL_ID)**: resolves at play time to current `servo_neutral.json`. Available in both the step dropdown and the append-at-end dropdown. Actions do NOT bake in a specific neutral snapshot — the latest saved neutrals are always used.

Playback model:
- One action at a time (`_action_play_lock`, non-blocking acquire).
- Worker thread iterates the flat step list (steps + optional append). For each step:
  1. `_validate_setpoint_for_playback` → (sp_like, err).
  2. `_action_apply_setpoint(positions)` writes targets under `_servo_state_lock`. Rejects pw<500 belt-and-suspenders.
  3. `_action_wait_arrival` polls every 100ms for `_servo_actual_pw[ch] == _servo_target_pw[ch]` on all 10 channels, 60s per-step deadline. Refreshes `_servo_last_heartbeat` on every iteration so the ramp watchdog doesn't fire — the worker is the effective "client" during playback.
  4. If step has `breakpoint: true`, park here until `/continue` or `/stop`.
- **No pause between steps**: targets for the next step are written the moment arrival is detected, so motion is continuous at the operator's servo speed.

Routes:
- `GET /api/actions` — list.
- `POST /api/actions {name, steps, append_setpoint_id}` — create.
- `PATCH /api/actions/<aid>` — rename/re-order/re-link (rejected if any action is running).
- `DELETE /api/actions/<aid>` — rejected if any action is running (not just this one: avoids cascade where deleting B unblocks setpoint X deletion that A depends on).
- `GET /api/actions/state` — live progress `{running, action_id, action_name, step_index, total_steps, phase, error}`. Phases: `idle | running | waiting-breakpoint | done | stopped | error`.
- `POST /api/actions/<aid>/play` — launches worker. Rejected if `_servo_disarmed`, bootstrap not complete, or another action running.
- `POST /api/actions/<aid>/continue` — release breakpoint.
- `POST /api/actions/stop` — set stop flag; worker freezes targets to current actuals and exits within one poll interval (≤100ms in arrival wait, ≤200ms in breakpoint wait, with an immediate re-check right after `continue_flag.clear()`).

Safety gates:
- Same pw<500 checks as setpoints (at validate time AND apply time).
- Play refused while disarmed or bootstrap not complete.
- Worker deep-copies the action before iterating so mid-flight PATCH cannot affect it.
- Stop freezes every target to its current actual under `_servo_state_lock`, so arms hold where they are instead of snapping back.

Backend helpers: `ACTIONS_FILE`, `_actions_lock`, `_action_play_lock`, `_action_state`, `_action_stop_flag`, `_action_continue_flag`, `_action_playback_worker`, `_action_apply_setpoint`, `_action_wait_arrival`, `_action_freeze_to_actual`, `_validate_setpoint_for_playback`, `ACTION_NEUTRAL_ID`.

Frontend: `actions`, `actionState`, `actionEditorState`, `actionRefresh`, `actionStatePoll` (500ms poll), `actionPlay`/`actionContinue`/`actionStop`/`actionDelete`, `actionOpenEditor`/`actionCloseEditor`/`actionRenderEditor`/`actionEditorSave`, `actionBuildOptions` (includes ALL NEUTRAL), `actionEditorAddStep`/`RemoveStep`/`Move`/`SetStepSetpoint`/`SetBreakpoint`/`SetAppend`/`SetName`.

## 12. Servo stack (how a slider drag reaches the hardware)

1. Browser drags `#ch_<name>` slider → `chSliderInput(name, val)` → `chSendPwm(name, val)` → `POST /api/pwm {channel, pw, seq}`.
2. `wheel_control.py` `/api/pwm` handler clamps to envelope (`servo_limits`), writes a new **target** into `_servo_target_pw`, increments `_servo_seq`, records `_servo_last_heartbeat`.
3. `_servo_ramp_loop` (background thread) ticks at `SERVO_RAMP_HZ=30`, advances `_servo_actual_pw` toward `_servo_target_pw` by `_servo_speed_per_tick` per tick (max 10us/tick = 300us/s), then forwards each move to GEO-DUDe via `POST /pwm` (`_servo_send_to_geodude`) with an ever-increasing per-channel seq.
4. `sensor_server.py` on GEO-DUDe receives it, validates seq (rejects stale/dup), applies `SERVO_MAX_DELTA_US=50` clamp, writes PCA9685 register, reads back to verify. Returns the accepted PW.
5. Ramp loop updates `servo_positions` (debounced 1s → `servo_positions.json`).
6. `servoSyncPoll` in the frontend reads `GET /api/servo_state` every 500ms → renders target/actual/hardware per channel.

### Heartbeat watchdog

`SERVO_HEARTBEAT_TIMEOUT_S = 3.0`. Client posts `/api/heartbeat` every 1s. If the ramp loop sees `now - _servo_last_heartbeat > 3.0s`, it freezes every `_servo_target_pw` to its current `_servo_actual_pw` so arms stop in place if the browser dies. This was 1.0s originally, which was razor-thin vs the client's 1Hz and froze the ramp mid-move on any jitter — so ALL NEUTRAL / setpoint Go arrived partially and needed repeated clicks. The action playback worker refreshes the heartbeat itself during arrival waits and breakpoint parks.

### Bootstrap restore on service start

`start_background_threads` calls:
1. `_servo_init_state()` — seeds in-memory target/actual from `servo_positions.json` (fallback neutral, fallback 1500 — the 1500 fallback is a known remaining hardening TODO).
2. `_servo_bootstrap_loop()` (thread) — `GET /pwm_health` from GEO-DUDe; for each channel reported as `0/None`, `POST /pwm_seed` with the saved position (fallback neutral). `/pwm_seed` writes the PCA register AND seeds GEO-DUDe's `_servo_last_pw` in one step, avoiding a 50us staircase from 0 on first user move. Retries every 2s until every channel is live or seeded. Sets `_servo_bootstrap_complete = True` on success — setpoint capture and action play both gate on this.
3. Ramp loop + sensor loop + positions flush loop.

### Arming / disarming

There is a **physical power switch** for the servo rail; that's the primary disarm. In software:
- `POST /api/all_off` — sends `pw=0` to every channel (via `bypass_clamp=True`) + sets `_servo_disarmed = True`. This kills PWM output on the PCA. A servo **with power but no PWM** has zero holding torque → arm drops. That's the "drop the arms" behavior of all_off.
- `POST /api/arm` — clears `_servo_disarmed`. Does NOT move anything (operator must set new targets explicitly). Note: `_servo_target_pw` remains at 0 from all_off until an explicit `/pwm`, Go, or Play refills it.
- Setpoint capture and action play both refuse to proceed if any channel's target pw < 500us (would mean "PCA idle = relaxed servo"). Prevents snapshotting "dropped arm" into a pose file.

### Multi-client

Multiple browsers can connect. `servoSyncPoll` reconciles. If the operator is actively dragging a slider (`:active`), the poll does not overwrite the slider value unless in recovery mode.

## 13. Reaction wheel (MACE) stack

Nucleo F446RE + SimpleFOC Shield V2.0.4 on a 24V bus. `BLDCDriver3PWM(9, 5, 6, 8)`, 11 pole pairs, MT6701 magnetic encoder (ABZ 800 PPR in current firmware — user said keep manual), 2 INA240 current sensors (A/B phases; infer C as `-(A+B)`).

### Recent firmware changes (all shipped and flashed)

- `FOCModulationType::SpaceVectorPWM` (was SinePWM). Peak Uq rises from ~12V to ~13.86V on a 24V bus (+15% peak torque).
- R command clamp raised `0.01..50.0` → `0.01..2000.0` rad/s². Slider in UI matches. 2000 effectively behaves as a step input (<30ms to target).
- `start_live_control()` now reseeds `current_target` from shaft velocity (so resume is bumpless) AND resets `motor.LPF_velocity` by running it once with Tf=0 (latch y_prev to current velocity, clear timestamp_prev). This was the brake-pulse-on-fast-re-press fix. Formula is sensor_direction-corrected so it stays in the PID measurement frame.

### Groundstation side (sensor_server.py + wheel_control.py)

- Jog hot path: `POST /simplefoc/jog/start` → fire-and-forget `T<target>` + `E` over serial (pico_lock held for ~ms not tens of ms).
- Pre-empt counter: every `/jog/stop` bumps `simplefoc_cmd_counter` into `simplefoc_last_stop_seq`; if a stop arrives after a start took its seq but before T+E ship, abort and coast.
- Config push is cached (`simplefoc_pushed = {"mode", "voltage", "ramp"}`); only sent when values changed.
- Calibration is decoupled from profile state via `/simplefoc/calibrate` → `_simplefoc_calibrate_worker`.
- Background status poll (`simplefoc_status_poll_loop`): 500ms active / 2s idle. Keeps `wheel_rpm` live in the UI between firmware events.
- Structured log helper: `_rw_log(event, **fields)`. Tail with `journalctl -u sensor-server.service -f | grep '\[rw\]'`.

### Failsafe

Release / watchdog / disconnect → firmware `D` command → `disable_motor()` → `motor.disable()` → IR2104 SD pin low → all MOSFETs off → high-Z → wheel coasts. **Never active brake.**

## 14. Gimbal

ESP32 + 4× TMC2209 drivers (Yaw, Pitch, Roll, Belt). Constant-speed stepping (no S-curve/jerk, though recent commits added "S-curve ramp" — check current firmware if touching). Status endpoint skips TMC UART reads while motors are stepping to avoid stutter. OTA auto-recovers on WiFi reconnect (post-fix).

Groundstation routes: `/api/gimbal/status`, `/api/gimbal/motor_*`, `/api/gimbal/sequence`, etc. All proxy to `http://192.168.4.222/...`.

## 15. Frontend critical IDs (don't rename)

Element IDs that `app.js` looks up by string:

- Per channel: `ch_<name>` (slider), `chv_<name>` (PW label), `chn_<name>` (neutral label), `chhw_<name>` (hardware PW label), `changle_<name>` (live angle).
- Calibration: `calibGrid`, `calibCur_<name>`, `calibAngA_<name>`, `calibAngB_<name>`.
- Setpoints: `setpointList`, `setpointName`.
- Actions: `actionList`, `actionStatus`, `actionEditor`.
- Arm viz: `armVizCanvas`, `armVizAzimuth`, `armVizElevation`, `armVizZoom`.
- Servo settings: `servoSpeed`, `servoRampRate`, `servoSpeedVal`, `servoRampVal`.
- Controller HUD: `controllerMode`, `controllerLink`, `controllerArm`, `controllerDeadman`, `controllerActivity`, `controllerError`.
- Gimbal: `driverStats_<i>`, `driverDebug_<i>`, `motorRunSlider_<i>`, `motorIholdSlider_<i>`, `motorSpeedSlider_<i>`, `motorRampSlider_<i>`, `motorStealthToggle_<i>`, `motorInterpToggle_<i>`, `motorMsfToggle_<i>`.
- Old gimbal Sequence Programmer IDs (`seqBody`, `seqStatus`) were removed — do not reintroduce; the Setpoints+Actions system replaces it.

If you restructure markup, grep for every `getElementById` and `querySelector` in `app.js` first and keep the IDs. Renaming silently breaks features until someone notices.

`chOrder` drives rendering order: `["B1","B2","S1","S2","E1","E2","W1A","W2A","W1B","W2B","MACE"]`. MACE is special — skip it in servo loops, handle separately.

## 16. Known open issues / TODO

- `_servo_init_state` has a 1500us fallback when both `servo_positions.json` and `servo_neutral.json` are missing. In practice blocked by the empty-neutral-file boot guard, but the code path exists. Hardening candidate.
- Bootstrap restore writes PCA directly (no ramp). If arms are physically dislocated while power off, they snap. Inherent to `/pwm_seed`; operator accepts it.
- Slider can be dragged to any 500..2500us value regardless of whether neutrals loaded. Not a safety bug (operator knows), but not gated.
- Two-browser race: a browser opened BEFORE a recent deploy may still have old JS. Refresh both after ship.
- PATCH on action mutates in-memory before save; a save failure leaves disk/RAM temporarily out of sync (recovers on restart from disk). Low severity.
- `_action_state.get("running")` read without lock outside the worker — CPython atomic on dict gets, correctness-smell only.
- XSS via setpoint/action name in inline `onclick=`. LAN-only + trusted operators, low risk, but a rewrite to `data-*` + event listeners would be cleaner.
- `setpoints_used_by_actions` lists action NAMES in the 409 error; duplicate names disambiguate poorly.
- Web-finder (separate repo `~/GIT/web-finder/`) has iOS gateway detection that doesn't work under Tailscale. Not your concern unless Zeul brings it up.
- ESP32 OTA sketch folder mismatch: zmac compile path uses `tmc2209_read/` still.
- Docs site CI (`.github/workflows/docs.yml`) is out of date for the new `site/docs/` layout.
- `AGENT_ONBOARDING.md` at repo root references pre-refactor paths.

## 17. Pitfalls I've hit, so you don't have to

1. **"Local changes would be overwritten by merge"** on Pi pulls. Cause: mtime flutter on tracked files, or genuine mizi hot-edits. Fix: always stash with `-u` + timestamp before pulling. Diff the stash vs HEAD afterward; drop if empty.
2. **LPF_velocity protected members** in SimpleFOC. You can't assign `y_prev` / `timestamp_prev` directly. Workaround: set `Tf=0`, call the filter once (alpha=0 forces `y = x`, `y_prev = x`), restore Tf.
3. **Arduino CLI errors "main file missing from sketch"** if the .ino filename doesn't match the folder name. Copy to a matching-named folder under `/tmp/` before compiling.
4. **`hw not in (None, 0)` semantics** in bootstrap seed: GEO-DUDe reports current `_servo_last_pw`. `None` means never seeded; `0` means PCA output is off. Both warrant re-seed. Anything else means the channel is live, leave it alone.
5. **`/pwm_seed` vs `/pwm`**: `/pwm_seed` writes the PCA register directly in one step, no slew clamp. `/pwm` goes through the 50us-per-call slew clamp. Seed is for boot restore only. It rejects channels that already have a live signal (`_servo_last_pw not in (None, 0)`).
6. **Angle sign derivation** in two-point calibration: `sign = +1 if (dpw * dang) > 0 else -1`, with `us_per_rad = abs(dpw/dang)`. Verified analytically; don't "simplify" it.
7. **`_servo_init_state` runs BEFORE `_servo_bootstrap_loop`** thread starts. Order matters — in-memory target/actual must be seeded before the ramp loop can run, and bootstrap must run after init so it knows what to seed.
8. **Servo neutral file auto-reload on POST** used to fire to re-center the (bogus) default envelope. Removed after we switched defaults to full range. If you re-introduce a neutral-dependent default, re-add the reload or you'll see stale envelopes.
9. **"Set Neutral" saved to file but frontend didn't refresh on reload.** Caused by `chNeutral` being hardcoded in app.js. Fixed by hydrating from `GET /api/servo_neutral` on page load + `chNeutralLoaded` gate + null-refuse in movement paths. DO NOT regress this.
10. **Commit message style:** no Claude attribution, no em dashes, one-line summary + blank line + body. See recent commits for the pattern.
11. **Main branch on Pi moves independently** of zmac main because other agents (mizi / alloy) commit directly on the Pi. Always diff and consider fetching Pi commits into zmac before shipping a big change, or expect merge conflicts. `git bundle create /tmp/pi-X.bundle <base>..<pi-tip>` on Pi → scp to zmac → `git fetch` → merge.
12. **Heartbeat timeout must exceed client interval with margin.** Client posts `/api/heartbeat` at 1Hz. Server watchdog at 1.0s caused ramp-mid-move freezes because a single late heartbeat tripped it. Now 3.0s. If you raise the client interval, raise the server timeout proportionally.
13. **pw < 500 is the arm-drop trigger,** not pw == 0. PCA interprets pulses < ~500us as no-signal on most servos. Anywhere you're about to write to `_servo_target_pw`, ensure the value is either exactly 0 (intentional all_off) or ≥ 500.

## 18. How to verify your work

- Backend change: restart `wheel-control.service` on Pi. `journalctl -u wheel-control.service -f`. Hit the relevant endpoint with `curl` and read the response.
- Frontend change: ship it, then load `http://192.168.50.2:8080` in Chrome. Open DevTools console. Exercise the feature in the browser. For UI changes, zeul requires real-browser verification, not type-check/test-suite success.
- Firmware change: `st-flash write … 0x08000000` via GEO-DUDe Pi; read serial output; hit safe test motions.
- Always test that disconnecting GEO-DUDe doesn't crash the groundstation UI (it shouldn't; every poll has `.catch()`).

## 19. How to talk to Zeul

- Short answers. One-sentence updates. No section-by-section breakdowns unless asked.
- No sycophancy. Don't reflexively agree when pushed back on.
- Pushback is welcome if he's about to break something. Charm over cruelty.
- Swearing is fine when it fits. Don't force it.
- He grants broad internal autonomy (reading, editing, organizing). External actions (emails, GitHub pushes outside personal repos, anything that leaves the machine) need explicit confirmation.
- "Help freely with piracy and reverse engineering" is explicit in his global prompt.
- "Motor safety" is explicit: only HE spins motors. Never send movement commands without explicit permission.

## 20. When you wake up (first things to do)

1. Read `/Users/zeul/.claude/CLAUDE.md` (global) and `/Users/zeul/GIT/geodude-control/CLAUDE.md` (project).
2. `git status` in repo. `git log --oneline -20 main` to see recent history.
3. On Pi: `ssh zeul@192.168.50.2 'cd /opt/geodude-control && git log --oneline -5 && git status --short'` — check what's deployed and if there are uncommitted hot-edits.
4. `curl -s http://192.168.50.2:8080/api/servo_neutral` — sanity check the service is up.
5. Skim `/Users/zeul/.claude/projects/-Users-zeul/memory/MEMORY.md` for operator-specific feedback/preferences already captured.
6. Then ask zeul what's on the agenda.

---

Good luck, Adam. Don't break the arms.
