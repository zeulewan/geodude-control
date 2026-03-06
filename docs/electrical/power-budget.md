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

## Realistic Operating Current vs Stall

The "kg" rating on hobby servos is the **stall torque** - the absolute maximum when the motor is locked and drawing peak current. During normal operation, servos draw a fraction of this.

**Assumptions:**

- The arm is manipulating a lightweight subscale satellite model, not heavy payloads
- Servos operate at 20-40% of stall torque during typical motion (holding against gravity, positioning)
- Current scales roughly linearly with torque for DC motors
- All servos will never simultaneously stall - that would mean every joint is jammed at once
- Brief acceleration spikes may hit 50-60% of stall but are transient (milliseconds)

### GEO-DUDe Realistic Current Draw

| Servo | Stall Current | Realistic Operating (per servo) | Qty | Realistic Total | Notes |
|-------|--------------|-------------------------------|-----|----------------|-------|
| Base (150kg) | 8.0A | **2-3A** (~30% load) | 2 | **4-6A** | Holding arm weight against gravity |
| Shoulder (150kg) | 8.0A | **2-3A** (~30% load) | 2 | **4-6A** | Highest static load (arm cantilevered) |
| Elbow (80kg) | 5.0A | **1.5-2A** (~35% load) | 2 | **3-4A** @ 7.4V | Lighter distal load |
| Wrist RDS3218 (20kg) | 1.6A | **0.5-0.8A** (~40% load) | 4 | **2-3.2A** @ 5V | Fine positioning, light torque |
| MG90S (2kg) | 0.5A | **0.2A** (~40% load) | 4 | **0.8A** @ 5V | End-effector gripper |
| Pi + PCA9685 | - | 2.6A | 1 | **2.6A** @ 5V | Constant |
| Fan | - | 0.15A | 1 | **0.15A** @ 12V | Constant |

### Current Through Relay (Realistic)

Everything after the relay, referred to 12V input:

| Branch | Realistic @ native V | Referred to 12V input | Stall @ 12V |
|--------|---------------------|----------------------|-------------|
| Base (12V direct) | 4-6A | **4-6A** | 16A |
| Shoulder (12V direct) | 4-6A | **4-6A** | 16A |
| Elbow (7.4V buck) | 3-4A @ 7.4V | **~2.5A** (efficiency ~80%) | ~6.2A |
| Wrist + EE (5V buck) | 2.8-4A @ 5V | **~2A** (efficiency ~80%) | ~3.5A |
| Fan | 0.15A | **0.15A** | 0.15A |
| **Total through relay** | | **~13-17A** | ~42A |

**Conclusion:** A **40A relay** provides 2.5x margin on realistic load. The 120A relay in the original design was massively oversized.

### Wire Gauge Sizing (Revised)

Wire gauge must be rated for the **fuse rating** (not the load), since the fuse is what limits current in a fault. With realistic loads, we can use smaller fuses and thinner wire:

| Segment | Old Gauge | Old Fuse | Revised Gauge | Revised Fuse | Justification |
|---------|-----------|----------|--------------|-------------|---------------|
| PSU to bus trunk | 8 AWG | 40A | **10 AWG** | **25A** | Realistic peak ~17A, 25A covers transients |
| Bus to relay | 8 AWG | - | **10 AWG** | - | Matches trunk |
| Relay to fuse block | 8 AWG | - | **10 AWG** | - | Matches trunk |
| GND trunk | 8 AWG | - | **10 AWG** | - | Matches trunk |
| Base servo branch | 14 AWG | 20A | **14 AWG** | **15A** | Realistic 3A/servo, 15A covers one stalling |
| Shoulder servo branch | 14 AWG | 20A | **14 AWG** | **15A** | Same as base |
| Buck 1 input | 16 AWG | 8A | **16 AWG** | **8A** | No change needed |
| Buck 2 input | 18 AWG | 3A | **18 AWG** | **3A** | No change needed |
| Buck 3 input | 16 AWG | 8A | **16 AWG** | **8A** | No change needed |
| Fan | 22 AWG | 1A | **22 AWG** | **1A** | No change needed |

### About Servo Wire Gauge

Hobby servos come with thin built-in leads (typically 22-26 AWG). This is fine because:

- Each lead only carries current for **one servo**
- Wire runs are short (15-30cm from distribution point to servo)
- Even the 150kg servos at 8A stall use ~20 AWG factory leads - the wire is rated for thermal load over short bursts
- The fuse upstream protects the servo's own wiring in a fault condition

The wire gauges in the diagrams are for the **distribution runs** (PSU to bus, bus to fuse block, fuse block to Wago junction). From the Wago to each servo, use the servo's own factory leads.

## Fuse Sizing

| Fuse | Branch | Realistic Draw | Peak/Stall | Rating | Wire Gauge | Notes |
|------|--------|---------------|------------|--------|-----------|-------|
| AC inline | Mains hot before slip ring | ~3A @120V | ~5A | **6A slow-blow** | Mains cable | |
| Main DC | 12V bus after PSU | **~17A** | ~42A stall | **25A** | **10 AWG** | Revised down from 40A |
| Base servo branch | 2x base 150kg servos | **~6A** | 16A stall | **15A** | **14 AWG** | |
| Shoulder servo branch | 2x shoulder 150kg servos | **~6A** | 16A stall | **15A** | **14 AWG** | |
| Buck 1 input | Elbow servos at 12V in | **~2.5A** | ~6.2A | **8A** | 16 AWG | Fuse block circuit |
| Buck 2 input | Pi + PCA9685 at 12V in | ~1.1A | ~1.1A | **3A** | 18 AWG | Before relay (always on) |
| Buck 3 input | Wrist + MG90S at 12V in | **~2A** | ~3.5A | **8A** | 16 AWG | Fuse block circuit |
| Fan line | 12V fan | 0.15A | 0.15A | **1A** | 22 AWG | Fuse block circuit |
| Apparatus main | 24V bus | ~8.6A | ~8.6A | **12A** | 14 AWG | Steppers are driver-limited |
