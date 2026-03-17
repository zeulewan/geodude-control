# GEO-DUDe Electronics

The GEO-DUDe servicer subscale model runs on a 12V system. A Raspberry Pi controls all 10 servos and a MACE reaction wheel via a PCA9685 PWM driver board over I2C. The entire system sits inside the rotating satellite body, powered by 120V AC mains passed through a slip ring.

---

## Controller

| | |
|---|---|
| **Main controller** | Raspberry Pi (already have, Zeul) |
| **PWM driver** | PCA9685 16-channel I2C PWM board (**add to BOM**) |
| **Camera** | Raspberry Pi Camera (AI vision, already have, Zeul) |
| **Comms to ESP32** | WiFi (both have built-in WiFi, no extra hardware) |
| **Comms to base station** | WiFi |

The PCA9685 drives all 10 servo signal lines and the ESC PWM signal over I2C (2 Pi pins). The IMU and magnetic encoder also share the I2C bus (different addresses). Limit switches connect directly to Pi GPIO (6 needed, plenty of free pins).

### Pi Connections

| Pi Pin | Goes To | Protocol | Notes |
|--------|---------|----------|-------|
| I2C SDA (GPIO 2) | PCA9685 | I2C | All 10 servo PWM signals |
| I2C SCL (GPIO 3) | PCA9685 | I2C | Shared bus |
| GPIO 4-9 (6 pins) | Limit switches | Digital input | One per joint, pulled up |
| CSI connector | Pi Camera | Ribbon cable | Fixed mount near Pi |
| I2C SDA (GPIO 2) | ICM20948 IMU | I2C | MACE attitude sensing (addr 0x68) |
| I2C SDA (GPIO 2) | AS5600 Encoder | I2C | MACE wheel speed sensing (addr 0x36) |
| WiFi | ESP32 | Wireless | Coordinated operation |
| WiFi | Base station Pi | Wireless | Ground control commands |

No GPIO is used for power switching -- the toggle switch is manual.

---

## Robotic Arm

6-DOF servo-driven arm for approach and capture via the defunct satellite's kick-engine nozzle. **All dumb PWM servos**, no smart servos.

| Joint | Servo | Torque | Qty | Voltage | Stall Current (each) | Source |
|-------|-------|--------|-----|---------|---------------------|--------|
| Base | [HOOYIJ 150kg](https://www.amazon.ca/HOOYIJ-Digital-Waterproof-Stainless-Steering/dp/B0CX92QNJY) | 150 kg-cm | 2 | **12V** | 8.0A | [Datasheet](https://www.amazon.com/HOOYIJ-RDS51150-Steering-U-Shaped-Brackets/dp/B0CP126F77) |
| Shoulder | [ANNIMOS 150kg](https://www.amazon.ca/ANNIMOS-Voltage-Digital-Steering-Brackets/dp/B0C69W2QP7) | 150 kg-cm | 2 | **12V** | 8.0A | |
| Elbow | [ANNIMOS 80kg](https://www.amazon.ca/ANNIMOS-Waterproof-Digital-Steering-Brackets/dp/B0C69WWLWQ) | 80 kg-cm | 2 | **7.4V** | 5.0A | [Specs](https://www.amazon.com/ANNIMOS-Waterproof-Digital-Steering-Brackets/dp/B0C69WWLWQ) |
| Wrist (rotate) | [Wishiot RDS3218](https://www.amazon.ca/Wishiot-RDS3218-Waterproof-Mounting-Bracket/dp/B0CCXRCFK4) | 20 kg-cm | 2 | **5V** | 1.6A | 270 deg, with U-bracket |
| Wrist (pan) | [Wishiot RDS3218](https://www.amazon.ca/Wishiot-RDS3218-Waterproof-Mounting-Bracket/dp/B0CCXRCFK4) | 20 kg-cm | 2 | **5V** | 1.6A | 270 deg, with U-bracket |

**Total: 10 dumb PWM servos**, all driven by PCA9685 I2C PWM driver.

---

## MACE (Reaction Wheel)

Momentum Attitude Control Electronics - a single-axis reaction wheel for attitude demonstration.

| Component | Model | Voltage | Current | Interface | I2C Addr |
|-----------|-------|---------|---------|-----------|----------|
| Motor | Uangel X2807 1700KV BLDC | 12V (via ESC) | ~1-3A realistic | PWM via ESC | - |
| ESC | Drfeify 40A | 7.4-14.8V | - | PWM (PCA9685 Ch 14) | - |
| IMU | ICM20948 | 3.3V | ~mA | I2C | 0x68 |
| Magnetic encoder | AS5600 | 3.3V | ~mA | I2C | 0x36 |

**Power:** ESC powered from 12V bus through the toggle switch (no separate fuse needed -- ESC has built-in overcurrent protection, and the motor draws only ~1-3A as a reaction wheel).

**Control:** PCA9685 Ch 14 sends PWM to ESC. ESC needs arming sequence on boot (send 1000us for ~2 seconds before accepting throttle commands).

**Sensors:** IMU and encoder share the I2C bus with PCA9685 (all different addresses: PCA9685 0x40, ICM20948 0x68, AS5600 0x36).

---

## Power Supply

| | |
|---|---|
| **Voltage** | 12V |
| **Power** | 600W (50A max) |
| **Input** | 120V AC mains via slip ring |
| **Location** | Inside rotating GEO-DUDe body |
| **Output terminals** | Screw terminals to Wago distribution blocks |
| **Link** | [Amazon.ca](https://www.amazon.ca/VAYALT-Switching-Universal-Transformer-Industrial/dp/B0DXL2BCGS) |

---

## Power Distribution (Wago Blocks)

All DC power distribution uses **Wago lever connectors** (from Mach). Each voltage rail gets its own Wago block. The PCA9685 only carries signal wires - servo power is wired directly from the correct voltage rail.

```
12V PSU output (2x 16 AWG parallel trunk)
    |
    +-- Main Fuse (30A) --> 12V Bus (Wago)
    |                          |
    |                          +-- Fuse (3A) --> Buck conv 2 (5V) --> 5V Pi Wago
    |                          |   (ALWAYS ON - taps off BEFORE toggle switch)
    |                          |         +-->  Raspberry Pi (20 AWG)
    |                          |         \-->  PCA9685 VCC (22 AWG)
    |                          |
    |                          \-- 40A TOGGLE SWITCH (manual, panel mount)
    |                                |
    |                                +-- 12V Servo Bus Board (16 AWG from toggle)
    |                                |     +-- Base servo L (8A slow-blow fuse)
    |                                |     +-- Base servo R (8A slow-blow fuse)
    |                                |     +-- Shoulder servo L (8A slow-blow fuse)
    |                                |     \-- Shoulder servo R (8A slow-blow fuse)
    |                                +-- Buck conv 1 (7.4V) --> 7.4V Servo Bus Board
    |                                |     +-- Elbow servo L (5A slow-blow fuse)
    |                                |     \-- Elbow servo R (5A slow-blow fuse)
    |                                +-- Buck conv 3 (5V) --> 5V Servo Bus Board
    |                                |     \-- RDS3218 wrist x4 (3A slow-blow each)
    |                                +-- ESC (40A) --> MACE reaction wheel motor
    |                                \-- 12V fan (1A fuse)
    |
    \-- GND Bus (2x 16 AWG parallel) --> Everything (star ground via Wago bus)
```

**Power-on sequence:** Pi and PCA9685 are always powered via buck 2 (before toggle switch, always on). When the operator is ready, they flip the panel-mount toggle switch to energize all servo bus boards and the ESC. PCA9685 outputs are off until Pi sends I2C commands, so servos stay still even after the toggle switch is flipped on. ESC requires arming sequence (1000us PWM for ~2s) before accepting throttle.

**Base and shoulder servos run directly off 12V** - no buck converter needed. They're rated 10-12.6V and the PSU outputs 12V.

**Grounding: Star topology.** Every component gets its own GND wire back to the GND Wago bus - no daisy-chaining. This prevents high-current servo ground return from raising the Pi/PCA9685 ground reference. The GND bus may need 2-3 ganged Wago blocks to fit all the wires (17+ connections).

---

## Buck Converters

**3 of 4** [20A 300W buck converters](https://www.amazon.ca/XLX-High-Power-Converter-Adjustable-Protection/dp/B081X5YX8V) are needed. 1 spare.

| Buck # | Output V | Feeds | Max Current | Location | Status |
|--------|----------|-------|-------------|----------|--------|
| 1 | **7.4V** | 2x elbow servos (80kg) | 10A stall | After toggle switch (fuse block 8A circuit) | OK |
| 2 | **5V** | Raspberry Pi + PCA9685 | ~2.6A | **Before toggle switch** (always on) | OK |
| 3 | **5V** | 4x RDS3218 wrist | ~6.4A stall | After toggle switch (fuse block 8A circuit) | OK |
| 4 | - | Spare | - | - | |

**Buck converter specs:** Input 6-40V, Output 1.25-36V adjustable (potentiometer), 20A max / 15A continuous, 300W, screw terminals, short circuit protection.

---

## Fuses

Fuses from Mach. Sized at 125-150% of expected max draw.

| Fuse | Branch | Max Draw | Rating | Wire Gauge | Notes |
|------|--------|----------|--------|-----------|-------|
| AC inline | Mains hot line before slip ring | ~5A at 120V | **6A slow-blow** | Mains cable | Protects AC path |
| Main DC | 12V bus after PSU | ~30A worst case | **30A** | **2x 16 AWG parallel** | |
| Base servo branch | 2x base 150kg servos | 16A stall | **8A each** (per-servo) | **16 AWG** | Individual fusing on bus board |
| Shoulder servo branch | 2x shoulder 150kg servos | 16A stall | **8A each** (per-servo) | **16 AWG** | Individual fusing on bus board |
| Buck 1 input | Elbow servos | ~6.2A at 12V in | **8A** | 18 AWG | Fuse block circuit |
| Buck 2 input | Pi + PCA9685 only | ~1.1A at 12V in | **3A** | 18 AWG | Before toggle switch (always on) |
| Buck 3 input | Wrist servos | ~2.7A at 12V in | **8A** | 18 AWG | Fuse block circuit |
| Fan line | 12V fan | 0.15A | **1A** | 22 AWG | Fuse block circuit |

---

## Slip Ring (AC Mains Passthrough)

A [3-wire 15A slip ring](https://www.amazon.ca/Conductive-Current-Collecting-Electric-Connector/dp/B09NBLY16J) passes 120V AC mains from the gantry through the rotation point (thrust bearing) into the GEO-DUDe body. The servicer rotates continuously (360+) on the thrust bearing on the linear rails.

| | |
|---|---|
| **Model** | 3-wire, 15A per wire, 150 RPM |
| **Carries** | 120V AC mains (live, neutral, ground) |
| **Location** | Between gantry/rail base (stationary) and rotating GEO-DUDe body |

### AC Wiring Path

```
Wall outlet
    --> IEC C16 panel socket on gantry (crimp spade terminals, 6.3mm insulated)
    --> 6A slow-blow inline fuse
    --> Wire to slip ring input (stationary side, solder or crimp butt connectors)
    --> Slip ring output (rotating side)
    --> 12V 600W PSU AC input screw terminals (inside GEO-DUDe)
```

!!! danger "AC mains safety"
    - Slip ring rated 15A per wire at 120V - sufficient for 600W PSU (~5A at 120V)
    - All AC connections must use proper **crimp spade terminals** on the IEC C16
    - Ground wire MUST pass through the slip ring
    - AC wiring physically separated from DC wiring inside GEO-DUDe
    - Inline fuse on AC hot line before slip ring (6A slow-blow)
    - Emergency shutdown: pull the mains plug

---

## Limit Switches

[Momentary limit switches](https://www.amazon.ca/MKBKLLJY-Momentary-Terminal-Electronic-Appliance/dp/B0DK693J79) - **6 needed** (one per joint: base, shoulder, elbow, wrist rotate, wrist pan, end-effector). Connected directly to Pi GPIO with internal pull-up resistors. 24 switches in stock (2 packs of 12), 18 spares.

---

## Cooling

| | |
|---|---|
| **Fan** | [12V 80mm fan](https://www.amazon.ca/KingWin-CF-08LB-80mm-Long-Bearing/dp/B002YFSHPY) |
| **Powered from** | 12V bus via fuse (1A) |

---

## Dropped Components

These items from the original BOM are **no longer needed** for GEO-DUDe electronics:

| Item | Reason |
|------|--------|
| ~~Waveshare smart servo driver board~~ | All servos are dumb PWM, using PCA9685 instead |
| ~~Feetech STS3215 smart servos~~ | Replaced with Wishiot RDS3218 20kg PWM servos for wrist |
| ~~PCF8575 I2C GPIO expander~~ | Only 6 limit switches, Pi GPIO handles it directly |
| ~~Buck converter 4~~ | Only 3 needed (7.4V elbow, 5V Pi, 5V servo), 1 spare |
| ~~120A 12V relay (irhapsody)~~ | Replaced by manual toggle switch |
| ~~2N2222 NPN transistor~~ | Was for relay coil driver, no longer needed |
| ~~1N4007 flyback diode~~ | Was for relay back-EMF protection, no longer needed |
| ~~1k ohm resistor~~ | Was for transistor base limiter, no longer needed |
| ~~Miuzei MG90S x4~~ | End-effector design deferred |

---

## Components To Add to BOM

| Item | Purpose | Status |
|------|---------|--------|
| ~~PCA9685 16-ch PWM driver~~ | ~~Drive all 10 servo signal lines via I2C~~ | Added (row 5, $19.99) |
| ~~GPIO screw terminal breakout HAT~~ | ~~Clean wiring for Pi GPIO connections~~ | Added (row 24, $12.99) |

---

## Diagrams

See the [System Diagrams](../diagrams/) page for full power and signal architecture diagrams (D2 rendered SVGs).

---

## Design Notes and Concerns

### Servo Factory Wire Gauge

The HOOYIJ and ANNIMOS 150kg servos ship with thin pre-attached leads (~18-20 AWG) despite their 8A stall current rating. This is acceptable because:

- Factory leads are short (typically 15-30cm)
- Voltage drop over short runs is minimal
- The fuse protects the branch, not the individual servo lead
- Do NOT extend these leads with thin wire. If longer runs are needed, splice with 16 AWG and use proper crimp butt connectors with heat shrink.

### Heat Dissipation

The GEO-DUDe body is a semi-enclosed rotating structure containing:

- 600W PSU (generates heat even at partial load)
- Up to 10 servos (heat from those near the body)
- 3x buck converters

Currently only 1x 80mm 12V fan for cooling. Considerations:

- The body is **not fully sealed** - 3D printed PLA structure will have gaps and openings for the arm
- Rotation itself creates some airflow through openings
- Most servos are on the arm (outside the body), not inside
- Buck converters and PSU are the main internal heat sources
- **Monitor temperatures during initial testing.** If thermals are a problem, add a second fan or cut ventilation slots in the body panels.

### WiFi Reliability

The Pi communicates with the ESP32 via WiFi. The rotating GEO-DUDe body may attenuate the signal if it has significant metal structure.

- PLA body is RF-transparent, so if the structure is mostly 3D printed, WiFi should be fine
- Metal fasteners, the PSU housing, and the thrust bearing are localized shielding
- The Pi's onboard WiFi antenna is omnidirectional
- **If signal is weak:** mount a small external antenna or use a USB WiFi adapter positioned near a PLA panel opening
- Test WiFi RSSI during rotation before relying on it for real-time control

### Cable Management (Rotating Body)

All wires inside the GEO-DUDe body experience forces during rotation. At low RPM (subscale test speeds), centrifugal forces are small, but wires still need to be secured:

- **Zip-tie all wire bundles** to the internal frame/structure
- **Strain relief** at every connection point (screw terminals, Wago blocks, servo connectors)
- Use **cable clips or adhesive tie mounts** on the 3D printed structure
- Route wires along structural members, not floating freely
- The arm cable bundle (signal + power to all 10 servos) exits the body through a single opening - use a **grommet or cable gland** to prevent chafing
- Keep slack to a minimum, but leave enough for the arm's range of motion

### Software Current Limiting

No hardware current sensing is implemented. Software-side protections to implement on the Pi:

- **Stall detection:** If a servo command doesn't result in expected motion (via limit switches or timing), cut PWM to that channel via PCA9685
- **Startup sequence:** Enable servos one joint at a time (base first, then shoulder, etc.) rather than all at once, to avoid inrush current spikes
- **Timeout:** If any servo is commanded to a position for more than a few seconds without reaching it, assume stall and disable
- **Temperature monitoring:** Consider adding a cheap I2C temperature sensor (like DS18B20) near the PSU and buck converters to trigger fan speed increase or servo shutdown if overheating
