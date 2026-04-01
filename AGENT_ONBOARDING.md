# GEO-DUDe Agent Onboarding

Quick-start guide for agents working on the GEO-DUDe subscale satellite control software.

---

## What Is This

GEO-DUDe is a subscale satellite servicer model for an AER813 capstone project. It has a reaction wheel (MACE) for attitude control, two 5-DOF robotic arms with 10 servos, an IMU, encoder, and camera — all controlled by a Raspberry Pi inside a rotating body.

The operator controls everything from a laptop through a groundstation Raspberry Pi that hosts a web UI.

---

## Architecture

```
Laptop (browser)
    ↓ Ethernet (192.168.50.x)
Groundstation Pi (192.168.50.2)
    - wheel_control.py (Flask, internal port 8080, exposed at http://192.168.50.2/) — web UI
    ↓ WiFi (192.168.4.x)
GEO-DUDe Pi (192.168.4.166)
    - sensor_server.py (Flask, port 5000) — sensors, PCA9685, camera
    - attitude_controller.py (Flask, port 5001) — PID attitude control
```

---

## Key Repos

| Repo | What | Path on workstation |
|------|------|---------------------|
| [zeulewan/geodude-control](https://github.com/zeulewan/geodude-control) (private) | All control software + PCB files | `~/GIT/geodude-control/` |
| [zeulewan/subscale-docs](https://github.com/zeulewan/subscale-docs-338f947b) (private) | Project documentation (Zensical site) | `~/Documents/subscale-docs/` |

---

## Control Software Files

All in `~/GIT/geodude-control/`:

### Groundstation (runs on groundstation Pi, 192.168.50.2)

| File | Port | Description |
|------|------|-------------|
| `wheel_control.py` | 8080 internally, exposed at `http://192.168.50.2/` | Web UI — MACE reaction wheel control (arm, hold-to-spin, ramp), attitude control panel, PCA9685 servo sliders, camera preview, system stats |

### GEO-DUDe (runs on GEO-DUDe Pi, 192.168.4.166)

| File | Port | Service | Description |
|------|------|---------|-------------|
| `sensor_server.py` | 5000 | `sensor-server.service` | IMU/encoder polling (30Hz), PCA9685 I2C control, camera MJPEG stream, system stats |
| `attitude_controller.py` | 5001 | `attitude-controller.service` | Closed-loop PID body angle control via reaction wheel |
| `pca9685_test.py` | — | — | PCA9685 connection test and channel mapping |

### PCB Design

| Path | Description |
|------|-------------|
| `pcb/geodude-carrier/generate_pcb.py` | Programmatic PCB layout generator (pcbnew API) |
| `pcb/geodude-carrier/generate_netlist.py` | SKiDL netlist generator |
| `pcb/geodude-carrier/route_pcb.py` | Full routing pipeline (DSN → Freerouting → SES) |
| `pcb/geodude-carrier/BLX-A_5x20mm.kicad_mod` | Custom fuse holder footprint |
| `pcb/geodude-carrier/geodude-carrier.kicad_pcb` | Current PCB layout |

---

## Hardware

### PCA9685 Channel Map

| Channel | Pin | Name | Device |
|---------|-----|------|--------|
| Ch 0 | 1 | B1 | Arm 1 Base servo |
| Ch 1 | 2 | S1 | Arm 1 Shoulder servo |
| Ch 2 | 3 | E1 | Arm 1 Elbow servo |
| Ch 3 | 4 | W1A | Arm 1 Wrist Rotate servo |
| Ch 4 | — | W1B | Arm 1 Wrist Pan servo |
| Ch 5 | 6 | B2 | Arm 2 Base servo |
| Ch 6 | 7 | S2 | Arm 2 Shoulder servo |
| Ch 7 | 8 | E2 | Arm 2 Elbow servo |
| Ch 8 | 9 | W2A | Arm 2 Wrist Rotate servo |
| Ch 9 | — | W2B | Arm 2 Wrist Pan servo |
| Ch 11 | 14 | MACE | Reaction wheel ESC |
| Ch 12 | — | FAN | Cooling fan |

PCA9685 socket is a 1x19 female header. Pins 5, 10, 15 are NC (cap gaps between groups of 4).

### I2C Devices

| Device | Address | Description |
|--------|---------|-------------|
| PCA9685 | 0x40 | 16-channel PWM driver |
| ICM20948 | 0x69 | IMU (gyro/accel) |
| AS5600 | 0x36 | Magnetic encoder (wheel angle) |

### MACE Reaction Wheel

| | |
|---|---|
| Motor | Uangel X2807 1700KV BLDC |
| ESC | **Bidirectional 40A 2-6S** ([Amazon.ca](https://www.amazon.ca/dp/B0BSSP61XW)) — replaces old Drfeify 40A |
| Control | PCA9685 Ch 11, **1500us=stop, 1100-1500us=reverse, 1500-1900us=forward** |
| RPM limit | 600 RPM (software, with hysteresis at 70%) |
| Ramp rate | Configurable, default 0.1%/s, max 100%/s |
| Brake | Not needed — active reverse torque replaces passive braking |
| ESC direction | **Bidirectional** (proportional forward + reverse) |
| Arming | None required — plug and play, no calibration |
| Deadband | ~±50-75us around 1500us center — handled in software |

### Sensors

| Sensor | Rate | Data |
|--------|------|------|
| IMU gz | 30Hz | Body rotation rate (deg/s), ±250°/s |
| Encoder | 30Hz | Wheel angle (0-360°), RPM (10-sample rolling avg) |
| Camera | 10fps | 640x480 MJPEG, IMX708 (RPi Camera Module 3) |

---

## Attitude Controller

PID controller for body angle using reaction wheel. Runs at 100Hz on GEO-DUDe.

| Parameter | Default | Description |
|-----------|---------|-------------|
| Kp | 1.5 | Proportional gain |
| Ki | 0.05 | Integral gain |
| Kd | 0.8 | Derivative gain |
| Max throttle | 60% | Output ceiling |
| Ramp rate | 40.5%/s | Max throttle change rate |
| Watchdog | 5s | Auto-disable if no frontend heartbeat |

**Bidirectional ESC:** Full proportional torque in both directions. PID output maps to 1500us ± 500us (center = stop, above = forward, below = reverse). No arming sequence needed. Deadband around center handled by skipping ±50-75us zone in software.

**Gyro bias:** Calibrated on enable (2s stationary sampling). Drift accumulates over time.

### API (port 5001)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/status` | Full state (angle, setpoint, error, output, gains, RPM) |
| POST | `/enable` | Calibrate gyro, arm ESC, start PID |
| POST | `/disable` | Stop PID, coast motor |
| POST | `/setpoint` | `{"angle": 45.0}` |
| POST | `/nudge` | `{"delta": 10.0}` |
| POST | `/zero` | Reset angle and setpoint to 0 |
| POST | `/gains` | `{"Kp": 1.5, "Ki": 0.05, "Kd": 0.8}` |
| POST | `/calibrate` | Re-run gyro bias calibration |
| POST | `/stop` | Emergency disable |

---

## Sensor Server API (port 5000)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/sensors` | `{ax, ay, az, gx, gy, gz, angle, rpm}` |
| GET | `/system` | `{temp, cpu, load}` |
| GET | `/camera` | MJPEG stream |
| GET | `/channels` | PCA9685 channel mapping |
| POST | `/motor` | `{"pw": 1500}` — MACE ESC (blocked when attitude active) |
| POST | `/pwm` | `{"channel": "B1", "pw": 1500}` — any channel |
| POST | `/pwm/off` | All channels off |

---

## Documentation

All in `~/Documents/subscale-docs/docs/`:

| Path | Content |
|------|---------|
| `electrical/geodude/index.md` | GEO-DUDe electronics — Pi, PCA9685, servos, MACE, power distribution, fuses |
| `electrical/geodude/carrier-pcb.md` | Carrier PCB design — components, nets, trace widths, layout |
| `electrical/basestation/index.md` | Groundstation — hardware, network, SSH, software, all API docs |
| `electrical/gimbal/index.md` | Gimbal apparatus — TMC2209 drivers, ESP32, stepper motors |
| `electrical/interconnects.md` | All wiring connections |
| `electrical/power-budget.md` | Current draw and fuse sizing |
| `project/bom.md` | Bill of materials |

---

## Network

| Device | IP | Access |
|--------|-----|--------|
| Laptop (Mac) | 192.168.50.x (DHCP) | USB Ethernet to groundstation/switch |
| Groundstation Pi | 192.168.50.2 (eth), 192.168.4.1 (wlan hotspot) | `ssh zeul@192.168.50.2` pw: `Temp1234` |
| GEO-DUDe Pi | 192.168.4.166 (WiFi) | `ssh zeul@192.168.4.166` (key auth from groundstation) |

Offline local network — no internet. Ethernet clients get DHCP leases from the groundstation Pi. Use `http://192.168.50.2/` for the web UI; do not rely on hostname discovery.

WiFi SSID: `groundstation`, WPA2, password: `Temp1234`, ~3 Mbps bandwidth.

---

## Power Rails (5 separate)

| Rail | Net | Source |
|------|-----|--------|
| 12V | `+12V` | Toggle switch / bus bar |
| 7.4V | `+7V4` | Buck converter 1 |
| 5V servo | `+5V_SERVO` | Buck converter 3 |
| 5V logic | `+5V_LOGIC` | Pi 5V pin |
| 3.3V | `+3V3` | Pi 3.3V pin |

Two separate grounds: `GND` (servo power) and `GND_LOGIC` (I2C/sensors). They connect only at the bus bar.

---

## Critical Safety Rules

1. **NEVER send motor/PWM/actuator commands without explicit user permission.** Only the user has physical control and can intervene if something goes wrong.
2. The reaction wheel can spin up and stay spinning if WiFi drops (PCA9685 latches last value). Always have physical access to the ESC power when testing.
3. ESC brake mode is NOT enabled — 1000us = coast, not stop.
4. The attitude controller has a 5s watchdog that auto-disables if the frontend disconnects.

---

## Deploying Changes

```bash
# Edit on workstation, push to GitHub
cd ~/GIT/geodude-control
git add . && git commit -m "description" && git push

# Deploy to groundstation
scp wheel_control.py zmac:/tmp/  # via Mac
ssh zmac "scp /tmp/wheel_control.py zeul@192.168.50.2:/home/zeul/"
ssh zmac "ssh zeul@192.168.50.2 'sudo systemctl restart wheel-control.service'"

# Deploy to GEO-DUDe (via groundstation)
ssh zmac "ssh zeul@192.168.50.2 'scp sensor_server.py zeul@192.168.4.166:/home/zeul/'"
ssh zmac "ssh zeul@192.168.50.2 'ssh zeul@192.168.4.166 sudo systemctl restart sensor-server.service'"
```

Note: `zmac` is the Mac at Tailscale IP 100.117.222.41. The workstation cannot SSH to the Pis directly — must go through the Mac.

---

## Memory / Context

See `~/.claude/projects/-home-zeul/memory/MEMORY.md` for persistent context about:
- System state, lessons learned, shortcuts
- GEO-DUDe config files and Nav2 parameters (from Isaac Sim simulation work)
- Critical safety rule: never send motor commands autonomously
