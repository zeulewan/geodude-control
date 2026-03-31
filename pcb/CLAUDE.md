# GEO-DUDe Carrier PCB — Agent Instructions

## Board Overview

150x118mm 2-layer carrier PCB for the GEO-DUDe subscale satellite. Interconnects: PCA9685 PWM driver, Pi Pico (SimpleFOC motor control), 10 servo outputs with per-servo fusing, and copper pours for power distribution.

## KiCad Project

- **Project:** `geodude-carrier/geodude-carrier.kicad_pcb` (KiCad 10)
- **Design tool:** KiCad on Mac (zmac, 100.117.222.41)
- **Python API:** `/Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/Current/bin/python3`
- **Freerouting:** `/tmp/freerouting.jar` with `/tmp/jdk-21.0.2.jdk/Contents/Home/bin/java`

## Custom Footprints (in `geodude-carrier/`)

| File | Source | Verified |
|------|--------|----------|
| `SimpleFOC_Mini.kicad_mod` | EasyEDA design files (LCSC C30419) | 2x5 header, exact pad positions |
| `SparkFun_ICM20948.kicad_mod` | SparkFun Eagle board file (SEN-15335) | 25.4x25.4mm square, 22.86mm row spacing |
| `PCA9685_Breakout.kicad_mod` | Adafruit PCA9685 Rev C dimensions | 62 pads + 4 mounting holes |
| `AS5600_Encoder.kicad_mod` | Standard 1x4 I2C header | VCC, GND, SDA, SCL |
| `BLX-A_5x20mm.kicad_mod` | Measured from physical fuse holder | 22.2mm pin pitch |

## Routing Pipeline

Run `route_pcb.py` with KiCad's Python on the Mac. **Close KiCad first** — file lock prevents saving.

```bash
# On Mac:
osascript -e 'quit app "KiCad"'
/Applications/KiCad/KiCad.app/.../python3 route_pcb.py
```

The script:
1. Strips autorouted tracks (preserves manual tracks on excluded nets)
2. Exports DSN
3. Patches trace widths, via sizes, layer restrictions, and excludes nets
4. Runs Freerouting
5. Imports SES — **NOTE:** The main save often fails due to SWIG corruption. Use `route_debug.py` pattern (fresh LoadBoard → ImportSES → Save) to reliably persist.

**SWIG gotcha:** After removing footprints/tracks from a board object, the Python references corrupt. Always save and reload in a separate script before doing more operations.

## Excluded Nets (manual routing / pours)

These nets are removed from the DSN so Freerouting skips them:
- `GND` — F.Cu pour (servo/power ground)
- `+12V` — F.Cu pour (right side, covers J1/J2 and 12V fuses)
- `GND_LOGIC` — F.Cu pour (logic area, covers Pico/IMU/encoder/serial)
- `+12V_FOC` — manual routing (SimpleFOC power)

## Trace Widths (1oz copper, 10C rise, IPC-2221)

| Current | Width | Nets |
|---------|-------|------|
| 8A | 3.8mm | +12V, SV1/2/6/7_PWR, GND |
| 5A | 2.0mm | +7V4, SV3/8_PWR |
| 3A | 1.0mm | +5V_SERVO, SV4/5/9/10_PWR |
| 2.5A | 1.5mm | +12V_FOC, MOTOR_U/V/W |
| <1A | 0.6mm | +3V3, +5V_LOGIC, GND_LOGIC |
| Signal | 0.4mm | PWM, I2C, FOC control, serial |

## Layer Restrictions

- **F.Cu only:** Power traces (+12V, +7V4, +5V_SERVO, motor)
- **B.Cu only:** PWM signals, FOC control, serial
- **Both:** I2C (SDA/SCL, PICO_SDA/SCL), low power (+3V3), GND

## Key Net Assignments

### Pico Pin Map
| Pin | GPIO | Net |
|-----|------|-----|
| 1 | GP0 | PICO_TX |
| 2 | GP1 | PICO_RX |
| 6 | GP4 | PICO_SDA (IMU + encoder I2C) |
| 7 | GP5 | PICO_SCL (IMU + encoder I2C) |
| 14 | GP10 | FOC_EN |
| 15 | GP11 | FOC_IN3 |
| 16 | GP12 | FOC_IN2 |
| 19 | GP14 | FOC_IN1 |
| 36 | 3V3 | +3V3 |
| 3,8,13,18,23,28,33,38 | GND | GND_LOGIC |

### PCA9685 Channel Map (right to left on board)
| CH | Servo | Joint |
|----|-------|-------|
| 0 | SV1 | B1 (Base Arm1) |
| 1 | SV2 | S1 (Shoulder Arm1) |
| 2 | SV6 | B2 (Base Arm2) |
| 3 | SV7 | S2 (Shoulder Arm2) |
| 4 | SV3 | E1 (Elbow Arm1) |
| 5 | SV8 | E2 (Elbow Arm2) |
| 6 | SV4 | W1A (Wrist Arm1) |
| 7 | SV5 | W1B (Wrist Arm1) |
| 8 | SV9 | W2A (Wrist Arm2) |
| 9 | SV10 | W2B (Wrist Arm2) |

### SimpleFOC Mini v1.0 (J_FOC, 2x5 header)
| Pin | Signal | Net |
|-----|--------|-----|
| 1 | GND | GND_LOGIC |
| 2 | 3V3 out | NC |
| 3 | EN | FOC_EN |
| 5 | IN3 | FOC_IN3 |
| 7 | IN2 | FOC_IN2 |
| 9 | IN1 | FOC_IN1 |
| 11 | M1 (U) | MOTOR_U |
| 12 | M2 (V) | MOTOR_V |
| 13 | M3 (W) | MOTOR_W |
| 14 | GND pwr | GND |
| 15 | VIN | +12V_FOC |

### Two Separate I2C Buses
- **SDA/SCL:** Pi → PCA9685 (through J_SERIAL pins 3/4)
- **PICO_SDA/PICO_SCL:** Pico → IMU + Encoder

### Two Separate Grounds
- **GND:** Servo power, fan, FOC motor driver → bus bar
- **GND_LOGIC:** Pico, IMU, encoder, PCA9685, serial → bus bar
- Connected only at the external bus bar, NOT on this PCB

## Copper Pours (all on F.Cu)

| Net | Coverage |
|-----|----------|
| +12V | Right side — J1/J2 terminals through 12V fuses |
| +7V4 | Middle — 7.4V fuses area |
| +5V_SERVO | Left-center — 5V fuses area, diagonal to J6 terminal |
| GND | Bottom strip — servo/fuse row + right column for GND terminals |
| GND_LOGIC | Top-left — Pico, IMU, encoder, serial area |

Pour diagonals all follow the same slope (~24.5 degrees) for visual consistency.

## JLCPCB Fabrication

- **Layers:** 2
- **Copper:** 1oz
- **Thickness:** 1.6mm
- **Vias:** 0.3mm hole / 0.6mm diameter (free tier, 0.15mm annular ring)
- **Min trace:** 0.4mm (well above 0.127mm minimum)
- **Min spacing:** 0.2mm (above 0.127mm minimum)
- **Silkscreen:** min 1.0mm height, 0.15mm stroke
- **Gerbers:** `geodude-carrier-gerbers.zip`

## Export Commands

```bash
# Gerbers + drill (run on Mac)
kicad-cli pcb export gerbers geodude-carrier.kicad_pcb -o gerbers/ -l 'F.Cu,B.Cu,F.SilkS,B.SilkS,F.Mask,B.Mask,Edge.Cuts,F.Paste,B.Paste'
kicad-cli pcb export drill geodude-carrier.kicad_pcb -o gerbers/ --format excellon

# 3D renders
kicad-cli pcb render geodude-carrier.kicad_pcb -o render-top.png --side top --quality high --floor --perspective --width 3000 --height 2000
```
