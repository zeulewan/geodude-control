#!/usr/bin/env python3
"""Generate KiCad PCB for GEO-DUDe Carrier Board (placement only, no routing).

Run with KiCad's Python:
/Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/Current/bin/python3 generate_pcb.py
"""

import pcbnew
import os

BOARD_W = 190
BOARD_H = 160

def mm(val):
    return pcbnew.FromMM(val)

def add_net(board, name, nets):
    ni = pcbnew.NETINFO_ITEM(board, name)
    board.Add(ni)
    nets[name] = ni

def place_fp(board, lib, fp_name, ref, value, x, y, angle=0):
    fp = pcbnew.FootprintLoad(lib, fp_name)
    if fp is None:
        print(f"WARNING: {fp_name} not found in {lib}")
        return None
    fp.SetReference(ref)
    fp.SetValue(value)
    fp.SetPosition(pcbnew.VECTOR2I(mm(x), mm(y)))
    if angle:
        fp.SetOrientationDegrees(angle)
    # Show value on silkscreen, hide reference
    ref_field = fp.Reference()
    ref_field.SetVisible(False)
    val_field = fp.Value()
    val_field.SetLayer(pcbnew.F_SilkS)
    val_field.SetVisible(True)
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
    FP = "/Applications/KiCad/KiCad.app/Contents/SharedSupport/footprints"
    TB = os.path.join(FP, "TerminalBlock.pretty")
    CONN = os.path.join(FP, "Connector_PinHeader_2.54mm.pretty")
    SOCK = os.path.join(FP, "Connector_PinSocket_2.54mm.pretty")
    LOCAL = os.path.dirname(os.path.abspath(__file__))

    TB2 = "TerminalBlock_MaiXu_MX126-5.0-02P_1x02_P5.00mm"
    H1 = "PinHeader_1x01_P2.54mm_Vertical"
    H3 = "PinHeader_1x03_P2.54mm_Vertical"
    S19 = "PinSocket_1x19_P2.54mm_Vertical"
    FUSE_FP = "BLX-A_5x20mm"

    # ==============================================================
    # NETS
    # ==============================================================
    nets = {}
    for name in ["GND", "GND_LOGIC", "+12V", "+7V4", "+5V_SERVO",
                  "+5V_LOGIC", "+3V3", "SDA", "SCL"]:
        add_net(board, name, nets)
    for i in range(16):
        add_net(board, f"PWM_CH{i}", nets)
    for i in range(10):
        add_net(board, f"SV{i+1}_PWR", nets)

    # ==============================================================
    # RIGHT EDGE: All power screw terminals in a vertical column
    # ==============================================================
    sp = 12
    px = BOARD_W - 10

    all_power = [
        ("J1", "12V", "+12V", "GND"),
        ("J2", "12V", "+12V", "GND"),
        ("J3", "12V", "+12V", "GND"),
        ("J4", "12V", "+12V", "GND"),
        ("J5", "7.4V", "+7V4", "GND"),
        ("J6", "5V Servo", "+5V_SERVO", "GND"),
        ("J7", "GND", "GND", "GND"),
        ("J8", "GND", "GND", "GND"),
        ("J9", "GND", "GND", "GND"),
        ("J10", "GND", "GND", "GND"),
        ("J11", "5V Logic", "+5V_LOGIC", "GND_LOGIC"),
        ("J12", "3.3V", "+3V3", "GND_LOGIC"),
    ]
    pwr_total = len(all_power) * sp
    py = (BOARD_H - pwr_total) / 2 + sp / 2
    for i, (ref, val, net1, net2) in enumerate(all_power):
        f = place_fp(board, TB, TB2, ref, val, px, py + i*sp, 90)
        if f:
            set_pad(f, 1, nets[net1])
            set_pad(f, 2, nets[net2])

    # ==============================================================
    # MIDDLE: Fuses (two columns)
    # ==============================================================
    f1x, f2x = 63, 135
    fy, fsp = 48, 16

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
        f = place_fp(board, LOCAL, FUSE_FP, ref, val, fx, fy + row*fsp)
        if f:
            set_pad(f, 1, nets[rail])
            set_pad(f, 2, nets[pwr])

    # ==============================================================
    # RIGHT EDGE: PCA9685 socket (1x19 female header)
    # ==============================================================
    pca_pin_to_ch = {
        1: 0, 2: 1, 3: 2, 4: 3,
        6: 4, 7: 5, 8: 6, 9: 7,
        11: 8, 12: 9, 13: 10, 14: 11,
        16: 12, 17: 13, 18: 14, 19: 15,
    }
    # PCA on top edge, horizontal (pins go left-right), centered
    # 1x19 at 2.54mm pitch = 45.72mm long. Pin 1 is origin, centre offset = 9*2.54 = 22.86mm
    # Rotated 270°: pin 1 right, pin 19 left. Origin at pin 1.
    # To centre: place origin at BOARD_W/2 + 22.86mm (so pin 10 lands at centre)
    pca_centre_offset = 9 * 2.54  # 22.86mm
    f = place_fp(board, SOCK, S19, "J_PCA", "PCA9685", BOARD_W / 2 + pca_centre_offset, 10, 270)
    if f:
        for pin, ch in pca_pin_to_ch.items():
            set_pad(f, pin, nets[f"PWM_CH{ch}"])

    # ==============================================================
    # BOTTOM: ESC + Fan row, then Servo headers row below
    # ==============================================================
    sv_sp = 12
    esc_y = BOARD_H - 22   # ESC/Fan row (above servos)
    sv_y = BOARD_H - 8     # Servo row (bottom edge)

    # ESC + Fan row (centred)
    f = place_fp(board, CONN, H3, "J_ESC", "ESC", 80, esc_y, 90)
    if f:
        set_pad(f, 1, nets["PWM_CH11"])
        # pin 2 NC
        set_pad(f, 3, nets["GND"])

    f = place_fp(board, CONN, H3, "J_FAN", "Fan", 92, esc_y, 90)
    if f:
        set_pad(f, 1, nets["PWM_CH12"])
        set_pad(f, 2, nets["+12V"])
        set_pad(f, 3, nets["GND"])

    # Arm 1 (left)
    for i, (ref, val, sig, pwr) in enumerate([
        ("SV1", "B1", "PWM_CH0", "SV1_PWR"),
        ("SV2", "S1", "PWM_CH1", "SV2_PWR"),
        ("SV3", "E1", "PWM_CH2", "SV3_PWR"),
        ("SV4", "W1A", "PWM_CH3", "SV4_PWR"),
        ("SV5", "W1B", "PWM_CH4", "SV5_PWR"),
    ]):
        f = place_fp(board, CONN, H3, ref, val, 20 + i*sv_sp, sv_y, 90)
        if f:
            set_pad(f, 1, nets[sig])
            set_pad(f, 2, nets[pwr])
            set_pad(f, 3, nets["GND"])
            # Move silkscreen value below pins, horizontal
            val_field = f.Value()
            val_field.SetPosition(pcbnew.VECTOR2I(mm(20 + i*sv_sp), mm(sv_y + 6)))
            val_field.SetTextAngle(pcbnew.EDA_ANGLE(0, pcbnew.DEGREES_T))

    # Arm 2 (right)
    for i, (ref, val, sig, pwr) in enumerate([
        ("SV6", "B2", "PWM_CH5", "SV6_PWR"),
        ("SV7", "S2", "PWM_CH6", "SV7_PWR"),
        ("SV8", "E2", "PWM_CH7", "SV8_PWR"),
        ("SV9", "W2A", "PWM_CH8", "SV9_PWR"),
        ("SV10", "W2B", "PWM_CH9", "SV10_PWR"),
    ]):
        f = place_fp(board, CONN, H3, ref, val, 120 + i*sv_sp, sv_y, 90)
        if f:
            set_pad(f, 1, nets[sig])
            set_pad(f, 2, nets[pwr])
            set_pad(f, 3, nets["GND"])
            val_field = f.Value()
            val_field.SetPosition(pcbnew.VECTOR2I(mm(120 + i*sv_sp), mm(sv_y + 6)))
            val_field.SetTextAngle(pcbnew.EDA_ANGLE(0, pcbnew.DEGREES_T))

    # ==============================================================
    # LEFT EDGE: Logic bus section
    # Each bus: 4x single pin headers + 2x screw terminals
    # ==============================================================
    H4 = "PinHeader_1x04_P2.54mm_Vertical"
    bus_sp = 14
    lx = 10  # left edge x

    buses = [
        ("SCL", "SCL"),
        ("SDA", "SDA"),
        ("3V3", "+3V3"),
        ("5V", "+5V_LOGIC"),
        ("GND_L", "GND_LOGIC"),
    ]

    # Screw terminals: single column, 2 per bus, centred vertically
    scr_sp = 12
    scr_total = 10 * scr_sp  # 10 terminals
    scr_y_start = (BOARD_H - scr_total) / 2 + scr_sp / 2
    jnum = 30
    scr_y = scr_y_start
    for row, (label, net_name) in enumerate(buses):
        for j in range(2):
            f = place_fp(board, TB, TB2, f"J{jnum}", label, lx, scr_y, 90)
            scr_y += scr_sp
            jnum += 1
            if f:
                set_pad(f, 1, nets[net_name])
                set_pad(f, 2, nets[net_name])

    # Pin headers: single column, centred vertically
    hdr_total = len(buses) * bus_sp
    hdr_y_start = (BOARD_H - hdr_total) / 2 + bus_sp / 2
    for row, (label, net_name) in enumerate(buses):
        y = hdr_y_start + row * bus_sp
        f = place_fp(board, CONN, H4, f"J{jnum}", label, lx + 18, y)
        jnum += 1
        if f:
            for p in range(1, 5):
                set_pad(f, p, nets[net_name])

    # ==============================================================
    # SAVE
    # ==============================================================
    out = os.path.join(LOCAL, "geodude-carrier.kicad_pcb")
    board.Save(out)
    print(f"PCB saved: {out}")
    print(f"Board: {BOARD_W}x{BOARD_H}mm, {len(board.GetFootprints())} components, {board.GetNetCount()} nets")
    print("Unrouted — adjust placement in KiCad, then run route_pcb.py")

if __name__ == "__main__":
    main()
