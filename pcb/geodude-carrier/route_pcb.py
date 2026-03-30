#!/usr/bin/env python3
"""Full headless routing pipeline: generate PCB → export DSN → patch widths → Freerouting → import SES.

Run with KiCad's Python:
/Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/Current/bin/python3 route_pcb.py
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

# Net-to-width mapping in mm, converted to um for DSN
# KiCad DSN export uses micrometers (um)
def mm_to_um(v):
    return int(v * 1000)

NET_WIDTHS_MM = {
    # 8A power (12V base/shoulder, ESC)
    "+12V": 3.0,
    "SV1_PWR": 3.0, "SV2_PWR": 3.0,
    "SV6_PWR": 3.0, "SV7_PWR": 3.0,
    # 5A power (7.4V elbow)
    "+7V4": 2.0,
    "SV3_PWR": 2.0, "SV8_PWR": 2.0,
    # 3A power (5V wrist)
    "+5V_SERVO": 1.5,
    "SV4_PWR": 1.5, "SV5_PWR": 1.5,
    "SV9_PWR": 1.5, "SV10_PWR": 1.5,
    # Low current power
    "+5V_LOGIC": 0.6,
    "+3V3": 0.6,
    # GND gets wide traces too
    "GND": 3.0,
}
# Convert to um for DSN file
NET_WIDTHS = {k: mm_to_um(v) for k, v in NET_WIDTHS_MM.items()}
DEFAULT_WIDTH = 400  # 0.4mm = 400um for signal traces


def patch_dsn_widths(dsn_file):
    """Patch the DSN file to set per-net trace widths via net classes."""
    with open(dsn_file, "r") as f:
        content = f.read()

    # Find the (network section and inject net class rules
    # Freerouting DSN uses (rule ... (width X)) in the (structure section
    # We'll modify the default width and add net-specific rules

    # Replace the default width in the structure/rule section
    content = re.sub(
        r'(\(rule\s*\(width\s+)[\d.]+(\))',
        f'\\g<1>{DEFAULT_WIDTH}\\2',  # default 400um for signals
        content
    )

    # Add net class rules before the closing of the structure section
    # Build class definitions
    classes = {}
    for net, width in NET_WIDTHS.items():
        w_key = f"w{int(width*10)}"
        if w_key not in classes:
            classes[w_key] = {"width": width, "nets": []}
        classes[w_key]["nets"].append(net)

    class_defs = ""
    for cls_name, cls_data in classes.items():
        net_list = " ".join(f'"{n}"' for n in cls_data["nets"])
        class_defs += f'    (class {cls_name} {net_list}\n'
        class_defs += f'      (rule (width {cls_data["width"]}))\n'  # already in um
        class_defs += f'    )\n'

    # Insert classes into the network section
    # Find "(network" and add classes before the closing ")"
    # Actually, in Specctra DSN, classes go in the (network section
    network_end = content.rfind(")")  # last closing paren
    # Find the network section
    net_section_start = content.find("(network")
    if net_section_start >= 0:
        # Find the matching closing paren for network
        depth = 0
        pos = net_section_start
        for i in range(net_section_start, len(content)):
            if content[i] == '(':
                depth += 1
            elif content[i] == ')':
                depth -= 1
                if depth == 0:
                    # Insert before this closing paren
                    content = content[:i] + "\n" + class_defs + content[i:]
                    break

    with open(dsn_file, "w") as f:
        f.write(content)

    print(f"Patched DSN with {len(classes)} net classes")


def main():
    # Step 1: Generate PCB
    print("Step 1: Generating PCB...")
    result = subprocess.run(
        ["/Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/Current/bin/python3",
         os.path.join(BASE, "generate_pcb.py")],
        capture_output=True, text=True
    )
    print(result.stdout)
    if result.returncode != 0:
        print(f"ERROR: {result.stderr}")
        return

    # Step 2: Export DSN
    print("Step 2: Exporting DSN...")
    board = pcbnew.LoadBoard(PCB_FILE)
    pcbnew.ExportSpecctraDSN(board, DSN_FILE)
    print(f"DSN exported: {DSN_FILE}")

    # Step 3: Patch DSN with trace width rules
    print("Step 3: Patching DSN trace widths...")
    patch_dsn_widths(DSN_FILE)

    # Step 4: Run Freerouting
    print("Step 4: Running Freerouting...")
    result = subprocess.run(
        [JAVA, "-jar", FREEROUTING, "-de", DSN_FILE, "-do", SES_FILE, "-mp", "50"],
        capture_output=True, text=True, timeout=120
    )
    print(result.stdout)
    if result.returncode != 0:
        print(f"Freerouting stderr: {result.stderr}")

    if not os.path.exists(SES_FILE):
        print("ERROR: Freerouting did not produce SES file")
        return

    # Step 5: Import SES back into PCB
    print("Step 5: Importing routed traces...")
    board = pcbnew.LoadBoard(PCB_FILE)
    pcbnew.ImportSpecctraSES(board, SES_FILE)
    board.Save(PCB_FILE)
    print(f"Imported. Tracks: {len(board.GetTracks())}")

    # Step 6: Run DRC
    print("Step 6: DRC check...")
    result = subprocess.run(
        ["/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli",
         "pcb", "drc", PCB_FILE, "-o", os.path.join(BASE, "drc_report.txt")],
        capture_output=True, text=True
    )
    print(result.stdout)

    # Step 7: Export SVG
    print("Step 7: Exporting SVG preview...")
    subprocess.run(
        ["/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli",
         "pcb", "export", "svg", PCB_FILE,
         "-o", os.path.join(BASE, "geodude-carrier.svg"),
         "-l", "F.Cu,B.Cu,Edge.Cuts,F.SilkS"],
        capture_output=True, text=True
    )
    print("Done! Open geodude-carrier.kicad_pcb in KiCad to review.")

if __name__ == "__main__":
    main()
