#!/usr/bin/env python3
"""Generate KiCad PCB for GEO-DUDe Carrier Board.

Run with KiCad's Python:
/Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/Current/bin/python3 generate_pcb.py

Reads the netlist and creates a PCB with components placed in a logical layout.
"""

import pcbnew
import os

# Board dimensions (mm)
BOARD_W = 120
BOARD_H = 100

# Helper: mm to KiCad internal units (nanometers)
def mm(val):
    return pcbnew.FromMM(val)

def place_footprint(board, lib, fp_name, ref, value, x, y, angle=0):
    """Load a footprint and place it on the board."""
    fp = pcbnew.FootprintLoad(lib, fp_name)
    if fp is None:
        print(f"WARNING: Could not load footprint {lib}/{fp_name}")
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

    # Set board outline
    outline = pcbnew.PCB_SHAPE(board)
    outline.SetShape(pcbnew.SHAPE_T_RECT)
    outline.SetStart(pcbnew.VECTOR2I(mm(0), mm(0)))
    outline.SetEnd(pcbnew.VECTOR2I(mm(BOARD_W), mm(BOARD_H)))
    outline.SetLayer(pcbnew.Edge_Cuts)
    outline.SetWidth(mm(0.1))
    board.Add(outline)

    # Footprint library paths
    fp_lib = "/Applications/KiCad/KiCad.app/Contents/SharedSupport/footprints"
    tb_lib = os.path.join(fp_lib, "TerminalBlock.pretty")
    conn_lib = os.path.join(fp_lib, "Connector_PinHeader_2.54mm.pretty")
    fuse_lib = os.path.join(fp_lib, "Fuse.pretty")

    # Check which terminal block footprints exist
    tb_2pin = "TerminalBlock_MaiXu_MX126-5.0-02P_1x02_P5.00mm"
    tb_4pin = "TerminalBlock_MaiXu_MX126-5.0-04P_1x04_P5.00mm"

    # --- Power input terminals (left edge) ---
    power_inputs = [
        ("J_12V", "12V_Input", 10, 15),
        ("J_7V4", "7V4_Input", 10, 30),
        ("J_5VS", "5V_Servo", 10, 45),
        ("J_5VL", "5V_Logic", 10, 60),
        ("J_3V3", "3V3_Input", 10, 75),
    ]
    for ref, val, x, y in power_inputs:
        place_footprint(board, tb_lib, tb_2pin, ref, val, x, y)

    # --- Fuse holders (center-left, two columns for arm 1 and arm 2) ---
    fuse_fp = "Fuseholder_Clip-5x20mm_Keystone_3517_Inline_P23.11x6.76mm_D1.70mm_Horizontal"  # Common 5x20mm PCB fuse holder
    fuse_data = [
        # Arm 1 (left column)
        ("F1", "8A", 35, 12),
        ("F2", "8A", 35, 24),
        ("F3", "5A", 35, 36),
        ("F4", "3A", 35, 48),
        ("F5", "3A", 35, 60),
        # Arm 2 (right column)
        ("F6", "8A", 55, 12),
        ("F7", "8A", 55, 24),
        ("F8", "5A", 55, 36),
        ("F9", "3A", 55, 48),
        ("F10", "3A", 55, 60),
    ]
    for ref, val, x, y in fuse_data:
        place_footprint(board, fuse_lib, fuse_fp, ref, val, x, y)

    # --- Servo output headers (right side, 3-pin male) ---
    servo_fp = "PinHeader_1x03_P2.54mm_Vertical"
    servo_data = [
        # Arm 1
        ("SV1", "Arm1_Base", 80, 10),
        ("SV2", "Arm1_Shoulder", 80, 20),
        ("SV3", "Arm1_Elbow", 80, 30),
        ("SV4", "Arm1_WristRot", 80, 40),
        ("SV5", "Arm1_WristPan", 80, 50),
        # Arm 2
        ("SV6", "Arm2_Base", 95, 10),
        ("SV7", "Arm2_Shoulder", 95, 20),
        ("SV8", "Arm2_Elbow", 95, 30),
        ("SV9", "Arm2_WristRot", 95, 40),
        ("SV10", "Arm2_WristPan", 95, 50),
        # ESC and Fan
        ("J_ESC", "MACE_ESC", 80, 65),
        ("J_FAN", "Fan", 95, 65),
    ]
    for ref, val, x, y in servo_data:
        place_footprint(board, conn_lib, servo_fp, ref, val, x, y)

    # --- PCA9685 socket (center, 6-pin control + 2x 8-pin PWM) ---
    place_footprint(board, conn_lib, "PinHeader_1x06_P2.54mm_Vertical",
                    "J_PCA_CTRL", "PCA9685_Ctrl", 45, 80)
    place_footprint(board, conn_lib, "PinHeader_1x08_P2.54mm_Vertical",
                    "J_PCA_A", "PCA_Ch0-7", 55, 80)
    place_footprint(board, conn_lib, "PinHeader_1x08_P2.54mm_Vertical",
                    "J_PCA_B", "PCA_Ch8-15", 65, 80)

    # --- I2C breakout terminals (bottom edge) ---
    i2c_data = [
        ("J_I2C1", "I2C_IMU", 30, 90),
        ("J_I2C2", "I2C_Encoder", 50, 90),
        ("J_I2C3", "I2C_Spare1", 70, 90),
        ("J_I2C4", "I2C_Spare2", 90, 90),
    ]
    for ref, val, x, y in i2c_data:
        place_footprint(board, tb_lib, tb_4pin, ref, val, x, y)

    # Ground plane zone will be added manually after netlist import
    # (needs GND net assigned which doesn't exist until netlist is loaded)

    # Save
    output = os.path.join(os.path.dirname(__file__), "geodude-carrier.kicad_pcb")
    board.Save(output)
    print(f"PCB saved to: {output}")
    print(f"Board size: {BOARD_W}mm x {BOARD_H}mm")
    print(f"Components placed: {len(board.GetFootprints())}")
    print()
    print("Next: Open in KiCad PCB Editor, then File -> Import Netlist")
    print("to connect all the nets to the placed footprints.")

if __name__ == "__main__":
    main()
