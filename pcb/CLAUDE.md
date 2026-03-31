# GEO-DUDe Carrier PCB — Agent Instructions

## Board Overview

150x118mm 2-layer carrier PCB for the GEO-DUDe subscale satellite. Interconnects: PCA9685 PWM driver, Pi Pico (SimpleFOC motor control), 10 servo outputs with per-servo fusing, and copper pours for power distribution.

## Design Workflow

The PCB design follows a collaborative human-agent workflow:

### 1. Netlist / Schematic (User + Agent)
The user provides the electrical requirements (what connects to what, which components, pin assignments). The agent translates this into net assignments on pads using the pcbnew Python API. There is no traditional KiCad schematic — nets are assigned programmatically.

**To add a new component:**
```python
import pcbnew
board = pcbnew.LoadBoard(PCB_FILE)
fp = pcbnew.FootprintLoad(LIBRARY_PATH, "FootprintName")
fp.SetReference("J_NEW")
fp.SetValue("Label")
fp.SetPosition(pcbnew.VECTOR2I(mm(x), mm(y)))
# Assign nets to pads
for pad in fp.Pads():
    if pad.GetNumber() == "1":
        pad.SetNet(board.FindNet("NET_NAME"))
board.Add(fp)
board.Save(PCB_FILE)
```

**To add a new net:**
```python
ni = pcbnew.NETINFO_ITEM(board, "NEW_NET")
board.Add(ni)
```

### 2. Footprint Creation (Agent)
Custom footprints are created from manufacturer source files when possible:
- Download EasyEDA/Eagle/KiCad design files from the component manufacturer
- Extract exact pad positions, drill sizes, and board dimensions
- Generate `.kicad_mod` files with verified geometry
- Use `easyeda2kicad` tool (pip) for LCSC component conversion
- Always verify pin-to-pin against datasheets before committing

### 3. Placement (User)
The user places components in KiCad GUI. The agent can assist with:
- Snapping to grid (`SetPosition`)
- Aligning groups (fuses to servos, etc.)
- Reordering components to minimize crossovers
- **Never move components without the user asking** — placement was a major pain point

### 4. Copper Pours (User + Agent)
User draws pour outlines in KiCad. Agent cleans up:
- Snaps near-horizontal/vertical edges (<10 degrees off) to exact H/V
- Keeps intentional diagonals
- Matches diagonal angles across pours for visual consistency (~24.5 degrees reference from +5V_SERVO pour)
- Removes and recreates zones via API (can't reliably modify zone outlines in-place due to SWIG issues)

### 5. Routing (Agent)
Agent runs `route_pcb.py` which:
1. Strips autorouted tracks (preserves manual tracks on excluded nets)
2. Exports Specctra DSN
3. Patches DSN with trace widths, via sizes, layer restrictions, net exclusions
4. Runs Freerouting autorouter
5. Imports SES results back into PCB

**Critical: close KiCad before routing.** The file lock prevents Python from saving. The `route_pcb.py` save step often fails due to SWIG memory corruption after track stripping. Use the two-step pattern:
```python
# Step 1: route_pcb.py strips and runs Freerouting
# Step 2: Fresh script imports SES
board = pcbnew.LoadBoard(PCB_FILE)  # fresh load
pcbnew.ImportSpecctraSES(board, SES_FILE)
board.Save(PCB_FILE)
# Step 3: Verify
board2 = pcbnew.LoadBoard(PCB_FILE)
print("Tracks:", len(board2.GetTracks()))
```

### 6. Manual Touch-up (User)
User routes the few connections Freerouting can't handle (congested areas, excluded nets). User also adds via stitching for ground planes.

### 7. DRC / JLCPCB Check (Agent)
Agent runs DRC via `kicad-cli pcb drc` and checks against JLCPCB design rules (trace width, spacing, via sizes, silkscreen, annular ring).

### 8. Export (Agent)
Gerbers + drill files exported via `kicad-cli`, zipped for JLCPCB upload.

## KiCad Project

- **Project:** `geodude-carrier/geodude-carrier.kicad_pcb` (KiCad 10)
- **Design tool:** KiCad on Mac (zmac, 100.117.222.41)
- **Python API:** `/Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/Current/bin/python3`
- **Freerouting:** `/tmp/freerouting.jar` with `/tmp/jdk-21.0.2.jdk/Contents/Home/bin/java`

## SWIG / pcbnew Python Gotchas

These bit us repeatedly — read before writing any pcbnew scripts:

1. **Memory corruption after removal:** After calling `board.Remove(fp)` on footprints or tracks, other Python references to board objects become invalid. The board object itself may still work for `Save()` but iterating footprints/tracks will crash. **Always save and reload in a separate script.**

2. **Split destructive operations:** Never remove + add + modify in the same script. Use: Script 1 (remove, save) → Script 2 (load, add, save) → Script 3 (load, modify, save).

3. **Zone outline modification:** `outline.RemoveAllContours()` + `NewOutline()` sometimes doesn't persist. Safer to remove the zone entirely and recreate it in a separate script.

4. **KiCad file lock:** When KiCad has the PCB open, `board.Save()` silently fails (writes 0 bytes or doesn't write). Always `osascript -e 'quit app "KiCad"'` and remove `.lck` file before running Python scripts.

5. **Via width API:** `via.GetWidth()` without a layer argument throws an assertion in KiCad 10. Use `via.GetWidth(pcbnew.F_Cu)` or just read `via.GetDrillValue()`.

6. **Footprint loading after removal:** `pcbnew.FootprintLoad()` can fail with `AttributeError: 'SwigPyObject'` if called in the same Python session where footprints were removed. Always save and start a fresh Python process.

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
# Full routing cycle (run on Mac via SSH from workstation):
ssh 100.117.222.41 "osascript -e 'quit app \"KiCad\"'"
ssh 100.117.222.41 "rm -f '...geodude-carrier/~geodude-carrier.kicad_pcb.lck'"
ssh 100.117.222.41 "'/Applications/KiCad/KiCad.app/.../python3' '.../route_pcb.py'"
# Then import SES with fresh load (avoids SWIG save bug):
ssh 100.117.222.41 "'/Applications/KiCad/KiCad.app/.../python3' -" < /tmp/route_debug.py
# Then open for review:
ssh 100.117.222.41 "open '.../geodude-carrier.kicad_pcb'"
```

### route_pcb.py internals
1. Strips autorouted tracks (preserves manual tracks on excluded nets like GND, +12V, GND_LOGIC, +12V_FOC)
2. Exports Specctra DSN
3. Patches DSN: trace widths per net class, via sizes (power 0.6/1.0mm, signal 0.3/0.6mm), layer restrictions (power F.Cu, signals B.Cu), excludes nets handled by pours
4. Runs Freerouting (headless, max 200 passes)
5. Imports SES — **save often fails due to SWIG corruption**, use separate script

### Freerouting DSN Patching Details
- **Net exclusion:** Remove `(net NETNAME (pins ...))` block from network section
- **Via sizes:** Use `(via_rule ...)` approach, NOT `(circuit (use_via ...))` — the latter has a clearance class matching bug that silently drops vias
- **Layer restriction:** `(circuit (use_layer "B.Cu"))` inside class definitions
- **Both via padstacks must be listed in structure:** `(via "Via[0-1]_600:300_um" "Via[0-1]_1000:600_um")`

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
KICAD_CLI='/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli'
PCB='geodude-carrier/geodude-carrier.kicad_pcb'
OUT='geodude-carrier/gerbers'

$KICAD_CLI pcb export gerbers $PCB -o $OUT/ -l 'F.Cu,B.Cu,F.SilkS,B.SilkS,F.Mask,B.Mask,Edge.Cuts,F.Paste,B.Paste'
$KICAD_CLI pcb export drill $PCB -o $OUT/ --format excellon

# Zip for JLCPCB
cd $OUT && zip -j ../geodude-carrier-gerbers.zip *.gtl *.gbl *.gto *.gbo *.gts *.gbs *.gtp *.gbp *.gm1 *.drl

# DRC
$KICAD_CLI pcb drc $PCB -o drc_report.txt --severity-all

# 3D renders
$KICAD_CLI pcb render $PCB -o render-top.png --side top --quality high --floor --perspective --width 3000 --height 2000 --background opaque --zoom 0.8
$KICAD_CLI pcb render $PCB -o render-bottom.png --side bottom --quality high --floor --perspective --width 3000 --height 2000 --background opaque --zoom 0.8
$KICAD_CLI pcb render $PCB -o render-angle.png --side top --quality high --floor --perspective --width 3000 --height 2000 --background opaque --zoom 0.7 --rotate 30,0,20
```

## Iteration Checklist

When the user asks for changes, follow this order:
1. **Netlist changes** — modify pad nets via pcbnew API script
2. **Let user save/place** — don't move components unless asked
3. **Close KiCad** — `osascript -e 'quit app "KiCad"'`
4. **Remove lock** — `rm -f ~geodude-carrier.kicad_pcb.lck`
5. **Route** — run route_pcb.py
6. **Import SES** — fresh LoadBoard → ImportSES → Save (separate script)
7. **Fix JLCPCB rules** — bump vias to 0.6mm dia, silk to 1.0mm/0.15mm
8. **DRC** — `kicad-cli pcb drc`
9. **Export gerbers** — zip to Desktop
10. **Open KiCad** — `open .kicad_pcb` for user review
