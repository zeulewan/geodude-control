# Electrical

All electronics for both systems in the test setup. The GEO-DUDe servicer and the gimbal apparatus have completely independent power and control systems.

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

-   :material-connection:{ .lg .middle } **Interconnects**

    ---

    Full connection tables: every wire, pin, fuse, and connector

    [:octicons-arrow-right-24: Interconnects](interconnects.md)

</div>

---

## System Comparison

| | GEO-DUDe (Servicer) | Gimbal (Apparatus) |
|---|---|---|
| **PSU** | 12V 600W (50A) | 24V 480W (20A) |
| **Controller** | Raspberry Pi | ESP32 |
| **Actuators** | 14x servo motors | 4x stepper motors |
| **Drivers** | Waveshare smart driver + PWM | TMC2209 (x4) |
| **Communication** | Pi camera (AI vision) | Standalone |
