import React from "react";
import { useCurrentFrame } from "remotion";
import { evolvePath, getLength, getPointAtLength } from "@remotion/paths";
import { StudioSourceStamp } from "../Stamp";
import type { FlowData } from "../Diagrams";
import { useStudio } from "../context";
import { EASE, SPRING, breathe, clamp01, loop, range, springOut } from "./motion";
import { PT, RADIUS, SP } from "./tokens";
import { usePremium, type Carry } from "./context";
import { findWord, norm } from "./words";

type Node = FlowData["nodes"][number];
type Rect = { x: number; y: number; w: number; h: number };

const TONE: Record<string, string> = { accent: PT.teal, accent2: PT.amber, accent3: PT.blue, negative: PT.coral };
const toneOf = (t?: string) => TONE[t ?? "accent"] ?? PT.teal;
const NUM = /(-?[$€£₹]?\d[\d,]*(?:\.\d+)?%?)\s*$/;

/** Split a node label into its words and a trailing number token ("Ten-year 4.88" -> ["Ten-year", "4.88"]). */
export const splitLabel = (label: string): { text: string; num: string | null } => {
  const m = NUM.exec(label.trim());
  return m && m.index > 0 ? { text: label.slice(0, m.index).trim(), num: m[1] } : { text: label, num: null };
};

const linesFor = (text: string | undefined, size: number, bw: number) => (!text ? 0 : Math.min(2, Math.max(1, Math.ceil((text.length * 0.54 * size) / bw))));

export type FlowLayout = { rects: Record<string, Rect>; top: number; boxH: number; vertical: boolean };

/** Node rectangles in scene-local px. Pure: shared by the diagram and by the morph that starts from one of its numbers. */
export const flowLayout = (data: FlowData, bw: number, bh: number, vertical: boolean, headline: string | undefined, T: { headline: number }): FlowLayout => {
  const top = headline ? linesFor(headline, T.headline, bw) * T.headline * 1.12 + SP.m : 0;
  const levels = Math.max(...data.nodes.map((n) => n.level)) + 1;
  const byLevel: string[][] = Array.from({ length: levels }, () => []);
  data.nodes.forEach((n) => byLevel[n.level].push(n.id));
  const widest = Math.max(...byLevel.map((l) => l.length));
  const availH = bh - top - 118 - SP.m, availW = bw;
  const gapCross = SP.m;
  const nLevelsGap = Math.max(1, levels - 1);
  const labelled = data.edges.some((e) => e.label);
  let gapMain = vertical ? SP.xl + SP.s : labelled ? 340 : 160;   // wide frame: room for the edge label between the boxes
  const boxW = vertical ? (availW - gapCross * (widest - 1)) / widest : Math.min(620, (availW - gapMain * (levels - 1)) / levels);
  const boxH = vertical ? Math.min(230, (availH - 100 * (levels - 1)) / levels) : Math.min(260, (availH - gapCross * (widest - 1)) / widest);
  // with few levels, spread them over the height instead of leaving a gap at the bottom (never past 220 px)
  if (vertical && levels > 1) gapMain = Math.max(gapMain, Math.min(220, (availH - levels * boxH) / nLevelsGap));
  const rects: Record<string, Rect> = {};
  data.nodes.forEach((n) => {
    const row = byLevel[n.level], idx = row.indexOf(n.id), cnt = row.length;
    if (vertical) {
      const total = levels * boxH + (levels - 1) * gapMain;
      const y0 = top + (availH - total) / 2;
      const w = cnt === 1 ? availW : boxW;
      rects[n.id] = { x: cnt === 1 ? 0 : idx * (boxW + gapCross), y: y0 + n.level * (boxH + gapMain), w, h: boxH };
    } else {
      const total = cnt * boxH + (cnt - 1) * gapCross;
      rects[n.id] = { x: (availW - (levels * boxW + (levels - 1) * gapMain)) / 2 + n.level * (boxW + gapMain), y: top + (availH - total) / 2 + idx * (boxH + gapCross), w: boxW, h: boxH };
    }
  });
  return { rects, top, boxH, vertical };
};

const edgeGeom = (a: Rect, b: Rect, vertical: boolean) => {
  if (vertical) {
    const x1 = a.x + a.w / 2, y1 = a.y + a.h, x2 = b.x + b.w / 2, y2 = b.y - 6, my = (y1 + y2) / 2;
    return { d: `M ${x1} ${y1} C ${x1} ${my}, ${x2} ${my}, ${x2} ${y2}`, mx: (x1 + x2) / 2, my, ax: x2, ay: y2, ang: 90 };
  }
  const x1 = a.x + a.w, y1 = a.y + a.h / 2, x2 = b.x - 6, y2 = b.y + b.h / 2, mx = (x1 + x2) / 2;
  return { d: `M ${x1} ${y1} C ${mx} ${y1}, ${mx} ${y2}, ${x2} ${y2}`, mx, my: (y1 + y2) / 2, ax: x2, ay: y2, ang: 0 };
};

/** The number inside a node is drawn at a fixed, computable place so a morph can start from exactly there. */
export const nodeNumberBox = (r: Rect, num: string, size: number) => {
  const w = num.length * size * 0.6;
  return { x: r.x + (r.w - w) / 2, y: r.y + r.h - size * 1.12 - SP.xs, size };
};

/** First number carried by a highlighted node, for a morph into the next chart's header figure. */
export const flowCarry = (data: FlowData, bw: number, bh: number, vertical: boolean, T: { headline: number; body: number }): Carry | null => {
  const lay = flowLayout(data, bw, bh, vertical, data.headline, T);
  const n = data.nodes.find((x) => x.tone === "accent2" && splitLabel(x.label).num) ?? data.nodes.find((x) => splitLabel(x.label).num);
  if (!n) return null;
  const num = splitLabel(n.label).num!;
  const b = nodeNumberBox(lay.rects[n.id], num, T.body * 1.5);
  return { text: num, x: b.x, y: b.y, size: b.size, color: PT.amber };
};

export const PremiumFlow: React.FC<{ data: FlowData }> = ({ data }) => {
  const { L } = useStudio();
  const { bw, bh, T, font, words, dur, morphOut } = usePremium();
  const f = useCurrentFrame();
  const lay = flowLayout(data, bw, bh, L.vertical, data.headline, T);
  const tug = (data as FlowData & { layout?: string }).layout === "tug";

  // ---- build order: each node lands on the narration word that names it; the rest spread across the first 70% of the scene
  const order = data.nodes.map((n, i) => ({ n, i })).sort((a, b) => a.n.level - b.n.level || a.i - b.i);
  const fallback = (k: number) => Math.round(10 + (k / Math.max(1, order.length)) * Math.max(30, dur * 0.7 - 10));
  const land: Record<string, number> = {};
  let last = 0;
  order.forEach(({ n }, k) => {
    const toks = splitLabel(n.label).text.split(/\s+/).map(norm).filter((t) => t.length > 2);
    let hit: { i: number; w: { a: number } } | null = null;
    for (const t of toks) { const h = findWord(words, t, 0); if (h && (!hit || h.w.a < hit.w.a)) hit = h; }
    const nn = splitLabel(n.label).num;
    if (nn) { const h = findWord(words, nn, 0); if (h) hit = h; }
    land[n.id] = Math.max(hit ? hit.w.a - 4 : fallback(k), last + 6);
    last = land[n.id];
  });
  const active = order.map(({ n }) => n).filter((n) => f >= land[n.id]).pop();
  const focus = active ? lay.rects[active.id] : null;
  const fx = focus ? ((focus.x + focus.w / 2) / bw - 0.5) * -14 : 0, fy = focus ? ((focus.y + focus.h / 2) / bh - 0.5) * -14 : 0;
  const numSize = T.body * 1.5;

  const wrap = (nodes: React.ReactNode) => (
    <div style={{ position: "absolute", left: 0, top: 0, width: bw, height: bh, fontFamily: font, color: PT.ink }}>
      {data.headline && (
        <div data-audit="headline" style={{ position: "absolute", left: 0, top: 0, width: bw, fontSize: T.headline, fontWeight: 700, lineHeight: 1.12, opacity: EASE.out(range(f, 0, 12)), transform: `translateY(${(1 - EASE.out(range(f, 0, 14))) * 18}px)` }}>{data.headline}</div>
      )}
      <div style={{ position: "absolute", inset: 0, transform: `translate(${fx}px, ${fy}px)` }}>{nodes}</div>
      <div style={{ position: "absolute", left: 0, bottom: 0, width: bw }}>
        <StudioSourceStamp source={data.meta.source} freshness={data.meta.freshness} />
      </div>
    </div>
  );

  if (tug) {
    const srcs = order.filter(({ n }) => !data.edges.some((e) => e.to === n.id)).map((o) => o.n);
    const knot = data.nodes.find((n) => data.edges.some((e) => e.to === n.id)) ?? data.nodes[data.nodes.length - 1];
    const sway = breathe(f, 54, 12);
    const kx = bw / 2 + (L.vertical ? 0 : sway), ky = lay.top + (bh - lay.top - 118 - SP.m) / 2 + (L.vertical ? sway : 0);
    const kr = 54;
    const arrive = EASE.out(range(f, land[knot.id] - 6, 16));
    return wrap(
      <>
        {srcs.slice(0, 2).map((n, i) => {
          const dirn = i === 0 ? -1 : 1;
          const r = lay.rects[n.id];
          const cx = r.x + r.w / 2, cy = r.y + r.h / 2;
          const k = springOut(range(f, land[n.id], 18), SPRING.snappy);
          const d = `M ${kx} ${ky} L ${cx} ${cy + (L.vertical ? (dirn < 0 ? r.h / 2 : -r.h / 2) : 0)}`;
          return (
            <g key={n.id}>
              <svg width={bw} height={bh} style={{ position: "absolute", left: 0, top: 0, overflow: "visible" }}>
                <path d={d} stroke={PT.panelLine} strokeWidth={10} strokeLinecap="round" fill="none" opacity={k} />
                <path d={d} stroke={toneOf(n.tone === "accent" ? (i ? "accent2" : "accent") : n.tone)} strokeWidth={6} strokeLinecap="round" fill="none" strokeDasharray="4 22" strokeDashoffset={-f * 1.6 * dirn * -1} opacity={k} />
              </svg>
              <div data-audit="label" style={{ position: "absolute", left: r.x, top: r.y, width: r.w, height: r.h, opacity: clamp01(k * 2), transform: `scale(${0.9 + 0.1 * k})`, boxSizing: "border-box", background: PT.panel,
                border: `3px solid ${toneOf(i ? "accent2" : "accent")}`, borderRadius: RADIUS, display: "flex", alignItems: "center", justifyContent: "center", textAlign: "center", fontSize: T.body, fontWeight: 700, lineHeight: 1.15, padding: `${SP.xs}px ${SP.m}px` }}>{n.label}</div>
            </g>
          );
        })}
        <div style={{ position: "absolute", left: kx - kr, top: ky - kr, width: kr * 2, height: kr * 2, borderRadius: "50%", background: PT.amber, opacity: arrive, transform: `scale(${0.6 + 0.4 * arrive})` }} />
        <div data-audit="label" style={{ position: "absolute", left: kx - bw * 0.3, top: ky + kr + SP.xs, width: bw * 0.6, textAlign: "center", fontSize: T.body, fontWeight: 700, color: PT.amber, opacity: arrive }}>{knot.label}</div>
      </>,
    );
  }

  return wrap(
    <>
      <svg width={bw} height={bh} style={{ position: "absolute", left: 0, top: 0, overflow: "visible" }}>
        {data.edges.map((e, i) => {
          const g = edgeGeom(lay.rects[e.from], lay.rects[e.to], L.vertical);
          const t0 = land[e.to] - 14;
          const k = EASE.inOut(range(f, t0, 18));
          const ev = evolvePath(k, g.d);
          const len = getLength(g.d);
          const pulse = k >= 1 ? getPointAtLength(g.d, len * loop(f, 70, i * 23)) : null;
          return (
            <g key={i} opacity={k > 0 ? 1 : 0}>
              <path d={g.d} fill="none" stroke={PT.panelLine} strokeWidth={8} />
              <path d={g.d} fill="none" stroke={PT.teal} strokeWidth={8} strokeLinecap="round" strokeDasharray={ev.strokeDasharray} strokeDashoffset={ev.strokeDashoffset} />
              {k >= 1 && <polygon points="0,-14 24,0 0,14" fill={PT.teal} transform={`translate(${g.ax - (g.ang === 0 ? 24 : 0)} ${g.ay - (g.ang === 90 ? 24 : 0)}) rotate(${g.ang})`} />}
              {pulse && <circle cx={pulse.x} cy={pulse.y} r={9} fill={PT.amber} opacity={0.95} />}
              {e.label && k >= 0.9 && <text x={L.vertical ? g.mx + 22 : g.mx} y={L.vertical ? g.my + 12 : g.my - 14} textAnchor={L.vertical ? "start" : "middle"} fontSize={T.label} fontWeight={700} fill={PT.amber} stroke={PT.navy0} strokeWidth={8} paintOrder="stroke" data-audit="stamp" opacity={EASE.out(range(f, t0 + 16, 10))}>{e.label}</text>}
            </g>
          );
        })}
      </svg>
      {data.nodes.map((n) => {
        const r = lay.rects[n.id];
        const a = range(f, land[n.id], 18);
        const k = springOut(a, SPRING.snappy);
        const c = toneOf(n.tone);
        const isActive = active?.id === n.id;
        const { text, num } = splitLabel(n.label);
        const nb = num ? nodeNumberBox(r, num, numSize) : null;
        const hideNum = morphOut && num && f >= dur - 2;
        return (
          <div key={n.id} style={{ position: "absolute", left: r.x, top: r.y, width: r.w, height: r.h, opacity: clamp01(a * 3), transform: `translateY(${(1 - k) * 28}px) scale(${0.94 + 0.06 * k})`, transformOrigin: "50% 50%" }}>
            {isActive && <div style={{ position: "absolute", inset: -8, borderRadius: RADIUS + 8, border: `3px solid ${c}`, opacity: 0.35 + 0.25 * Math.sin((f / 18) * Math.PI) }} />}
            <div data-audit="label" style={{ position: "absolute", inset: 0, boxSizing: "border-box", background: PT.panel, border: `3px solid ${c}`, borderRadius: RADIUS, display: "flex", flexDirection: "column",
              alignItems: "center", justifyContent: num ? "flex-start" : "center", textAlign: "center", fontSize: T.body, fontWeight: 700, lineHeight: 1.15, padding: `${SP.s}px ${SP.m}px`, overflow: "hidden" }}>
              <span>{text}</span>
            </div>
            {nb && <div data-audit="headline" style={{ position: "absolute", left: nb.x - r.x, top: nb.y - r.y, fontSize: nb.size, lineHeight: 1, fontWeight: 700, color: PT.amber, letterSpacing: -2, fontVariantNumeric: "tabular-nums", whiteSpace: "nowrap", opacity: hideNum ? 0 : 1 }}>{num}</div>}
          </div>
        );
      })}
    </>,
  );
};
