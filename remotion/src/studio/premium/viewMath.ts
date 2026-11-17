// Pure maths for chart sequences: several views (windows) of one series, with the window scrubbing and zooming between them.
import { scaleLinear } from "d3-scale";
import { ticks as d3ticks } from "d3-array";
import { EASE, clamp01, mix } from "./motion.ts";
import { parseX, niceExtent } from "../chartMath.ts";

export type Mark = { x: string | number; label?: string; value?: number; atWord?: string };
export type View = {
  window: { from: string | number; to: string | number };
  highlight?: { from: string | number; to: string | number; label?: string; atWord?: string };
  marks?: Mark[];
  point?: Mark;             // the tip the line stops at in this view
  atWord?: string;          // the spoken word this view starts on
  atFrame?: number;         // resolved start frame (scene-local); filled by resolveViews
};
export type PremiumLine = {
  series: { name: string; points: { x: string | number; y: number }[] }[];
  views: View[];
  decimals?: number;
};

export type Dom = { x0: number; x1: number; y0: number; y1: number };

/** y-range of the series points inside [x0, x1]; padded and niced exactly like the classic chart so the axis stays honest. */
export const windowDomain = (pts: { x: string | number; y: number }[], x0: number, x1: number): [number, number] => {
  const ys = pts.filter((p) => { const x = parseX(p.x); return x >= x0 && x <= x1; }).map((p) => p.y);
  return niceExtent(ys.length ? ys : pts.map((p) => p.y), 0.14, false, false);
};

export const viewDomain = (pts: { x: string | number; y: number }[], v: View): Dom => {
  const x0 = parseX(v.window.from), x1 = parseX(v.window.to);
  const [y0, y1] = windowDomain(pts, x0, x1);
  return { x0, x1, y0, y1 };
};

/** Frames the scrub from one view to the next takes. */
export const SCRUB = 22;

/** The interpolated domain at frame f given each view's start frame. Views must be sorted by atFrame. */
export const domainAt = (pts: { x: string | number; y: number }[], views: View[], f: number): { dom: Dom; i: number; blend: number; from: Dom; to: Dom } => {
  const doms = views.map((v) => viewDomain(pts, v));
  let i = 0;
  for (let k = 0; k < views.length; k++) if (f >= (views[k].atFrame ?? 0)) i = k;
  const start = views[i].atFrame ?? 0;
  const e = i === 0 ? 1 : EASE.inOut(clamp01((f - start) / SCRUB));
  const prev = i === 0 ? doms[0] : doms[i - 1];
  const cur = doms[i];
  return { dom: { x0: mix(prev.x0, cur.x0, e), x1: mix(prev.x1, cur.x1, e), y0: mix(prev.y0, cur.y0, e), y1: mix(prev.y1, cur.y1, e) }, i, blend: e, from: prev, to: cur };
};

export const yTicks = (d: Dom, n = 4): number[] => d3ticks(d.y0, d.y1, n);
export const linear = (d: [number, number], r: [number, number]) => scaleLinear().domain(d).range(r);

/** Value of a series at x (linear between observations), used for the header figure that follows the line tip. */
export const valueAt = (pts: { x: string | number; y: number }[], x: number): number => {
  const p = pts.map((q) => ({ x: parseX(q.x), y: q.y }));
  if (x <= p[0].x) return p[0].y;
  for (let i = 1; i < p.length; i++) if (x <= p[i].x) { const t = (x - p[i - 1].x) / (p[i].x - p[i - 1].x || 1); return mix(p[i - 1].y, p[i].y, t); }
  return p[p.length - 1].y;
};
