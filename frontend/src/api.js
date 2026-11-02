// All data comes from the Python backend (supermaster API). Nothing talks to SUMO directly.
import { useEffect, useState } from "react";

export async function api(path, options = {}) {
  const headers = new Headers(options.headers || {});
  try {
    const token = sessionStorage.getItem("traffix-operator-token");
    if (token) headers.set("Authorization", `Bearer ${token}`);
  } catch { /* sessionStorage may be unavailable in private browser modes */ }
  if (options.body && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
  const res = await fetch(`/api${path}`, { ...options, headers });
  if (!res.ok) {
    const text = await res.text();
    let detail = text;
    try { detail = JSON.parse(text).detail || text; } catch { /* not JSON */ }
    if (typeof detail !== "string") detail = JSON.stringify(detail);   // FastAPI 422: a list of objects
    throw new Error(`${res.status} ${detail}`);
  }
  return res.json();
}

// Polls the live snapshot once per second.
export function useLive() {
  const [state, setState] = useState({ status: "idle" });
  useEffect(() => {
    let alive = true;
    const tick = async () => {
      try {
        const s = await api("/state");
        if (alive) setState(s);
      } catch {
        if (alive) setState({ status: "offline" });
      }
    };
    tick();
    const id = setInterval(tick, 1000);
    return () => { alive = false; clearInterval(id); };
  }, []);
  return state;
}

export function useOnce(path, deps = []) {
  const [data, setData] = useState(null);
  useEffect(() => {
    if (!path) { setData(null); return; }        // nothing to fetch yet
    api(path).then(setData).catch(() => setData(null));
  }, deps);
  return data;
}

export const PERSONAS = [
  { id: "pedestrian", path: "/pedestrian", name: "Ferjani", role: "Pedestrian" },
  { id: "car_driver", path: "/driver", name: "Faycel", role: "Car driver" },
  { id: "bus_passenger", path: "/passenger", name: "Mamadou", role: "Bus passenger" },
  { id: "bus_driver", path: "/bus-driver", name: "Hédi", role: "Bus driver" },
  { id: "emergency_crew", path: "/emergency", name: "Touhami", role: "Ambulance crew" },
  { id: "operator", path: "/operator", name: "Kamel", role: "Traffic operator" },
  { id: "analyst", path: "/analyst", name: "Tahani", role: "Incident analyst" },
];
