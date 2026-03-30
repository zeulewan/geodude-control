# GEO-DUDe Carrier PCB

Custom PCB replacing the perfboard fuse board. Serves as the central interconnect for all GEO-DUDe electronics: PCA9685 PWM driver, servo power distribution with per-servo fusing, I2C bus breakout, and connector headers for all peripherals.

---

## Design Summary

| | |
|---|---|
| **Replaces** | Perfboard fuse board |
| **Tool** | KiCad 10.0.0 |
| **Fab target** | JLCPCB |
| **Layers** | 2 (top + bottom copper) |
| **Copper weight** | 2 oz (for high-current traces) |

---

## Components On-Board

### PCA9685 Socket

Female header socket to mount the PCA9685 16-channel PWM breakout board. Board connects via I2C to the Pi and provides PWM signals to all 12 output headers.

| PCA9685 Pin | Connects To |
|-------------|-------------|
| VCC | 5V rail |
| GND | GND rail |
| SDA | I2C bus SDA |
| SCL | I2C bus SCL |
| OE | Directly to GND (always enabled) |
| Ch 0-9 | Servo signal pins (10 servos) |
| Ch 11 | ESC signal pin |
| Ch 12+ (spare) | Fan signal pin |

### Fuse Holders (10x glass tube)

Per-servo fusing. Each fuse sits between the correct voltage rail and the servo power pin.

| Fuse | Rating | Voltage Rail | Servo |
|------|--------|-------------|-------|
| F1 | 8A slow-blow | 12V | Arm 1 Base |
| F2 | 8A slow-blow | 12V | Arm 1 Shoulder |
| F3 | 5A slow-blow | 7.4V | Arm 1 Elbow |
| F4 | 3A slow-blow | 5V | Arm 1 Wrist Rotate |
| F5 | 3A slow-blow | 5V | Arm 1 Wrist Pan |
| F6 | 8A slow-blow | 12V | Arm 2 Base |
| F7 | 8A slow-blow | 12V | Arm 2 Shoulder |
| F8 | 5A slow-blow | 7.4V | Arm 2 Elbow |
| F9 | 3A slow-blow | 5V | Arm 2 Wrist Rotate |
| F10 | 3A slow-blow | 5V | Arm 2 Wrist Pan |

### I2C Bus Breakout (4 ports)

4-pin screw terminals (SDA, SCL, 3.3V, GND) for each I2C device:

| Port | Device | I2C Address |
|------|--------|-------------|
| 1 | PCA9685 (on-board socket) | 0x40 |
| 2 | ICM20948 IMU (external) | 0x69 |
| 3 | AS5600 Encoder (external) | 0x36 |
| 4 | Spare | — |

All 4 ports share the same I2C bus (SDA/SCL connected in parallel).

---

## Connectors

### Power Input (screw terminals)

| Terminal | Voltage | Source | Wire Gauge |
|----------|---------|--------|-----------|
| J_12V | 12V + GND | Toggle switch / 12V bus | 16 AWG |
| J_7V4 | 7.4V + GND | Buck converter 1 | 18 AWG |
| J_5V | 5V + GND | Buck converter 3 | 18 AWG |

### Servo/ESC/Fan Output Headers (12x 3-pin male)

Each header provides: **Signal (PWM)** | **Power (V+)** | **GND**

Standard servo connector pinout (signal on edge, power in middle, GND on other edge).

| Header | PCA9685 Ch | Voltage | Fuse | Device |
|--------|-----------|---------|------|--------|
| SV1 | Ch 0 | 12V | F1 (8A) | Arm 1 Base |
| SV2 | Ch 1 | 12V | F2 (8A) | Arm 1 Shoulder |
| SV3 | Ch 2 | 7.4V | F3 (5A) | Arm 1 Elbow |
| SV4 | Ch 3 | 5V | F4 (3A) | Arm 1 Wrist Rotate |
| SV5 | Ch 4 | 5V | F5 (3A) | Arm 1 Wrist Pan |
| SV6 | Ch 5 | 12V | F6 (8A) | Arm 2 Base |
| SV7 | Ch 6 | 12V | F7 (8A) | Arm 2 Shoulder |
| SV8 | Ch 7 | 7.4V | F8 (5A) | Arm 2 Elbow |
| SV9 | Ch 8 | 5V | F9 (3A) | Arm 2 Wrist Rotate |
| SV10 | Ch 9 | 5V | F10 (3A) | Arm 2 Wrist Pan |
| ESC | Ch 11 | 12V | — (ESC has built-in) | MACE reaction wheel |
| FAN | Ch 12 | 12V | — (fan draws <1A) | Cooling fan |

---

## Trace Width Requirements

Current capacity depends on trace width and copper weight. At 2 oz copper:

| Current | Min Trace Width | Used For |
|---------|----------------|----------|
| 8A | 3.0 mm | 12V base/shoulder servo traces |
| 5A | 2.0 mm | 7.4V elbow servo traces |
| 3A | 1.2 mm | 5V wrist servo traces |
| <1A | 0.5 mm | Signal traces, I2C, fan |

GND uses a copper pour (ground plane) on the bottom layer.

---

## Board Layout Notes

- PCA9685 socket centrally placed — all PWM signal traces radiate outward
- Fuse holders along one edge or in two rows (one per arm)
- Servo headers along the board edges for easy cable access
- Power input screw terminals on one end
- I2C screw terminals grouped together near the PCA9685
- Keep high-current 12V traces short and wide
- Ground plane on bottom layer for star ground topology
- Board outline: target ~100mm x 80mm (verify against enclosure)

---

## Design Workflow

1. **Schematic** — KiCad 10, generated programmatically (`.kicad_sch`)
2. **PCB layout** — component placement and trace routing in KiCad
3. **DRC** — design rule check for trace widths, clearances
4. **Gerber export** — via `kicad-cli`
5. **Order** — JLCPCB, 2-layer, 2 oz copper

---

## Source Files

KiCad project files tracked in [zeulewan/geodude-control](https://github.com/zeulewan/geodude-control) under `pcb/geodude-carrier/`.
