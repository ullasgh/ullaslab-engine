import React from "react";
import { SceneRenderer, type SceneRendererProps } from "./SceneRenderer";
import { DEMO_REFS, DEMO_SCENES } from "./fixtures";
import { SIZES, type Orientation } from "./layout";
import { totalFrames, type StudioScene } from "./scenes";

export const StudioDemo: React.FC<{ orientation: Orientation }> = ({ orientation }) => (
  <SceneRenderer orientation={orientation} scenes={DEMO_SCENES} refs={DEMO_REFS} />
);

export type StudioScenesProps = SceneRendererProps;
export const studioMetadata = (p: { orientation: Orientation; scenes: StudioScene[] }) => ({
  durationInFrames: Math.max(1, totalFrames(p.scenes)), width: SIZES[p.orientation].w, height: SIZES[p.orientation].h, fps: 30,
});
export const demoProps = (orientation: Orientation): StudioScenesProps => ({ orientation, scenes: DEMO_SCENES, refs: DEMO_REFS });
