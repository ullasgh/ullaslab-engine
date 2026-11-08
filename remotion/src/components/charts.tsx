import React from "react";
import { C, fmt, t } from "../brand";
import { ease } from "../hooks";
import { useCtx } from "../layout";
import { Chart, Series } from "../types";

type Beat = { index: number; count: number; since: number };
type Geo = { W: number; H: number; l: number; r: number; tp: number; b: number };

const colorOf = (s: Series, i: number) =>
  ({ primary: C.primary, secondary: C.secondary, accent: C.accent, muted: C.muted } as const)[s.color ?? (["primary", "secondary", "accent", "muted"] as const)[i % 4]];

const extent = (series: Series[], zero: boolean) => {
  const ys = series.flatMap((s) => s.points.map((p) => p.y));
  let lo = Math.min(...ys), hi = Math.max(...ys);
  if (zero) { lo = Math.min(0, lo); hi = Math.max(0, hi); }
  if (lo === hi) { lo -= 1; hi += 1; }
  const pad = (hi - lo) * 0.08;
  return [zero && lo === 0 ? 0 : lo - pad, hi + pad] as const;
};

const Axes: React.FC<{ g: Geo; lo: number; hi: number; xs: (string | number)[]; dec: number; locale: string; bars?: boolean }> = ({ g, lo, hi, xs, dec, locale, bars }) => {
  const { L } = useCtx();
  const y = (v: number) => g.H - g.b - ((v - lo) / (hi - lo)) * (g.H - g.b - g.tp);
  const ticks = [lo + (hi - lo) * 0.08, (lo + hi) / 2, hi - (hi - lo) * 0.08];
  const n = xs.length;
  const xi = n > 1 ? [0, Math.floor((n - 1) / 2), n - 1] : [0];
  const xpos = (i: number) => (bars ? g.l + ((i + 0.5) / n) * (g.W - g.l - g.r) : g.l + (i / Math.max(1, n - 1)) * (g.W - g.l - g.r));
  return (
    <g>
      {ticks.map((v, i) => (
        <g key={i}>
          <line x1={g.l} x2={g.W - g.r} y1={y(v)} y2={y(v)} stroke={C.grid} strokeWidth={2} />
          <text data-audit="axis" x={g.l - 14} y={y(v) + 12} textAnchor="end" fontSize={L.type.label} fill={C.muted}>{fmt(v, dec, locale)}</text>
        </g>
      ))}
      {(bars ? xs.map((_, i) => i) : xi).map((i) => {
        const anchor = !bars && i === 0 ? "start" : !bars && i === n - 1 && n > 1 ? "end" : "middle";
        const x = xpos(i);
        return <text data-audit="axis" key={i} x={anchor === "start" ? g.l : anchor === "end" ? g.W - g.r : x} y={g.H - 12} textAnchor={anchor} fontSize={L.type.label} fill={C.muted}>{String(xs[i])}</text>;
      })}
    </g>
  );
};

const geo = (W: number, H: number, locale: string, series: Series[], dec: number): Geo => {
  const longest = Math.max(...series.flatMap((s) => s.points.map((p) => fmt(p.y, dec, locale).length)));
  return { W, H, l: 36 + longest * 22, r: 40, tp: 24, b: 66 };
};

export const LineChart: React.FC<{ chart: Chart; W: number; H: number; frame: number; fps: number; beat: Beat; area?: boolean; dots?: boolean }> = ({ chart, W, H, frame, fps, beat, area, dots }) => {
  const { p, L } = useCtx();
  const series = chart.series!;
  const dec = chart.decimals ?? 1;
  const g = geo(W, H, p.numberLocale, series, dec);
  const [lo, hi] = extent(series, false);
  const x = (i: number, n: number) => g.l + (i / Math.max(1, n - 1)) * (W - g.l - g.r);
  const y = (v: number) => H - g.b - ((v - lo) / (hi - lo)) * (H - g.b - g.tp);
  const prog = ease(frame, 0, 1.4 * fps);
  const main = series[0].points;
  const mi = Math.round(((beat.index + 1) / Math.max(1, beat.count)) * (main.length - 1));
  const mAnim = ease(beat.since, 0, 0.4);
  const mPrev = Math.round((Math.max(0, beat.index) / Math.max(1, beat.count)) * (main.length - 1));
  const mx = x(mPrev + (mi - mPrev) * mAnim, main.length);
  const my = y(main[Math.min(main.length - 1, Math.max(0, Math.round(mPrev + (mi - mPrev) * mAnim)))].y);
  return (
    <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`} style={{ display: "block" }}>
      <Axes g={g} lo={lo} hi={hi} xs={main.map((q) => q.x)} dec={dec} locale={p.numberLocale} />
      {series.map((s, si) => {
        const d = s.points.map((q, i) => `${i ? "L" : "M"}${x(i, s.points.length).toFixed(1)},${y(q.y).toFixed(1)}`).join(" ");
        const col = colorOf(s, si);
        return (
          <g key={si}>
            {area && si === 0 && <path d={`${d} L${x(s.points.length - 1, s.points.length)},${H - g.b} L${g.l},${H - g.b} Z`} fill={col} opacity={0.14 * prog} />}
            <path d={d} fill="none" stroke={col} strokeWidth={6} strokeLinecap="round" strokeLinejoin="round" pathLength={1} strokeDasharray={1} strokeDashoffset={1 - prog} />
            {dots && s.points.map((q, i) => <circle key={i} cx={x(i, s.points.length)} cy={y(q.y)} r={7} fill={col} opacity={prog > i / s.points.length ? 1 : 0} />)}
          </g>
        );
      })}
      {prog > 0.98 && (
        <g>
          <line x1={mx} x2={mx} y1={g.tp} y2={H - g.b} stroke={C.muted} strokeWidth={2} strokeDasharray="6 8" />
          <circle cx={mx} cy={my} r={13} fill={C.text} />
          <circle cx={mx} cy={my} r={7} fill={C.primary} />
        </g>
      )}
      {chart.annotations?.map((a, i) => {
        const idx = main.findIndex((q) => String(q.x) === String(a.x));
        if (idx < 0 || prog < idx / main.length) return null;
        const ax = x(idx, main.length), ay = y(main[idx].y);
        const label = t(a.label, p.lang);
        const anchor = ax > W * 0.66 ? "end" : ax < W * 0.34 ? "start" : "middle";
        return (
          <g key={i}>
            <circle cx={ax} cy={ay} r={10} fill={C.secondary} />
            <text data-audit="label" x={ax} y={Math.max(g.tp + L.type.label, ay - 28)} textAnchor={anchor} fontSize={L.type.label} fill={C.secondary} fontWeight={700} stroke={C.panel} strokeWidth={8} paintOrder="stroke">{label}</text>
          </g>
        );
      })}
    </svg>
  );
};

export const BarChart: React.FC<{ chart: Chart; W: number; H: number; frame: number; fps: number; beat: Beat; mirrored?: boolean }> = ({ chart, W, H, frame, fps, beat }) => {
  const { p } = useCtx();
  const s = chart.series![0];
  const dec = chart.decimals ?? 1;
  const g = geo(W, H, p.numberLocale, [s], dec);
  const [lo, hi] = extent([s], true);
  const n = s.points.length;
  const slot = (W - g.l - g.r) / n;
  const y = (v: number) => H - g.b - ((v - lo) / (hi - lo)) * (H - g.b - g.tp);
  const hl = beat.index % n;
  return (
    <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`} style={{ display: "block" }}>
      <Axes g={g} lo={lo} hi={hi} xs={s.points.map((q) => q.x)} dec={dec} locale={p.numberLocale} bars />
      {s.points.map((q, i) => {
        const grow = ease(frame, i * 3, i * 3 + 0.8 * fps);
        const y0 = y(0), y1 = y0 + (y(q.y) - y0) * grow;
        const w = slot * 0.62;
        return <rect key={i} x={g.l + slot * i + (slot - w) / 2} y={Math.min(y0, y1)} width={w} height={Math.abs(y1 - y0)} rx={8}
          fill={q.y < 0 ? C.negative : i === hl ? C.primary : C.accent} opacity={i === hl ? 1 : 0.7} />;
      })}
    </svg>
  );
};

export const Legend: React.FC<{ series: Series[] }> = ({ series }) => {
  const { L, p } = useCtx();
  return (
    <div style={{ display: "flex", gap: 36, flexWrap: "wrap" }}>
      {series.map((s, i) => (
        <div key={i} data-audit="label" style={{ display: "flex", alignItems: "center", gap: 12, fontSize: L.type.label, color: C.text }}>
          <span style={{ width: 28, height: 8, borderRadius: 4, background: colorOf(s, i), display: "inline-block" }} />{t(s.name, p.lang)}
        </div>
      ))}
    </div>
  );
};

// Big-number card for counter and delta charts: counts up, shows prior and change.
export const Counter: React.FC<{ chart: Chart; frame: number; fps: number; beat: Beat; label: string }> = ({ chart, frame, fps, beat, label }) => {
  const { p, L } = useCtx();
  const dec = chart.decimals ?? 1;
  const v = chart.value ?? 0;
  const shown = v * ease(frame, 0, 1.5 * fps);
  const delta = chart.prior !== undefined ? v - chart.prior : undefined;
  const pulse = ease(beat.since, 0, 0.6);
  const unit = chart.unit ?? "";
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 20, alignItems: "flex-start" }}>
      <div data-audit="body" style={{ fontSize: L.type.body, color: C.muted, direction: p.rtl ? "rtl" : "ltr" }}>{label}</div>
      <div data-audit="headline" style={{ fontSize: L.vertical ? 200 : 220, fontWeight: 700, lineHeight: 1.05, color: C.primary, fontVariantNumeric: "tabular-nums", direction: "ltr" }}>
        {fmt(shown, dec, p.numberLocale)}{unit}
      </div>
      {delta !== undefined && (
        <div style={{ display: "flex", gap: 28, alignItems: "center", opacity: ease(frame, 1.2 * fps, 1.7 * fps), direction: "ltr" }}>
          <span data-audit="body" style={{ fontSize: L.type.body, color: C.muted }}>{fmt(chart.prior!, dec, p.numberLocale)}{unit}</span>
          <span data-audit="body" style={{ fontSize: L.type.body, fontWeight: 700, color: delta < 0 ? C.negative : C.primary, boxShadow: `0 0 0 ${6 * (1 - pulse)}px ${delta < 0 ? C.negative : C.primary}55`, borderRadius: 12, padding: "4px 14px" }}>
            {delta < 0 ? "▼" : delta > 0 ? "▲" : "▬"} {fmt(Math.abs(delta), dec, p.numberLocale)}
          </span>
        </div>
      )}
    </div>
  );
};
