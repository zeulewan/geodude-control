# GEO-DUDe Control — Project Instructions

## Repo Structure

```
groundstation/
  frontend/       — Flask browser UI (prod 8080, dev worktree ports 8081/8082)
  backend/        — future shared groundstation hub placeholder (not running yet)
geodude/
  backend/        — GEO-DUDe Pi hardware API/service code
firmware/
  nucleo/         — STM32 Nucleo / SimpleFOC firmware
  esp32/          — ESP32 gimbal firmware
pcb/              — KiCad carrier PCB design
site/             — Documentation site (Zensical/MkDocs)
  ├── docs/       — Markdown source
  └── zensical.toml
```

## Live Deployment

The repo is cloned on the groundstation Pi at `/opt/geodude-control/`. The `main` branch is the live deployment. The systemd service runs directly from there:

```
ExecStart=/usr/bin/python3 /opt/geodude-control/groundstation/wheel_control.py
WorkingDirectory=/opt/geodude-control/groundstation
```

`groundstation/wheel_control.py` is a compatibility wrapper. The actual UI app now lives at `groundstation/frontend/app.py`.

Dev frontends are served from worktrees, not from `/opt`:

| URL | Checkout | Branch | Purpose |
|-----|----------|--------|---------|
| `http://192.168.50.2:8080` | `/opt/geodude-control` | `main` | prod/main UI |
| `http://192.168.50.2:8081` | `/home/zeul/geodude-dev` | `zeul-dev` | zeul frontend dev |
| `http://192.168.50.2:8082` | `/home/mizi/geodude-dev` | `mizi-dev` | mizi frontend dev |

Dev worktrees should run **frontend only** via `groundstation/run_local_dev.py` / `groundstation/frontend/run_local_dev.py`. They should not run their own hardware-owning backend services.

Persistent data files (not in git, created at runtime):
- `groundstation/servo_neutral.json` — saved neutral positions
- `groundstation/servo_positions.json` — last-known servo positions

## Users

Two user accounts on the groundstation Pi, both in the `geodude` group with write access to `/opt/geodude-control/`:

| User | Role |
|------|------|
| `zeul` | Project lead |
| `mizi` | Team member (onboarding at `/home/mizi/ONBOARDING.md`) |

## Deployment

The groundstation Pi has no internet access. Updates are pushed from zmac via git bundle.

### Groundstation (from zmac)
```bash
# Push commits to Pi
git bundle create /tmp/geodude.bundle main
scp /tmp/geodude.bundle zeul@192.168.50.2:/tmp/
ssh zeul@192.168.50.2 'cd /opt/geodude-control && git pull /tmp/geodude.bundle main && sudo systemctl restart wheel-control.service'
```

### Groundstation Dev Frontends
```bash
# zeul-dev
cd /home/zeul/geodude-dev/groundstation
WHEEL_CONTROL_PORT=8081 python3 run_local_dev.py

# mizi-dev
cd /home/mizi/geodude-dev/groundstation
WHEEL_CONTROL_PORT=8082 python3 run_local_dev.py
```

### GEO-DUDe Pi (from groundstation)
```bash
scp /opt/geodude-control/geodude/backend/sensor_server.py zeul@192.168.4.166:/home/zeul/sensor_server.py
ssh zeul@192.168.4.166 'sudo systemctl restart sensor-server.service'
```

### ESP32 Gimbal (compile on zmac, flash via groundstation)

The ESP32 gimbal controller at `192.168.4.222` takes firmware updates over WiFi via ArduinoOTA on UDP port 3232.

**Normal flash workflow:**
```bash
# On zmac:
cp firmware/esp32/gimbal_controller.ino ~/tmp/tmc2209_read/tmc2209_read.ino
arduino-cli compile --fqbn esp32:esp32:esp32doit-devkit-v1 --output-dir ~/tmp/tmc2209_read/build ~/tmp/tmc2209_read/
scp ~/tmp/tmc2209_read/build/tmc2209_read.ino.bin zeul@192.168.50.2:/tmp/
ssh zeul@192.168.50.2 'python3 /tmp/espota.py -i 192.168.4.222 -p 3232 -f /tmp/tmc2209_read.ino.bin'
```

Notes:
- Arduino CLI path on zmac: current version is `esp32:esp32@3.3.8`, so `espota.py` lives at `/Users/zeul/Library/Arduino15/packages/esp32/hardware/esp32/3.3.8/tools/espota.py` (adjust for your installed version; copy to groundstation `/tmp/` if missing).
- zmac needs `arduino-cli` (homebrew) with the esp32 core and TMCStepper library installed.

**If OTA times out with "No response from the ESP":**

The firmware now auto-recovers OTA when WiFi reconnects (`WiFi.onEvent` handler re-runs `ArduinoOTA.begin`). If it still gets stuck, reboot it via HTTP:
```bash
ssh zeul@192.168.50.2 'curl -sS -X POST http://192.168.4.222/reboot'
# wait ~5s for boot, then retry flash
```

Only power-cycle the gimbal physically if the ESP32 is wedged beyond HTTP reach (e.g. crashed into a busy loop). Older firmware (before the WiFi-event fix) had a latent bug where a groundstation WiFi-AP reboot would orphan the OTA UDP socket until the ESP32 itself rebooted.

### GitHub
Pushes to GitHub happen from zmac periodically. Keep it simple for now: bundle/scp between the groundstation and zmac, then push to GitHub from zmac. The Pi network currently has no internet.

## Servo Startup & Safety

- **1500us (center/middle) is DANGEROUS** — fully extends arms outward. Never send 1500us as a default.
- **Neutral positions** are the safe home. Stored server-side in `servo_neutral.json` on the groundstation Pi.
- **Servo positions** tracked server-side in `servo_positions.json`, persisted to disk (debounced 1s). Survives reboots.
- **On groundstation boot**: restore loop waits for GEO-DUDe, then sends last-known positions to resume where servos were before shutdown.
- **STARTUP button**: sends neutral positions directly (no ramp) when user knows arms may have been moved manually.
- **sensor_server.py does NOT call pca_all_off() on boot** — lets groundstation handle position restore.
- **Multi-client**: multiple browsers can connect. Camera uses fan-out (single rpicam-vid reader, shared frame buffer). Servo sliders sync from server every 500ms.

## Known Code Issues (TODO)

- **ESP32 OTA filename:** The Mac compile path still uses `tmc2209_read/` as the sketch folder name. The ESP32 doesn't care, but the Mac-side paths in the deploy script reference this old name.
- **Docs site CI:** The GitHub Actions workflow (`.github/workflows/docs.yml`) needs updating — it was written for the old standalone repo structure. The docs source is now at `site/docs/` and config at `site/zensical.toml`.
- **AGENT_ONBOARDING.md** references file paths at repo root — needs updating to reflect `groundstation/`, `geodude/`, and `firmware/` subdirectories.
- **Pico pin assignments — two hardware versions:** The perfboard prototype and the carrier PCB use different Pico GPIO pins for FOC signals (IN1/IN2/IN3/EN). Serial (GP0/1) and I2C (GP4/5) are the same on both. PCB version is documented in `pcb/CLAUDE.md` and `site/docs/electrical/geodude/carrier-pcb.md`. Perfboard version TBD — needs confirming from physical wiring.

## MACE Reaction Wheel (SimpleFOC / STM32 Nucleo)

The reaction wheel uses an STM32 Nucleo F446RE with SimpleFOC Shield V2.0.4, connected to the GEO-DUDe Pi via USB serial (`/dev/ttyACM0`, 115200 baud).

### Hardware (Current - Nucleo + SimpleFOC Shield)
- **Controller:** STM32 Nucleo F446RE (ARM Cortex-M4, 180MHz, 512KB flash, 128KB SRAM)
- **Driver:** SimpleFOC Shield V2.0.4 (clone) - 3x IR2104 half-bridge, 2x INA240 current sensors, 12-35V input
- **Motor:** 4015 BLDC with MT6701 encoder (hollow shaft, robot joint motor)
- **Encoder:** MT6701 magnetic encoder (ABZ mode, 1024 PPR, on motor shaft)
- **IMU:** ICM20948 9DoF (I2C, address 0x69)
- **Connection:** Nucleo USB (ST-LINK virtual COM) to GEO-DUDe Pi
- **Flashing:** `st-flash write firmware.bin 0x08000000` via ST-LINK/V2.1 onboard
- **Power:** Nucleo powered from Pi USB (5V), Shield powered from external PSU (12-35V)

### Previous Hardware (Pi Pico + DRV8313) - Retired
See `site/docs/electrical/geodude/mace-development-log.md` for full Pico development history.

### Firmware
- Source: `firmware/nucleo/nucleo-simplefoc.ino` (in repo), compiled on zmac
- Framework: Arduino (STM32duino core) + SimpleFOC library
- Compile: `arduino-cli compile --fqbn "STMicroelectronics:stm32:Nucleo_64:pnum=NUCLEO_F446RE,upload_method=swdMethod"`
- Two modes: velocity (M0, MACE manual) and torque (M1, attitude control)
- Motor disabled on boot, initFOC skippable (send G to run when motor connected)
- 50Hz JSON telemetry stream over ST-LINK virtual COM
- Serial commands: T (velocity), U (voltage), V (voltage limit), P/I/W (PID), L (velocity limit), A (output ramp), F (LPF), M0/M1 (mode), G (initFOC), C (calibrate+enable), D (disable), E (enable)

Important bring-up notes from the March 2026 STM32/shield session:
- Board is silkscreened "FOC Arduino v1.1" but behaves like a SimpleFOC Shield V2.0.4-compatible clone: IR2104 gate drivers, 6 NMOS, 2x INA240 current sensors, 12-35V bus.
- IR2104 jumper must be on the `VCC > 20V` / regulated 16V side for 24V bus power.
- Working shield control pins: `BLDCDriver3PWM(9, 5, 6, 8)` = PWM A/B/C plus enable.
- Motor listing says 22 poles = 11 pole pairs; use `BLDCMotor(11)`. Do not use 14 or 22 pole pairs.
- Phase-to-phase motor resistance measured about 5 ohms for all three pairs, and pairwise phase tests were balanced after shortening motor phase leads.
- Current sense is two-shunt A/B only. Use A/B readings and infer C as `-(A+B)`; do not treat missing direct phase-C current as a dead winding.
- Open-loop was smooth only when firmware loop was minimal. Heavy JSON/debug/current-sense/web serial work in the fast loop caused obvious knocking/jitter.
- Correct fast-loop pattern is `motor.loopFOC(); motor.move(target);` with no blocking serial prints during motion. For tuning, log to RAM during runs and dump after `RUN_DONE`.
- Velocity closed-loop began working after runtime PID tuning (`P≈0.2`, `I≈1.0`, `LPF≈0.05`) and later higher authority tests. Treat these as starting points, not final flight tuning.
- Encoder is ABI on D2/D3. Verify encoder PPR by hand-rotating one mechanical revolution before final closed-loop firmware; old sketches/configs disagree (`800` vs `1024`).

### Flashing the Nucleo
```bash
# From GEO-DUDe Pi:
st-flash write /tmp/nucleo.bin 0x08000000
st-flash reset
```

### Attitude Controller (`geodude/attitude_controller.py`)
- Runs on GEO-DUDe Pi, port 5001
- Single PID: angle error (deg) -> voltage command (1.5V-12V)
- D term uses gyro rate (derivative on measurement, not error)
- Auto-calibrates gyro bias on enable (2s stationary)
- Switches Nucleo to torque mode (M1) on enable, disables motor (D) on disable
- Mutual exclusion with MACE manual controls

### API (sensor_server.py on GEO-DUDe)
- `GET /simplefoc/status` - cached telemetry from Nucleo serial stream
- `POST /simplefoc` with `{"command": "T5"}` or `{"velocity": 5.0}` - sends command
- `GET /sensors` - sensor data (accel, gyro, encoder, rpm)

## Gimbal (ESP32 + TMC2209)

- 4 stepper drivers: Yaw, Pitch, Roll, Belt
- Constant-speed stepping (no S-curve/jerk)
- Status endpoint skips slow TMC UART reads while motors are stepping to avoid stutter
- Speed controlled via `stepDelay` (us between steps)

## Safety

**NEVER send motor, PWM, or actuator commands to hardware without explicit user permission.** Read-only debugging only.

## Network Architecture

The groundstation Pi has **no internet access**. It connects to zmac via USB Ethernet and hosts its own WiFi hotspot (`groundstation` / `Temp1234`) for the GEO-DUDe Pi and ESP32.

```
Internet
  |
zmac (MacBook, Toronto) — 100.117.222.41 (Tailscale)
  |                        192.168.50.1 (USB Ethernet to groundstation)
  |
  USB Ethernet
  |
Groundstation Pi — 192.168.50.2 (USB Ethernet from zmac)
  |                 NO INTERNET — isolated local network
  |                 Runs: wheel_control.py (Flask web UI, port 8080)
  |                 Repo: /opt/geodude-control (main branch = live)
  |                 WiFi hotspot: "groundstation"
  |
  WiFi (groundstation hotspot)
  |
  +— GEO-DUDe Pi — 192.168.4.166
  |    Runs: sensor_server.py (sensors, PCA9685, camera)
  |    Runs: attitude_controller.py (PID control)
  |
  +— ESP32 (gimbal) — 192.168.4.222
       Runs: gimbal_controller.ino (TMC2209 stepper control)
       OTA updates via espota.py from groundstation
```

| Device | IP | Role |
|--------|-----|------|
| zmac (MacBook) | 100.117.222.41 / 192.168.50.1 | Development, ESP32 compilation, GitHub push |
| Groundstation Pi | 192.168.50.2 | Web UI server, command relay to GEO-DUDe/ESP32 |
| GEO-DUDe Pi | 192.168.4.166 | Sensor reading, servo/motor control, camera |
| ESP32 (gimbal) | 192.168.4.222 | Stepper motor control (4x TMC2209) |

## Services (all auto-start on boot)

| Service | Device | Unit | Runs From |
|---------|--------|------|-----------|
| Web UI | Groundstation Pi | `wheel-control.service` | `/opt/geodude-control/groundstation/wheel_control.py` |
| Sensor/Motor API | GEO-DUDe Pi | `sensor-server.service` | `/home/zeul/sensor_server.py` |
| Attitude Controller | GEO-DUDe Pi | `attitude-controller.service` | `/home/zeul/attitude_controller.py` |
| Gimbal | ESP32 | firmware in flash | boots automatically on power |

## Repo Layout Plan

One repo owns all software and firmware, split first by the machine it runs on:

```text
groundstation/
  backend/     # future shared hub service on groundstation; not running yet
  frontend/    # browser UI on groundstation, prod 8080 and dev worktree ports

geodude/
  backend/     # GEO-DUDe Pi hardware API, port 5000

firmware/
  nucleo/      # STM32 Nucleo / SimpleFOC firmware
  esp32/       # ESP32 gimbal firmware
```

Compatibility wrappers remain at the old service paths during the refactor:

```text
groundstation/wheel_control.py
groundstation/run_local_dev.py
geodude/sensor_server.py
geodude/attitude_controller.py
geodude/pca9685_test.py
```

The groundstation hub is a future step, not needed/running right now. When built, it should be the only process polling GEO-DUDe so prod/dev frontends share one telemetry pipeline and one control lock.

## Frontend Split

The groundstation UI source is split under `groundstation/frontend/templates`:

```text
index.html                    # shell/header/tabs/includes
partials/dashboard.html       # Dashboard tab
partials/mission.html         # Mission Simulation panel
partials/competition.html     # stub for future standalone Competition panel
```

Important: the old MACE Competition tab reused the Mission panel DOM and JS mode instead of having a separate page. `competition.html` is intentionally a stub for now so we do not duplicate mission element IDs and break Mizi's mission UI. Do an ID-safe split later if the Competition page needs its own independent DOM.

Dashboard replaces the old "Manual Testing" label. The Dashboard no longer includes the old ML Vision, Attitude Control, or MACE Reaction Wheel cards. Mizi's mission, competition workflow, arm workspace, gimbal, servo, and controller visuals should be preserved.

## Git Workflow

Two developers: **zeul** (uses zmac) and **mizi** (uses his own Mac). Both SSH into the groundstation Pi to develop.

### Worktree Setup

`/opt/geodude-control/` is the **deployment** on `main`. Nobody edits it directly. Each developer has their own worktree:

| Developer | Worktree | Branch |
|-----------|----------|--------|
| zeul | `/home/zeul/geodude-dev` | `zeul-dev` |
| mizi | `/home/mizi/geodude-dev` | `mizi-dev` |
| (deploy) | `/opt/geodude-control` | `main` |

### Development Flow
```bash
# SSH into the Pi
ssh zeul@192.168.50.2   # or mizi@192.168.50.2

# Work in your worktree
cd ~/geodude-dev
# edit files, test, etc.
git add -A && git commit -m "description of change"

# When ready to deploy: merge to main
cd /opt/geodude-control
git merge --no-ff zeul-dev   # or mizi-dev
sudo systemctl restart wheel-control.service
```

### Main Protection Rule

Do not commit directly on `main`. Work on a branch/worktree, then merge into main with an explicit merge commit:

```bash
git switch -c zeul/some-change
git add -A && git commit -m "Do the thing"
git switch main
git merge --no-ff zeul/some-change
```

The repo has a local pre-commit hook at `scripts/git-hooks/pre-commit` that blocks normal direct commits on `main` while allowing merge commits. Install it into `.git/hooks/pre-commit` in any checkout used for deployment.

### Dev Frontend Serving

The dev branch ports are reserved by convention. They are not systemd services yet; start them manually from each worktree when needed:

```bash
# zeul-dev frontend
cd /home/zeul/geodude-dev/groundstation
WHEEL_CONTROL_PORT=8081 python3 run_local_dev.py

# mizi-dev frontend
cd /home/mizi/geodude-dev/groundstation
WHEEL_CONTROL_PORT=8082 python3 run_local_dev.py
```

These dev servers should serve frontend work only. Do not start duplicate hardware backends from dev worktrees; keep `sensor-server.service`, `attitude-controller.service`, and the live hardware-owning services under main/live control.

Mizi's pre-refactor uncommitted frontend work was reconciled into main and then his `mizi-dev` worktree was fast-forwarded to `cc9a7ee4`. His old local edits were preserved as a stash named `mizi-pre-main-sync-20260326-110335` in `/home/mizi/geodude-dev`.

### Syncing with zmac / GitHub (Pi has no internet)
```bash
# Push Pi commits to zmac:
ssh zeul@192.168.50.2 'cd /opt/geodude-control && git bundle create /tmp/geodude.bundle --all'
scp zeul@192.168.50.2:/tmp/geodude.bundle /tmp/
git pull /tmp/geodude.bundle main

# Push zmac commits to Pi:
git bundle create /tmp/geodude.bundle main
scp /tmp/geodude.bundle zeul@192.168.50.2:/tmp/
ssh zeul@192.168.50.2 'cd /opt/geodude-control && git pull /tmp/geodude.bundle main'

# Push to GitHub (from zmac only):
git push origin main
```
