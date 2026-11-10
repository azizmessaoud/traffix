"""
Transit monitoring agent (network). Tracks every bus line and decides which buses are late.

Records when each bus passes each junction, computes the gap to the previous
bus of the same line, and publishes TRANSIT_LATE for late buses (the junction
transit agents use this). Learned (models/bus_lateness.joblib): predicts the
gap a bus will have at its next junction, so lateness is flagged earlier.
Also keeps the live line state for the bus driver and passenger pages.
"""
from ...core import config
from ...core.messages import Message
from ..base import Agent


class TransitMonitorAgent(Agent):
    name = "transit_monitor"
    model_file = "bus_lateness.joblib"

    def __init__(self, ctx):
        super().__init__(ctx)
        self.headway = config.demand()["bus_headway"]
        self.factor = self.cfg["transit"]["late_factor"]
        self.prev, self.last_pass, self.state = {}, {}, {}

    def step(self, now):
        on_road = {v.id for vs in self.sensors.approaching.values() for v in vs}
        for b in [b for b in self.state if b not in on_road]:
            del self.state[b]                          # bus left the network
        tracked = []                                   # (tls, bus, gap) for buses with a reference
        for tls, vehicles in self.sensors.approaching.items():
            cur = {v.id: v for v in vehicles if v.kind == "bus"}
            for b, line in self.prev.get(tls, {}).items():
                if b not in cur:
                    self.last_pass[(tls, line)] = now
            self.prev[tls] = {b: v.line for b, v in cur.items()}
            for v in cur.values():
                last = self.last_pass.get((tls, v.line))
                if last is None:                       # no reference yet: track, never "late"
                    self.state[v.id] = {"line": v.line, "next_junction": tls, "gap_s": None, "late": False,
                                        "distance_m": round(v.distance), "speed": round(v.speed, 1),
                                        "upcoming": [[tls, round(v.distance)]] + [[t, round(d)] for t, _, d in v.upcoming]}
                    continue
                tracked.append((tls, v, now - last))
        # one batched prediction per step: single-row predict calls dominated run time
        if self.model is not None and tracked:
            preds = [float(p) for p in self.model.predict(
                [[gap, v.distance, v.speed, v.lane_halting] for _, v, gap in tracked])]
        else:
            preds = [gap for _, _, gap in tracked]
        for (tls, v, gap), pred in zip(tracked, preds):
            late = pred > self.factor * self.headway
            self.state[v.id] = {"line": v.line, "next_junction": tls, "gap_s": round(gap),
                                "late": late, "distance_m": round(v.distance),
                                "speed": round(v.speed, 1),
                                "upcoming": [[tls, round(v.distance)]] + [[t, round(d)] for t, _, d in v.upcoming]}
            self.bus.publish(Message(self.label, "TRANSIT_STATUS", "all", now, now + 60, v.id,
                                     details=self.state[v.id]))
            if late:
                self.bus.publish(Message(self.label, "TRANSIT_LATE", "all", now, now + 60, v.id,
                                         details={"gap": round(gap, 1), "line": v.line}))
            else:
                self.bus.unpublish("TRANSIT_LATE", v.id)
