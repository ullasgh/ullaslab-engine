import React from "react";
import { AbsoluteFill } from "remotion";
import { Audit } from "../components/audit";
import { collectText, useBrandFonts } from "../fonts";
import { SceneRenderer } from "./SceneRenderer";
import { StudioCaptions } from "./StudioCaptions";
import { STYLE_DEMO_CUE, STYLE_DEMO_REFS, STYLE_DEMO_SCENES } from "./fixtures";
import { CAPTION_RESERVE, SIZES, type Orientation } from "./layout";
import type { StyleId } from "./styles";

export type StyleDemoProps = { orientation: Orientation; style: StyleId; audit?: boolean };

// One sample output per style: three scenes plus a burned-in caption, for stills and the layout audit. Fixture numbers only.
export const StyleDemo: React.FC<StyleDemoProps> = ({ orientation, style, audit }) => {
  useBrandFonts("en", collectText([STYLE_DEMO_SCENES[style], STYLE_DEMO_CUE]));
  return (
  <AbsoluteFill>
    <SceneRenderer orientation={orientation} scenes={STYLE_DEMO_SCENES[style]} refs={STYLE_DEMO_REFS} style={style} reserveBottom={CAPTION_RESERVE} />
    <StudioCaptions cues={[STYLE_DEMO_CUE]} orientation={orientation} lang="en" style={style} />
    <Audit enabled={!!audit} sceneId="" />
  </AbsoluteFill>
  );
};

export const styleDemoMetadata = (p: { orientation: Orientation }) => ({ durationInFrames: 270, width: SIZES[p.orientation].w, height: SIZES[p.orientation].h, fps: 30 });
