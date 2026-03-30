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
| ESP32 | GPIO 32 (STEP) | TMC2209 #1 | STEP | Jumper | Yaw axis |
| ESP32 | GPIO 33 (DIR) | TMC2209 #1 | DIR | Jumper | Yaw axis |
| ESP32 | GPIO 25 (STEP) | TMC2209 #2 | STEP | Jumper | Pitch axis |
| ESP32 | GPIO 26 (DIR) | TMC2209 #2 | DIR | Jumper | Pitch axis |
| ESP32 | GPIO 23 (STEP) | TMC2209 #3 | STEP | Jumper | Roll axis |
| ESP32 | GPIO 22 (DIR) | TMC2209 #3 | DIR | Jumper | Roll axis |
| ESP32 | GPIO 19 (STEP) | TMC2209 #4 | STEP | Jumper | Belt motor |
| ESP32 | GPIO 18 (DIR) | TMC2209 #4 | DIR | Jumper | Belt motor |
| ESP32 | GPIO 16 (RX) / GPIO 17 (TX) | TMC2209 #1-4 | RX (PDN_UART) | Jumper | Shared bus, 1k resistor on TX, direct RX |
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

#### 12V Bus and Always-On Path (before toggle switch)

| From | Terminal | To | Terminal | Wire Gauge | Notes |
|------|----------|----|----------|-----------|-------|
| 12V PSU | +12V | Main DC fuse (30A) | In | **2x 16 AWG parallel** | |
| Main DC fuse | Out | 12V bus (Wago) | In | **2x 16 AWG parallel** | |
| 12V bus | Out | Buck 2 fuse (3A inline) | In | 18 AWG | **Always on** (before toggle switch) |
| Buck 2 fuse | Out | Buck conv 2 | VIN+ | 18 AWG | |
| Buck conv 2 (5V) | VOUT+ | 5V Pi Wago | In | 18 AWG | Pi + PCA9685 only |
| 5V Pi Wago | Out | Raspberry Pi | 5V GPIO pin | 20 AWG | |
| 5V Pi Wago | Out | PCA9685 | VCC | 22 AWG | Logic power only |

#### Toggle Switch and Buck Converters (after toggle switch)

| From | Terminal | To | Terminal | Wire Gauge | Notes |
|------|----------|----|----------|-----------|-------|
| 12V bus | Out | 40A Toggle Switch | Input | **2x 16 AWG parallel** | Jtron SPST, manual panel mount |
| 40A Toggle Switch | Output | Buck conv 1 | VIN+ | 18 AWG | Via 8A fuse |
| Buck conv 1 (7.4V) | VOUT+ | Arm 1 Fuse Board | 7.4V in | 18 AWG | Elbow fuse |
| Buck conv 1 (7.4V) | VOUT+ | Arm 2 Fuse Board | 7.4V in | 18 AWG | Elbow fuse |
| 40A Toggle Switch | Output | Buck conv 3 | VIN+ | 18 AWG | Via 8A fuse |
| Buck conv 3 (5V) | VOUT+ | Arm 1 Fuse Board | 5V in | 18 AWG | Wrist fuses |
| Buck conv 3 (5V) | VOUT+ | Arm 2 Fuse Board | 5V in | 18 AWG | Wrist fuses |

#### Arm 1 Fuse Board (perfboard, 5 fuses)

| From | Terminal | To | Terminal | Wire Gauge | Notes |
|------|----------|----|----------|-----------|-------|
| 40A Toggle Switch | 12V output | Arm 1 Base fuse (8A) | In | **16 AWG** | Glass tube slow-blow |
| Arm 1 Base fuse | Out | Arm 1 Base servo | Power + | servo lead | HOOYIJ 150kg |
| 40A Toggle Switch | 12V output | Arm 1 Shoulder fuse (8A) | In | **16 AWG** | Glass tube slow-blow |
| Arm 1 Shoulder fuse | Out | Arm 1 Shoulder servo | Power + | servo lead | ANNIMOS 150kg |
| Buck conv 1 (7.4V) | Via board | Arm 1 Elbow fuse (5A) | In | 18 AWG | Glass tube slow-blow |
| Arm 1 Elbow fuse | Out | Arm 1 Elbow servo | Power + | servo lead | ANNIMOS 80kg |
| Buck conv 3 (5V) | Via board | Arm 1 Wrist Rotate fuse (3A) | In | 18 AWG | Glass tube slow-blow |
| Arm 1 Wrist Rotate fuse | Out | Arm 1 Wrist Rotate servo | Power + | servo lead | RDS3218 |
| Buck conv 3 (5V) | Via board | Arm 1 Wrist Pan fuse (3A) | In | 18 AWG | Glass tube slow-blow |
| Arm 1 Wrist Pan fuse | Out | Arm 1 Wrist Pan servo | Power + | servo lead | RDS3218 |

#### Arm 2 Fuse Board (perfboard, 5 fuses -- identical to Arm 1)

| From | Terminal | To | Terminal | Wire Gauge | Notes |
|------|----------|----|----------|-----------|-------|
| 40A Toggle Switch | 12V output | Arm 2 Base fuse (8A) | In | **16 AWG** | Glass tube slow-blow |
| Arm 2 Base fuse | Out | Arm 2 Base servo | Power + | servo lead | HOOYIJ 150kg |
| 40A Toggle Switch | 12V output | Arm 2 Shoulder fuse (8A) | In | **16 AWG** | Glass tube slow-blow |
| Arm 2 Shoulder fuse | Out | Arm 2 Shoulder servo | Power + | servo lead | ANNIMOS 150kg |
| Buck conv 1 (7.4V) | Via board | Arm 2 Elbow fuse (5A) | In | 18 AWG | Glass tube slow-blow |
| Arm 2 Elbow fuse | Out | Arm 2 Elbow servo | Power + | servo lead | ANNIMOS 80kg |
| Buck conv 3 (5V) | Via board | Arm 2 Wrist Rotate fuse (3A) | In | 18 AWG | Glass tube slow-blow |
| Arm 2 Wrist Rotate fuse | Out | Arm 2 Wrist Rotate servo | Power + | servo lead | RDS3218 |
| Buck conv 3 (5V) | Via board | Arm 2 Wrist Pan fuse (3A) | In | 18 AWG | Glass tube slow-blow |
| Arm 2 Wrist Pan fuse | Out | Arm 2 Wrist Pan servo | Power + | servo lead | RDS3218 |

#### Other Power (after toggle switch)

| From | Terminal | To | Terminal | Wire Gauge | Notes |
|------|----------|----|----------|-----------|-------|
| 40A Toggle Switch | Output | ESC (40A) | Power + | 16 AWG | MACE reaction wheel |
| 40A Toggle Switch | Output | 12V fan | +12V | 22 AWG | Via 1A fuse |

#### GND (star topology via Wago bus)

| From | Terminal | To | Terminal | Wire Gauge | Notes |
|------|----------|----|----------|-----------|-------|
| 12V PSU | GND | GND bus (Wago) | In | **2x 16 AWG parallel** | Star ground point |
| GND bus | Out | Arm 1 Fuse Board | GND rail | **16 AWG** | |
| Arm 1 Fuse Board | GND | Arm 1 Base servo | GND | 16 AWG | Star topology |
| Arm 1 Fuse Board | GND | Arm 1 Shoulder servo | GND | 16 AWG | Star topology |
| Arm 1 Fuse Board | GND | Arm 1 Elbow servo | GND | 18 AWG | Star topology |
| Arm 1 Fuse Board | GND | Arm 1 Wrist Rotate | GND | 18 AWG | Star topology |
| Arm 1 Fuse Board | GND | Arm 1 Wrist Pan | GND | 18 AWG | Star topology |
| GND bus | Out | Arm 2 Fuse Board | GND rail | **16 AWG** | |
| Arm 2 Fuse Board | GND | Arm 2 Base servo | GND | 16 AWG | Star topology |
| Arm 2 Fuse Board | GND | Arm 2 Shoulder servo | GND | 16 AWG | Star topology |
| Arm 2 Fuse Board | GND | Arm 2 Elbow servo | GND | 18 AWG | Star topology |
| Arm 2 Fuse Board | GND | Arm 2 Wrist Rotate | GND | 18 AWG | Star topology |
| Arm 2 Fuse Board | GND | Arm 2 Wrist Pan | GND | 18 AWG | Star topology |
| GND bus | Out | 12V fan | GND | 22 AWG | Star topology |
| GND bus | Out | Buck conv 1 | GND | 18 AWG | Star topology |
| GND bus | Out | Buck conv 2 | GND | 18 AWG | Before toggle switch path |
| GND bus | Out | Buck conv 3 | GND | 18 AWG | Star topology |
| GND bus | Out | Pi | GND GPIO | 20 AWG | Star topology |
| GND bus | Out | PCA9685 | GND | 22 AWG | Star topology |
| GND bus | Out | Limit switches (all 10) | GND | 22 AWG | Star topology |

### Signal (all via PCA9685 I2C PWM driver)

| From | Pin | To | Pin | Cable | Notes |
|------|-----|----|-----|-------|-------|
| Pi | I2C SDA (GPIO 2) | PCA9685 | SDA | Dupont jumper | |
| Pi | I2C SCL (GPIO 3) | PCA9685 | SCL | Dupont jumper | |
| PCA9685 | Ch 0 | Arm 1 Base servo | Signal | 22 AWG | PWM |
| PCA9685 | Ch 1 | Arm 1 Shoulder servo | Signal | 22 AWG | PWM |
| PCA9685 | Ch 2 | Arm 1 Elbow servo | Signal | 22 AWG | PWM |
| PCA9685 | Ch 3 | Arm 1 Wrist Rotate | Signal | 22 AWG | PWM |
| PCA9685 | Ch 4 | Arm 1 Wrist Pan | Signal | 22 AWG | PWM |
| PCA9685 | Ch 5 | Arm 2 Base servo | Signal | 22 AWG | PWM |
| PCA9685 | Ch 6 | Arm 2 Shoulder servo | Signal | 22 AWG | PWM |
| PCA9685 | Ch 7 | Arm 2 Elbow servo | Signal | 22 AWG | PWM |
| PCA9685 | Ch 8 | Arm 2 Wrist Rotate | Signal | 22 AWG | PWM |
| PCA9685 | Ch 9 | Arm 2 Wrist Pan | Signal | 22 AWG | PWM |
| PCA9685 | Ch 14 | ESC | PWM | 22 AWG | MACE reaction wheel |

### Limit Switches (Pi GPIO direct)

| From | Pin | To | Pin | Cable | Notes |
|------|-----|----|-----|-------|-------|
| Pi | GPIO 4 | Arm 1 Base limit switch | Signal | 22 AWG | Internal pull-up |
| Pi | GPIO 5 | Arm 1 Shoulder limit switch | Signal | 22 AWG | Internal pull-up |
| Pi | GPIO 6 | Arm 1 Elbow limit switch | Signal | 22 AWG | Internal pull-up |
| Pi | GPIO 17 | Arm 1 Wrist Rotate limit switch | Signal | 22 AWG | Internal pull-up |
| Pi | GPIO 27 | Arm 1 Wrist Pan limit switch | Signal | 22 AWG | Internal pull-up |
| Pi | GPIO 22 | Arm 2 Base limit switch | Signal | 22 AWG | Internal pull-up |
| Pi | GPIO 23 | Arm 2 Shoulder limit switch | Signal | 22 AWG | Internal pull-up |
| Pi | GPIO 24 | Arm 2 Elbow limit switch | Signal | 22 AWG | Internal pull-up |
| Pi | GPIO 25 | Arm 2 Wrist Rotate limit switch | Signal | 22 AWG | Internal pull-up |
| Pi | GPIO 26 | Arm 2 Wrist Pan limit switch | Signal | 22 AWG | Internal pull-up |

### Other Signal

| From | Pin | To | Pin | Cable | Notes |
|------|-----|----|-----|-------|-------|
| Pi | CSI connector | Pi Camera | Ribbon | Ribbon cable | |

### Connector Reference

| Connection Point | Connector Type | Notes |
|-----------------|---------------|-------|
| IEC C16 socket terminals | **Crimp spade terminals** (6.3mm insulated) | Need crimping tool |
| Slip ring wires | Solder or crimp butt connectors | Secure with heat shrink |
| 12V PSU AC input | Screw terminals (on PSU) | Strip and insert |
| 12V PSU DC output | Screw terminals (on PSU) | Strip and insert |
| DC bus distribution | **Wago lever connectors** | Tool-free, from Mach |
| 40A Toggle Switch | Screw terminals | Jtron waterproof panel-mount |
| Buck converter I/O | Screw terminals (on board) | Strip and insert |
| Arm fuse boards | Glass tube fuse holders soldered to perfboard | 5 fuses per board |
| Servo power/signal | Bare leads or JST | Cut servo connector if needed |
| Pi GPIO | Dupont jumper pins | Standard 2.54mm headers |
| PCA9685 servo headers | 3-pin male headers | Signal only (power wired separately) |
| Pi Camera | CSI ribbon cable | Comes with camera |
| Limit switches | Bare wire to Dupont | Solder leads, crimp Dupont for Pi |
