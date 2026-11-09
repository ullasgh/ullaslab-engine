import React from "react";
import { useCurrentFrame } from "remotion";
import { useStudio } from "./context";
import { ChartShell, type ChartMeta } from "./Stamp";
import { PlotSlot } from "./Charts";

const clamp01 = (x: number) => Math.min(1, Math.max(0, x));
const ease = (x: number) => x * x * (3 - 2 * x);

/* --------------------------------------------------------------------------------------- timeline */
export type TimelineData = {
  meta: ChartMeta; headline?: string; events: { when: string; title: string; detail?: string }[];
};

export const Timeline: React.FC<{ data: TimelineData }> = ({ data }) => (
  <ChartShell meta={data.meta} headline={data.headline}>
    <PlotSlot>{({ w, h }) => <TimelinePlot data={data} w={w} h={h} />}</PlotSlot>
  </ChartShell>
);

const TimelinePlot: React.FC<{ data: TimelineData; w: number; h: number }> = ({ data, w, h }) => {
  const { L, pal } = useStudio();
  const f = useCurrentFrame();
  const fs = L.type.label;
  const n = data.events.length;
  const step = 13;
  const lineP = ease(clamp01((f - 4) / (n * step)));
  if (L.vertical) {
    const x = 26, rowH = h / n;
    return (
      <div style={{ position: "absolute", inset: 0 }}>
        <div style={{ position: "absolute", left: x - 2, top: 18, width: 4, height: (h - 36) * lineP, background: pal.accent, borderRadius: 2 }} />
        {data.events.map((e, i) => {
          const k = ease(clamp01((f - (8 + i * step)) / 18));
          const cy = i * rowH + rowH / 2;
          return (
            <div key={i} style={{ position: "absolute", left: 0, top: cy - rowH / 2, width: w, height: rowH, opacity: k, transform: `translateX(${(1 - k) * 30}px)` }}>
              <div style={{ position: "absolute", left: x - 14, top: rowH / 2 - 14, width: 28, height: 28, borderRadius: 14, background: pal.bg, border: `5px solid ${i === n - 1 ? pal.accent2 : pal.accent}` }} />
              <div style={{ position: "absolute", left: 76, top: 0, bottom: 0, right: 0, display: "flex", flexDirection: "column", justifyContent: "center" }}>
                <div data-audit="body" style={{ fontSize: fs, color: i === n - 1 ? pal.accent2 : pal.accent, fontWeight: 700, lineHeight: 1.15 }}>{e.when}</div>
                <div data-audit="body" style={{ fontSize: L.type.body, color: pal.ink, fontWeight: 700, lineHeight: 1.12 }}>{e.title}</div>
                {e.detail && <div data-audit="body" style={{ fontSize: fs, color: pal.muted, lineHeight: 1.2 }}>{e.detail}</div>}
              </div>
            </div>
          );
        })}
      </div>
    );
  }
  const y = h / 2, colW = w / n;
  return (
    <div style={{ position: "absolute", inset: 0 }}>
      <div style={{ position: "absolute", left: 0, top: y - 2, width: w * lineP, height: 4, background: pal.accent, borderRadius: 2 }} />
      {data.events.map((e, i) => {
        const k = ease(clamp01((f - (8 + i * step)) / 18));
        const up = i % 2 === 0;
        const cx = colW * i + colW / 2;
        return (
          <div key={i} style={{ position: "absolute", left: cx - colW / 2, top: 0, width: colW, height: h, opacity: k }}>
            <div style={{ position: "absolute", left: colW / 2 - 15, top: y - 15, width: 30, height: 30, borderRadius: 15, background: pal.bg, border: `5px solid ${i === n - 1 ? pal.accent2 : pal.accent}` }} />
            <div style={{ position: "absolute", left: colW / 2 - 2, top: up ? y - 90 : y + 20, width: 4, height: 70, background: pal.grid }} />
            <div style={{ position: "absolute", left: 10, right: 10, [up ? "bottom" : "top"]: up ? h - y + 90 : y + 90, textAlign: "center" }}>
              <div data-audit="body" style={{ fontSize: fs, color: i === n - 1 ? pal.accent2 : pal.accent, fontWeight: 700 }}>{e.when}</div>
              <div data-audit="body" style={{ fontSize: L.type.body - 4, color: pal.ink, fontWeight: 700, lineHeight: 1.12 }}>{e.title}</div>
              {e.detail && <div data-audit="body" style={{ fontSize: fs, color: pal.muted, lineHeight: 1.2, marginTop: 4 }}>{e.detail}</div>}
            </div>
          </div>
        );
      })}
    </div>
  );
};

/* ------------------------------------------------------------------------------------------ flow */
export type FlowData = {
  meta: ChartMeta; headline?: string;
  nodes: { id: string; label: string; level: number; tone?: "accent" | "accent2" | "accent3" | "negative" }[];
  edges: { from: string; to: string; label?: string }[];
};

export const FlowDiagram: React.FC<{ data: FlowData }> = ({ data }) => (
  <ChartShell meta={data.meta} headline={data.headline}>
    <PlotSlot>{({ w, h }) => <FlowPlot data={data} w={w} h={h} />}</PlotSlot>
  </ChartShell>
);

const FlowPlot: React.FC<{ data: FlowData; w: number; h: number }> = ({ data, w, h }) => {
  const { L, pal } = useStudio();
  const f = useCurrentFrame();
  const fs = L.type.label;
  const levels = Math.max(...data.nodes.map((n) => n.level)) + 1;
  const byLevel: string[][] = Array.from({ length: levels }, () => []);
  data.nodes.forEach((n) => byLevel[n.level].push(n.id));
  const widest = Math.max(...byLevel.map((l) => l.length));
  // box size
  const gapMain = L.vertical ? 74 : 110, gapCross = 28;
  const boxW = L.vertical ? Math.min(430, (w - gapCross * (widest - 1)) / widest) : (w - gapMain * (levels - 1)) / levels;
  const boxH = L.vertical ? Math.min(150, (h - gapMain * (levels - 1)) / levels) : Math.min(180, (h - gapCross * (widest - 1)) / widest);
  const pos: Record<string, { x: number; y: number; k: number }> = {};
  data.nodes.forEach((n) => {
    const row = byLevel[n.level], idx = row.indexOf(n.id), cnt = row.length;
    const mainPos = L.vertical ? (h - boxH) * (levels === 1 ? 0 : n.level / (levels - 1)) : n.level * (boxW + gapMain);
    const crossSpan = L.vertical ? w : h, crossBox = L.vertical ? boxW : boxH;
    const total = cnt * crossBox + (cnt - 1) * gapCross;
    const crossPos = (crossSpan - total) / 2 + idx * (crossBox + gapCross);
    const k = ease(clamp01((f - (6 + n.level * 14 + idx * 4)) / 18));
    pos[n.id] = L.vertical ? { x: crossPos, y: mainPos, k } : { x: mainPos, y: crossPos, k };
  });
  const edgePath = (a: string, b: string) => {
    const p = pos[a], q = pos[b];
    if (L.vertical) {
      const x1 = p.x + boxW / 2, y1 = p.y + boxH, x2 = q.x + boxW / 2, y2 = q.y;
      const my = (y1 + y2) / 2;
      return { d: `M ${x1} ${y1} C ${x1} ${my}, ${x2} ${my}, ${x2} ${y2 - 12}`, mx: (x1 + x2) / 2, my, ax: x2, ay: y2, ang: 90 };
    }
    const x1 = p.x + boxW, y1 = p.y + boxH / 2, x2 = q.x, y2 = q.y + boxH / 2;
    const mx = (x1 + x2) / 2;
    return { d: `M ${x1} ${y1} C ${mx} ${y1}, ${mx} ${y2}, ${x2 - 12} ${y2}`, mx, my: (y1 + y2) / 2, ax: x2, ay: y2, ang: 0 };
  };
  const toneOf = (t?: string) => (t ? pal[t as "accent"] : pal.accent);
  return (
    <div style={{ position: "absolute", inset: 0 }}>
      <svg width={w} height={h} style={{ position: "absolute", inset: 0, overflow: "visible" }}>
        {data.edges.map((e, i) => {
          const ed = edgePath(e.from, e.to);
          const k = Math.min(pos[e.from].k, pos[e.to].k);
          const grow = ease(clamp01((f - (14 + data.nodes.find((n) => n.id === e.to)!.level * 14) + 8) / 22));
          return (
            <g key={i} opacity={Math.max(0.0, grow)}>
              <path d={ed.d} fill="none" stroke={pal.grid} strokeWidth={6} pathLength={1} />
              <path d={ed.d} fill="none" stroke={pal.accent} strokeWidth={6} strokeLinecap="round" pathLength={1} strokeDasharray="0.04 0.06" strokeDashoffset={-f * 0.012} opacity={k} />
              <polygon points="0,-13 22,0 0,13" fill={pal.accent} transform={`translate(${ed.ax - 22 * (ed.ang === 0 ? 1 : 0)} ${ed.ay - 22 * (ed.ang === 90 ? 1 : 0)}) rotate(${ed.ang})`} />
              {e.label && (
                <text x={ed.mx} y={ed.my - 12} textAnchor="middle" fontSize={fs} fill={pal.muted} stroke={pal.bg} strokeWidth={8} paintOrder="stroke" data-audit="stamp">{e.label}</text>
              )}
            </g>
          );
        })}
      </svg>
      {data.nodes.map((n) => {
        const p = pos[n.id];
        return (
          <div key={n.id} data-audit="body" style={{
            position: "absolute", left: p.x, top: p.y, width: boxW, height: boxH, opacity: p.k, transform: `translateY(${(1 - p.k) * 20}px)`,
            background: pal.panel, border: `3px solid ${toneOf(n.tone)}`, borderRadius: 22, boxSizing: "border-box", padding: "8px 18px",
            display: "flex", alignItems: "center", justifyContent: "center", textAlign: "center", fontSize: fs, fontWeight: 700, lineHeight: 1.15, color: pal.ink,
          }}>{n.label}</div>
        );
      })}
    </div>
  );
};
