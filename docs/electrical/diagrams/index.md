# System Diagrams

3-level hierarchical block diagrams for both electrical systems. D2 rendered diagrams (SVG).

---

## Level 0: Test Setup Overview

Both systems at a glance - gimbal apparatus, linear rails, GEO-DUDe servicer, and the WiFi link between them.

![Test Setup Overview](L0-test-setup.svg)

---

## Level 1a: GEO-DUDe System Overview

Full 12V system - AC mains through slip ring, PSU, toggle switch, buck converters, servo bus boards, and all servo groups.

![GEO-DUDe System Overview](L1-geodude.svg)

---

## Level 1b: Gimbal System Overview

Full 24V stepper system - PSU, TMC2209 drivers, 4 stepper motors, ESP32, and fans.

![Gimbal System Overview](L1-gimbal.svg)

---

## Level 2a: GEO-DUDe Power Distribution Detail

Every fuse, wire gauge, connector, and voltage rail in the 12V system.

![GEO-DUDe Power Detail](L2-geodude-power.svg)

---

## Level 2b: GEO-DUDe Signal Routing Detail

All signal connections - I2C, PCA9685 PWM channels, limit switch GPIOs, camera.

![GEO-DUDe Signal Detail](L2-geodude-signal.svg)

---

## Level 2c: Gimbal TMC2209 Wiring Detail

ESP32 pin assignments, STEP/DIR connections, UART bus, MS1/MS2 addressing, decoupling caps.

![Gimbal TMC2209 Wiring Detail](L2-gimbal-wiring.svg)

---

## Diagram Source

D2 source files are in `docs/electrical/diagrams/`. To re-render after editing:

```bash
cd docs/electrical/diagrams
d2 --layout elk --theme 0 <file>.d2 <file>.svg
```

Requires [D2](https://d2lang.com/) installed (`brew install d2`)
