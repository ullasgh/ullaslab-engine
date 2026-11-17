import React from "react";
import { useCurrentFrame } from "remotion";
import { scaleUtc } from "d3-scale";
import { StudioSourceStamp, type ChartMeta } from "../Stamp";
import { fmtNum, linePath, parseX, pickTicks, revealPoints } from "../chartMath";
import { useStudio } from "../context";
import { EASE, SPRING, breathe, clamp01, loop, mix, range, springOut } from "./motion";
import { PT, SP } from "./tokens";
import { usePremium, type Carry } from "./context";
import { domainAt, linear, valueAt, yTicks, SCRUB, type View } from "./viewMath";
import { findWord } from "./words";

export type PremiumChartData = {
  meta: ChartMeta; headline?: string;
  series: { name: string; points: { x: string | number; y: number }[] }[];
  views?: View[];                       // chart sequence (premium); absent = one view built from the classic fields
  annotations?: { x: string | number; label: string }[];
  highlight?: { from: string | number; to: string | number; label?: string };
  decimals?: number;
};

/** Views of a chart: the premium sequence, or the single classic view (all of the series, its highlight and annotations). */
export const viewsOf = (d: PremiumChartData): View[] => {
  if (d.views?.length) return d.views;
  const pts = d.series[0].points;
  return [{ window: { from: pts[0].x, to: pts[pts.length - 1].x }, highlight: d.highlight,
    marks: (d.annotations ?? []).map((a) => ({ x: a.x, label: a.label })), point: { x: pts[pts.length - 1].x } }];
};

const unitSuffix = (unit: string) => (/percent/i.test(unit) ? "%" : "");

/** Where the header figure sits (scene-local px) and how big: shared by the chart and by a morph that lands on it. */
export const headerFigure = (colW: number, headlineLines: number, T: { headline: number; number: number }) => ({ x: 0, y: headlineLines * T.headline * 1.12 + SP.s, size: T.number, colW });
/** Width of the header column: the whole content width on a tall frame, the left third on a wide one (the plot takes the rest). */
export const headerCol = (bw: number, vertical: boolean) => (vertical ? bw : bw * 0.36);
const linesFor = (text: string | undefined, size: number, bw: number) => (!text ? 0 : Math.min(2, Math.max(1, Math.ceil((text.length * 0.54 * size) / bw))));

const xTickLabel = (d: Date, spanDays: number) =>
  spanDays > 900 ? String(d.getUTCFullYear())
    : spanDays <= 62 ? d.toLocaleDateString("en-US", { month: "short", day: "numeric", timeZone: "UTC" })
      : d.toLocaleDateString("en-US", { month: "short", year: "2-digit", timeZone: "UTC" });

type KF = { f: number; x: number };

export const PremiumLineChart: React.FC<{ data: PremiumChartData }> = ({ data }) => {
  const { L, numberLocale } = useStudio();
  const { bw, bh, T, font, words, carryIn, morphOut } = usePremium();
  const f = useCurrentFrame();
  const pts = data.series[0].points;
  const dec = data.decimals ?? 1;
  const views = viewsOf(data).map((v) => ({ ...v }));
  const fullX = [parseX(pts[0].x), parseX(pts[pts.length - 1].x)];

  // ---- timing: every view starts on its spoken word (or spread across the scene); marks and the tip land on their words
  let cursor = 0;
  const wf = (tok: string | undefined, fb: number) => { if (!tok) return fb; const h = findWord(words, tok, cursor); if (!h) return fb; cursor = h.i + 1; return Math.max(0, h.w.a); };
  const startAt = 8;
  const kfs: KF[][] = [];
  const marksAt: number[][] = [];
  views.forEach((v, i) => {
    v.atFrame = i === 0 ? 0 : wf(v.atWord, Math.round(startAt + i * 70));
    const x0 = parseX(v.window.from);
    const list: KF[] = [{ f: i === 0 ? startAt : v.atFrame + SCRUB * 0.6, x: i === 0 ? x0 : Number.NaN }];
    const ms = (v.marks ?? []).map((m) => ({ m, x: parseX(m.x) })).sort((a, b) => a.x - b.x);
    const mf: number[] = [];
    ms.forEach(({ m, x }, k) => {
      const t = wf(m.atWord, Math.round((v.atFrame ?? 0) + 30 + k * 26));
      mf.push(t);
      list.push({ f: Math.max(t, list[list.length - 1].f + 6), x });
    });
    const endX = parseX((v.point ?? { x: v.window.to }).x);
    const endF = wf(v.point?.atWord, Math.round((v.atFrame ?? 0) + 60));
    if (!list.length || list[list.length - 1].x !== endX) list.push({ f: Math.max(endF, list[list.length - 1].f + 6), x: endX });
    kfs.push(list);
    marksAt.push(mf);
  });
  // a later view starts its line where the previous one ended
  kfs.forEach((list, i) => { if (i > 0) list[0].x = kfs[i - 1][kfs[i - 1].length - 1].x; });
  const revealAt = (frame: number): { x: number; landed: number } => {
    // piecewise keyframes over all views, eased per segment
    const all = kfs.flat();
    if (frame <= all[0].f) return { x: all[0].x, landed: -1 };
    for (let i = 1; i < all.length; i++) {
      if (frame <= all[i].f) {
        const t = EASE.inOut((frame - all[i - 1].f) / Math.max(1, all[i].f - all[i - 1].f));
        return { x: mix(all[i - 1].x, all[i].x, t), landed: i };
      }
    }
    return { x: all[all.length - 1].x, landed: all.length };
  };
  const { x: revealX } = revealAt(f);
  const { dom, i: vi, blend, from: domFrom, to: domTo } = domainAt(pts, views, f);

  // ---- layout (scene-local px). Tall frame: header on top, plot below, axis caption and source stamp at the bottom.
  // Wide frame: header (headline, figure, axis notes) in a left column, plot on the right, source stamp along the bottom.
  const fs = T.label;
  const vertical = L.vertical;
  const colW = headerCol(bw, vertical);
  const headLines = vertical ? linesFor(data.headline, T.headline, colW) : Math.min(3, Math.max(1, Math.ceil(((data.headline ?? "").length * 0.54 * T.headline) / colW)));
  const hf = headerFigure(colW, headLines, T);
  const stampH = T.stamp * 1.25 * 2 + 4 + (data.meta.caveat ? T.stamp * 1.3 : 0);
  const capH = vertical ? fs * 1.2 + SP.s : 0;
  const plotX = vertical ? 0 : colW + SP.xl, plotW = bw - plotX;
  const plotTop = vertical ? hf.y + hf.size + SP.s : 0;
  const plotH = Math.max(200, bh - plotTop - stampH - capH - SP.s);
  const hasMarks = views.some((v) => (v.marks?.length ?? 0) > 0 || v.point?.label);
  const m = { l: fs * 2.5, r: 22, t: hasMarks ? fs * 1.9 : fs * 0.5, b: fs * 2.4 };
  const X = linear([dom.x0, dom.x1], [m.l, plotW - m.r]);
  const Y = linear([dom.y0, dom.y1], [plotH - m.b, m.t]);

  const shown = (() => {
    const vis = pts.map((p) => ({ x: parseX(p.x), y: p.y })).filter((p) => p.x <= revealX);
    const tipY = valueAt(pts, revealX);
    if (!vis.length || vis[vis.length - 1].x < revealX) vis.push({ x: revealX, y: tipY });
    return vis;
  })();
  const xy = shown.map((p) => ({ x: X(p.x), y: Y(p.y) }));
  const tip = xy[xy.length - 1];
  const d = linePath(xy);
  const tipVal = valueAt(pts, revealX);
  const reached = revealX >= kfs[kfs.length - 1][kfs[kfs.length - 1].length - 1].x - 1;

  // ---- ticks, two sets (the view scrubbed from and the one scrubbed to) cross-faded so labels never pop
  const spanDays = (dd: { x0: number; x1: number }) => (dd.x1 - dd.x0) / 86400000;
  const xTicksFor = (dd: typeof dom, op: number) => {
    const sc = scaleUtc().domain([dd.x0, dd.x1]).range([m.l, plotW - m.r]);
    const all = sc.ticks(L.vertical ? 4 : 6);
    const lab = (t: Date) => xTickLabel(t, spanDays(dd));
    const keep = pickTicks(all.map((t) => X(+t)), all.map((t) => lab(t).length * fs * 0.62), fs * 0.9).map((i) => all[i]);
    return keep.filter((t) => X(+t) >= m.l - 1 && X(+t) <= plotW - m.r + 1).map((t) => ({ key: +t, x: X(+t), label: lab(t), op }));
  };
  const xTicks = blend >= 1 ? xTicksFor(domTo, 1) : [...xTicksFor(domFrom, 1 - blend), ...xTicksFor(domTo, blend)];
  const yTicksSet = (dd: typeof dom, op: number) => yTicks(dd, 4).map((v) => ({ v, op }));
  const yT = blend >= 1 ? yTicksSet(domTo, 1) : [...yTicksSet(domFrom, 1 - blend).map((t) => ({ ...t, k: "a" })), ...yTicksSet(domTo, blend).map((t) => ({ ...t, k: "b" }))];

  const zoomed = domTo.y0 > 0 || spanDays(domTo) < spanDays({ x0: fullX[0], x1: fullX[1] }) - 1;
  const view = views[vi];
  const hl = view.highlight;
  const hlWord = hl?.atWord ? findWord(words, hl.atWord, 0) : null;
  const hlStart = hlWord ? Math.max(0, hlWord.w.a) : kfs.flat().find((k) => hl && k.x >= parseX(hl.to))?.f ?? (view.atFrame ?? 0) + 40;

  // ---- header figure: follows the line tip; lands with a spring when the tip reaches a mark; a morph hands it over
  const lastLand = Math.max(...marksAt.flat(), ...kfs.map((k) => k[k.length - 1].f));
  const pops = [...marksAt.flat(), ...kfs.map((k) => k[k.length - 1].f)];
  const popScale = 1 + 0.07 * Math.max(0, ...pops.map((t) => { const a = (f - t) / 16; return a >= 0 && a < 1 ? Math.sin(Math.PI * a) * (1 - a) : 0; }));
  // axes arrive after the scene has settled in, so a transition never shows the incoming scale behind the outgoing scene
  const axisIn = EASE.out(range(f, 14, 12));
  const figure = fmtNum(tipVal, dec, numberLocale);
  const intro = carryIn ? (f >= 20 ? 1 : 0) : EASE.out(range(f, 2, 14));   // with a morph the carried figure is drawn by the ghost until it lands
  const dim = morphOut ? 0 : 1;

  return (
    <div style={{ position: "absolute", left: 0, top: 0, width: bw, height: bh, fontFamily: font, color: PT.ink }}>
      {data.headline && (
        <div data-audit="headline" style={{ position: "absolute", left: 0, top: 0, width: colW, fontSize: T.headline, fontWeight: 700, lineHeight: 1.12, opacity: EASE.out(range(f, 0, 12)), transform: `translateY(${(1 - EASE.out(range(f, 0, 14))) * 18}px)` }}>
          {data.headline}
        </div>
      )}
      {/* header figure: follows the line tip */}
      <div data-audit="headline" style={{ position: "absolute", left: hf.x, top: hf.y, height: hf.size, fontSize: hf.size, lineHeight: 1, fontWeight: 700, color: PT.amber, letterSpacing: -4,
        fontVariantNumeric: "tabular-nums", opacity: intro * dim, transform: `scale(${popScale})`, transformOrigin: "0% 60%", whiteSpace: "nowrap" }}>
        {figure}<span style={{ fontSize: hf.size * 0.42, marginLeft: 6, color: PT.amber, letterSpacing: 0 }}>{unitSuffix(data.meta.unit)}</span>
      </div>
      {zoomed && (
        <div data-audit="axis" style={{ position: "absolute", left: vertical ? bw * 0.56 : 0, top: vertical ? hf.y + 20 : hf.y + hf.size + SP.s, width: vertical ? bw * 0.44 : colW, fontSize: fs, color: PT.amber, lineHeight: 1.2, fontWeight: 700, opacity: EASE.out(range(f, 8, 12)) }}>
          Zoomed view, axis not from zero
        </div>
      )}
      {!vertical && (
        <div style={{ position: "absolute", left: 0, top: hf.y + hf.size + SP.s + (zoomed ? fs * 1.2 * 2 + SP.s : 0), width: colW, opacity: EASE.out(range(f, 4, 14)) }}>
          <div data-audit="axis" style={{ fontSize: fs, color: PT.muted, lineHeight: 1.2 }}>{data.meta.metric}</div>
          <div data-audit="axis" style={{ fontSize: fs, color: PT.muted, lineHeight: 1.2 }}>{data.meta.unit}</div>
        </div>
      )}
      {/* plot */}
      <svg width={plotW} height={plotH} style={{ position: "absolute", left: plotX, top: plotTop, overflow: "visible" }}>
        <defs>
          <linearGradient id={`area-${vi}`} x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor={PT.teal} stopOpacity={0.3} /><stop offset="1" stopColor={PT.teal} stopOpacity={0} /></linearGradient>
          <clipPath id="plotclip"><rect x={m.l - 2} y={0} width={plotW - m.l - m.r + 4} height={plotH - m.b + 2} /></clipPath>
        </defs>
        {yT.map((t, i) => (
          <g key={`${(t as { k?: string }).k ?? "o"}${t.v}${i}`} opacity={t.op * axisIn}>
            <line x1={m.l} x2={plotW - m.r} y1={Y(t.v)} y2={Y(t.v)} stroke={PT.grid} strokeWidth={1.5} />
            <text x={m.l - 12} y={Y(t.v) + fs * 0.35} textAnchor="end" fontSize={fs} fill={PT.muted} data-audit="axis">{fmtNum(t.v, dec, numberLocale)}</text>
          </g>
        ))}
        {xTicks.map((t) => <text key={`${t.key}-${t.op}`} x={t.x} y={plotH - m.b + fs * 1.55} textAnchor="middle" fontSize={fs} fill={PT.muted} opacity={t.op * axisIn} data-audit="axis">{t.label}</text>)}
        <g clipPath="url(#plotclip)">
          {hl && (() => {
            const hx0 = Math.max(m.l, X(parseX(hl.from))), hx1 = Math.min(plotW - m.r, X(parseX(hl.to)));
            const k = EASE.out(range(f, hlStart, 14));
            return (
              <g opacity={k}>
                <rect x={hx0} y={m.t} width={Math.max(4, (hx1 - hx0) * k)} height={plotH - m.b - m.t} fill={PT.amber} opacity={0.14} />
                <line x1={hx0} x2={hx0} y1={m.t} y2={plotH - m.b} stroke={PT.amber} strokeWidth={2.5} strokeDasharray="8 8" />
              </g>
            );
          })()}
          <path d={`${d} L ${tip.x} ${plotH - m.b} L ${xy[0].x} ${plotH - m.b} Z`} fill={`url(#area-${vi})`} />
          <path d={d} fill="none" stroke={PT.teal} strokeWidth={14} strokeLinecap="round" strokeLinejoin="round" opacity={0.14} />
          <path d={d} fill="none" stroke={PT.teal} strokeWidth={L.vertical ? 7 : 8} strokeLinecap="round" strokeLinejoin="round" />
        </g>
        {hl?.label && (() => {
          const hx0 = Math.max(m.l, X(parseX(hl.from))), hx1 = Math.min(plotW - m.r, X(parseX(hl.to)));
          return <text x={(hx0 + hx1) / 2} y={plotH - m.b - 14} textAnchor="middle" fontSize={fs} fontWeight={700} fill={PT.amber} stroke={PT.navy0} strokeWidth={8} paintOrder="stroke" opacity={EASE.out(range(f, hlStart + 6, 12))} data-audit="stamp">{hl.label}</text>;
        })()}
        {/* marks: pins that land on the word that names them */}
        {(view.marks ?? []).concat(vi > 0 ? (views[vi - 1].marks ?? []) : []).filter((mk, i, a) => a.findIndex((o) => String(o.x) === String(mk.x)) === i).map((mk, i) => {
          const mx = X(parseX(mk.x));
          if (mx < m.l - 2 || mx > plotW - m.r + 2) return null;
          const owner = views.findIndex((v) => (v.marks ?? []).some((o) => String(o.x) === String(mk.x)));
          const ownerIdx = (views[owner].marks ?? []).findIndex((o) => String(o.x) === String(mk.x));
          const at = marksAt[owner][ownerIdx] ?? 0;
          const a = range(f, at, 16);
          if (a <= 0) return null;
          const my = Y(valueAt(pts, parseX(mk.x)));
          const label = [mk.label, mk.value !== undefined ? fmtNum(mk.value, dec, numberLocale) : ""].filter(Boolean).join(" ").trim();
          const lvl = i % 2;
          const ty = m.t - fs * 0.35 + lvl * fs * 1.15;
          const anchor = mx > plotW * 0.66 ? "end" : mx < plotW * 0.2 ? "start" : "middle";
          const k = springOut(a, SPRING.snappy);
          return (
            <g key={String(mk.x)} opacity={clamp01(a * 3)}>
              <line x1={mx} x2={mx} y1={ty + 12} y2={my - 16 * k} stroke={PT.amber} strokeWidth={2.5} strokeDasharray="6 6" />
              <circle cx={mx} cy={my} r={9 + 7 * (1 - k)} fill={PT.navy0} stroke={PT.amber} strokeWidth={4} />
              {label && <text x={mx} y={ty} textAnchor={anchor} fontSize={fs} fontWeight={700} fill={PT.amber} stroke={PT.navy0} strokeWidth={8} paintOrder="stroke" data-audit="stamp">{label}</text>}
            </g>
          );
        })}
        {/* tip: a dot with a slow pulse once the line has arrived, so a held chart still breathes */}
        <circle cx={tip.x} cy={tip.y} r={13 + (reached ? breathe(f, 40, 1.5) : 0)} fill={PT.amber} stroke={PT.navy0} strokeWidth={4} />
        {reached && <circle cx={tip.x} cy={tip.y} r={13 + 22 * loop(f, 44)} fill="none" stroke={PT.amber} strokeWidth={3} opacity={0.7 * (1 - loop(f, 44))} />}
      </svg>
      <div style={{ position: "absolute", left: 0, bottom: 0, width: bw }}>
        {vertical && <div data-audit="axis" style={{ fontSize: fs, color: PT.muted, lineHeight: 1.2, marginBottom: SP.xs }}>{data.meta.metric}{" \u00b7 "}{data.meta.unit}</div>}
        {data.meta.caveat && <div data-audit="stamp" style={{ fontSize: T.stamp, color: PT.muted, lineHeight: 1.2, fontStyle: "italic", marginBottom: SP.xs }}>{data.meta.caveat}</div>}
        <StudioSourceStamp source={data.meta.source} freshness={data.meta.freshness} />
      </div>
    </div>
  );
};

/** The header figure's text on the first frame (the series value where the first view starts). A shared-element morph is only
 *  allowed to land on it when the carried figure is the same text, so a style can never put a different number in a header. */
export const initialFigure = (data: PremiumChartData, numberLocale: string): string => {
  const v0 = viewsOf(data)[0];
  return fmtNum(valueAt(data.series[0].points, parseX(v0.window.from)), data.decimals ?? 1, numberLocale) + unitSuffix(data.meta.unit);
};

/** The figure a following scene can morph from: this chart's header figure at the end of the scene. */
export const chartCarry = (data: PremiumChartData, bw: number, T: { headline: number; number: number }, numberLocale: string, vertical = true): Carry => {
  const views = viewsOf(data);
  const last = views[views.length - 1];
  const pts = data.series[0].points;
  const endX = parseX((last.point ?? { x: last.window.to }).x);
  const colW = headerCol(bw, vertical);
  const hf = headerFigure(colW, vertical ? linesFor(data.headline, T.headline, colW) : Math.min(3, Math.max(1, Math.ceil(((data.headline ?? "").length * 0.54 * T.headline) / colW))), T);
  return { text: fmtNum(valueAt(pts, endX), data.decimals ?? 1, numberLocale) + unitSuffix(data.meta.unit), x: hf.x, y: hf.y, size: hf.size, color: PT.amber };
};
