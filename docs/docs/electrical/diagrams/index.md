# System Diagrams

Hierarchical block diagrams for both electrical systems. D2 rendered diagrams (SVG).

---

## Level 0: Test Setup Overview

Both systems at a glance - gimbal apparatus, linear rails, GEO-DUDe servicer, and the WiFi link between them.

![Test Setup Overview](L0-test-setup.svg)

---

## GEO-DUDe Power Distribution

Every fuse, wire gauge, connector, bus bar, and voltage rail in the 12V system. Includes power paths, signal routing (I2C, PWM), limit switches, and MACE reaction wheel.

![GEO-DUDe Power Distribution](L2-geodude-power.svg)

---

## Gimbal Wiring (24V System)

Complete 24V system - PSU, bus bar, TMC2209 drivers, ESP32 pins, stepper motors, decoupling caps.

![Gimbal Wiring (24V System)](L2-gimbal.svg)

---


---

## Diagram Source

D2 source files are in `docs/electrical/diagrams/`. To re-render after editing:

```bash
cd docs/electrical/diagrams
d2 --layout elk --theme 0 <file>.d2 <file>.svg
```

Requires [D2](https://d2lang.com/) installed.
