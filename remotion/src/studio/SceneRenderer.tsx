import React from "react";
import { AbsoluteFill, Sequence, useCurrentFrame } from "remotion";
import { Backdrop } from "./Backdrop";
import { BarChart, LineChart, NumberCounter, YieldCurve, type BarData, type CounterData, type LineData, type YieldData } from "./Charts";
import { StudioProvider, useCameraStyle, useStudio } from "./context";
import { FlowDiagram, Timeline, type FlowData, type TimelineData } from "./Diagrams";
import { FootageScene, type FootageData } from "./Footage";
import { GlobeScene, MapScene, type GlobeData, type MapData } from "./geo";
import { KineticText } from "./Kinetic";
import type { Orientation } from "./layout";
import { normalizeScenes, type DirectorScene } from "./director";
import { overlapAfter, resolveData, transitionProgress, validateScenes, type StudioScene, type TransitionKind } from "./scenes";

export type ChartSceneData =
  | ({ kind: "line" } & LineData) | ({ kind: "bar" } & BarData) | ({ kind: "yield" } & YieldData) | ({ kind: "counter" } & CounterData);

export type SceneRendererProps = {
  orientation: Orientation;
  scenes: (StudioScene | DirectorScene)[];   // kit shape or director scenes.json scenes (schema v1)
  refs: Record<string, unknown>;   // resolves each scene's data_ref
  lang?: string;
  numberLocale?: string;
};

const Art: React.FC<{ scene: StudioScene; data: unknown }> = ({ scene, data }) => {
  const text = scene.on_screen_text;
  const cam = useCameraStyle(scene.camera_move);
  const { pal } = useStudio();
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
      const h = text ?? d.headline;
      switch (d.kind) {
        case "line": return withBackdrop(<LineChart data={{ ...d, headline: h }} />);
        case "bar": return withBackdrop(<BarChart data={{ ...d, headline: h }} />);
        case "yield": return withBackdrop(<YieldCurve data={{ ...d, headline: h }} />);
        case "counter": return withBackdrop(<NumberCounter data={{ ...d, headline: h }} />);
        default: throw new Error(`scene ${scene.id}: unknown chart kind "${(d as { kind?: string }).kind}"`);
      }
    }
    case "timeline": return withBackdrop(<Timeline data={{ ...(data as TimelineData), headline: text ?? (data as TimelineData).headline }} />);
    case "flow": return withBackdrop(<FlowDiagram data={{ ...(data as FlowData), headline: text ?? (data as FlowData).headline }} />);
    case "kinetic": return withBackdrop(<KineticText text={text ?? ""} />);
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

export const SceneRenderer: React.FC<SceneRendererProps> = ({ orientation, scenes: raw, refs, lang, numberLocale }) => {
  const scenes = normalizeScenes(raw);
  const errs = validateScenes(scenes, refs);
  if (errs.length) throw new Error(`scenes.json invalid:\n${errs.join("\n")}`);
  return (
    <AbsoluteFill>
      {scenes.map((s, i) => {
        const data = resolveData(s, refs);
        return (
          <Sequence key={s.id} from={s.start} durationInFrames={s.end - s.start + overlapAfter(scenes, i)} name={`${s.type}:${s.id}`}>
            <StudioProvider orientation={orientation} topic={s.palette} lang={lang} numberLocale={numberLocale}>
              <SceneEnter scene={s} first={i === 0}><Art scene={s} data={data} /></SceneEnter>
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
