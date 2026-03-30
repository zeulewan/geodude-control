#!/usr/bin/env python3
"""Generate KiCad PCB for GEO-DUDe Carrier Board.

Run with KiCad's Python:
/Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/Current/bin/python3 generate_pcb.py
"""

import pcbnew
import os

BOARD_W = 160
BOARD_H = 150

def mm(val):
    return pcbnew.FromMM(val)

def place_fp(board, lib, fp_name, ref, value, x, y, angle=0):
    fp = pcbnew.FootprintLoad(lib, fp_name)
    if fp is None:
        print(f"WARNING: Could not load {fp_name} from {lib}")
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
    local_lib = os.path.dirname(os.path.abspath(__file__))  # custom footprints

    TB_2 = "TerminalBlock_MaiXu_MX126-5.0-02P_1x02_P5.00mm"
    TB_4 = "TerminalBlock_MaiXu_MX126-5.0-04P_1x04_P5.00mm"
    FUSE = "BLX-A_5x20mm"  # custom, in local dir
    H3 = "PinHeader_1x03_P2.54mm_Vertical"
    H6 = "PinHeader_1x06_P2.54mm_Vertical"
    H8 = "PinHeader_1x08_P2.54mm_Vertical"

    # ============================================================
    # LEFT EDGE: Power input terminals
    # ============================================================
    px = 12
    py = 10
    sp = 14

    # 4x 12V (paralleled, ~9A each)
    for i in range(4):
        place_fp(board, tb_lib, TB_2, f"J_12V_{i+1}", f"12V_{i+1}", px, py + i * sp)

    # 7.4V, 5V servo, 5V logic, 3.3V
    place_fp(board, tb_lib, TB_2, "J_7V4", "7V4", px, py + 4 * sp)
    place_fp(board, tb_lib, TB_2, "J_5VS", "5V_Servo", px, py + 5 * sp)
    place_fp(board, tb_lib, TB_2, "J_5VL", "5V_Logic", px, py + 6 * sp)
    place_fp(board, tb_lib, TB_2, "J_3V3", "3V3", px, py + 7 * sp)

    # 2x GND bus (paralleled)
    place_fp(board, tb_lib, TB_2, "J_GND_1", "GND_1", px, py + 8 * sp)
    place_fp(board, tb_lib, TB_2, "J_GND_2", "GND_2", px, py + 9 * sp)

    # ============================================================
    # CENTER: Fuse holders (two columns, 15mm vertical spacing)
    # ============================================================
    # BLX-A is ~28x10mm, 22mm pin spacing
    f1x = 50   # Arm 1 column
    f2x = 85   # Arm 2 column
    fy = 15
    fsp = 16   # vertical spacing (fuse is ~10mm tall + clearance)

    fuses = [
        ("F1", "8A", f1x, 0), ("F2", "8A", f1x, 1), ("F3", "5A", f1x, 2),
        ("F4", "3A", f1x, 3), ("F5", "3A", f1x, 4),
        ("F6", "8A", f2x, 0), ("F7", "8A", f2x, 1), ("F8", "5A", f2x, 2),
        ("F9", "3A", f2x, 3), ("F10", "3A", f2x, 4),
    ]
    for ref, val, fx, row in fuses:
        place_fp(board, local_lib, FUSE, ref, val, fx, fy + row * fsp)

    # ============================================================
    # RIGHT SIDE: Servo/ESC/Fan 3-pin headers
    # ============================================================
    s1x = 120  # Arm 1 column
    s2x = 138  # Arm 2 column
    sy = 12
    ssp = 10

    servos = [
        ("SV1", "Arm1_Base", s1x), ("SV2", "Arm1_Shldr", s1x),
        ("SV3", "Arm1_Elbow", s1x), ("SV4", "Arm1_WrRot", s1x),
        ("SV5", "Arm1_WrPan", s1x),
        ("SV6", "Arm2_Base", s2x), ("SV7", "Arm2_Shldr", s2x),
        ("SV8", "Arm2_Elbow", s2x), ("SV9", "Arm2_WrRot", s2x),
        ("SV10", "Arm2_WrPan", s2x),
    ]
    for i, (ref, val, sx) in enumerate(servos):
        row = i % 5
        place_fp(board, conn_lib, H3, ref, val, sx, sy + row * ssp)

    # ESC and Fan
    place_fp(board, conn_lib, H3, "J_ESC", "MACE_ESC", s1x, sy + 5 * ssp + 8)
    place_fp(board, conn_lib, H3, "J_FAN", "Fan", s2x, sy + 5 * ssp + 8)

    # ============================================================
    # CENTER-BOTTOM: PCA9685 socket
    # ============================================================
    place_fp(board, conn_lib, H6, "J_PCA_CTRL", "PCA_Ctrl", 45, 110)
    place_fp(board, conn_lib, H8, "J_PCA_A", "PCA_Ch0-7", 60, 110)
    place_fp(board, conn_lib, H8, "J_PCA_B", "PCA_Ch8-15", 75, 110)

    # ============================================================
    # BOTTOM EDGE: I2C breakout terminals
    # ============================================================
    i2c_y = 138
    for i, (ref, val) in enumerate([
        ("J_I2C1", "IMU"), ("J_I2C2", "Encoder"),
        ("J_I2C3", "Spare1"), ("J_I2C4", "Spare2"),
    ]):
        place_fp(board, tb_lib, TB_4, ref, val, 25 + i * 32, i2c_y)

    # Save
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "geodude-carrier.kicad_pcb")
    board.Save(out)
    n = len(board.GetFootprints())
    print(f"PCB saved: {out}")
    print(f"Board: {BOARD_W}x{BOARD_H}mm, {n} components")

if __name__ == "__main__":
    main()
