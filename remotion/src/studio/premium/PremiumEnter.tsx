import React from "react";
import { AbsoluteFill, useCurrentFrame } from "remotion";
import { noise2D } from "@remotion/noise";
import { transitionProgress, type TransitionKind } from "../scenes";
import { EASE, range } from "./motion";
import { PT } from "./tokens";

// Entering transition of a premium scene. The incoming scene sits above the outgoing one (which may animate its own exit, see
// PremiumScene Exit). Every look is a pure function of the local frame, mirrored in frame count by studio/scenecache.py.
//   crossfade / match_move: as the classic set.
//   push_through: the incoming scene comes forward out of depth while the outgoing one is pushed past the camera.
//   morph: a shared figure travels between the scenes (the ghost is drawn by the caller); the rest fades.
//   sweep: a light sweep wipe, a skewed edge carrying a soft glow.
//   interrupt: a real pattern interrupt: a hard cut with an amber-white flash, a punch-in and a short shake.
export const PremiumEnter: React.FC<{ kind: TransitionKind; first: boolean; children: React.ReactNode }> = ({ kind, first, children }) => {
  const f = useCurrentFrame();
  const k = first ? "cut" : kind;
  const p = transitionProgress(k, f);
  if (k === "cut" || p >= 1) return <AbsoluteFill>{children}</AbsoluteFill>;
  if (k === "crossfade") return <AbsoluteFill style={{ opacity: p }}>{children}</AbsoluteFill>;
  if (k === "wipe") return <AbsoluteFill style={{ clipPath: `inset(0 ${(1 - p) * 100}% 0 0)` }}>{children}</AbsoluteFill>;
  if (k === "match_move") return <AbsoluteFill style={{ opacity: p, transform: `scale(${1 + 0.09 * (1 - p)})` }}>{children}</AbsoluteFill>;
  if (k === "push_through") {
    const e = EASE.outQuint(range(f, 0, 20));
    return <AbsoluteFill style={{ opacity: EASE.smooth(range(f, 0, 12)), transform: `scale(${0.8 + 0.2 * e})`, transformOrigin: "50% 45%" }}>{children}</AbsoluteFill>;
  }
  if (k === "morph") return <AbsoluteFill style={{ opacity: EASE.smooth(range(f, 0, 14)), transform: `translateY(${(1 - EASE.out(range(f, 0, 18))) * 22}px)` }}>{children}</AbsoluteFill>;
  if (k === "sweep") {
    const x = -20 + 150 * EASE.inOut(range(f, 0, 16));     // leading edge, % of width, at the top
    const skew = 22;
    return (
      <AbsoluteFill>
        <AbsoluteFill style={{ clipPath: `polygon(0 0, ${x}% 0, ${x - skew}% 100%, 0 100%)` }}>{children}</AbsoluteFill>
        <div style={{ position: "absolute", top: 0, bottom: 0, left: `${x - skew / 2}%`, width: 260, marginLeft: -130, transform: `skewX(-${Math.round((Math.atan((skew / 100) * 0.56) * 180) / Math.PI)}deg)`,
          background: `linear-gradient(90deg, transparent 0%, ${PT.amber}55 38%, rgba(255,255,255,0.85) 50%, ${PT.teal}44 62%, transparent 100%)`, opacity: 0.9 }} />
      </AbsoluteFill>
    );
  }
  // interrupt
  const q = range(f, 0, 8);
  const shake = (1 - q) * 14;
  return (
    <AbsoluteFill>
      <AbsoluteFill style={{ transform: `translate(${noise2D("shx", f, 1) * shake}px, ${noise2D("shy", f, 2) * shake}px) scale(${1 + 0.07 * (1 - EASE.out(q))})`, transformOrigin: "50% 45%" }}>{children}</AbsoluteFill>
      <AbsoluteFill style={{ background: `linear-gradient(180deg, ${PT.amber}, #FFFFFF)`, opacity: 0.4 * (1 - EASE.out(range(f, 0, 6))) }} />
    </AbsoluteFill>
  );
};
