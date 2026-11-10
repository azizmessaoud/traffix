"""
Assembles one controller for one run.

  junction_only   masters + junction agents (trained models), no supermaster
  traffix_rules   full hierarchy, every agent on its rule-based fallback
  traffix         full hierarchy with trained models (max-pressure traffic light agent)
  traffix_predictive  same, with the predictive (MPC) traffic light agent
  traffix_rl          same, with the reinforcement learning traffic light agent
  traffix_bus_first   same as traffix, but max-pressure counts people, not vehicles: a bus waiting
                      at the light weighs agents.yaml > bus_first > bus_weight queued cars
(fixed and actuated are SUMO's own plans: no TraffiX objects at all.)

Order inside one simulated second:
  sensors -> supermaster (network agents, every 5 s) -> masters (junction agents,
  decide, write) -> executor -> bus prune
"""
from ..agents.base import Context
from ..core.messages import MessageBus
from ..simulation.executor import Executor
from ..simulation.sensors import SensorLayer
from .master import Master
from .safety_rules import SafetyRules
from .supermaster import Supermaster


class TraffixSystem:
    def __init__(self, controller, models, net_file, log, start):
        use_models = controller in ("traffix", "junction_only", "traffix_predictive", "traffix_rl",
                                    "traffix_bus_first")
        light = {"traffix_predictive": "predictive", "traffix_rl": "rl"}.get(controller, "max_pressure")
        self.sensors = SensorLayer(models, net_file)
        self.bus = MessageBus()
        self.ctx = Context(models, self.sensors, self.bus, log, use_models, start,
                           bus_first=controller == "traffix_bus_first")
        self.safety = SafetyRules(models, self.sensors, self.bus, log)
        self.executor = Executor(models, self.safety, log)
        self.masters = [Master(self.ctx, t, self.safety, self.executor, light) for t in models]
        self.supermaster = Supermaster(self.ctx) if controller != "junction_only" else None

    def start(self, now):
        self.sensors.update(now)
        self.executor.start(now)

    def step(self, now):
        self.sensors.update(now)
        if self.supermaster:
            self.supermaster.step(now)
        for m in self.masters:
            m.step(now)
        self.executor.step(now)
        self.bus.prune(now)
