# MACE Reaction Wheel - Development Log

This document captures the full development history of the MACE reaction wheel system, including hardware iterations, firmware changes, issues encountered, and lessons learned.

Important: the top section below is historical. The current wheel controller in the active repo is STM32 Nucleo F446RE + SimpleFOC, not Raspberry Pi Pico. The last full manual-control UI before the frontend purge was the Nucleo-backed panel with:

- direct RPM input
- `ENABLE`, `DISABLE`, and `STOP`
- `CALIBRATE FOC`
- manual voltage-limit tuning

The older Pico / DRV8313 notes are kept here because they are still useful history, but they are not the current hardware state.

## Hardware Configuration (Final State - 2804 Motor)

| Component | Spec |
|-----------|------|
| Motor | 2804 hollow shaft BLDC gimbal outrunner, 7 pole pairs, 220 KV, 2.3 ohm phase resistance, 0.03 Nm torque |
| Driver | SimpleFOC Mini v1.0 (DRV8313, 2.5A continuous, 3.5A OCP) |
| Encoder | AS5600 magnetic encoder (I2C on Wire1/I2C1, GP2/GP3, 400kHz) |
| IMU | ICM20948 9DoF (I2C on Wire/I2C0, GP4/GP5, 200kHz, address 0x69) |
| Controller | Raspberry Pi Pico (RP2040) |
| Flywheel mass | 500g |
| Power | VSYS from 5V buck (not USB), 12V to driver |

### Pico GPIO (Perfboard Wiring)

| GPIO | Function |
|------|----------|
| GP10 | IN1 (PWM Phase A) |
| GP11 | IN2 (PWM Phase B) |
| GP12 | IN3 (PWM Phase C) |
| GP14 | EN (driver enable) |
| GP19 | nRESET (DRV8313, active low) |
| GP20 | nSLEEP (DRV8313, active low) |
| GP21 | nFAULT (DRV8313, active low input) |
| GP2  | SDA - I2C1/Wire1 (AS5600 encoder) |
| GP3  | SCL - I2C1/Wire1 (AS5600 encoder) |
| GP4  | SDA - I2C0/Wire (ICM20948 IMU) |
| GP5  | SCL - I2C0/Wire (ICM20948 IMU) |
| GP6  | Bootloader entry (emergency, active low) |
| RUN  | Hard reset from Pi GPIO 27 |

## Firmware Architecture

SimpleFOC-based, two operating modes:

- **Velocity mode (M0)**: SimpleFOC PID controls wheel speed. Used for manual MACE control.
- **Torque mode (M1)**: Voltage applied directly through FOC commutation. Used for attitude control where the outer PID on the Pi outputs voltage directly.

Serial commands: T (velocity), U (voltage), V (voltage limit), P/I/W (PID), L (velocity limit), A (output ramp), F (LPF), M0/M1 (mode switch), C (calibrate/initFOC), D (disable), E (enable), R (reset fault).

Telemetry: 50Hz JSON stream over USB serial with all motor state, sensor data, and tuning parameters.

## Issues Encountered

### 1. Wire vs Wire1 (I2C Bus Confusion)

**Problem:** GP2/GP3 are I2C1 pins on RP2040. Using `Wire` (I2C0) with `setSDA(2)/setSCL(3)` crashed the Pico.

**Fix:** Use `Wire1` for GP2/GP3. `Wire` is I2C0 (GP4/GP5 default).

**Lesson:** On the earlephilhower RP2040 core, Wire = I2C0, Wire1 = I2C1. The pin numbers determine which peripheral, not the Wire object.

### 2. Pico USB Disconnects / Crashes

**Problem:** Pico would randomly disconnect from USB, especially under motor load.

**Root cause:** Pi's USB polyfuse drops voltage to the Pico. Under motor current draw, the 5V rail sagged enough to brown out the Pico.

**Fix:** Power Pico VSYS (pin 39) from an external 5V buck converter. USB is data only. Added 1000uF cap on Pi 5V rail.

### 3. I2C Sensor Timing Race at Boot

**Problem:** I2C errors (error code 5 = timeout) on AS5600 reads immediately after boot.

**Root cause:** Sensors powered from Pi 3.3V weren't ready when Pico booted. The Pico started I2C transactions before the sensor had finished its power-on sequence.

**Fix:** Power sensors from Pico's own 3.3V pin (pin 36). Added retry loop in firmware that polls AS5600 (address 0x36) up to 20 times with 100ms delays before calling `sensor.init()`.

### 4. Motor Not Spinning (loopFOC Required)

**Problem:** Motor wouldn't spin even with target velocity set.

**Root cause:** `motor.loopFOC()` was removed thinking it wasn't needed for open-loop. On RP2040 it IS needed in every mode for FOC commutation.

**Fix:** Always call `motor.loopFOC()` in the main loop, followed by `motor.move()`.

### 5. Motor Not Spinning (PID Limit Capped)

**Problem:** Motor enabled, target set, but duty cycles stayed at 50% (no movement).

**Root cause:** `driver.voltage_limit` was never set (defaulted to some low value), and `motor.PID_velocity.limit` was stuck at the initial `motor.voltage_limit` (1.5V). Changing voltage_limit via the GUI slider didn't update the PID limit.

**Fix:** Set `driver.voltage_limit = 12` in setup. Added code to sync PID limit when voltage_limit changes: `motor.PID_velocity.limit = motor.voltage_limit`.

### 6. DRV8313 Fault on Motor Connect

**Problem:** Driver immediately faulted (nFAULT low) when motor was connected.

**Root cause:** Original motor had a shorted coil winding.

**Fix:** Swapped to new 2804 motor from spare kit. Always check motor winding resistance before connecting to driver.

### 7. ttyACM Number Changing

**Problem:** `/dev/ttyACM0` would change to `/dev/ttyACM1` after USB disconnect/reconnect cycles, breaking sensor_server.

**Fix:** udev rule creates `/dev/pico` symlink: `SUBSYSTEM=="tty", ATTRS{idVendor}=="2e8a", ATTRS{idProduct}=="000a", SYMLINK+="pico"`.

### 8. Motor Overheating

**Problem:** Motor got extremely hot even at zero target velocity.

**Root causes:**
- Failed `initFOC()` calibration pushing current without proper commutation (coils energized but no rotation).
- PID oscillation from noisy encoder feeding back into velocity control. PID constantly pumped current back and forth.
- Ki=10 (way too high) caused integral windup, slamming current into motor.

**Fix:** Lower Ki, increase LPF Tf, ensure initFOC() completes successfully. Send `D` (disable) immediately if motor heats unexpectedly.

### 9. Analog Encoder Noise (RP2040 ADC)

**Problem:** AS5600 analog output on GP26 showed +/-3 degrees jitter at rest. RPM swung +/-80 at standstill. PID chased phantom velocity errors.

**Root cause:** RP2040's ADC has inherent 5-6 LSB noise. This is a known hardware limitation. Differentiating the noisy position to get velocity amplified the noise massively.

**Measurements:** Encoder range at rest: 304.5 to 307.5 degrees (3 degree spread). RPM at rest: -80 to +36.

**Attempted fixes:**
- Shortened analog wire from 15cm to shorter - minimal improvement
- Increased LPF Tf from 0.01 to 0.05 - helped but added lag
- Lowered Ki to 2 - reduced oscillation but didn't fix root cause

**Final fix:** Switched to I2C encoder. 400kHz I2C gives clean readings with +/-1 RPM noise at rest vs +/-80 with analog.

### 10. I2C Encoder Speed Limit

**Problem:** Motor limited to ~800 RPM with I2C encoder at 100kHz. At 200kHz, hit ~450 RPM limit with buzzing above that.

**Root cause:** I2C reads take time (address, register, data, ACK/NACK). Each read at 100kHz takes ~500-800us. The FOC loop rate is bottlenecked by sensor reads. With 7 pole pairs, the electrical frequency at 800 RPM is 93Hz, needing ~1000Hz FOC loop minimum.

**Fix:** Increased I2C clock to 400kHz. AS5600 supports it. Works fine even with dupont jumper wires. Achieved 1000+ RPM cleanly.

**Note:** 15cm dupont jumpers were a concern for 400kHz I2C signal integrity, but worked fine in practice. A 100nF cap on the I2C lines would add margin.

### 11. sensor.init(&Wire1) Hanging at Boot

**Problem:** Firmware with I2C encoder (`MagneticSensorI2C`) sometimes hung at boot with no serial output.

**Root cause:** `sensor.init(&Wire1)` does a blocking I2C read. If the AS5600 isn't powered/ready, the function hangs forever. Power sequencing race - sometimes sensor is ready, sometimes not.

**Fix:** Added retry loop before `sensor.init()` that polls address 0x36 up to 20 times with 100ms delays. Gives the sensor up to 2 seconds to power up before initialization.

### 12. Two PIDs Fighting (Attitude Control)

**Problem:** When the attitude controller sent velocity commands to SimpleFOC, the wheel just kept speeding up and saturated without generating useful body torque.

**Root cause:** Two velocity controllers fighting each other. SimpleFOC runs its own velocity PID (encoder feedback). The attitude controller runs an outer PID that outputs velocity setpoints. When the body doesn't respond fast enough (high inertia), the attitude controller increases velocity, SimpleFOC happily tracks it, wheel saturates.

**Fix:** Switch SimpleFOC to torque mode (`MotionControlType::torque`). The attitude controller directly commands voltage (1.5V-12V) through FOC. No competing velocity PID. Single control authority.

### 13. GEO-DUDe Pi Brownouts

**Problem:** GEO-DUDe Pi reboots during high motor speeds (1000+ RPM).

**Root cause:** Motor current spikes cause voltage dip on the Pi's 5V rail. The 1000uF cap helps but isn't enough for sustained high-current operation.

**Status:** Ongoing. May need larger capacitance or separate power regulation for the Pi vs motor driver.

### 14. Gyro Bias Drift

**Problem:** Body angle drifts over time even when stationary. gz reads ~-1.5 deg/s at rest.

**Root cause:** MEMS gyro bias. Normal for ICM20948. Without correction, accumulates to 90 degrees of drift per minute.

**Fix:** Gyro bias calibration on attitude controller enable (2-second average while stationary). Subtracted from all subsequent readings.

**Note:** Long-term drift still occurs due to bias instability and temperature changes. A complementary filter (gyro + accelerometer) or Kalman filter would help for sustained operation.

## Performance Measurements

| Metric | Value |
|--------|-------|
| Max speed with I2C encoder @ 100kHz | ~800 RPM |
| Max speed with I2C encoder @ 200kHz | ~450 RPM (buzzing above) |
| Max speed with I2C encoder @ 400kHz | 1000+ RPM |
| Max speed with analog encoder | 1200+ RPM (but unusable noise) |
| Encoder noise (analog, stationary) | +/-3 degrees, +/-80 RPM |
| Encoder noise (I2C 400kHz, stationary) | +/-0.5 degrees, +/-10 RPM |
| Gyro bias (ICM20948, typical) | ~1.5 deg/s |
| Body rate during full reversal | ~5 deg/s (+800 to -800 RPM) |

## Software Stack

```
Groundstation Pi (wheel_control.py :8080)
  |-- HTTP proxy to GEO-DUDe
  |-- MACE manual controls (velocity mode)
  |-- Attitude control GUI (torque mode)
  |-- MACE section disable when attitude active
  |
GEO-DUDe Pi
  |-- sensor_server.py (:5000) - reads Pico serial, caches telemetry
  |-- attitude_controller.py (:5001) - PID: angle error -> voltage
  |
Pi Pico (USB serial)
  |-- SimpleFOC firmware
  |-- M0: velocity mode (MACE manual)
  |-- M1: torque mode (attitude control)
  |-- 50Hz JSON telemetry stream
```

## Key Lessons

1. **Power the Pico from a dedicated 5V source**, not through USB from the Pi. USB polyfuse causes brownouts.
2. **I2C encoder beats analog on RP2040.** The RP2040 ADC is too noisy for reliable velocity estimation. I2C at 400kHz provides clean readings up to 1000+ RPM.
3. **Add sensor boot retry loops.** I2C devices may not be ready when the MCU boots. Poll before init.
4. **Don't run two velocity controllers in series.** If an outer loop commands velocity, and the inner loop also does velocity PID, they fight. Use torque/voltage mode for the inner loop when cascading.
5. **Always call motor.loopFOC()** on RP2040 with SimpleFOC, regardless of control mode.
6. **Ki is the most dangerous PID gain.** High Ki + noisy sensor = integral windup = motor overheating. Start with Ki=0, tune Kp first, add Ki carefully.
7. **udev rules** are essential for persistent device naming with USB serial devices.
8. **initFOC() calibration** requires the motor to be connected and free to move. A failed calibration means the commutation angle is wrong, leading to inefficient operation and overheating.
