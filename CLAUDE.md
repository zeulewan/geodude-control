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

## Deployment

Workstation cannot SSH to the Pis directly — must go through the Mac (100.117.222.41 via Tailscale).

```bash
# Groundstation Pi (192.168.50.2) — deploy web UI
scp groundstation/wheel_control.py zmac:/tmp/ && ssh zmac "scp /tmp/wheel_control.py zeul@192.168.50.2:/home/zeul/"
# Also deploy templates/ and static/ if changed:
scp -r groundstation/templates zmac:/tmp/ && ssh zmac "scp -r /tmp/templates/* zeul@192.168.50.2:/home/zeul/templates/"
scp -r groundstation/static zmac:/tmp/ && ssh zmac "scp -r /tmp/static/* zeul@192.168.50.2:/home/zeul/static/"
ssh zmac "ssh zeul@192.168.50.2 'sudo systemctl restart wheel-control.service'"

# GEO-DUDe Pi (192.168.4.166 via groundstation) — deploy sensor/attitude
scp geodude/sensor_server.py zmac:/tmp/ && ssh zmac "scp /tmp/sensor_server.py zeul@192.168.50.2:/tmp/ && ssh zeul@192.168.50.2 'scp /tmp/sensor_server.py zeul@192.168.4.166:/home/zeul/ && ssh zeul@192.168.4.166 sudo systemctl restart sensor-server.service'"

# ESP32 (192.168.4.222 via groundstation) — compile on Mac, flash OTA
scp gimbal/gimbal_controller.ino zmac:/Users/zeul/tmp/tmc2209_read/tmc2209_read.ino
ssh zmac "arduino-cli compile --fqbn esp32:esp32:esp32doit-devkit-v1 --output-dir build ~/tmp/tmc2209_read/"
ssh zmac "scp ~/tmp/tmc2209_read/build/tmc2209_read.ino.bin zeul@192.168.50.2:/tmp/"
ssh zmac "ssh zeul@192.168.50.2 'python3 /tmp/espota.py -i 192.168.4.222 -p 3232 -f /tmp/tmc2209_read.bin'"
```

Note: `zmac` = 100.117.222.41. The Mac needs `arduino-cli` (homebrew) with esp32 board package and TMCStepper library.

## Known Code Issues (TODO)

- **Groundstation paths:** The systemd service on the groundstation Pi runs `/home/zeul/wheel_control.py`. After the repo reorganization, the deployed file is still at that path (flat copy), but Flask looks for `templates/` and `static/` relative to the .py file. These must be deployed to `/home/zeul/templates/` and `/home/zeul/static/` on the Pi.
- **ESP32 OTA filename:** The Mac compile path still uses `tmc2209_read/` as the sketch folder name. The ESP32 doesn't care, but the Mac-side paths in the deploy script reference this old name.
- **Docs site CI:** The GitHub Actions workflow (`.github/workflows/docs.yml`) needs updating — it was written for the old standalone repo structure. The docs source is now at `site/docs/` and config at `site/zensical.toml`.
- **AGENT_ONBOARDING.md** references file paths at repo root — needs updating to reflect `groundstation/`, `geodude/`, `gimbal/` subdirectories.
- **Pico pin assignments — two hardware versions:** The perfboard prototype and the carrier PCB use different Pico GPIO pins for FOC signals (IN1/IN2/IN3/EN). Serial (GP0/1) and I2C (GP4/5) are the same on both. PCB version is documented in `pcb/CLAUDE.md` and `site/docs/electrical/geodude/carrier-pcb.md`. Perfboard version TBD — needs confirming from physical wiring.

## Safety

**NEVER send motor, PWM, or actuator commands to hardware without explicit user permission.** Read-only debugging only.

## Network

| Device | IP | Access |
|--------|-----|--------|
| Workstation | 100.101.214.44 | You are here |
| Mac (zmac) | 100.117.222.41 | Tailscale |
| Groundstation Pi | 192.168.50.2 | Via Mac USB Ethernet |
| GEO-DUDe Pi | 192.168.4.166 | Via groundstation WiFi |
| ESP32 (gimbal) | 192.168.4.222 | Via groundstation WiFi |
