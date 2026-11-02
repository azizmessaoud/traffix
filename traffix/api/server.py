"""
Backend API for the React frontend. The frontend only talks to this server,
which reads from the supermaster's live run; it never reaches the masters or SUMO.

  GET  /api/scenarios                       list of scenarios
  POST /api/start?scenario=rain&speed=4     start a live run
  POST /api/stop
  GET  /api/state                           full live snapshot
  GET  /api/network                         map geometry
  GET  /api/basemap/streets                 street map image (offline fallback under the live tiles)
  GET  /api/notifications?persona=bus_driver
  GET  /api/decisions?limit=200&q=ambulance
  GET  /api/places                          trip planner start and end points
  GET  /api/trip?origin=EDGE&destination=EDGE   personal route, delay, alerts, alternative
  POST /api/ask  {"question": "...", "lang": "en|fr|ar"}   explainer agent (Synapse)
  GET  /api/copilot?lang=fr                 operator copilot summary + suggestions
  POST /api/copilot/report?lang=ar          incident report draft
  POST /api/copilot/decision                approve / dismiss a suggestion (recorded only)
  POST /api/synapse/explain {"decision_id": 412, "question": "..."}   CoFlow Synapse: verified/template/abstain
  POST /api/synapse/audit   {"decision_id": 412, "claim": "..."}      + seven-field provenance
  GET  /api/synapse/metrics                 abstention / fallback rates of this run's Synapse
  GET  /api/llm                             is a language model available?
  GET  /api/results                         experiment summary (if available)
  GET  /api/models                          training metrics
"""
import hmac
import json
import os
import threading
from uuid import UUID

from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from ..agents.network.explainer import ExplainerAgent
from ..core import config
from ..synapse.coflow_bridge import TraffixSynapse
from .live import LiveRun, SUMO_HOME

app = FastAPI(title="TraffiX API")
SETTINGS = {"gui": False}       # set by scripts/run_live.py --gui
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
RUN = {"live": None}
RUN_LOCK = threading.Lock()


class Question(BaseModel):
    question: str
    lang: str = "en"


class SynapseQuestion(BaseModel):
    decision_id: int
    question: str = "Why was this decision taken?"


class SynapseClaim(BaseModel):
    decision_id: int
    claim: str


class Decision(BaseModel):
    suggestion_id: str
    title: str
    decision: str          # "approve" | "dismiss"


class IncidentRequest(BaseModel):
    request_id: UUID
    edge_id: str = Field(min_length=1, max_length=128)
    lane_index: int = Field(ge=0, le=16)
    duration_seconds: int = Field(ge=10, le=1800)


def require_operator(authorization: str | None):
    """Local runs may omit a token; hosted runs must set TRAFFIX_OPERATOR_TOKEN."""
    expected = os.environ.get("TRAFFIX_OPERATOR_TOKEN", "")
    required = os.environ.get("TRAFFIX_REQUIRE_OPERATOR_TOKEN", "").lower() in {"1", "true", "yes"}
    if required and not expected:
        raise HTTPException(503, "Operator access is not configured")
    if not expected and not required:
        return
    supplied = authorization[7:] if authorization and authorization.startswith("Bearer ") else ""
    if not supplied or not hmac.compare_digest(supplied, expected):
        raise HTTPException(401, "A valid operator token is required")


def live():
    if RUN["live"] is None:
        raise HTTPException(409, "No live run. POST /api/start first.")
    return RUN["live"]


@app.get("/api/scenarios")
def scenarios():
    return [{"id": k, "start": v["start"], "description": v.get("description", ""),
             "events": list((v.get("events") or {}).keys())} for k, v in config.scenarios().items()]


LIVE_CONTROLLERS = ["traffix", "traffix_predictive", "traffix_rl", "traffix_rules", "junction_only"]


@app.get("/api/controllers")
def controllers():
    return LIVE_CONTROLLERS


@app.get("/health")
def health():
    sumo_binary = "sumo.exe" if os.name == "nt" else "sumo"
    sumo_ready = os.path.isfile(os.path.join(SUMO_HOME, "bin", sumo_binary))
    network_ready = os.path.isfile(config.network_files()[0])
    frontend_ready = os.path.isfile(config.path("frontend", "dist", "index.html"))
    status = "ready" if sumo_ready and network_ready and frontend_ready else "not_ready"
    result = {"status": status, "sumo": sumo_ready, "network": network_ready, "frontend": frontend_ready}
    if status != "ready":
        raise HTTPException(503, result)
    return result


@app.post("/api/start")
def start(scenario: str = "morning_peak", speed: float = 4.0, seed: int = 1, controller: str = "traffix",
          authorization: str | None = Header(default=None)):
    require_operator(authorization)
    if not 0.25 <= speed <= 16:
        raise HTTPException(422, "Speed must be between 0.25× and 16×")
    if not 1 <= seed <= 2_147_483_647:
        raise HTTPException(422, "Seed must be between 1 and 2147483647")
    if scenario not in config.scenarios():
        raise HTTPException(404, f"Unknown scenario {scenario}")
    if controller not in LIVE_CONTROLLERS:
        raise HTTPException(404, f"Unknown controller {controller}")
    with RUN_LOCK:
        if RUN["live"] and not RUN["live"].stop():
            raise HTTPException(409, "The previous run is still stopping. Try again in a few seconds.")
        RUN["live"] = LiveRun(scenario, seed, speed, controller, gui=SETTINGS["gui"])
        RUN["live"].start()
    return {"started": scenario, "speed": speed, "seed": seed, "controller": controller}


@app.post("/api/stop")
def stop(authorization: str | None = Header(default=None)):
    require_operator(authorization)
    with RUN_LOCK:
        if RUN["live"]:
            RUN["live"].stop()
    return {"stopped": True}


@app.get("/api/event-options")
def event_options():
    lv = live()
    return {"types": ["incident"], "max_active": 20,
            "duration_seconds": {"minimum": 10, "maximum": 1800},
            "edges": lv.incident_options}


@app.post("/api/events")
def inject_event(body: IncidentRequest, authorization: str | None = Header(default=None)):
    require_operator(authorization)
    try:
        event = live().enqueue_incident(body.edge_id, body.lane_index, body.duration_seconds, body.request_id)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return event


@app.get("/api/events")
def events():
    return live().state().get("world_events", [])


@app.get("/api/state")
def state():
    return live().state() if RUN["live"] else {"status": "idle"}


@app.get("/api/network")
def network():
    return live().geometry


@app.get("/api/basemap/{style}")
def basemap(style: str):
    """Street map image behind the network map (built by scripts/build_basemap.py)."""
    net = config.network_files()[0]
    meta_file = net.replace(".net.xml", ".basemap.json")
    if not os.path.exists(meta_file):
        raise HTTPException(404, "no basemap for this network: run scripts/build_basemap.py")
    with open(meta_file, encoding="utf-8") as f:
        files = json.load(f)["styles"]
    if style not in files:
        raise HTTPException(404, f"Unknown basemap style {style}")
    return FileResponse(os.path.join(os.path.dirname(net), files[style]),
                        headers={"cache-control": "public, max-age=86400"})


@app.get("/api/notifications")
def notifications(persona: str = "operator", limit: int = 50):
    items = [n for n in live().state().get("notifications", []) if n["persona"] == persona]
    return items[-limit:][::-1]


@app.get("/api/decisions")
def decisions(limit: int = 200, q: str = ""):
    lv = live()
    entries = lv.narrator.enrich(lv.log.entries) if hasattr(lv, "narrator") else lv.log.entries
    if q:
        entries = [e for e in entries if q.lower() in json.dumps(e, ensure_ascii=False).lower()]
    return entries[-limit:][::-1]


@app.get("/api/places")
def places():
    return live().places


@app.get("/api/trip")
def trip(origin: str, destination: str):
    """Personal trip: fastest route now, delay, alerts on the route, and an alternative."""
    return live().plan_trip(origin, destination)


@app.post("/api/ask")
def ask(body: Question, authorization: str | None = Header(default=None)):
    require_operator(authorization)
    lv = live()
    tools = {"get_live_state": lambda: lv.copilot.context() if hasattr(lv, "copilot") else lv.state(),
             "get_results": lambda measure="": [r for r in results()["summary"]
                                                if measure.lower() in r["measure"].lower()][:120]}
    return ExplainerAgent(list(lv.log.entries), getattr(lv, "narrator", None)).ask(body.question, lang=body.lang,
                                                                                 tools=tools)


def synapse():
    """CoFlow Synapse over a frozen copy of the live decision log (rebuilt when the log grows)."""
    lv = live()
    entries = list(lv.log.entries)
    cached = getattr(lv, "_synapse", None)
    if cached is None:
        lv._synapse = TraffixSynapse(entries, run_id=f"live_{lv.controller}_{lv.scenario}_{lv.seed}",
                                     scenario=lv.meta)
    elif len(cached.entries) != len(entries):
        lv._synapse = cached.refreshed(entries)
    return lv._synapse


@app.post("/api/synapse/explain")
def synapse_explain(body: SynapseQuestion):
    return synapse().explain(body.question, body.decision_id)


@app.post("/api/synapse/audit")
def synapse_audit(body: SynapseClaim):
    return synapse().audit(body.claim, body.decision_id)


@app.get("/api/synapse/metrics")
def synapse_metrics():
    return synapse().metrics()


@app.get("/api/llm")
def llm_status():
    """Is a language model available? (ANTHROPIC_API_KEY set before starting the server)"""
    from ..synapse import llm
    from ..core import config as cfg
    s = cfg.agents()["synapse"]
    lv = RUN["live"]
    return {"available": llm.available(), "provider": llm.provider(), "languages": s["languages"],
            "models": {r: llm.model_for(r) for r in ("explainer", "copilot", "alert")} if llm.available() else {},
            "alerts": getattr(getattr(lv, "alert_writer", None), "stats", None)}


@app.get("/api/copilot")
def copilot(lang: str = "en", authorization: str | None = Header(default=None)):
    require_operator(authorization)
    return live().copilot.summary(lang)


@app.post("/api/copilot/report")
def copilot_report(lang: str = "en", authorization: str | None = Header(default=None)):
    require_operator(authorization)
    return live().copilot.report(lang)


@app.post("/api/copilot/decision")
def copilot_decision(body: Decision, authorization: str | None = Header(default=None)):
    require_operator(authorization)
    lv = live()
    entry = lv.copilot.decide(body.suggestion_id, body.title, body.decision, lv.state().get("t", 0))
    return {"recorded": True, "log_id": entry, "applied": False}


@app.get("/api/results")
def results():
    """Experiment results produced by scripts/run_experiments.py + scripts/analyze.py."""
    # imported here, after libsumo: pandas loads pyarrow, whose arrow.dll makes libsumo ~10x slower if it loads first
    import pandas as pd

    def csv(name):
        p = config.path("results", name)
        try:
            return pd.read_csv(p).astype(object).where(lambda d: pd.notna(d), None).to_dict("records")
        except (FileNotFoundError, pd.errors.EmptyDataError):
            return []
    summary = csv("summary_by_persona.csv")
    return {"summary": summary, "significance": csv("significance.csv"),
            "has_chart": os.path.exists(config.path("results", "persona_charts.png")),
            "scenarios": list(dict.fromkeys(r["scenario"] for r in summary)),
            "controllers": [c for c in ["fixed", "actuated", "junction_only", "traffix_rules", "traffix",
                                        "traffix_predictive", "traffix_rl"]
                            if any(r["controller"] == c for r in summary)]}


@app.get("/api/results/chart")
def results_chart():
    p = config.path("results", "persona_charts.png")
    if not os.path.exists(p):
        raise HTTPException(404, "Run scripts/analyze.py first")
    return FileResponse(p, media_type="image/png")


@app.get("/api/models")
def models():
    p = config.path("models", "metrics.json")
    return json.load(open(p)) if os.path.exists(p) else {}


dist = config.path("frontend", "dist")
if os.path.isdir(dist):
    app.mount("/assets", StaticFiles(directory=os.path.join(dist, "assets")), name="assets")

    @app.get("/{page:path}")
    def spa(page: str):
        """Any non-API path returns the React app, which handles the routing."""
        return FileResponse(os.path.join(dist, "index.html"))
