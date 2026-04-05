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

The reaction wheel uses a Pi Pico running SimpleFOC firmware, connected to the GEO-DUDe Pi via USB serial (`/dev/ttyACM0`, 115200 baud). This replaces the old ESC + PCA9685 PWM system.

### Hardware
- **Motor:** 2804 hollow shaft BLDC gimbal motor (7 pole pairs)
- **Driver:** SimpleFOC Mini v1.0 (DRV8313)
- **Encoder:** AS5600 magnetic encoder (I2C, on motor shaft)
- **Controller:** Raspberry Pi Pico (RP2040)
- **Connection:** Pico USB to GEO-DUDe Pi USB port

### Pico GPIO (current perfboard wiring)
- GP10 = IN1 (PWM)
- GP11 = IN2 (PWM)
- GP12 = IN3 (PWM)
- GP14 = EN (enable)
- GP4 = SDA (I2C, for AS5600 encoder)
- GP5 = SCL (I2C, for AS5600 encoder)
- GP6 = Bootloader entry (emergency, active low)

### Firmware
- Source: `~/tmp/pico-simplefoc/pico-simplefoc.ino` (on zmac)
- Framework: Arduino (earlephilhower rp2040 core) + SimpleFOC library
- Mode: Open-loop velocity (no encoder connected yet)
- Serial protocol: SimpleFOC Commander (`T<vel>\n` = set velocity, `T\n` = read)
- Compile: `arduino-cli compile --fqbn rp2040:rp2040:rpipico`

### Flashing the Pico (no button needed)
```bash
# From GEO-DUDe Pi: trigger BOOTSEL via 1200 baud touch
python3 -c "import serial; s=serial.Serial('/dev/ttyACM0',1200); s.close()"
# Wait 3 seconds, then mount and copy UF2
sudo mkdir -p /mnt/pico && sudo mount /dev/sda1 /mnt/pico
sudo cp firmware.uf2 /mnt/pico/ && sudo sync && sudo umount /mnt/pico
```

### API (sensor_server.py on GEO-DUDe)
- `POST /simplefoc` with `{"velocity": 5.0}` or `{"command": "T5"}` - sends command to Pico
- Legacy `POST /motor` still works but translates PWM to velocity

### Ground station UI
- Velocity slider (-20 to +20 rad/s)
- Quick preset buttons
- Enable/disable toggle (instant, no ESC arming)
- Ramp rate control (rad/s/s)

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
