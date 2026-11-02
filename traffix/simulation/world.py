"""
Scenario events: things that happen TO the city, not decisions about it.
  incident      a stalled vehicle blocks one lane
  sensor_fault  one junction's incoming detectors freeze
  rain          drivers slow down and keep longer gaps; pedestrians slow down
  flood         a road becomes impassable (drivers who see it detour)
They change the simulated world and the weather feed, never a traffic light.
"""
from .backend import traci

STALL_ID = "incident_stall"
VEHICLE_TYPES = ("car", "moto", "bus", "ambulance")


class World:
    def __init__(self, events, models, sensors=None):
        self.ev = events or {}
        self.models, self.sensors = models, sensors
        self.done = set()
        self.rain = 0.0
        self.base = {}

    def _once(self, key, now, at):
        if key not in self.done and now >= at:
            self.done.add(key)
            return True
        return False

    def step(self, now):
        inc = self.ev.get("incident")
        if inc and self._once("incident", now, inc["at"]):
            traci.route.add("incident_route", [inc["edge"]])
            pos = traci.lane.getLength(f'{inc["edge"]}_{inc["lane"]}') * 0.6
            traci.vehicle.add(STALL_ID, "incident_route", typeID="car", depart="now",
                              departLane=str(inc["lane"]), departPos=str(pos - 10), departSpeed="0")
            traci.vehicle.setStop(STALL_ID, inc["edge"], pos=pos, laneIndex=inc["lane"],
                                  duration=inc["duration"])

        fault = self.ev.get("sensor_fault")
        if fault and self.sensors and self._once("fault", now, fault["at"]):
            self.sensors.freeze(self.models[fault["tls"]].incoming_lanes,
                                until=fault["at"] + fault["duration"])

        rain = self.ev.get("rain")
        if rain:
            if self._once("rain", now, rain["at"]):
                self._set_rain(rain["intensity"])
            if "heavy_at" in rain and self._once("heavy", now, rain["heavy_at"]):
                self._set_rain(rain.get("heavy_intensity", 1.0))
            if "flood_edge" in rain and self._once("flood", now, rain["flood_at"]):
                self._flood(rain["flood_edge"])

    def inject_incident(self, event, now):
        """Create a uniquely named stopped vehicle. Called only by the SUMO owner thread."""
        event_id = event["event_id"].replace("-", "")
        vehicle_id = f"incident_{event_id}"
        route_id = f"incident_route_{event_id}"
        edge, lane = event["edge_id"], event["lane_index"]
        lane_id = f"{edge}_{lane}"
        length = traci.lane.getLength(lane_id)
        if length < 20:
            raise ValueError("Selected lane is too short for a safe incident placement")
        stop_pos = min(length - 2, max(12, length * 0.6))
        depart_pos = max(0, stop_pos - 8)
        route_added = False
        vehicle_added = False
        try:
            traci.route.add(route_id, [edge])
            route_added = True
            traci.vehicle.add(vehicle_id, route_id, typeID="car", depart="now",
                              departLane=str(lane), departPos=str(depart_pos), departSpeed="0")
            vehicle_added = True
            traci.vehicle.setStop(vehicle_id, edge, pos=stop_pos, laneIndex=lane,
                                  duration=event["duration_seconds"])
        except Exception:
            if vehicle_added:
                try:
                    traci.vehicle.remove(vehicle_id)
                except Exception:
                    pass
            if route_added:
                try:
                    traci.route.remove(route_id)
                except Exception:
                    pass
            raise
        return {"vehicle_id": vehicle_id, "applied_at": now}

    def _set_rain(self, intensity):
        """Rain: lower desired speed, longer reaction gaps, gentler braking."""
        for vt in VEHICLE_TYPES:
            if vt not in self.base:
                self.base[vt] = (traci.vehicletype.getSpeedFactor(vt), traci.vehicletype.getTau(vt),
                                 traci.vehicletype.getDecel(vt))
            sf, tau, dec = self.base[vt]
            traci.vehicletype.setSpeedFactor(vt, sf * (1 - 0.2 * intensity))
            traci.vehicletype.setTau(vt, tau * (1 + 0.6 * intensity))
            traci.vehicletype.setDecel(vt, dec * (1 - 0.3 * intensity))
        for pt in ("ped_normal", "ped_slow"):
            if pt not in self.base:
                self.base[pt] = traci.vehicletype.getMaxSpeed(pt)
            traci.vehicletype.setMaxSpeed(pt, self.base[pt] * (1 - 0.15 * intensity))
        self.rain = intensity
        if self.sensors:
            self.sensors.weather["rain"] = intensity

    def _flood(self, edge):
        n = traci.edge.getLaneNumber(edge)
        for i in range(n):
            traci.lane.setDisallowed(f"{edge}_{i}", ["passenger", "motorcycle", "bus", "emergency"])
        traci.edge.adaptTraveltime(edge, 1e5)
        for v in traci.vehicle.getIDList():                 # drivers who see it detour
            try:
                rest = traci.vehicle.getRoute(v)[traci.vehicle.getRouteIndex(v) + 1:]
                if edge in rest:
                    traci.vehicle.rerouteTraveltime(v, currentTravelTimes=False)
            except traci.TraCIException:
                pass
        if self.sensors:
            self.sensors.weather["flood_alerts"].append(edge)
