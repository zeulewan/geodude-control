# Power Budget

Current draw estimates for all electrical loads. Values marked TBD need servo/motor datasheets to confirm.

---

## Apparatus (24V System)

| | |
|---|---|
| **PSU** | 24V, 480W (20A max) |

| Component | Voltage | Est. Max Current | Qty | Total Current | Source |
|-----------|---------|-----------------|-----|---------------|--------|
| Stepper motors | 24V | TBD | 4 | TBD | Need datasheet |
| TMC2209 drivers | 24V | ~2A per driver (RMS) | 4 | ~8A | TMC2209 rated 2A RMS |
| 24V 80mm fans | 24V | ~0.15A | 4 | ~0.6A | Typical 80mm fan |
| ESP32 | 3.3V (onboard reg) | ~0.5A | 1 | ~0.5A | |
| **Total estimated** | | | | **~9.1A** | **Well within 20A PSU** |

---

## Subscale Satellite (12V System)

| | |
|---|---|
| **PSU** | 12V, 600W (50A max) |

| Component | Voltage | Est. Stall Current | Qty | Total Stall Current | Source |
|-----------|---------|-------------------|-----|--------------------|---------|
| Base servos (150kg) | TBD (~7.4V) | TBD (~4-5A) | 2 | TBD (~8-10A) | Need datasheet |
| Shoulder servos (150kg) | TBD (~7.4V) | TBD (~4-5A) | 2 | TBD (~8-10A) | Need datasheet |
| Elbow servos (80kg) | TBD (~7.4V) | TBD (~3-4A) | 2 | TBD (~6-8A) | Need datasheet |
| Wrist smart servos (20kg) | TBD (~7.4V) | TBD (~1.5A) | 4 | TBD (~6A) | Need datasheet |
| MG90S end-effector | 5V | ~0.5A | 4 | ~2A | MG90S typical |
| Raspberry Pi | 5V | ~2.5A | 1 | ~2.5A | Pi 4/5 typical |
| Pi Camera | 5V (via Pi) | ~0.25A | 1 | included in Pi | |
| I2C Expander | 3.3V (via Pi) | negligible | 1 | negligible | |
| Waveshare driver | 5V | ~0.5A | 1 | ~0.5A | Board logic only |
| 12V fan | 12V | ~0.15A | 1 | ~0.15A | |
| **Total estimated** | | | | **~35-39A at 12V** | **Within 50A PSU** |

!!! warning "Stall current is worst case"
    Normal operating current is much lower than stall. But fuses and wiring must be sized for stall conditions to prevent fires. The estimates above are rough - actual values from datasheets may differ significantly.

---

## Buck Converter Loading

Each buck converter needs to handle the load of its branch. The [listed converter](https://www.amazon.ca/XLX-High-Power-Converter-Adjustable-Protection/dp/B081X5YX8V) max current rating needs to be checked against these loads.

| Buck # | Output V | Load | Est. Max Current | Converter OK? |
|--------|----------|------|-----------------|---------------|
| 1 | ~7.4V | 2x base servos | TBD (~8-10A) | TBD |
| 2 | ~7.4V | 2x shoulder servos | TBD (~8-10A) | TBD |
| 3 | ~7.4V | 2x elbow servos | TBD (~6-8A) | TBD |
| 4 | 5V | Pi + MG90S + driver | ~5.5A | TBD |

---

## Fuse Sizing

Fuses sized at 125-150% of expected max draw per branch.

| Fuse | Branch | Max Draw | Fuse Rating |
|------|--------|----------|-------------|
| Main (apparatus) | 24V bus | ~9.1A | TBD |
| Main (subscale) | 12V bus | ~39A | TBD |
| Buck 1 input | Base servos | TBD | TBD |
| Buck 2 input | Shoulder servos | TBD | TBD |
| Buck 3 input | Elbow servos | TBD | TBD |
| Buck 4 input | Pi + micro servos | ~5.5A | 8A |
| Fan (subscale) | 12V fan | ~0.15A | 1A |
