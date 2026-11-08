import React from "react";
import { Composition } from "remotion";
import { FPS, SAFE } from "./brand";
import { Video } from "./Video";
import { Props } from "./types";
import { Story } from "./Story";
import { STORY_SAFE, StoryProps, clampDuration } from "./storyConfig";

const empty: Props = {
  lang: "en", orientation: "vertical", format: 1, template: "", hookStyle: "", disclaimer: "", scenes: [],
  timeline: { total_s: 2, scenes: [] }, cues: [], audio: "", numberLocale: "en-US", rtl: false,
};

const emptyStory: StoryProps = { lang: "en", text: "", sub: "", source: "", edu: "", cta: "", aiVoice: "", durationS: 12, audio: "", rtl: false, accent: "#4FD1C5" };

export const Root: React.FC = () => (
  <>
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
  <Composition
    id="Story"
    component={Story as unknown as React.FC<Record<string, unknown>>}
    durationInFrames={FPS * 12}
    fps={FPS}
    width={STORY_SAFE.w}
    height={STORY_SAFE.h}
    defaultProps={emptyStory as unknown as Record<string, unknown>}
    calculateMetadata={({ props }) => ({ durationInFrames: Math.round(clampDuration((props as unknown as StoryProps).durationS) * FPS), width: STORY_SAFE.w, height: STORY_SAFE.h, fps: FPS })}
  />
  </>
);
