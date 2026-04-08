# GEO-DUDe Control — Project Instructions

## Repo Structure

```
groundstation/    — Flask web UI (runs on groundstation Pi, port 8080)
geodude/          — sensor_server.py + attitude_controller.py (runs on GEO-DUDe Pi)
gimbal/           — gimbal_controller.ino (runs on ESP32)
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

### Groundstation (editing directly on Pi)
```bash
# Edit files in /opt/geodude-control/, then:
sudo systemctl restart wheel-control.service
```

### GEO-DUDe Pi (from groundstation)
```bash
scp /opt/geodude-control/geodude/sensor_server.py zeul@192.168.4.166:/home/zeul/sensor_server.py
ssh zeul@192.168.4.166 'sudo systemctl restart sensor-server.service'
```

### ESP32 Gimbal (compile on zmac, flash via groundstation)
```bash
# On zmac:
cp gimbal/gimbal_controller.ino ~/tmp/tmc2209_read/tmc2209_read.ino
arduino-cli compile --fqbn esp32:esp32:esp32doit-devkit-v1 --output-dir ~/tmp/tmc2209_read/build ~/tmp/tmc2209_read/
scp ~/tmp/tmc2209_read/build/tmc2209_read.ino.bin zeul@192.168.50.2:/tmp/
ssh zeul@192.168.50.2 'python3 /tmp/espota.py -i 192.168.4.222 -p 3232 -f /tmp/tmc2209_read.ino.bin'
```

Note: zmac needs `arduino-cli` (homebrew) with esp32 board package and TMCStepper library. `espota.py` is at `/Users/zeul/Library/Arduino15/packages/esp32/hardware/esp32/3.3.7/tools/espota.py` (copy to groundstation `/tmp/` if missing).

### GitHub
Pushes to GitHub happen from zmac periodically. The Pi will pull from GitHub directly once it gets internet access.

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
- **AGENT_ONBOARDING.md** references file paths at repo root — needs updating to reflect `groundstation/`, `geodude/`, `gimbal/` subdirectories.
- **Pico pin assignments — two hardware versions:** The perfboard prototype and the carrier PCB use different Pico GPIO pins for FOC signals (IN1/IN2/IN3/EN). Serial (GP0/1) and I2C (GP4/5) are the same on both. PCB version is documented in `pcb/CLAUDE.md` and `site/docs/electrical/geodude/carrier-pcb.md`. Perfboard version TBD — needs confirming from physical wiring.

## MACE Reaction Wheel (SimpleFOC / Pi Pico)

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
- Source: `nucleo/nucleo-simplefoc.ino` (in repo), compiled on zmac
- Framework: Arduino (STM32duino core) + SimpleFOC library
- Compile: `arduino-cli compile --fqbn "STMicroelectronics:stm32:Nucleo_64:pnum=NUCLEO_F446RE,upload_method=swdMethod"`
- Two modes: velocity (M0, MACE manual) and torque (M1, attitude control)
- Motor disabled on boot, initFOC skippable (send G to run when motor connected)
- 50Hz JSON telemetry stream over ST-LINK virtual COM
- Serial commands: T (velocity), U (voltage), V (voltage limit), P/I/W (PID), L (velocity limit), A (output ramp), F (LPF), M0/M1 (mode), G (initFOC), C (calibrate+enable), D (disable), E (enable)

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
  backend/     # future shared hub service on groundstation, port 8070, main only
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

The groundstation hub will eventually be the only process polling GEO-DUDe. Prod and dev frontends should all read from that hub so multiple tabs/computers/worktrees share one telemetry pipeline and one control lock.

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
git merge zeul-dev   # or mizi-dev
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
