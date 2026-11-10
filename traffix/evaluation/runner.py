"""Runs one simulation: one controller, one scenario, one seed."""
import json
import os
from datetime import datetime

import sumo

from ..core import config
from ..core.decision_log import DecisionLog
from ..demand.generator import net_digest
from ..orchestration.system import TraffixSystem
from ..simulation.backend import traci
from ..simulation.network_model import load_models
from ..simulation.world import World
from .monitor import Monitor

SUMO_HOME = os.environ.get("SUMO_HOME", sumo.SUMO_HOME)
GEN = config.path("data", "generated")
OUT = config.path("results")


def detection_metrics(entries, events):
    out = {}
    alarms = [e for e in entries if e["reason"] == "INCIDENT_SUSPECTED"]
    inc = events.get("incident")
    hits = []
    if inc:
        hits = [e for e in alarms if e["details"]["edge"] == inc["edge"]
                and inc["at"] <= e["t"] <= inc["at"] + inc["duration"] + 60]
        out["incident_detected"] = bool(hits)
        out["incident_detect_delay_s"] = hits[0]["t"] - inc["at"] if hits else None
    out["incident_false_alarms"] = len(alarms) - len(hits)
    fault = events.get("sensor_fault")
    if fault:
        st = [e for e in entries if e["reason"] == "DATA_STALE" and e["t"] >= fault["at"]]
        out["stale_detect_delay_s"] = st[0]["t"] - fault["at"] if st else None
    return out


def demand_is_current(base):
    """True when the traffic files at `base` exist and were built for the current build of the map.
    Traffic built for another map, or an older build, can use stops or edges this one lacks."""
    try:
        with open(base + ".events.json") as f:
            meta = json.load(f)
    except FileNotFoundError:
        return False
    return (meta.get("network") == config.network_name()
            and meta.get("net_digest") == net_digest(config.network_files()[0]))


def run_one(controller, scenario, seed, gui=False, route_dir=GEN, hooks=None, save_log=True):
    """hooks: optional callables f(now, system) called every second (used by data generation)."""
    nets = config.network_files()
    net = nets[1] if controller == "actuated" else nets[0]
    base = os.path.join(route_dir, f"{scenario}_seed{seed}")
    if not demand_is_current(base):
        raise RuntimeError(f"{base}.rou.xml was not built for the current {config.network_name()} map: "
                           f"run scripts/build_demand.py --scenario {scenario} --seeds {seed}")
    meta = json.load(open(base + ".events.json"))
    tag = f"{controller}_{scenario}_{seed}"
    for d in ("tripinfo", "logs"):
        os.makedirs(os.path.join(OUT, d), exist_ok=True)
    tripinfo = os.path.join(OUT, "tripinfo", f"{tag}.xml")
    binary = os.path.join(SUMO_HOME, "bin", "sumo-gui" if gui else "sumo")
    stops = nets[0].replace(".net.xml", ".stops.xml")
    additional = [stops] if os.path.exists(stops) else []
    if controller == "fixed_retimed":          # Webster plan designed on another seed (retime.py)
        from .retime import build_plan
        additional.append(build_plan(scenario, route_dir))
    traci.start([binary, "-n", net, "-r", base + ".rou.xml", "--tripinfo-output", tripinfo]
                + (["-a", ",".join(additional)] if additional else []) + [
                 "--device.emissions.probability", "1", "--time-to-teleport", "300",
                 "--ignore-route-errors", "true", "--seed", str(seed),
                 "--no-step-log", "true", "--no-warnings", "true",
                 "--error-log", os.path.join(OUT, "logs", f"sumo_errors_{tag}.txt")]
                + (["--delay", "100"] if gui else []))
    models = load_models(net)
    log = DecisionLog(os.path.join(OUT, "logs", f"decisions_{tag}.jsonl") if save_log else None)
    start = datetime.strptime(meta["start"], "%Y-%m-%d %H:%M")
    system = None
    if controller not in ("fixed", "fixed_retimed", "actuated"):
        system = TraffixSystem(controller, models, net, log, start)
        system.start(0)
    world = World(meta["events"], models, system.sensors if system else None)
    monitor = Monitor(models)
    end = meta["duration"] + config.simulation()["max_extra_time"]
    try:
        while traci.simulation.getMinExpectedNumber() > 0 and traci.simulation.getTime() < end:
            traci.simulationStep()
            now = traci.simulation.getTime()
            world.step(now)
            if system:
                system.step(now)
            monitor.step(now)
            for h in hooks or []:
                h(now, system)
    finally:
        traci.close()
    row = {"controller": controller, "scenario": scenario, "seed": seed, "start": meta["start"]}
    row.update(monitor.results(tripinfo, meta["vehicles"]))
    if system:
        log.save()
        e = log.entries
        row.update({"decisions_logged": len(e),
                    "emergency_granted": sum(x["reason"].startswith("EMERGENCY_GRANTED") for x in e),
                    "emergency_prepared": log.count("EMERGENCY_PREPARE"),
                    "emergency_denied_exit_full": log.count("EMERGENCY_DENIED_EXIT_FULL"),
                    "transit_granted": sum(x["reason"].startswith("TRANSIT_GRANTED") for x in e),
                    "ped_service_granted": log.count("PED_SERVICE_GRANTED"),
                    "clearance_extended": log.count("CLEARANCE_EXTENDED"),
                    "corridor_switches": log.count("CORRIDOR_PLATOON"),
                    "reroute_advisories": log.count("REROUTE_ADVISORY"),
                    "notifications": len(system.bus.notifications),
                    "mode_fallbacks": log.count("MODE_FIXED") + log.count("MODE_ACTUATED")})
        row.update(detection_metrics(e, meta["events"]))
    return {k: (round(v, 3) if isinstance(v, float) else v) for k, v in row.items()}
