"""
How Python talks to SUMO. Only simulation/sensors.py (read), simulation/executor.py (write lights),
simulation/world.py (scenario events) and evaluation/monitor.py may import this.
check_architecture.py enforces that rule.

libsumo runs SUMO inside Python (fast); traci uses a socket and is needed
for the GUI. Both expose the same functions.
"""
import sys


def _load_traci():
    """SUMO is needed only to run a simulation, not to import the API or the agents. Without it
    this is None, and a run fails with a clear error instead of the whole app failing to import."""
    if "--gui" not in sys.argv:
        try:
            import libsumo
            return libsumo
        except ImportError:
            pass
    try:
        import traci
        return traci
    except ImportError:
        return None


traci = _load_traci()
