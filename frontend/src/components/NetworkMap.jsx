import { useEffect, useRef, useState } from "react";
import { useOnce } from "../api.js";

// Vehicles are drawn top-down at their real size in metres (SUMO defaults), with a minimum size on
// screen so they stay visible when zoomed out. Shapes point along +x and are rotated to the heading.
const VEHICLES = {
  car: { L: 4.5, W: 1.85, min: 9, fill: "#c9d1d8", label: "Car" },
  moto: { L: 2.1, W: 0.8, min: 6, fill: "#f2c47a", label: "Motorcycle" },
  bus: { L: 12, W: 2.55, min: 16, fill: "#2f7fd8", label: "Bus" },
  ambulance: { L: 5.8, W: 2.1, min: 11, fill: "#ffffff", label: "Ambulance" },
  police: { L: 4.8, W: 1.9, min: 10, fill: "#1f3fbf", label: "Police" },
  fire: { L: 9, W: 2.5, min: 14, fill: "#d8261c", label: "Fire truck" },
  incident: { L: 4.5, W: 1.85, min: 10, fill: "#ff3b30", label: "Stalled vehicle" },
};
// Paint mix of cars in Tunis traffic; "taxi" is the yellow city taxi.
const CAR_PAINTS = [["#f4f4f2", 28], ["#b8bec4", 18], ["#6b7178", 11], ["#1d2126", 12], ["taxi", 13],
  ["#9e2a2b", 6], ["#2d4f8a", 6], ["#d8cdb4", 4], ["#3f6b4a", 2]];
const PAINT_TOTAL = CAR_PAINTS.reduce((a, [, w]) => a + w, 0);
function hash(s) {
  let h = 2166136261;
  for (let i = 0; i < s.length; i++) h = Math.imul(h ^ s.charCodeAt(i), 16777619);
  return h >>> 0;
}
function paint(id) {
  let r = hash(id) % PAINT_TOTAL;
  for (const [c, w] of CAR_PAINTS) { if ((r -= w) < 0) return c; }
  return CAR_PAINTS[0][0];
}

// One vehicle in its own frame: x forward, metres. detail adds lights and markings when big enough to see.
function VehicleShape({ v, kind, detail }) {
  const s = VEHICLES[kind] || VEHICLES.car;
  const h = s.L / 2, w = s.W / 2;
  const shadow = <rect x={-h + 0.25} y={-w + 0.3} width={s.L} height={s.W} rx={w * 0.7} fill="#000" opacity="0.35" />;
  const lights = detail && <>
    <rect x={h - 0.25} y={-w + 0.15} width={0.2} height={0.45} fill="#fff6c8" />
    <rect x={h - 0.25} y={w - 0.6} width={0.2} height={0.45} fill="#fff6c8" />
    <rect x={-h + 0.05} y={-w + 0.15} width={0.2} height={0.45} fill="#ff3b30" />
    <rect x={-h + 0.05} y={w - 0.6} width={0.2} height={0.45} fill="#ff3b30" />
  </>;
  if (kind === "moto") {
    return <>
      <ellipse cx={0.25} cy={0.2} rx={h} ry={w} fill="#000" opacity="0.3" />
      <ellipse cx={0} cy={0} rx={h} ry={w * 0.75} fill={s.fill} />
      <circle cx={-0.15} cy={0} r={0.42} fill="#2a2f36" />
    </>;
  }
  if (kind === "bus" || kind === "fire") {
    return <>
      {shadow}
      <rect x={-h} y={-w} width={s.L} height={s.W} rx={0.45} fill={s.fill} stroke="#0008" strokeWidth={0.08} />
      <rect x={h - 0.9} y={-w + 0.2} width={0.7} height={s.W - 0.4} rx={0.2} fill="#17202b" />
      {kind === "bus" && <>
        <rect x={-h + 1.2} y={-w + 0.35} width={2.2} height={s.W - 0.7} rx={0.2} fill="#d9dee3" />
        <rect x={-h + 4.4} y={-w + 0.55} width={1.4} height={s.W - 1.1} rx={0.2} fill="#d9dee3" />
        {detail && v.line && <text x={1.2} y={0.55} textAnchor="middle" fontSize={1.5} fontWeight="700"
                                   fill="#fff" fontFamily="IBM Plex Sans">{v.line.replace("_R", "")}</text>}
      </>}
      {kind === "fire" && [-2.4, -1, 0.4, 1.8].map((x) => (
        <rect key={x} x={x} y={-0.55} width={0.25} height={1.1} fill="#e6e6e6" />))}
      {kind === "fire" && <rect x={-h + 0.6} y={-0.6} width={s.L - 2.4} height={0.18} fill="#e6e6e6" />}
      {lights}
    </>;
  }
  const fill = kind === "car" ? paint(v.id) : s.fill;
  const body = fill === "taxi" ? "#f7c600" : fill;
  return <>
    {shadow}
    <rect x={-h} y={-w} width={s.L} height={s.W} rx={w * 0.7} fill={body} stroke="#0007" strokeWidth={0.07} />
    {/* windscreen (front) and rear window */}
    <path d={`M${h * 0.18},${-w * 0.78} L${h * 0.52},${-w * 0.66} L${h * 0.52},${w * 0.66} L${h * 0.18},${w * 0.78} Z`}
          fill="#16202b" opacity="0.9" />
    <path d={`M${-h * 0.5},${-w * 0.72} L${-h * 0.72},${-w * 0.62} L${-h * 0.72},${w * 0.62} L${-h * 0.5},${w * 0.72} Z`}
          fill="#16202b" opacity="0.85" />
    {fill === "taxi" && <rect x={-0.35} y={-0.35} width={0.7} height={0.7} rx={0.1} fill="#fff" stroke="#222" strokeWidth={0.05} />}
    {kind === "police" && <>
      <rect x={-0.9} y={-w} width={1.4} height={s.W} fill="#fff" />
      <rect x={-0.25} y={-w * 0.8} width={0.4} height={w * 0.8} fill="#ff2d2d" />
      <rect x={-0.25} y={0} width={0.4} height={w * 0.8} fill="#2d6bff" />
    </>}
    {kind === "ambulance" && <>
      <rect x={-h} y={-0.2} width={s.L} height={0.4} fill="#ff3b30" />
      <rect x={-1.6} y={-0.15} width={1.2} height={0.3} fill="#ff3b30" />
      <rect x={-1.15} y={-0.6} width={0.3} height={1.2} fill="#ff3b30" />
      <rect x={0.7} y={-w * 0.8} width={0.35} height={s.W * 0.8} fill="#2d6bff" />
    </>}
    {lights}
  </>;
}

// Positions arrive once a second; CSS glides each vehicle to its new place over that second.
function Vehicle({ v, x, y, angle, focused, mpp }) {
  const kind = VEHICLES[v.kind] ? v.kind : "car";
  const s = VEHICLES[kind];
  const k = Math.max(1, (s.min * mpp) / s.L) * (focused ? 1.6 : 1);   // never shorter than s.min px on screen
  const detail = (s.L * k) / mpp > 22;
  return (
    <g style={{ transform: `translate(${x}px, ${y}px) rotate(${angle - 90}deg)`, transition: "transform 1s linear" }}>
      <g transform={`scale(${k})`}>
        {focused && <circle r={s.L * 0.75} fill="none" stroke="#fff" strokeWidth={0.35} />}
        <VehicleShape v={v} kind={kind} detail={detail} />
      </g>
    </g>
  );
}

export function Legend() {
  return (
    <div style={{ display: "flex", gap: 16, flexWrap: "wrap", fontSize: 13 }} className="muted">
      <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
        <svg width="26" height="12" aria-hidden="true"><rect x="1" y="2" width="24" height="8" rx="3" fill="#f7c600" stroke="#0006" strokeWidth="1" /></svg>Taxi
      </span>
      {Object.entries(VEHICLES).map(([k, s]) => (
        <span key={k} style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
          <svg width="26" height="12" aria-hidden="true">
            <rect x="1" y="2" width="24" height="8" rx="3" fill={s.fill} stroke="#0006" strokeWidth="1" />
            {k === "ambulance" && <rect x="1" y="5" width="24" height="2" fill="#ff3b30" />}
            {k === "police" && <rect x="10" y="2" width="6" height="8" fill="#fff" />}
          </svg>{s.label}
        </span>
      ))}
      <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
        <svg width="12" height="12" aria-hidden="true"><circle cx="6" cy="6" r="4" fill="#e8ecef" /></svg>Pedestrian
      </span>
      <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
        <svg width="12" height="12" aria-hidden="true"><circle cx="6" cy="6" r="4" fill="#ff4fd8" /></svg>Slow walker
      </span>
      <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
        <svg width="34" height="12" aria-hidden="true">
          <circle cx="6" cy="6" r="4.5" fill="#ff4a3a" /><circle cx="17" cy="6" r="4.5" fill="#ffc83d" />
          <circle cx="28" cy="6" r="4.5" fill="#35d07f" /></svg>Traffic light
      </span>
      <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
        <svg width="26" height="12" aria-hidden="true"><line x1="1" y1="6" x2="25" y2="6" stroke="#35d07f" strokeWidth="4" strokeDasharray="2.5 2.5" /></svg>Crossing (green = walk)
      </span>
      <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
        <svg width="14" height="14" aria-hidden="true"><rect x="1" y="1" width="12" height="12" rx="3" fill="#1d4f9c" stroke="#fff" />
          <text x="7" y="10.5" textAnchor="middle" fontSize="9" fill="#fff" fontWeight="700">B</text></svg>Bus stop
      </span>
    </div>
  );
}

// Draws the Tunis network, junction states, vehicles and pedestrians. Zoom with the mouse wheel,
// drag to pan, double-click or the reset button to fit the whole network again.
// highlight: { incidents, floods, routeB, alt } (edge ids), focus: vehicle ids to emphasise
const LINE_PALETTE = ["#4cc3ff", "#ff8a3d", "#b78cff", "#3ddc97", "#ff5c8a", "#ffd23f", "#5c9bea", "#e86bff", "#9be15d"];
// Same colour for both directions of a line; the return trip ("_R") is drawn dashed.
export const lineColor = (id) => LINE_PALETTE[hash(id.replace(/_R$/, "")) % LINE_PALETTE.length];

// Street map under the simulation, already warped into SUMO x/y by scripts/build_basemap.py.
// "dark" is the street map recoloured in the browser for the dark theme.
const BASEMAPS = {
  dark: { style: "streets", label: "Dark streets", filter: "invert(1) hue-rotate(180deg) brightness(0.95) contrast(0.85)" },
  streets: { style: "streets", label: "Streets" },
  satellite: { style: "satellite", label: "Satellite" },
  off: { label: "No map" },
};
// Live web-map tiles at the zoom that matches the view. Each tile is placed by the exact
// net <-> web-map transform from scripts/build_basemap.py (affine, a few cm over the network),
// so it stays sharp at every zoom. A coarser layer underneath fills gaps while sharp tiles load.
function Tiles({ basemap, style, view, box, mpp, origin }) {
  const url = basemap.tiles?.[style], fwd = basemap.net_to_merc, inv = basemap.merc_to_net;
  if (!url || !fwd || !inv) return null;
  const [x0, y1, pad] = origin;
  const [A, B, C, D, E, F] = inv;                    // net x = A u + B v + C, y = D u + E v + F
  const w = box?.width ? box.width * mpp : view[2], h = box?.height ? box.height * mpp : view[3];
  const cx = view[0] + view[2] / 2, cy = view[1] + view[3] / 2;
  const corners = [[cx - w / 2, cy - h / 2], [cx + w / 2, cy - h / 2], [cx - w / 2, cy + h / 2], [cx + w / 2, cy + h / 2]]
    .map(([sx, sy]) => [sx + x0 - pad, y1 + pad - sy])          // screen -> net x/y
    .map(([x, y]) => [fwd[0] * x + fwd[1] * y + fwd[2], fwd[3] * x + fwd[4] * y + fwd[5]]);
  const us = corners.map((c) => c[0]), vs = corners.map((c) => c[1]);
  const dpr = window.devicePixelRatio || 1;
  const range = (zz) => {
    const n = 2 ** zz;
    return [Math.floor(Math.min(...us) * n), Math.floor(Math.max(...us) * n),
            Math.floor(Math.min(...vs) * n), Math.floor(Math.max(...vs) * n)];
  };
  let z = Math.ceil(Math.log2(Math.hypot(A, D) / ((256 * mpp) / dpr)));
  z = Math.max(12, Math.min(basemap.max_zoom || 19, z));
  while (z > 12) {
    const [a, b, c, d] = range(z);
    if ((b - a + 1) * (d - c + 1) <= 160) break;
    z -= 1;
  }
  const layer = (zz) => {
    const [ta, tb, tc, td] = range(zz), n = 2 ** zz, s = 1 / (n * 256), out = [];
    for (let tx = ta; tx <= tb; tx++) {
      for (let ty = tc; ty <= td; ty++) {
        const u0 = tx / n, v0 = ty / n;
        const m = [A * s, -D * s, B * s, -E * s, A * u0 + B * v0 + C - x0 + pad, y1 + pad - (D * u0 + E * v0 + F)];
        out.push(<image key={`${zz}/${tx}/${ty}`} href={url.replace("{z}", zz).replace("{x}", tx).replace("{y}", ty)}
                        width={256.6} height={256.6} transform={`matrix(${m.join(",")})`} preserveAspectRatio="none" />);
      }
    }
    return out;
  };
  return <>{z - 3 >= 12 && layer(z - 3)}{layer(z)}</>;
}

function savedBasemap() {
  try { return BASEMAPS[localStorage.getItem("basemap")] ? localStorage.getItem("basemap") : "dark"; } catch { return "dark"; }
}

export default function NetworkMap({ live, highlight = {}, focus = [], showCars = true, height = 420, lines = [] }) {
  const geo = useOnce(live.scenario ? "/network" : null, [live.scenario]);
  const svgRef = useRef(null);
  const [view, setView] = useState(null);           // [x, y, w, h] of the visible area
  const [peds, setPeds] = useState(true);
  const [basemap, setBasemap] = useState(savedBasemap);
  const chooseBasemap = (b) => { setBasemap(b); try { localStorage.setItem("basemap", b); } catch { /* private window */ } };
  const drag = useRef(null);
  const angles = useRef(new Map());                 // last drawn heading per vehicle, unwrapped

  const pad = 60;
  const full = geo ? (() => {
    const [x0, y0, x1, y1] = geo.bounds;
    return [0, 0, x1 - x0 + 2 * pad, y1 - y0 + 2 * pad];
  })() : null;
  useEffect(() => { if (full) setView(full); }, [geo]);

  useEffect(() => {                                  // wheel zoom needs a non-passive listener
    const el = svgRef.current;
    if (!el) return;
    const onWheel = (e) => {
      e.preventDefault();
      zoomAt(e.deltaY < 0 ? 0.8 : 1.25, e.clientX, e.clientY);
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
  });

  if (!geo || !view || live.status === "idle" || live.status === "offline")
    return <div className="map empty" style={{ height }}>Start a scenario to see the map</div>;

  const [x0, , , y1] = geo.bounds;
  const X = (x) => x - x0 + pad, Y = (y) => y1 - y + pad;
  const toMap = (cx, cy) => {
    const r = svgRef.current.getBoundingClientRect();
    const scale = Math.max(view[2] / r.width, view[3] / r.height);
    const offX = (r.width * scale - view[2]) / 2, offY = (r.height * scale - view[3]) / 2;
    return [view[0] - offX + (cx - r.left) * scale, view[1] - offY + (cy - r.top) * scale, scale];
  };
  function zoomAt(factor, cx, cy) {
    setView((v) => {
      if (!v) return v;
      const r = svgRef.current.getBoundingClientRect();
      const [mx, my] = cx === undefined ? [v[0] + v[2] / 2, v[1] + v[3] / 2] : toMap(cx, cy);
      const w = Math.min(Math.max(v[2] * factor, full[2] / 20), full[2] * 1.5);
      const h = w * (v[3] / v[2]);
      const k = w / v[2];
      return [mx - (mx - v[0]) * k, my - (my - v[1]) * k, w, h];
    });
  }
  const onDown = (e) => { drag.current = { x: e.clientX, y: e.clientY, v: view }; e.currentTarget.setPointerCapture?.(e.pointerId); };
  const onMove = (e) => {
    if (!drag.current) return;
    const r = svgRef.current.getBoundingClientRect();
    const scale = Math.max(view[2] / r.width, view[3] / r.height);
    const { x, y, v } = drag.current;
    setView([v[0] - (e.clientX - x) * scale, v[1] - (e.clientY - y) * scale, v[2], v[3]]);
  };
  const onUp = () => { drag.current = null; };

  const status = Object.fromEntries((live.junctions || []).map((j) => [j.id, j]));
  const inc = new Set(highlight.incidents || []), fl = new Set(highlight.floods || []);
  const rb = new Set(highlight.routeB || []), alt = new Set(highlight.alt || []);
  const color = (j) => !j ? "#5a6470" : j.preempt ? "#e5604d" : j.mode === "fixed" ? "#e6a23c"
    : j.mode === "actuated" ? "#c9b25a" : j.queue > 12 ? "#e6a23c" : "#2bc4b5";
  const zoomedIn = view[2] < full[2] * 0.6;
  const btn = { padding: "2px 10px", fontSize: 16, lineHeight: "22px" };
  const jr = Math.max(9, Math.min(30, view[2] / 55));     // junction markers shrink when zooming in
  const sr = Math.max(3.5, Math.min(9, view[2] / 170));    // traffic light size
  const br = Math.max(5, Math.min(13, view[2] / 120));     // bus stop size
  const walk = {};
  (live.junctions || []).forEach((j) => j.crossings.forEach((c) => { walk[c.id] = c.walk; }));
  const lightColor = { G: "#35d07f", y: "#ffc83d", r: "#ff4a3a" };
  const box = svgRef.current?.getBoundingClientRect();
  const mpp = box && box.width ? Math.max(view[2] / box.width, view[3] / box.height) : view[2] / 800;  // metres per px
  const heading = (v) => {                          // turn the short way round (359 -> 1 is +2, not -358)
    const a = v.angle ?? 90, last = angles.current.get(v.id);
    const next = last === undefined ? a : last + ((((a - last) % 360) + 540) % 360) - 180;
    angles.current.set(v.id, next);
    return next;
  };
  if (angles.current.size > 2 * (live.vehicles?.length || 0) + 200) {   // forget vehicles that left
    const here = new Set((live.vehicles || []).map((v) => v.id));
    for (const id of angles.current.keys()) if (!here.has(id)) angles.current.delete(id);
  }
  const pr = Math.max(0.9, Math.min(3, view[2] / 550));        // pedestrian dot radius
  const bm = geo.basemap && BASEMAPS[basemap].style ? BASEMAPS[basemap] : null;
  const roadOpacity = bm ? 0.6 : 1;                              // let the real streets show through

  return (
    <div style={{ position: "relative" }}>
      <div style={{ position: "relative" }}>
      <svg ref={svgRef} className="map" viewBox={view.join(" ")} style={{ height, cursor: drag.current ? "grabbing" : "grab", touchAction: "none" }}
           role="img" aria-label="Zoomable map of the central Tunis network with junctions, vehicles and pedestrians"
           onPointerDown={onDown} onPointerMove={onMove} onPointerUp={onUp} onPointerLeave={onUp}
           onDoubleClick={() => setView(full)}>
        {bm && <g style={{ filter: bm.filter }}>
          {geo.basemap.styles[bm.style] && (() => {           // offline fallback, also shown while tiles load
            const [bx0, by0, bx1, by1] = geo.basemap.bounds;
            return <image href={geo.basemap.styles[bm.style]} x={X(bx0)} y={Y(by1)} width={bx1 - bx0}
                          height={by1 - by0} preserveAspectRatio="none" />;
          })()}
          <Tiles basemap={geo.basemap} style={bm.style} view={view} box={box} mpp={mpp} origin={[x0, y1, pad]} />
        </g>}
        {/* sidewalks, then each traffic lane (real widths in metres) */}
        {geo.edges.flatMap((e) => (e.sidewalks || []).map((sh, i) => (
          <polyline key={`sw${e.id}${i}`} points={sh.map(([x, y]) => `${X(x)},${Y(y)}`).join(" ")} fill="none"
                    stroke="#4b5462" strokeWidth={2.4} strokeLinecap="round" opacity={roadOpacity} />
        )))}
        {geo.edges.flatMap((e) => (e.lane_shapes || [e.shape]).map((sh, i) => (
          <polyline key={`ln${e.id}${i}`} points={sh.map(([x, y]) => `${X(x)},${Y(y)}`).join(" ")} fill="none"
                    stroke="#2c3442" strokeWidth={e.lane_shapes ? 3.3 : 8 + e.lanes * 5} strokeLinecap="butt"
                    opacity={roadOpacity} />
        )))}
        {geo.edges.filter((e) => fl.has(e.id) || inc.has(e.id) || rb.has(e.id) || alt.has(e.id)).map((e) => {
          const stroke = fl.has(e.id) ? "#5c9bea" : inc.has(e.id) ? "#e5604d" : rb.has(e.id) ? "#2bc4b5" : "#e6a23c";
          return <polyline key={`hl${e.id}`} points={e.shape.map(([x, y]) => `${X(x)},${Y(y)}`).join(" ")} fill="none"
                           stroke={stroke} strokeWidth={Math.max(4, e.lanes * 3.3)} opacity="0.7"
                           strokeDasharray={fl.has(e.id) ? "14 8" : undefined} />;
        })}
        {geo.edges.filter((e) => e.bus_lane).map((e) => (
          <polyline key={`bl${e.id}`} points={e.shape.map(([x, y]) => `${X(x)},${Y(y)}`).join(" ")} fill="none"
                    stroke="#8a2f3a" strokeWidth={5} strokeDasharray="10 6" />
        ))}
        {lines.map((ln) => (geo.lines?.[ln] || []).map((eid) => {
          const e = geo.edges.find((x) => x.id === eid);
          return e && <polyline key={`ln${ln}${eid}`} points={e.shape.map(([x, y]) => `${X(x)},${Y(y)}`).join(" ")}
                                fill="none" stroke={lineColor(ln)} strokeWidth={6} opacity="0.85"
                                strokeDasharray={ln.endsWith("_R") ? "12 7" : undefined} />;
        }))}
        {(geo.crossings || []).map((c) => (
          <polyline key={c.id} points={c.shape.map(([x, y]) => `${X(x)},${Y(y)}`).join(" ")} fill="none"
                    stroke={walk[c.id] ? "#35d07f" : "#e8ecef"} strokeWidth={4} strokeDasharray="2.5 2.5"
                    opacity={walk[c.id] ? 0.95 : 0.55} />
        ))}
        {zoomedIn && geo.edges.filter((e) => e.name).map((e) => {
          const [[ax, ay], [bx, by]] = [e.shape[0], e.shape[e.shape.length - 1]];
          if (e.id > e.id.split("_").reverse().join("_")) return null;     // one label per road
          return <text key={`n${e.id}`} x={(X(ax) + X(bx)) / 2} y={(Y(ay) + Y(by)) / 2 - 22} textAnchor="middle"
                       fontSize={view[2] / 45} fill="#8995a0" fontFamily="IBM Plex Sans">{e.name}</text>;
        })}
        {peds && (live.people || []).map(([x, y, slow], i) => (
          <circle key={`p${i}`} cx={X(x)} cy={Y(y)} r={slow ? pr * 1.15 : pr} fill={slow ? "#ff4fd8" : "#e8ecef"} opacity="0.9" />
        ))}
        {showCars && (live.vehicles || []).map((v) => (
          <Vehicle key={v.id} v={v} x={X(v.x)} y={Y(v.y)} angle={heading(v)} focused={focus.includes(v.id)} mpp={mpp} />
        ))}
        {(geo.bus_stops || []).map((b) => (
          <g key={b.id}>
            <rect x={X(b.x) - br} y={Y(b.y) - br} width={br * 2} height={br * 2} rx={br / 3} fill="#1d4f9c"
                  stroke="#ffffff" strokeWidth={br / 5} />
            <text x={X(b.x)} y={Y(b.y) + br * 0.4} textAnchor="middle" fontSize={br * 1.1} fill="#fff"
                  fontFamily="IBM Plex Sans" fontWeight="700">B</text>
            {zoomedIn && <text x={X(b.x)} y={Y(b.y) + br * 2.6} textAnchor="middle" fontSize={br * 0.9}
                               fill="#a9c8f3" fontFamily="IBM Plex Sans">bus stop</text>}
          </g>
        ))}
        {(geo.signals || []).map((g) => {
          const c = live.signals?.[g.tls]?.[g.edge] || "r";
          return (
            <g key={`s${g.edge}`}>
              <rect x={X(g.x) - sr * 1.25} y={Y(g.y) - sr * 1.25} width={sr * 2.5} height={sr * 2.5} rx={sr * 0.6}
                    fill="#0b0e13" stroke="#3a4454" strokeWidth={sr * 0.2} />
              <circle cx={X(g.x)} cy={Y(g.y)} r={sr} fill={lightColor[c]} />
            </g>
          );
        })}
        {geo.nodes.filter((n) => n.signal).map((n) => (
          <g key={n.id}>
            <circle cx={X(n.x)} cy={Y(n.y)} r={jr} fill={color(status[n.id])} opacity={zoomedIn ? 0.75 : 0.92} />
            <text x={X(n.x)} y={Y(n.y) + jr * 0.27} textAnchor="middle" fontSize={jr * 0.8} fontFamily="IBM Plex Mono"
                  fill="#12161e" fontWeight="600">{n.id}</text>
          </g>
        ))}
      </svg>
      {bm && <div className="muted" style={{ position: "absolute", left: 8, bottom: 6, fontSize: 10, opacity: 0.75,
                                              pointerEvents: "none" }}>{geo.basemap.attribution}</div>}
      </div>
      <div style={{ position: "absolute", top: 10, right: 10, display: "flex", flexDirection: "column", gap: 6 }}>
        <button style={btn} onClick={() => zoomAt(0.7)} aria-label="Zoom in">+</button>
        <button style={btn} onClick={() => zoomAt(1.4)} aria-label="Zoom out">−</button>
        <button style={{ ...btn, fontSize: 12 }} onClick={() => setView(full)} aria-label="Reset view">fit</button>
      </div>
      <div style={{ display: "flex", justifyContent: "space-between", gap: 12, marginTop: 8, flexWrap: "wrap" }}>
        <Legend />
        <span style={{ display: "inline-flex", gap: 14, alignItems: "center" }}>
        {geo.basemap && <label className="muted" style={{ fontSize: 13, display: "inline-flex", gap: 6, alignItems: "center" }}>
          map
          <select value={basemap} onChange={(e) => chooseBasemap(e.target.value)} style={{ fontSize: 13 }}>
            {Object.entries(BASEMAPS).map(([k, b]) => <option key={k} value={k}>{b.label}</option>)}
          </select>
        </label>}
        <label className="muted" style={{ fontSize: 13, display: "inline-flex", gap: 6, alignItems: "center" }}>
          <input type="checkbox" checked={peds} onChange={(e) => setPeds(e.target.checked)} style={{ padding: 0 }} />
          show pedestrians
        </label>
        </span>
      </div>
    </div>
  );
}
