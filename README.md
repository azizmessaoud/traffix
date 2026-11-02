---
title: TraffiX Live Simulation
emoji: 🚦
colorFrom: blue
colorTo: green
sdk: docker
app_port: 7860
pinned: false
---

# traffix

A reliable AI decision platform for urban traffic simulation, built on Eclipse SUMO by six
ESPRIT 5DS students for the course advanced data science project
*Intelligent Multi-Agent Traffic Management*.

Agents cooperate to run the traffic lights of a simulated city. **Only one controller per light
may change it**, every decision is logged with a reason, and a language layer (**Synapse**)
explains decisions from that log. Synapse never touches the simulation.

> **Simulation only.** Road demand is synthetic. SUMO/HBEFA emissions are proxies, not measured
> air quality. Simulated emergency times are not lives saved. Nothing here is deployment evidence.

This README replaces the project's earlier markdown documents: the Design Thinking books, the
requirements books, the architecture decision records (ADRs), the run guides and the project
summaries. Each of those is summarised in a section below.

---

## Contents

1. [Quick start](#1-quick-start)
2. [What is in the repository](#2-what-is-in-the-repository)
3. [The live system: traffix hierarchy on Tunis J1..J6](#3-the-live-system-traffix-hierarchy-on-tunis-j1j6)
4. [The controlled J0 platform (`src/coflow5`)](#4-the-controlled-j0-platform-srccoflow5)
5. [How to run SUMO](#5-how-to-run-sumo)
6. [Architecture rules](#6-architecture-rules)
7. [Evidence, evaluation and honesty](#7-evidence-evaluation-and-honesty)
8. [Design Thinking (Empathize, Define, Ideate)](#8-design-thinking)
9. [Requirements](#9-requirements)
10. [Architecture decisions (ADR summaries)](#10-architecture-decisions)
11. [Team and delivery plan](#11-team-and-delivery-plan)
12. [Data sources](#12-data-sources)
13. [Research evidence behind the personas](#13-research-evidence-behind-the-personas)
14. [Known limitations](#14-known-limitations)
15. [Glossary](#15-glossary)

---

## 1. Quick start

Requirements: Windows, Python 3.11 (`py -3.11`), SUMO 1.27.1 (`SUMO_HOME` set, or
`pip install eclipse-sumo==1.27.1`), Node.js for rebuilding the web app.

```powershell
py -3.11 -m pip install -r requirements-traffix.txt
py -3.11 scripts\setup.py              # network (if missing), traffic for every scenario, models if unusable
py -3.11 scripts\run_live.py --gui     # web app at http://localhost:8000; --gui also opens sumo-gui
```

Pick a scenario in the web app and press **Start**. Each persona page (pedestrian, car driver,
bus passenger, bus driver, ambulance crew, operator, analyst) shows the same live run from that
person's point of view. `run_live.py` options: `--port`, `--scenario`, `--speed`, `--controller`.

Optional LLM explanations: put an API key in a local `.env` file at the repository root (it is
gitignored). Without one, explanations fall back to deterministic templates.

Experiments and analysis:

```powershell
py -3.11 scripts\run_experiments.py --scenario morning_peak --seeds 1   # one quick comparison
py -3.11 scripts\run_experiments.py                                     # 7 controllers x 12 scenarios x 3 seeds
py -3.11 scripts\run_experiments.py --fresh                             # start over
py -3.11 scripts\analyze.py                                             # tables and charts in results/
py -3.11 scripts\check_architecture.py                                  # hierarchy rules hold
py -3.11 scripts\train.py                                               # retrain models on the current network
py -3.11 scripts\ask.py results\logs\decisions_traffix_emergency_1.jsonl "Why did ambulance1 get green at J1?"
py -3.11 -m pytest -q                                                   # all tests
```

`run_experiments.py` rebuilds any traffic file that was built for another map or an older build
of the network (each traffic file records the network's fingerprint).

---

## 2. What is in the repository

| Path | What it is |
|---|---|
| `traffix/` | The live multi-agent controller (traffix3 hierarchy) and the CoFlow Synapse bridge |
| `config/` | Simulation, agent, calendar and scenario settings; per-network files in `config/networks/` |
| `scenarios/` | SUMO networks: `tunis-centre-6j/` (default), `tunis-showcase/`, `watch/`, `smoke/`, `safety-mask/`, `baselines/`, `max-pressure/` |
| `models/` | Trained models used by the traffix agents (`metrics.json` records their scores) |
| `frontend/` | React web app served by `run_live.py` (persona pages, live map) |
| `src/coflow5/` | The controlled J0 platform: A1 controller, safety mask, A2–A5 advisers, message board, Synapse service, read-only API |
| `web/` | Read-only React evidence dashboard for the `src/coflow5` API |
| `deploy/` | Docker files for the hosted read-only API and dashboard (no SUMO inside) |
| `scripts/` | Build, run, experiment, training and evidence scripts |
| `tests/` | `architecture/`, `api/`, `acceptance/`, `contracts/`, `properties/`, `scripts/`, `traffix/` |
| `results/` | Run outputs (gitignored): experiment results, logs, `results/evidence/<row>/` evidence bundles |
| `docs/presentation/` | Slide decks and printable persona canvases |
| `data/` | Generated traffic (`data/generated/`, gitignored) and the schematic network |

---

## 3. The live system: traffix hierarchy on Tunis J1..J6

The team adopted the agent architecture of
[aymenhamzik/traffix3](https://github.com/aymenhamzik/traffix3) and runs it on the real
OpenStreetMap streets of Tunis centre-ville. Six junctions carry traffic lights (J1..J6); every
other junction yields. Node ids and light ids are both J1..J6.

### The six junctions

| Light | Streets |
|---|---|
| J1 | Av. Habib Bourguiba x Place du 14 Janvier 2011 x Av. Mohamed V |
| J2 | Av. Habib Bourguiba x Av. de France x Rue Jamel Abdel Nasser x Rue de Rome |
| J3 | Rue Saad Zagloul x Av. Moncef Bey |
| J4 | Av. Habib Thameur x Rue de Rome x Rue Mokhtar Attia |
| J5 | Av. Habib Thameur x Rue de Sparte x Rue Salonique x Rue d'Athènes |
| J6 | Av. Habib Bourguiba x Rue d'Alger |

OSM node ids, signal plans, downstream neighbours and bus stops are in
`scenarios/tunis-centre-6j/junctions.json`, also summarised in
`scenarios/tunis-centre-6j/README.md`. Network facts (folder, bus lines, scenario event places,
demand level) are in `config/networks/tunis6j.yaml`. Scenarios refer to places as `"@name"`.

Bus-line geometry is TRANSTU-attributed data from a community-maintained visualization
(`scripts/import_transtu_lines.py` writes `tunis6j.lines.json` and bus stops); it is not an
independently verified official feed. Its headway is an assumption, not a timetable. The
background street map comes from Esri tiles aligned to the network
(`scripts/build_basemap.py`).

Rebuild the network from the committed OSM extract:

```powershell
py -3.11 scripts\build_tunis_centre_6j.py      # also re-imports TRANSTU lines and the basemap decal
py -3.11 -m pytest tests\scripts\test_tunis_centre_6j.py -q
```

To refresh the map from a fresh Geofabrik Tunisia PBF, download the current
[`tunisia-latest.osm.pbf`](https://download.geofabrik.de/africa/tunisia.html), clip the wider Tunis
area, then rebuild the six-junction scenario while recording the PBF fingerprint:

```powershell
py -3.11 scripts\clip_tunis_osm.py --input path\to\tunisia-latest.osm.pbf --output scenarios\tunis-showcase\tunis.osm.xml --bbox 10.127879 36.787714 10.233358 36.820741
py -3.11 scripts\build_tunis_centre_6j.py --source-pbf path\to\tunisia-latest.osm.pbf --source-pbf-data-as-of 2026-10-15T20:21:00Z
```

The current scenario is based on OSM data through 2026-10-15 20:21 UTC. All six selected OSM node IDs
were present, and their stored coordinates match the refreshed source coordinates within 0.01 m.
However, the lane data are not complete: **43/466 road ways** in the central clip have explicit OSM
lane-count tags, and only **3/21 unique ways directly incident to the six junctions** have them.
SUMO annotates defaults for the rest; **those defaults are not verified real-world lane counts**.
The OSM geometry was cross-checked against Esri World Imagery at zoom 19, but the imagery capture
date is not exposed and it is not adequate evidence to certify every lane marking. The previous
claim that lanes matched satellite imagery within a few metres was unsupported and has been removed.
For exact lane counts, the 18 untagged junction-incident ways need current local survey or
authoritative road-design data; do not treat the current lane configuration as fully verified.
They are tracked in `scenarios/tunis-centre-6j/lane_overrides.json` (all still `unverified`; a
desk search of Panoramax, KartaView and Wikimedia Commons found no dated imagery showing the
stop-line markings) and listed on the printable `field-survey-sheet.html`. Verified values entered
there are applied before `netconvert`; `py -3.11 scripts\lane_overrides.py --strict` fails until all
21 junction roads have evidence. Junction roads without an OSM `maxspeed` use Tunisia's 50 km/h
urban legal default instead of SUMO's 80–100 km/h; see the scenario README for sources and limits.

The six junctions were chosen deterministically from the Tunis OSM graph
(`scenarios/tunis-centre-6j/selection.json`): degree ≥ 3, then traffic signals > roundabout >
stop/give-way > named > degree > major road > node id. Motorway ramp lane guessing is disabled in
this city-centre network.

To use traffix3's original schematic network instead, set `TRAFFIX_NETWORK=tunis_centre`, then run
`scripts\build_network.py` and `scripts\build_demand.py`.

### The hierarchy

| Level | Component | Role |
|---|---|---|
| Junction (x6) | 5 agents | traffic light (max-pressure / predictive / RL), pedestrian, transit priority, emergency priority, sensor health |
| Junction (x6) | Master | resolves requests in the order safety > emergency > supermaster directive > transit > pedestrian > normal; the only writer of its light |
| Network | Supermaster | runs 8 network agents every 5 s, sends directives, never writes a light |
| Network | 8 agents | demand forecast, incident detection, rerouting, emergency route, corridor, transit monitor, weather, notification |
| Synapse | Explainer, alert writer, operator copilot | language layer (EN/FR/AR, optional LLM); no path to the simulation |
| Synapse | **CoFlow Synapse** | `traffix/synapse/coflow_bridge.py`: verified / template / abstain over the decision log, seven-field provenance |

How the CoFlow rules hold in traffix:

| Rule | In traffix |
|---|---|
| One signal writer | Only `simulation/executor.py` writes lights, and only masters call it (`scripts/check_architecture.py` enforces this) |
| Synapse cannot reach SUMO | `traffix/synapse/` and the explainer may not import the backend, sensors, executor or masters (same check) |
| Recovery ladder | Master modes `MODE_MAX_PRESSURE` -> `MODE_ACTUATED` -> `MODE_FIXED` on stale data |
| Learning optional | The RL light agent (`traffix_rl`) is optional; max-pressure is the default |

Controllers compared by `run_experiments.py`: `fixed`, `actuated` (SUMO plans), `junction_only`
(no supermaster), `traffix_rules` (no trained models), `traffix`, `traffix_predictive` (MPC) and
`traffix_rl`.

### CoFlow Synapse API

Each decision in the log becomes a CoFlow `EvidenceEvent`. The policy corpus is the reason-code
table in `traffix/core/decision_log.py`.

```text
POST /api/synapse/explain  {"decision_id": 337}
POST /api/synapse/audit    {"decision_id": 337, "claim": "J1 held green for ambulance 2"}
GET  /api/synapse/metrics
```

- `verified`: the decision's reason code is in the corpus and is cited.
- `template`: no citation available; the answer is built from recorded facts only.
- `abstain`: unknown decision id, or a claim the recorded facts do not support.

The analyst page shows a **Verify with CoFlow Synapse** button under each decision.

---

## 4. The controlled J0 platform (`src/coflow5`)

Before the traffix hierarchy, the team built a controlled single-junction (J0) platform as the
scientific benchmark: five domain agents, one signal writer, deterministic safety, baselines and
failure injection, all checked by tests.

| Agent | Responsibility | Permission |
|---|---|---|
| A1 Flow | Selects legal signal actions using cooperative Max-Pressure | The only signal writer |
| A2 Emergency | Expiring emergency-corridor requests (ETA, urgency, benefit, civilian externality) | Advisory only |
| A3 Multimodal | Pedestrian crossing state, waiting deadlines, conditional late-bus priority | Advisory only |
| A4 Situation | Forecasting and residual incident detection, with confidence and expiry | Advisory only |
| A5 Sustainability | SUMO/HBEFA emission-proxy advice | Advisory only |
| Synapse | Retrieval, explanations, audits, what-if support | Read-only; never actuates |

```text
src/coflow5/
  control/       a1_controller (sole safe submission capability), max_pressure, safety, recovery,
                 request_arbitration, baselines
  sumo_adapter/  signal_executor (guarded writes), J0 TraCI runners, smoke backends
  messaging/     envelope, board, A1 advisories and forecasts
  a2/ a3/ a4/ a5/  advisory agents
  synapse/       service (explanations, audits, fallback), observer
  evidence/      evidence bundle, schemas, artifact generators
  evaluation/    J0 completion checks
  api/           read-only FastAPI over evidence (app.py, store.py)
```

The native runner is J0-specific (one signal `J0`, lanes `N_in_0`, `E_in_0`, `S_in_0`, `W_in_0`).
The six-junction Tunis control was done with the traffix hierarchy (section 3) rather than by
generalising this runner.

Evidence generators write bundles to `results/evidence/<row>/`:

```powershell
py -3.11 scripts\generate_evidence_bundle.py
py -3.11 scripts\generate_safety_artifacts.py
py -3.11 scripts\generate_baseline_artifacts.py
py -3.11 scripts\generate_max_pressure_artifacts.py
py -3.11 scripts\generate_message_board_artifacts.py
py -3.11 scripts\generate_cooperation_artifacts.py
```

Read-only API and dashboard over stored evidence:

```powershell
$env:EVIDENCE_ROOT = (Resolve-Path "deploy\evidence").Path
py -3.11 -m uvicorn coflow5.api.app:app --app-dir src --host 127.0.0.1 --port 8000
cd web; npm.cmd run dev -- --host 127.0.0.1           # http://127.0.0.1:5173/
```

Endpoints: `/health`, `/runs`, `/runs/{run_id}`, `/runs/{run_id}/artifacts/{name}`, `/events`,
`/comparisons`, `/metrics`, `/explanations`, `/audits`, plus LOCAL_RUNNER-only proposal and
approval endpoints. The dashboard reports `actuates: false` and `sumo: false`.

Hosted demo (read-only, no SUMO in the images): `cd deploy; docker compose up --build`.

---

## 5. How to run SUMO

Two different things can be run:

1. **Watch the map:** `sumo-gui` and the green Play button, with SUMO's default lights.
2. **Run the agents:** Python drives SUMO through TraCI (headless or with `--gui`).

Once per PowerShell window, if SUMO is not on the path:

```powershell
$env:SUMO_HOME = "C:\Program Files (x86)\Eclipse\Sumo"
$env:Path = "$env:SUMO_HOME\bin;" + $env:Path
```

### Watch a scene

| Command | What you see |
|---|---|
| `py -3.11 scripts\watch_sumo.py smoke` | Tiny smoke grid (~180 s) |
| `py -3.11 scripts\watch_sumo.py safety` | Four-way junction used by the safety tests |
| `py -3.11 scripts\watch_sumo.py baselines` | Baseline signal plans |
| `py -3.11 scripts\watch_sumo.py max-pressure` | Max-Pressure plan file, not live A1 |
| `py -3.11 scripts\watch_sumo.py a1` | sumo-gui with live TraCI Max-Pressure (A1) on J0 |
| `py -3.11 scripts\watch_sumo.py tunis` | Wider Tunis OSM showcase with synthetic routes |
| `py -3.11 scripts\watch_sumo.py tunis6j` | Tunis centre-ville, only J1..J6 signalised |

Same by hand: `sumo-gui -c scenarios\tunis-centre-6j\tunis6j.sumocfg` (or any `.sumocfg` above).

The headless J0 A1 run is `py -3.11 scripts\generate_max_pressure_artifacts.py`. The live
`watch_sumo.py a1` window does not rewrite those artifacts.

### Wider Tunis showcase

```powershell
py -3.11 scripts\build_tunis_sumo.py      # uses the committed OSM extract; SUMO/netconvert + randomTrips
py -3.11 scripts\watch_sumo.py tunis
```

The builder is portable across Windows, Linux and macOS when SUMO is installed (set `SUMO_HOME` if
needed). It uses the checked-in `scenarios/tunis-showcase/tunis.osm.xml` by default instead of a
developer-specific local file path. To refresh from the latest country extract, download the
[Geofabrik Tunisia OSM PBF](https://download.geofabrik.de/africa/tunisia.html) and run
`py -3.11 scripts\build_tunis_sumo.py --pbf path\to\tunisia-latest.osm.pbf --force` with `pyosmium`
installed. The network preserves OSM road geometry and tagged lane attributes as interpreted by
SUMO `netconvert`; it is a map snapshot, so verify current construction, closures and lane marking
against local survey data before claiming current field accuracy. The fixed-seed routes are
synthetic, not observed Tunis traffic. Each run writes `scenarios/tunis-showcase/tunis.source.json`
with the imported OSM XML hash, OSM attribution/license, AOI, and (when supplied) the source PBF hash.

The central six-junction network is the recommended reproducible study AOI. Its road extract,
selected junctions and build options are hash-recorded in `scenarios/tunis-centre-6j/junctions.json`.
The TRANSTU stop/line geometry used there is imported from the community-maintained
[`transtu-visualisation` dataset](https://hobbes-286.github.io/transtu-visualisation/), whose map
credits TRANSTU and OpenStreetMap. It is **not** a directly published or independently validated
official timetable/GTFS feed. The repository stores the source rows and content hash; generated
bus routes are snapped to legal OSM bus edges and tested for continuity, stop ordering and loops.
The configured 15-minute line headway is explicitly an assumption, not observed or published
service frequency. Do not describe these line geometries or demand levels as independently
verified real-world operations.

### Native smoke test

`py -3.11 scripts\run_native_smoke.py` checks the toolchain and `libsumo` throughput. On this
machine Windows application control blocks the `libsumo` DLLs, so the project uses TraCI. Do not
use the smoke test as the daily demo until `libsumo` is allowed. Docker is not part of it.

---

## 6. Architecture rules

These hold in both the J0 platform and the traffix hierarchy:

1. **One signal writer.** Exactly one authorised writer per light. Advisers ask; they never write.
2. **Synapse cannot reach SUMO.** Enforced by imports and capabilities, not by prompts.
3. **Required recovery ladder:** cooperative Max-Pressure -> actuated -> fixed-time. If optional
   RL/DQN is ever enabled, it fails into Max-Pressure first.
4. **Learning is optional.** Max-Pressure needs no training; the product passes without RL.
5. **Evidence lives in files** (manifests, logs, artifacts), not in chat or memory.
6. **Claim flags stay** (section 7).

```text
SUMO -> observation adapter -> A1 (+ typed advice from A2..A5 via the message board)
     -> deterministic safety mask -> A1 signal executor -> SUMO
messages + decisions + faults + trips -> run evidence -> evaluation / API / Synapse
```

| Component | May | Must not |
|---|---|---|
| Observation adapter | Read SUMO, build typed observations | Choose traffic policy |
| A1 controller/executor | Arbitrate and execute safety-approved commands | Accept LLM text as a command or bypass the mask |
| Advisers (A2–A5) | Read approved observations, publish typed advice | Import TraCI/libsumo or reach the executor |
| Evidence/evaluation | Read immutable artifacts and compute results | Actuate signals |
| Synapse/API/UI | Read approved evidence | Reach TraCI, change state, or invent evidence ids |

**Decision loop:** SUMO steps; the adapter builds observations; advisers publish bounded messages;
A1 reads the messages valid now; duplicate, expired, malformed or contradictory messages get a
recorded disposition; A1 scores legal actions from pressure, downstream space, phase timing and
valid requests; the safety mask accepts or rejects; the executor writes only accepted actions and
records an immutable decision event.

**Priority tiers (J0 design):** active safety or a pedestrian already crossing -> emergency ->
pedestrian waiting deadline -> late transit -> general flow -> sustainability. Within a tier A1
compares benefit and externality, and every accepted, rejected or deferred request keeps its
`message_id` and a reason code.

**Message envelope:** `run_id`, `scenario_hash`, `message_id`, `correlation_id`, `source_agent`,
`destination_or_topic`, `created_at`, `simulation_time`, `expires_at`, `priority_class`,
`confidence`, `schema_version`, `payload_type`, `payload`, `provenance`. Topics: `state`,
`forecast`, `alerts`, `eco`, `requests`, `replies`, `health`. The board is in-process; Redis is
allowed only after a proven multi-process need.

**Edge cases:** an emergency arriving while a pedestrian crosses waits for the clearance; two
conflicting emergencies use a deterministic rule and both outcomes are recorded; a pedestrian
deadline beats a late bus; a silent A4 means "forecast unavailable", never "normal"; an eco request
during spillback is rejected with a reason; an unsafe human override goes through the same mask;
if Synapse or the LLM dies, traffic actions do not change.

**Multi-agent patterns kept:** single actuation authority, deterministic safety mask, blackboard
pub/sub, contract-net request/reply for A2/A3, bid comparison inside priority tiers, hierarchical
timescales (A1 in seconds, advisers slower), watchdog recovery ladder, heartbeat/TTL/stale
handling, LLM as explainer only. **Rejected:** LLM signal writes, five conversational agents,
independent RL without one writer, throughput-only optimisation, RoadwayVR as a runtime
dependency. The design trades optimality for auditability, safety and graceful degradation.

**Incident schema:** every incident has `incident_id`, `scenario_id`, `type` (flood, weather,
emergency, police, pothole, closure), `location` (SUMO edges/lanes), `start_time`, `duration_s`,
`severity` and `confidence` (0–1), and `source` (synthetic_scenario, scenario_engine,
agent_detection). Its lifecycle is detected -> active -> resolved (or cancelled), with each
transition logged against `run_id`/`scenario_hash`. Effects (capacity and speed multipliers, lane
closure, priority request) are removed on resolve or cancel, and an incident never writes a
signal directly.

---

## 7. Evidence, evaluation and honesty

**Seven provenance fields** on every Synapse response: `run_id`, `scenario_hash`, `event_id`,
`message_id`, `bundle_digest`, `corpus_hash`, `query_hash`. No event or evidence -> `abstain`;
missing policy support -> `template` with a policy-support marker.

**Identity contract:** `run_id` (one execution), `scenario_hash` (frozen inputs),
`configuration_hash` (controller, demand, faults), `event_id` (decision, fault, transition or
explanation target) and `message_id` (advisory publication). No API, UI, trace, RAG or report
layer may invent a replacement identity. Run manifests record status, timings, source revision,
SUMO version, hashes, controller and model versions, seeds and artifact references; bulk records
are Parquet, read with DuckDB.

**Metrics:**

| Area | Measures |
|---|---|
| Safety | Conflicting greens, clearance truncations, rejected illegal actions |
| Flow/reliability | Mean and P95 travel time and delay, variability, queues, stops, unfinished trips, teleports |
| Specialists | Emergency travel and civilian delay; pedestrian waits; bus headway and lateness; link-level emission proxies |
| Reliability | Message and controller faults, mode transitions, recovery, reproducibility |
| Synapse | Citation validity, event consistency, abstention, latency, cost, fallback |

**Evaluation method:** paired seeds against fixed-time and actuated baselines, ablations (each
adviser on/off), failure injection, tails and unfinished trips, and null or negative results kept.

**Reliability demonstration:** kill Synapse and the same inputs give the same actions; drop all
adviser messages and local Max-Pressure continues; silence A4 and the forecast becomes
"unavailable"; fail Max-Pressure and the actuated/fixed recovery is visible; remove retrieval and
the answer is a template, structured facts or an abstention.

**Test layers:** schema and property tests; single-junction integration; controller, safety and
cooperation acceptance tests; fault tests; paired evaluation and explanation golden tests.

**Claims that are never made (claim flags):**

- No lives saved from simulated emergency times.
- No measured air quality from SUMO/HBEFA emission proxies.
- No invented interview quotes or interview counts; personas are research-informed, not interviewed.
- No best-training-episode headline.
- No P95 that silently drops unfinished or teleported trips.
- No proposed target presented as achieved.
- No "X% of engineers distrust AI" figure (no such survey exists), no universal incident-detection delay.
- Tunis road demand is synthetic, and TRANSTU timetables are not road-outcome evidence.

**Status of results:** the J0 matched evidence was one seed with mixed results for Max-Pressure,
so no controller is declared the winner. traffix results on Tunis depend on the trained models
(section 14).

---

## 8. Design Thinking

### Course brief

Source: `SUMO_forStudents.docx` (creator recorded: Akermi Hasni).

> How might we use data and intelligent agents to make urban traffic more efficient, adaptive, and sustainable?

Required outcomes: a working prototype, experiments under different traffic conditions, a
comparison with an appropriate baseline, and data-driven strengths and limitations. Evidence
matters more than technological complexity. Suggested extensions: emergency vehicles,
pedestrians, public transport, sustainability, pollution, accidents, agent communication,
prediction, large networks.

| Brief question | CoFlow-5 answer |
|---|---|
| What information should an agent use? | Local SUMO observations plus typed, expiring, confidence-tagged advice |
| What decisions should it make? | A1 picks a legal signal action; A2–A5 request, forecast, alert or advise; Synapse explains |
| Independent or cooperating? | Cooperating: one writer, specialists ask, A1 arbitrates |
| How is performance evaluated? | Paired seeds vs fixed-time and actuated, stakeholder KPIs, ablations, failure injection, honest nulls |
| Which approaches? | Max-Pressure control, forecasting, retrieval-grounded explanations; RL optional |
| Beyond traffic flow? | Emergency passage, pedestrian clearance, transit regularity, emission proxies, incidents, communication faults, explainability |

Stages 1–3 (Empathize, Define, Ideate) were completed as research-informed work. The
23 September 2026 session was **proxy validation** by the six builders (± professor), not
stakeholder interviews.

### 5W1H and root cause

- **Who:** pedestrians, drivers, bus riders, emergency crews, residents and network operators.
- **What:** a reproducible SUMO prototype where agents cooperate, only one writes each light, and every decision is logged and testable.
- **Where:** first a controlled single junction (J0), then Tunis centre-ville on real OSM streets.
- **When:** a 12-week build, 23 September–15 December 2026.
- **Why:** average vehicle delay hides pedestrian safety, trip reliability, bus regularity, emergency side effects, local pollution displacement and silent failures.
- **How:** Design Thinking -> requirements -> smoke test -> evidence bundle -> safety and baselines -> Max-Pressure -> typed requests -> failure injection -> paired evaluation -> product.

**Five Whys:** a good average can fail people, because different groups' outcomes are hidden in
one number. They are hidden because each need is handled by a separate mechanism with no shared
record of trade-offs. That is dangerous because agents, sensors and models can fail or go stale
without a visible response. **Root need:** one safe authority arbitrating bounded specialist
advice, producing evidence anyone can check.

### Personas

Research-informed design tools, not interviewed people. The web app uses the deck names;
the system uses the canonical names.

| Canonical (deck name) | Role | Need | Solution | Evidence of success |
|---|---|---|---|---|
| Amara (Ferjani, 74) | Pedestrian with a cane (~0.8 m/s) | Enough time to finish crossing, tolerable wait | A3 publishes waiting/crossing state; A1 keeps clearance through the mask | Mean/P95/max wait, zero clearance truncations |
| David (Faycel, 41) | Driver (deck: bus driver; original: delivery driver) | Predictable journeys, not only a lower mean | Max-Pressure with downstream capacity; report tails | Mean/P95 travel time, stops, unfinished trips |
| Chidi (Mamadou, 25–27) | Bus passenger | Regular buses, no bunching | A3 asks for bounded priority only when a bus is late | Lateness, headway variation, effect on others |
| Rosa (Tahani, 35–52) | Depot controller / incident-report reader | Understand why priority was granted or refused | Reason-coded events and a read-only explanation view | Reason-code coverage, event completeness |
| Marcus (Touhami, 34–50) | Ambulance crew | Useful safe passage and recovery afterwards | A2 expiring corridor request; A1 checks downstream space and crossings | Emergency time, civilian delay, refused unsafe requests |
| Omar (Kamel, 55) | Duty officer | Trustworthy alerts; "unknown" differs from "clear" | A4 residual detection with confidence and expiry | Alert delay, false alarms, misses, stale handling |
| Yuki (infrastructure) | Traffic engineer | Diagnose, override and safely restore automation | One writer, health checks, safe override, deterministic recovery | Fault detection, transition records, safe override |
| Maria (infrastructure) | Parent near an arterial | Fixes must not move queues and exhaust to her street | A5 eco advice; link-level displacement checks | Link-level proxy maps, displacement test |

Shared journey used in workshops: an ambulance approaches while Amara is crossing, a late bus
arrives, queues grow near Maria's school street, and communication fails.

### Define

> Street users—pedestrians, drivers, bus riders, emergency crews, residents, and the people who
> run the network—need signal control that treats their different needs as first-class objectives
> with visible trade-offs, because separate mechanisms optimize vehicle throughput, hide who pays
> for whom, and can degrade silently when conditions or communication fail.

> How might we use data and intelligent agents to make urban traffic efficient, adaptive, and
> sustainable for every person on the network—not only the average car—while making trade-offs
> auditable and preserving safe control when components fail?

### Ideate

Methods: brainstorm/brainwrite, Worst Possible Idea, SCAMPER on the existing signal controller,
a morphological chart and a weighted decision matrix.

| Alternative | Benefit | Main problem | Decision |
|---|---|---|---|
| Central AI or RL controller | Uses the whole network state | Single failure point, hard to audit, training and safety risk | Rejected as the required design |
| Independent junction controllers | Simple, scalable | Weak coordination and specialist priority | Comparator only |
| Five equal signal-writing agents | Represents many goals | Conflicting commands, unclear responsibility | Rejected |
| One deterministic authority plus advisers | Explicit authority, visible trade-offs, graceful failure | Needs careful message and evidence contracts | **Chosen** |
| Hierarchical learned control | Regional coordination | Too costly and risky for 12 weeks | Future research |

| Deliberately bad idea | Principle learned |
|---|---|
| Let an LLM set phases | Synapse is read-only and separated from TraCI |
| Give all agents write access | Exactly one writer per signal |
| Always grant emergency or bus priority | Requests are conditional and bounded; side effects are recorded |
| Optimise average delay only | Report tails, unfinished trips, stakeholder outcomes, displacement |
| Trust every message forever | TTL, confidence, schema validation, idempotency, stale handling |

The chosen design fits beginners: Max-Pressure needs no training, advisers start as transparent
rules, the message board runs in one process, and each optional technology enters only after a
simpler interface passes its tests.

---

## 9. Requirements

| ID | Requirement |
|---|---|
| R0 | Keep Design Thinking traceability: six validation personas, plus Yuki and Maria as infrastructure personas |
| R1 | Working prototype, experiments, baselines, honest strengths and limits |
| R2 | Reproducible runs: versions, hashes, seeds, status, timing, artifacts |
| R3 | One-writer authority and deterministic signal safety |
| R4 | Cooperative Max-Pressure as the required control; works without RL |
| R5 | Typed, expiring, confidence-tagged, idempotent messages with dispositions |
| R6 | Safe emergency requests, downstream checks, arbitration and recovery |
| R7 | Protected pedestrian clearance; conditional late-transit priority |
| R8 | Bounded A4 situation and A5 sustainability advice, with limitations |
| R9 | Deterministic failure recovery; control unchanged when Synapse fails |
| R10 | Paired evaluation, ablations, failure sweeps, tails, error classification |
| R11 | Data schemas, chronological ML splits, sources and limitations |
| R12 | Synapse answers grounded in immutable events and allow-listed policy, with template/abstention |
| R13 | Typed API and operator views for runs, evidence, explanations and bounded what-if |
| R14 | Joined traces, versioned configuration, protected credentials, regression tests |
| R15 | Protect the core workstreams; cut optional complexity before rigour |

The product must not become an LLM traffic-light controller, five chatbots posing as agents, a
required RL project, a best-episode demo without fair baselines, or simulation presented as field
evidence.

---

## 10. Architecture decisions

### ADR-0001: a reliable AI decision platform (20 September 2026)

**Status:** Accepted

A deterministic, safety-constrained control plane owns SUMO actuation. A1 is the sole signal
authority, using cooperative Max-Pressure. A2, A3 and A5 are transparent advisers; A4 does bounded
forecasting and residual incident detection. Synapse is a non-actuating retrieval, explanation and
evaluation layer and never reaches TraCI. Agents are typed Python modules; LangGraph is limited to
Synapse approval/resume flows. Retrieval starts with exact local search (pgvector later for the
hosted product; Pinecone is not the default). A shared DQN is an optional experiment after the
cooperative core is frozen. Evaluation (baselines, paired seeds, invariants, failure injection,
citations, abstention, latency, cost) takes priority over feature count. Rejected: five LLM traffic
agents, LangGraph for A1–A5, RL as a core dependency, all-learned agents, Tunis-only or
synthetic-grid-only experiments.

### ADR-0002: six named builders, one active work item (22 September 2026)

**Status:** Accepted

Six builders work as three pairs (section 11). Only one work item is active at a time; extra
people do not authorise parallel product work. Changing one-writer authority, non-actuating
Synapse or required Max-Pressure needs a new ADR, not a workshop vote.

### ADR-0003: later DevOps/MLOps without live-signal deployment (22 September 2026)

**Status:** Accepted

Three consumers are kept apart: the **local runner** (native Windows Python 3.11 and pinned SUMO;
the control path), the **product API/UI** (FastAPI and React over precomputed evidence; hosted
containers contain no SUMO, and Synapse never reaches TraCI), and **offline analysis** (Parquet and
DuckDB joined on `run_id`/`scenario_hash`/`event_id`/`message_id`).

- PR CI (`.github/workflows/pr.yml`) stays SUMO-free: architecture and read-only API tests plus `compileall`.
- Eval CI (`.github/workflows/eval.yml`) runs only on a SUMO-capable runner (`workflow_dispatch`, or nightly when `SUMO_RUNNER=true`) and fails if `libsumo` cannot load.
- `deploy/` images serve tagged evidence and never ship `sumo`, `traci` or `libsumo`.
- MLflow is optional. It may index `run_id`, `scenario_hash` and artifact paths, but it must not mint a second run identity; the run manifest is the source of truth.
- Docker is not a required smoke-test command. Packaging is a later product path only.
- Never: deployment into a real signal cabinet, lives-saved claims, measured air quality, Kafka, Kubernetes, or Pinecone by default.

Rollback for the hosted product is the previous git tag of the API image plus the previous tagged
evidence bundle.

### ADR-0004: traffix hierarchy with CoFlow Synapse on the Tunis six-junction map (16 October 2026)

**Status:** Accepted

The traffix3 code lives here (`traffix/`, `config/`, `models/`, `frontend/`, scripts). The default
network is `tunis6j`, where only J1..J6 have lights, so each light has exactly one master.
Network-specific facts live in `config/networks/<network>.yaml`. CoFlow's `SynapseService` is
attached to the traffix decision log by `traffix/synapse/coflow_bridge.py`, read-only. Models in
`models/` must be retrained whenever the network or demand changes. traffix3 has no licence file:
add one, or get the author's written permission, before any public release.

---

## 11. Team and delivery plan

Team (ESPRIT 4DS): Aziz Messaoud, Eya Laourine, Fares Ben Kacem, Mohamed Aymen Hamzaoui,
Oumayma Saddouri, Ranim Ben Salem.

| Pair | People | Area |
|---|---|---|
| Control | Aziz Messaoud, Fares Ben Kacem | SUMO, observations, A1, safety, controllers |
| Data/Evaluation | Mohamed Aymen Hamzaoui, Oumayma Saddouri | Scenarios, manifests, Parquet/DuckDB, KPIs, Tunis data |
| Cooperation/Product | Eya Laourine, Ranim Ben Salem | Messages, A2/A3, API, Synapse, UI |

For each work item one pair builds, one pair writes and runs independent tests, and one pair
prepares the demo and a beginner-level explanation. Roles rotate. Only tests and files can mark
work done.

Twelve-week plan (23 September–15 December 2026):

| Week | Goal |
|---|---|
| 1 | Proxy validation; native toolchain smoke test |
| 2 | Evidence bundle: run identities, manifest, Parquet, DuckDB |
| 3 | Safety mask: only the A1 executor can write; illegal actions rejected with reasons |
| 4 | Fixed-time and actuated baselines on matched seeds |
| 5 | Cooperative Max-Pressure with an empty message board |
| 6 | Typed message board: TTL, idempotency, dispositions |
| 7 | A2 emergency and A3 pedestrian/transit requests |
| 8 | Failure injection and the recovery ladder |
| 9 | Paired evaluation and ablations; freeze the core |
| 10 | A4/A5 advice, matched Max-Pressure trip KPIs, evidence page |
| 11 | Bounded Synapse explanations, then the API and React views |
| 12 | Tunis showcase, final checks, report |

Cut order if time runs short: optional DQN, Tunis showcase, React view, API, before weakening the
control and evidence core. Final demo: a frozen scenario with its manifest; fixed-time vs actuated
vs Max-Pressure on matched evidence; one request with its disposition and reason code; dropped
messages and a controller failure showing recovery; Synapse killed with traffic unchanged, then a
cited or template explanation. The headline is that authority, evidence, failure and trade-offs are
measurable, not "AI improved traffic by X%".

---

## 12. Data sources

| Source | Identity | Use |
|---|---|---|
| OpenStreetMap via [Geofabrik Tunisia](https://download.geofabrik.de/africa/tunisia.html) | Clipped source snapshot: `scenarios/tunis-showcase/tunis.osm.xml`; hash recorded in `scenarios/tunis-centre-6j/junctions.json` | Road topology. Original country PBF and its historic checksum are not included in this checkout, so the original PBF timestamp/checksum cannot be verified here. |
| TRANSTU-attributed line visualization ([community-published source](https://hobbes-286.github.io/transtu-visualisation/)) | `scenarios/tunis-centre-6j/tunis6j.transtu.csv`; source hash in `tunis6j.lines.json` | Stop/line geometry mapped to OSM roads; not an official GTFS/timetable and not independently validated. |
| Previously referenced TRANSTU GTFS archive | Archive is not present in this checkout; its publisher and recorded checksum cannot be independently verified here. | Do not use as evidence of official scheduled service unless the original feed and publisher are confirmed. |
| Esri World Street Map / World Imagery tiles | attribution in the app | Background map and satellite overlay |

Selected OSM junctions: 5294059357 (J1), 287386655 (J2), 287837812 (J3), 287863982 (J4),
387151856 (J5), 517939913 (J6). Wider showcase bounding box: 10.127879, 36.787714, 10.233358,
36.820741 (left, bottom, right, top); the six-junction network uses 10.1755, 36.7925, 10.1910, 36.8055.

---

## 13. Research evidence behind the personas

These sources motivate the needs; they do not set the project's targets.

| Topic | Finding | Source |
|---|---|---|
| Pedestrian wait | Frustration rises after 20–30 s; perceived wait ≈ 2x actual; compliance drops after 30 s | NZTA RR440 (2009); Vallyon, Turner & Hodgson, ATRF (2009); TfL via London Assembly (2019) |
| Accessibility | Leading pedestrian intervals cut pedestrian crashes (NYC −28%, FHWA CMF 0.87); cane ≈ 0.8 m/s, walker 0.6 m/s; MUTCD clearance 1.07 m/s | FHWA-HRT-18-060 (2018); LaPlante & Kaese (ITE); MUTCD 2009 §4E |
| Transit | Waiting valued ~2x in-vehicle time; bunching is self-reinforcing; SCOOT bus priority cut bus times 39% | DfT TAG A1.3; TR Part C review (2024); Hounsell & McDonald (1986) |
| Emergency | Each minute of ALS delay: survival −7%; emergency preemption cuts response 14–23% but adds 20–30 s on arterials | PLOS One (2022); USFA/USDOT ITS JRS; Nelson & Bullock TRR 1727 (2000) |
| Operations | SCATS ships manual intervention and audit trails; Surtrac falls back to defaults on sensor failure | Transport NSW (2022); CMU Surtrac pilot report |
| Exposure | 13.5% of US children live within 250 m of a major road; ~33% of public schools within 400 m | Kingsley et al. IJERPH (2014); Appatova et al. (2008) |
| Emissions | A stopped heavy vehicle emits >5x the NOx of one slowing down | Deschle et al., Energies 15:1242 (2022) |
| Reliability | Reliability ratio 0.4 for cars; incidents cause ~25% of congestion delay | DfT TAG A1.3; FHWA |

---

## 14. Known limitations

- **Synthetic demand.** Car and pedestrian trips are generated from a calendar model; bus headways are assumed. Calendar values are project assumptions.
- **Controller results are mixed.** Re-measured on the current network with 3 seeds (`results/`, see `docs/presentation/prototype-validation.md` §5.3): far fewer greens during crossings and lower pedestrian waits, mixed car waits, slower ambulances than SUMO's plans, nothing significant yet. The models were retrained on the current Tunis network (`models/metrics.json`). Sensor health uses its rule (the retrained model scored F1 0.752 vs 0.978, so it was deleted). Incident detection uses its rule: training had no labelled incidents because the training incident places had no detector (fixed in `config/networks/tunis6j.yaml`; retrain to get an incident model). `scripts\train.py` still saves `sensor_health.joblib` on every run: delete it after retraining.
- **Unsignalised side streets** yield on the real grid, so car waits are higher than on the schematic network; `demand.base_vehicles_per_hour` is 2400 for this map.
- **`libsumo` is blocked** by Windows application control on the development machine; TraCI is used.
- **J0 evidence** is one matched seed with mixed Max-Pressure results; no winner is claimed.
- **14 residential side streets** are two-way in OSM but one-way in the SUMO network; none touch J1..J6.
- **traffix3 licence** is missing; see ADR-0004.
- **`priority_order` in `config/agents.yaml`** is not read by the code; the masters hard-code the same order.

---

## 15. Glossary

| Term | Meaning |
|---|---|
| Ablation | The same experiment with one agent or feature turned off |
| Actuated control | Rule-based signals that respond to detected vehicles |
| Claim flag | A statement the project must not make without valid evidence |
| Control plane | Safety-critical code that observes SUMO and executes legal actions |
| Cooperative Max-Pressure | Controller using queue pressure, downstream space and valid requests |
| Evidence bundle | Manifest plus artifacts that make one run reproducible and auditable |
| Idempotency | Processing the same message twice has no second effect |
| Paired seeds | Controllers run on identical random scenarios so differences are fair |
| Proxy validation | Team walkthrough of personas; not an interview with real users |
| Reason code | Structured reason for accepting, rejecting, deferring or recovering |
| Synapse | The non-actuating layer that explains logged decisions |
| TTL | Time-to-live; an expired message cannot influence a decision |
