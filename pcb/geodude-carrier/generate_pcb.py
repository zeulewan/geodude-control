#!/usr/bin/env python3
"""Generate KiCad PCB for GEO-DUDe Carrier Board.

Run with KiCad's Python:
/Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/Current/bin/python3 generate_pcb.py
"""

import pcbnew
import os

# Board dimensions (mm)
BOARD_W = 150
BOARD_H = 120

def mm(val):
    return pcbnew.FromMM(val)

def place_footprint(board, lib, fp_name, ref, value, x, y, angle=0):
    fp = pcbnew.FootprintLoad(lib, fp_name)
    if fp is None:
        print(f"WARNING: Could not load {lib}/{fp_name}")
        return None
    fp.SetReference(ref)
    fp.SetValue(value)
    fp.SetPosition(pcbnew.VECTOR2I(mm(x), mm(y)))
    if angle:
        fp.SetOrientationDegrees(angle)
    board.Add(fp)
    return fp

def main():
    board = pcbnew.BOARD()

    # Board outline
    outline = pcbnew.PCB_SHAPE(board)
    outline.SetShape(pcbnew.SHAPE_T_RECT)
    outline.SetStart(pcbnew.VECTOR2I(mm(0), mm(0)))
    outline.SetEnd(pcbnew.VECTOR2I(mm(BOARD_W), mm(BOARD_H)))
    outline.SetLayer(pcbnew.Edge_Cuts)
    outline.SetWidth(mm(0.1))
    board.Add(outline)

    # Library paths
    fp_base = "/Applications/KiCad/KiCad.app/Contents/SharedSupport/footprints"
    tb_lib = os.path.join(fp_base, "TerminalBlock.pretty")
    conn_lib = os.path.join(fp_base, "Connector_PinHeader_2.54mm.pretty")
    fuse_lib = os.path.join(fp_base, "Fuse.pretty")

    # Footprint names
    TB_2PIN = "TerminalBlock_MaiXu_MX126-5.0-02P_1x02_P5.00mm"
    TB_4PIN = "TerminalBlock_MaiXu_MX126-5.0-04P_1x04_P5.00mm"
    FUSE_5x20 = "Fuseholder_Clip-5x20mm_Keystone_3517_Inline_P23.11x6.76mm_D1.70mm_Horizontal"
    HDR_3PIN = "PinHeader_1x03_P2.54mm_Vertical"
    HDR_6PIN = "PinHeader_1x06_P2.54mm_Vertical"
    HDR_8PIN = "PinHeader_1x08_P2.54mm_Vertical"

    # === POWER INPUT TERMINALS (left edge, vertical stack) ===
    pwr_x = 12
    pwr_y_start = 15
    pwr_spacing = 18
    power_inputs = [
        ("J_12V", "12V_Input"),
        ("J_7V4", "7V4_Input"),
        ("J_5VS", "5V_Servo"),
        ("J_5VL", "5V_Logic"),
        ("J_3V3", "3V3_Input"),
    ]
    for i, (ref, val) in enumerate(power_inputs):
        place_footprint(board, tb_lib, TB_2PIN, ref, val,
                        pwr_x, pwr_y_start + i * pwr_spacing)

    # === FUSE HOLDERS (center-left, two rows of 5) ===
    # Fuse holders are ~26x11mm, need 14mm vertical spacing
    fuse_x_arm1 = 45
    fuse_x_arm2 = 75
    fuse_y_start = 12
    fuse_spacing = 15

    fuse_data = [
        # Arm 1
        ("F1", "8A", fuse_x_arm1),
        ("F2", "8A", fuse_x_arm1),
        ("F3", "5A", fuse_x_arm1),
        ("F4", "3A", fuse_x_arm1),
        ("F5", "3A", fuse_x_arm1),
        # Arm 2
        ("F6", "8A", fuse_x_arm2),
        ("F7", "8A", fuse_x_arm2),
        ("F8", "5A", fuse_x_arm2),
        ("F9", "3A", fuse_x_arm2),
        ("F10", "3A", fuse_x_arm2),
    ]
    for i, (ref, val, fx) in enumerate(fuse_data):
        row = i % 5
        place_footprint(board, fuse_lib, FUSE_5x20, ref, val,
                        fx, fuse_y_start + row * fuse_spacing)

    # === SERVO/ESC/FAN HEADERS (right side, two columns) ===
    sv_x_arm1 = 110
    sv_x_arm2 = 125
    sv_y_start = 12
    sv_spacing = 10

    servo_data = [
        ("SV1", "Arm1_Base", sv_x_arm1),
        ("SV2", "Arm1_Shoulder", sv_x_arm1),
        ("SV3", "Arm1_Elbow", sv_x_arm1),
        ("SV4", "Arm1_WristRot", sv_x_arm1),
        ("SV5", "Arm1_WristPan", sv_x_arm1),
        ("SV6", "Arm2_Base", sv_x_arm2),
        ("SV7", "Arm2_Shoulder", sv_x_arm2),
        ("SV8", "Arm2_Elbow", sv_x_arm2),
        ("SV9", "Arm2_WristRot", sv_x_arm2),
        ("SV10", "Arm2_WristPan", sv_x_arm2),
    ]
    for i, (ref, val, sx) in enumerate(servo_data):
        row = i % 5
        place_footprint(board, conn_lib, HDR_3PIN, ref, val,
                        sx, sv_y_start + row * sv_spacing)

    # ESC and Fan below servos
    place_footprint(board, conn_lib, HDR_3PIN, "J_ESC", "MACE_ESC",
                    sv_x_arm1, sv_y_start + 5 * sv_spacing + 5)
    place_footprint(board, conn_lib, HDR_3PIN, "J_FAN", "Fan",
                    sv_x_arm2, sv_y_start + 5 * sv_spacing + 5)

    # === PCA9685 SOCKET (center bottom) ===
    pca_y = 95
    place_footprint(board, conn_lib, HDR_6PIN, "J_PCA_CTRL", "PCA_Ctrl",
                    45, pca_y)
    place_footprint(board, conn_lib, HDR_8PIN, "J_PCA_A", "PCA_Ch0-7",
                    60, pca_y)
    place_footprint(board, conn_lib, HDR_8PIN, "J_PCA_B", "PCA_Ch8-15",
                    75, pca_y)

    # === I2C BREAKOUT (bottom edge) ===
    i2c_y = 110
    i2c_spacing = 28
    i2c_data = [
        ("J_I2C1", "I2C_IMU"),
        ("J_I2C2", "I2C_Encoder"),
        ("J_I2C3", "I2C_Spare1"),
        ("J_I2C4", "I2C_Spare2"),
    ]
    for i, (ref, val) in enumerate(i2c_data):
        place_footprint(board, tb_lib, TB_4PIN, ref, val,
                        25 + i * i2c_spacing, i2c_y)

    # Save
    output = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "geodude-carrier.kicad_pcb")
    board.Save(output)
    print(f"PCB saved: {output}")
    print(f"Board: {BOARD_W}mm x {BOARD_H}mm")
    print(f"Components: {len(board.GetFootprints())}")
    print()
    print("Open in KiCad PCB Editor, then: File -> Import Netlist -> geodude-carrier.net")

if __name__ == "__main__":
    main()
