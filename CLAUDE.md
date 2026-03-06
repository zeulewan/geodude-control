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

### Mermaid Diagrams

Inline in Markdown files via superfences (configured in `zensical.toml`). Used for L0 and L1 comparison diagrams only.

## Skills

Diagram generation skills are saved at:
- `/Users/zeul/.claude/skills/d2-diagrams/SKILL.md` - D2 syntax reference and generation guide
- `/Users/zeul/.claude/skills/mermaid-diagrams/SKILL.md` - Mermaid syntax reference
- `/Users/zeul/.claude/skills/aer813-capstone/references/chart-making.md` - SVG style guide (PDR color palette)

## Serving

```bash
.venv/bin/zensical serve
```

Port 8813 by default.

## Google Sheet BOM

- **Spreadsheet ID:** `1E1N-070xhcGK5FVkjd1sBZlGc8as569FgII3UE0jsTo`
- **Subscale Satellite BOM** tab (rows 4-24)
- **Testing Apparatus BOM** tab (rows 4-17)

## Key Component Reference

### GEO-DUDe (12V System)
- 12V 600W PSU, 50A max
- 120V AC via 3-wire 15A slip ring
- 14 PWM servos (3 voltage rails: 12V, 7.4V, 5V)
- PCA9685 I2C PWM driver (all 14 servo signals)
- 3 buck converters (7.4V elbow, 5V Pi, 5V servo)
- 40A relay for power-on sequencing
- Cyrico 12-circuit fuse block with negative bus

### Gimbal (24V System)
- 24V 480W PSU, 20A max
- 4x TMC2209 stepper drivers (UART addressed, breadboard mounted)
- 4x stepper motors (yaw, pitch, roll, belt)
- ESP32 DOIT DevKit V1
- WiFi link to Raspberry Pi
