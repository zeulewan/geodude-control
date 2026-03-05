# Robotic Arm

6-DOF servo-driven robotic arm for approach and capture. The arm captures the defunct satellite via its kick-engine nozzle using the end-effector.

---

## Joint Breakdown

| Joint | Servo Type | Torque | Qty | Signal | Notes |
|-------|-----------|--------|-----|--------|-------|
| Base | [HOOYIJ 150kg](https://www.amazon.ca/HOOYIJ-Digital-Waterproof-Stainless-Steering/dp/B0CX92QNJY) | 150 kg-cm | 2 | PWM | Standard hobby servo |
| Shoulder | [ANNIMOS 150kg](https://www.amazon.ca/ANNIMOS-Voltage-Digital-Steering-Brackets/dp/B0C69W2QP7) | 150 kg-cm | 2 | PWM | Robot version with brackets |
| Elbow | [ANNIMOS 80kg](https://www.amazon.ca/ANNIMOS-Waterproof-Digital-Steering-Brackets/dp/B0C69WWLWQ) | 80 kg-cm | 2 | PWM | Robot version with brackets |
| Wrist (rotate) | [RCmall Smart 20kg](https://www.amazon.com/RCmall-Continuous-Programmable-SO-ARM100-Controller/dp/B0F87Z9M3P) | 20 kg-cm | 2 | Serial (UART) | Smart servo, pack of 2 |
| Wrist (pan) | [RCmall Smart 20kg](https://www.amazon.com/RCmall-Continuous-Programmable-SO-ARM100-Controller/dp/B0F87Z9M3P) | 20 kg-cm | 2 | Serial (UART) | Smart servo, pack of 2 |
| End-effector | [Miuzei MG90S](https://www.amazon.ca/Miuzei-MG90S-Servo-Helicopter-Arduino/dp/B0CP98TZJ2) | 2 kg-cm | 4 | PWM | Micro servo, pack of 4 |

**Total: 14 servos** (6 standard PWM + 4 smart serial + 4 micro PWM)

---

## Slip Ring

The base joint rotates continuously, so a [3-wire slip ring](https://www.amazon.ca/Conductive-Current-Collecting-Electric-Connector/dp/B09NBLY16J) passes power and signal through the rotating base joint.

!!! warning "Slip ring capacity check needed"
    Only 3 wires - need to verify this is enough for the power + signal lines passing through the base rotation. The base servos draw significant current.

---

## Limit Switches

[Momentary limit switches](https://www.amazon.ca/MKBKLLJY-Momentary-Terminal-Electronic-Appliance/dp/B0DK693J79) (pack of 12, qty 2 packs = 24 switches) used for zeroing/homing each joint to a known reference position.

---

## Vision

| | |
|---|---|
| **Camera** | Raspberry Pi Camera (already have, Zeul) |
| **Purpose** | AI-guided approach and target identification |
| **Controller** | Raspberry Pi processes camera feed |
