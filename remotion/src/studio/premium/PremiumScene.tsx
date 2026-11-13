import React from "react";
import { AbsoluteFill, useCurrentFrame } from "remotion";
import { BarChart, NumberCounter, YieldCurve } from "../Charts";
import { Timeline } from "../Diagrams";
import type { FlowData, TimelineData } from "../Diagrams";
import { useStudio } from "../context";
import type { ChartSceneData } from "../SceneRenderer";
import { TRANSITION_FRAMES, type StudioScene, type TransitionKind } from "../scenes";
import { stripEmphasis } from "../styles";
import { PremiumBackdrop, type BackdropId } from "./Backdrops";
import { contentPose, moveFor, type Pose } from "./camera";
import { usePremium, type Carry } from "./context";
import { EASE, clamp01, mix, range } from "./motion";
import { PremiumLineChart, chartCarry, initialFigure, headerCol, headerFigure, type PremiumChartData } from "./PChart";
import { PremiumFlow, flowCarry } from "./PFlow";
import { PremiumKinetic, kineticCarry } from "./PKinetic";
import { PT, PTYPE } from "./tokens";
import { toLocalWords } from "./words";

/** Camera pose of scene `index` at its local frame f. Used by the scene itself and by a morph that starts in the previous scene. */
export const poseAt = (s: StudioScene, index: number, f: number, dur: number): Pose =>
  contentPose(moveFor(s.camera_move, s.role, index), clamp01(f / Math.max(1, dur - 1)), index % 2 ? -1 : 1);

const isLine = (d: unknown): d is PremiumChartData & { kind: "line" } => !!d && (d as { kind?: string }).kind === "line";

/** The figure a scene hands to a following morph, or null. */
export const carryOf = (s: StudioScene, data: unknown, bw: number, bh: number, o: "horizontal" | "vertical", locale: string): Carry | null => {
  const T = PTYPE[o];
  if (s.type === "chart" && isLine(data)) return chartCarry(data, bw, T, locale, o === "vertical");
  if (s.type === "flow") return flowCarry(data as FlowData, bw, bh, o === "vertical", T);
  if (s.type === "kinetic" && s.on_screen_text) return kineticCarry(s.on_screen_text, bw, bh, T.display * (o === "vertical" ? 0.78 : 0.8) * 1.28);
  return null;
};

/** Where a morph lands: only a premium line chart has a header figure to land on. */
export const carryTarget = (s: StudioScene, data: unknown, bw: number, o: "horizontal" | "vertical", carry?: Carry | null, locale = "en-US") => {
  if (s.type !== "chart" || !isLine(data)) return null;
  if (carry && carry.text.replace(/[^0-9.]/g, "") !== initialFigure(data as PremiumChartData, locale).replace(/[^0-9.]/g, "")) return null;   // same number only
  const T = PTYPE[o];
  const d = data as PremiumChartData;
  const colW = headerCol(bw, o === "vertical");
  const lines = o === "vertical" ? (!d.headline ? 0 : Math.min(2, Math.max(1, Math.ceil((d.headline.length * 0.54 * T.headline) / colW)))) : Math.min(3, Math.max(1, Math.ceil(((d.headline ?? "").length * 0.54 * T.headline) / colW)));
  return headerFigure(colW, lines, T);
};

const Exit: React.FC<{ kind: TransitionKind | null; children: React.ReactNode }> = ({ kind, children }) => {
  const f = useCurrentFrame();
  const { dur, overlap } = usePremium();
  if (!kind || f < dur) return <AbsoluteFill>{children}</AbsoluteFill>;
  const p = range(f, dur, Math.max(1, overlap));
  if (kind === "push_through") return <AbsoluteFill style={{ opacity: 1 - EASE.smooth(p), transform: `scale(${1 + 0.24 * EASE.in(p)})`, transformOrigin: "50% 45%" }}>{children}</AbsoluteFill>;
  if (kind === "morph") return <AbsoluteFill style={{ opacity: 1 - EASE.smooth(p) }}>{children}</AbsoluteFill>;
  return <AbsoluteFill>{children}</AbsoluteFill>;
};

type ArtProps = { scene: StudioScene; data: unknown; index: number; backdrop: BackdropId; exitKind: TransitionKind | null };

const Content: React.FC<{ scene: StudioScene; data: unknown }> = ({ scene, data }) => {
  const text = scene.on_screen_text;
  switch (scene.type) {
    case "chart": {
      const d = data as ChartSceneData;
      if (d.kind === "line") return <PremiumLineChart data={{ ...(d as PremiumChartData), headline: text ? stripEmphasis(text) : (d as PremiumChartData).headline }} />;
      return null;
    }
    case "flow": return <PremiumFlow data={{ ...(data as FlowData), headline: text ? stripEmphasis(text) : (data as FlowData).headline }} />;
    case "kinetic": return <PremiumKinetic text={text ?? ""} silent={scene.role === "disclaimer"} />;
    default: return null;
  }
};

/** Chart kinds and diagrams the premium kit does not redraw yet render with the classic components, on a premium backdrop and
 *  without the content camera (their layout is not inset for it). */
const Fallback: React.FC<{ scene: StudioScene; data: unknown }> = ({ scene, data }) => {
  const text = scene.on_screen_text ? stripEmphasis(scene.on_screen_text) : undefined;
  if (scene.type === "timeline") return <Timeline data={{ ...(data as TimelineData), headline: text ?? (data as TimelineData).headline }} />;
  const d = data as ChartSceneData;
  const h = text ?? (d as { headline?: string }).headline;
  if (d.kind === "bar") return <BarChart data={{ ...d, headline: h }} />;
  if (d.kind === "yield") return <YieldCurve data={{ ...d, headline: h }} />;
  if (d.kind === "counter") return <NumberCounter data={{ ...d, headline: h }} />;
  return null;
};

const needsFallback = (s: StudioScene, data: unknown) =>
  s.type === "timeline" || (s.type === "chart" && !isLine(data));

export const PremiumArt: React.FC<ArtProps> = ({ scene, data, index, backdrop, exitKind }) => {
  const { L } = useStudio();
  const { dur, box } = usePremium();
  const f = useCurrentFrame();
  const fallback = needsFallback(scene, data);
  const pose = poseAt(scene, index, f, dur);
  const cx = (L.x0 + L.x1) / 2, cy = (L.y0 + L.y1) / 2;
  return (
    <Exit kind={exitKind}>
      <PremiumBackdrop id={backdrop} w={L.w} h={L.h} f={f} pose={pose} seed={index + 1} />
      {fallback ? <Fallback scene={scene} data={data} /> : (
        <div style={{ position: "absolute", inset: 0, transform: `translate(${pose.x}px, ${pose.y}px) scale(${pose.scale})`, transformOrigin: `${cx}px ${cy}px` }}>
          <div style={{ position: "absolute", left: box.x0, top: box.y0, width: box.x1 - box.x0, height: box.y1 - box.y0 }}>
            <Content scene={scene} data={data} />
          </div>
        </div>
      )}
    </Exit>
  );
};

/** A figure travelling from the previous scene's key element to the incoming chart's header (shared-element morph), in frame space. */
export const MorphGhost: React.FC<{ carry: Carry; target: { x: number; y: number; size: number }; from: Pose; to: Pose; boxX: number; boxY: number; cx: number; cy: number }> = ({ carry, target, from, to, boxX, boxY, cx, cy }) => {
  const f = useCurrentFrame();
  const { font } = usePremium();
  const n = TRANSITION_FRAMES.morph;
  const t = EASE.inOut(range(f, 0, n));
  if (f >= n) return null;
  const at = (p: { x: number; y: number }, pose: Pose) => ({ x: cx + (boxX + p.x - cx) * pose.scale + pose.x, y: cy + (boxY + p.y - cy) * pose.scale + pose.y });
  const a = at(carry, from), b = at(target, to);
  const size = mix(carry.size * from.scale, target.size * to.scale, t);
  return (
    <div data-audit="headline" style={{ position: "absolute", left: mix(a.x, b.x, t), top: mix(a.y, b.y, t), fontSize: size, lineHeight: 1, fontWeight: 700, color: PT.amber, letterSpacing: -4,
      fontVariantNumeric: "tabular-nums", whiteSpace: "nowrap", fontFamily: font }}>{carry.text}</div>
  );
};
