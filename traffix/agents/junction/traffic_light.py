"""
Traffic light agent (one per junction). PROPOSES the normal phase; the master decides.

Modes (chosen by the master from data health):
  max_pressure  pressure = queued vehicles on approach - queued vehicles downstream,
                + waiting pedestrians, + corridor bias for platoons on their way
  actuated      needs incoming lanes only (downstream data stale)
  fixed         needs no data (incoming data stale)

Learned part: the max-pressure parameters (pedestrian weight, switching margin)
are tuned by training/tune_traffic_light.py and saved in models/.
Neighbour link: downstream queues come from the neighbouring master's status
when it is fresh, otherwise from this junction's own sensors.
"""
import json
import os

from ...core import config
from ..base import Agent


class TrafficLightAgent(Agent):
    name = "traffic_light"

    def __init__(self, ctx, tls, master):
        super().__init__(ctx, tls)
        self.master, self.m = master, ctx.models[tls]
        self.p = dict(self.cfg["traffic_light"])
        tuned = config.path(self.cfg["models_dir"], "traffic_light_params.json")
        if ctx.use_models and os.path.exists(tuned):
            self.p.update(json.load(open(tuned)))
        self.last_arrival = 0.0

    def _downstream(self, lane):
        for st in self.bus.status.values():
            q = st.get("incoming_queue", {})
            if lane in q and self.sensors.now - st["t"] <= 2:
                return q[lane]                         # told by the neighbouring master
        r = self.sensors.lane(lane)
        return r.halting if self.p["downstream_queued_only"] else r.vehicles

    def pressure(self, phase):
        p = 0.0
        bias = {d.subject: d.details["weight"] for d in self.bus.inbox(self.tls, self.sensors.now,
                                                                         "CORRIDOR_BIAS")}
        served_edges = set()
        for l in self.m.vehicle_links:
            if phase[l.index] in "Gg":
                p += self.sensors.lane(l.in_lane).halting - self._downstream(l.out_lane)
                served_edges.add(l.in_edge)
        p += sum(w for e, w in bias.items() if e in served_edges)
        if self.ctx.bus_first:                         # people, not vehicles: weigh nearby buses
            bf = self.cfg["bus_first"]
            p += bf["bus_weight"] * sum(
                1 for v in self.sensors.approaching.get(self.tls, [])
                if v.kind == "bus" and v.distance <= bf["detect_distance"] and phase[v.link_index] in "Gg")
        for c in self.m.crossings:
            if self.m.crossing_green(phase, c):
                p += self.p["ped_weight"] * self.sensors.waiting_at.get(c, (0, 0))[0]
        return p

    def _demand(self, phase):
        lanes = {l.in_lane for l in self.m.vehicle_links if phase[l.index] in "Gg"}
        return sum(self.sensors.lane(l).halting for l in lanes) + sum(
            self.sensors.waiting_at.get(c, (0, 0))[0]
            for c in self.m.crossings if self.m.crossing_green(phase, c))

    def _next(self, cur):
        ph = self.m.green_phases
        return ph[(ph.index(cur) + 1) % len(ph)] if cur in ph else ph[0]

    def step(self, now):
        st, mode = self.master.signal_status(), self.master.mode
        green, tg = st["green"], st["time_in_green"]
        if st["busy"] or tg < self.cfg["safety"]["min_green"]:
            return
        if mode == "max_pressure":
            pr = {ph: self.pressure(ph) for ph in self.m.green_phases}
            best = max(pr, key=pr.get)
            if best != green and pr[best] > pr.get(green, 0) + self.p["switch_margin"]:
                corridor = bool(self.bus.inbox(self.tls, now, "CORRIDOR_BIAS"))
                self.send("PROPOSAL", self.tls, now, subject=best,
                          reason="CORRIDOR_PLATOON" if corridor else "MAX_PRESSURE_SWITCH",
                          pressure_new=round(pr[best], 1), pressure_old=round(pr.get(green, 0), 1))
        elif mode == "actuated":
            lanes = {l.in_lane for l in self.m.vehicle_links if green[l.index] in "Gg"}
            if any(self.sensors.lane(l).vehicles > self.sensors.lane(l).halting for l in lanes):
                self.last_arrival = now
            gap = now - self.last_arrival >= self.p["actuated_gap"]
            maxed = tg >= self.p["actuated_max_green"]
            if gap or maxed:
                nxt = self._next(green)
                for _ in self.m.green_phases:
                    if self._demand(nxt) > 0 or nxt == green:
                        break
                    nxt = self._next(nxt)
                if nxt != green:
                    self.send("PROPOSAL", self.tls, now, subject=nxt,
                              reason="ACTUATED_MAX_OUT" if maxed else "ACTUATED_GAP_OUT", green_s=tg)
        elif tg >= self.p["fallback_fixed_green"]:
            self.send("PROPOSAL", self.tls, now, subject=self._next(green), reason="FIXED_CYCLE",
                      green_s=tg)
