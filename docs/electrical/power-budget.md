# Power Budget

Current draw calculations based on component datasheets.

---

## Apparatus (24V System)

| | |
|---|---|
| **PSU** | 24V, 480W (20A max) |

| Component | Voltage | Max Current (each) | Qty | Total Current | Source |
|-----------|---------|-------------------|-----|---------------|--------|
| Stepper motors | 24V | ~2A (TMC2209 limited) | 4 | ~8A | [TMC2209 rated 2A RMS](https://www.amazon.ca/BIGTREETECH-TMC2209-Stepper-Stepstick-Heatsink/dp/B0CQC7QMS2) |
| 24V 80mm fans | 24V | ~0.15A | 4 | ~0.6A | Typical 80mm fan |
| ESP32 | 3.3V (onboard reg) | ~0.5A | 1 | ~0.5A | |
| **Total** | | | | **~9.1A** | **46% of 20A PSU** |

---

## GEO-DUDe (12V System)

| | |
|---|---|
| **PSU** | 12V, 600W (50A max) |

### Servo Specifications (from datasheets)

| Servo | Model | Voltage Range | Stall Current | Stall Torque | Signal | Source |
|-------|-------|--------------|---------------|-------------|--------|--------|
| Base (150kg) | HOOYIJ RDS51150 | **10-12.6V** | 7.4A@10V, 8.0A@12V, 8.3A@12.6V | 150/165/173 kg-cm | PWM 500-2500us | [Amazon](https://www.amazon.com/HOOYIJ-RDS51150-Steering-U-Shaped-Brackets/dp/B0CP126F77) |
| Shoulder (150kg) | ANNIMOS 150kg | **10-12.6V** (assumed, confirm) | ~7-8A (assumed, confirm) | ~150 kg-cm | PWM 500-2500us | [Amazon](https://www.amazon.ca/ANNIMOS-Voltage-Digital-Steering-Brackets/dp/B0C69W2QP7) |
| Elbow (80kg) | ANNIMOS DS-series | **6-8.4V** | 4.1A@6V, 5A@7.4V, 6.5A@8.4V | 85/98/105 kg-cm | PWM 500-2500us | [Amazon](https://www.amazon.com/ANNIMOS-Waterproof-Digital-Steering-Brackets/dp/B0C69WWLWQ) |
| Wrist (20kg) | Feetech STS3215 | **4-7.4V** | 2-2.5A | 19.5 kg-cm @7.4V | TTL serial (half-duplex) | [Datasheet](https://core-electronics.com.au/attachments/uploads/sts3215-smart-servo-datasheet-translated.pdf) |
| End-effector | MG90S | **4.8-6V** | ~0.5A | 2 kg-cm | PWM | Standard MG90S |

### Current Budget

| Component | Buck # | Voltage | Stall Current (each) | Qty | Total Stall | At 12V input |
|-----------|--------|---------|---------------------|-----|-------------|-------------|
| Base servos (HOOYIJ 150kg) | 1 | 12V | 8.0A | 2 | **16.0A** | 16.0A |
| Shoulder servos (ANNIMOS 150kg) | 2 | 12V (TBC) | ~8.0A (TBC) | 2 | **~16.0A** | ~16.0A |
| Elbow servos (ANNIMOS 80kg) | 3 | 7.4V | 5.0A | 2 | **10.0A** | ~6.2A |
| Wrist smart servos (STS3215) | via Waveshare | 7.4V | 2.5A | 4 | **10.0A** | ~6.2A |
| MG90S end-effector | 4 | 5V | 0.5A | 4 | **2.0A** | ~0.8A |
| Raspberry Pi | 4 | 5V | 2.5A | 1 | **2.5A** | ~1.0A |
| Waveshare driver | 4 | 5V | 0.5A | 1 | **0.5A** | ~0.2A |
| I2C Expander | 4 | 3.3V (via Pi) | negligible | 1 | - | - |
| 12V fan | direct | 12V | 0.15A | 1 | **0.15A** | 0.15A |
| **Total at 12V input** | | | | | | **~46.6A** |

!!! danger "Worst-case stall is 46.6A - close to 50A PSU limit"
    This is absolute worst case (all servos stalling simultaneously), which is unlikely in practice. Normal operating current is much lower. But the PSU has only ~7% headroom at full stall.

---

## Buck Converter Verification

**Converter specs:** [20A 300W buck converter](https://www.amazon.ca/XLX-High-Power-Converter-Adjustable-Protection/dp/B081X5YX8V) - Input 6-40V, Output 1.25-36V, **20A max (15A continuous recommended)**

| Buck # | Output V | Load | Stall Current | Power at Output | Converter Rating | Status |
|--------|----------|------|---------------|----------------|-----------------|--------|
| 1 | 12V | 2x base servos (150kg) | **16.0A** | 192W | 20A / 300W | :warning: **AT LIMIT** - stall exceeds 15A continuous |
| 2 | 12V | 2x shoulder servos (150kg) | **~16.0A** | ~192W | 20A / 300W | :warning: **AT LIMIT** - same issue |
| 3 | 7.4V | 2x elbow servos (80kg) | **10.0A** | 74W | 20A / 300W | :white_check_mark: OK |
| 4 | 5V | Pi + MG90S + Waveshare | **5.5A** | 27.5W | 20A / 300W | :white_check_mark: OK |

!!! danger "Buck converters 1 and 2 are marginal for 150kg servos"
    Two 150kg servos at stall draw 16A, which exceeds the 15A continuous rating. Options:

    1. **Run base/shoulder servos directly off 12V PSU** (they're rated 10-12.6V, the PSU is 12V) - skip the buck converter entirely
    2. **Add a second buck converter per branch** and split the servos (1 servo per converter)
    3. **Accept the risk** since sustained stall is unlikely in normal operation

    **Option 1 is recommended** - the 12V PSU output matches the servo voltage range perfectly, so buck converters 1 and 2 may be unnecessary. Use them as spares or reassign to the wrist servos.

### Wrist Servo Power Path

The 4 Feetech STS3215 wrist servos (7.4V, 2.5A stall each = 10A total) need their own power. Options:

- Use one of the freed-up buck converters (set to 7.4V) - 10A is well within 20A rating
- Power through the Waveshare driver board (check if it has onboard regulation)

---

## Revised Buck Converter Allocation (Recommended)

| Buck # | Output V | Feeds | Max Current | Status |
|--------|----------|-------|-------------|--------|
| ~~1~~ | - | Base servos run direct from 12V bus | - | Not needed |
| ~~2~~ | - | Shoulder servos run direct from 12V bus | - | Not needed |
| 3 | 7.4V | 2x elbow servos (80kg) | 10.0A | OK |
| 4 | 5V | Pi + MG90S + Waveshare driver | 5.5A | OK |
| Spare | 7.4V | 4x wrist smart servos (STS3215) | 10.0A | OK |
| Spare | - | Available as backup | - | |

---

## Fuse Sizing

Fuses sized at 125-150% of expected max draw per branch.

| Fuse | Branch | Max Draw | Fuse Rating | Notes |
|------|--------|----------|-------------|-------|
| AC inline | Mains to PSU | ~5A at 120V | **6A slow-blow** | Before slip ring |
| Main DC | 12V bus | ~46.6A worst case | **50A** | After PSU output |
| Base servo branch | 2x 150kg direct from 12V | 16A | **20A** | |
| Shoulder servo branch | 2x 150kg direct from 12V | ~16A | **20A** | |
| Buck 3 input | Elbow servos | ~6.2A at 12V | **8A** | |
| Buck 4 input | Pi + micro servos | ~2A at 12V | **3A** | |
| Wrist buck input | Smart servos | ~6.2A at 12V | **8A** | |
| Fan line | 12V fan | 0.15A | **1A** | |
| Main (apparatus) | 24V bus | ~9.1A | **12A** | |
