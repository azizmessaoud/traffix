"""
Base class for every agent.

An agent reads the sensor layer and the message bus, and writes only messages
(requests, proposals, directives, publications). It never touches SUMO and
never changes a light. If a trained model exists in models/ (and the
controller allows models), the agent uses it; otherwise it falls back to a
transparent rule, so every agent always works.
"""
import json
import os
import warnings
from dataclasses import dataclass
from functools import lru_cache
from datetime import datetime, timedelta

import joblib

from ..core import config
from ..core.messages import Message


@lru_cache(maxsize=1)
def models_usable():
    """Trained models only load in the scikit-learn version that saved them.
    Returns (ok, message). On a mismatch every agent uses its rule-based fallback."""
    meta = config.path(config.agents()["models_dir"], "metrics.json")
    if not os.path.exists(meta):
        return False, "no trained models yet: run  python scripts/train.py --skip-tune"
    import sklearn
    saved = json.load(open(meta)).get("_versions", {}).get("scikit-learn")
    if saved != sklearn.__version__:
        return False, (f"models were trained with scikit-learn {saved}, you have {sklearn.__version__}: "
                       f"run  python scripts/train.py --skip-tune  (agents use rule-based fallbacks until then)")
    return True, ""


_warned = set()


def _warn_once(msg):
    if msg not in _warned:
        _warned.add(msg)
        print(f"[TraffiX] {msg}", flush=True)


@dataclass
class Context:
    models: dict            # junction id -> static junction model
    sensors: object
    bus: object
    log: object
    use_models: bool
    start: datetime         # wall-clock time at simulation second 0
    bus_first: bool = False # person-weighted pressure: a queued bus counts for its passengers

    def clock(self, now):
        return self.start + timedelta(seconds=now)


class Agent:
    name = "agent"
    model_file = None       # file in models/ this agent can learn into

    def __init__(self, ctx, tls=None):
        self.ctx, self.tls = ctx, tls
        self.sensors, self.bus, self.log = ctx.sensors, ctx.bus, ctx.log
        self.cfg = config.agents()
        self.model = self._load(self.model_file)

    @property
    def label(self):
        return f"{self.name}@{self.tls}" if self.tls else self.name

    def _load(self, filename):
        if not (filename and self.ctx.use_models):
            return None
        p = config.path(self.cfg["models_dir"], filename)
        if not os.path.exists(p):
            return None
        ok, msg = models_usable()
        if not ok:
            _warn_once(msg)
            return None
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                return joblib.load(p)
        except Exception as e:      # never let one bad file stop the simulation
            _warn_once(f"could not load {filename} ({e.__class__.__name__}); {self.name} uses its rule. "
                       f"Run  python scripts/train.py --skip-tune")
            return None

    def send(self, kind, target, now, ttl=1.5, subject="", link_index=-1, **details):
        return self.bus.post(Message(self.label, kind, target, now, now + ttl, subject,
                                     link_index, details))

    def step(self, now):
        raise NotImplementedError
