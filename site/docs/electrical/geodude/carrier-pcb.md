# GEO-DUDe Carrier PCB

Custom 2-layer PCB replacing the perfboard. Central interconnect for all GEO-DUDe electronics: PCA9685 PWM driver socket, SimpleFOC motor control, per-servo fusing, and servo/fan headers.

---

## Design Summary

| | |
|---|---|
| **Replaces** | Perfboard fuse board |
| **Tool** | KiCad 10.0.0 |
| **Fab target** | JLCPCB |
| **Layers** | 2 (front: power, back: signals) |
| **Copper weight** | 2 oz (high-current traces) |
| **Board size** | 170 x 112 mm |

---

## Power Rails (6 separate rails)

| Rail | Net | Source | Used For |
|------|-----|--------|----------|
| 12V | `+12V` | Toggle switch / bus | Base/shoulder servos, fan |
| 12V FOC | `+12V_FOC` | Separate switch | SimpleFOC motor driver (independent from servos) |
| 7.4V | `+7V4` | Buck converter 1 | Elbow servos |
| 5V servo | `+5V_SERVO` | Buck converter 3 | Wrist servos |
| 5V logic | `+5V_LOGIC` | Pi 5V pin | General logic |
| 3.3V | `+3V3` | Pi 3.3V pin | PCA9685 VCC, I2C bus, IMU, encoder |

## Ground (2 separate nets)

| Net | Used For | Returns To |
|-----|----------|------------|
| `GND` | Servo power, fan, FOC motor driver | GND bus bar |
| `GND_LOGIC` | I2C, PCA9685, IMU, encoder | GND bus bar |

Both connect at the bus bar only — not on this PCB.

---

## Right Edge — Power Input Terminals

| Terminal | Pins | Net |
|----------|------|-----|
| J_FOC_12V | pin1: +12V_FOC, pin2: GND | FOC motor power (separate switch) |
| J1 | 2x | +12V (both pins) |
| J2 | 2x | +12V (both pins) |
| J5 | pin1: +7V4, pin2: GND | 7.4V input |
| J6 | pin1: +5V_SERVO, pin2: GND | 5V servo input |
| J3 | 2x | GND (both pins) |
| J4 | 2x | GND (both pins) |

---

## PCA9685 Socket (J_PCA)

Custom footprint matching the Adafruit PCA9685 16-channel PWM driver breakout (62×25mm). The breakout plugs directly into the carrier board.

**Servo output pads (48 pins):** 4 blocks of 3×4 (Signal, V+, GND per channel). Signal pads wired to PWM_CH0–CH15. V+ pads unconnected (power routed separately through fuses). GND pads wired to GND.

**Control headers (2× 1×6):** Left and right side headers — VCC (+3V3), SDA, SCL, GND_LOGIC connected. OE and V+ left NC.

**Terminal block (2 pins):** NC (servo power supplied through fuses).

**Mounting holes (4×):** M2.5 for standoffs.

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

Replaces the old ESC. Uses Pi Pico + SimpleFOC Mini v1.0 driver (DRV8313) + 2804 hollow shaft BLDC motor with AS5600 encoder.

| Header | Footprint | Description |
|--------|-----------|-------------|
| J_PICO | RaspberryPi_Pico_Common_THT | Pi Pico socket — runs SimpleFOC firmware |
| J_FOC | Custom (20 pads) | SimpleFOC Mini v1.0 full board socket (MCU header + motor output + power + mounting) |
| J_IMU | Custom (2×6, 19mm apart) | SparkFun ICM-20948 9DoF IMU breakout — two 1×6 headers on opposite board edges |
| J_ENC | PinHeader_1x04 | AS5600 encoder I2C cable (VCC, GND, SDA, SCL) — encoder lives on motor |
| J_SERIAL | PinHeader_1x04 | Pico ↔ Pi serial link (TX, RX, GND, 3V3) |

**J_FOC pad map (SimpleFOC Mini v1.0, from EasyEDA design files):**

| Pad | Signal | Net | Section |
|-----|--------|-----|---------|
| 1 | GND | GND | MCU header (2×5) |
| 2 | 3V3 out | — | MCU header |
| 3 | EN | FOC_EN | MCU header |
| 4 | GND | GND | MCU header |
| 5 | IN3 | FOC_IN3 | MCU header |
| 6 | nRESET | — | MCU header |
| 7 | IN2 | FOC_IN2 | MCU header |
| 8 | nSLEEP | — | MCU header |
| 9 | IN1 | FOC_IN1 | MCU header |
| 10 | nFAULT | — | MCU header |
| 11 | M1 (U) | — | Motor output (1×3) |
| 12 | M2 (V) | — | Motor output |
| 13 | M3 (W) | — | Motor output |
| 14 | GND | GND | Power terminal |
| 15 | VIN | +12V_FOC | Power terminal |
| 16–19 | GND | GND | Corner mounting pads |
| 20 | GND | GND | Extra GND pad |

Motor UVW order doesn't matter — SimpleFOC handles commutation direction in firmware.

**Pico pin assignments (PCB version):**

| Pico Pin | GPIO | Function |
|----------|------|----------|
| 1 | GP0 | TX → Pi serial |
| 2 | GP1 | RX ← Pi serial |
| 6 | GP4 | SDA (IMU + encoder I2C) |
| 7 | GP5 | SCL (IMU + encoder I2C) |
| 14 | GP10 | FOC EN (enable) |
| 15 | GP11 | FOC IN3 (PWM) |
| 16 | GP12 | FOC IN2 (PWM) |
| 19 | GP14 | FOC IN1 (PWM) |
| 38 | GND | Ground |

!!! note "Two hardware versions"
    The table above is for the **carrier PCB** (routed layout). The **perfboard prototype** uses different Pico GPIO pins for the FOC signals — update this section once perfboard wiring is confirmed. Serial (GP0/1) and I2C (GP4/5) are the same on both versions.

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
| 2-pin 5mm screw terminal | TerminalBlock_MaiXu_MX126-5.0-02P | 7 |
| 1x3 pin header 2.54mm | PinHeader_1x03_P2.54mm_Vertical | 11 |
| 1x4 pin header 2.54mm | PinHeader_1x04_P2.54mm_Vertical | 2 |
| BLX-A 5x20mm fuse holder | Custom (22.2mm pitch, 1.5mm drill) | 10 |
| PCA9685 breakout socket | Custom (62 pads + 4 mounting) | 1 |
| SimpleFOC Mini socket | Custom (20 pads, from EasyEDA) | 1 |
| SparkFun ICM-20948 socket | Custom (12 pads, 19mm row spacing) | 1 |
| Pi Pico socket | RaspberryPi_Pico_Common_THT | 1 |
| 2x4 pin header 2.54mm | PinHeader_2x04_P2.54mm_Vertical | 1 |

---

## Source Files

KiCad project: [zeulewan/geodude-control](https://github.com/zeulewan/geodude-control) → `pcb/geodude-carrier/`
