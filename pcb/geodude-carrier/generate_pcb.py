#!/usr/bin/env python3
"""Generate KiCad PCB for GEO-DUDe Carrier Board (placement only, no routing).

Run with KiCad's Python:
/Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/Current/bin/python3 generate_pcb.py
"""

import pcbnew
import os

BOARD_W = 160
BOARD_H = 150

def mm(val):
    return pcbnew.FromMM(val)

def add_net(board, name, nets):
    ni = pcbnew.NETINFO_ITEM(board, name)
    board.Add(ni)
    nets[name] = ni

def place_fp(board, lib, fp_name, ref, value, x, y, angle=0):
    fp = pcbnew.FootprintLoad(lib, fp_name)
    if fp is None:
        print(f"WARNING: {fp_name} not found")
        return None
    fp.SetReference(ref)
    fp.SetValue(value)
    fp.SetPosition(pcbnew.VECTOR2I(mm(x), mm(y)))
    if angle:
        fp.SetOrientationDegrees(angle)
    board.Add(fp)
    return fp

def set_pad(fp, pad_num, net_info):
    for pad in fp.Pads():
        if pad.GetNumber() == str(pad_num):
            pad.SetNet(net_info)
            return

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

    # Libraries
    fp = "/Applications/KiCad/KiCad.app/Contents/SharedSupport/footprints"
    TB = os.path.join(fp, "TerminalBlock.pretty")
    CONN = os.path.join(fp, "Connector_PinHeader_2.54mm.pretty")
    SOCK = os.path.join(fp, "Connector_PinSocket_2.54mm.pretty")
    FUSE = os.path.join(fp, "Fuse.pretty")

    TB2 = "TerminalBlock_MaiXu_MX126-5.0-02P_1x02_P5.00mm"
    TB4 = "TerminalBlock_MaiXu_MX126-5.0-04P_1x04_P5.00mm"
    FUSE_FP = "Fuse_Littelfuse_395Series"
    H2 = "PinHeader_1x02_P2.54mm_Vertical"
    H3 = "PinHeader_1x03_P2.54mm_Vertical"
    S19 = "PinSocket_1x19_P2.54mm_Vertical"

    # ==============================================================
    # NETS
    # ==============================================================
    nets = {}
    for name in ["GND", "+12V", "+7V4", "+5V_SERVO", "+5V_LOGIC", "+3V3", "SDA", "SCL"]:
        add_net(board, name, nets)
    for i in range(16):
        add_net(board, f"PWM_CH{i}", nets)
    for i in range(10):
        add_net(board, f"SV{i+1}_PWR", nets)

    # ==============================================================
    # TOP: Power input terminals
    # ==============================================================
    sp = 12  # terminal spacing

    # Row 1: 4x 12V
    for i in range(4):
        f = place_fp(board, TB, TB2, f"J_12V_{i+1}", f"12V_{i+1}", 15 + i*sp, 12)
        if f:
            set_pad(f, 1, nets["+12V"])
            set_pad(f, 2, nets["GND"])

    # Row 2: 2x GND, 7V4, 5V servo
    for i, (ref, val, net) in enumerate([
        ("J_GND_1", "GND", "GND"), ("J_GND_2", "GND", "GND"),
        ("J_7V4", "7V4", "+7V4"), ("J_5VS", "5V_S", "+5V_SERVO"),
    ]):
        f = place_fp(board, TB, TB2, ref, val, 15 + i*sp, 24)
        if f:
            set_pad(f, 1, nets[net])
            set_pad(f, 2, nets["GND"])

    # Row 3: 5V logic, 3.3V
    for i, (ref, val, net) in enumerate([
        ("J_5VL", "5V_L", "+5V_LOGIC"), ("J_3V3", "3V3", "+3V3"),
    ]):
        f = place_fp(board, TB, TB2, ref, val, 15 + i*sp, 36)
        if f:
            set_pad(f, 1, nets[net])
            set_pad(f, 2, nets["GND"])

    # ==============================================================
    # MIDDLE: Fuses (two columns, arm1 left, arm2 right)
    # ==============================================================
    f1x, f2x = 35, 95
    fy, fsp = 55, 15

    for ref, val, rail, pwr, fx, row in [
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
    ]:
        f = place_fp(board, FUSE, FUSE_FP, ref, val, fx, fy + row*fsp)
        if f:
            set_pad(f, 1, nets[rail])
            set_pad(f, 2, nets[pwr])

    # ==============================================================
    # RIGHT EDGE: PCA9685 socket (1x19 female header)
    # ==============================================================
    # Pin mapping: 1-4=Ch0-3, 5=NC, 6-9=Ch4-7, 10=NC, 11-14=Ch8-11, 15=NC, 16-19=Ch12-15
    pca_pin_to_ch = {
        1: 0, 2: 1, 3: 2, 4: 3,
        6: 4, 7: 5, 8: 6, 9: 7,
        11: 8, 12: 9, 13: 10, 14: 11,
        16: 12, 17: 13, 18: 14, 19: 15,
    }

    f = place_fp(board, SOCK, S19, "J_PCA", "PCA9685", BOARD_W - 8, 50, 0)
    if f:
        for pin, ch in pca_pin_to_ch.items():
            set_pad(f, pin, nets[f"PWM_CH{ch}"])
        # Pins 5, 10, 15 = NC (no net assigned)

    # ==============================================================
    # BOTTOM: Servo headers (3-pin: signal, power, GND)
    # ==============================================================
    # Arm 1 row
    for i, (ref, val, sig, pwr) in enumerate([
        ("SV1", "A1_Base", "PWM_CH0", "SV1_PWR"),
        ("SV2", "A1_Shldr", "PWM_CH1", "SV2_PWR"),
        ("SV3", "A1_Elbow", "PWM_CH2", "SV3_PWR"),
        ("SV4", "A1_WrRot", "PWM_CH3", "SV4_PWR"),
        ("SV5", "A1_WrPan", "PWM_CH4", "SV5_PWR"),
    ]):
        f = place_fp(board, CONN, H3, ref, val, 12 + i*14, 130)
        if f:
            set_pad(f, 1, nets[sig])
            set_pad(f, 2, nets[pwr])
            set_pad(f, 3, nets["GND"])

    # Arm 2 row
    for i, (ref, val, sig, pwr) in enumerate([
        ("SV6", "A2_Base", "PWM_CH5", "SV6_PWR"),
        ("SV7", "A2_Shldr", "PWM_CH6", "SV7_PWR"),
        ("SV8", "A2_Elbow", "PWM_CH7", "SV8_PWR"),
        ("SV9", "A2_WrRot", "PWM_CH8", "SV9_PWR"),
        ("SV10", "A2_WrPan", "PWM_CH9", "SV10_PWR"),
    ]):
        f = place_fp(board, CONN, H3, ref, val, 90 + i*14, 130)
        if f:
            set_pad(f, 1, nets[sig])
            set_pad(f, 2, nets[pwr])
            set_pad(f, 3, nets["GND"])

    # ESC (2-pin: PWM + GND)
    f = place_fp(board, CONN, H2, "J_ESC", "ESC", 12, 142)
    if f:
        set_pad(f, 1, nets["PWM_CH11"])
        set_pad(f, 2, nets["GND"])

    # Fan (3-pin: PWM + 12V + GND)
    f = place_fp(board, CONN, H3, "J_FAN", "Fan", 26, 142)
    if f:
        set_pad(f, 1, nets["PWM_CH12"])
        set_pad(f, 2, nets["+12V"])
        set_pad(f, 3, nets["GND"])

    # ==============================================================
    # BOTTOM EDGE: I2C breakout terminals
    # ==============================================================
    for i, (ref, val) in enumerate([
        ("J_I2C1", "IMU"), ("J_I2C2", "Encoder"),
        ("J_I2C3", "Spare1"), ("J_I2C4", "Spare2"),
    ]):
        f = place_fp(board, TB, TB4, ref, val, 50 + i*28, 145)
        if f:
            set_pad(f, 1, nets["SDA"])
            set_pad(f, 2, nets["SCL"])
            set_pad(f, 3, nets["+3V3"])
            set_pad(f, 4, nets["GND"])

    # ==============================================================
    # SAVE
    # ==============================================================
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "geodude-carrier.kicad_pcb")
    board.Save(out)
    print(f"PCB saved: {out}")
    print(f"Board: {BOARD_W}x{BOARD_H}mm, {len(board.GetFootprints())} components, {board.GetNetCount()} nets")
    print("Unrouted — adjust placement in KiCad, then run route_pcb.py")

if __name__ == "__main__":
    main()
