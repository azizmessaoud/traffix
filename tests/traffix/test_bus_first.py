"""Bus-First metrics and the Webster baseline:  python -m pytest tests/traffix/test_bus_first.py"""
import os
import sys
import xml.etree.ElementTree as ET

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from traffix.evaluation.monitor import energy_metrics  # noqa: E402
from traffix.evaluation.retime import restructure  # noqa: E402


def trip(loss, length=1000, fuel=100_000, co2=300_000, stops=1):
    t = ET.Element("tripinfo", timeLoss=str(loss), routeLength=str(length), waitingCount=str(stops))
    ET.SubElement(t, "emissions", fuel_abs=str(fuel), CO2_abs=str(co2))
    return t


def test_person_delay_weights_buses_by_occupancy():
    # one car losing 100 s and one bus losing 100 s: the bus carries most of the people
    m = energy_metrics([trip(100)], [trip(100)], [])
    assert abs(m["person_mean_delay_s"] - 100) < 1e-9          # same loss, so same mean
    m2 = energy_metrics([trip(100)], [trip(0)], [])
    assert m2["person_mean_delay_s"] < 5                        # bus riders dominate the average
    assert m2["bus_mean_time_loss_s"] == 0


def test_fuel_and_co2_units():
    m = energy_metrics([trip(0, length=2000, fuel=200_000, co2=600_000)], [], [])
    assert abs(m["fuel_total_kg"] - 0.2) < 1e-9                 # mg -> kg
    assert abs(m["fuel_g_per_veh"] - 200) < 1e-9
    # 600 g over 1.2 persons x 2 km
    assert abs(m["co2_g_per_person_km"] - 600 / 2.4) < 1e-6


def test_missing_emissions_count_as_zero():
    t = ET.Element("tripinfo", timeLoss="10", routeLength="500", waitingCount="0")
    assert energy_metrics([t], [], [])["fuel_total_kg"] == 0


def tl(phases):
    e = ET.Element("tlLogic")
    for d, s in phases:
        ET.SubElement(e, "phase", duration=str(d), state=s)
    return e


def test_restructure_keeps_clearance_and_yellow():
    default = tl([(37, "gGGrG"), (5, "gGGrr"), (3, "yyyrr"), (37, "rrrGr"), (5, "rrrGr"), (3, "rrryr")])
    webster = tl([(20, "gGGrG"), (20, "gGGrr"), (4, "yyyrr"), (8, "rrrGr"), (8, "rrrGr"), (4, "rrryr")])
    out = restructure(default, webster, crossing_m=6.4, slow_speed=0.95)
    assert [d for d, _ in out] == [35, 5, 3, 11, 5, 3]          # stage green kept, 5 s clearance
    assert [s for _, s in out] == [s.get("state") for s in default]


def test_restructure_protects_slow_walkers():
    default = tl([(37, "gGrG"), (5, "gGrr"), (3, "yyrr")])
    webster = tl([(4, "gGrG"), (4, "gGrr"), (4, "yyrr")])
    out = restructure(default, webster, crossing_m=19.0, slow_speed=0.95)   # 20 s to cross
    walk, clear = out[0][0], out[1][0]
    assert walk + clear >= 19.0 / 0.95
