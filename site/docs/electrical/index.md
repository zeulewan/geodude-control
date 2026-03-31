# Electrical

All electronics for the three systems in the test setup. The GEO-DUDe servicer, gimbal apparatus, and base station have independent power systems, linked by WiFi.

<div class="grid cards" markdown>

-   :material-robot-industrial:{ .lg .middle } **GEO-DUDe**

    ---

    Raspberry Pi, servo motors, buck converters, 12V power distribution

    [:octicons-arrow-right-24: GEO-DUDe](geodude/index.md)

-   :material-rotate-3d-variant:{ .lg .middle } **Gimbal**

    ---

    ESP32, stepper motors, TMC2209 drivers, 24V power distribution

    [:octicons-arrow-right-24: Gimbal](gimbal/index.md)

-   :material-flash:{ .lg .middle } **Power Budget**

    ---

    Current draw calculations, voltage requirements, and PSU headroom

    [:octicons-arrow-right-24: Power Budget](power-budget.md)

-   :material-access-point:{ .lg .middle } **Base Station**

    ---

    Raspberry Pi ground control station, WiFi comms to GEO-DUDe and gimbal

    [:octicons-arrow-right-24: Base Station](basestation/index.md)

-   :material-connection:{ .lg .middle } **Interconnects**

    ---

    Full connection tables: every wire, pin, fuse, and connector

    [:octicons-arrow-right-24: Interconnects](interconnects.md)

</div>

---

## System Comparison

| | GEO-DUDe (Servicer) | Gimbal (Apparatus) | Base Station |
|---|---|---|---|
| **PSU** | 12V 600W (50A) | 24V 480W (20A) | 5V USB adapter |
| **Controller** | Raspberry Pi | ESP32 | Raspberry Pi |
| **Actuators** | 14x servos + 1x BLDC (reaction wheel) | 4x stepper motors | None |
| **Drivers** | PCA9685 PWM + 40A ESC | TMC2209 (x4) | None |
| **Communication** | WiFi to base station | WiFi to base station | WiFi AP to both systems, ground control UI |
