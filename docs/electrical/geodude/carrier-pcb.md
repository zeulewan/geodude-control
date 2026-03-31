# GEO-DUDe Carrier PCB

Custom 2-layer PCB replacing the perfboard. Central interconnect for all GEO-DUDe electronics: PCA9685 PWM driver socket, per-servo fusing, logic bus breakout, and servo/ESC/fan headers.

---

## Design Summary

| | |
|---|---|
| **Replaces** | Perfboard fuse board |
| **Tool** | KiCad 10.0.0 |
| **Fab target** | JLCPCB |
| **Layers** | 2 (front: power, back: signals) |
| **Copper weight** | 2 oz (high-current traces) |
| **Board size** | 190 x 160 mm |

---

## Power Rails (5 separate rails)

| Rail | Net | Source | Used For |
|------|-----|--------|----------|
| 12V | `+12V` | Toggle switch / bus | Base/shoulder servos, ESC, fan |
| 7.4V | `+7V4` | Buck converter 1 | Elbow servos |
| 5V servo | `+5V_SERVO` | Buck converter 3 | Wrist servos |
| 5V logic | `+5V_LOGIC` | Pi 5V pin | General logic |
| 3.3V | `+3V3` | Pi 3.3V pin | PCA9685 VCC, I2C bus |

## Ground (2 separate nets)

| Net | Used For | Returns To |
|-----|----------|------------|
| `GND` | Servo power, ESC, fan | GND bus bar |
| `GND_LOGIC` | I2C, PCA9685, sensors | GND bus bar |

Both connect at the bus bar only — not on this PCB.

---

## Right Edge — Servo Power Input

| Terminal | Pins | Net |
|----------|------|-----|
| J1 | 2x | +12V (both pins) |
| J2 | 2x | +12V (both pins) |
| J3 | 2x | GND (both pins) |
| J4 | 2x | GND (both pins) |
| J5 | pin1: +7V4, pin2: GND | 7.4V input |
| J6 | pin1: +5V_SERVO, pin2: GND | 5V servo input |

12V and GND: 4 pins each = 40A capacity (10A per pin).

---

## Left Edge — Logic Bus

Each bus has 2x screw terminals + 1x 4-pin header (all same net). Plug in any I2C device, sensor, or logic wire.

| Bus | Net | Screw Terminals | Pin Header |
|-----|-----|-----------------|------------|
| SCL | `SCL` | 2x 2-pin | 1x 4-pin |
| SDA | `SDA` | 2x 2-pin | 1x 4-pin |
| 3.3V | `+3V3` | 2x 2-pin | 1x 4-pin |
| 5V | `+5V_LOGIC` | 2x 2-pin | 1x 4-pin |
| Logic GND | `GND_LOGIC` | 2x 2-pin | 1x 4-pin |

---

## Top Edge — PCA9685 Socket

1x19 female header socket. PCA9685 breakout plugs in directly. Control pins (VCC, GND, SDA, SCL, OE) wired via Dupont from PCA breakout to the logic bus — not routed through this socket.

| Socket Pin | PCA9685 Ch | Socket Pin | PCA9685 Ch |
|------------|-----------|------------|-----------|
| 1 | Ch 0 | 11 | Ch 8 |
| 2 | Ch 1 | 12 | Ch 9 |
| 3 | Ch 2 | 13 | Ch 10 |
| 4 | Ch 3 | 14 | Ch 11 (ESC) |
| 5 | NC (cap gap) | 15 | NC (cap gap) |
| 6 | Ch 4 | 16 | Ch 12 (Fan) |
| 7 | Ch 5 | 17 | Ch 13 |
| 8 | Ch 6 | 18 | Ch 14 |
| 9 | Ch 7 | 19 | Ch 15 |
| 10 | NC (cap gap) | | |

Pin 1 on the right side (facing board).

---

## Middle — Fuse Holders

10x BLX-A 5x20mm PCB-mount fuse holders (22.2mm pin pitch, 1.5mm drill). Two columns: arm 1 (left), arm 2 (right). Silkscreen labeled with servo name.

| Fuse | Label | Rating | Rail | Servo |
|------|-------|--------|------|-------|
| F1 | B1 | 8A | +12V | Arm 1 Base |
| F2 | S1 | 8A | +12V | Arm 1 Shoulder |
| F3 | E1 | 5A | +7V4 | Arm 1 Elbow |
| F4 | W1A | 3A | +5V_SERVO | Arm 1 Wrist Rotate |
| F5 | W1B | 3A | +5V_SERVO | Arm 1 Wrist Pan |
| F6 | B2 | 8A | +12V | Arm 2 Base |
| F7 | S2 | 8A | +12V | Arm 2 Shoulder |
| F8 | E2 | 5A | +7V4 | Arm 2 Elbow |
| F9 | W2A | 3A | +5V_SERVO | Arm 2 Wrist Rotate |
| F10 | W2B | 3A | +5V_SERVO | Arm 2 Wrist Pan |

---

## Bottom Edge — Output Headers

### Servo Headers (10x 3-pin male)

Pin order: Signal (PWM) | Power (fused V+) | GND

| Header | Label | PCA Ch | Fuse |
|--------|-------|--------|------|
| SV1 | B1 | Ch 0 | F1 |
| SV2 | S1 | Ch 1 | F2 |
| SV3 | E1 | Ch 2 | F3 |
| SV4 | W1A | Ch 3 | F4 |
| SV5 | W1B | Ch 4 | F5 |
| SV6 | B2 | Ch 5 | F6 |
| SV7 | S2 | Ch 6 | F7 |
| SV8 | E2 | Ch 7 | F8 |
| SV9 | W2A | Ch 8 | F9 |
| SV10 | W2B | Ch 9 | F10 |

### Fan Header (2x4 pin male)

Row 1 (fan connector): GND, +12V_FAN, Tach, PWM (Ch 12)
Row 2 (Pi jumper): NC, NC, Tach, PWM (mirror for wiring to Pi GPIO)

### SimpleFOC Motor Control

Replaces the old ESC. Uses Pi Pico + SimpleFOC mini driver + 2804 hollow shaft motor with AS5600 encoder.

| Header | Pins | Description |
|--------|------|-------------|
| J_PICO | 2x20 female | Pi Pico socket — runs SimpleFOC firmware |
| J_FOC | 1x11 male | SimpleFOC mini v1.1 driver board socket |
| J_MOTOR | 1x3 male | Motor UVW phase outputs |
| J_IMU | 1x9 male | SparkFun ICM-20948 9DoF IMU breakout (Qwiic) |
| J_ENC | 1x4 male | AS5600 encoder (I2C, on motor) |
| J_SERIAL | 1x4 male | Pico ↔ Pi serial link (TX, RX, GND, 3V3) |

**Pico pin assignments:**

| Pico Pin | GPIO | Function |
|----------|------|----------|
| 1 | GP0 | TX → Pi serial |
| 2 | GP1 | RX ← Pi serial |
| 6 | GP4 | SDA (IMU + encoder I2C) |
| 7 | GP5 | SCL (IMU + encoder I2C) |
| 9 | GP6 | FOC IN1 (PWM) |
| 10 | GP7 | FOC IN2 (PWM) |
| 11 | GP8 | FOC IN3 (PWM) |
| 12 | GP9 | FOC EN (enable) |
| 38 | GND | Ground |

**SimpleFOC mini v1.1 pins:**

| Pin | Signal | Connection |
|-----|--------|------------|
| 1 | GND | GND |
| 2 | VIN | +12V bus |
| 3 | EN | Pico GP9 |
| 4 | IN3 | Pico GP8 |
| 5 | IN2 | Pico GP7 |
| 6 | IN1 | Pico GP6 |
| 7 | GND | GND |
| 8-11 | nRT/nSP/nFT/3V3 | NC (optional) |

---

## Trace Widths

| Current | Width | Nets |
|---------|-------|------|
| 8A | 3.0 mm | +12V, GND, base/shoulder fused power |
| 5A | 2.0 mm | +7V4, elbow fused power |
| 3A | 1.5 mm | +5V_SERVO, wrist fused power |
| <1A | 0.6 mm | +5V_LOGIC, +3V3, GND_LOGIC |
| Signal | 0.4 mm | PWM, SDA, SCL |

Front copper: power traces. Back copper: signal traces. Freerouting autorouter handles 2-layer routing.

---

## Design Workflow (headless)

```
generate_pcb.py → place components, assign nets (pcbnew Python API)
    ↓
route_pcb.py → export DSN → patch trace widths → Freerouting → import SES
    ↓
kicad-cli pcb drc → verify
    ↓
kicad-cli pcb export svg → visual preview
    ↓
kicad-cli pcb export gerbers → fab files for JLCPCB
```

No GUI required. Human reviews SVG/KiCad for final placement tweaks.

---

## Components

| Part | Footprint | Qty |
|------|-----------|-----|
| 2-pin 5mm screw terminal | TerminalBlock_MaiXu_MX126-5.0-02P | 16 |
| 1x4 pin header 2.54mm | PinHeader_1x04_P2.54mm_Vertical | 5 |
| 1x3 pin header 2.54mm | PinHeader_1x03_P2.54mm_Vertical | 12 |
| 1x19 female socket 2.54mm | PinSocket_1x19_P2.54mm_Vertical | 1 |
| BLX-A 5x20mm fuse holder | Custom (22.63mm pitch, 1.5mm drill) | 10 |

---

## Source Files

KiCad project: [zeulewan/geodude-control](https://github.com/zeulewan/geodude-control) → `pcb/geodude-carrier/`
