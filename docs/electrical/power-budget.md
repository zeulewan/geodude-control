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
| Shoulder (ANNIMOS 150kg) | 12V | 8.0A | 2 | ~16.0A | 12V bus direct |
| Elbow (ANNIMOS 80kg) | 7.4V | 5.0A | 2 | 10.0A | Buck conv 1 (7.4V) |
| Wrist rotate (RDS3218 20kg) | 5V | 1.6A | 2 | 3.2A | Buck conv 3 (5V) |
| Wrist pan (RDS3218 20kg) | 5V | 1.6A | 2 | 3.2A | Buck conv 3 (5V) |
| End-effector (MG90S) | 5V | 0.5A | 4 | 2.0A | Buck conv 3 (5V) |

### Other Loads

| Component | Voltage | Max Current | Power Source |
|-----------|---------|-------------|-------------|
| Raspberry Pi | 5V | 2.5A | Buck conv 2 (5V) |
| PCA9685 PWM driver | 5V | ~0.05A | Buck conv 2 (5V) |
| 12V fan | 12V | 0.15A | 12V bus direct |

### Current by Rail

| Rail | Components | Total Max Current | Capacity | Status |
|------|-----------|------------------|----------|--------|
| **12V direct** | 4x 150kg servos + fan | ~32A stall | 50A PSU (40A fused) | OK |
| **7.4V buck 1** | 2x 80kg elbow servos | 10A | 20A converter (8A fused at 12V in) | OK |
| **5V buck 2** | Pi + PCA9685 (always on) | ~2.6A | 20A converter (3A fused at 12V in) | OK |
| **5V buck 3** | 4x RDS3218 + 4x MG90S (after relay) | ~8.4A stall | 20A converter (8A fused at 12V in) | OK |

---

## Buck Converter Allocation

**Converter:** [20A 300W buck](https://www.amazon.ca/XLX-High-Power-Converter-Adjustable-Protection/dp/B081X5YX8V) - Input 6-40V, Output 1.25-36V adj, 20A max / 15A continuous

| Buck # | Output V | Load | Max Current | Headroom | Notes |
|--------|----------|------|-------------|----------|-------|
| 1 | 7.4V | 2x elbow servos | 10A stall | 5-10A spare | After relay (fuse block) |
| 2 | 5V | Pi + PCA9685 | ~2.6A | 12-17A spare | Before relay (always on) |
| 3 | 5V | 4x RDS3218 wrist + 4x MG90S | ~8.4A stall | 7-12A spare | After relay (fuse block) |
| 4 | - | **Spare** | - | - | |

---

## Fuse Sizing

| Fuse | Branch | Max Draw | Rating | Wire Gauge | Notes |
|------|--------|----------|--------|-----------|-------|
| AC inline | Mains hot before slip ring | ~5A @120V | **6A slow-blow** | Mains cable | |
| Main DC | 12V bus after PSU | ~40A worst case | **40A** | **8 AWG** | |
| Base servo branch | 2x base 150kg servos | 16A stall | **20A** | **12 AWG** | Split for fault isolation |
| Shoulder servo branch | 2x shoulder 150kg servos | 16A stall | **20A** | **12 AWG** | Split for fault isolation |
| Buck 1 input | Elbow servos at 12V in | ~6.2A | **8A** | 16 AWG | Fuse block circuit |
| Buck 2 input | Pi + PCA9685 at 12V in | ~1.1A | **3A** | 18 AWG | Before relay (always on) |
| Buck 3 input | Wrist + MG90S at 12V in | ~3.5A | **8A** | 16 AWG | Fuse block circuit |
| Fan line | 12V fan | 0.15A | **1A** | 22 AWG | Fuse block circuit |
| Apparatus main | 24V bus | ~8.6A | **12A** | 14 AWG | |
