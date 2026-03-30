#!/usr/bin/env python3
"""Generate complete KiCad PCB for GEO-DUDe Carrier Board.

Creates footprints, nets, assigns nets to pads. Then export DSN → Freerouting → import SES.

Run with KiCad's Python:
/Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/Current/bin/python3 generate_pcb.py
"""

import pcbnew
import os

BOARD_W = 160
BOARD_H = 160

def mm(val):
    return pcbnew.FromMM(val)

def add_net(board, name, nets_dict):
    ni = pcbnew.NETINFO_ITEM(board, name)
    board.Add(ni)
    nets_dict[name] = ni
    return ni

def place_fp(board, lib, fp_name, ref, value, x, y, angle=0):
    fp = pcbnew.FootprintLoad(lib, fp_name)
    if fp is None:
        print(f"WARNING: Could not load {fp_name}")
        return None
    fp.SetReference(ref)
    fp.SetValue(value)
    fp.SetPosition(pcbnew.VECTOR2I(mm(x), mm(y)))
    if angle:
        fp.SetOrientationDegrees(angle)
    board.Add(fp)
    return fp

def set_pad_net(fp, pad_num, net_info):
    for pad in fp.Pads():
        if pad.GetNumber() == str(pad_num):
            pad.SetNet(net_info)
            return
    print(f"WARNING: Pad {pad_num} not found on {fp.GetReference()}")

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

    TB_2 = "TerminalBlock_MaiXu_MX126-5.0-02P_1x02_P5.00mm"
    TB_4 = "TerminalBlock_MaiXu_MX126-5.0-04P_1x04_P5.00mm"
    FUSE = "Fuse_Littelfuse_395Series"
    H3 = "PinHeader_1x03_P2.54mm_Vertical"
    H6 = "PinHeader_1x06_P2.54mm_Vertical"
    H8 = "PinHeader_1x08_P2.54mm_Vertical"

    # ==============================================================
    # CREATE NETS
    # ==============================================================
    nets = {}
    add_net(board, "GND", nets)
    add_net(board, "+12V", nets)
    add_net(board, "+7V4", nets)
    add_net(board, "+5V_SERVO", nets)
    add_net(board, "+5V_LOGIC", nets)
    add_net(board, "+3V3", nets)
    add_net(board, "SDA", nets)
    add_net(board, "SCL", nets)
    for i in range(16):
        add_net(board, f"PWM_CH{i}", nets)
    for i in range(10):
        add_net(board, f"SV{i+1}_PWR", nets)

    # Trace widths handled by DSN patching in route_pcb.py

    # ==============================================================
    # TOP SECTION: Power input terminals (rows 1-3)
    # ==============================================================
    # Layout: top of board, horizontal rows of snapped-together terminals
    # 12mm spacing between 2-pin blocks (10mm wide + 2mm gap)

    # Row 1 (y=12): 4x 12V
    for i in range(4):
        fp = place_fp(board, tb_lib, TB_2, f"J_12V_{i+1}", f"12V_{i+1}",
                       15 + i * 12, 12)
        if fp:
            set_pad_net(fp, 1, nets["+12V"])
            set_pad_net(fp, 2, nets["GND"])

    # Row 2 (y=24): 2x GND, 7V4, 5V servo
    for i, (ref, val, net1) in enumerate([
        ("J_GND_1", "GND_1", "GND"), ("J_GND_2", "GND_2", "GND"),
        ("J_7V4", "7V4", "+7V4"), ("J_5VS", "5V_Servo", "+5V_SERVO"),
    ]):
        fp = place_fp(board, tb_lib, TB_2, ref, val, 15 + i * 12, 24)
        if fp:
            set_pad_net(fp, 1, nets[net1])
            set_pad_net(fp, 2, nets["GND"])

    # Row 3 (y=36): 5V logic, 3.3V
    for i, (ref, val, net1) in enumerate([
        ("J_5VL", "5V_Logic", "+5V_LOGIC"), ("J_3V3", "3V3", "+3V3"),
    ]):
        fp = place_fp(board, tb_lib, TB_2, ref, val, 15 + i * 12, 36)
        if fp:
            set_pad_net(fp, 1, nets[net1])
            set_pad_net(fp, 2, nets["GND"])

    # ==============================================================
    # MIDDLE SECTION: Fuse holders (y=55-125, two columns)
    # ==============================================================
    f1x, f2x = 40, 100  # wider spacing between arm columns
    fy, fsp = 55, 15

    fuse_config = [
        ("F1", "8A", "+12V", "SV1_PWR", f1x, 0),
        ("F2", "8A", "+12V", "SV2_PWR", f1x, 1),
        ("F3", "5A", "+7V4", "SV3_PWR", f1x, 2),
        ("F4", "3A", "+5V_SERVO", "SV4_PWR", f1x, 3),
        ("F5", "3A", "+5V_SERVO", "SV5_PWR", f1x, 4),
        ("F6", "8A", "+12V", "SV6_PWR", f2x, 0),
        ("F7", "8A", "+12V", "SV7_PWR", f2x, 1),
        ("F8", "5A", "+7V4", "SV8_PWR", f2x, 2),
        ("F9", "3A", "+5V_SERVO", "SV9_PWR", f2x, 3),
        ("F10", "3A", "+5V_SERVO", "SV10_PWR", f2x, 4),
    ]
    for ref, val, rail_net, pwr_net, fx, row in fuse_config:
        fp = place_fp(board, fuse_lib, FUSE, ref, val, fx, fy + row * fsp)
        if fp:
            set_pad_net(fp, 1, nets[rail_net])
            set_pad_net(fp, 2, nets[pwr_net])

    # PCA9685 socket between fuse columns
    fp = place_fp(board, conn_lib, H6, "J_PCA_CTRL", "PCA_Ctrl", 65, 55)
    if fp:
        set_pad_net(fp, 1, nets["GND"])
        set_pad_net(fp, 2, nets["GND"])   # OE -> GND
        set_pad_net(fp, 3, nets["SCL"])
        set_pad_net(fp, 4, nets["SDA"])
        set_pad_net(fp, 5, nets["+3V3"])

    fp = place_fp(board, conn_lib, H8, "J_PCA_A", "PCA_Ch0-7", 75, 55)
    if fp:
        for i in range(8):
            set_pad_net(fp, i + 1, nets[f"PWM_CH{i}"])

    fp = place_fp(board, conn_lib, H8, "J_PCA_B", "PCA_Ch8-15", 85, 55)
    if fp:
        for i in range(8):
            set_pad_net(fp, i + 1, nets[f"PWM_CH{8 + i}"])

    # ==============================================================
    # BOTTOM SECTION: Servo/ESC/Fan headers + I2C breakout
    # ==============================================================
    # Servo headers in two rows (arm1 / arm2), 10mm spacing
    s1x, s2x = 15, 90  # arm1 left, arm2 right
    sy = 140
    ssp = 8  # tight horizontal spacing for 3-pin headers

    # Arm 1 servos (horizontal row)
    for i, (ref, val, sig, pwr) in enumerate([
        ("SV1", "Base", "PWM_CH0", "SV1_PWR"),
        ("SV2", "Shldr", "PWM_CH1", "SV2_PWR"),
        ("SV3", "Elbow", "PWM_CH2", "SV3_PWR"),
        ("SV4", "WrRot", "PWM_CH3", "SV4_PWR"),
        ("SV5", "WrPan", "PWM_CH4", "SV5_PWR"),
    ]):
        fp = place_fp(board, conn_lib, H3, ref, f"A1_{val}", s1x + i * 14, sy)
        if fp:
            set_pad_net(fp, 1, nets[sig])
            set_pad_net(fp, 2, nets[pwr])
            set_pad_net(fp, 3, nets["GND"])

    # Arm 2 servos (horizontal row)
    for i, (ref, val, sig, pwr) in enumerate([
        ("SV6", "Base", "PWM_CH5", "SV6_PWR"),
        ("SV7", "Shldr", "PWM_CH6", "SV7_PWR"),
        ("SV8", "Elbow", "PWM_CH7", "SV8_PWR"),
        ("SV9", "WrRot", "PWM_CH8", "SV9_PWR"),
        ("SV10", "WrPan", "PWM_CH9", "SV10_PWR"),
    ]):
        fp = place_fp(board, conn_lib, H3, ref, f"A2_{val}", s2x + i * 14, sy)
        if fp:
            set_pad_net(fp, 1, nets[sig])
            set_pad_net(fp, 2, nets[pwr])
            set_pad_net(fp, 3, nets["GND"])

    # ESC (PWM + GND only, ESC gets its own power from bus)
    H2 = "PinHeader_1x02_P2.54mm_Vertical"
    fp = place_fp(board, conn_lib, H2, "J_ESC", "MACE_ESC", 15, 152)
    if fp:
        set_pad_net(fp, 1, nets["PWM_CH11"])
        set_pad_net(fp, 2, nets["GND"])

    fp = place_fp(board, conn_lib, H3, "J_FAN", "Fan", 30, 152)
    if fp:
        set_pad_net(fp, 1, nets["PWM_CH12"])
        set_pad_net(fp, 2, nets["+12V"])
        set_pad_net(fp, 3, nets["GND"])

    # I2C breakout terminals (bottom right)
    for i, (ref, val) in enumerate([
        ("J_I2C1", "IMU"), ("J_I2C2", "Encoder"),
        ("J_I2C3", "Spare1"), ("J_I2C4", "Spare2"),
    ]):
        fp = place_fp(board, tb_lib, TB_4, ref, val, 60 + i * 25, 152)
        if fp:
            set_pad_net(fp, 1, nets["SDA"])
            set_pad_net(fp, 2, nets["SCL"])
            set_pad_net(fp, 3, nets["+3V3"])
            set_pad_net(fp, 4, nets["GND"])

    # ==============================================================
    # SAVE
    # ==============================================================
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "geodude-carrier.kicad_pcb")
    board.Save(out)

    print(f"PCB saved: {out}")
    print(f"Board: {BOARD_W}x{BOARD_H}mm")
    print(f"Components: {len(board.GetFootprints())}, Nets: {board.GetNetCount()}")

if __name__ == "__main__":
    main()
