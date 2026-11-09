import React, { useMemo } from "react";
import { useCurrentFrame } from "remotion";
import { feature } from "topojson-client";
import { geoGraticule10, geoNaturalEarth1, geoOrthographic, geoPath } from "d3-geo";
import type { Feature, FeatureCollection, Geometry } from "geojson";
import world from "./data/countries-110m.json";
import { StudioSourceStamp, SceneHeadline, type ChartMeta } from "./Stamp";
import { useCameraStyle, useFont, useRamp, useStudio } from "./context";
import { FOCUS, along, onNearSide, sampleRoute, splitJumps, type LonLat } from "./geoMath";
import { linePath } from "./chartMath";
import type { CameraMove } from "./scenes";
import type { Palette } from "./palettes";

type Topo = Parameters<typeof feature>[0];
const countries = feature(world as unknown as Topo, (world as any).objects.countries) as unknown as FeatureCollection<Geometry, { name: string }>;
const land = feature(world as unknown as Topo, (world as any).objects.land) as unknown as Feature<Geometry>;
const graticule = geoGraticule10();

type ColorKey = "accent" | "accent2" | "accent3" | "negative";
export type GeoRoute = { id: string; name?: string; points: LonLat[]; color?: ColorKey; delay?: number; duration?: number; markers?: number; dashed?: boolean };
type LabelPlace = { text?: string; at?: LonLat; dx?: number; dy?: number; anchor?: "start" | "middle" | "end" };
export type GeoLabel = { text: string; at: LonLat; dx?: number; dy?: number; anchor?: "start" | "middle" | "end"; delay?: number; color?: ColorKey; dot?: boolean; vertical?: LabelPlace };
// Labels may carry a 9:16 placement override (the framing differs, so collisions differ).
const place = (l: GeoLabel, vertical: boolean): GeoLabel => (vertical && l.vertical ? { ...l, ...l.vertical } : l);
export type GeoHighlight = { id: string; color?: ColorKey; label?: GeoLabel };
export type GeoMeta = Pick<ChartMeta, "source" | "freshness" | "caveat">;

export type MapData = {
  meta: GeoMeta; focus?: string | { center: LonLat; zoom: number }; focusVertical?: string | { center: LonLat; zoom: number };
  highlights?: GeoHighlight[]; routes?: GeoRoute[]; labels?: GeoLabel[];
};
export type GlobeData = {
  meta: GeoMeta; lon0?: number; lonSpeed?: number; lat?: number;
  highlights?: GeoHighlight[]; routes?: GeoRoute[]; labels?: GeoLabel[];
};

const col = (pal: Palette, k: ColorKey | undefined) => pal[k ?? "accent"];

const Label: React.FC<{ x: number; y: number; l: GeoLabel; pal: Palette; size: number; show?: boolean }> = ({ x, y, l, pal, size, show = true }) => {
  const k = useRamp(l.delay ?? 20, (l.delay ?? 20) + 14);
  if (!show) return null;
  const c = col(pal, l.color);
  return (
    <g opacity={k} transform={`translate(0 ${(1 - k) * 8})`}>
      {l.dot !== false && <circle cx={x} cy={y} r={size * 0.17} fill={c} stroke={pal.bg} strokeWidth={3} />}
      <text x={x + (l.dx ?? 0)} y={y + (l.dy ?? 0)} textAnchor={l.anchor ?? "start"} fontSize={size} fontWeight={700} fill={pal.ink}
        stroke={pal.bg} strokeWidth={size * 0.22} strokeLinejoin="round" paintOrder="stroke" data-audit="stamp">{l.text}</text>
    </g>
  );
};

type Proj = ReturnType<typeof geoNaturalEarth1>;

const Routes: React.FC<{ routes: GeoRoute[]; project: (p: LonLat) => [number, number] | null; visible?: (p: LonLat) => boolean; pal: Palette; jump: number; maxW: number }> = ({ routes, project, visible, pal, jump, maxW }) => {
  const f = useCurrentFrame();
  return (
    <>
      {routes.map((r) => {
        const samples = sampleRoute(r.points, 40);
        const delay = r.delay ?? 0, dur = r.duration ?? 60;
        const raw = Math.min(1, Math.max(0, (f - delay) / dur));
        const p = raw * raw * (3 - 2 * raw);
        const c = col(pal, r.color);
        const n = Math.max(1, Math.round(p * (samples.length - 1)));
        // projected runs (split where hidden or wrapped)
        const runs: [number, number][][] = [];
        let cur: [number, number][] = [];
        samples.forEach((s, i) => {
          const q = i <= n && (!visible || visible(s)) ? project(s) : null;
          if (q) cur.push(q); else if (cur.length) { runs.push(cur); cur = []; }
        });
        if (cur.length) runs.push(cur);
        const segs = runs.flatMap((rr) => splitJumps(rr, jump));
        const fullProj = samples.map((s) => ((!visible || visible(s)) ? project(s) : null));
        const markersN = r.markers ?? 2;
        return (
          <g key={r.id}>
            {segs.map((sg, i) => sg.length > 1 && (
              <React.Fragment key={i}>
                <path d={linePath(sg.map(([x, y]) => ({ x, y })), false)} fill="none" stroke={c} strokeOpacity={0.28} strokeWidth={maxW * 3.2} strokeLinecap="round" strokeLinejoin="round" />
                <path d={linePath(sg.map(([x, y]) => ({ x, y })), false)} fill="none" stroke={c} strokeWidth={maxW} strokeLinecap="round" strokeLinejoin="round" strokeDasharray={r.dashed ? `${maxW * 2.4} ${maxW * 2}` : undefined} />
              </React.Fragment>
            ))}
            {p > 0.02 && Array.from({ length: markersN }, (_, i) => {
              const base = ((f - delay) / (dur * 1.6) + i / markersN) % 1;
              const m = base * 1;
              if (m > p) return null;
              const idx = Math.round(m * (samples.length - 1));
              const pt = fullProj[idx];
              if (!pt) return null;
              // trail
              const trail = fullProj.slice(Math.max(0, idx - 9), idx + 1).filter((q): q is [number, number] => !!q);
              const tr = splitJumps(trail, jump).filter((s) => s.length > 1);
              return (
                <g key={i}>
                  {tr.map((s, j) => <path key={j} d={linePath(s.map(([x, y]) => ({ x, y })), false)} fill="none" stroke={pal.ink} strokeOpacity={0.85} strokeWidth={maxW * 1.4} strokeLinecap="round" />)}
                  <circle cx={pt[0]} cy={pt[1]} r={maxW * 3.4} fill={c} opacity={0.35} />
                  <circle cx={pt[0]} cy={pt[1]} r={maxW * 1.9} fill={pal.ink} stroke={c} strokeWidth={maxW * 0.9} />
                </g>
              );
            })}
          </g>
        );
      })}
    </>
  );
};

const Highlights: React.FC<{ items: GeoHighlight[]; path: ReturnType<typeof geoPath>; pal: Palette; size: number; projectLL?: (p: LonLat) => [number, number] | null; visible?: (p: LonLat) => boolean; vertical?: boolean }> = ({ items, path, pal, size, projectLL, visible, vertical }) => {
  const f = useCurrentFrame();
  const pulse = 0.38 + 0.1 * Math.sin(f / 14);
  return (
    <>
      {items.map((h) => {
        const feat = countries.features.find((c) => String(c.id) === h.id);
        if (!feat) return null;
        const c = col(pal, h.color);
        const d = path(feat);
        return d ? <path key={h.id} d={d} fill={c} fillOpacity={pulse} stroke={c} strokeWidth={size * 0.05} /> : null;
      })}
      {items.map((h) => {
        if (!h.label || !projectLL) return null;
        const hl = place(h.label, !!vertical);
        if (visible && !visible(hl.at)) return null;
        const q = projectLL(hl.at);
        return q ? <Label key={`l${h.id}`} x={q[0]} y={q[1]} l={{ ...hl, color: hl.color ?? h.color }} pal={pal} size={size} /> : null;
      })}
    </>
  );
};

// Soft bottom scrim so the stamp stays legible over land and glow.
const Scrim: React.FC = () => {
  const { L, pal } = useStudio();
  const hh = (L.reserve ? 0 : L.h - L.y1) + 230;
  return <div style={{ position: "absolute", left: 0, bottom: L.reserve ? L.h - L.y1 : 0, width: L.w, height: hh, background: `linear-gradient(to bottom, transparent 0%, ${pal.bg}e6 62%, ${pal.bg} 100%)` }} />;
};

export const MapScene: React.FC<{ data: MapData; headline?: string; camera?: CameraMove }> = ({ data, headline, camera }) => {
  const { L, pal } = useStudio();
  const font = useFont();
  const cam = useCameraStyle(camera);
  const fSel = (L.vertical && data.focusVertical) || data.focus;
  const focus = typeof fSel === "string" || !fSel ? FOCUS[(fSel as string) ?? "world"] ?? FOCUS.world : fSel;
  const top = L.vertical ? L.y0 + 230 : 0;
  const boxW = L.w, boxH = (L.reserve ? L.y1 : L.h) - top;   // with captions reserved the map ends above the caption zone
  const { project, path, size } = useMemo(() => {
    const base = geoNaturalEarth1().fitSize([boxW * 0.98, boxH * 0.92], { type: "Sphere" } as any);
    const k = base.scale() * focus.zoom;
    const p: Proj = geoNaturalEarth1().scale(k).center(focus.center).translate([boxW / 2, boxH / 2]);
    return { project: (ll: LonLat) => p(ll) as [number, number] | null, path: geoPath(p), size: L.type.label };
  }, [boxW, boxH, focus.zoom, focus.center[0], focus.center[1], L.type.label]);
  const k = useRamp(0, 16);
  return (
    <div style={{ position: "absolute", inset: 0, fontFamily: font }}>
      <div style={{ position: "absolute", left: 0, top, width: boxW, height: boxH, overflow: "hidden", opacity: k,
        WebkitMaskImage: L.vertical ? "linear-gradient(to bottom, transparent 0, #000 60px)" : undefined }}>
        <div style={{ width: boxW, height: boxH, ...cam }}>
          <svg width={boxW} height={boxH} style={{ display: "block" }}>
            <path d={path({ type: "Sphere" } as any) ?? ""} fill={pal.water} opacity={0.35} />
            <path d={path(graticule) ?? ""} fill="none" stroke={pal.grid} strokeWidth={1.5} opacity={0.5} />
            <path d={path(land) ?? ""} fill={pal.land} stroke={pal.landLine} strokeWidth={1.2} />
            <path d={path({ type: "FeatureCollection", features: countries.features } as any) ?? ""} fill="none" stroke={pal.landLine} strokeWidth={0.8} opacity={0.8} />
            <Highlights items={data.highlights ?? []} path={path} pal={pal} size={size} projectLL={project} vertical={L.vertical} />
            <Routes routes={data.routes ?? []} project={project} pal={pal} jump={boxW / 2.2} maxW={L.vertical ? 5 : 5} />
            {(data.labels ?? []).map((l0, i) => { const l = place(l0, L.vertical); const q = project(l.at); return q ? <Label key={i} x={q[0]} y={q[1]} l={l} pal={pal} size={size} /> : null; })}
          </svg>
        </div>
      </div>
      <Scrim />
      <SceneHeadline text={headline} maxWidth={L.vertical ? L.cw : L.cw * 0.62} />
      <div style={{ position: "absolute", left: L.x0, bottom: L.h - L.y1, width: L.cw }}>
        {data.meta.caveat && <div data-audit="stamp" style={{ fontSize: L.type.stamp, color: pal.muted, fontStyle: "italic", marginBottom: 6 }}>{data.meta.caveat}</div>}
        <StudioSourceStamp source={data.meta.source} freshness={data.meta.freshness} />
      </div>
    </div>
  );
};

export const GlobeScene: React.FC<{ data: GlobeData; headline?: string; camera?: CameraMove }> = ({ data, headline, camera }) => {
  const { L, pal } = useStudio();
  const font = useFont();
  const f = useCurrentFrame();
  const cam = useCameraStyle(camera);
  const r = L.vertical ? L.cw * 0.44 : L.reserve ? Math.min(420, L.ch * 0.5 - 40) : 420;
  const cx = L.vertical ? L.x0 + L.cw / 2 : L.w * 0.66;
  const cy = L.vertical ? L.y0 + 270 + (L.ch - 270 - 190) / 2 : L.reserve ? (L.y0 + L.y1) / 2 : L.h * 0.5;
  const lon = (data.lon0 ?? 20) + f * (data.lonSpeed ?? 0.45);
  const lat = data.lat ?? 18;
  const proj = geoOrthographic().scale(r).translate([cx, cy]).rotate([-lon, -lat]).clipAngle(90);
  const path = geoPath(proj);
  const center: LonLat = [lon, lat];
  const project = (p: LonLat) => proj(p) as [number, number] | null;
  const visible = (p: LonLat) => onNearSide(p, center);
  const k = useRamp(0, 18);
  const size = L.type.label;
  return (
    <div style={{ position: "absolute", inset: 0, fontFamily: font }}>
      <div style={{ position: "absolute", inset: 0, opacity: k, ...cam }}>
        <svg width={L.w} height={L.h} style={{ display: "block" }}>
          <defs>
            <radialGradient id="globe-sea" cx="38%" cy="32%" r="80%">
              <stop offset="0%" stopColor={pal.bg2} /><stop offset="70%" stopColor={pal.water} /><stop offset="100%" stopColor={pal.bg} />
            </radialGradient>
            <radialGradient id="globe-glow" cx="50%" cy="50%" r="50%">
              <stop offset="88%" stopColor={pal.accent} stopOpacity={0.0} /><stop offset="96%" stopColor={pal.accent} stopOpacity={0.28} /><stop offset="100%" stopColor={pal.accent} stopOpacity={0} />
            </radialGradient>
          </defs>
          <circle cx={cx} cy={cy} r={r * 1.14} fill="url(#globe-glow)" />
          <circle cx={cx} cy={cy} r={r} fill="url(#globe-sea)" />
          <path d={path(graticule) ?? ""} fill="none" stroke={pal.grid} strokeWidth={1.4} opacity={0.6} />
          <path d={path(land) ?? ""} fill={pal.land} stroke={pal.landLine} strokeWidth={1.4} />
          <Highlights items={data.highlights ?? []} path={path} pal={pal} size={size} projectLL={project} visible={visible} vertical={L.vertical} />
          <Routes routes={data.routes ?? []} project={project} visible={visible} pal={pal} jump={r} maxW={5} />
          {(data.labels ?? []).map((l, i) => { if (!visible(l.at)) return null; const q = project(l.at); return q ? <Label key={i} x={q[0]} y={q[1]} l={l} pal={pal} size={size} /> : null; })}
          <circle cx={cx} cy={cy} r={r} fill="none" stroke={pal.accent} strokeOpacity={0.45} strokeWidth={2} />
        </svg>
      </div>
      <Scrim />
      <SceneHeadline text={headline} maxWidth={L.vertical ? L.cw : L.cw * 0.4} />
      <div style={{ position: "absolute", left: L.x0, bottom: L.h - L.y1, width: L.cw }}>
        {data.meta.caveat && <div data-audit="stamp" style={{ fontSize: L.type.stamp, color: pal.muted, fontStyle: "italic", marginBottom: 6 }}>{data.meta.caveat}</div>}
        <StudioSourceStamp source={data.meta.source} freshness={data.meta.freshness} />
      </div>
    </div>
  );
};
