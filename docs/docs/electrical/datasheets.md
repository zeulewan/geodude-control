# Datasheets and Specifications

Reference links for every electrical component. PDF links where available, Amazon listings for Chinese components without formal datasheets.

---

## GEO-DUDe (12V System)

### Servos

| Component | Datasheet | Voltage | Stall Current | Notes |
|-----------|-----------|---------|---------------|-------|
| HOOYIJ RDS51150 (150kg base) | [Amazon.ca](https://www.amazon.ca/HOOYIJ-Digital-Waterproof-Stainless-Steering/dp/B0CX92QNJY), [Specs page](https://www.motorobit.com/rds51150-150kg-digital-servo-motor-180-u-servo-bracket-included) | 9-12.6V | 8.0A @ 12V | DSServo RDS51150SG rebrand, IP66, 270 deg, 18T spline |
| ANNIMOS 150kg (shoulder) | [Spec sheet PDF](https://m.media-amazon.com/images/I/81atmTkZyeL.pdf), [Amazon.ca](https://www.amazon.ca/ANNIMOS-Voltage-Digital-Steering-Brackets/dp/B0C69W2QP7) | 9-12.6V | 8.0A @ 12V | Same DSServo RDS51150SG internals as HOOYIJ, IP67 |
| ANNIMOS DS5180 (80kg elbow) | [Spec sheet PDF](https://m.media-amazon.com/images/I/81+tlTNEl7L.pdf), [Amazon.ca](https://www.amazon.ca/ANNIMOS-Waterproof-Digital-Steering-Brackets/dp/B0C69WWLWQ) | 6-8.4V | 5.4A @ 7.4V | Copper/aluminum gear, IP67. Max 8.4V, needs buck to 7.4V |
| Wishiot RDS3218 (20kg wrist) | [DSServo downloads](https://www.dsservo.com/en/download.asp), [Amazon.ca](https://www.amazon.ca/Wishiot-RDS3218-Waterproof-Mounting-Bracket/dp/B0CCXRCFK4) | 4.8-6.8V | ~2.5A stall | 270 deg, 25T spline, IP66. Needs 5V buck |
| ~~Miuzei MG90S (2kg end-effector)~~ | ~~[Tower Pro datasheet PDF](https://www.electronicoscaldas.com/datasheet/MG90S_Tower-Pro.pdf)~~ | ~~4.8-6.0V~~ | ~~\~650mA stall~~ | ~~Dropped (end-effector deferred)~~ |

### Controllers and ICs

| Component | Datasheet | Notes |
|-----------|-----------|-------|
| PCA9685 16-ch PWM driver | [NXP official PDF](https://www.nxp.com/docs/en/data-sheet/PCA9685.pdf) | I2C, 12-bit resolution, 24-1526 Hz, up to 62 devices per bus |
| Raspberry Pi 4 Model B | [RPi datasheet PDF](https://datasheets.raspberrypi.com/rpi4/raspberry-pi-4-datasheet.pdf), [Product brief](https://datasheets.raspberrypi.com/rpi4/raspberry-pi-4-product-brief.pdf) | BCM2711, 2.4/5 GHz WiFi, 40-pin GPIO |

### Power

| Component | Datasheet | Specs |
|-----------|-----------|-------|
| VAYALT 12V 600W PSU | [Amazon.ca](https://www.amazon.ca/VAYALT-Switching-Universal-Transformer-Industrial/dp/B0DXL2BCGS) | AC 85-265V in, 12V 50A out, OCP/OVP/OTP/SCP. No formal datasheet (generic Chinese SMPS) |
| XLX 20A 300W buck converter | [Module datasheet PDF](https://rajguruelectronics.com/Product/21609/300W%2020A%20DC-DC%20Buck%20Converter_datasheet.pdf), [Amazon.ca](https://www.amazon.ca/XLX-High-Power-Converter-Adjustable-Protection/dp/B081X5YX8V) | 6-40V in, 1.2-36V adj out, 20A max/15A cont, CV/CC modes |
| 3-wire 15A slip ring | [Amazon.ca](https://www.amazon.ca/Conductive-Current-Collecting-Electric-Connector/dp/B09NBLY16J) | 3 circuits, 15A/circuit, 0-600V, 250 RPM max, IP51. No formal datasheet |

---

## Gimbal (24V System)

### Stepper Drivers

| Component | Datasheet | Notes |
|-----------|-----------|-------|
| TMC2209 IC (Trinamic) | [Analog Devices datasheet PDF](https://www.analog.com/media/en/technical-documentation/data-sheets/tmc2209_datasheet_rev1.09.pdf), [Product page](https://www.analog.com/en/products/tmc2209.html) | VM 4.75-29V, 2A RMS/2.8A peak, StealthChop2, StallGuard4, UART |
| BIGTREETECH TMC2209 V1.3 module | [BTT user manual PDF](https://github.com/bigtreetech/BIGTREETECH-Stepper-Motor-Driver/blob/master/TMC2209/V1.3/manual/BIGTREETECH%20TMC2209%20V1.3%20User%20Manual.pdf), [V1.2 GitHub repo](https://github.com/bigtreetech/BIGTREETECH-TMC2209-V1.2) | 12-28V, 110 mOhm sense resistors (1.77A effective RMS max), heatsink included |

### Controllers

| Component | Datasheet | Notes |
|-----------|-----------|-------|
| ESP32-WROOM-32 module | [Espressif WROOM-32 PDF](https://www.espressif.com/sites/default/files/documentation/esp32-wroom-32_datasheet_en.pdf) | Dual-core 240 MHz, WiFi+BT, 4MB flash |
| ESP32 SoC | [Espressif ESP32 PDF](https://www.espressif.com/sites/default/files/documentation/esp32_datasheet_en.pdf) | Full chip reference |
| DOIT ESP32 DevKit V1 (board) | [Pinout reference](https://www.espboards.dev/esp32/esp32doit-devkit-v1/) | CP2102 USB bridge, 30 GPIO exposed |

### Power

| Component | Datasheet | Specs |
|-----------|-----------|-------|
| BOSYTRO 24V 480W PSU | [Amazon.ca](https://www.amazon.ca/BOSYTRO-Switching-Universal-Transformers-Upgraded/dp/B0F7XCLJVM) | AC 85-265V in, 24V 20A out, OCP/OVP/OTP/SCP. No formal datasheet (generic Chinese SMPS) |

---

## Servo Specifications (Quick Reference)

All servos are dumb PWM. Control signal: 500-2500 us pulse width, 50-330 Hz.

| Servo | Model | Voltage | Torque | Stall I | Speed (no-load) | Rotation | Gear | IP | Weight |
|-------|-------|---------|--------|---------|-----------------|----------|------|----|--------|
| Base 150kg | RDS51150SG | 9-12.6V | 165 kg-cm @12V | 8.0A | 0.21s/60 @12V | 270 | Steel, 18T, 357:1 | IP66 | 163g |
| Shoulder 150kg | RDS51150SG | 9-12.6V | 165 kg-cm @12V | 8.0A | 0.21s/60 @12V | 270 | Steel, 18T, 357:1 | IP67 | 175g |
| Elbow 80kg | DS5180 | 6-8.4V | 78 kg-cm @7.4V | 5.4A | 0.21s/60 @7.4V | 270 | Cu/Al, 18T | IP67 | 165g |
| Wrist 20kg | RDS3218 | 4.8-6.8V | 19 kg-cm @5V | ~2.5A | 0.16s/60 @5V | 270 | Cu/Al, 25T | IP66 | 60g |
| ~~End-effector 2kg~~ | ~~MG90S~~ | ~~4.8-6.0V~~ | ~~1.8 kg-cm @4.8V~~ | ~~\~650mA~~ | ~~0.10s/60 @4.8V~~ | ~~180~~ | ~~Metal~~ | ~~-~~ | ~~13.4g~~ |

---

## Notes

- **Chinese servo datasheets:** HOOYIJ, ANNIMOS, and Wishiot are all DSServo Technology Co. (Dongguan) products sold under different brand names. The Amazon-hosted PDFs linked above are image scans of manufacturer spec cards, which are the best publicly available documentation.
- **PSU datasheets:** Both the VAYALT and BOSYTRO PSUs are generic Chinese switching power supplies without formal published datasheets. For safety-critical upgrades, consider Mean Well equivalents (LRS-600-12 for 12V, LRS-480-24 for 24V) which have UL/TUV certified datasheets.
- **DSServo download page:** [dsservo.com/en/download.asp](https://www.dsservo.com/en/download.asp) has PDFs for the RDS3218/DS3218 but not the RDS51150.
