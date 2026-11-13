import React from "react";
import { AbsoluteFill, Sequence, useCurrentFrame } from "remotion";
import { Backdrop } from "./Backdrop";
import { BarChart, LineChart, NumberCounter, YieldCurve, type BarData, type CounterData, type LineData, type YieldData } from "./Charts";
import { StudioProvider, useCameraStyle, useStudio } from "./context";
import { FlowDiagram, Timeline, type FlowData, type TimelineData } from "./Diagrams";
import { FootageScene, type FootageData } from "./Footage";
import { GlobeScene, MapScene, type GlobeData, type MapData } from "./geo";
import { KineticText } from "./Kinetic";
import { CardStack, ChalkSteps, CreatorKinetic } from "./StyleKit";
import { isStyledType, resolveStyle, stripEmphasis, type StyleId } from "./styles";
import type { Orientation, Platform } from "./layout";
import { normalizeScenes, type DirectorScene } from "./director";
import { TRANSITION_FRAMES, overlapAfter, resolveData, transitionProgress, validateScenes, type StudioScene, type TransitionKind } from "./scenes";
import { backdropFor, type BackdropId } from "./premium/Backdrops";
import { PremiumProvider, type Carry } from "./premium/context";
import { PremiumArt, MorphGhost, carryOf, carryTarget, poseAt } from "./premium/PremiumScene";
import { contentBox } from "./premium/camera";
import { PremiumEnter } from "./premium/PremiumEnter";
import { toLocalWords } from "./premium/words";
import { studioLayout } from "./layout";

export type ChartSceneData =
  | ({ kind: "line" } & LineData) | ({ kind: "bar" } & BarData) | ({ kind: "yield" } & YieldData) | ({ kind: "counter" } & CounterData);

export type SceneRendererProps = {
  orientation: Orientation;
  scenes: (StudioScene | DirectorScene)[];   // kit shape or director scenes.json scenes (schema v1)
  refs: Record<string, unknown>;   // resolves each scene's data_ref
  lang?: string;
  numberLocale?: string;
  platform?: Platform;      // safe-area template: "both" (stricter union, default) or one platform
  reserveBottom?: number;   // px held back at the bottom of the safe box (burned-in captions)
  style?: StyleId;          // item video style (V2 M2); a scene's own `style` wins; absent = the default look
  brandMark?: unknown;      // premium end card only (see premium/PEnd.tsx); read by StudioVideo, not by the scenes
};

// Data-licensing gate: a styled chart, timeline or flow scene must carry its source (the stamp is always drawn by ChartShell).
const assertSource = (scene: StudioScene, data: unknown, required: boolean) => {
  if (!required || scene.type === "kinetic" || scene.type === "footage") return;
  const src = (data as { meta?: { source?: { name?: string } } } | undefined)?.meta?.source?.name;
  if (!src) throw new Error(`scene ${scene.id}: ${scene.type} scene has no meta.source, a source stamp is required`);
};

const StyledKinetic: React.FC<{ text: string }> = ({ text }) => {
  const { style } = useStudio();
  switch (style) {
    case "creator-motion": return <CreatorKinetic text={text} />;
    case "chalk-talk": return <ChalkSteps text={text} />;
    case "clean-tech": return <CardStack text={text} />;
    default: return <KineticText text={text} />;
  }
};

const Art: React.FC<{ scene: StudioScene; data: unknown }> = ({ scene, data }) => {
  // Kinetic scenes parse the markup themselves; everywhere else the words are shown plain.
  const text = scene.type === "kinetic" || scene.on_screen_text === undefined ? scene.on_screen_text : stripEmphasis(scene.on_screen_text);
  const cam = useCameraStyle(scene.camera_move);
  const { pal, preset } = useStudio();
  assertSource(scene, data, preset.chart.requireSource);
  const withBackdrop = (node: React.ReactNode) => (
    <AbsoluteFill style={{ background: pal.bg }}>
      <div style={{ position: "absolute", inset: 0, ...cam }}><Backdrop /></div>
      {node}
    </AbsoluteFill>
  );
  switch (scene.type) {
    case "footage": return <FootageScene data={(data ?? {}) as FootageData} headline={text} camera={scene.camera_move} />;
    case "map": return <AbsoluteFill style={{ background: pal.bg }}><Backdrop grid={false} /><MapScene data={data as MapData} headline={text} camera={scene.camera_move} /></AbsoluteFill>;
    case "globe": return <AbsoluteFill style={{ background: pal.bg }}><Backdrop grid={false} /><GlobeScene data={data as GlobeData} headline={text} camera={scene.camera_move} /></AbsoluteFill>;
    case "chart": {
      const d = data as ChartSceneData;
      const h = text ?? (d.headline === undefined ? undefined : stripEmphasis(d.headline));
      switch (d.kind) {
        case "line": return withBackdrop(<LineChart data={{ ...d, headline: h }} />);
        case "bar": return withBackdrop(<BarChart data={{ ...d, headline: h }} />);
        case "yield": return withBackdrop(<YieldCurve data={{ ...d, headline: h }} />);
        case "counter": return withBackdrop(<NumberCounter data={{ ...d, headline: h }} />);
        default: throw new Error(`scene ${scene.id}: unknown chart kind "${(d as { kind?: string }).kind}"`);
      }
    }
    case "timeline": return withBackdrop(<Timeline data={{ ...(data as TimelineData), headline: text ?? stripEmphasis((data as TimelineData).headline ?? "") }} />);
    case "flow": return withBackdrop(<FlowDiagram data={{ ...(data as FlowData), headline: text ?? stripEmphasis((data as FlowData).headline ?? "") }} />);
    case "kinetic": return withBackdrop(<StyledKinetic text={text ?? ""} />);
  }
};

// Entering transition. Restrained set only: cut, crossfade, wipe, match-move (incoming scene settles from the
// outgoing scene's camera scale). Applied to the incoming scene, which is stacked above the outgoing one.
const Enter: React.FC<{ kind: TransitionKind; first: boolean; accent: string; children: React.ReactNode }> = ({ kind, first, accent, children }) => {
  const f = useCurrentFrame();
  const k = first ? "cut" : kind;
  const p = transitionProgress(k, f);
  if (k === "cut" || p >= 1) return <AbsoluteFill>{children}</AbsoluteFill>;
  if (k === "wipe") {
    return (
      <AbsoluteFill style={{ clipPath: `inset(0 ${(1 - p) * 100}% 0 0)` }}>
        {children}
        <div style={{ position: "absolute", top: 0, bottom: 0, left: `${p * 100}%`, width: 6, marginLeft: -6, background: accent, opacity: 0.8 }} />
      </AbsoluteFill>
    );
  }
  if (k === "match_move") {
    return <AbsoluteFill style={{ opacity: p, transform: `scale(${1 + 0.09 * (1 - p)})`, transformOrigin: "50% 50%" }}>{children}</AbsoluteFill>;
  }
  return <AbsoluteFill style={{ opacity: p }}>{children}</AbsoluteFill>;
};

export const SceneRenderer: React.FC<SceneRendererProps> = ({ orientation, scenes: raw, refs, lang, numberLocale, reserveBottom, platform, style: itemStyle }) => {
  const scenes = normalizeScenes(raw, 30, itemStyle);
  const errs = validateScenes(scenes, refs);
  if (errs.length) throw new Error(`scenes.json invalid:\n${errs.join("\n")}`);
  const styles = scenes.map((s) => (isStyledType(s.type) ? resolveStyle(itemStyle, s.style) : undefined));   // footage, map and globe render unchanged
  // premium: per-scene backdrop (never the same twice in a row), and the figure a morph carries from one scene to the next
  const L = studioLayout(orientation, reserveBottom ?? 0, platform ?? "both", "premium");
  const cb = contentBox({ x0: L.x0, y0: L.y0, x1: L.x1, y1: L.y1 });
  const bw = cb.x1 - cb.x0, bh = cb.y1 - cb.y0;
  let prevBackdrop: BackdropId | undefined;
  const backdrops = scenes.map((s, i) => { if (styles[i] !== "premium") return undefined; const b = backdropFor(s.role, s.type, prevBackdrop); prevBackdrop = b; return b; });
  const locale = numberLocale ?? "en-US";
  const datas = scenes.map((s) => resolveData(s, refs));
  const carries = scenes.map((s, i) => (styles[i] === "premium" ? carryOf(s, datas[i], bw, bh, orientation, locale) : null));
  return (
    <AbsoluteFill>
      {scenes.map((s, i) => {
        const data = datas[i];
        const style = styles[i];
        const overlap = overlapAfter(scenes, i);
        const dur = s.end - s.start;
        if (style !== "premium") {
          return (
            <Sequence key={s.id} from={s.start} durationInFrames={dur + overlap} name={`${s.type}:${s.id}`}>
              <StudioProvider orientation={orientation} topic={s.palette} lang={lang} numberLocale={numberLocale} reserveBottom={reserveBottom} platform={platform} style={style}>
                <SceneEnter scene={s} first={i === 0}><Art scene={s} data={data} /></SceneEnter>
              </StudioProvider>
            </Sequence>
          );
        }
        const next = scenes[i + 1];
        const prev = scenes[i - 1];
        const target = s.transition === "morph" && i > 0 && styles[i - 1] === "premium" ? carryTarget(s, data, bw, orientation, carries[i - 1], locale) : null;
        const carryIn: Carry | null = target ? carries[i - 1] : null;
        const morphOut = !!next && next.transition === "morph" && styles[i + 1] === "premium" && !!carries[i] && !!carryTarget(next, datas[i + 1], bw, orientation, carries[i], locale);
        const exitKind: TransitionKind | null = next ? (next.transition ?? "cut") : null;
        return (
          <Sequence key={s.id} from={s.start} durationInFrames={dur + overlap} name={`${s.type}:${s.id}`}>
            <StudioProvider orientation={orientation} topic={s.palette} lang={lang} numberLocale={numberLocale} reserveBottom={reserveBottom} platform={platform} style="premium">
              <PremiumProvider dur={dur} overlap={overlap} words={toLocalWords(s.words, s.start)} role={s.role} index={i} carryIn={carryIn} morphOut={morphOut}>
                <PremiumEnter kind={s.transition ?? "cut"} first={i === 0}>
                  <PremiumArt scene={s} data={data} index={i} backdrop={backdrops[i]!} exitKind={exitKind} />
                  {carryIn && target && prev && (
                    <MorphGhost carry={carryIn} target={target} from={poseAt(prev, i - 1, prev.end - prev.start, prev.end - prev.start)} to={poseAt(s, i, TRANSITION_FRAMES.morph, dur)}
                      boxX={cb.x0} boxY={cb.y0} cx={(L.x0 + L.x1) / 2} cy={(L.y0 + L.y1) / 2} />
                  )}
                </PremiumEnter>
              </PremiumProvider>
            </StudioProvider>
          </Sequence>
        );
      })}
    </AbsoluteFill>
  );
};

const SceneEnter: React.FC<{ scene: StudioScene; first: boolean; children: React.ReactNode }> = ({ scene, first, children }) => {
  const { pal } = useStudio();
  return <Enter kind={scene.transition ?? "cut"} first={first} accent={pal.accent}>{children}</Enter>;
};
