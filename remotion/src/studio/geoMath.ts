import { geoInterpolate, geoDistance } from "d3-geo";

export type LonLat = [number, number];

// Densely sampled great-circle polyline through waypoints (lon/lat), n samples per leg.
export const sampleRoute = (waypoints: LonLat[], perLeg = 48): LonLat[] => {
  const out: LonLat[] = [];
  for (let i = 0; i < waypoints.length - 1; i++) {
    const f = geoInterpolate(waypoints[i], waypoints[i + 1]);
    for (let k = i === 0 ? 0 : 1; k <= perLeg; k++) out.push(f(k / perLeg) as LonLat);
  }
  return out;
};

// Split a projected polyline wherever consecutive points jump more than maxJump px (antimeridian wrap).
export const splitJumps = (pts: [number, number][], maxJump: number): [number, number][][] => {
  const segs: [number, number][][] = [];
  let cur: [number, number][] = [];
  for (const p of pts) {
    const prev = cur[cur.length - 1];
    if (prev && Math.hypot(p[0] - prev[0], p[1] - prev[1]) > maxJump) { segs.push(cur); cur = []; }
    cur.push(p);
  }
  if (cur.length) segs.push(cur);
  return segs;
};

// Index-interpolated position along a sampled array at fraction f in 0..1.
export const along = <T extends [number, number]>(pts: T[], f: number): [number, number] => {
  if (!pts.length) return [0, 0];
  const x = Math.min(1, Math.max(0, f)) * (pts.length - 1), i = Math.floor(x), r = x - i;
  const a = pts[i], b = pts[Math.min(pts.length - 1, i + 1)];
  return [a[0] + (b[0] - a[0]) * r, a[1] + (b[1] - a[1]) * r];
};

// True if the point faces the viewer on a globe centred at `center` (lon, lat).
export const onNearSide = (p: LonLat, center: LonLat): boolean => geoDistance(p, center) < Math.PI / 2 - 0.02;

export type MapFocus = { center: LonLat; zoom: number };
// Named focus presets for the Natural Earth projection (zoom relative to a world fit).
export const FOCUS: Record<string, MapFocus> = {
  world: { center: [10, 12], zoom: 1 },
  indian_ocean: { center: [70, 14], zoom: 2.3 },
  asia: { center: [95, 28], zoom: 1.9 },
  europe_med: { center: [20, 40], zoom: 2.6 },
  atlantic: { center: [-30, 30], zoom: 1.7 },
  americas: { center: [-80, 10], zoom: 1.7 },
};
