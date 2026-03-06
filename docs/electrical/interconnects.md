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
| 24V bus | Out | TMC2209 #1 | VMOT | 18 AWG | 100uF 50V cap at driver |
| 24V bus | Out | TMC2209 #2 | VMOT | 18 AWG | 100uF 50V cap at driver |
| 24V bus | Out | TMC2209 #3 | VMOT | 18 AWG | 100uF 50V cap at driver |
| 24V bus | Out | TMC2209 #4 | VMOT | 18 AWG | 100uF 50V cap at driver |
| 24V bus | Out | 24V Fans | +24V | 22 AWG | - |
| 24V PSU | GND | GND bus (Wago) | In | 14 AWG | - |
| ESP32 3.3V | Out | TMC2209 #1-4 | VIO | 22 AWG | Shared logic supply |
| USB adapter | USB | ESP32 | USB port | USB cable | - |

### Signal

| From | Pin | To | Pin | Cable | Notes |
|------|-----|----|-----|-------|-------|
| ESP32 | GPIO 13 (STEP) | TMC2209 #1 | STEP | Jumper | Yaw axis |
| ESP32 | GPIO 14 (DIR) | TMC2209 #1 | DIR | Jumper | Yaw axis |
| ESP32 | GPIO 16 (STEP) | TMC2209 #2 | STEP | Jumper | Pitch axis |
| ESP32 | GPIO 17 (DIR) | TMC2209 #2 | DIR | Jumper | Pitch axis |
| ESP32 | GPIO 18 (STEP) | TMC2209 #3 | STEP | Jumper | Roll axis |
| ESP32 | GPIO 19 (DIR) | TMC2209 #3 | DIR | Jumper | Roll axis |
| ESP32 | GPIO 25 (STEP) | TMC2209 #4 | STEP | Jumper | Belt motor |
| ESP32 | GPIO 26 (DIR) | TMC2209 #4 | DIR | Jumper | Belt motor |
| ESP32 | GPIO TBD (UART) | TMC2209 #1-4 | PDN_UART | Jumper | Shared bus, 1k bridge TX/RX |
| TMC2209 #1 | MS1/MS2 | GND/GND | - | Jumper | Address 0 |
| TMC2209 #2 | MS1/MS2 | 3.3V/GND | - | Jumper | Address 1 |
| TMC2209 #3 | MS1/MS2 | GND/3.3V | - | Jumper | Address 2 |
| TMC2209 #4 | MS1/MS2 | 3.3V/3.3V | - | Jumper | Address 3 |
| TMC2209 #1-4 | CLK | GND | - | Jumper | Internal 12MHz clock |
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

#### 12V Bus and Always-On Path (before relay)

| From | Terminal | To | Terminal | Wire Gauge | Notes |
|------|----------|----|----------|-----------|-------|
| 12V PSU | +12V | Main DC fuse (25A) | In | **10 AWG** | |
| Main DC fuse | Out | 12V bus (Wago) | In | **10 AWG** | |
| 12V bus | Out | Buck 2 fuse (3A inline) | In | 18 AWG | **Always on** (before relay) |
| Buck 2 fuse | Out | Buck conv 2 | VIN+ | 18 AWG | |
| Buck conv 2 (5V) | VOUT+ | 5V Pi Wago | In | 18 AWG | Pi + PCA9685 only |
| 5V Pi Wago | Out | Raspberry Pi | 5V GPIO pin | 20 AWG | |
| 5V Pi Wago | Out | PCA9685 | VCC | 22 AWG | Logic power only |

#### Relay and Fuse Block (servo power, after relay)

| From | Terminal | To | Terminal | Wire Gauge | Notes |
|------|----------|----|----------|-----------|-------|
| 12V bus | Out | 40A Relay | Input | **10 AWG** | Normally open, Pi GPIO controlled |
| 40A Relay | Output | Cyrico fuse block | +12V in | **10 AWG** | All servo power through here |
| Fuse block | 15A circuit | Base servo L | Power + | 14 AWG | |
| Fuse block | 15A circuit | Base servo R | Power + | 14 AWG | |
| Fuse block | 15A circuit | Shoulder servo L | Power + | 14 AWG | |
| Fuse block | 15A circuit | Shoulder servo R | Power + | 14 AWG | |
| Fuse block | 8A circuit | Buck conv 1 | VIN+ | 16 AWG | |
| Buck conv 1 (7.4V) | VOUT+ | 7.4V Wago | In | 16 AWG | |
| 7.4V Wago | Out | Elbow servo L | Power + | 18 AWG | |
| 7.4V Wago | Out | Elbow servo R | Power + | 18 AWG | |
| Fuse block | 8A circuit | Buck conv 3 | VIN+ | 16 AWG | |
| Buck conv 3 (5V) | VOUT+ | 5V Servo Wago | In | 16 AWG | Servo 5V only (after relay) |
| 5V Servo Wago | Out | Wrist rotate L (RDS3218) | Power + | 18 AWG | |
| 5V Servo Wago | Out | Wrist rotate R (RDS3218) | Power + | 18 AWG | |
| 5V Servo Wago | Out | Wrist pan L (RDS3218) | Power + | 18 AWG | |
| 5V Servo Wago | Out | Wrist pan R (RDS3218) | Power + | 18 AWG | |
| 5V Servo Wago | Out | MG90S #1 | Power + | 22 AWG | |
| 5V Servo Wago | Out | MG90S #2 | Power + | 22 AWG | |
| 5V Servo Wago | Out | MG90S #3 | Power + | 22 AWG | |
| 5V Servo Wago | Out | MG90S #4 | Power + | 22 AWG | |
| Fuse block | 1A circuit | 12V fan | +12V | 22 AWG | |

#### GND (star topology via fuse block negative bus)

| From | Terminal | To | Terminal | Wire Gauge | Notes |
|------|----------|----|----------|-----------|-------|
| 12V PSU | GND | GND bus (Wago) | In | **10 AWG** | Star ground point |
| GND bus | Out | Fuse block | Negative bus | **10 AWG** | Fuse block has built-in GND bus |
| Fuse block neg bus | Out | Base servo L | GND | 14 AWG | Star topology |
| Fuse block neg bus | Out | Base servo R | GND | 14 AWG | Star topology |
| Fuse block neg bus | Out | Shoulder servo L | GND | 14 AWG | Star topology |
| Fuse block neg bus | Out | Shoulder servo R | GND | 14 AWG | Star topology |
| Fuse block neg bus | Out | Buck conv 1 | GND | 16 AWG | Star topology |
| Fuse block neg bus | Out | Elbow servo L | GND | 18 AWG | Via buck 1 GND or direct |
| Fuse block neg bus | Out | Elbow servo R | GND | 18 AWG | Via buck 1 GND or direct |
| Fuse block neg bus | Out | Buck conv 3 | GND | 16 AWG | Star topology |
| Fuse block neg bus | Out | Wrist rotate L | GND | 18 AWG | Via buck 3 GND or direct |
| Fuse block neg bus | Out | Wrist rotate R | GND | 18 AWG | Via buck 3 GND or direct |
| Fuse block neg bus | Out | Wrist pan L | GND | 18 AWG | Via buck 3 GND or direct |
| Fuse block neg bus | Out | Wrist pan R | GND | 18 AWG | Via buck 3 GND or direct |
| Fuse block neg bus | Out | MG90S #1-4 | GND | 22 AWG | Via buck 3 GND or direct |
| Fuse block neg bus | Out | 12V fan | GND | 22 AWG | Star topology |
| GND bus | Out | Buck conv 2 | GND | 18 AWG | Before relay path |
| GND bus | Out | Pi | GND GPIO | 20 AWG | Star topology |
| GND bus | Out | PCA9685 | GND | 22 AWG | Star topology |

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
| Pi | GPIO TBD | 40A Relay coil | Control | 22 AWG | Via transistor driver circuit |
| Pi | CSI connector | Pi Camera | Ribbon | Ribbon cable | |

### Connector Reference

| Connection Point | Connector Type | Notes |
|-----------------|---------------|-------|
| IEC C16 socket terminals | **Crimp spade terminals** (6.3mm insulated) | Need crimping tool |
| Slip ring wires | Solder or crimp butt connectors | Secure with heat shrink |
| 12V PSU AC input | Screw terminals (on PSU) | Strip and insert |
| 12V PSU DC output | Screw terminals (on PSU) | Strip and insert |
| DC bus distribution | **Wago lever connectors** | Tool-free, from Mach |
| Cyrico fuse block | Blade fuse + screw terminals | 12-circuit, has negative bus |
| 40A Relay | Spade terminals or bolt | Automotive style, Pi GPIO via transistor |
| Buck converter I/O | Screw terminals (on board) | Strip and insert |
| Servo power/signal | Bare leads or JST | Cut servo connector if needed |
| Pi GPIO | Dupont jumper pins | Standard 2.54mm headers |
| PCA9685 servo headers | 3-pin male headers | Signal only (power wired separately) |
| Pi Camera | CSI ribbon cable | Comes with camera |
| Limit switches | Bare wire to Dupont | Solder leads, crimp Dupont for Pi |
