# GEO-DUDe Control — Project Instructions

## Repo Structure

```
groundstation/    — Flask web UI (runs on groundstation Pi, port 8080)
geodude/          — sensor_server.py (runs on GEO-DUDe Pi)
pico/             — pico-simplefoc.ino (compiled on zmac, flashed to Pico)
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

The reaction wheel uses a Pi Pico running SimpleFOC firmware, connected to the GEO-DUDe Pi via USB serial (`/dev/pico`, 115200 baud). Replaces the old ESC + PCA9685 PWM system.

### Hardware
- **Motor:** 2804 hollow shaft BLDC gimbal outrunner (7 pole pairs, 220 KV, 2.3 ohm phase resistance, 0.03 Nm torque)
- **Driver:** SimpleFOC Mini v1.0 (DRV8313, 2.5A continuous, 3.5A OCP)
- **Encoder:** AS5600 magnetic encoder (analog output to GP26 for FOC, I2C on GP2/GP3 for IMU)
- **IMU:** ICM20948 9DoF (I2C1 on GP2/GP3, address 0x69)
- **Controller:** Raspberry Pi Pico (RP2040)
- **Connection:** Pico USB to GEO-DUDe Pi USB port (data), Pico VSYS powered from 5V buck (not USB power)

### Pico GPIO (current perfboard wiring)
- GP10 = IN1 (PWM phase A)
- GP11 = IN2 (PWM phase B)
- GP12 = IN3 (PWM phase C)
- GP14 = EN (driver enable)
- GP19 = nRT (DRV8313 reset, active low)
- GP20 = nSP (DRV8313 sleep, active low)
- GP21 = nFT (DRV8313 fault output, active low = fault)
- GP26 = AS5600 analog output (ADC0, for FOC encoder)
- GP2 = SDA (I2C1, for IMU)
- GP3 = SCL (I2C1, for IMU)
- GP6 = Bootloader entry (emergency, active low)
- GP27 (Pi side) = Pico RUN pin (hard reset from Pi)

### Important hardware notes
- **Pico must be powered via VSYS (pin 39) from 5V buck**, not USB. USB is data only. The Pi's USB polyfuse drops voltage too much.
- **Sensors must be powered from Pico 3.3V (pin 36)**, not Pi 3.3V. Avoids I2C timing race at boot.
- **I2C1 (Wire1)** for GP2/GP3. Wire (I2C0) doesn't work on those pins.
- **AS5600 analog output** used for FOC (fast reads). I2C was too slow, limited motor to ~800 RPM.
- **udev rule** on GEO-DUDe Pi creates `/dev/pico` symlink (persistent across reconnects):
  `SUBSYSTEM=="tty", ATTRS{idVendor}=="2e8a", ATTRS{idProduct}=="000a", SYMLINK+="pico"`
- **1000uF cap** on Pi 5V rail to prevent undervoltage on current spikes.
- **Never disconnect motor while 12V is on** - voltage spike destroys driver.

### Firmware
- Source: `pico/pico-simplefoc.ino` (in repo), compiled on zmac
- Framework: Arduino (earlephilhower rp2040 core) + SimpleFOC library
- Mode: Closed-loop velocity with analog encoder
- Streams JSON telemetry at 50Hz over USB serial (sensors, motor state, tuning params)
- Serial commands: T (velocity), V (voltage limit), P/I/W (PID), L (velocity limit), A (output ramp), F (LPF), C (calibrate), D (disable), E (enable), R (reset fault)
- `initFOC()` runs at boot (motor must be connected and free to move)
- `driver.voltage_limit = 12` (hardware cap), `motor.voltage_limit = 2` (startup default, adjustable via GUI)

### Flashing the Pico
```bash
# DTR reboot to BOOTSEL (from GEO-DUDe Pi):
python3 -c "import serial; s=serial.Serial('/dev/pico',1200); s.dtr=True; import time; time.sleep(0.3); s.dtr=False; s.close()"
# Wait for RP2 Boot in lsusb, then:
sudo mkdir -p /mnt/pico && sudo mount /dev/sda1 /mnt/pico
sudo cp simplefoc.uf2 /mnt/pico/ && sudo sync && sudo umount /mnt/pico
```
Hard reset via RUN pin: Pi GPIO 27 low for 200ms then high.

### Telemetry stream format (JSON, 50Hz)
```json
{"t":0.0,"vsys":5.17,"enc":131.7,"ax":0.0,"ay":0.06,"az":1.0,"gx":-0.1,"gy":0.4,"gz":-0.4,"ft":1,"sp":1,"rt":1,"ie":0,"ii":0,"en":1,"me":1,"va":3.0,"vb":8.2,"vc":-2.2,"da":0.25,"db":0.5,"dc":0.0,"vl":2.0,"sl":300.0,"kp":0.2,"ki":10.0,"kd":0.0,"rmp":1000,"lpf":0.01}
```

### API (sensor_server.py on GEO-DUDe)
- `GET /simplefoc/status` - cached telemetry (no serial query)
- `POST /simplefoc` with `{"velocity": 5.0}` or `{"command": "T5"}` - sends command to Pico
- `GET /sensors` - sensor data (accel, gyro, encoder, rpm)

### Ground station UI
- RPM slider (-2500 to +2500 RPM), converts to rad/s for Pico
- Quick preset buttons (RPM)
- Enable/disable/calibrate/reset fault/stop buttons
- Motor tuning sliders: voltage limit, velocity limit, Kp, Ki, Kd, output ramp, LPF
- Live telemetry: fault/sleep/reset status, phase voltages, duty cycles, encoder, RPM

### Performance (measured)
- Max speed with I2C encoder: ~800 RPM (I2C read bottleneck)
- Max speed with analog encoder: ~1200+ RPM (and increasing)
- Reaction torque: 5 deg/s body rate during full reversal (+800 to -800 RPM)
- PID needs retuning for analog encoder (faster sensor = lower gains needed)

## Gimbal (ESP32 + TMC2209)

- 4 stepper drivers: Yaw, Pitch, Roll, Belt
- Constant-speed stepping (no S-curve/jerk)
- Status endpoint skips slow TMC UART reads while motors are stepping to avoid stutter
- Speed controlled via `stepDelay` (us between steps)

## Safety

**NEVER send motor, PWM, or actuator commands to hardware without explicit user permission.** Read-only debugging only.

**NEVER copy files directly to `/opt/geodude-control/`.** Always use git merge. The deployment dir is on `main` and may have changes from other developers (mizi). Direct file copies will overwrite their work.

## Deployment Rules

1. **Always merge through git, never direct file copy to /opt/geodude-control/**
2. Work in your worktree branch (e.g., `zeul-simplefoc`, `zeul-dev`)
3. To deploy: merge your branch into `main` at `/opt/geodude-control/`
4. Resolve conflicts properly (keep both sides where appropriate)
5. Then restart the service: `sudo systemctl restart wheel-control`
6. If the Pi has no internet, use git bundles to transfer branches:
   ```bash
   # On zmac:
   git bundle create /tmp/branch.bundle <branch-name>
   scp /tmp/branch.bundle zeul@192.168.50.2:/tmp/
   # On Pi:
   cd /opt/geodude-control && git fetch /tmp/branch.bundle <branch-name>:<branch-name>
   git merge <branch-name>
   ```

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
| SimpleFOC (Pico) | GEO-DUDe Pi USB | firmware in flash | boots automatically, streams to sensor-server |
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
