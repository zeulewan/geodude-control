# Power Budget

Current draw calculations based on component datasheets. All servos are dumb PWM.

---

## Apparatus (24V System)

| | |
|---|---|
| **PSU** | 24V, 480W (20A max) |
| **ESP32** | Powered separately via 5V USB adapter |

| Component | Voltage | Max Current (each) | Qty | Total Current | Source |
|-----------|---------|-------------------|-----|---------------|--------|
| Stepper motors (via TMC2209) | 24V | 2A RMS (driver limited) | 4 | ~8A | TMC2209 spec |
| 24V 80mm fans | 24V | ~0.15A | 4 | ~0.6A | Typical 80mm fan |
| **Total** | | | | **~8.6A** | **43% of 20A PSU** |

---

## GEO-DUDe (12V System)

| | |
|---|---|
| **PSU** | 12V, 600W (50A max) |
| **AC input** | 120V mains through 3-wire 15A slip ring |

### Servo Specifications

| Servo | Voltage | Stall Current (each) | Qty | Total Stall | Power Source |
|-------|---------|---------------------|-----|-------------|-------------|
| Base (HOOYIJ 150kg) | 12V | 8.0A | 2 | 16.0A | 12V bus direct |
| Shoulder (ANNIMOS 150kg) | 12V | ~8.0A (confirm) | 2 | ~16.0A | 12V bus direct |
| Elbow (ANNIMOS 80kg) | 7.4V | 5.0A | 2 | 10.0A | Buck conv 1 (7.4V) |
| Wrist rotate (TBD ~20kg) | TBD | TBD | 2 | TBD | TBD |
| Wrist pan (TBD ~20kg) | TBD | TBD | 2 | TBD | TBD |
| End-effector (MG90S) | 5V | 0.5A | 4 | 2.0A | Buck conv 2 (5V) |

### Other Loads

| Component | Voltage | Max Current | Power Source |
|-----------|---------|-------------|-------------|
| Raspberry Pi | 5V | 2.5A | Buck conv 2 (5V) |
| PCA9685 PWM driver | 5V | ~0.05A | Buck conv 2 (5V) |
| 12V fan | 12V | 0.15A | 12V bus direct |

### Current by Rail

| Rail | Components | Total Max Current | Capacity | Status |
|------|-----------|------------------|----------|--------|
| **12V direct** | 4x 150kg servos + fan + wrist (TBD) | ~32A + TBD | 50A PSU | OK |
| **7.4V buck** | 2x 80kg elbow servos | 10A | 20A converter | OK |
| **5V buck** | Pi + 4x MG90S + PCA9685 | ~5A | 20A converter | OK |

---

## Buck Converter Allocation

**Converter:** [20A 300W buck](https://www.amazon.ca/XLX-High-Power-Converter-Adjustable-Protection/dp/B081X5YX8V) - Input 6-40V, Output 1.25-36V adj, 20A max / 15A continuous

| Buck # | Output V | Load | Max Current | Headroom | Notes |
|--------|----------|------|-------------|----------|-------|
| 1 | 7.4V | 2x elbow servos | 10A stall | 5-10A spare | OK |
| 2 | 5V | Pi + MG90S + PCA9685 | ~5A | 10-15A spare | OK |
| 3 | - | **Spare** | - | - | |
| 4 | - | **Spare** | - | - | |

---

## Fuse Sizing

| Fuse | Branch | Max Draw | Rating | Notes |
|------|--------|----------|--------|-------|
| AC inline | Mains hot before slip ring | ~5A @120V | **6A slow-blow** | |
| Main DC | 12V bus after PSU | ~40A+ worst case | **50A** | |
| 12V servo branch | Base + shoulder + wrist + fan | ~32A+ stall | **40A** | May split into separate branches |
| Buck 1 input | Elbow servos at 12V in | ~6.2A | **8A** | |
| Buck 2 input | Pi + MG90S at 12V in | ~2A | **3A** | |
| Fan line | 12V fan | 0.15A | **1A** | |
| Apparatus main | 24V bus | ~8.6A | **12A** | |
