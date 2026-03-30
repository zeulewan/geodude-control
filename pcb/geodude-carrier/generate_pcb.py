#!/usr/bin/env python3
"""Generate complete KiCad PCB for GEO-DUDe Carrier Board.

Creates footprints, nets, and assigns nets to pads — no GUI netlist import needed.

Run with KiCad's Python:
/Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/Current/bin/python3 generate_pcb.py
"""

import pcbnew
import os

BOARD_W = 160
BOARD_H = 150

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
    """Assign a net to a pad by pad number (string)."""
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
    # CREATE ALL NETS
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

    # ==============================================================
    # POWER INPUT TERMINALS (top, horizontal rows)
    # ==============================================================
    row_y = 10
    row_sp = 12

    # 4x 12V paralleled
    for i in range(4):
        fp = place_fp(board, tb_lib, TB_2, f"J_12V_{i+1}", f"12V_{i+1}",
                       10 + i * 10, row_y)
        if fp:
            set_pad_net(fp, 1, nets["+12V"])
            set_pad_net(fp, 2, nets["GND"])

    # GND bus x2, 7V4, 5V servo
    for i, (ref, val, net1) in enumerate([
        ("J_GND_1", "GND_1", "GND"), ("J_GND_2", "GND_2", "GND"),
        ("J_7V4", "7V4", "+7V4"), ("J_5VS", "5V_Servo", "+5V_SERVO"),
    ]):
        fp = place_fp(board, tb_lib, TB_2, ref, val, 10 + i * 10, row_y + row_sp)
        if fp:
            set_pad_net(fp, 1, nets[net1])
            set_pad_net(fp, 2, nets["GND"])

    # 5V logic, 3V3
    for i, (ref, val, net1) in enumerate([
        ("J_5VL", "5V_Logic", "+5V_LOGIC"), ("J_3V3", "3V3", "+3V3"),
    ]):
        fp = place_fp(board, tb_lib, TB_2, ref, val, 10 + i * 15, row_y + 2 * row_sp)
        if fp:
            set_pad_net(fp, 1, nets[net1])
            set_pad_net(fp, 2, nets["GND"])

    # ==============================================================
    # FUSE HOLDERS (two columns)
    # ==============================================================
    f1x, f2x = 50, 85
    fy, fsp = 50, 16

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

    # ==============================================================
    # SERVO HEADERS (3-pin: signal, power, GND)
    # ==============================================================
    s1x, s2x = 120, 140
    sy, ssp = 50, 10

    servo_config = [
        ("SV1", "Arm1_Base", 0, "PWM_CH0", "SV1_PWR", s1x),
        ("SV2", "Arm1_Shldr", 1, "PWM_CH1", "SV2_PWR", s1x),
        ("SV3", "Arm1_Elbow", 2, "PWM_CH2", "SV3_PWR", s1x),
        ("SV4", "Arm1_WrRot", 3, "PWM_CH3", "SV4_PWR", s1x),
        ("SV5", "Arm1_WrPan", 4, "PWM_CH4", "SV5_PWR", s1x),
        ("SV6", "Arm2_Base", 0, "PWM_CH5", "SV6_PWR", s2x),
        ("SV7", "Arm2_Shldr", 1, "PWM_CH6", "SV7_PWR", s2x),
        ("SV8", "Arm2_Elbow", 2, "PWM_CH7", "SV8_PWR", s2x),
        ("SV9", "Arm2_WrRot", 3, "PWM_CH8", "SV9_PWR", s2x),
        ("SV10", "Arm2_WrPan", 4, "PWM_CH9", "SV10_PWR", s2x),
    ]
    for ref, val, row, sig_net, pwr_net, sx in servo_config:
        fp = place_fp(board, conn_lib, H3, ref, val, sx, sy + row * ssp)
        if fp:
            set_pad_net(fp, 1, nets[sig_net])
            set_pad_net(fp, 2, nets[pwr_net])
            set_pad_net(fp, 3, nets["GND"])

    # ESC (12V direct, no fuse)
    fp = place_fp(board, conn_lib, H3, "J_ESC", "MACE_ESC", s1x, sy + 5 * ssp + 8)
    if fp:
        set_pad_net(fp, 1, nets["PWM_CH11"])
        set_pad_net(fp, 2, nets["+12V"])
        set_pad_net(fp, 3, nets["GND"])

    # Fan (12V direct, no fuse)
    fp = place_fp(board, conn_lib, H3, "J_FAN", "Fan", s2x, sy + 5 * ssp + 8)
    if fp:
        set_pad_net(fp, 1, nets["PWM_CH12"])
        set_pad_net(fp, 2, nets["+12V"])
        set_pad_net(fp, 3, nets["GND"])

    # ==============================================================
    # PCA9685 SOCKET (control + PWM headers)
    # ==============================================================
    # Control header: GND, OE(->GND), SCL, SDA, VCC(3.3V), V+(NC)
    fp = place_fp(board, conn_lib, H6, "J_PCA_CTRL", "PCA_Ctrl", 45, 130)
    if fp:
        set_pad_net(fp, 1, nets["GND"])       # GND
        set_pad_net(fp, 2, nets["GND"])       # OE -> GND
        set_pad_net(fp, 3, nets["SCL"])
        set_pad_net(fp, 4, nets["SDA"])
        set_pad_net(fp, 5, nets["+3V3"])      # VCC
        # Pin 6 = V+ (NC, no net)

    # PWM Ch0-7
    fp = place_fp(board, conn_lib, H8, "J_PCA_A", "PCA_Ch0-7", 60, 130)
    if fp:
        for i in range(8):
            set_pad_net(fp, i + 1, nets[f"PWM_CH{i}"])

    # PWM Ch8-15
    fp = place_fp(board, conn_lib, H8, "J_PCA_B", "PCA_Ch8-15", 75, 130)
    if fp:
        for i in range(8):
            set_pad_net(fp, i + 1, nets[f"PWM_CH{8 + i}"])

    # ==============================================================
    # I2C BREAKOUT (4x 4-pin: SDA, SCL, 3V3, GND)
    # ==============================================================
    i2c_labels = ["IMU", "Encoder", "Spare1", "Spare2"]
    for i, label in enumerate(i2c_labels):
        fp = place_fp(board, tb_lib, TB_4, f"J_I2C{i+1}", label,
                       25 + i * 32, 145)
        if fp:
            set_pad_net(fp, 1, nets["SDA"])
            set_pad_net(fp, 2, nets["SCL"])
            set_pad_net(fp, 3, nets["+3V3"])
            set_pad_net(fp, 4, nets["GND"])

    # ==============================================================
    # ROUTING
    # ==============================================================
    print("Routing traces...")

    def get_pad_pos(ref, pad_num):
        """Get pad position by component reference and pad number."""
        for fp in board.GetFootprints():
            if fp.GetReference() == ref:
                for pad in fp.Pads():
                    if pad.GetNumber() == str(pad_num):
                        return pad.GetPosition()
        print(f"WARNING: pad {ref}:{pad_num} not found")
        return None

    def get_pad_net_code(ref, pad_num):
        """Get net code of a pad."""
        for fp in board.GetFootprints():
            if fp.GetReference() == ref:
                for pad in fp.Pads():
                    if pad.GetNumber() == str(pad_num):
                        return pad.GetNetCode()
        return 0

    def add_track(p1, p2, width_mm, layer, net_code):
        """Add a copper trace between two points."""
        if p1 is None or p2 is None:
            return
        track = pcbnew.PCB_TRACK(board)
        track.SetStart(p1)
        track.SetEnd(p2)
        track.SetWidth(mm(width_mm))
        track.SetLayer(layer)
        track.SetNetCode(net_code)
        board.Add(track)

    def route_pads(ref1, pad1, ref2, pad2, width_mm, layer=pcbnew.F_Cu):
        """Route a trace between two pads."""
        p1 = get_pad_pos(ref1, pad1)
        p2 = get_pad_pos(ref2, pad2)
        nc = get_pad_net_code(ref1, pad1)
        add_track(p1, p2, width_mm, layer, nc)

    # Trace widths by current rating
    W_8A = 3.0    # 12V base/shoulder (8A)
    W_5A = 2.0    # 7.4V elbow (5A)
    W_3A = 1.2    # 5V wrist (3A)
    W_SIG = 0.4   # signal / I2C / PWM
    W_PWR_LOW = 0.6  # low-current power (3.3V, 5V logic)

    # --- Power: 12V input terminals paralleled ---
    # Chain 12V terminals together
    for i in range(3):
        route_pads(f"J_12V_{i+1}", 1, f"J_12V_{i+2}", 1, W_8A)

    # Chain GND terminals
    route_pads("J_GND_1", 1, "J_GND_2", 1, W_8A)
    route_pads("J_GND_1", 2, "J_GND_2", 2, W_8A)

    # --- Power rails to fuse inputs ---
    # 12V to base/shoulder fuses
    for fuse in ["F1", "F2", "F6", "F7"]:
        route_pads("J_12V_1", 1, fuse, 1, W_8A)

    # 7.4V to elbow fuses
    route_pads("J_7V4", 1, "F3", 1, W_5A)
    route_pads("J_7V4", 1, "F8", 1, W_5A)

    # 5V servo to wrist fuses
    for fuse in ["F4", "F5", "F9", "F10"]:
        route_pads("J_5VS", 1, fuse, 1, W_3A)

    # --- Fuse outputs to servo power pins ---
    for i in range(10):
        route_pads(f"F{i+1}", 2, f"SV{i+1}", 2, W_8A if i in [0,1,5,6] else W_5A if i in [2,7] else W_3A)

    # --- 12V direct to ESC and Fan ---
    route_pads("J_12V_1", 1, "J_ESC", 2, W_8A)
    route_pads("J_12V_1", 1, "J_FAN", 2, W_3A)

    # --- PWM signals: PCA9685 to servo headers ---
    # Ch0-4 (Arm1) from J_PCA_A pins 1-5
    for i in range(5):
        route_pads("J_PCA_A", i + 1, f"SV{i+1}", 1, W_SIG)

    # Ch5-7 (Arm2 first 3) from J_PCA_A pins 6-8
    for i in range(3):
        route_pads("J_PCA_A", 6 + i, f"SV{6+i}", 1, W_SIG)

    # Ch8-9 (Arm2 last 2) from J_PCA_B pins 1-2
    route_pads("J_PCA_B", 1, "SV9", 1, W_SIG)
    route_pads("J_PCA_B", 2, "SV10", 1, W_SIG)

    # Ch11 (ESC) from J_PCA_B pin 4
    route_pads("J_PCA_B", 4, "J_ESC", 1, W_SIG)

    # Ch12 (Fan) from J_PCA_B pin 5
    route_pads("J_PCA_B", 5, "J_FAN", 1, W_SIG)

    # --- I2C bus: chain all I2C ports + PCA control ---
    # SDA chain
    route_pads("J_PCA_CTRL", 4, "J_I2C1", 1, W_SIG)
    for i in range(3):
        route_pads(f"J_I2C{i+1}", 1, f"J_I2C{i+2}", 1, W_SIG)

    # SCL chain
    route_pads("J_PCA_CTRL", 3, "J_I2C1", 2, W_SIG)
    for i in range(3):
        route_pads(f"J_I2C{i+1}", 2, f"J_I2C{i+2}", 2, W_SIG)

    # 3.3V chain
    route_pads("J_3V3", 1, "J_PCA_CTRL", 5, W_PWR_LOW)
    route_pads("J_PCA_CTRL", 5, "J_I2C1", 3, W_PWR_LOW)
    for i in range(3):
        route_pads(f"J_I2C{i+1}", 3, f"J_I2C{i+2}", 3, W_PWR_LOW)

    # --- GND: servo headers on back copper to GND pour ---
    # Route all servo GND pins to nearest GND terminal via back copper
    for i in range(10):
        route_pads(f"SV{i+1}", 3, "J_GND_1", 1, W_8A, pcbnew.B_Cu)
    route_pads("J_ESC", 3, "J_GND_1", 1, W_8A, pcbnew.B_Cu)
    route_pads("J_FAN", 3, "J_GND_1", 1, W_8A, pcbnew.B_Cu)

    # I2C GND on back copper
    for i in range(4):
        route_pads(f"J_I2C{i+1}", 4, "J_GND_1", 1, W_SIG, pcbnew.B_Cu)

    # PCA control GND
    route_pads("J_PCA_CTRL", 1, "J_GND_1", 1, W_SIG, pcbnew.B_Cu)

    print(f"Routed {len(board.GetTracks())} traces")

    # ==============================================================
    # SAVE
    # ==============================================================
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "geodude-carrier.kicad_pcb")
    board.Save(out)

    n_fp = len(board.GetFootprints())
    n_nets = board.GetNetCount()
    n_tracks = len(board.GetTracks())
    print(f"PCB saved: {out}")
    print(f"Board: {BOARD_W}x{BOARD_H}mm")
    print(f"Components: {n_fp}, Nets: {n_nets}, Traces: {n_tracks}")
    print("Ready to open in KiCad.")

if __name__ == "__main__":
    main()
