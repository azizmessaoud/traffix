"""Webster-retimed fixed-time plans: the fair baseline every TraffiX claim is compared against.

Plain retiming is what a city can do without any AI (field studies report 15-37% less delay
than old plans), so beating SUMO's default 90 s plans is not enough. This module builds, for one
scenario, a fixed-time plan that a traffic engineer would set from counts:

  1. route the scenario's trips with duarouter (the demand file has trips, not routes, and
     tlsCycleAdaptation can only count flows on routed vehicles);
  2. run SUMO's tlsCycleAdaptation.py (Webster's method) on those routes;
  3. keep each junction's own phase structure: walk green + 5 s pedestrian clearance + yellow,
     with walk + clearance long enough for a slow walker to cross the longest crossing.

The plan is designed from a separate DESIGN_SEED of the same scenario, never from the seed it is
evaluated on, the way an engineer designs from one count survey and lives with other days.
"""
import os
import subprocess
import sys
import xml.etree.ElementTree as ET

import sumo

from ..core import config

SUMO_HOME = os.environ.get("SUMO_HOME", sumo.SUMO_HOME)
DESIGN_SEED = 1000
MIN_CYCLE, MAX_CYCLE = 60, 120
MIN_WALK = 7          # s, minimum walk green
PROGRAM_ID = "webster"


def crossing_lengths(net_file):
    """Longest pedestrian crossing (m) at each junction."""
    out = {}
    for e in ET.parse(net_file).getroot().iter("edge"):
        if e.get("function") == "crossing":
            junction = e.get("id")[1:].rsplit("_c", 1)[0]
            length = max(float(l.get("length")) for l in e.findall("lane"))
            out[junction] = max(out.get(junction, 0.0), length)
    return out


def _phases(tl):
    return [(int(float(p.get("duration"))), p.get("state")) for p in tl.findall("phase")]


def restructure(default_tl, webster_tl, crossing_m, slow_speed):
    """Webster's green split, poured into the junction's own walk / clearance / yellow pattern.

    tlsCycleAdaptation gives every green phase of a stage the same length; the original plans have
    a long walk green, a 5 s clearance (vehicles still green, walkers red) and a 3 s yellow. The
    stage's total green from Webster is kept, the clearance stays 5 s, and walk + clearance is
    raised if needed so a slow walker who starts at the end of the walk can still finish."""
    base, web = _phases(default_tl), _phases(webster_tl)
    ped_min = crossing_m / slow_speed if crossing_m else 0
    out = []
    i = 0
    while i < len(base):
        dur, state = base[i]
        if "y" in state:
            out.append((dur, state))
            i += 1
            continue
        # a stage: walk green, then (optionally) the clearance green
        clear = base[i + 1] if i + 1 < len(base) and "y" not in base[i + 1][1] else None
        stage_green = web[i][0] + (web[i + 1][0] if clear else 0)
        clear_s = clear[0] if clear else 0
        walk = max(MIN_WALK, stage_green - clear_s, int(round(ped_min - clear_s + 0.5)))
        out.append((walk, state))
        if clear:
            out.append((clear_s, clear[1]))
            i += 2
        else:
            i += 1
    return out


def build_plan(scenario, out_dir):
    """Writes <out_dir>/<scenario>_webster.tls.xml and returns its path (cached)."""
    net = config.network_files()[0]
    out = os.path.join(out_dir, f"{scenario}_webster.tls.xml")
    if os.path.exists(out) and os.path.getmtime(out) > os.path.getmtime(net):
        return out
    base = os.path.join(out_dir, f"{scenario}_seed{DESIGN_SEED}")
    from .runner import demand_is_current
    if not demand_is_current(base):
        from ..demand.generator import DemandGenerator
        DemandGenerator(net).build(scenario, config.scenarios()[scenario], DESIGN_SEED, out_dir)
    routed = base + ".routed.xml"
    stops = net.replace(".net.xml", ".stops.xml")
    subprocess.run([os.path.join(SUMO_HOME, "bin", "duarouter"), "-n", net, "-r", base + ".rou.xml",
                    "-o", routed, "--ignore-errors", "--no-warnings", "--no-step-log"]
                   + (["-a", stops] if os.path.exists(stops) else []),
                   check=True, capture_output=True)
    raw = base + ".webster_raw.tls.xml"
    subprocess.run([sys.executable, os.path.join(SUMO_HOME, "tools", "tlsCycleAdaptation.py"),
                    "-n", net, "-r", routed, "-b", "0", "-o", raw,
                    "--min-cycle", str(MIN_CYCLE), "--max-cycle", str(MAX_CYCLE)],
                   check=True, capture_output=True)
    defaults = {t.get("id"): t for t in ET.parse(net).getroot().findall("tlLogic")}
    webster = {t.get("id"): t for t in ET.parse(raw).getroot().findall("tlLogic")}
    lengths = crossing_lengths(net)
    slow = config.demand()["slow_walker_speed"]
    root = ET.Element("additional")
    for tls, default_tl in defaults.items():
        if tls not in webster:                      # Webster had no flows: keep the default plan
            continue
        tl = ET.SubElement(root, "tlLogic", id=tls, type="static", programID=PROGRAM_ID, offset="0")
        for dur, state in restructure(default_tl, webster[tls], lengths.get(tls, 0), slow):
            ET.SubElement(tl, "phase", duration=str(dur), state=state)
    ET.indent(root)
    ET.ElementTree(root).write(out, encoding="UTF-8", xml_declaration=True)
    return out


def describe(path):
    """{tls: (cycle_s, [durations])} for a plan file, for reports."""
    return {t.get("id"): (sum(int(p.get("duration")) for p in t), [int(p.get("duration")) for p in t])
            for t in ET.parse(path).getroot().findall("tlLogic")}
