import React from "react";
import { Composition } from "remotion";
import { FPS, SAFE } from "./brand";
import { Video } from "./Video";
import { Props } from "./types";

const empty: Props = {
  lang: "en", orientation: "vertical", format: 1, template: "", hookStyle: "", disclaimer: "", scenes: [],
  timeline: { total_s: 2, scenes: [] }, cues: [], audio: "", numberLocale: "en-US", rtl: false,
};

export const Root: React.FC = () => (
  <Composition
    id="Main"
    component={Video as unknown as React.FC<Record<string, unknown>>}
    durationInFrames={FPS * 2}
    fps={FPS}
    width={SAFE.vertical.w}
    height={SAFE.vertical.h}
    defaultProps={empty as unknown as Record<string, unknown>}
    calculateMetadata={({ props }) => {
      const p = props as unknown as Props;
      return { durationInFrames: Math.max(1, Math.ceil(p.timeline.total_s * FPS)), width: SAFE[p.orientation].w, height: SAFE[p.orientation].h, fps: FPS };
    }}
  />
);
