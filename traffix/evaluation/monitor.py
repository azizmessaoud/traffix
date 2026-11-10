"""
Evaluation monitor: measures what each persona cares about, identically for
every controller (fixed, actuated, TraffiX). Read-only; not part of control.

  Ferjani  pedestrian mean/P95/max wait, clearance truncations
  Faycel   completed vs unfinished trips, P95/max duration, stops
  Mamadou  bus headway variation, share of long gaps
  Touhami  ambulance travel time and delay, delay to other traffic
"""
import statistics
import xml.etree.ElementTree as ET
from collections import defaultdict

from ..core import config
from ..simulation.backend import traci
from ..simulation.world import STALL_ID

LATE_FACTOR = config.agents()["transit"]["late_factor"]
HEADWAY = config.demand()["bus_headway"]


def p95(xs):
    if not xs:
        return 0.0
    s = sorted(xs)
    return s[min(len(s) - 1, int(0.95 * len(s)))]


class Monitor:
    def __init__(self, models):
        self.models = models
        self.prev_state = {}
        self.ped_wait = defaultdict(float)
        self.ped_type = {}
        self.truncations = 0
        self.truncations_slow = 0
        self.buses = {}                    # bus id -> checkpoint edge
        self.bus_line = {}
        self.bus_passes = defaultdict(list)

    def step(self, now):
        for p in traci.person.getIDList():
            if p not in self.ped_type:
                self.ped_type[p] = traci.person.getTypeID(p)
            if traci.person.getSpeed(p) < 0.1:
                self.ped_wait[p] += 1

        # a conflicting vehicle green starting while someone is on the crossing
        for tls, m in self.models.items():
            state = traci.trafficlight.getRedYellowGreenState(tls)
            prev = self.prev_state.get(tls)
            if prev and prev != state:
                newly = {i for i, (a, b) in enumerate(zip(prev, state))
                         if b in "Gg" and a not in "Gg" and m.links[i] and not m.links[i].is_crossing}
                for crossing, conf in m.conflicts.items():
                    if newly & set(conf):
                        for person in traci.edge.getLastStepPersonIDs(crossing):
                            self.truncations += 1
                            if self.ped_type.get(person) == "ped_slow":
                                self.truncations_slow += 1
            self.prev_state[tls] = state

        for v in traci.simulation.getDepartedIDList():
            if v.startswith("bus_"):
                route = traci.vehicle.getRoute(v)
                self.buses[v] = route[len(route) // 2]
                self.bus_line[v] = traci.vehicle.getLine(v)
        # Drop arrived buses first: a bus that teleports past its midpoint edge
        # arrives without passing it and is no longer known to SUMO.
        for v in traci.simulation.getArrivedIDList():
            self.buses.pop(v, None)
        for v in list(self.buses):
            if traci.vehicle.getRoadID(v) == self.buses[v]:
                self.bus_passes[self.bus_line[v]].append(now)
                del self.buses[v]

    def results(self, tripinfo_file, expected_vehicles):
        root = ET.parse(tripinfo_file).getroot()
        cars, buses, ambulances = [], [], []
        for t in root.findall("tripinfo"):
            if t.get("id") == STALL_ID:
                continue
            vt = t.get("vType")
            (buses if vt == "bus" else ambulances if vt in ("ambulance", "police", "fire_truck") else cars).append(t)
        arrived_peds = [p.get("id") for p in root.findall("personinfo")]

        def col(rows, attr):
            return [float(r.get(attr)) for r in rows]

        dur, wait = col(cars, "duration"), col(cars, "waitingTime")
        co2 = sum(emission(t, "CO2_abs") for t in cars) / 1000.0  # g
        energy = energy_metrics(cars, buses, ambulances)
        ped_w = [self.ped_wait[p] for p in arrived_peds]
        gaps = [b - a for times in self.bus_passes.values()
                for a, b in zip(sorted(times), sorted(times)[1:])]
        completed = len(cars) + len(buses) + len(ambulances)
        mean = statistics.mean
        return {
            # Faycel
            "veh_completed": len(cars),
            "veh_unfinished": max(0, expected_vehicles - completed),
            "veh_mean_travel_s": mean(dur) if dur else 0,
            "veh_p95_travel_s": p95(dur),
            "veh_max_travel_s": max(dur) if dur else 0,
            "veh_mean_wait_s": mean(wait) if wait else 0,
            "veh_p95_wait_s": p95(wait),
            "veh_mean_stops": mean(col(cars, "waitingCount")) if cars else 0,
            "veh_mean_time_loss_s": mean(col(cars, "timeLoss")) if cars else 0,
            "co2_g_per_trip": co2 / max(1, len(cars)),
            # Ferjani
            "ped_completed": len(arrived_peds),
            "ped_mean_wait_s": mean(ped_w) if ped_w else 0,
            "ped_p95_wait_s": p95(ped_w),
            "ped_max_wait_s": max(ped_w) if ped_w else 0,
            "clearance_truncations": self.truncations,
            "clearance_truncations_slow": self.truncations_slow,
            # Mamadou
            "bus_mean_travel_s": mean(col(buses, "duration")) if buses else 0,
            "bus_headway_cv": (statistics.pstdev(gaps) / mean(gaps)) if len(gaps) > 1 else 0,
            "bus_long_gap_share": (sum(g > LATE_FACTOR * HEADWAY
                                       for g in gaps) / len(gaps)) if gaps else 0,
            # Touhami
            "ambulance_n": len(ambulances),
            "ambulance_mean_travel_s": mean(col(ambulances, "duration")) if ambulances else None,
            "ambulance_mean_wait_s": mean(col(ambulances, "waitingTime")) if ambulances else None,
            "ambulance_mean_time_loss_s": mean(col(ambulances, "timeLoss")) if ambulances else None,
            # Bus-First / sustainability (all vehicles; HBEFA proxies, not measured air)
            **energy,
        }


def emission(trip, attr):
    """One emissions attribute of a tripinfo element (mg; 0 when SUMO wrote none)."""
    e = trip.find("emissions")
    return float(e.get(attr, 0)) if e is not None else 0.0


def energy_metrics(cars, buses, ambulances):
    """Person-weighted delay, fuel and CO2 for every finished vehicle.

    Occupancy is an assumption from simulation.yaml > occupancy (no Tunis survey yet).
    Person-delay is what makes bus priority visible: one bus minute counts as ~50 car minutes
    divided by car occupancy. SUMO reports fuel_abs and CO2_abs in mg."""
    occ = config.simulation().get("occupancy", {})
    car_occ, bus_occ = float(occ.get("car", 1.2)), float(occ.get("bus", 50))
    groups = ((cars, car_occ), (buses, bus_occ), (ambulances, float(occ.get("emergency", 2))))
    person_loss = persons = person_km = 0.0
    fuel_mg = co2_mg = 0.0
    for rows, k in groups:
        for t in rows:
            person_loss += k * float(t.get("timeLoss", 0))
            persons += k
            person_km += k * float(t.get("routeLength", 0)) / 1000.0
            fuel_mg += emission(t, "fuel_abs")
            co2_mg += emission(t, "CO2_abs")
    vehicles = len(cars) + len(buses) + len(ambulances)
    bus_loss = [float(t.get("timeLoss", 0)) for t in buses]
    bus_stops = [float(t.get("waitingCount", 0)) for t in buses]
    return {
        "person_mean_delay_s": person_loss / persons if persons else 0,
        "person_delay_h": person_loss / 3600.0,
        "bus_mean_time_loss_s": statistics.mean(bus_loss) if bus_loss else 0,
        "bus_mean_stops": statistics.mean(bus_stops) if bus_stops else 0,
        "fuel_total_kg": fuel_mg / 1e6,
        "fuel_g_per_veh": fuel_mg / 1000.0 / vehicles if vehicles else 0,
        "co2_total_kg": co2_mg / 1e6,
        "co2_g_per_person_km": co2_mg / 1000.0 / person_km if person_km else 0,
        "fuel_g_per_person_km": fuel_mg / 1000.0 / person_km if person_km else 0,
    }
