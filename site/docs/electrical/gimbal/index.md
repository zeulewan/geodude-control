# Gimbal Electronics

The 3-axis gimbal and linear rail system runs on a 24V system with an ESP32 controlling stepper motors through TMC2209 drivers. Separate mains connection from GEO-DUDe.

---

## Controller

| | |
|---|---|
| **MCU** | ESP32 DOIT DevKit V1 (already have, Aidan M) |
| **Power** | 5V USB adapter (separate from 24V system) |
| **Role** | Gimbal axis control (3 axes) + belt drive motor |
| **WiFi** | Connects to "groundstation" network (base station Pi hotspot) |
| **Web UI** | HTTP server on port 80 for motor control, driver scanning, current setting |
| **OTA** | Firmware updates over WiFi (ArduinoOTA, hostname `esp32-tmc`) |
| **Framework** | Arduino (ESP-IDF v4.4.4), TMCStepper library for UART driver control |

---

## Stepper Motors and Drivers

4 stepper motors total, driven by TMC2209 stepper drivers.

| Motor | Function | Notes |
|-------|----------|-------|
| Stepper 1 | Gimbal yaw axis | Base rotation on roller bearing |
| Stepper 2 | Gimbal pitch axis | Through 80mm thrust bearing |
| Stepper 3 | Gimbal roll axis | Through 80mm thrust bearing |
| Stepper 4 | Belt drive | Linear approach, housed in gimbal base |

Stepper motors are provided by Aidan M. Confirmed compatible with TMC2209 drivers (under 1.77A RMS per phase). Model/specs TBD - update when Aidan provides details.

### Mounting

All 4 TMC2209 modules are mounted on a **breadboard** inside the gimbal base enclosure. Each driver needs:

- 100uF 50V electrolytic cap across VMOT/GND (as close to driver pins as possible)
- 100nF ceramic cap in parallel (optional but recommended)
- Heatsink installed on IC (included in pack)

### TMC2209 Drivers

| | |
|---|---|
| **Driver IC** | TMC2209 (BIGTREETECH V1.3) |
| **Quantity** | Pack of 5 (4 needed, 1 spare) |
| **VMOT range** | 4.75-28V (24V is ideal) |
| **Current limit** | 2A RMS / 2.8A peak per driver (1.77A effective max with 110 mOhm sense resistors) |
| **Logic voltage (VIO)** | 3.3-5V (ESP32 3.3V is fine) |
| **Features** | StealthChop (silent), SpreadCycle, UART config, sensorless homing (StallGuard4), CoolStep |
| **Heatsinks** | Included in pack, must be installed |
| **Link** | [Amazon.ca](https://www.amazon.ca/BIGTREETECH-TMC2209-Stepper-Stepstick-Heatsink/dp/B0CQC7QMS2) |

### UART Addressing

All 4 TMC2209 drivers can share a single UART bus from the ESP32. Each driver gets a unique address via MS1/MS2 pins:

| Driver | Motor | MS1 | MS2 | Address |
|--------|-------|-----|-----|---------|
| TMC2209 #1 | Yaw | LOW | LOW | 0 |
| TMC2209 #2 | Pitch | HIGH | LOW | 1 |
| TMC2209 #3 | Roll | LOW | HIGH | 2 |
| TMC2209 #4 | Belt | HIGH | HIGH | 3 |

ESP32 TX and RX are bridged with a **1k ohm resistor** for the single-wire UART interface. The TMCStepper Arduino library handles echo stripping automatically.

!!! warning "Critical TMC2209 Requirements"
    - **100uF electrolytic cap on each VMOT** (50V rated) - protects against back-EMF spikes. Without this, drivers will die. Add 100nF ceramic in parallel.
    - **Power sequencing:** VMOT must power up BEFORE VIO, and VIO must power down BEFORE VMOT.
    - **Never disconnect a motor while powered** - the voltage spike destroys the driver instantly.
    - **CLK pin must be tied to GND** (uses internal 12MHz clock). Floating CLK causes erratic behavior.
    - **Never hot-swap drivers** - always power down first.

### Current Setting

In UART mode, motor current is set digitally via IRUN/IHOLD registers (no potentiometer needed). In standalone STEP/DIR mode, adjust the onboard Vref potentiometer:

- Formula: I_RMS = (Vref / 2.5V) x 1.77A
- Factory default Vref ~1.2V = ~0.85A RMS
- For 1.5A RMS motor: set Vref to ~2.12V

### Wiring

| | |
|---|---|
| **Motor cables** | 1M, 6-pin to 4-pin (pack of 4, qty 2 packs) |
| **Link** | [Amazon.ca](https://www.amazon.ca/Stepper-Cables-Printer-XH2-54-Terminal/dp/B0DKJ69DQX) |

### ESP32 Pin Assignments

| Driver | STEP | DIR |
|--------|------|-----|
| TMC2209 #1 (Yaw) | GPIO 32 | GPIO 33 |
| TMC2209 #2 (Pitch) | GPIO 25 | GPIO 26 |
| TMC2209 #3 (Roll) | GPIO 22 | GPIO 23 |
| TMC2209 #4 (Belt) | GPIO 19 | GPIO 18 |

UART bus: ESP32 GPIO 16 (RX) / GPIO 17 (TX), bridged with 1k resistor to TMC2209 RX pin (single-wire UART)

!!! note "UART Wiring (BTT TMC2209 V1.3)"
    The V1.3 board has separate RX and TX header pins, but by factory default only the **RX pin** is connected to PDN_UART. The TX pin is disconnected unless you solder R10 on the bottom of the board.

    For single-wire UART (factory default, no R10 bridge):

    - ESP32 GPIO 16 (RX) connects **directly** to TMC2209 RX pin
    - ESP32 GPIO 17 (TX) connects through **1K resistor** to TMC2209 RX pin (same pin)
    - TMC2209 TX pin is left unconnected

    All 4 drivers share the same UART bus (all RX pins connected together).

!!! note "24V Required for UART"
    The TMC2209 chip is powered internally from VM, not VIO. VIO only sets the logic level. **UART will not respond without 24V on VM**, even if VIO is connected.

### ESP32 Firmware

Firmware source: `~/tmp/tmc2209_read/tmc2209_read.ino`

The ESP32 runs a web server with:

- **Driver scanning** - detects TMC2209s on the UART bus, reads version, microsteps, current, DRV_STATUS
- **Motor control** - step any driver forward/backward with configurable step count
- **Current setting** - adjustable 50-2000 mA via web UI (applies to all connected drivers)
- **Speed control** - slow (5ms), medium (2ms), fast (500us) step delay
- **Driver setup** - one-click configuration (400mA default, 16 microsteps, StealthChop)
- **OTA updates** - flash new firmware wirelessly via `espota.py`
- **HTTP /reboot** - `POST http://192.168.4.222/reboot` to soft-reset without power cycling
- **OTA resilience** - `WiFi.onEvent(STA_GOT_IP)` re-inits ArduinoOTA on every WiFi reconnect so OTA survives AP reboots

### Flashing OTA

Standard workflow (compile on zmac, flash from the groundstation Pi because the Pi network has no internet):

```bash
# On zmac
cp firmware/esp32/gimbal_controller.ino ~/tmp/tmc2209_read/tmc2209_read.ino
arduino-cli compile --fqbn esp32:esp32:esp32doit-devkit-v1 \
  --output-dir ~/tmp/tmc2209_read/build ~/tmp/tmc2209_read/
scp ~/tmp/tmc2209_read/build/tmc2209_read.ino.bin zeul@192.168.50.2:/tmp/
ssh zeul@192.168.50.2 "python3 /tmp/espota.py -i 192.168.4.222 -p 3232 \
  -f /tmp/tmc2209_read.ino.bin"
```

`espota.py` lives at `~/Library/Arduino15/packages/esp32/hardware/esp32/<version>/tools/espota.py` on zmac — copy it to the groundstation `/tmp/` if missing.

### If OTA times out

If `espota.py` prints "No response from the ESP", the ESP32 is still reachable over HTTP but the OTA UDP listener is wedged. Soft-reboot via HTTP:

```bash
ssh zeul@192.168.50.2 "curl -sS -X POST http://192.168.4.222/reboot"
# wait ~5 s, then retry the espota.py command
```

Only physically power-cycle the gimbal if HTTP itself stops responding (firmware has crashed into a busy loop). The current firmware re-initializes OTA on every WiFi reconnect, so an AP reboot no longer orphans the UDP socket.

---

## Power Supply

| | |
|---|---|
| **Voltage** | 24V |
| **Power** | 480W (20A) |
| **Input** | Separate mains connection (not through slip ring) |
| **Link** | [Amazon.ca](https://www.amazon.ca/BOSYTRO-Switching-Universal-Transformers-Upgraded/dp/B0F7XCLJVM) |

ESP32 is powered separately via a 5V USB adapter, NOT from the 24V bus.


---

## Linear Rail System

| | |
|---|---|
| **Rails** | HGR15, 1000mm, 2 rails + 4 HGH15CA carriages |
| **Belt** | 5M GT2 timing belt with pulleys and tensioners |
| **Drive** | Stepper #4 in gimbal base drives belt, translates servicer along rails |

---

## Cooling

| | |
|---|---|
| **Fans** | 24V 80mm brushless (pack of 2, qty 2 packs = 4 fans) |
| **Purpose** | Cooling gimbal base enclosure internals |
| **Link** | [Amazon.ca](https://www.amazon.ca/GDSTIME-Brushless-Ventilateur-Computer-Applications/dp/B0F1FHQKZD) |

---

## Power Architecture

PSU -> 14 AWG -> V+ Bus Bar (250A, 5/16" stud) -> 18 AWG to each TMC2209 VMOT (ring terminals).

No DC fuse on the gimbal. Overcurrent protection is handled by:

- TMC2209 drivers: 2A RMS current limit per driver (hardware)
- PSU: 20A overcurrent shutdown
- Wall breaker: 15A

### AC Current Calculation (no fuse needed)

| Load | DC Current (24V) | AC Current (120V) |
|------|------------------|-------------------|
| 4x steppers (TMC2209 limited) | 8A | - |
| Total DC | 8.6A | - |
| PSU at full load (480W) | - | 4.0A |
| With efficiency losses (~85%) | - | ~4.7A |

Combined with GEO-DUDe on the same outlet:

| System | AC Draw (max) |
|--------|---------------|
| GEO-DUDe (600W PSU) | ~5.9A |
| Gimbal (480W PSU) | ~4.7A |
| **Total** | **~10.6A** |

15A wall breaker provides 30% margin at absolute worst case. No AC fuse needed.
