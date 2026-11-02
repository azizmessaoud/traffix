"""
Builds the traffic for one scenario and seed: cars, motorcycles, buses,
pedestrians, ambulances, plus the hidden events file.

Trip types (direction follows the calendar's inbound share):
  through   enter at the edge of the map, leave at the edge
  inbound   enter at the edge, end inside the centre
  outbound  start inside the centre, leave at the edge
"""
import json
import os
import random
from datetime import datetime, timedelta

try:                                     # needed to build a network, not to import this module
    import sumolib
except ImportError:
    sumolib = None

from ..core import config
from .calendar_model import CalendarModel

VTYPES = """  <vType id="car" vClass="passenger" sigma="0.5" color="200,200,200"/>
  <vType id="moto" vClass="motorcycle" sigma="0.6" color="240,170,60"/>
  <vType id="bus" vClass="bus" color="40,120,220"/>
  <vType id="ambulance" vClass="emergency" guiShape="emergency" speedFactor="1.3" color="255,40,40"/>
  <vType id="police" vClass="emergency" guiShape="police" speedFactor="1.3" color="40,90,255"/>
  <vType id="fire_truck" vClass="emergency" guiShape="firebrigade" length="9" speedFactor="1.2" color="255,110,30"/>
  <vType id="ped_normal" vClass="pedestrian" speed="{n}"/>
  <vType id="ped_slow" vClass="pedestrian" speed="{s}" color="255,0,255"/>
"""


def parse_start(text, cal):
    """'2026-10-13 08:00' or '2026-03-05 sunset-01:45'."""
    day, clock = text.split()
    if clock.startswith("sunset"):
        h, m = clock.split("-")[1].split(":")
        d = datetime.strptime(day, "%Y-%m-%d")
        minutes = cal.sunset(d.date()) - int(h) * 60 - int(m)
        return d + timedelta(minutes=round(minutes))
    return datetime.strptime(text, "%Y-%m-%d %H:%M")


def classify_edges(net):
    entries, exits, inner = [], [], []
    for e in net.getEdges():
        if e.getFunction() or not e.allows("passenger"):
            continue
        frm, to = e.getFromNode(), e.getToNode()
        is_entry = all(i.getFromNode() == to for i in frm.getIncoming() if not i.getFunction())
        is_exit = all(o.getToNode() == frm for o in to.getOutgoing() if not o.getFunction())
        if is_entry:
            entries.append(e)
        elif is_exit:
            exits.append(e)
        else:
            inner.append(e)
    return entries, exits, inner


def poisson(rng, rate_fn, duration):
    peak = max(rate_fn(t) for t in range(0, duration, 60)) or 1e-6
    t, out = 0.0, []
    while True:
        t += rng.expovariate(peak / 3600.0)
        if t >= duration:
            return out
        if rng.random() < rate_fn(t) / peak:
            out.append(t)


# Paint mix of cars in Tunis traffic, the same mix and the same pick per vehicle id as the web map
# (frontend NetworkMap.jsx CAR_PAINTS), so sumo-gui and the browser show each car in one colour.
CAR_PAINTS = [("244,244,242", 28), ("184,190,196", 18), ("107,113,120", 11), ("29,33,38", 12),
              ("247,198,0", 13), ("158,42,43", 6), ("45,79,138", 6), ("216,205,180", 4), ("63,107,74", 2)]


def _paint(xml):
    """Give a car trip its colour: FNV-1a hash of the id, as in the web map."""
    if ' type="car"' not in xml:
        return xml
    vid = xml.split('id="', 1)[1].split('"', 1)[0]
    h = 2166136261
    for ch in vid:
        h = ((h ^ ord(ch)) * 16777619) & 0xFFFFFFFF
    r = h % sum(w for _, w in CAR_PAINTS)
    for color, w in CAR_PAINTS:
        r -= w
        if r < 0:
            return xml.replace(' type="car"', f' type="car" color="{color}"', 1)
    return xml


def net_digest(net_file):
    """Fingerprint of a network file: traffic built for an older build of the same map
    may drive on edges that no longer exist."""
    import hashlib
    with open(net_file, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()[:16]


class DemandGenerator:
    def __init__(self, net_file):
        self.network = os.path.basename(net_file).replace(".net.xml", "")
        self.digest = net_digest(net_file)
        self.net =sumolib.net.readNet(net_file, withPedestrianConnections=True)
        self.entries, self.exits, self.inner = classify_edges(self.net)
        self.walk_edges = [e for e in self.net.getEdges()
                           if not e.getFunction() and e.allows("pedestrian")]
        self.cal = CalendarModel()
        self.stops = {}                                   # edge -> bus stop id
        stops_file = net_file.replace(".net.xml", ".stops.xml")
        if os.path.exists(stops_file):
            import xml.etree.ElementTree as ET
            for b in ET.parse(stops_file).getroot().findall("busStop"):
                self.stops[b.get("lane").rsplit("_", 1)[0]] = b.get("id")
        self.dwell = config.simulation().get("bus_stop_dwell", 20)
        self.d = config.demand()
        self._paths = {}                                  # (edge, vclass) -> edges reachable from it
        self._next = {}                                   # vclass -> {edge: edges the router may step to}
        self._walk_components = None                      # pedestrian: edge -> its shared connected component

    def _reachable(self, a, vclass):
        """Every edge a `vclass` trip can reach from `a`: the edges sumolib's router would search
        (allowed successors; walkers may also go against the direction). One search per start
        edge instead of one shortest-path search per trip."""
        if vclass == "pedestrian":
            return self._walk_component(a)
        key = (a, vclass)
        if key not in self._paths:
            nxt = self._successors(vclass)
            seen, todo = {a}, [a]
            while todo:
                for n in nxt.get(todo.pop(), ()):
                    if n not in seen:
                        seen.add(n)
                        todo.append(n)
            self._paths[key] = seen
        return self._paths[key]

    def _walk_component(self, a):
        """Walkers may go both ways along every edge, so reachability is symmetric: the set is the
        edge's connected component. One shared set per component keeps memory linear in the network;
        a search per start edge kept a full-network set for each edge (MemoryError on Tunis)."""
        if self._walk_components is None:
            nxt = self._successors("pedestrian")
            self._walk_components = {}
            for start in nxt:
                if start in self._walk_components:
                    continue
                comp, todo = {start}, [start]
                while todo:
                    for n in nxt.get(todo.pop(), ()):
                        if n not in comp:
                            comp.add(n)
                            todo.append(n)
                for e in comp:
                    self._walk_components[e] = comp
        return self._walk_components.get(a, {a})

    def _successors(self, vclass):
        if vclass not in self._next:
            walk = vclass == "pedestrian"
            nxt = {}
            for e in self.net.getEdges(withInternal=True):
                nxt[e] = list(e.getAllowedOutgoing(vclass))
                if walk:
                    nxt[e] += list(e.getIncoming())
                    if not self.net.hasWalkingArea and e.getFunction() == "":
                        nxt[e] += [i for i in e.getToNode().getIncoming() if i.getFunction() == ""]
            self._next[vclass] = nxt
        return self._next[vclass]

    def _ok(self, a, b, vclass="passenger"):
        if a == b or b.getToNode() == a.getFromNode():
            return False
        return b in self._reachable(a, vclass)

    def _pick(self, rng, kind, towards=None):
        for _ in range(40):
            if kind == "through":
                a, b = rng.choice(self.entries), rng.choice(self.exits)
            elif kind == "inbound":
                a, b = rng.choice(self.entries), rng.choice(towards or self.inner)
            else:
                a, b = rng.choice(self.inner), rng.choice(self.exits)
            if self._ok(a, b):
                return a, b
        return None

    def build(self, name, scen, seed, out_dir):
        os.makedirs(out_dir, exist_ok=True)
        rng = random.Random(f"{name}-{seed}")
        start = parse_start(scen["start"], self.cal)
        duration = int(scen.get("duration", 3600))
        mult = float(scen.get("demand_multiplier", 1.0))
        events = scen.get("events", {}) or {}
        d = self.d

        def at(t):
            return self.cal.level(start + timedelta(seconds=t))

        items = []
        # vehicles
        for i, t in enumerate(poisson(rng, lambda t: d["base_vehicles_per_hour"] * at(t)[0] * mult,
                                      duration)):
            _, share, _ = at(t)
            r = rng.random()
            kind = "through" if r < d["through_share"] else (
                "inbound" if rng.random() < share else "outbound")
            pair = self._pick(rng, kind)
            if not pair:
                continue
            vt = "moto" if rng.random() < d["motorcycle_share"] else "car"
            items.append((t, f'  <trip id="veh{i}" type="{vt}" depart="{t:.1f}" from="{pair[0].getID()}" '
                             f'to="{pair[1].getID()}" departLane="best"><param key="kind" value="{kind}"/></trip>'))
        # demand surge towards one junction
        if "surge" in events:
            s = events["surge"]
            node = self.net.getNode(s["towards"])
            targets = [e for e in node.getIncoming() if e in self.inner] or self.inner
            for k in range(s["extra_vehicles"]):
                t = s["at"] + rng.uniform(0, s["duration"])
                pair = self._pick(rng, "inbound", targets)
                if pair:
                    items.append((t, f'  <trip id="surge{k}" type="car" depart="{t:.1f}" from="{pair[0].getID()}" '
                                     f'to="{pair[1].getID()}" departLane="best"/>'))
        # buses
        delay = events.get("bus_delay")
        routes = config.line_routes(self.net)
        for line, first, last in config.bus_lines():
            if line in routes:                           # real route and stops (e.g. TRANSTU lines)
                edges = " ".join(routes[line]["edges"])
                stops = "".join(f'<stop busStop="{s}" duration="{self.dwell}"/>' for s in routes[line]["stops"])
            else:
                if not (self.net.hasEdge(first) and self.net.hasEdge(last)):
                    continue
                p, _ = self.net.getShortestPath(self.net.getEdge(first), self.net.getEdge(last), vClass="bus")
                if p is None:
                    continue
                edges = " ".join(e.getID() for e in p)
                stops = "".join(f'<stop busStop="{self.stops[e.getID()]}" duration="{self.dwell}"/>'
                                for e in p if e.getID() in self.stops)
            off = rng.uniform(0, d["bus_headway"])
            k = 0
            while off + k * d["bus_headway"] < duration:
                sched = off + k * d["bus_headway"]
                dep = sched + abs(rng.gauss(0, d["bus_delay_sd"]))
                if delay and delay["line"] == line and k >= delay.get("from_bus", 0):
                    dep += delay["delay"]
                if dep < duration:
                    items.append((dep, f'  <vehicle id="bus_{line}_{k}" type="bus" depart="{dep:.1f}" line="{line}">'
                                       f'<param key="scheduled" value="{sched:.1f}"/><route edges="{edges}"/>{stops}</vehicle>'))
                k += 1
        # pedestrians
        for i, t in enumerate(poisson(rng, lambda t: d["pedestrians_per_hour"] * at(t)[0] * at(t)[2] * mult,
                                      duration)):
            for _ in range(30):
                a, b = rng.sample(self.walk_edges, 2)
                if self._ok(a, b, "pedestrian"):
                    break
            else:
                continue
            pt = "ped_slow" if rng.random() < d["slow_walker_share"] else "ped_normal"
            items.append((t, f'  <person id="ped{i}" type="{pt}" depart="{t:.1f}">'
                             f'<walk from="{a.getID()}" to="{b.getID()}"/></person>'))
        # emergency services: ambulances, police cars, fire trucks
        for key, vtype in (("ambulances", "ambulance"), ("police", "police"), ("fire_trucks", "fire_truck")):
            if key not in events:
                continue
            n = events[key]["count"]
            prefix = {"ambulance": "ambulance", "police": "police", "fire_truck": "fire"}[vtype]
            for i in range(n):
                t = (i + rng.uniform(0.2, 0.8)) * duration / n
                pair = self._pick(rng, "through")
                if pair:
                    items.append((t, f'  <trip id="{prefix}{i}" type="{vtype}" depart="{t:.1f}" '
                                     f'from="{pair[0].getID()}" to="{pair[1].getID()}" departLane="best"/>'))

        items.sort(key=lambda x: x[0])
        items = [(t, _paint(x)) for t, x in items]
        base = os.path.join(out_dir, f"{name}_seed{seed}")
        with open(base + ".rou.xml", "w") as f:
            f.write("<routes>\n" + VTYPES.format(n=d["normal_walker_speed"], s=d["slow_walker_speed"])
                    + "\n".join(x for _, x in items) + "\n</routes>\n")
        meta = {"scenario": name, "seed": seed, "network": self.network, "net_digest": self.digest, "start": start.strftime("%Y-%m-%d %H:%M"),
                "duration": duration, "events": events,
                "vehicles": sum(1 for _, x in items if "<trip" in x or "<vehicle" in x)}
        with open(base + ".events.json", "w") as f:
            json.dump(meta, f, indent=1)
        return base + ".rou.xml", meta
