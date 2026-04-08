#!/usr/bin/env python3
"""PCA9685 connection test and channel mapping for GEO-DUDe."""

import smbus2
import time
import struct

PCA9685_ADDR = 0x40
I2C_BUS = 1

# Registers
MODE1 = 0x00
MODE2 = 0x01
PRESCALE = 0xFE
LED0_ON_L = 0x06  # each channel is 4 registers: ON_L, ON_H, OFF_L, OFF_H

# Channel mapping (pin - 1 = 0-indexed channel)
CHANNELS = {
    "B1":   15,  # pin 16
    "S1":   14,  # pin 15
    "B2":   13,  # pin 14
    "S2":   12,  # pin 13
    "MACE": 11,  # pin 12
    "E1":    6,  # pin 7
    "E2":    4,  # pin 5
    "W1A":   3,  # pin 4
    "W1B":   2,  # pin 3
    "W2A":   1,  # pin 2
    "W2B":   0,  # pin 1
}


class PCA9685:
    def __init__(self, bus_num=I2C_BUS, addr=PCA9685_ADDR):
        self.bus = smbus2.SMBus(bus_num)
        self.addr = addr

    def read_reg(self, reg):
        return self.bus.read_byte_data(self.addr, reg)

    def write_reg(self, reg, val):
        self.bus.write_byte_data(self.addr, reg, val)

    def init(self, freq=50):
        """Initialize PCA9685 with given PWM frequency (default 50Hz for servos)."""
        # Put to sleep before changing prescale
        mode1 = self.read_reg(MODE1)
        self.write_reg(MODE1, (mode1 & 0x7F) | 0x10)  # sleep
        # Set prescale: freq = 25MHz / (4096 * (prescale + 1))
        prescale = round(25_000_000 / (4096 * freq)) - 1
        self.write_reg(PRESCALE, prescale)
        # Wake up
        self.write_reg(MODE1, mode1 & 0xEF)  # clear sleep
        time.sleep(0.005)
        # Enable auto-increment, restart
        self.write_reg(MODE1, mode1 | 0xA0)
        actual_freq = 25_000_000 / (4096 * (prescale + 1))
        return prescale, actual_freq

    def set_pwm(self, channel, on, off):
        """Set raw PWM on/off counts (0-4095) for a channel."""
        reg = LED0_ON_L + 4 * channel
        self.bus.write_i2c_block_data(self.addr, reg, [
            on & 0xFF, (on >> 8) & 0xFF,
            off & 0xFF, (off >> 8) & 0xFF,
        ])

    def set_pulse_us(self, channel, pulse_us, freq=50):
        """Set PWM pulse width in microseconds."""
        period_us = 1_000_000 / freq
        counts = int(pulse_us / period_us * 4096)
        counts = max(0, min(4095, counts))
        self.set_pwm(channel, 0, counts)

    def off(self, channel):
        """Turn channel fully off."""
        self.set_pwm(channel, 0, 0)

    def all_off(self):
        """Turn all channels off."""
        for ch in range(16):
            self.off(ch)

    def close(self):
        self.all_off()
        self.bus.close()


def main():
    print("=== PCA9685 Connection Test ===\n")

    pca = PCA9685()

    # Read identification
    mode1 = pca.read_reg(MODE1)
    mode2 = pca.read_reg(MODE2)
    prescale_raw = pca.read_reg(PRESCALE)
    print(f"MODE1:    0x{mode1:02X}")
    print(f"MODE2:    0x{mode2:02X}")
    print(f"PRESCALE: {prescale_raw} (raw)")
    print()

    # Initialize at 50Hz
    prescale, actual_freq = pca.init(freq=50)
    print(f"Initialized: prescale={prescale}, freq={actual_freq:.1f}Hz")
    print()

    # Verify channel mapping
    print("Channel mapping:")
    print(f"  {'Name':<6} {'Pin':<5} {'Ch':<5}")
    print(f"  {'-'*16}")
    for name, ch in sorted(CHANNELS.items(), key=lambda x: x[1]):
        pin = ch + 1
        print(f"  {name:<6} {pin:<5} {ch:<5}")
    print()

    # Test: set all mapped channels to neutral (1500us) briefly
    print("Setting all channels to neutral (1500us)...")
    for name, ch in CHANNELS.items():
        pca.set_pulse_us(ch, 1500)
    time.sleep(0.5)

    print("Setting all channels off...")
    pca.all_off()
    print()
    print("PCA9685 connection OK")

    pca.close()


if __name__ == "__main__":
    main()
