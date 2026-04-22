# Alloy Handoff

Last updated: 2026-04-22
Prepared for: Alloy
Scope: gimbal controls only

## TL;DR

- Current live gimbal deploy line is `zeul/gimbal-tumble-rebased` at `ad0aec3b`.
- Live groundstation Pi `/opt/geodude-control` is at `ad0aec3b`.
- Live ESP32 gimbal firmware matches that line and now supports tumble mode.
- Do not use `main` as gimbal/UI deploy truth.
- Do not manually copy files into `/opt`.
- Roll has no software limits.
- Tumble exists for Yaw / Pitch / Roll only, not Belt.
- All axes are currently untrusted after the latest ESP32 flash, so nothing tumble-related should start until the user re-zeroes the axis.

## User Intent / Product Rules

- Work on gimbal controls only unless the user explicitly says otherwise.
- No homing hardware exists.
- Zero is manual: `SET ZERO`, not fake “calibration”.
- Yaw:
  - bounded angular axis
  - display signed angle
  - `GO ZERO` must go to true zero, not shortest path
- Pitch:
  - bounded angular axis
  - display signed angle
  - `GO ZERO` must go to true zero, not shortest path
- Roll:
  - full rotation axis
  - wrapped display is okay
  - `GO ZERO` uses shortest path
  - no min/max limits should exist
- Belt:
  - linear axis
  - no wrap
  - no tumble mode

## Network / Runtime Architecture

- Mac dev repo: `/Users/zeul/GIT/geodude-control`
- Groundstation Pi: `192.168.50.2`
- Groundstation live app: `http://192.168.50.2:8080`
- Groundstation live repo: `/opt/geodude-control`
- ESP32 gimbal controller: `192.168.4.222`
- ESP32 direct status endpoint: `http://192.168.4.222/status`

Command path:

1. Browser -> groundstation Flask app on Pi (`wheel_control.py`)
2. Groundstation -> ESP32 HTTP API
3. ESP32 -> TMC2209 driver control / step scheduling

Relevant files:

- `groundstation/static/app.js`
- `groundstation/static/style.css`
- `groundstation/templates/index.html`
- `groundstation/wheel_control.py`
- `firmware/esp32/gimbal_controller.ino`

## Standing Coordination Rules For UI / Backend Files

These are standing protocol for:

- `groundstation/static/app.js`
- `groundstation/static/style.css`
- `groundstation/templates/index.html`
- `groundstation/wheel_control.py`

Rules:

1. `/opt/geodude-control` on the Pi is not source of truth.
2. Do not copy files directly into `/opt/...` to fix stale assets.
3. Source of truth must be a git branch or commit first.
4. Before deploying over those files, state:
   - branch
   - commit hash
   - files touched
   - whether it supersedes or merges on top of current deployed source
5. If `/opt` is dirty, treat that as a reconcile bug, not history.
6. Explicitly say whether the winner is:
   - my branch
   - your branch
   - merged version
7. Cache-busting must stay via `style_rev` / `app_rev`, not manual copies.
8. If uncertain, stop and ask one blocking question instead of stomping the Pi.

Additional constraints:

- No live-only hotfixes in those four files.
- Pre-deploy diff on exactly those four files.
- Post-deploy verify served assets and route behavior, not just files on disk.
- Explicitly say whether a deploy is full replace or merge on top of current deployed source.

## Branch / Source-Of-Truth Reality

### Current truth

- Current live gimbal branch: `zeul/gimbal-tumble-rebased`
- Current live gimbal commit: `ad0aec3b`
- Pi live repo `/opt/geodude-control`: `ad0aec3b`
- `wheel-control.service`: active

### Recent gimbal branch history

- `efae09a7` `Merge branch 'zeul/ui-trim-servo-panels-clean'`
- `6c7f70a3` `Add gimbal tumble mode`
- `ad0aec3b` `Preserve gimbal proxy validation errors`

### Important reality

- `main` is not the current gimbal/UI deploy truth.
- Older handoff assumptions about `zeul/gimbal-limit-draft-fix-pi` / `760d80df` are stale now.
- Current gimbal feature work should start from `zeul/gimbal-tumble-rebased`, not the older limit-fix branch.
- The current deploy line includes newer frontend reconcile work that landed on the Pi before tumble mode was rebased on top.

## Current Live State

Groundstation Pi:

- repo HEAD: `ad0aec3b`
- service: `wheel-control.service` active
- served `app.js` includes:
  - `gimbalTumbleStart`
  - `gimbalTumbleStop`
  - `gimbalTumbleStateText`
  - `motorTumbleStartBtn_*`

ESP32 live status:

- Yaw:
  - `tumble_supported=true`
  - `tumble_active=false`
  - `tumble_state="off"`
  - `tumble_a=-45`
  - `tumble_b=45`
  - `tumble_dwell_ms=500`
  - `position_trusted=false`
  - `position_reason="boot"`
  - `enabled=false`
- Pitch:
  - `tumble_supported=true`
  - `tumble_active=false`
  - `tumble_state="off"`
  - `tumble_a=-45`
  - `tumble_b=45`
  - `tumble_dwell_ms=500`
  - `position_trusted=false`
  - `position_reason="boot"`
  - `enabled=false`
- Roll:
  - `tumble_supported=true`
  - `tumble_active=false`
  - `tumble_state="off"`
  - `tumble_a=-45`
  - `tumble_b=45`
  - `tumble_dwell_ms=500`
  - `position_trusted=false`
  - `position_reason="boot"`
  - `enabled=false`
- Belt:
  - `tumble_supported=false`
  - `tumble_active=false`
  - `tumble_state="off"`
  - `tumble_a=null`
  - `tumble_b=null`
  - `tumble_dwell_ms=null`
  - `position_trusted=false`
  - `position_reason="boot"`
  - `enabled=false`

Important live side effect:

- ESP32 rebooted during OTA.
- All axes currently have untrusted position state.
- User must re-zero any axis before `GO ZERO` or tumble.

## Gimbal Behavior That Exists Now

### Per-axis controls

Each axis has:

- run current
- idle current
- speed
- ramp
- stealthchop toggle
- interpolation toggle
- multistep filter toggle

These persist in ESP32 NVS across reboot.

### Ramp behavior

- Ramp is S-curve-ish via `smootherStep01()` in firmware.
- It applies symmetrically for accel and decel.

### Position ownership

Position is owned by the ESP32 now, not faked in the browser.

Status fields:

- `position_steps`
- `position_deg`
- `position_trusted`
- `position_reason`

Trust is invalidated on:

- boot
- disable
- estop
- power loss

### Zeroing

Per-axis actions:

- `SET ZERO`
- `GO ZERO`
- `UNTRUST`

Semantics:

- Yaw / Pitch / Belt `GO ZERO` = absolute zero
- Roll `GO ZERO` = shortest path to zero-equivalent

### Soft limits

Soft limits are enforced only when position is trusted.

Current design:

- Yaw: yes
- Pitch: yes
- Roll: no limits at all
- Belt: yes

Roll limit support was removed both in UI and firmware.

### Display behavior

- Yaw: signed angle
- Pitch: signed angle
- Roll: wrapped angle display
- Belt: steps

## Tumble Mode

### What exists now

Tumble mode is implemented and live for:

- Yaw
- Pitch
- Roll

It is not implemented for Belt.

### Where it lives

Tumble is owned by the ESP32, not the browser.

Firmware adds:

- per-axis tumble config:
  - `tumble_a`
  - `tumble_b`
  - `tumble_dwell_ms`
- per-axis tumble runtime:
  - `tumble_active`
  - `tumble_state`

Backend adds proxy routes:

- `/api/gimbal/tumble_start`
- `/api/gimbal/tumble_stop`

Frontend adds per-axis controls:

- `A`
- `B`
- `Dwell ms`
- `START`
- `STOP`

### Tumble rules

- Only Yaw / Pitch / Roll support tumble.
- Axis must be `enabled`.
- Position must be `trusted`.
- If soft limits exist and are trusted, endpoints must stay inside them.
- `A` and `B` cannot be identical.
- Start picks the nearer endpoint first, then bounces `A <-> B`.
- Stop kills tumble immediately for that axis.

### Tumble state machine

Firmware states:

- `off`
- `to_a`
- `dwell_a`
- `to_b`
- `dwell_b`

### Tumble is cleared/stopped by

- manual move
- manual move_deg
- `SET ZERO`
- `UNTRUST`
- `GO ZERO`
- motor limit changes
- disable
- stop
- stop_all
- estop
- power loss / power return handling

### Tumble defaults currently stored

For Yaw / Pitch / Roll:

- `A = -45`
- `B = 45`
- `Dwell = 500 ms`

### Current validation behavior

The Pi proxy now preserves ESP32 validation errors instead of flattening them into fake `502`s.

Example:

- starting tumble on a disabled axis returns `409 {"error":"motor not enabled","ok":false}`

That proxy fix is commit:

- `ad0aec3b` `Preserve gimbal proxy validation errors`

## Bugs Fixed Recently

### 1. Min/max textbox reset-on-blur bug

Symptom:

- user typed a different min/max
- on blur, polling reset it to the saved value before `APPLY`

Fix:

- added local draft state:
  - `gimbalLimitDrafts`
  - `gimbalEnsureLimitDraft`
  - `gimbalLimitDraft`
  - `gimbalClearLimitDraft`
- draft persists across blur
- draft is cleared only after successful `APPLY`

Commit:

- `7bb8d881` Preserve unsaved gimbal limit drafts

### 2. Roll limit bug

User requirement:

- roll should have no min/max degree limits at all

Fix:

- firmware:
  - `limits_supported=false` for Roll
  - roll moves are no longer checked against soft limits
  - `/status` reports roll limit fields as `null`
  - `/motor_limits` rejects Roll
- UI:
  - no Min/Max UI is rendered for Roll
  - direct Roll limit apply is blocked client-side too

Commit:

- `760d80df` Remove roll soft limits

### 3. Tumble mode implementation

Commit:

- `6c7f70a3` Add gimbal tumble mode

## Important Deployment Lessons

### Groundstation deploy

Good path:

1. Commit locally on the correct branch.
2. Push branch to GitHub if useful.
3. Push branch/commit to Pi repo over SSH remote `groundstation`.
4. On Pi:
   - `cd /opt/geodude-control`
   - `git merge --ff-only <commit-or-branch>`
   - `sudo systemctl restart wheel-control.service`
5. Verify:
   - service active
   - served `app.js` / routes reflect the change

Do not:

- manually copy UI files into `/opt`

### ESP32 compile

Working compile pattern:

```bash
rm -rf /Users/zeul/tmp/gimbal_controller_build /Users/zeul/tmp/gimbal_controller_sketch
mkdir -p /Users/zeul/tmp/gimbal_controller_sketch
cp firmware/esp32/gimbal_controller.ino /Users/zeul/tmp/gimbal_controller_sketch/gimbal_controller_sketch.ino
arduino-cli compile --fqbn esp32:esp32:esp32doit-devkit-v1 \
  --output-dir /Users/zeul/tmp/gimbal_controller_build \
  /Users/zeul/tmp/gimbal_controller_sketch
```

Gotcha:

- Arduino CLI requires the `.ino` filename to match the sketch folder name.

### ESP32 OTA upload

Mac direct OTA to `192.168.4.222` was flaky and often timed out after invitation.

Reliable path:

1. Copy these to the Pi:
   - built `.bin`
   - `espota.py`
2. Run OTA from the Pi:

```bash
python3 /tmp/espota.py -i 192.168.4.222 -f /tmp/gimbal_controller_sketch.ino.bin -r -d
```

Use:

- `/Users/zeul/Library/Arduino15/packages/esp32/hardware/esp32/3.3.8/tools/espota.py`

## Files Most Likely To Matter Next

- `firmware/esp32/gimbal_controller.ino`
- `groundstation/static/app.js`
- `groundstation/wheel_control.py`
- `groundstation/templates/index.html`
- maybe `groundstation/static/style.css` if UI changes are needed

## Remaining Work / Known Gaps

### Hardware validation

Code is in. The next honest step is hardware validation, not more code theater.

Need to verify in the real mechanism:

- tumble start/stop feel sane
- dwell timing is sane
- soft limits reject bad endpoints cleanly
- trusted/untrusted gating feels clear
- zeroing workflow is not annoying

### Mechanical bounds

Right now:

- Yaw / Pitch / Belt use user-set soft limits
- Roll has none

Hardcoded mechanical bounds were intentionally not finalized.

### Skipped-step truth

Still open-loop.

- ESP32 knows commanded steps
- it does not know if motor physically skipped

Trust model exists, but there is no encoder/homing truth.

### Branch cleanup

At some point the gimbal branch situation should be reconciled back into a sane mainline, but do not do that casually through the coordinated UI/backend files without following the protocol.

## Recommended Next-Agent Workflow

If Alloy is touching gimbal UI/backend files:

1. Start from `zeul/gimbal-tumble-rebased`, not `main`.
2. Check diff against:
   - `groundstation/static/app.js`
   - `groundstation/static/style.css`
   - `groundstation/templates/index.html`
   - `groundstation/wheel_control.py`
3. State:
   - branch
   - commit
   - touched files
   - replace vs merge on top of `ad0aec3b`
4. Avoid direct `/opt` edits.
5. Verify served assets and route behavior after deploy.

If Alloy is touching only ESP32 firmware:

- still start from `zeul/gimbal-tumble-rebased`, because that branch now contains the real deployed firmware state

## Local Dirty / Unrelated Files

These existed and I intentionally did not touch/revert them:

- `pcb/geodude-carrier/geodude-carrier.kicad_prl`
- `site/docs/DOCS_CLAUDE.md`
- `site/docs/electrical/geodude/carrier-pcb.md`
- `site/docs/electrical/geodude/index.md`
- `site/docs/electrical/index.md`
- `reaction-wheel-audit-prompt.md` (untracked)
- `ADAM_HANDOFF.md` (untracked)
- `ALICE_HANDOFF.md` (untracked)

Do not “clean these up” unless the user explicitly wants that.

## Quick Reality Check Commands

Groundstation Pi gimbal status:

```bash
ssh 192.168.50.2 'curl -s http://localhost:8080/api/gimbal/status'
```

Direct ESP32 status from Pi:

```bash
ssh 192.168.50.2 'curl -s http://192.168.4.222/status'
```

Check live repo head on Pi:

```bash
ssh 192.168.50.2 'cd /opt/geodude-control && git rev-parse --short HEAD'
```

Current expected answer:

- `ad0aec3b`

Test tumble validation path without moving hardware:

```bash
ssh 192.168.50.2 'curl -s -o /tmp/tumble_test.out -w "%{http_code}\n" -X POST \
  -H "Content-Type: application/json" \
  -d "{\"driver\":\"Yaw\",\"a\":-10,\"b\":10,\"dwell_ms\":500}" \
  http://localhost:8080/api/gimbal/tumble_start && echo --- && cat /tmp/tumble_test.out'
```

Current expected answer when Yaw is disabled:

- HTTP `409`
- body `{"error":"motor not enabled","ok":false}`

## Bottom Line

If Alloy needs one sentence:

Start from `zeul/gimbal-tumble-rebased` at `ad0aec3b`, treat that as the current gimbal deploy truth, do not use `main`, do not reintroduce roll limits, and do not touch `/opt` by hand.
