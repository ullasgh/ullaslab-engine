import { scaleLinear, scaleUtc } from "d3-scale";
import { line as d3line, curveMonotoneX, curveLinear } from "d3-shape";
import { extent } from "d3-array";

export type XY = { x: number; y: number };
export const parseX = (x: string | number): number => (typeof x === "number" ? x : Date.parse(x.length === 7 ? `${x}-01` : x));

export const niceExtent = (vals: number[], padFrac = 0.08, includeZero = false): [number, number] => {
  const [lo, hi] = extent(vals) as [number, number];
  const a = includeZero ? Math.min(0, lo) : lo, b = includeZero ? Math.max(0, hi) : hi;
  const pad = (b - a || Math.abs(b) || 1) * padFrac;
  return scaleLinear().domain([a - pad, b + pad]).nice(4).domain() as [number, number];
};

export const makeTimeScale = (xs: number[], range: [number, number]) => scaleUtc().domain(extent(xs) as [number, number]).range(range);
export const makeLinear = (domain: [number, number], range: [number, number]) => scaleLinear().domain(domain).range(range);

export const linePath = (pts: XY[], smooth = true): string => {
  const g = d3line<XY>().x((p) => p.x).y((p) => p.y).curve(smooth ? curveMonotoneX : curveLinear);
  return g(pts) ?? "";
};

export const fmtNum = (n: number, decimals = 0, locale = "en-US") =>
  n.toLocaleString(locale, { minimumFractionDigits: decimals, maximumFractionDigits: decimals });

// Value shown by a counter at progress p (0..1), eased out.
export const counterValue = (from: number, to: number, p: number): number => {
  const t = Math.min(1, Math.max(0, p));
  return from + (to - from) * (1 - Math.pow(1 - t, 3));
};

// Points of a polyline visible at progress p (0..1): returns the prefix plus an interpolated tip.
export const revealPoints = (pts: XY[], p: number): XY[] => {
  if (pts.length < 2 || p >= 1) return pts;
  if (p <= 0) return [pts[0]];
  const f = p * (pts.length - 1), i = Math.floor(f), r = f - i;
  const out = pts.slice(0, i + 1);
  out.push({ x: pts[i].x + (pts[i + 1].x - pts[i].x) * r, y: pts[i].y + (pts[i + 1].y - pts[i].y) * r });
  return out;
};
