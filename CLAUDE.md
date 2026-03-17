# Subscale Satellite Documentation

AER813 Capstone project - subscale satellite test apparatus documentation site.

## Project Structure

- `docs/` - Zensical documentation source (Markdown)
- `docs/electrical/` - Electrical systems documentation
- `docs/electrical/diagrams/` - D2 diagram source files + rendered SVGs
- `docs/project/` - BOM, procurement tracking

## Diagram Workflow

### D2 Diagrams

Source `.d2` files live in `docs/electrical/diagrams/`. Rendered SVGs are committed alongside them.

**To render all diagrams:**
```bash
cd docs/electrical/diagrams
for f in *.d2; do d2 --layout elk --theme 0 "$f" "${f%.d2}.svg"; done
```

**D2 gotchas learned the hard way:**
- `#` starts a comment - always quote labels containing `#` (e.g., `d1: "TMC2209 #1"`)
- `()` defines shapes - always quote labels containing parentheses
- `->` in labels gets parsed as connections - quote or rephrase
- Don't add child nodes to containers after the container block closes
- Always use `--layout elk` for best results on block diagrams

## Skills

Diagram generation skills are saved at:
- `/Users/zeul/.claude/skills/d2-diagrams/SKILL.md` - D2 syntax reference and generation guide
- `/Users/zeul/.claude/skills/aer813-capstone/references/chart-making.md` - SVG style guide (PDR color palette)

## Serving

```bash
.venv/bin/zensical serve
```

Port 8813 by default.

## Google Sheet BOM

- **Spreadsheet ID:** `1E1N-070xhcGK5FVkjd1sBZlGc8as569FgII3UE0jsTo`
- **Subscale Satellite BOM** tab (rows 4-24 original, 27-40 additional wiring/discrete)
- **Testing Apparatus BOM** tab (rows 4-17 original, 19-26 additional wiring/discrete)

## Key Component Reference

### GEO-DUDe (12V System)
- 12V 600W PSU, 50A max
- 120V AC via 3-wire 15A slip ring
- 10 PWM servos (3 voltage rails: 12V, 7.4V, 5V)
- PCA9685 I2C PWM driver (all 10 servo signals)
- 3 buck converters (7.4V elbow, 5V Pi, 5V servo)
- 40A toggle switch for manual servo power control (Jtron Waterproof DC12V 40A/24V 20A, replaces relay + transistor driver)
- Per-servo fusing on custom servo bus boards (glass tube slow-blow, sized at 125% of normal operating current)
- 30A inline blade fuse on 12V trunk
- 6A slow-blow AC fuse on mains hot (must be AC-rated, not blade fuse)
- Trunk wiring: 2x 16 AWG parallel (~24A capacity, 30A fuse)
- Realistic load ~17A through toggle switch, stall worst-case ~42A
- Cyrico blade fuse block used for buck converter inputs and fan
- All per-servo fusing uses glass tube slow-blow fuses with inline holders (need to buy holders)

### Gimbal (24V System)
- 24V 480W PSU, 20A max
- 4x TMC2209 stepper drivers (UART addressed, breadboard for logic/signal)
- 4x NEMA 17 stepper motors (yaw, pitch, roll, belt)
- ESP32 DOIT DevKit V1 (powered separately via 5V USB)
- 12A main DC fuse, 14 AWG trunk
- WiFi link to Raspberry Pi
- Power wiring (VMOT, GND, motor outputs) via Wago lever connectors, NOT through breadboard (2A per motor exceeds breadboard contact rating)
- Need to buy: screw terminals for breadboard (plug into breadboard, accept wire via screw)
- TMC2209 drivers handle overcurrent protection (2A RMS limit), no per-motor fusing needed
