# Electrical

Overview of both electrical systems in the test setup. The apparatus and subscale satellite have completely independent power and control systems.

<div class="grid cards" markdown>

-   :material-flash:{ .lg .middle } **Power Budget**

    ---

    Current draw calculations, voltage requirements, and PSU headroom for both systems

    [:octicons-arrow-right-24: Power Budget](power-budget.md)

-   :material-connection:{ .lg .middle } **Interconnects**

    ---

    Full connection tables: every wire, pin, fuse, and connector

    [:octicons-arrow-right-24: Interconnects](interconnects.md)

</div>

---

## Two Independent Systems

| | Apparatus (Gimbal + Rails) | Subscale Satellite |
|---|---|---|
| **PSU** | 24V 480W | 12V 600W |
| **Controller** | ESP32 | Raspberry Pi |
| **Actuators** | 4x stepper motors | 14x servo motors |
| **Drivers** | TMC2209 (x4) | Waveshare smart driver + PWM |
| **Communication** | Standalone | Pi camera (AI vision) |
