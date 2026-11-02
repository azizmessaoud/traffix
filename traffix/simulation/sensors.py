"""
Sensor layer: the ONLY way agents see the simulation. Read-only.

Every lane reading carries the time it was measured, so agents can tell fresh
data from stale. A frozen detector (world.py injects these) keeps returning its
last reading with its old timestamp. The weather feed plays the role of an
external weather service; world.py fills it during rain scenarios.
"""
from dataclasses import dataclass
from html import unescape

try:                                     # SUMO is needed to read a network, not to import this module
    import sumolib
except ImportError:
    sumolib = None

from .backend import traci


@dataclass
class LaneReading:
    lane: str
    t: float
    halting: int
    vehicles: int
    speed: float
    occupancy: float
    length: float
    isolated_stops: int = 0
    last_change: float = 0.0     # when the values last changed
    ids: tuple = ()              # vehicles on the lane (camera / connected-vehicle data)
    approach: tuple = ()         # (distance to stop line, speed) of moving vehicles

    def age(self, now):
        return now - self.t


@dataclass
class PriorityVehicle:
    id: str
    kind: str          # "emergency" | "bus"
    tls: str
    link_index: int
    distance: float
    speed: float
    lane_halting: int
    line: str = ""
    upcoming: tuple = ()     # [(tls, link, distance), ...] further along the route


class SensorLayer:
    def __init__(self, models, net_file):
        self.models = models
        self.lanes = sorted({l for m in models.values() for l in m.incoming_lanes + m.outgoing_lanes})
        self.readings, self.frozen = {}, {}
        self.crossing_edges = sorted({c for m in models.values() for c in m.crossings})
        self.crossing_tls = {c: m.id for m in models.values() for c in m.crossings}
        self.on_crossing, self.waiting_at, self.approaching = {}, {}, {}
        self.weather = {"rain": 0.0, "flood_alerts": []}
        self.now = 0.0
        net = sumolib.net.readNet(net_file)
        self.graph = {e.getID(): [o.getID() for o in e.getOutgoing()]
                      for e in net.getEdges() if not e.getFunction()}
        self.edge_length = {e.getID(): e.getLength() for e in net.getEdges() if not e.getFunction()}
        self.edge_to_node = {e.getID(): e.getToNode().getID() for e in net.getEdges()
                             if not e.getFunction()}
        self.edge_from_node = {e.getID(): e.getFromNode().getID() for e in net.getEdges()
                               if not e.getFunction()}
        self.edge_name = {e.getID(): unescape(e.getName()) for e in net.getEdges()
                          if not e.getFunction() and e.getName()}

    def freeze(self, lanes, until):
        for l in lanes:
            self.frozen[l] = until

    def update(self, now):
        self.now = now
        for lane in self.lanes:
            if lane in self.frozen and now < self.frozen[lane] and lane in self.readings:
                continue
            length = traci.lane.getLength(lane)
            halting = traci.lane.getLastStepHaltingNumber(lane)
            vals = (halting, traci.lane.getLastStepVehicleNumber(lane),
                    round(traci.lane.getLastStepMeanSpeed(lane), 1))
            old = self.readings.get(lane)
            changed = old is None or (old.halting, old.vehicles, round(old.speed, 1)) != vals
            ids = tuple(traci.lane.getLastStepVehicleIDs(lane))
            approach = tuple((round(length - traci.vehicle.getLanePosition(v), 1), round(sp, 1))
                             for v in ids if (sp := traci.vehicle.getSpeed(v)) >= 0.1)
            self.readings[lane] = LaneReading(
                lane, now, vals[0], vals[1], traci.lane.getLastStepMeanSpeed(lane),
                traci.lane.getLastStepOccupancy(lane) / 100.0, length,
                self._isolated(lane, length) if halting else 0,
                now if changed else old.last_change, ids, approach)

        self.on_crossing = {c: [] for c in self.crossing_edges}
        waiting = {c: [0, 0.0] for c in self.crossing_edges}
        for p in traci.person.getIDList():
            road = traci.person.getRoadID(p)
            if road in self.on_crossing:
                self.on_crossing[road].append((p, traci.person.getSpeed(p)))
            elif road.startswith(":") and traci.person.getSpeed(p) < 0.1:
                nxt = traci.person.getNextEdge(p)
                if nxt in waiting:
                    waiting[nxt][0] += 1
                    waiting[nxt][1] = max(waiting[nxt][1], traci.person.getWaitingTime(p))
        self.waiting_at = {c: tuple(v) for c, v in waiting.items()}

        self.approaching = {t: [] for t in self.models}
        for v in traci.vehicle.getIDList():
            vclass = traci.vehicle.getVehicleClass(v)
            if vclass not in ("emergency", "bus"):
                continue
            nxt = [x for x in traci.vehicle.getNextTLS(v) if x[0] in self.models]
            if not nxt:
                continue
            tls, idx, dist, _ = nxt[0]
            lane = traci.vehicle.getLaneID(v)
            self.approaching[tls].append(PriorityVehicle(
                v, "emergency" if vclass == "emergency" else "bus", tls, idx, dist,
                traci.vehicle.getSpeed(v),
                self.readings[lane].halting if lane in self.readings else 0,
                traci.vehicle.getLine(v) if vclass == "bus" else "",
                tuple((t, i, d) for t, i, d, _ in nxt[1:])))

    @staticmethod
    def _isolated(lane, length):
        # a bus waiting at its stop is not a blocked lane: the camera can tell them apart
        stopped = sorted(length - traci.vehicle.getLanePosition(v)
                         for v in traci.lane.getLastStepVehicleIDs(lane)
                         if traci.vehicle.getSpeed(v) < 0.1 and not traci.vehicle.isAtBusStop(v))
        end, n = 0.0, 0
        for dist in stopped:
            if dist - end > 15.0:
                n += 1
            end = dist + 7.5
        return n

    def lane(self, lane):
        return self.readings[lane]

    def edge_travel_times(self):
        return {e: traci.edge.getTraveltime(e) for e in self.graph}

    def vehicles_planning(self, edge, limit=30):
        out = []
        for v in traci.vehicle.getIDList():
            if traci.vehicle.getVehicleClass(v) != "passenger":
                continue
            rest = list(traci.vehicle.getRoute(v)[max(traci.vehicle.getRouteIndex(v), 0):])
            if edge in rest[1:]:
                out.append((v, rest))
                if len(out) >= limit:
                    break
        return out
