---
title: Home
icon: lucide/satellite
hide:
  - navigation
  - toc
---

<h1 style="text-align: center;">Subscale Satellite Test Setup</h1>
<p style="text-align: center;">SOOS-1 GEO-DUDe subscale demonstration model for the AER813 capstone project. A 3-axis gimbal simulates a defunct satellite while the servicer approaches on linear rails with a robotic arm.</p>

---

<div class="grid cards" markdown>

-   :material-lightning-bolt:{ .lg .middle } **Electrical**

    ---

    Power systems, servo/stepper electronics, wiring, fuses, and interconnects for both GEO-DUDe and the gimbal

    [:octicons-arrow-right-24: Electrical](electrical/index.md)

-   :material-clipboard-check:{ .lg .middle } **Project**

    ---

    Combined BOM, procurement tracking, and build status

    [:octicons-arrow-right-24: Project](project/index.md)

</div>

---

## How It Works

The test setup simulates on-orbit servicing of a defunct GEO satellite:

- **Left side (Gimbal)** - A 3-axis gimbal holds a "defunct" satellite model, allowing it to tumble in pitch, yaw, and roll. Driven by stepper motors controlled by an ESP32.
- **Right side (GEO-DUDe)** - The servicer satellite sits on a thrust bearing mounted to linear rail carriages. A belt drive (motor in the gimbal base) slides it along 1000mm rails toward the target.
- **Approach and capture** - The servicer uses its robotic arm (6-DOF, servo-driven) with a Raspberry Pi and camera for AI-guided approach and end-effector capture via the target's kick-engine nozzle.

## BOM Spreadsheet

[:material-google-spreadsheet: Subscale & Testing Apparatus BOM](https://docs.google.com/spreadsheets/d/1E1N-070xhcGK5FVkjd1sBZlGc8as569FgII3UE0jsTo/edit)
