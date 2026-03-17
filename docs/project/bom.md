# Bill of Materials

All components from the [master BOM spreadsheet](https://docs.google.com/spreadsheets/d/1E1N-070xhcGK5FVkjd1sBZlGc8as569FgII3UE0jsTo/edit).

---

## GEO-DUDe (Subscale Satellite)

Source: [Subscale Satellite BOM](https://docs.google.com/spreadsheets/d/1E1N-070xhcGK5FVkjd1sBZlGc8as569FgII3UE0jsTo/edit?gid=1535441720#gid=1535441720) tab

| Row | Item | Description | Qty | Cost | Link | Status |
|-----|------|-------------|-----|------|------|--------|
| 4 | PLA filament | For printing structure | 2 | $135.98 | [Amazon.ca](https://www.amazon.ca/ELEGOO-Filament-Toughness-Printing-Dimensional/dp/B0CLM1DCBN) | Not ordered |
| 5 | PCA9685 PWM controller | For controlling servos (pack of 2) | 1 | $19.99 | [Amazon.ca](https://www.amazon.ca/HUAREW-PCA9685-Interface-Compatible-Raspberry/dp/B0CRV3MK14) | Not ordered |
| 6 | Base servo motors | HOOYIJ 150kg | 2 | $97.98 | [Amazon.ca](https://www.amazon.ca/HOOYIJ-Digital-Waterproof-Stainless-Steering/dp/B0CX92QNJY) | Not ordered |
| 7 | Shoulder servo motors | ANNIMOS 150kg, robot version w/ brackets | 2 | $117.96 | [Amazon.ca](https://www.amazon.ca/ANNIMOS-Voltage-Digital-Steering-Brackets/dp/B0C69W2QP7) | Not ordered |
| 8 | Elbow servo motors | ANNIMOS 80kg, robot version w/ brackets | 2 | $77.98 | [Amazon.ca](https://www.amazon.ca/ANNIMOS-Waterproof-Digital-Steering-Brackets/dp/B0C69WWLWQ) | Not ordered |
| 9 | Wrist servo motors (rotate + pan) | Wishiot RDS3218 20kg, with U-bracket | 4 | $107.96 | [Amazon.ca](https://www.amazon.ca/Wishiot-RDS3218-Waterproof-Mounting-Bracket/dp/B0CCXRCFK4) | Not ordered |
| 10 | End-effector servo motors | Miuzei MG90S 2kg, pack of 4 | 1 | $21.99 | [Amazon.ca](https://www.amazon.ca/Miuzei-MG90S-Servo-Helicopter-Arduino/dp/B0CP98TZJ2) | Not ordered |
| 11 | Slip ring (3 wire) | For base rotation passthrough | 1 | $27.59 | [Amazon.ca](https://www.amazon.ca/Conductive-Current-Collecting-Electric-Connector/dp/B09NBLY16J) | Arrived |
| 12 | Raspberry Pi | Satellite controller | 1 | - | - | Have (Zeul) |
| 13 | Raspberry Pi camera | AI vision | 1 | - | - | Have (Zeul) |
| 14 | Power supply | 12V 600W | 1 | $57.99 | [Amazon.ca](https://www.amazon.ca/VAYALT-Switching-Universal-Transformer-Industrial/dp/B0DXL2BCGS) | Not ordered |
| 15 | ~~5V buck converter~~ | ~~Stepping down to 5V~~ | 0 | $0.00 | - | NOT NEEDED |
| 16 | 12V adjustable buck converter | High current, adjustable output | 4 | $66.00 | [Amazon.ca](https://www.amazon.ca/XLX-High-Power-Converter-Adjustable-Protection/dp/B081X5YX8V) | Not ordered |
| 17 | ~~I2C expander~~ | ~~PCF8575, pack of 3~~ | 0 | $0.00 | - | NOT NEEDED (6 limit switches fit on Pi GPIO) |
| 18 | 12V cooling fan | 80mm | 1 | $8.89 | [Amazon.ca](https://www.amazon.ca/KingWin-CF-08LB-80mm-Long-Bearing/dp/B002YFSHPY) | Not ordered |
| 19 | Limit switches | Momentary, pack of 12 | 2 | $21.38 | [Amazon.ca](https://www.amazon.ca/MKBKLLJY-Momentary-Terminal-Electronic-Appliance/dp/B0DK693J79) | Not ordered |
| 20 | Wago connectors | General purpose | - | - | - | Have (Mach) |
| 21 | IEC C16 socket | Mains input | 1 | $10.89 | [Amazon.ca](https://www.amazon.ca/Baomain-Panel-Power-Sockets-Connectors/dp/B00WFZH042) | Not ordered |
| 22 | 12-circuit fuse block | Cyrico, w/ negative bus, LED indicators, 24 blade fuses | 1 | - | [Amazon.ca](https://www.amazon.ca/Indicator-Waterproof-Circuits-Negative-Automotive/dp/B0C6Z49434) | Have (Mach) |
| 23 | 40A toggle switch | Jtron Waterproof DC12V 40A/24V 20A, SPST, ON-OFF, panel mount | 1 | $18.99 | - | Ordered |
| 24 | GPIO breakout HAT | GeeekPi, 40-pin screw terminal, no soldering | 1 | $12.99 | [Amazon.ca](https://www.amazon.ca/GeeekPi-Raspberry-Terminal-Breakout-Expansion/dp/B08GKQMC72) | Not ordered |
| | **--- Additional (from wiring diagrams) ---** | | | | | |
| 25 | 6A slow-blow AC fuse + inline holder | Protects AC hot line before slip ring | 1 | ~$5 | - | Not ordered |
| 26 | 30A blade fuse + inline holder | Main DC protection after 12V PSU | 1 | ~$5 | - | Not ordered |
| ~~27~~ | ~~2N2222 NPN transistor~~ | ~~Relay coil driver~~ | 0 | $0.00 | - | NOT NEEDED (relay replaced by toggle switch) |
| ~~28~~ | ~~1N4007 flyback diode~~ | ~~Relay back-EMF protection~~ | 0 | $0.00 | - | NOT NEEDED |
| ~~29~~ | ~~1k ohm resistor~~ | ~~Transistor base limiter~~ | 0 | $0.00 | - | NOT NEEDED |
| 30 | Crimp spade terminals | 6.3mm insulated, for fuse block/toggle switch/PSU | ~20 | ~$8 | - | Not ordered |
| 31 | Crimp butt connectors + heat shrink | Inline wire splices | ~10 | ~$5 | - | Not ordered |
| 32 | Wire, 16 AWG (red + black) | PSU to bus trunk (doubled for capacity), toggle switch to servo bus boards, base/shoulder servo branches | ~5m | ~$8 | - | Not ordered |
| 33 | Wire, 18 AWG | Buck converter inputs and outputs, always-on path | ~5m | ~$6 | - | Not ordered |
| 34 | Wire, 22 AWG | Signal, low-current (PCA9685, MG90S, fan) | ~2m | ~$3 | - | Not ordered |
| 35 | Dupont jumper wires | I2C, GPIO, PCA9685 signal connections | ~20 | ~$5 | - | Not ordered |

**GEO-DUDe Total: ~$845** (original ~$801 + ~$44 wiring/discrete)

---

## Gimbal (Testing Apparatus)

Source: [Testing Apparatus BOM](https://docs.google.com/spreadsheets/d/1E1N-070xhcGK5FVkjd1sBZlGc8as569FgII3UE0jsTo/edit?gid=276299618#gid=276299618) tab

| Row | Item | Description | Qty | Cost | Link | Status |
|-----|------|-------------|-----|------|------|--------|
| 4 | PLA filament | ELEGOO, pack of 4 | 2 | $135.98 | [Amazon.ca](https://www.amazon.ca/ELEGOO-Filament-Toughness-Printing-Dimensional/dp/B0CLM1DCBN) | Arrived |
| 5 | Linear rails + bearings | HGR15 1000mm, 2 rails + 4 HGH15CA | 1 | $74.88 | [Amazon.ca](https://www.amazon.ca/ANWOK-HGR15-1000mm-HGH15CA-Carriage-Bearing/dp/B09VC59SY1) | Arrived |
| 6 | Stepper motors | Gimbal actuation | 4 | $0.00 | - | Have (Aidan M) |
| 7 | Fasteners | M-size stainless set | 2 | $69.98 | [Amazon.ca](https://www.amazon.ca/2200Pcs-Assortment-Stainless-Washers-Wrenches/dp/B0D14JXHV3) | Arrived |
| 8 | Power supply | 24V 480W | 1 | $51.99 | [Amazon.ca](https://www.amazon.ca/BOSYTRO-Switching-Universal-Transformers-Upgraded/dp/B0F7XCLJVM) | Arrived |
| 9 | Primary base bearing | Roller bearing | 1 | $0.00 | - | Have (Aidan M) |
| 10 | Thrust bearings | AXK80105, 80mm bore | 2 | $30.18 | [Amazon.ca](https://www.amazon.ca/uxcell-AXK80105-Thrust-Bearings-Washers/dp/B07GC94P6Y) | Arrived |
| 11 | ESP32 | Gimbal controller | 1 | $0.00 | - | Have (Aidan M) |
| 12 | Stepper motor drivers | TMC2209, pack of 5 | 1 | $37.99 | [Amazon.ca](https://www.amazon.ca/BIGTREETECH-TMC2209-Stepper-Stepstick-Heatsink/dp/B0CQC7QMS2) | Arrived |
| 13 | Belt kit | 5M belt + pulleys + tensioners | 1 | $19.99 | [Amazon.ca](https://www.amazon.ca/dp/B08SMFM3Z6) | Arrived |
| 14 | 24V 80mm fans | Pack of 2 | 2 | $31.98 | [Amazon.ca](https://www.amazon.ca/GDSTIME-Brushless-Ventilateur-Computer-Applications/dp/B0F1FHQKZD) | Arrived |
| 15 | Stepper motor wires | 1M 6-pin to 4-pin, pack of 4 | 2 | $27.98 | [Amazon.ca](https://www.amazon.ca/Stepper-Cables-Printer-XH2-54-Terminal/dp/B0DKJ69DQX) | Arrived |
| 16 | Heat set inserts | M2/M2.5/M3/M4 brass set | 2 | $53.58 | [Amazon.ca](https://www.amazon.ca/Besitu-M2-M2-5-M3-M4/dp/B0CNRSJ1B2) | Arrived |
| 17 | VMOT decoupling caps | 100uF 50V + 100nF ceramic per driver (4 sets) | 4 | - | - | Not ordered |
| | **--- Additional (from wiring diagrams) ---** | | | | | |
| 18 | 5V USB adapter | Separate power for ESP32 (not from 24V bus) | 1 | ~$5 | - | Not ordered |
| 19 | 12A DC fuse + holder | Main DC protection after 24V PSU | 1 | ~$5 | - | Not ordered |
| 20 | 1k ohm resistor | UART TX/RX bridge for TMC2209 single-wire bus | 1 | ~$1 | - | Not ordered |
| 21 | Breadboard | Mounting TMC2209 drivers, ESP32 wiring | 1 | ~$5 | - | Not ordered |
| 22 | Wire, 18 AWG | 24V bus to TMC2209 VMOT inputs | ~2m | ~$4 | - | Not ordered |
| 23 | Dupont jumper wires | STEP/DIR/UART/VIO/MS1/MS2 connections | ~30 | ~$5 | - | Not ordered |

**Gimbal Total: ~$560** (original ~$535 + ~$25 wiring/discrete)

---

**Combined Total: ~$1,405**

---

### Notes

- **Blade fuses** (8A, 3A, 1A) for the Cyrico fuse block are already included with the fuse block (24 blade fuses come in the box). The Cyrico fuse block is used for buck converter inputs and fan.
- **Wago connectors** are covered by Mach's existing supply.
- Most of the additional items are cheap discrete components (~$5-15 total for fuses). Wire and terminals are the main cost items.
- **Wire gauges needed:** Only 16, 18, and 22 AWG (no 10 or 14 AWG needed for the GEO-DUDe 12V system).
