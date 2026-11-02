"""
Live mode: runs ONE simulation in a background thread, paced for watching,
and keeps a snapshot of everything the persona pages need.
"""
import copy
import json
import os
import queue
import threading
import time
import traceback
import uuid
from datetime import datetime

try:                                     # SUMO is optional at import time; a live run needs it
    import sumo
    import sumolib
except ImportError:
    sumo = sumolib = None

from ..core import config
from ..core.decision_log import DecisionLog
from ..core.narrate import Narrator
from ..synapse.alert_writer import AlertWriter
from ..synapse.copilot import Copilot
from ..agents.network.rerouting import shortest
from ..demand.generator import DemandGenerator, classify_edges
from ..orchestration.system import TraffixSystem
from ..simulation.backend import traci
from ..simulation.network_model import load_models
from ..simulation.world import World

SUMO_HOME = os.environ.get("SUMO_HOME", sumo.SUMO_HOME if sumo else "")


def _close_traci():
    """Close the TraCI connection if one is open; SUMO may already be gone."""
    try:
        traci.close()
    except Exception:                                   # noqa: BLE001 - nothing open or SUMO gone
        pass


def _point_back(shape, dist, side):
    """Point `dist` metres before the end of a polyline, shifted `side` metres to the right."""
    import math
    (x1, y1), (x2, y2) = shape[-2], shape[-1]
    L = math.hypot(x2 - x1, y2 - y1) or 1.0
    ux, uy = (x2 - x1) / L, (y2 - y1) / L
    d = min(dist, L * 0.8)
    return x2 - ux * d + uy * side, y2 - uy * d - ux * side


def network_geometry(net_file):
    import xml.etree.ElementTree as ET
    from sumolib.geomhelper import positionAtShapeOffset
    net = sumolib.net.readNet(net_file)
    nodes = [{"id": n.getID(), "x": n.getCoord()[0], "y": n.getCoord()[1],
              "signal": n.getType() == "traffic_light"} for n in net.getNodes()]
    edges, signals, crossings = [], [], []
    for e in net.getEdges():
        if e.getFunction() == "crossing":
            tls = e.getID().lstrip(":").split("_c")[0]
            crossings.append({"id": e.getID(), "tls": tls, "shape": [list(p) for p in e.getLanes()[0].getShape()]})
            continue
        if e.getFunction() or not e.allows("passenger") and not e.allows("bus"):
            continue
        lanes = [l for l in e.getLanes() if l.allows("passenger") or l.allows("bus")]
        bus_only = any(l.allows("bus") and not l.allows("passenger") for l in lanes)
        edges.append({"id": e.getID(), "from": e.getFromNode().getID(), "to": e.getToNode().getID(),
                      "name": e.getName(), "lanes": len(lanes), "bus_lane": bus_only,
                      "shape": [list(p) for p in e.getShape()],
                      "lane_shapes": [[list(p) for p in l.getShape()] for l in lanes],
                      "sidewalks": [[list(p) for p in l.getShape()] for l in e.getLanes()
                                    if l.allows("pedestrian") and not l.allows("passenger") and not l.allows("bus")]})
        if e.getToNode().getType() == "traffic_light":
            x, y = _point_back(e.getShape(), 42, 2 + 3.2 * len(lanes))
            signals.append({"tls": e.getToNode().getID(), "edge": e.getID(), "x": x, "y": y})
    stops = []
    stops_file = net_file.replace(".net.xml", ".stops.xml")
    if os.path.exists(stops_file):
        for b in ET.parse(stops_file).getroot().findall("busStop"):
            lane = net.getLane(b.get("lane"))
            x, y = positionAtShapeOffset(lane.getShape(), (float(b.get("startPos")) + float(b.get("endPos"))) / 2)
            p = b.find("param")
            stops.append({"id": b.get("id"), "name": b.get("name"), "x": x, "y": y,
                          "lines": b.get("lines").split(), "junction": p.get("value") if p is not None else ""})
    xs = [n["x"] for n in nodes]
    ys = [n["y"] for n in nodes]
    basemap = None                                   # street map warped into net x/y (scripts/build_basemap.py)
    basemap_file = net_file.replace(".net.xml", ".basemap.json")
    if os.path.exists(basemap_file):
        with open(basemap_file, encoding="utf-8") as f:
            meta = json.load(f)
        basemap = {"bounds": meta["bounds"], "attribution": meta["attribution"],
                   "styles": {name: f"/api/basemap/{name}" for name in meta["styles"]},
                   "tiles": meta.get("tiles", {}), "max_zoom": meta.get("max_zoom", 19),
                   "net_to_merc": meta.get("net_to_merc"), "merc_to_net": meta.get("merc_to_net")}
    return {"nodes": nodes, "edges": edges, "signals": signals, "crossings": crossings, "bus_stops": stops,
            "bounds": [min(xs), min(ys), max(xs), max(ys)], "basemap": basemap}


class LiveRun:
    def __init__(self, scenario, seed=1, speed=4.0, controller="traffix", gui=False):
        self.scenario, self.seed, self.speed, self.controller = scenario, seed, speed, controller
        self.gui = gui          # also show THIS run in SUMO's own window
        self.lock = threading.Lock()
        self.event_commands = queue.Queue(maxsize=20)
        self.world_events = []
        self._event_requests = {}
        self.snapshot = {"status": "starting"}
        self.log = DecisionLog()
        self.running = False
        net = config.network_files()[0]
        self.geometry = network_geometry(net)
        self.geometry_links = None
        self._static(net)
        gen = DemandGenerator(net)
        self.routes, self.meta = gen.build(scenario, config.scenarios()[scenario], seed,
                                           config.path("data", "generated", "live"))

    def _static(self, net_file):
        """Trip planner data that never changes: road graph, free-flow times, places, bus lines."""
        net = sumolib.net.readNet(net_file)
        # Only lanes the junction sensors read can be detected; offering any other lane
        # would let an operator inject an event that the system can never report.
        observed = {lane for m in load_models(net_file).values()
                    for lane in m.incoming_lanes + m.outgoing_lanes}
        self.incident_options = []
        self._incident_lanes = {}
        for edge in net.getEdges():
            if edge.getFunction() or not edge.allows("passenger"):
                continue
            lane_indexes = [lane.getIndex() for lane in edge.getLanes()
                            if lane.allows("passenger") and lane.getID() in observed]
            if lane_indexes:
                self._incident_lanes[edge.getID()] = lane_indexes
                self.incident_options.append({
                    "edge_id": edge.getID(), "name": edge.getName() or edge.getID(),
                    "lanes": lane_indexes,
                })
        self.graph = {e.getID(): [o.getID() for o in e.getOutgoing()]
                      for e in net.getEdges() if not e.getFunction()}
        self.free_tt = {e.getID(): e.getLength() / max(e.getSpeed(), 0.1)
                        for e in net.getEdges() if not e.getFunction()}
        self.edge_name = {e.getID(): e.getName() or e.getID() for e in net.getEdges() if not e.getFunction()}
        self.edge_to = {e.getID(): e.getToNode().getID() for e in net.getEdges() if not e.getFunction()}
        entries, exits, _ = classify_edges(net)
        self.places = {"from": self._place_names(entries, "getOutgoing"),
                       "to": self._place_names(exits, "getIncoming")}
        self.lines, self.line_edges = {}, {}
        routes = config.line_routes(net)
        self.geometry["line_info"] = {lid: {k: r[k] for k in ("name", "direction", "from", "to", "stops")}
                                      for lid, r in routes.items()}
        self.geometry["transit"] = {"headway_s": config.demand()["bus_headway"],
                                    "late_factor": config.agents()["transit"]["late_factor"]}
        for line, first, last in config.bus_lines():
            if line in routes:
                path = [net.getEdge(e) for e in routes[line]["edges"]]
            elif net.hasEdge(first) and net.hasEdge(last):
                path, _ = net.getShortestPath(net.getEdge(first), net.getEdge(last), vClass="bus")
            else:
                path = None
            if path:
                self.lines[line] = [e.getToNode().getID() for e in path
                                    if e.getToNode().getType() == "traffic_light"]
                self.line_edges[line] = [e.getID() for e in path]
        self.geometry["lines"] = self.line_edges

    @staticmethod
    def _place_names(edges, onward):
        """Label each map entry or exit by its street, or by the nearest named street it leads
        into (`onward` = "getOutgoing") or comes from ("getIncoming"); then a compass side."""
        from html import unescape

        def mid(e):
            return e.getShape()[len(e.getShape()) // 2]

        def street(e):
            level = [e]
            for _ in range(5):
                named = sorted(x.getName() for x in level if x.getName())
                if named:
                    return unescape(named[0])
                level = [o for x in level for o in getattr(x, onward)() if not o.getFunction()]
            return "Side street"
        xs = [mid(e)[0] for e in edges] or [0]
        ys = [mid(e)[1] for e in edges] or [0]
        cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
        out, seen = [], {}
        for e in sorted(edges, key=lambda e: (street(e), e.getID())):
            x, y = mid(e)
            side = ("north" if y > cy else "south") if abs(y - cy) > abs(x - cx) else ("east" if x > cx else "west")
            name = f"{street(e)} ({side})"
            seen[name] = seen.get(name, 0) + 1
            out.append({"edge": e.getID(), "name": name if seen[name] == 1 else f"{name} {seen[name]}"})
        return out

    def plan_trip(self, from_edge, to_edge):
        """Fastest route now, its delay vs normal, the alerts on it, and an alternative.
        Uses only the latest snapshot: never touches SUMO from the web thread."""
        snap = self.state()
        tt = {**self.free_tt, **snap.get("edge_tt", {})}
        problems = {}
        for kind in ("incidents", "floods", "congestion"):
            for p in snap.get(kind, []):
                problems.setdefault(p["subject"], []).append(kind[:-1] if kind != "congestion" else "congestion")
        for p in snap.get("floods", []):
            tt[p["subject"]] = 1e6
        t_now, route = shortest(self.graph, from_edge, to_edge, tt)
        if not route:
            return {"error": "no route between these places"}
        t_free = sum(self.free_tt.get(e, 0) for e in route)
        junctions = [self.edge_to[e] for e in route[:-1]]
        alerts = []
        for e in route:
            for kind in problems.get(e, []):
                alerts.append({"kind": kind, "edge": e, "street": self.edge_name[e]})
        for amb in snap.get("ambulances", []):
            hits = [j for j, eta in amb["junctions"] if j in junctions]
            if hits:
                alerts.append({"kind": "ambulance", "vehicle": amb["subject"], "junction": hits[0]})
        if snap.get("weather", {}).get("rain"):
            alerts.append({"kind": "rain", "intensity": snap["weather"]["rain"]})
        alt = None
        avoid = [e for e in route if e in problems and e not in (from_edge, to_edge)]
        if avoid:
            t_alt, alt_route = shortest(self.graph, from_edge, to_edge, tt, avoid)
            if alt_route and alt_route != route:
                alt = {"edges": alt_route, "time_s": round(t_alt), "saving_s": round(t_now - t_alt),
                       "streets": self._streets(alt_route)}
        return {"edges": route, "streets": self._streets(route), "time_s": round(t_now),
                "normal_s": round(t_free), "delay_s": round(t_now - t_free), "junctions": junctions,
                "alerts": alerts, "alternative": alt, "clock": snap.get("clock")}

    def _streets(self, route):
        out = []
        for e in route:
            n = self.edge_name[e]
            if n == e:                                  # unnamed segment: its id means nothing to a driver
                continue
            if not out or out[-1] != n:
                out.append(n)
        return out

    def start(self):
        self.copilot = Copilot(self)
        self.alert_writer = AlertWriter(self)
        self.alert_writer.start()
        self.running = True
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def stop(self):
        """Ask the run to end and wait for it, so the next run gets a free TraCI connection.
        False if the run is still going after 20 s (TraCI is global: no new run may start then)."""
        self._close_intake()
        if hasattr(self, "alert_writer"):
            self.alert_writer.stop()
        thread = getattr(self, "thread", None)
        if thread and thread is not threading.current_thread():
            thread.join(timeout=20)
            return not thread.is_alive()
        return True

    def _close_intake(self):
        """No new events after this. Under the lock, so an enqueue cannot land after the drain."""
        with self.lock:
            self.running = False

    def enqueue_incident(self, edge_id, lane_index, duration_seconds, request_id):
        """Validate on the request thread; enqueue only. TraCI is touched by _simulate only."""
        if edge_id not in self._incident_lanes:
            raise ValueError("Unknown or unsupported road edge")
        if lane_index not in self._incident_lanes[edge_id]:
            raise ValueError("Lane is not a passenger-vehicle lane on this edge")
        if not 10 <= duration_seconds <= 1800:
            raise ValueError("Duration must be between 10 and 1800 simulation seconds")
        request_id = str(request_id)
        signature = (edge_id, lane_index, duration_seconds)
        event = {
            "event_id": str(uuid.uuid4()), "type": "incident", "edge_id": edge_id,
            "lane_index": lane_index, "duration_seconds": duration_seconds,
            "status": "queued", "queued_at": time.time(),
        }
        # Check intake, idempotency, limits and the enqueue under ONE lock: _close_intake and the
        # end-of-run drain take the same lock, so an event is either refused or drained, never stranded.
        with self.lock:
            if not self.running:
                raise ValueError("No running simulation")
            previous = self._event_requests.get(request_id)
            if previous:
                if previous[0] != signature:
                    raise ValueError("Request ID was already used for different event parameters")
                existing = next((e for e in self.world_events if e["event_id"] == previous[1]), None)
                if existing:
                    return copy.deepcopy(existing)
            if len([e for e in self.world_events if e["status"] in ("queued", "applied", "detected")]) >= 20:
                raise ValueError("The active event limit has been reached")
            self.world_events.append(event)
            self.world_events = self.world_events[-100:]
            self._event_requests[request_id] = (signature, event["event_id"])
            try:
                self.event_commands.put_nowait(event["event_id"])
            except queue.Full as exc:
                event["status"] = "rejected"
                event["error"] = "The event queue is full"
                raise ValueError("The event queue is full") from exc
            return copy.deepcopy(event)

    def _apply_queued_events(self, world, now):
        while True:
            try:
                event_id = self.event_commands.get_nowait()
            except queue.Empty:
                break
            with self.lock:
                event = next((e for e in self.world_events if e["event_id"] == event_id), None)
            if not event:
                continue
            try:
                details = world.inject_incident(event, now)
                with self.lock:
                    event.update(details, status="applied")
            except Exception as exc:  # SUMO rejects bad placement or insertion; preserve the reason.
                with self.lock:
                    event.update(status="rejected", error=f"{type(exc).__name__}: {exc}")
            finally:
                self.event_commands.task_done()

    def _update_world_events(self, now):
        incident_messages = self.system.bus.published("INCIDENT")
        by_lane = {(p.details.get("lane"), p.subject) for p in incident_messages}
        vehicles = set(traci.vehicle.getIDList())
        with self.lock:
            for event in self.world_events:
                if event["status"] not in ("applied", "detected"):
                    continue
                target = (f'{event["edge_id"]}_{event["lane_index"]}', event["edge_id"])
                if event.get("detected_at") is None and target in by_lane:
                    event.update(status="detected", detected_at=now)
                expired = now >= event["applied_at"] + event["duration_seconds"]
                seen = event.get("vehicle_id") in vehicles
                if seen:
                    event["vehicle_seen"] = True
                gone = event.get("vehicle_seen", False) and not seen
                if expired or gone:
                    event.update(status="completed", completed_at=now)

    def _cancel_pending_events(self):
        while True:
            try:
                event_id = self.event_commands.get_nowait()
            except queue.Empty:
                break
            with self.lock:
                event = next((e for e in self.world_events if e["event_id"] == event_id), None)
                if event and event["status"] == "queued":
                    event.update(status="cancelled", error="Simulation stopped before event application")
            self.event_commands.task_done()

    def _run(self):
        """Any failure ends as status "error" with a reason the page can show, never a silent hang."""
        try:
            self._simulate()
        except Exception as e:                          # noqa: BLE001 - reported to the operator
            traceback.print_exc()
            closed = type(e).__name__ == "FatalTraCIError"
            if closed and not getattr(self, "sumo_started", False):
                # TraCI never connected: SUMO itself failed to start (for example a missing shared library).
                reason = ("SUMO did not start: no connection to the simulator. The server log shows "
                          "SUMO's own error, such as a missing shared library.")
            elif closed:
                reason = "SUMO stopped (was the SUMO window closed?)."
            else:
                reason = f"{type(e).__name__}: {e}"
            with self.lock:
                self.snapshot = {**self.snapshot, "status": "error", "error": reason}
            self.running = False
            if hasattr(self, "alert_writer"):
                self.alert_writer.stop()

    def _simulate(self):
        net = config.network_files()[0]
        stops = net.replace(".net.xml", ".stops.xml")
        binary = os.path.join(SUMO_HOME, "bin", "sumo-gui" if self.gui else "sumo")
        gui_opts = ["--start", "--quit-on-end", "--delay", "0"] if self.gui else []
        settings = net.replace(".net.xml", ".settings.xml")    # viewport + street-map decal
        if self.gui and os.path.exists(settings):
            gui_opts += ["--gui-settings-file", settings]
        extra = [f for f in (stops, net.replace(".net.xml", ".poi.add.xml") if self.gui else None)
                 if f and os.path.exists(f)]
        _close_traci()                                  # a run that died earlier may have left its connection
        traci.start([binary, "-n", net, "-r", self.routes] + gui_opts
                    + (["-a", ",".join(extra)] if extra else []) + [
                     "--time-to-teleport", "300", "--ignore-route-errors", "true",
                     "--no-step-log", "true", "--no-warnings", "true", "--seed", str(self.seed)])
        self.sumo_started = True                        # from here on, a TraCI error is a mid-run failure
        models = load_models(net)
        start = datetime.strptime(self.meta["start"], "%Y-%m-%d %H:%M")
        self.narrator = Narrator({t: m.name for t, m in models.items()}, self.edge_name, start)
        self.system = TraffixSystem(self.controller, models, net, self.log, start)
        self.system.start(0)
        world = World(self.meta["events"], models, self.system.sensors)
        end = self.meta["duration"]
        max_wall_seconds = float(os.environ.get("TRAFFIX_MAX_RUN_WALL_SECONDS", "3600"))
        deadline = time.monotonic() + max(60, max_wall_seconds)
        try:
            while self.running and traci.simulation.getTime() < end and time.monotonic() < deadline:
                t0 = time.time()
                traci.simulationStep()
                now = traci.simulation.getTime()
                world.step(now)
                self._apply_queued_events(world, now)
                self.system.step(now)
                self._update_world_events(now)
                if int(now) % 5 == 0 or not hasattr(self, "_tt"):
                    sm = self.system.supermaster
                    self._tt = sm.rerouting.travel_times() if sm else self.system.sensors.edge_travel_times()
                if int(now) % 2 == 0 or not hasattr(self, "_next_stops"):
                    self._next_stops = self._bus_next_stops()
                snap = self._snapshot(now, models)
                with self.lock:
                    self.snapshot = snap
                time.sleep(max(0.0, 1.0 / self.speed - (time.time() - t0)))
        finally:
            self._close_intake()                        # also on normal end of run, not only on stop()
            self._cancel_pending_events()
            _close_traci()
            with self.lock:
                if self.snapshot.get("status") != "error":
                    self.snapshot["status"] = "finished"
                    if time.monotonic() >= deadline:
                        self.snapshot["end_reason"] = "Maximum wall-clock run time reached"
                self.snapshot["world_events"] = copy.deepcopy(self.world_events)

    def _bus_next_stops(self):
        """Each bus's remaining stops with the driving distance to them: {bus: [[stop id, metres], ...]}."""
        out = {}
        for v in traci.vehicle.getIDList():
            if traci.vehicle.getTypeID(v) != "bus":
                continue
            rows = []
            for st in traci.vehicle.getStops(v, 8):
                if not st.stoppingPlaceID:
                    continue
                d = traci.vehicle.getDrivingDistance(v, st.lane.rsplit("_", 1)[0], st.endPos)
                if d >= 0:
                    rows.append([st.stoppingPlaceID, round(d)])
            out[v] = rows
        return out

    def _snapshot(self, now, models):
        s, bus = self.system.sensors, self.system.bus
        with self.lock:
            world_events = copy.deepcopy(self.world_events)
        kinds = {"car": "car", "moto": "moto", "bus": "bus", "ambulance": "ambulance",
                 "police": "police", "fire_truck": "fire"}
        vehicles = []
        for v in traci.vehicle.getIDList():
            x, y = traci.vehicle.getPosition(v)
            vt = traci.vehicle.getTypeID(v)
            vehicles.append({"id": v, "x": round(x, 1), "y": round(y, 1),
                             "kind": "incident" if v.startswith("incident_") else kinds.get(vt, "car"),
                             "angle": round(traci.vehicle.getAngle(v)),
                             "line": traci.vehicle.getLine(v) if vt == "bus" else "",
                             "speed": round(traci.vehicle.getSpeed(v), 1)})
        people = []
        for p in traci.person.getIDList()[:800]:
            x, y = traci.person.getPosition(p)
            people.append([round(x, 1), round(y, 1), 1 if traci.person.getTypeID(p) == "ped_slow" else 0])
        signals = {}
        for tls, m in models.items():
            state = traci.trafficlight.getRedYellowGreenState(tls)
            per_edge = {}
            for l in m.vehicle_links:
                c = state[l.index]
                cur = per_edge.get(l.in_edge, "r")
                per_edge[l.in_edge] = "G" if c in "Gg" or cur == "G" else "y" if c in "yY" or cur == "y" else "r"
            signals[tls] = per_edge
        junctions = []
        for tls, st in bus.status.items():
            m = models[tls]
            junctions.append({
                "id": tls, "name": m.name, "mode": st["mode"], "queue": st["queue_total"],
                "preempt": st["preempt"],
                "crossings": [{"id": c, "walk": m.crossing_green(st["green"], c),
                               "waiting": s.waiting_at.get(c, (0, 0))[0],
                               "longest_wait": round(s.waiting_at.get(c, (0, 0))[1]),
                               "on_crossing": len(s.on_crossing.get(c, []))} for c in m.crossings]})
        pubs = lambda k: [{"subject": p.subject, "t": p.t, **p.details} for p in bus.published(k)]
        return {
            "status": "running", "scenario": self.scenario, "controller": self.controller,
            "seed": self.seed, "t": now,
            "world_events": world_events,
            "clock": self.system.ctx.clock(now).strftime("%Y-%m-%d %H:%M:%S"),
            "duration": self.meta["duration"], "junctions": junctions, "vehicles": vehicles, "people": people,
            "signals": signals,
            "incidents": pubs("INCIDENT"), "floods": pubs("FLOOD"), "route_b": pubs("ROUTE_B"),
            "congestion": pubs("CONGESTION"), "ambulances": pubs("AMBULANCE_ROUTE"),
            "edge_tt": {e: round(min(v, 1e5), 1) for e, v in self._tt.items()},
            "lines": self.lines,
            "bus_next_stops": self._next_stops,
            "stale": pubs("DATA_STALE"), "weather": s.weather, "forecast": bus.forecast,
            "buses": self.system.supermaster.transit.state if self.system.supermaster else {},
            "notifications": bus.notifications[-150:],
            "decisions": self.narrator.enrich(self.log.entries[-60:]),
            "emergency_decisions": self.narrator.enrich([e for e in self.log.entries[-3000:]
                                                         if e["reason"].startswith(("EMERGENCY", "RECOVER"))][-40:]),
            "transit_decisions": self.narrator.enrich([e for e in self.log.entries[-3000:]
                                                       if e["reason"].startswith(("TRANSIT", "BUS_"))][-150:]),
            "counts": {"vehicles": len(vehicles), "pedestrians": traci.person.getIDCount(),
                       "decisions": len(self.log.entries)}}

    def state(self):
        with self.lock:
            return dict(self.snapshot)
