#!/usr/bin/env python3
"""Generate KiCad netlist for GEO-DUDe Carrier PCB using SKiDL.

Run: /tmp/skidl-env/bin/python generate_netlist.py
Outputs: geodude-carrier.net (KiCad netlist)
"""

from skidl import *

# Set default tool to KiCad
set_default_tool(KICAD8)

# --- Power nets ---
vcc_12v = Net("+12V")
vcc_7v4 = Net("+7V4")
vcc_5v_servo = Net("+5V_SERVO")
vcc_5v_logic = Net("+5V_LOGIC")
vcc_3v3 = Net("+3V3")
gnd = Net("GND")

# I2C nets
sda = Net("SDA")
scl = Net("SCL")

# PWM signal nets
pwm = [Net(f"PWM_CH{i}") for i in range(16)]

# Per-servo fused power nets
sv_pwr = [Net(f"SV{i+1}_PWR") for i in range(10)]

# --- Power input terminals ---
# 12V needs 4 paralleled terminals (~9A each, 35A total possible)
TB_FP = "TerminalBlock:TerminalBlock_MaiXu_MX126-5.0-02P_1x02_P5.00mm"

for i in range(4):
    j = Part("Connector", "Screw_Terminal_01x02",
             ref=f"J_12V_{i+1}", value=f"12V_Input_{i+1}", footprint=TB_FP)
    j[1] += vcc_12v
    j[2] += gnd

j_7v4 = Part("Connector", "Screw_Terminal_01x02",
             ref="J_7V4", value="7V4_Input", footprint=TB_FP)
j_7v4[1] += vcc_7v4
j_7v4[2] += gnd

j_5v_servo = Part("Connector", "Screw_Terminal_01x02",
                   ref="J_5VS", value="5V_Servo_Input", footprint=TB_FP)
j_5v_servo[1] += vcc_5v_servo
j_5v_servo[2] += gnd

j_5v_logic = Part("Connector", "Screw_Terminal_01x02",
                   ref="J_5VL", value="5V_Logic_Input", footprint=TB_FP)
j_5v_logic[1] += vcc_5v_logic
j_5v_logic[2] += gnd

j_3v3 = Part("Connector", "Screw_Terminal_01x02",
             ref="J_3V3", value="3V3_Input", footprint=TB_FP)
j_3v3[1] += vcc_3v3
j_3v3[2] += gnd

# Common GND bus (2 paralleled terminals for current capacity)
for i in range(2):
    j = Part("Connector", "Screw_Terminal_01x02",
             ref=f"J_GND_{i+1}", value=f"GND_Bus_{i+1}", footprint=TB_FP)
    j[1] += gnd
    j[2] += gnd

# --- Fuses (10x, 5x20mm PCB-mount holders) ---
# Fuse ratings and voltage rail assignments:
# F1,F2 (Arm1 Base,Shoulder) = 8A on 12V
# F3 (Arm1 Elbow) = 5A on 7.4V
# F4,F5 (Arm1 Wrist Rot,Pan) = 3A on 5V_SERVO
# F6,F7 (Arm2 Base,Shoulder) = 8A on 12V
# F8 (Arm2 Elbow) = 5A on 7.4V
# F9,F10 (Arm2 Wrist Rot,Pan) = 3A on 5V_SERVO

fuse_config = [
    ("F1", "8A", vcc_12v, sv_pwr[0]),   # Arm1 Base
    ("F2", "8A", vcc_12v, sv_pwr[1]),   # Arm1 Shoulder
    ("F3", "5A", vcc_7v4, sv_pwr[2]),   # Arm1 Elbow
    ("F4", "3A", vcc_5v_servo, sv_pwr[3]),  # Arm1 Wrist Rot
    ("F5", "3A", vcc_5v_servo, sv_pwr[4]),  # Arm1 Wrist Pan
    ("F6", "8A", vcc_12v, sv_pwr[5]),   # Arm2 Base
    ("F7", "8A", vcc_12v, sv_pwr[6]),   # Arm2 Shoulder
    ("F8", "5A", vcc_7v4, sv_pwr[7]),   # Arm2 Elbow
    ("F9", "3A", vcc_5v_servo, sv_pwr[8]),  # Arm2 Wrist Rot
    ("F10", "3A", vcc_5v_servo, sv_pwr[9]), # Arm2 Wrist Pan
]

fuses = []
for ref, rating, rail, out_net in fuse_config:
    f = Part("Device", "Fuse", ref=ref, value=rating,
             footprint="Fuse:Fuse_Littelfuse_395Series")
    f[1] += rail
    f[2] += out_net
    fuses.append(f)

# --- PCA9685 breakout socket ---
# The breakout has two rows of headers. We model it as connectors.
# Left side: GND, OE, SCL, SDA, VCC, V+ (we don't use V+)
# Right side: 16 PWM outputs (0-15) in groups

# Control header (6-pin)
j_pca_ctrl = Part("Connector", "Conn_01x06_Pin",
                   ref="J_PCA_CTRL", value="PCA9685_Control",
                   footprint="Connector_PinHeader_2.54mm:PinHeader_1x06_P2.54mm_Vertical")
j_pca_ctrl[1] += gnd       # GND
j_pca_ctrl[2] += gnd       # OE (tied to GND = always enabled)
j_pca_ctrl[3] += scl       # SCL
j_pca_ctrl[4] += sda       # SDA
j_pca_ctrl[5] += vcc_3v3   # VCC (3.3V logic)
j_pca_ctrl[6] += NC        # V+ (not used, servo power separate)

# PWM output headers (2x 8-pin for Ch0-15)
j_pca_pwm_a = Part("Connector", "Conn_01x08_Pin",
                    ref="J_PCA_A", value="PCA9685_Ch0-7",
                    footprint="Connector_PinHeader_2.54mm:PinHeader_1x08_P2.54mm_Vertical")
for i in range(8):
    j_pca_pwm_a[i+1] += pwm[i]

j_pca_pwm_b = Part("Connector", "Conn_01x08_Pin",
                    ref="J_PCA_B", value="PCA9685_Ch8-15",
                    footprint="Connector_PinHeader_2.54mm:PinHeader_1x08_P2.54mm_Vertical")
for i in range(8):
    j_pca_pwm_b[i+1] += pwm[8+i]

# --- I2C bus breakout (4x 4-pin screw terminals) ---
i2c_labels = ["IMU", "Encoder", "Spare1", "Spare2"]
for idx, label in enumerate(i2c_labels):
    j = Part("Connector", "Screw_Terminal_01x04",
             ref=f"J_I2C{idx+1}", value=f"I2C_{label}",
             footprint="TerminalBlock:TerminalBlock_MaiXu_MX126-5.0-04P_1x04_P5.00mm")
    j[1] += sda
    j[2] += scl
    j[3] += vcc_3v3
    j[4] += gnd

# --- Servo output headers (10x 3-pin) ---
# Pin order: Signal (PWM), V+ (fused power), GND
servo_labels = [
    "Arm1_Base", "Arm1_Shoulder", "Arm1_Elbow",
    "Arm1_WristRot", "Arm1_WristPan",
    "Arm2_Base", "Arm2_Shoulder", "Arm2_Elbow",
    "Arm2_WristRot", "Arm2_WristPan",
]

for i, label in enumerate(servo_labels):
    sv = Part("Connector", "Conn_01x03_Pin",
              ref=f"SV{i+1}", value=label,
              footprint="Connector_PinHeader_2.54mm:PinHeader_1x03_P2.54mm_Vertical")
    sv[1] += pwm[i]       # Signal from PCA9685 Ch0-9
    sv[2] += sv_pwr[i]    # Fused power
    sv[3] += gnd           # GND

# --- ESC header (3-pin, no fuse, 12V direct) ---
esc = Part("Connector", "Conn_01x03_Pin",
           ref="J_ESC", value="MACE_ESC",
           footprint="Connector_PinHeader_2.54mm:PinHeader_1x03_P2.54mm_Vertical")
esc[1] += pwm[11]     # Signal from PCA9685 Ch11
esc[2] += vcc_12v     # 12V direct (ESC has built-in protection)
esc[3] += gnd

# --- Fan header (3-pin, no fuse, 12V direct) ---
fan = Part("Connector", "Conn_01x03_Pin",
           ref="J_FAN", value="Fan",
           footprint="Connector_PinHeader_2.54mm:PinHeader_1x03_P2.54mm_Vertical")
fan[1] += pwm[12]     # Signal from PCA9685 Ch12
fan[2] += vcc_12v     # 12V direct
fan[3] += gnd

# --- Generate netlist ---
generate_netlist(file_="geodude-carrier.net")
print("Netlist generated: geodude-carrier.net")
