# Alloy Handoff

Last updated: 2026-04-22
Prepared for: Alloy
Scope: gimbal controls only

## TL;DR

- Current working gimbal source line is `zeul/gimbal-limit-draft-fix-pi` / local `pi-main` at `760d80df`.
- Live groundstation Pi `/opt/geodude-control` is at `760d80df`.
- Live ESP32 gimbal firmware was recompiled and OTA flashed from that same source line.
- `origin/main` is not the current gimbal/UI truth. Do not deploy UI/backend gimbal files from `main` without reconcile.
- Roll has no software limits now.
- Min/max textbox draft stomping is fixed.
- S-curve ramp is live.
- All positions are currently untrusted after the ESP32 reboot from flashing.

## User Intent / Product Rules

- Work on gimbal controls only unless user explicitly says otherwise.
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

## Network / Runtime Architecture

- Mac dev repo: `/Users/zeul/GIT/geodude-control`
- Groundstation Pi: `192.168.50.2`
- Groundstation live app: `http://192.168.50.2:8080`
- Groundstation live repo: `/opt/geodude-control`
- ESP32 gimbal controller: `192.168.4.222`
- ESP32 status endpoint: `http://192.168.4.222/status`

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

## Standing Coordination Rules For UI Files

These were explicitly agreed and should be treated as standing protocol for:

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

Additional constraints I added:

- No live-only hotfixes in those four files.
- Pre-deploy diff on exactly those four files.
- Post-deploy verify served assets and route behavior, not just files on disk.
- Explicitly say whether a deploy is full replace or merge on top of current deployed source.

## Branch / Source-Of-Truth Reality

Current local branches of interest:

- `zeul/gimbal-limit-draft-fix-pi` -> `760d80df`
- `pi-main` -> `760d80df`
- `main` -> `308e4f6d`

Important reality:

- `main` diverged badly from the reconciled frontend line.
- `origin/main` currently points to `27effd46`, which is not the latest gimbal deployment source.
- The current gimbal/UI deployment line is `zeul/gimbal-limit-draft-fix-pi` / `pi-main`.
- That line descended from the reconciled frontend merge:
  - `b54226b9`
  - then `b4092c62`
  - then later frontend/Pi reconcile commits
  - then my two latest commits on top:
    - `7bb8d881` Preserve unsaved gimbal limit drafts
    - `760d80df` Remove roll soft limits

Current useful refs:

- local branch: `zeul/gimbal-limit-draft-fix-pi`
- remote GitHub branch: `origin/zeul/gimbal-limit-draft-fix-pi`
- Pi branch: `groundstation/zeul/gimbal-limit-draft-fix-pi`
- Pi live `main`: `760d80df`

Do not assume `origin/main` matches deployed gimbal behavior.

## Current Live State

Groundstation Pi:

- repo HEAD: `760d80df`
- service: `wheel-control.service` active
- served app.js includes:
  - `gimbalLimitDrafts`
  - `gimbalDriverSupportsLimits`
  - roll limit suppression logic

ESP32 live status after latest flash:

- Yaw:
  - `limits_supported=true`
  - `soft_limit_min=-90.0`
  - `soft_limit_max=180.0`
  - `go_zero_mode=absolute`
  - `display_wrap=false`
- Pitch:
  - `limits_supported=true`
  - `soft_limit_min=-80.0`
  - `soft_limit_max=260.0`
  - `go_zero_mode=absolute`
  - `display_wrap=false`
- Roll:
  - `limits_supported=false`
  - `soft_limit_min=null`
  - `soft_limit_max=null`
  - `hard_limit_min=null`
  - `hard_limit_max=null`
  - `go_zero_mode=shortest_path`
  - `display_wrap=true`
- Belt:
  - `limits_supported=true`
  - `soft_limit_min=0`
  - `soft_limit_max=40000`
  - `go_zero_mode=absolute`
  - `display_wrap=false`

Important live side effect:

- ESP32 rebooted during OTA.
- All axes currently have untrusted position state (`position_reason=boot`).
- User must re-zero as needed.

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

- Ramp is now S-curve-ish via `smootherStep01()` in firmware.
- It applies symmetrically for accel and decel.
- This replaced the earlier linear ramp.

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

- Yaw/Pitch/Belt `GO ZERO` = absolute zero
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

## Bugs Fixed Recently

### 1. Min/max textbox reset-on-blur bug

Symptom:

- user typed a different min/max
- on blur, polling reset it to the saved value before `APPLY`

Root cause:

- `app.js` poll loop overwrote non-focused limit inputs from `drv.soft_limit_min/max`

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
  - added `driverSupportsSoftLimits(d)`
  - returns `false` for Roll
  - roll moves are no longer checked against soft limits
  - `/status` reports roll limit fields as `null`
  - `/motor_limits` rejects Roll
- UI:
  - added `gimbalDriverSupportsLimits()`
  - no Min/Max UI is rendered for Roll
  - direct Roll limit apply is blocked client-side too

Commit:

- `760d80df` Remove roll soft limits

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

Reliable path was:

1. Copy these to the Pi:
   - built `.bin`
   - `espota.py`
2. Run OTA from the Pi:

```bash
python3 /tmp/espota.py -i 192.168.4.222 -f /tmp/gimbal_controller_sketch.ino.bin -r -d
```

That path succeeded cleanly.

Use:

- `/Users/zeul/Library/Arduino15/packages/esp32/hardware/esp32/3.3.8/tools/espota.py`

## Files Most Likely To Matter Next

- `firmware/esp32/gimbal_controller.ino`
- `groundstation/static/app.js`
- `groundstation/wheel_control.py`
- `groundstation/templates/index.html`
- maybe `groundstation/static/style.css` if UI changes are needed

## Remaining Work / Known Gaps

### Tumble mode

Not implemented yet.

Desired direction:

1. Keep it on ESP32, not browser.
2. Use trusted zero / signed position model.
3. Use per-axis A/B endpoints and dwell.
4. Gate it on trusted position and soft limits.

### Mechanical bounds

Right now:

- Yaw/Pitch/Belt use user-set soft limits
- Roll has none

Hardcoded mechanical bounds were intentionally not finalized.
User wanted GUI-set limits first, then maybe hardcode later.

### Skipped-step truth

Still open-loop.

- ESP32 knows commanded steps
- it does not know if motor physically skipped

Trust model exists, but there is no encoder/homing truth.

### Branch cleanup

Current deployed gimbal line is on `zeul/gimbal-limit-draft-fix-pi` / `pi-main`.

At some point this should be reconciled back into a sane mainline, but do not do that casually through the four coordinated UI files without following the protocol.

## Recommended Next-Agent Workflow

If Alloy is touching gimbal UI/backend files:

1. Start from `zeul/gimbal-limit-draft-fix-pi` or `pi-main`, not `main`.
2. Check diff against:
   - `groundstation/static/app.js`
   - `groundstation/static/style.css`
   - `groundstation/templates/index.html`
   - `groundstation/wheel_control.py`
3. State:
   - branch
   - commit
   - touched files
   - replace vs merge on top of `760d80df`
4. Avoid direct `/opt` edits.
5. Verify served assets after deploy.

If Alloy is touching only ESP32 firmware:

- still start from `zeul/gimbal-limit-draft-fix-pi`, because that branch now contains the real deployed firmware state

## Local Dirty / Unrelated Files

These existed and I intentionally did not touch/revert them:

- `pcb/geodude-carrier/geodude-carrier.kicad_prl`
- `site/docs/DOCS_CLAUDE.md`
- `site/docs/electrical/geodude/carrier-pcb.md`
- `site/docs/electrical/geodude/index.md`
- `site/docs/electrical/index.md`
- `reaction-wheel-audit-prompt.md` (untracked)
- `ADAM_HANDOFF.md` (untracked)

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

- `760d80df`

## Bottom Line

If Alloy needs one sentence:

Start from `zeul/gimbal-limit-draft-fix-pi` / `pi-main` at `760d80df`, do not use `main` as gimbal/UI deploy truth, and do not reintroduce roll limits or direct `/opt` file-copy deploys.
