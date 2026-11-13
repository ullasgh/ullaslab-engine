import React from "react";
import { AbsoluteFill } from "remotion";
import { SceneRenderer, type SceneRendererProps } from "./SceneRenderer";
import { EndCard, type EndCardProps } from "./EndCard";
import { StudioCaptions, type CaptionCue } from "./StudioCaptions";
import { CAPTION_RESERVE, SIZES, type Orientation } from "./layout";
import { FPS } from "../brand";
import { Audit } from "../components/audit";
import { collectText, useBrandFonts } from "../fonts";

export type StudioVideoProps = SceneRendererProps & { captions: CaptionCue[]; rtl?: boolean; durationInFrames: number; endCard?: EndCardProps;
  audit?: boolean };

// One output (long / short / reel): the director's scenes plus burned-in captions. Narration is mixed in ffmpeg (stems stay separate).
// `audit` (stills only, WP8 safe-zone gate): logs element geometry and font sizes, never text (components/audit.tsx).
export const StudioVideo: React.FC<StudioVideoProps> = ({ captions, rtl, durationInFrames: _d, endCard, audit, ...scene }) => {
  useBrandFonts(scene.lang ?? "en", collectText({ scene, captions, endCard }));   // local brand fonts, same loader as Video.tsx
  return (
  <AbsoluteFill>
    <SceneRenderer {...scene} reserveBottom={CAPTION_RESERVE} />
    {endCard && <EndCard orientation={scene.orientation} lang={scene.lang ?? "en"} rtl={rtl} card={endCard} reserveBottom={CAPTION_RESERVE} platform={scene.platform} />}
    <StudioCaptions cues={captions} orientation={scene.orientation} lang={scene.lang ?? "en"} rtl={rtl} platform={scene.platform} style={scene.style} />
    {audit && <Audit enabled sceneId="" />}
  </AbsoluteFill>
  );
};

export const studioVideoMetadata = (p: { orientation: Orientation; durationInFrames: number }) => ({
  durationInFrames: Math.max(1, p.durationInFrames), width: SIZES[p.orientation].w, height: SIZES[p.orientation].h, fps: FPS,
});
