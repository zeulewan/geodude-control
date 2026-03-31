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

Two independent identical arms, 5 servos per arm, 10 servos total.

| Servo | Voltage | Stall Current (each) | Qty (total, 1 per arm) | Total Stall | Power Source |
|-------|---------|---------------------|------------------------|-------------|-------------|
| Base (HOOYIJ 150kg) | 12V | 8.0A | 2 | 16.0A | 12V bus direct |
| Shoulder (ANNIMOS 150kg) | 12V | 8.0A | 2 | ~16.0A | 12V bus direct |
| Elbow (ANNIMOS 80kg) | 7.4V | 5.0A | 2 | 10.0A | Buck conv 1 (7.4V) |
| Wrist rotate (RDS3218 20kg) | 5V | 1.6A | 2 | 3.2A | Buck conv 3 (5V) |
| Wrist pan (RDS3218 20kg) | 5V | 1.6A | 2 | 3.2A | Buck conv 3 (5V) |

### Other Loads

| Component | Voltage | Max Current | Power Source |
|-----------|---------|-------------|-------------|
| Raspberry Pi | 5V | 2.5A | Buck conv 2 (5V) |
| PCA9685 PWM driver | 5V | ~0.05A | Buck conv 2 (5V) |
| 12V fan | 12V | 0.15A | 12V bus direct |

### Current by Rail

| Rail | Components | Total Max Current | Capacity | Status |
|------|-----------|------------------|----------|--------|
| **12V direct** | 4x 150kg servos (2 base + 2 shoulder, one per arm) + fan | ~32A stall | 50A PSU (30A fused) | OK |
| **7.4V buck 1** | 2x 80kg elbow servos (one per arm) | 10A | 20A converter (8A fused at 12V in) | OK |
| **5V buck 2** | Pi + PCA9685 (always on) | ~2.6A | 20A converter (3A fused at 12V in) | OK |
| **5V buck 3** | 4x RDS3218 wrist (two per arm) (after toggle switch) | ~6.4A stall | 20A converter (8A fused at 12V in) | OK |

---

## Buck Converter Allocation

**Converter:** [20A 300W buck](https://www.amazon.ca/XLX-High-Power-Converter-Adjustable-Protection/dp/B081X5YX8V) - Input 6-40V, Output 1.25-36V adj, 20A max / 15A continuous

| Buck # | Output V | Load | Max Current | Headroom | Notes |
|--------|----------|------|-------------|----------|-------|
| 1 | 7.4V | 2x elbow servos (one per arm) | 10A stall | 5-10A spare | After toggle switch |
| 2 | 5V | Pi + PCA9685 | ~2.6A | 12-17A spare | Before toggle switch (always on) |
| 3 | 5V | 4x RDS3218 wrist (two per arm) | ~6.4A stall | 9-14A spare | After toggle switch |
| 4 | - | **Spare** | - | - | |

---

## Realistic Operating Current vs Stall

The "kg" rating on hobby servos is the **stall torque** - the absolute maximum when the motor is locked and drawing peak current. During normal operation, servos draw a fraction of this.

**Assumptions:**

- The arms are manipulating a lightweight subscale satellite model, not heavy payloads
- Servos operate at 20-40% of stall torque during typical motion (holding against gravity, positioning)
- Current scales roughly linearly with torque for DC motors
- All servos will never simultaneously stall - that would mean every joint on both arms is jammed at once
- Brief acceleration spikes may hit 50-60% of stall but are transient (milliseconds)

### GEO-DUDe Realistic Current Draw

| Servo | Stall Current | Realistic Operating (per servo) | Qty (total) | Realistic Total | Notes |
|-------|--------------|-------------------------------|-------------|----------------|-------|
| Base (150kg) | 8.0A | **2-3A** (~30% load) | 2 | **4-6A** | Holding arm weight against gravity |
| Shoulder (150kg) | 8.0A | **2-3A** (~30% load) | 2 | **4-6A** | Highest static load (arm cantilevered) |
| Elbow (80kg) | 5.0A | **1.5-2A** (~35% load) | 2 | **3-4A** @ 7.4V | Lighter distal load |
| Wrist RDS3218 (20kg) | 1.6A | **0.5-0.8A** (~40% load) | 4 | **2-3.2A** @ 5V | Fine positioning, light torque |
| Pi + PCA9685 | - | 2.6A | 1 | **2.6A** @ 5V | Constant |
| Fan | - | 0.15A | 1 | **0.15A** @ 12V | Constant |

### Current Through Toggle Switch (Realistic)

Everything after the toggle switch, referred to 12V input:

| Branch | Realistic @ native V | Referred to 12V input | Stall @ 12V |
|--------|---------------------|----------------------|-------------|
| Base (12V direct, 2 servos) | 4-6A | **4-6A** | 16A |
| Shoulder (12V direct, 2 servos) | 4-6A | **4-6A** | 16A |
| Elbow (7.4V buck, 2 servos) | 3-4A @ 7.4V | **~2.5A** (efficiency ~80%) | ~6.2A |
| Wrist (5V buck, 4 servos) | 2-3.2A @ 5V | **~1.7A** (efficiency ~80%) | ~2.7A |
| Fan | 0.15A | **0.15A** | 0.15A |
| **Total through toggle switch** | | **~12-16A** | ~41A |

**Conclusion:** A **40A toggle switch** provides 2.5x margin on realistic load.

### Wire Gauge Sizing (Revised)

Wire gauge must be rated for the **fuse rating** (not the load), since the fuse is what limits current in a fault. Only 16, 18, and 22 AWG wire is available.

| Segment | Old Gauge | Old Fuse | Revised Gauge | Revised Fuse | Justification |
|---------|-----------|----------|--------------|-------------|---------------|
| PSU to bus trunk | 8 AWG | 40A | **2x 16 AWG parallel** | **30A** | 2x 16 AWG gives ~24A capacity, 30A fuse protects |
| Bus to toggle switch | 8 AWG | - | **2x 16 AWG parallel** | - | Matches trunk |
| Toggle switch to fuse boards | 8 AWG | - | **16 AWG** | - | After toggle, splits to individual branches |
| GND trunk | 8 AWG | - | **2x 16 AWG parallel** | - | Matches trunk |
| Base/shoulder servo branch | 14 AWG | 20A | **16 AWG** | **8A per servo** | Per-servo fusing on arm fuse board |
| Buck 1 input | 16 AWG | 8A | **18 AWG** | **8A** | |
| Buck 2 input | 18 AWG | 3A | **18 AWG** | **3A** | No change needed |
| Buck 3 input | 16 AWG | 8A | **18 AWG** | **8A** | |
| Buck outputs to fuse boards | 16 AWG | - | **18 AWG** | - | |
| Fan | 22 AWG | 1A | **22 AWG** | **1A** | No change needed |
| Signal / low current | 22 AWG | - | **22 AWG** | - | No change needed |

### About Servo Wire Gauge

Hobby servos come with thin built-in leads (typically 22-26 AWG). This is fine because:

- Each lead only carries current for **one servo**
- Wire runs are short (15-30cm from distribution point to servo)
- Even the 150kg servos at 8A stall use ~20 AWG factory leads - the wire is rated for thermal load over short bursts
- The fuse upstream protects the servo's own wiring in a fault condition

The wire gauges in the diagrams are for the **distribution runs** (PSU to bus, bus to toggle switch, toggle switch to fuse boards). From the fuse board to each servo, use the servo's own factory leads.

## Fuse Sizing

| Fuse | Branch | Realistic Draw | Peak/Stall | Rating | Wire Gauge | Notes |
|------|--------|---------------|------------|--------|-----------|-------|
| AC inline | Mains hot before slip ring | ~3A @120V | ~5A | **6A slow-blow** | Mains cable | |
| Main DC | 12V bus after PSU | **~16A** | ~41A stall | **30A** | **2x 16 AWG parallel** | |
| Base servo (each, x2) | Per base servo, one per arm | **~3A** | 8A stall | **8A** | **16 AWG** | Per-servo on arm fuse board |
| Shoulder servo (each, x2) | Per shoulder servo, one per arm | **~3A** | 8A stall | **8A** | **16 AWG** | Per-servo on arm fuse board |
| Elbow servo (each, x2) | Per elbow servo, one per arm | **~1.8A** | 5A stall | **5A** | **18 AWG** | Per-servo on arm fuse board |
| Wrist rotate (each, x2) | Per wrist rotate, one per arm | **~0.7A** | 1.6A stall | **3A** | **18 AWG** | Per-servo on arm fuse board |
| Wrist pan (each, x2) | Per wrist pan, one per arm | **~0.7A** | 1.6A stall | **3A** | **18 AWG** | Per-servo on arm fuse board |
| Buck 1 input | Elbow servos at 12V in | **~2.5A** | ~6.2A | **8A** | 18 AWG | |
| Buck 2 input | Pi + PCA9685 at 12V in | ~1.1A | ~1.1A | **3A** | 18 AWG | Before toggle switch (always on) |
| Buck 3 input | Wrist servos at 12V in | **~1.7A** | ~2.7A | **8A** | 18 AWG | |
| Fan line | 12V fan | 0.15A | 0.15A | **1A** | 22 AWG | |
| Apparatus main | 24V bus | ~8.6A | ~8.6A | **12A** | 14 AWG | Steppers are driver-limited |
