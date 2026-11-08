import { useCurrentFrame, useVideoConfig, interpolate, spring } from "remotion";
import { TlScene } from "./types";

// Scene-relative clock. Beats come from the Python timeline (single source of truth for QA A4).
export const useScene = (sc: TlScene) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const t = frame / fps;
  const beats = sc.beats.map((b) => b - sc.start);
  let index = 0;
  for (let i = 0; i < beats.length; i++) if (t >= beats[i]) index = i;
  const since = t - (beats[index] ?? 0);
  const dur = sc.end - sc.start;
  return { frame, fps, t, dur, beats, beatIndex: index, beatCount: beats.length, sinceBeat: since };
};

export const useEnter = (style: string, delay = 0) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const p = spring({ frame: frame - delay, fps, config: { damping: 200 }, durationInFrames: 18 });
  switch (style) {
    case "slide": return { opacity: p, transform: `translateX(${(1 - p) * 60}px)` };
    case "fade": return { opacity: p };
    case "flip": return { opacity: p, transform: `perspective(900px) rotateX(${(1 - p) * 40}deg)` };
    case "wipe": return { opacity: p, clipPath: `inset(0 ${(1 - p) * 100}% 0 0)` };
    default: return { opacity: p, transform: `translateY(${(1 - p) * 40}px)` };
  }
};

export const ease = (frame: number, from: number, to: number, a = 0, b = 1) =>
  interpolate(frame, [from, to], [a, b], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
