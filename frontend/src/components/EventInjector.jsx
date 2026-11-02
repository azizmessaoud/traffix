import { useEffect, useMemo, useState } from "react";
import { api } from "../api.js";

function time(value) {
  if (typeof value !== "number") return "";
  return new Date(value * 1000).toLocaleTimeString();
}

export default function EventInjector({ live }) {
  const [options, setOptions] = useState([]);
  const [edgeId, setEdgeId] = useState("");
  const [laneIndex, setLaneIndex] = useState(0);
  const [duration, setDuration] = useState(180);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [failure, setFailure] = useState("");
  const events = live.world_events || [];
  const active = live.status === "running";

  useEffect(() => {
    if (!active) { setOptions([]); return; }
    let alive = true;
    api("/event-options").then((result) => {
      if (!alive) return;
      setOptions(result.edges || []);
      setEdgeId((current) => current || result.edges?.[0]?.edge_id || "");
    }).catch((error) => { if (alive) setFailure(error.message); });
    return () => { alive = false; };
  }, [active]);

  const edge = useMemo(() => options.find((item) => item.edge_id === edgeId), [options, edgeId]);
  useEffect(() => { if (edge && !edge.lanes.includes(laneIndex)) setLaneIndex(edge.lanes[0]); }, [edge, laneIndex]);

  async function inject(e) {
    e.preventDefault();
    setBusy(true); setFailure(""); setMessage("");
    try {
      const result = await api("/events", { method: "POST", body: JSON.stringify({
        request_id: crypto.randomUUID(), edge_id: edgeId,
        lane_index: Number(laneIndex), duration_seconds: Number(duration),
      }) });
      setMessage(`Incident ${result.event_id.slice(0, 8)} queued.`);
    } catch (error) { setFailure(error.message); }
    finally { setBusy(false); }
  }

  return (
    <section className="card event-panel">
      <div>
        <h2>Live event injection</h2>
        <p className="muted">Add a simulated stalled vehicle while the run is active. The live map marks injected vehicles in red.</p>
      </div>
      <form className="event-controls" onSubmit={inject}>
        <label>Road
          <select value={edgeId} onChange={(e) => setEdgeId(e.target.value)} disabled={!active || !options.length} required>
            {options.map((item) => <option key={item.edge_id} value={item.edge_id}>{item.name} · {item.edge_id}</option>)}
          </select>
        </label>
        <label>Lane
          <select value={laneIndex} onChange={(e) => setLaneIndex(Number(e.target.value))} disabled={!active || !edge}>
            {(edge?.lanes || []).map((lane) => <option key={lane} value={lane}>{lane + 1}</option>)}
          </select>
        </label>
        <label>Duration (simulation seconds)
          <input type="number" min="10" max="1800" step="10" value={duration}
                 onChange={(e) => setDuration(e.target.value)} disabled={!active} />
        </label>
        <button className="primary" disabled={!active || busy || !edgeId}>{busy ? "Queueing…" : "Inject lane blockage"}</button>
      </form>
      {!active && <span className="muted">Start a simulation to enable event controls.</span>}
      {message && <span className="pill ok" role="status">{message}</span>}
      {failure && <span className="pill bad" role="alert">{failure}</span>}
      <div>
        <h3>Event timeline</h3>
        {events.length === 0 ? <p className="muted">No operator-injected events in this run.</p> : (
          <div className="event-timeline">
            {[...events].reverse().map((event) => (
              <div className="event-row" key={event.event_id}>
                <span className={`pill ${event.status === "completed" ? "info" : event.status === "rejected" || event.status === "cancelled" ? "bad" : "warn"}`}>{event.status}</span>
                <span>Stalled vehicle · {event.edge_id} · lane {event.lane_index + 1}</span>
                <span className="muted">{event.applied_at != null ? `applied ${Math.round(event.applied_at)}s` : `queued ${time(event.queued_at)}`}</span>
                {event.detected_at != null && <span className="pill ok">detector observed at {Math.round(event.detected_at)}s</span>}
                {event.error && <span className="pill bad">{event.error}</span>}
              </div>
            ))}
          </div>
        )}
      </div>
      <p className="muted event-note">Injected events and agent detections are recorded separately. Detection may take time and is not guaranteed.</p>
    </section>
  );
}
