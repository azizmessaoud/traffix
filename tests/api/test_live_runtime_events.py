from __future__ import annotations

import os
import queue
import threading

import pytest
from types import SimpleNamespace
from traffix.api.live import LiveRun
from traffix.core import config
from fastapi import HTTPException
from traffix.api.server import require_operator


def _run() -> LiveRun:
    run = object.__new__(LiveRun)
    run.running = True
    run._incident_lanes = {"edge-a": [0, 1]}
    run.lock = threading.Lock()
    run.world_events = []
    run._event_requests = {}
    run.event_commands = queue.Queue(maxsize=20)
    return run


def test_incident_request_is_validated_and_enqueued_without_simulator_access() -> None:
    run = _run()

    event = run.enqueue_incident("edge-a", 1, 180, "request-1")

    assert event["status"] == "queued"
    assert event["edge_id"] == "edge-a"
    assert run.event_commands.get_nowait() == event["event_id"]


@pytest.mark.parametrize(("edge", "lane", "duration"), [
    ("missing", 0, 180), ("edge-a", 4, 180), ("edge-a", 0, 9), ("edge-a", 0, 1801),
])
def test_incident_request_rejects_invalid_targets_and_duration(edge, lane, duration) -> None:
    with pytest.raises(ValueError):
        _run().enqueue_incident(edge, lane, duration, "request-1")


def test_event_queue_full_rejects_and_records_event() -> None:
    run = _run()
    run.event_commands = queue.Queue(maxsize=1)
    run.event_commands.put_nowait("already-pending")

    with pytest.raises(ValueError, match="queue is full"):
        run.enqueue_incident("edge-a", 0, 60, "request-1")

    assert run.world_events[0]["status"] == "rejected"


def test_idempotency_key_replays_one_event_and_rejects_parameter_changes() -> None:
    run = _run()
    first = run.enqueue_incident("edge-a", 0, 60, "request-1")

    replay = run.enqueue_incident("edge-a", 0, 60, "request-1")
    assert replay["event_id"] == first["event_id"]
    assert run.event_commands.qsize() == 1

    with pytest.raises(ValueError, match="different event parameters"):
        run.enqueue_incident("edge-a", 1, 60, "request-1")


def test_stopping_cancels_commands_that_were_not_applied() -> None:
    run = _run()
    event = run.enqueue_incident("edge-a", 0, 60, "request-1")

    run._cancel_pending_events()

    assert run.world_events[0]["event_id"] == event["event_id"]
    assert run.world_events[0]["status"] == "cancelled"
    assert run.event_commands.empty()


def test_queued_command_is_applied_by_the_simulation_loop_thread() -> None:
    run = _run()
    event = run.enqueue_incident("edge-a", 0, 60, "request-1")
    observed = {}

    class FakeWorld:
        def inject_incident(self, command, now):
            observed["thread_id"] = threading.get_ident()
            observed["event_id"] = command["event_id"]
            return {"vehicle_id": "incident-test", "applied_at": now}

    owner_thread = threading.get_ident()
    run._apply_queued_events(FakeWorld(), 12)

    assert observed == {"thread_id": owner_thread, "event_id": event["event_id"]}
    assert run.world_events[0]["status"] == "applied"
    assert run.world_events[0]["applied_at"] == 12


def test_detector_observation_is_recorded_separately_from_injection(monkeypatch) -> None:
    from traffix.api import live as live_module

    run = _run()
    event = run.enqueue_incident("edge-a", 0, 60, "request-1")
    run.world_events[0].update(status="applied", vehicle_id="incident-test", applied_at=1)
    run.system = SimpleNamespace(bus=SimpleNamespace(published=lambda kind: [
        SimpleNamespace(subject="edge-a", details={"lane": "edge-a_0"})
    ]))
    monkeypatch.setattr(live_module, "traci", SimpleNamespace(
        vehicle=SimpleNamespace(getIDList=lambda: ["incident-test"]),
    ))

    run._update_world_events(21)

    assert run.world_events[0]["event_id"] == event["event_id"]
    assert run.world_events[0]["status"] == "detected"
    assert run.world_events[0]["detected_at"] == 21


def test_event_is_not_completed_before_vehicle_has_entered_simulation(monkeypatch) -> None:
    from traffix.api import live as live_module

    run = _run()
    run.enqueue_incident("edge-a", 0, 60, "request-1")
    run.world_events[0].update(status="applied", vehicle_id="incident-test", applied_at=1)
    run.system = SimpleNamespace(bus=SimpleNamespace(published=lambda kind: []))
    monkeypatch.setattr(live_module, "traci", SimpleNamespace(
        vehicle=SimpleNamespace(getIDList=lambda: []),
    ))

    run._update_world_events(2)
    assert run.world_events[0]["status"] == "applied"

    monkeypatch.setattr(live_module, "traci", SimpleNamespace(
        vehicle=SimpleNamespace(getIDList=lambda: ["incident-test"]),
    ))
    run._update_world_events(3)
    monkeypatch.setattr(live_module, "traci", SimpleNamespace(
        vehicle=SimpleNamespace(getIDList=lambda: []),
    ))
    run._update_world_events(4)
    assert run.world_events[0]["status"] == "completed"
    assert run.world_events[0]["completed_at"] == 4


def test_mutating_live_api_auth_check_requires_the_configured_bearer_token(monkeypatch) -> None:
    monkeypatch.setenv("TRAFFIX_OPERATOR_TOKEN", "test-secret")
    monkeypatch.setenv("TRAFFIX_REQUIRE_OPERATOR_TOKEN", "1")
    with pytest.raises(HTTPException) as unauthenticated:
        require_operator(None)
    assert unauthenticated.value.status_code == 401
    require_operator("Bearer test-secret")

    monkeypatch.setenv("TRAFFIX_OPERATOR_TOKEN", "")
    with pytest.raises(HTTPException) as misconfigured:
        require_operator(None)
    assert misconfigured.value.status_code == 503


def test_closed_intake_refuses_new_events_and_drain_cancels_queued_ones() -> None:
    run = _run()
    queued = run.enqueue_incident("edge-a", 0, 60, "request-1")

    run._close_intake()                 # the simulation is stopping or has finished
    run._cancel_pending_events()

    assert run.world_events[0]["event_id"] == queued["event_id"]
    assert run.world_events[0]["status"] == "cancelled"
    with pytest.raises(ValueError, match="No running simulation"):
        run.enqueue_incident("edge-a", 0, 60, "request-2")
    assert len(run.world_events) == 1      # nothing stranded in the queue after the drain
    assert run.event_commands.empty()


@pytest.mark.skipif(not os.path.exists(config.network_files()[0]), reason="Tunis network not generated")
def test_incident_options_only_offer_lanes_the_detector_reads() -> None:
    pytest.importorskip("sumolib")          # reads the network with SUMO's own parser
    from traffix.simulation.network_model import load_models

    net = config.network_files()[0]
    run = object.__new__(LiveRun)
    run.geometry = {}
    run._static(net)
    observed = {lane for m in load_models(net).values() for lane in m.incoming_lanes + m.outgoing_lanes}
    offered = {f"{o['edge_id']}_{lane}" for o in run.incident_options for lane in o["lanes"]}

    assert offered and offered <= observed
    assert "-100080970_1" not in offered    # a lane with no junction sensor cannot be detected


class FatalTraCIError(Exception):
    """Same class name as traci's error: the run handler decides by name."""


@pytest.mark.parametrize(("started", "expected"), [
    (False, "SUMO did not start"),
    (True, "SUMO stopped"),
])
def test_run_error_says_whether_sumo_never_started_or_stopped_mid_run(started, expected) -> None:
    run = _run()
    run.snapshot = {"status": "starting"}
    if started:
        run.sumo_started = True

    def failing_simulate():
        raise FatalTraCIError("Could not connect in 11 tries")

    run._simulate = failing_simulate
    run._run()

    assert run.snapshot["status"] == "error"
    assert run.snapshot["error"].startswith(expected)
    assert run.running is False
