import React from "react";
import { AbsoluteFill } from "remotion";
import { SceneRenderer, type SceneRendererProps } from "./SceneRenderer";
import { EndCard, type EndCardProps } from "./EndCard";
import { StudioCaptions, type CaptionCue } from "./StudioCaptions";
import { CAPTION_RESERVE, SIZES, type Orientation } from "./layout";
import { FPS } from "../brand";

export type StudioVideoProps = SceneRendererProps & { captions: CaptionCue[]; rtl?: boolean; durationInFrames: number; endCard?: EndCardProps };

// One output (long / short / reel): the director's scenes plus burned-in captions. Narration is mixed in ffmpeg (stems stay separate).
export const StudioVideo: React.FC<StudioVideoProps> = ({ captions, rtl, durationInFrames: _d, endCard, ...scene }) => (
  <AbsoluteFill>
    <SceneRenderer {...scene} reserveBottom={CAPTION_RESERVE} />
    {endCard && <EndCard orientation={scene.orientation} lang={scene.lang ?? "en"} rtl={rtl} card={endCard} reserveBottom={CAPTION_RESERVE} platform={scene.platform} />}
    <StudioCaptions cues={captions} orientation={scene.orientation} lang={scene.lang ?? "en"} rtl={rtl} platform={scene.platform} style={scene.style} />
  </AbsoluteFill>
);

export const studioVideoMetadata = (p: { orientation: Orientation; durationInFrames: number }) => ({
  durationInFrames: Math.max(1, p.durationInFrames), width: SIZES[p.orientation].w, height: SIZES[p.orientation].h, fps: FPS,
});
