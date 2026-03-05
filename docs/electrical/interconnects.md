# Interconnect Tables

Every wire connection in both systems. Use this as the wiring reference when building.

---

## Apparatus Connections (24V System)

### Power

| From | Terminal | To | Terminal | Wire Gauge | Fuse |
|------|----------|----|----------|-----------|------|
| Mains | L/N/G | 24V PSU | AC input | Mains cable | Breaker |
| 24V PSU | +24V | Main fuse | In | 14 AWG | - |
| Main fuse (12A) | Out | 24V bus (Wago) | In | 14 AWG | - |
| 24V bus | Out | TMC2209 #1 | VMOT | 18 AWG | - |
| 24V bus | Out | TMC2209 #2 | VMOT | 18 AWG | - |
| 24V bus | Out | TMC2209 #3 | VMOT | 18 AWG | - |
| 24V bus | Out | TMC2209 #4 | VMOT | 18 AWG | - |
| 24V bus | Out | 24V Fans | +24V | 22 AWG | - |
| 24V PSU | GND | GND bus (Wago) | In | 14 AWG | - |
| USB adapter | USB | ESP32 | USB port | USB cable | - |

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
| ESP32 | WiFi | Raspberry Pi | WiFi | Wireless | Coordinated operation |

---

## GEO-DUDe Connections (12V System)

### AC Mains (through slip ring)

| From | Terminal | To | Terminal | Connector Type | Notes |
|------|----------|----|----------|---------------|-------|
| Wall outlet | Plug | IEC C16 panel socket (gantry) | Spade terminals | **Crimp spade 6.3mm insulated** | Panel-mounted on gantry |
| IEC C16 socket | L (hot) | AC inline fuse (6A) | In | Crimp/solder | |
| AC inline fuse | Out | Slip ring wire 1 | Stationary input | Solder or crimp butt | 15A rated |
| IEC C16 socket | N (neutral) | Slip ring wire 2 | Stationary input | Solder or crimp butt | 15A rated |
| IEC C16 socket | G (ground) | Slip ring wire 3 | Stationary input | Solder or crimp butt | 15A rated |
| Slip ring wire 1 | Rotating output | 12V PSU | AC Live | Screw terminal | Inside GEO-DUDe |
| Slip ring wire 2 | Rotating output | 12V PSU | AC Neutral | Screw terminal | Inside GEO-DUDe |
| Slip ring wire 3 | Rotating output | 12V PSU | AC Ground | Screw terminal / chassis | Inside GEO-DUDe |

### DC Power (all internal to GEO-DUDe)

| From | Terminal | To | Terminal | Wire Gauge | Fuse |
|------|----------|----|----------|-----------|------|
| 12V PSU | +12V | Main DC fuse (50A) | In | 12 AWG | - |
| Main DC fuse | Out | 12V bus (Wago) | In | 12 AWG | - |
| 12V bus | Out | 12V servo fuse (40A) | In | 14 AWG | - |
| 12V servo fuse | Out | 12V Wago block | In | 14 AWG | - |
| 12V Wago | Out | Base servo L | Power + | 16 AWG | - |
| 12V Wago | Out | Base servo R | Power + | 16 AWG | - |
| 12V Wago | Out | Shoulder servo L | Power + | 16 AWG | - |
| 12V Wago | Out | Shoulder servo R | Power + | 16 AWG | - |
| 12V Wago | Out | Wrist servos (TBD) | Power + | 16 AWG | - |
| 12V Wago | Out | 12V fan | +12V | 22 AWG | 1A inline |
| 12V bus | Out | Buck 1 fuse (8A) | In | 16 AWG | - |
| Buck 1 fuse | Out | Buck conv 1 | VIN+ | 16 AWG | - |
| Buck conv 1 (7.4V) | VOUT+ | 7.4V Wago block | In | 16 AWG | - |
| 7.4V Wago | Out | Elbow servo L | Power + | 18 AWG | - |
| 7.4V Wago | Out | Elbow servo R | Power + | 18 AWG | - |
| 12V bus | Out | Buck 2 fuse (3A) | In | 18 AWG | - |
| Buck 2 fuse | Out | Buck conv 2 | VIN+ | 18 AWG | - |
| Buck conv 2 (5V) | VOUT+ | 5V Wago block | In | 18 AWG | - |
| 5V Wago | Out | Raspberry Pi | 5V GPIO pin | 20 AWG | - |
| 5V Wago | Out | PCA9685 | VCC | 22 AWG | - |
| 5V Wago | Out | MG90S #1 | Power + | 22 AWG | - |
| 5V Wago | Out | MG90S #2 | Power + | 22 AWG | - |
| 5V Wago | Out | MG90S #3 | Power + | 22 AWG | - |
| 5V Wago | Out | MG90S #4 | Power + | 22 AWG | - |
| 12V PSU | GND | GND bus (Wago) | In | 12 AWG | - |
| GND bus | Out | All servo GND | GND | Various | Common ground |
| GND bus | Out | Buck conv 1 | GND | 16 AWG | |
| GND bus | Out | Buck conv 2 | GND | 18 AWG | |
| GND bus | Out | Pi | GND GPIO | 20 AWG | |
| GND bus | Out | PCA9685 | GND | 22 AWG | |

### Signal (all via PCA9685 I2C PWM driver)

| From | Pin | To | Pin | Cable | Notes |
|------|-----|----|-----|-------|-------|
| Pi | I2C SDA (GPIO 2) | PCA9685 | SDA | Dupont jumper | |
| Pi | I2C SCL (GPIO 3) | PCA9685 | SCL | Dupont jumper | |
| PCA9685 | Ch 0 | Base servo L | Signal | 22 AWG | PWM |
| PCA9685 | Ch 1 | Base servo R | Signal | 22 AWG | PWM |
| PCA9685 | Ch 2 | Shoulder servo L | Signal | 22 AWG | PWM |
| PCA9685 | Ch 3 | Shoulder servo R | Signal | 22 AWG | PWM |
| PCA9685 | Ch 4 | Elbow servo L | Signal | 22 AWG | PWM |
| PCA9685 | Ch 5 | Elbow servo R | Signal | 22 AWG | PWM |
| PCA9685 | Ch 6 | Wrist rotate L | Signal | 22 AWG | PWM |
| PCA9685 | Ch 7 | Wrist rotate R | Signal | 22 AWG | PWM |
| PCA9685 | Ch 8 | Wrist pan L | Signal | 22 AWG | PWM |
| PCA9685 | Ch 9 | Wrist pan R | Signal | 22 AWG | PWM |
| PCA9685 | Ch 10 | MG90S #1 | Signal | 22 AWG | End-effector |
| PCA9685 | Ch 11 | MG90S #2 | Signal | 22 AWG | End-effector |
| PCA9685 | Ch 12 | MG90S #3 | Signal | 22 AWG | End-effector |
| PCA9685 | Ch 13 | MG90S #4 | Signal | 22 AWG | End-effector |
| Pi | GPIO 4 | Limit switch 1 | Signal | 22 AWG | Base joint homing |
| Pi | GPIO 5 | Limit switch 2 | Signal | 22 AWG | Shoulder joint homing |
| Pi | GPIO 6 | Limit switch 3 | Signal | 22 AWG | Elbow joint homing |
| Pi | GPIO 17 | Limit switch 4 | Signal | 22 AWG | Wrist rotate homing |
| Pi | GPIO 27 | Limit switch 5 | Signal | 22 AWG | Wrist pan homing |
| Pi | GPIO 22 | Limit switch 6 | Signal | 22 AWG | End-effector homing |
| Pi | CSI connector | Pi Camera | Ribbon | Ribbon cable | |

### Connector Reference

| Connection Point | Connector Type | Notes |
|-----------------|---------------|-------|
| IEC C16 socket terminals | **Crimp spade terminals** (6.3mm insulated) | Need crimping tool |
| Slip ring wires | Solder or crimp butt connectors | Secure with heat shrink |
| 12V PSU AC input | Screw terminals (on PSU) | Strip and insert |
| 12V PSU DC output | Screw terminals (on PSU) | Strip and insert |
| DC bus distribution | **Wago lever connectors** | Tool-free, from Mach |
| Buck converter I/O | Screw terminals (on board) | Strip and insert |
| Servo power/signal | Bare leads or JST | Cut servo connector if needed |
| Pi GPIO | Dupont jumper pins | Standard 2.54mm headers |
| PCA9685 servo headers | 3-pin male headers | Signal only (power wired separately) |
| Pi Camera | CSI ribbon cable | Comes with camera |
| Limit switches | Bare wire to Dupont | Solder leads, crimp Dupont for Pi |
