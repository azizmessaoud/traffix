import { Link } from "react-router-dom";
import { PERSONAS } from "../api.js";
import NetworkMap from "../components/NetworkMap.jsx";
import { Stat } from "../components/Feed.jsx";
import EventInjector from "../components/EventInjector.jsx";

const TEXT = {
  pedestrian: "Crossing status, waits and walk-signal alerts",
  car_driver: "Congestion, incidents, floods and Route B",
  bus_passenger: "Where the buses are and which are late",
  bus_driver: "Schedule gap and bus priority at each junction",
  emergency_crew: "Green requests, grants and blocked exits",
  operator: "Every junction, alert and sensor in one view",
  analyst: "The decision log and Synapse explanations",
};

export default function Home({ live }) {
  const running = live.status === "running" || live.status === "finished";
  return (
    <>
      <div>
        <h1>Central Tunis, one hierarchy of agents</h1>
        <p className="muted" style={{ maxWidth: 720 }}>
          Five agents at each junction advise a master, the only writer of its light. A supermaster with
          eight network agents coordinates the masters. Pick a scenario above, then open a persona page.
        </p>
      </div>
      {running && (
        <div className="grid g4">
          <Stat label="vehicles in the network" value={live.counts?.vehicles ?? 0} />
          <Stat label="pedestrians walking" value={live.counts?.pedestrians ?? 0} />
          <Stat label="decisions logged" value={live.counts?.decisions ?? 0} />
          <Stat label="active alerts" value={(live.incidents?.length || 0) + (live.floods?.length || 0)}
                tone={(live.incidents?.length || live.floods?.length) ? "#e6a23c" : undefined} />
        </div>
      )}
      <NetworkMap live={live} height={380}
                  highlight={{ incidents: [...(live.incidents?.map((i) => i.subject) || []),
                    ...(live.world_events?.filter((e) => ["applied", "detected"].includes(e.status)).map((e) => e.edge_id) || [])],
                    floods: live.floods?.map((f) => f.subject) }} />
      <EventInjector live={live} />
      <div className="grid g4 persona-grid">
        {PERSONAS.map((p) => (
          <Link key={p.id} to={p.path} className="card">
            <h3>{p.role}</h3>
            <span className="muted">{p.name} · {TEXT[p.id]}</span>
          </Link>
        ))}
      </div>
    </>
  );
}
