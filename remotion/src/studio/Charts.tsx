import React, { useLayoutEffect, useRef, useState } from "react";
import { useCurrentFrame } from "remotion";
import { scalePoint } from "d3-scale";
import { ticks as d3ticks } from "d3-array";
import { useRamp, useStudio } from "./context";
import { ChartShell, type ChartMeta } from "./Stamp";
import { counterValue, fmtNum, linePath, makeLinear, makeTimeScale, niceExtent, parseX, plotValues, revealPoints, type Band, type XY } from "./chartMath";
import type { Palette } from "./palettes";

type ColorKey = "accent" | "accent2" | "accent3" | "negative" | "muted";
const colorOf = (pal: Palette, k?: ColorKey) => (k ? pal[k] : pal.accent);
const SERIES_COLORS: ColorKey[] = ["accent", "accent2", "accent3"];

// Measures the flexible plot slot so SVG text renders 1:1 (no viewBox scaling).
export const PlotSlot: React.FC<{ children: (size: { w: number; h: number }) => React.ReactNode }> = ({ children }) => {
  const ref = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState({ w: 0, h: 0 });
  useLayoutEffect(() => {
    const el = ref.current;
    if (el) setSize({ w: el.clientWidth, h: el.clientHeight });
  }, []);
  return <div ref={ref} style={{ position: "absolute", inset: 0 }}>{size.w > 0 && children(size)}</div>;
};

const Y_TICKS = 4;
const svgBox: React.CSSProperties = { position: "absolute", inset: 0, overflow: "visible" };

/* ----------------------------------------------------------------------------------------- line */
export type LineData = {
  meta: ChartMeta; headline?: string;
  series: { name: string; color?: ColorKey; points: { x: string | number; y: number }[] }[];
  annotations?: { x: string | number; label: string }[];
  /** Scenario range: a shaded y-range (both edges are numbers from the data passed in) from `from` to the right edge. */
  band?: Band;
  decimals?: number; includeZero?: boolean; revealFrames?: number;
};

const xTickLabel = (d: Date, spanDays: number) =>
  spanDays > 900 ? String(d.getUTCFullYear()) : d.toLocaleDateString("en-US", { month: "short", year: "2-digit", timeZone: "UTC" });

export const LineChart: React.FC<{ data: LineData }> = ({ data }) => (
  <ChartShell meta={data.meta} headline={data.headline}>
    <PlotSlot>{({ w, h }) => <LinePlot data={data} w={w} h={h} />}</PlotSlot>
  </ChartShell>
);

const LinePlot: React.FC<{ data: LineData; w: number; h: number }> = ({ data, w, h }) => {
  const { L, pal, numberLocale, preset } = useStudio();
  const fs = L.type.label;
  const dec = data.decimals ?? 1;
  const multi = data.series.length > 1;
  const band = preset.chart.band ? data.band : undefined;
  const m = { l: 18 + fs * 2.3, r: fs * 2.6, t: (multi ? fs * 1.9 : 20) + (data.annotations?.length ? fs * 2.4 : 0), b: fs * 2.1 };
  const xs = data.series.flatMap((s) => s.points.map((p) => parseX(p.x)));
  const ys = plotValues(data.series, band);
  const X = makeTimeScale(xs, [m.l, w - m.r]);
  const Yd = niceExtent(ys, 0.1, data.includeZero ?? preset.chart.zeroBaseline);
  const Y = makeLinear(Yd, [h - m.b, m.t]);
  const span = (Math.max(...xs) - Math.min(...xs)) / 86400000;
  const xt = X.ticks(L.vertical ? 4 : 6);
  const yt = d3ticks(Yd[0], Yd[1], Y_TICKS);
  const reveal = useRamp(10, 10 + (data.revealFrames ?? 80));
  return (
    <svg width={w} height={h} style={svgBox}>
      {yt.map((v) => (
        <g key={v}>
          <line x1={m.l} x2={w - m.r} y1={Y(v)} y2={Y(v)} stroke={pal.grid} strokeWidth={1.5} />
          <text x={m.l - 12} y={Y(v) + fs * 0.35} textAnchor="end" fontSize={fs} fill={pal.muted}>{fmtNum(v, dec, numberLocale)}</text>
        </g>
      ))}
      {xt.map((d) => { const near = X(d) - m.l < fs * 1.4; return <text key={+d} x={near ? m.l : X(d)} y={h - m.b + fs * 1.3} textAnchor={near ? "start" : "middle"} fontSize={fs} fill={pal.muted}>{xTickLabel(d, span)}</text>; })}
      {band && (() => {
        const bx = Math.max(m.l, Math.min(w - m.r, band.from === undefined ? X(Math.max(...xs)) - (w - m.r - m.l) * 0.35 : X(parseX(band.from))));
        const k = Math.min(1, Math.max(0, (reveal - (bx - m.l) / (w - m.r - m.l)) * 6));
        const y0 = Y(band.hi), y1 = Y(band.lo);
        return (
          <g opacity={k}>
            <rect x={bx} y={y0} width={w - m.r - bx} height={Math.max(2, y1 - y0)} fill={pal.accent2} opacity={0.18} />
            <line x1={bx} x2={w - m.r} y1={y0} y2={y0} stroke={pal.accent2} strokeWidth={2.5} strokeDasharray="10 8" />
            <line x1={bx} x2={w - m.r} y1={y1} y2={y1} stroke={pal.accent2} strokeWidth={2.5} strokeDasharray="10 8" />
            <text x={bx + 10} y={Math.max(y0 + fs * 1.05, y1 - 10)} textAnchor="start" fontSize={fs} fontWeight={700} fill={pal.accent2} stroke={pal.bg} strokeWidth={8} paintOrder="stroke" data-audit="stamp">{band.label}</text>
          </g>
        );
      })()}
      {multi && data.series.map((s, i) => {
        const lx = m.l + i * (L.vertical ? 330 : 420);
        return (
          <g key={s.name}>
            <rect x={lx} y={fs * 0.15} width={fs * 0.9} height={8} rx={4} fill={colorOf(pal, s.color ?? SERIES_COLORS[i])} />
            <text x={lx + fs * 1.15} y={fs * 0.8} fontSize={fs} fill={pal.ink}>{s.name}</text>
          </g>
        );
      })}
      {data.series.map((s, i) => {
        const c = colorOf(pal, s.color ?? SERIES_COLORS[i]);
        const pts: XY[] = s.points.map((p) => ({ x: X(parseX(p.x)), y: Y(p.y) }));
        const vis = revealPoints(pts, reveal);
        const tip = vis[vis.length - 1];
        const val = s.points[Math.min(s.points.length - 1, Math.round(reveal * (s.points.length - 1)))].y;
        const flip = false;
        // keep tip labels apart: a series whose tip sits within one text height below another puts its label underneath
        const lastY = (o: typeof s) => Y(o.points[Math.min(o.points.length - 1, Math.round(reveal * (o.points.length - 1)))].y);
        const crowdedAbove = data.series.some((o) => o !== s && lastY(o) <= tip.y && (tip.y - lastY(o) < fs * 1.1) && (lastY(o) < tip.y || data.series.indexOf(o) < data.series.indexOf(s)));
        const labelY = (crowdedAbove ? tip.y + fs * 0.55 : tip.y - fs * 0.15) + fs * 0.35;
        return (
          <g key={s.name}>
            {!multi && <path d={`${linePath(vis)} L ${tip.x} ${h - m.b} L ${vis[0].x} ${h - m.b} Z`} fill={c} opacity={0.1} />}
            <path d={linePath(vis)} fill="none" stroke={c} strokeWidth={L.vertical ? 6 : 7} strokeLinecap="round" strokeLinejoin="round" />
            <circle cx={tip.x} cy={tip.y} r={11} fill={c} stroke={pal.bg} strokeWidth={4} />
            {reveal > 0.05 && (
              <text x={tip.x + 18} y={labelY} textAnchor={flip ? "end" : "start"} fontSize={fs} fontWeight={700} fill={pal.ink}
                stroke={pal.bg} strokeWidth={7} paintOrder="stroke" data-audit="stamp">{fmtNum(val, dec, numberLocale)}</text>
            )}
          </g>
        );
      })}
      {(data.annotations ?? []).map((a, i) => {
        const ax = X(parseX(a.x));
        const prog = (ax - m.l) / (w - m.r - m.l);
        if (reveal < prog) return null;
        const s0 = data.series[0];
        const near = s0.points.reduce((best, p) => (Math.abs(parseX(p.x) - parseX(a.x)) < Math.abs(parseX(best.x) - parseX(a.x)) ? p : best));
        const ay = Y(near.y);
        const level = i % 2;
        const ty = fs * (1.0 + level * 1.15) + (multi ? fs * 1.9 : 0);
        const anchor = ax > w * 0.62 ? "end" : ax < w * 0.2 ? "start" : "middle";
        const k = Math.min(1, (reveal - prog) * 12);
        return (
          <g key={i} opacity={k}>
            <line x1={ax} x2={ax} y1={ty + 10} y2={ay - 14} stroke={pal.accent2} strokeWidth={2.5} strokeDasharray="6 6" />
            <circle cx={ax} cy={ay} r={9} fill="none" stroke={pal.accent2} strokeWidth={4} />
            <text x={ax} y={ty} textAnchor={anchor} fontSize={fs} fontWeight={700} fill={pal.accent2} stroke={pal.bg} strokeWidth={8} paintOrder="stroke" data-audit="stamp">{a.label}</text>
          </g>
        );
      })}
    </svg>
  );
};

/* ------------------------------------------------------------------------------------------ bar */
export type BarData = {
  meta: ChartMeta; headline?: string; bars: { label: string; value: number; highlight?: boolean }[]; decimals?: number; suffix?: string;
};

export const BarChart: React.FC<{ data: BarData }> = ({ data }) => (
  <ChartShell meta={data.meta} headline={data.headline}>
    <PlotSlot>{({ w, h }) => <BarPlot data={data} w={w} h={h} />}</PlotSlot>
  </ChartShell>
);

const BarPlot: React.FC<{ data: BarData; w: number; h: number }> = ({ data, w, h }) => {
  const { L, pal, numberLocale } = useStudio();
  const f = useCurrentFrame();
  const fs = L.type.label;
  const n = data.bars.length;
  const dec = data.decimals ?? 1;
  const labelW = L.vertical ? 0 : Math.min(w * 0.3, 420);
  const valW = fs * 4.2;
  const rowH = h / n;
  const barH = Math.min(L.vertical ? 56 : 64, rowH * (L.vertical ? 0.42 : 0.62));
  const max = Math.max(...data.bars.map((b) => b.value), 0);
  const X = makeLinear([0, max || 1], [0, w - labelW - valW - 12]);
  return (
    <svg width={w} height={h} style={svgBox}>
      {data.bars.map((b, i) => {
        const a = Math.min(1, Math.max(0, (f - (6 + i * 7)) / 26));
        const k = 1 - Math.pow(1 - a, 3);
        const y = i * rowH + (L.vertical ? fs * 1.15 : (rowH - barH) / 2);
        const c = b.highlight ? pal.accent2 : pal.accent;
        const bw = Math.max(2, X(b.value) * k);
        return (
          <g key={b.label} opacity={Math.min(1, k * 3)}>
            <text x={0} y={L.vertical ? y - fs * 0.25 : y + barH / 2 + fs * 0.35} fontSize={fs} fill={b.highlight ? pal.ink : pal.muted} fontWeight={b.highlight ? 700 : 400}>{b.label}</text>
            <rect x={labelW} y={y} width={bw} height={barH} rx={barH / 2.8} fill={c} opacity={b.highlight ? 1 : 0.78} />
            <text x={labelW + bw + 14} y={y + barH / 2 + fs * 0.35} fontSize={fs} fontWeight={700} fill={pal.ink} data-audit="stamp">
              {fmtNum(b.value * k, dec, numberLocale)}{data.suffix ?? ""}
            </text>
          </g>
        );
      })}
    </svg>
  );
};

/* ----------------------------------------------------------------------------------- yield curve */
export type YieldData = {
  meta: ChartMeta; headline?: string; tenors: string[]; now: number[]; nowLabel: string; prior?: number[]; priorLabel?: string; decimals?: number;
};

export const YieldCurve: React.FC<{ data: YieldData }> = ({ data }) => (
  <ChartShell meta={data.meta} headline={data.headline}>
    <PlotSlot>{({ w, h }) => <YieldPlot data={data} w={w} h={h} />}</PlotSlot>
  </ChartShell>
);

const YieldPlot: React.FC<{ data: YieldData; w: number; h: number }> = ({ data, w, h }) => {
  const { L, pal, numberLocale, preset } = useStudio();
  const fs = L.type.label;
  const dec = data.decimals ?? 2;
  const m = { l: 18 + fs * 2.3, r: 30, t: fs * 2.2, b: fs * 1.7 };
  const X = scalePoint<string>().domain(data.tenors).range([m.l + 90, w - m.r - 60]);
  const Yd = niceExtent([...data.now, ...(data.prior ?? [])], 0.15, preset.chart.zeroBaseline);
  const Y = makeLinear(Yd, [h - m.b, m.t]);
  const reveal = useRamp(8, 70);
  const pts = (arr: number[]): XY[] => arr.map((v, i) => ({ x: X(data.tenors[i])!, y: Y(v) }));
  const yt = d3ticks(Yd[0], Yd[1], Y_TICKS);
  const nowVis = revealPoints(pts(data.now), reveal);
  const px = m.l + (L.vertical ? 330 : 400);
  return (
    <svg width={w} height={h} style={svgBox}>
      {yt.map((v) => (
        <g key={v}>
          <line x1={m.l} x2={w - m.r} y1={Y(v)} y2={Y(v)} stroke={pal.grid} strokeWidth={1.5} />
          <text x={m.l - 12} y={Y(v) + fs * 0.35} textAnchor="end" fontSize={fs} fill={pal.muted}>{fmtNum(v, 1, numberLocale)}</text>
        </g>
      ))}
      {data.tenors.map((t) => <text key={t} x={X(t)} y={h - m.b + fs * 1.15} textAnchor="middle" fontSize={fs} fill={pal.muted}>{t}</text>)}
      <rect x={m.l} y={fs * 0.15} width={fs * 0.9} height={8} rx={4} fill={pal.accent} />
      <text x={m.l + fs * 1.15} y={fs * 0.8} fontSize={fs} fill={pal.ink}>{data.nowLabel}</text>
      {data.prior && <>
        <rect x={px} y={fs * 0.15} width={fs * 0.9} height={8} rx={4} fill={pal.muted} />
        <text x={px + fs * 1.15} y={fs * 0.8} fontSize={fs} fill={pal.muted}>{data.priorLabel}</text>
      </>}
      {data.prior && <path d={linePath(pts(data.prior))} fill="none" stroke={pal.muted} strokeWidth={4.5} strokeDasharray="4 12" strokeLinecap="round" />}
      <path d={linePath(nowVis)} fill="none" stroke={pal.accent} strokeWidth={7} strokeLinecap="round" />
      {pts(data.now).map((p, i) => (reveal >= i / (data.now.length - 1) - 0.001 ? (
        <g key={i}>
          <circle cx={p.x} cy={p.y} r={11} fill={pal.accent} stroke={pal.bg} strokeWidth={4} />
          <text x={p.x} y={p.y - 24} textAnchor="middle" fontSize={fs} fontWeight={700} fill={pal.ink} stroke={pal.bg} strokeWidth={7} paintOrder="stroke" data-audit="stamp">{fmtNum(data.now[i], dec, numberLocale)}</text>
        </g>
      ) : null))}
    </svg>
  );
};

/* ------------------------------------------------------------------------------------- counter */
export type CounterData = {
  meta: ChartMeta; headline?: string; value: number; from?: number; decimals?: number; prefix?: string; suffix?: string;
  delta?: { text: string; tone?: "up" | "down" | "flat" }; spark?: number[];
};

export const NumberCounter: React.FC<{ data: CounterData }> = ({ data }) => {
  const { L, pal, numberLocale } = useStudio();
  const f = useCurrentFrame();
  const v = counterValue(data.from ?? 0, data.value, (f - 8) / 48);
  const k = useRamp(46, 62);
  return (
    <ChartShell meta={data.meta} headline={data.headline}>
      <div style={{ position: "absolute", inset: 0, display: "flex", flexDirection: "column", justifyContent: "center", gap: 22 }}>
        <div data-audit="headline" style={{ fontSize: L.type.number, fontWeight: 700, lineHeight: 1, color: pal.ink, letterSpacing: -4, fontVariantNumeric: "tabular-nums" }}>
          {data.prefix}{fmtNum(v, data.decimals ?? 1, numberLocale)}<span style={{ color: pal.accent, fontSize: L.type.number * 0.6 }}>{data.suffix}</span>
        </div>
        {data.delta && (
          <div data-audit="body" style={{ opacity: k, transform: `translateY(${(1 - k) * 14}px)`, alignSelf: "flex-start", fontSize: L.type.body, fontWeight: 700, padding: "4px 24px", borderRadius: 999,
            color: pal.bg, background: data.delta.tone === "down" ? pal.negative : data.delta.tone === "flat" ? pal.muted : pal.accent3 }}>{data.delta.text}</div>
        )}
        {data.spark && <Spark values={data.spark} w={L.cw} h={L.vertical ? 200 : 170} />}
      </div>
    </ChartShell>
  );
};

const Spark: React.FC<{ values: number[]; w: number; h: number }> = ({ values, w, h }) => {
  const { pal } = useStudio();
  const reveal = useRamp(20, 80);
  const X = makeLinear([0, values.length - 1], [6, w - 6]);
  const Y = makeLinear(niceExtent(values, 0.1), [h - 8, 8]);
  const vis = revealPoints(values.map((v, i) => ({ x: X(i), y: Y(v) })), reveal);
  const tip = vis[vis.length - 1];
  return (
    <svg width={w} height={h} style={{ overflow: "visible" }}>
      <line x1={0} x2={w} y1={h - 1} y2={h - 1} stroke={pal.grid} strokeWidth={2} />
      <path d={linePath(vis)} fill="none" stroke={pal.accent} strokeWidth={5} strokeLinecap="round" />
      <circle cx={tip.x} cy={tip.y} r={9} fill={pal.accent} stroke={pal.bg} strokeWidth={3} />
    </svg>
  );
};
