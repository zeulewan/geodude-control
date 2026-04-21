# Base Station

Standalone ground control station. Separate Raspberry Pi powered by its own wall adapter (5V USB). Not wired into either the GEO-DUDe or gimbal power systems.

---

## Hardware

| | |
|---|---|
| **Controller** | Raspberry Pi 4 Model B (8 GB RAM) |
| **Hostname** | `groundstation` |
| **OS** | Debian 13 (Trixie) / Raspberry Pi OS, kernel 6.12, aarch64 |
| **Storage** | 128 GB microSD |
| **Power** | 5V USB wall adapter (independent) |
| **Communication** | Ethernet (to laptop) + WiFi hotspot (to subsystems) |
| **Software** | Ground control UI, reaction wheel web control service |

---

## Network Configuration

### Ethernet (eth0) — Laptop Link

The Pi's built-in Ethernet port connects directly to the operator laptop via a USB Ethernet adapter or small unmanaged switch. The Pi keeps a static IP on `eth0` and runs DHCP for connected laptops, so the laptop side should be left on automatic/DHCP.

| | Pi (`eth0`) | Laptop (USB Ethernet) |
|---|---|---|
| **IP** | `192.168.50.2/24` | `192.168.50.x/24` |
| **Config** | Static (NetworkManager `netplan-eth0`) | DHCP / automatic |

On macOS, the USB adapter may appear under names like **"USB 10/100/1000 LAN"** or a custom renamed service. Leave it on **Using DHCP**. No manual IP assignment is required.

The reliable operator URL is:

```text
http://192.168.50.2/
```

### WiFi Hotspot (wlan0) — Subsystem Link

The Pi runs a WiFi hotspot on `wlan0` at `192.168.4.1/24`. GEO-DUDe Pi and ESP32 connect to this network.

| | |
|---|---|
| **Interface** | `wlan0` |
| **IP** | `192.168.4.1/24` |
| **SSID** | `groundstation` |
| **Security** | WPA2-PSK (`Temp1234`) |
| **Mode** | Hotspot (access point) |
| **Clients** | GEO-DUDe Pi (`192.168.4.166`), ESP32 |
| **Bandwidth** | ~3 Mbps (measured) |

---

## SSH Access

```bash
ssh zeul@192.168.50.2
```

| | |
|---|---|
| **User** | `zeul` |
| **Password** | `Temp1234` |
| **Auth methods** | publickey, keyboard-interactive |

!!! warning
    Default credentials — change the password before any public demo or field test.

---

## Communication Links

| Link | From | To | Protocol |
|------|------|----|----------|
| Operator interface | Laptop | Base station Pi | Ethernet (`192.168.50.x`) |
| GEO-DUDe control | Base station Pi | GEO-DUDe Pi | WiFi (`192.168.4.x`) |
| Gimbal control | Base station Pi | ESP32 | WiFi (`192.168.4.x`) |

The base station Pi acts as the central coordinator. The operator controls the system from a laptop connected to the base station Pi over Ethernet, which relays commands to both the GEO-DUDe servicer (via its onboard Pi) and the gimbal apparatus (via ESP32) over WiFi.

```mermaid
graph LR
    LAPTOP["Laptop<br/>(Operator)<br/>DHCP on 192.168.50.x"] -->|Ethernet| BASEPI["Base Station Pi<br/>(Ground Control)<br/>eth0: 192.168.50.2<br/>wlan0: 192.168.4.1"]
    BASEPI -->|WiFi| GEOPI["GEO-DUDe Pi<br/>(Servicer)<br/>192.168.4.166"]
    BASEPI -->|WiFi| ESP["ESP32<br/>(Gimbal)<br/>192.168.4.x"]
    GEOPI -->|WiFi| ESP
```

---

## Network Architecture

The base station Pi runs a WiFi hotspot (`groundstation`) that both the ESP32 and GEO-DUDe Pi connect to. The laptop connects to the Pi via Ethernet (192.168.50.0/24 subnet).

IP forwarding and NAT are enabled on the Pi so the laptop can reach WiFi clients:

```bash
sudo sysctl -w net.ipv4.ip_forward=1
sudo nft add table ip nat
sudo nft add chain ip nat postrouting { type nat hook postrouting priority 100 \; }
sudo nft add rule ip nat postrouting oifname wlan0 masquerade
sudo nft add table ip filter
sudo nft add chain ip filter forward { type filter hook forward priority 0 \; policy accept \; }
```

On the laptop, add a route to the WiFi subnet:
```bash
sudo route add -net 192.168.4.0/24 192.168.50.2
```

| Device | IP | Subnet |
|--------|----|--------|
| Base station Pi (eth0) | 192.168.50.2 | 192.168.50.0/24 |
| Base station Pi (wlan0) | 192.168.4.1 | 192.168.4.0/24 |
| ESP32 (gimbal) | 192.168.4.222 | 192.168.4.0/24 |
| Laptop (Ethernet) | 192.168.50.x | 192.168.50.0/24 |

## Notes

- No fusing or power distribution needed — just a Pi with a USB power supply
- WiFi range should be tested with the GEO-DUDe rotating inside the gimbal apparatus
- The GEO-DUDe Pi and ESP32 also communicate directly with each other over WiFi for coordinated operation
- Laptop connects via Ethernet to the Pi (192.168.50.0/24)

---

## Software

### GEO-DUDe Control Web UI (`wheel-control.service`)

Flask web app exposed to operators at **`http://192.168.50.2/`**. Internally the service still runs on port `8080`, with port `80` redirected to it on the groundstation Pi. Controls GEO-DUDe hardware via HTTP to `192.168.4.166:5000`. Source: [zeulewan/geodude-control](https://github.com/zeulewan/geodude-control) (private).

**Camera:**

- Live MJPEG preview from RPi Camera Module 3 (IMX708)
- 640x480 @ 10fps, JPEG quality 50 (bandwidth-limited by WiFi)
- 180° flipped, proxied through groundstation

**System Stats:**

- CPU%, temperature, load average for both Pis
- Polled at 0.5Hz

**MACE (Reaction Wheel) panel:**

- STM32 Nucleo / SimpleFOC manual wheel control
- Direct target entry in wheel RPM, plus quick-set buttons for common values
- `ENABLE`, `DISABLE`, and `STOP` buttons for live control state
- `CALIBRATE FOC` button to run `initFOC()` on the wheel controller before enabling live motion
- Live wheel RPM readout from the wheel encoder over serial status polling
- Voltage limit input for tuning authority in manual mode
- Manual MACE control is mutually exclusive with the higher-level attitude control paths

**Attitude Control panel:**

- Closed-loop body-angle and body-rate experimentation built on the same STM32 / SimpleFOC stack
- Body angle zeroing and gyro bias calibration from the GEO-DUDe side
- Angle dial, setpoint controls, live gains, and breakaway/profile tooling
- Shared safety constraints with manual MACE control, including mutual exclusion and wheel-speed limits

**PCA9685 Channels panel:**

- Individual sliders for all servo channels (500-2500us for B/W/E/S, center 1500us)
- Servos always active at center on page load (continuous signal required)
- Per-channel center button, ALL CENTER button
- Slider thumb-drag only (no track click-jump), center button ramps slowly

**Sensor readout:**

- Live gyroscope, accelerometer, and encoder angle from GEO-DUDe IMU/encoder
- GEO-DUDe connection status and motor error reporting

### Sensor Server (`sensor-server.service` on GEO-DUDe)

Flask API on GEO-DUDe (`192.168.4.166:5000`). Owns the PCA9685 servo path, wheel telemetry, and the STM32 / SimpleFOC serial bridge.

- `GET /sensors` — gyro, accel, encoder angle, RPM
- `GET /system` — CPU%, temperature, load average
- `POST /pwm` — per-channel PCA9685 control (`{"channel": "B1", "pw": 1500}`)
- `GET /pwm_health` — servo write/readback health and last pulse widths
- `GET /camera` — MJPEG stream from RPi Camera Module 3
- `POST /simplefoc` — raw SimpleFOC commander bridge for the wheel controller
- `GET /simplefoc/status` — current wheel target / controller connectivity
- `POST /simplefoc/profile/calibrate` — run wheel `initFOC()` calibration on the STM32 side
- `GET /simplefoc/control/state` — live body control state
- `POST /simplefoc/control/start|config|zero|stop|breakaway` — higher-level wheel/body control routes

There is no longer a separate ESC-style `/motor` path for MACE, and the old `attitude-controller.service` split is obsolete. Those capabilities now live under the unified `sensor-server.service` + SimpleFOC stack.

### Networking Notes

- Offline local network — no internet
- Ethernet clients get `192.168.50.x` addresses automatically by DHCP from the groundstation Pi
- Use `http://192.168.50.2/` for the UI; do not rely on hostname discovery for demos or field use
- WiFi bandwidth ~3 Mbps — camera stream and sensor polling are bandwidth-conscious
- GEO-DUDe SSID configured as `groundstation` (no space) in NetworkManager
