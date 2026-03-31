#!/usr/bin/env python3
"""Headless routing pipeline: export DSN → patch widths/vias/layers → Freerouting → import SES.

Run with KiCad's Python:
/Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/Current/bin/python3 route_pcb.py

Does NOT regenerate the PCB — routes whatever placement is currently saved.
"""

import pcbnew
import subprocess
import os
import re

BASE = os.path.dirname(os.path.abspath(__file__))
PCB_FILE = os.path.join(BASE, "geodude-carrier.kicad_pcb")
DSN_FILE = os.path.join(BASE, "geodude-carrier.dsn")
SES_FILE = os.path.join(BASE, "geodude-carrier.ses")
JAVA = "/tmp/jdk-21.0.2.jdk/Contents/Home/bin/java"
FREEROUTING = "/tmp/freerouting.jar"

MAX_PASSES = 200

# ==============================================================
# Nets to exclude from autorouting (route manually)
# ==============================================================
EXCLUDE_NETS = [
    "GND",          # handled by F.Cu pour
    "+12V",         # handled by F.Cu pour
    "GND_LOGIC",    # handled by F.Cu pour
    "+12V_FOC",     # manual routing
]

# ==============================================================
# Trace widths — 1oz copper, 10°C rise (IPC-2221)
# ==============================================================
# 8A = 3.8mm, 5A = 2.0mm, 3A = 1.0mm, 2.5A = 1.5mm, <1A = 0.6mm, signal = 0.4mm

DEFAULT_WIDTH_UM = 400  # 0.4mm for signals

NET_CLASSES = {
    # name: (width_um, via_type, layer, nets)
    # via_type: "power" = 0.6mm drill/1.0mm pad, "signal" = 0.3mm/0.6mm
    # layer: "F.Cu", "B.Cu", or None (both)

    "pwr_8a": (3800, "power", "F.Cu", [
        "+12V", "SV1_PWR", "SV2_PWR", "SV6_PWR", "SV7_PWR",
    ]),
    "pwr_5a": (2000, "power", "F.Cu", [
        "+7V4", "SV3_PWR", "SV8_PWR",
    ]),
    "pwr_3a": (1000, "power", "F.Cu", [
        "+5V_SERVO", "SV4_PWR", "SV5_PWR", "SV9_PWR", "SV10_PWR",
    ]),
    "pwr_motor": (1500, "power", "F.Cu", [
        "+12V_FOC", "MOTOR_U", "MOTOR_V", "MOTOR_W",
    ]),
    "pwr_low": (600, "signal", None, [
        "+5V_LOGIC", "+3V3", "+12V_FAN",
    ]),
    "gnd_power": (3800, "power", None, [
        "GND",
    ]),
    "gnd_logic": (600, "signal", None, [
        "GND_LOGIC",
    ]),
    "sig_pwm": (400, "signal", "B.Cu", [
        "PWM_CH0", "PWM_CH1", "PWM_CH2", "PWM_CH3", "PWM_CH4",
        "PWM_CH5", "PWM_CH6", "PWM_CH7", "PWM_CH8", "PWM_CH9",
        "PWM_CH10", "PWM_CH11", "PWM_CH12", "PWM_CH13", "PWM_CH14", "PWM_CH15",
    ]),
    "sig_i2c": (400, "signal", None, [
        "SDA", "SCL", "PICO_SDA", "PICO_SCL",
    ]),
    "sig_foc": (400, "signal", "B.Cu", [
        "FOC_IN1", "FOC_IN2", "FOC_IN3", "FOC_EN",
    ]),
    "sig_serial": (400, "signal", "B.Cu", [
        "PICO_TX", "PICO_RX",
    ]),
    "sig_fan": (400, "signal", "B.Cu", [
        "TACH",
    ]),
}

# ==============================================================
# Via definitions
# ==============================================================
POWER_VIA = 'Via[0-1]_1000:600_um'   # 0.6mm drill, 1.0mm pad
SIGNAL_VIA = 'Via[0-1]_600:300_um'   # 0.3mm drill, 0.6mm pad


def patch_dsn(dsn_file):
    """Patch the DSN file with trace widths, via sizes, and layer restrictions."""
    with open(dsn_file, "r") as f:
        content = f.read()

    # 0. Remove excluded nets from DSN (they won't be autorouted)
    for net_name in EXCLUDE_NETS:
        # DSN format: (net GND (pins J1-1 J2-1 ...)) — no quotes around net name
        # Match with or without quotes
        for pattern in [
            r'\(net\s+%s\s+\(pins[^)]*\)\s*\)' % re.escape(net_name),
            r'\(net\s+"%s"\s+\(pins[^)]*\)\s*\)' % re.escape(net_name),
        ]:
            removed = len(re.findall(pattern, content))
            if removed:
                content = re.sub(pattern, '', content)
                print("  Excluded net %s from routing (%d blocks removed)" % (net_name, removed))
                break
        else:
            print("  WARNING: net %s not found in DSN" % net_name)

    # 1. Set default trace width
    content = re.sub(
        r'(\(rule\s*\(width\s+)[\d.]+(\))',
        r'\g<1>%d\2' % DEFAULT_WIDTH_UM,
        content
    )

    # 2. Add power via padstack to library if missing
    if POWER_VIA not in content:
        fp = content.find('(padstack')
        if fp >= 0:
            pv = (
                '    (padstack %s\n'
                '      (shape (circle "F.Cu" 1000))\n'
                '      (shape (circle "B.Cu" 1000))\n'
                '      (attach off)\n'
                '    )\n' % POWER_VIA
            )
            content = content[:fp] + pv + content[fp:]

    # 3. Register both vias in structure section
    old_via = '(via "%s")' % SIGNAL_VIA
    new_via = '(via "%s" "%s")' % (SIGNAL_VIA, POWER_VIA)
    struct_start = content.find('(structure')
    if struct_start >= 0:
        struct_chunk = content[struct_start:struct_start + 500]
        if POWER_VIA not in struct_chunk:
            content = content.replace(old_via, new_via, 1)

    # 4. Build net class definitions with via_rule + layer restrictions
    # Via info and rules (in network section)
    via_defs = '    (via "PowerViaInfo" "%s" default)\n' % POWER_VIA
    via_defs += '    (via "SignalViaInfo" "%s" default)\n' % SIGNAL_VIA
    via_defs += '    (via_rule power_via_rule PowerViaInfo)\n'
    via_defs += '    (via_rule signal_via_rule SignalViaInfo)\n'

    class_defs = ""
    for cls_name, (width, via_type, layer, nets) in NET_CLASSES.items():
        net_list = " ".join('"%s"' % n for n in nets)
        via_rule = "power_via_rule" if via_type == "power" else "signal_via_rule"

        class_defs += '    (class %s %s\n' % (cls_name, net_list)
        class_defs += '      (via_rule %s)\n' % via_rule
        class_defs += '      (rule (width %d))\n' % width
        if layer:
            class_defs += '      (circuit\n'
            class_defs += '        (use_layer "%s")\n' % layer
            class_defs += '      )\n'
        class_defs += '    )\n'

    # 5. Insert into network section
    ns = content.find("(network")
    if ns >= 0:
        depth = 0
        for i in range(ns, len(content)):
            if content[i] == '(':
                depth += 1
            elif content[i] == ')':
                depth -= 1
                if depth == 0:
                    content = content[:i] + "\n" + via_defs + class_defs + content[i:]
                    break

    with open(dsn_file, "w") as f:
        f.write(content)

    print("Patched DSN: %d net classes" % len(NET_CLASSES))
    print("  Power traces on F.Cu, signals on B.Cu")
    print("  Power vias: 0.6mm drill / 1.0mm pad")
    print("  Signal vias: 0.3mm drill / 0.6mm pad")


def main():
    # Step 1: Strip autorouted tracks only (preserve manual tracks on excluded nets)
    print("Step 1: Stripping tracks (preserving excluded net tracks)...")
    board = pcbnew.LoadBoard(PCB_FILE)
    stripped = kept = 0
    for t in list(board.GetTracks()):
        if t.GetNetname() in EXCLUDE_NETS:
            kept += 1
        else:
            board.Remove(t)
            stripped += 1
    board.Save(PCB_FILE)
    print("  Stripped %d tracks, kept %d on excluded nets" % (stripped, kept))

    # Step 2: Export DSN
    print("Step 2: Exporting DSN...")
    board = pcbnew.LoadBoard(PCB_FILE)
    pcbnew.ExportSpecctraDSN(board, DSN_FILE)

    # Step 3: Patch DSN
    print("Step 3: Patching DSN...")
    patch_dsn(DSN_FILE)

    # Step 4: Run Freerouting
    print("Step 4: Running Freerouting (max %d passes)..." % MAX_PASSES)
    result = subprocess.run(
        [JAVA, "-jar", FREEROUTING, "-de", DSN_FILE, "-do", SES_FILE,
         "-mp", str(MAX_PASSES)],
        capture_output=True, text=True, timeout=600
    )
    print(result.stdout[-400:] if len(result.stdout) > 400 else result.stdout)
    if result.returncode != 0:
        print("STDERR: " + result.stderr[-300:])

    if not os.path.exists(SES_FILE):
        print("ERROR: Freerouting did not produce SES file")
        return

    # Step 5: Import SES
    print("Step 5: Importing routed traces...")
    board = pcbnew.LoadBoard(PCB_FILE)
    pcbnew.ImportSpecctraSES(board, SES_FILE)
    board.Save(PCB_FILE)

    # Report
    ToMM = pcbnew.ToMM
    via_sizes = {}
    for t in board.GetTracks():
        if t.GetClass() == "PCB_VIA":
            d = ToMM(t.GetDrillValue())
            via_sizes[d] = via_sizes.get(d, 0) + 1

    print("\nDone! Tracks: %d" % len(board.GetTracks()))
    for d, c in sorted(via_sizes.items()):
        print("  Via %.1fmm drill: %d" % (d, c))

    # Step 6: DRC
    print("\nStep 6: DRC check...")
    kicad_cli = "/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli"
    drc_report = os.path.join(BASE, "drc_report.txt")
    result = subprocess.run(
        [kicad_cli, "pcb", "drc", PCB_FILE, "-o", drc_report, "--severity-all"],
        capture_output=True, text=True
    )
    print(result.stdout)


if __name__ == "__main__":
    main()
