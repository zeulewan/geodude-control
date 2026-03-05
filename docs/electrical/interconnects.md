# Interconnect Tables

Every wire connection in both systems. Use this as the wiring reference when building.

---

## Apparatus Connections (24V System)

### Power

| From | Terminal | To | Terminal | Wire Gauge | Fuse |
|------|----------|----|----------|-----------|------|
| Mains | L/N/G | 24V PSU | AC input | Mains cable | Breaker |
| 24V PSU | +24V | Main fuse | In | 14 AWG | - |
| Main fuse | Out | 24V bus (Wago) | In | 14 AWG | TBD |
| 24V bus | Out | TMC2209 #1 | VMOT | 18 AWG | - |
| 24V bus | Out | TMC2209 #2 | VMOT | 18 AWG | - |
| 24V bus | Out | TMC2209 #3 | VMOT | 18 AWG | - |
| 24V bus | Out | TMC2209 #4 | VMOT | 18 AWG | - |
| 24V bus | Out | 24V Fans | +24V | 22 AWG | - |
| 24V bus | Out | ESP32 | VIN | 22 AWG | - |
| 24V PSU | GND | GND bus (Wago) | In | 14 AWG | - |

### Signal

| From | Pin | To | Pin | Cable | Notes |
|------|-----|----|-----|-------|-------|
| ESP32 | STEP pin (TBD) | TMC2209 #1 | STEP | Jumper | Yaw axis |
| ESP32 | DIR pin (TBD) | TMC2209 #1 | DIR | Jumper | Yaw axis |
| ESP32 | STEP pin (TBD) | TMC2209 #2 | STEP | Jumper | Pitch axis |
| ESP32 | DIR pin (TBD) | TMC2209 #2 | DIR | Jumper | Pitch axis |
| ESP32 | STEP pin (TBD) | TMC2209 #3 | STEP | Jumper | Roll axis |
| ESP32 | DIR pin (TBD) | TMC2209 #3 | DIR | Jumper | Roll axis |
| ESP32 | STEP pin (TBD) | TMC2209 #4 | STEP | Jumper | Belt motor |
| ESP32 | DIR pin (TBD) | TMC2209 #4 | DIR | Jumper | Belt motor |
| TMC2209 #1 | A1/A2/B1/B2 | Stepper #1 | Coils | 6-to-4 pin cable | 1M length |
| TMC2209 #2 | A1/A2/B1/B2 | Stepper #2 | Coils | 6-to-4 pin cable | 1M length |
| TMC2209 #3 | A1/A2/B1/B2 | Stepper #3 | Coils | 6-to-4 pin cable | 1M length |
| TMC2209 #4 | A1/A2/B1/B2 | Stepper #4 | Coils | 6-to-4 pin cable | 1M length |

---

## Subscale Satellite Connections (12V System)

### Power

| From | Terminal | To | Terminal | Wire Gauge | Fuse |
|------|----------|----|----------|-----------|------|
| Mains | L/N/G | IEC C16 socket | Panel mount | Mains cable | Breaker |
| IEC C16 | Output | 12V PSU | AC input | Internal | - |
| 12V PSU | +12V | Main fuse | In | 12 AWG | TBD |
| Main fuse | Out | 12V bus (Wago) | In | 12 AWG | TBD |
| 12V bus | Out | Fuse 1 | In | 16 AWG | TBD |
| Fuse 1 | Out | Buck conv 1 | VIN+ | 16 AWG | - |
| Buck conv 1 | VOUT+ | Base servo L | Power + | 16 AWG | - |
| Buck conv 1 | VOUT+ | Base servo R | Power + | 16 AWG | - |
| 12V bus | Out | Fuse 2 | In | 16 AWG | TBD |
| Fuse 2 | Out | Buck conv 2 | VIN+ | 16 AWG | - |
| Buck conv 2 | VOUT+ | Shoulder servo L | Power + | 16 AWG | - |
| Buck conv 2 | VOUT+ | Shoulder servo R | Power + | 16 AWG | - |
| 12V bus | Out | Fuse 3 | In | 16 AWG | TBD |
| Fuse 3 | Out | Buck conv 3 | VIN+ | 16 AWG | - |
| Buck conv 3 | VOUT+ | Elbow servo L | Power + | 16 AWG | - |
| Buck conv 3 | VOUT+ | Elbow servo R | Power + | 16 AWG | - |
| 12V bus | Out | Fuse 4 | In | 18 AWG | TBD |
| Fuse 4 | Out | Buck conv 4 | VIN+ | 18 AWG | - |
| Buck conv 4 | VOUT (5V) | Raspberry Pi | 5V GPIO | 18 AWG | - |
| Buck conv 4 | VOUT (5V) | MG90S servos | Power + | 22 AWG | - |
| Buck conv 4 | VOUT (5V) | Waveshare driver | VCC | 22 AWG | - |
| 12V bus | Out | Fuse 5 | In | 22 AWG | 1A |
| Fuse 5 | Out | 12V fan | +12V | 22 AWG | - |
| 12V PSU | GND | GND bus (Wago) | In | 12 AWG | - |

### Signal

| From | Pin | To | Pin | Cable | Notes |
|------|-----|----|-----|-------|-------|
| Pi | GPIO PWM (TBD) | Base servo L | Signal | 22 AWG | Via slip ring |
| Pi | GPIO PWM (TBD) | Base servo R | Signal | 22 AWG | Via slip ring |
| Pi | GPIO PWM (TBD) | Shoulder servo L | Signal | 22 AWG | |
| Pi | GPIO PWM (TBD) | Shoulder servo R | Signal | 22 AWG | |
| Pi | GPIO PWM (TBD) | Elbow servo L | Signal | 22 AWG | |
| Pi | GPIO PWM (TBD) | Elbow servo R | Signal | 22 AWG | |
| Pi | GPIO PWM (TBD) | MG90S #1 | Signal | 22 AWG | End-effector |
| Pi | GPIO PWM (TBD) | MG90S #2 | Signal | 22 AWG | End-effector |
| Pi | GPIO PWM (TBD) | MG90S #3 | Signal | 22 AWG | End-effector |
| Pi | GPIO PWM (TBD) | MG90S #4 | Signal | 22 AWG | End-effector |
| Pi | TX (UART) | Waveshare driver | RX | 22 AWG | Smart servo serial |
| Pi | RX (UART) | Waveshare driver | TX | 22 AWG | Smart servo serial |
| Waveshare driver | Servo bus | Wrist rotate L | Data | Servo cable | Daisy chain |
| Waveshare driver | Servo bus | Wrist rotate R | Data | Servo cable | Daisy chain |
| Waveshare driver | Servo bus | Wrist pan L | Data | Servo cable | Daisy chain |
| Waveshare driver | Servo bus | Wrist pan R | Data | Servo cable | Daisy chain |
| Pi | I2C SDA (GPIO 2) | PCF8575 | SDA | 22 AWG | |
| Pi | I2C SCL (GPIO 3) | PCF8575 | SCL | 22 AWG | |
| PCF8575 | P0-P15 | Limit switches | Signal | 22 AWG | Up to 16 switches |
| Pi | CSI connector | Pi Camera | Ribbon | Ribbon cable | |

### Slip Ring Passthrough

The 3-wire slip ring at the base joint passes:

| Wire | Carries | Notes |
|------|---------|-------|
| Wire 1 | Servo power (+) | From buck conv 1 to base servos |
| Wire 2 | GND | Common ground |
| Wire 3 | Signal | PWM for base servos |

!!! warning "3 wires may not be enough"
    Two base servos need individual PWM signal lines. Options: multiplex the signal, use a Y-splitter above the slip ring, or get a slip ring with more conductors.
