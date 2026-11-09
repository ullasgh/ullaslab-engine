import React from "react";
import { AbsoluteFill } from "remotion";
import { C, fontFor } from "../brand";
import { SceneRenderer, type SceneRendererProps } from "./SceneRenderer";

export type StudioThumbProps = SceneRendererProps & { headline: string; art?: boolean };

// 1280x720 thumbnail: the hook scene's art (rendered at 1920x1080 and scaled) under a scrim, plus the headline.
// Headline text is supplied by the caller from the hook's own on-screen text: no figures or claims are added here.
export const StudioThumb: React.FC<StudioThumbProps> = ({ headline, art = true, ...scene }) => (
  <AbsoluteFill style={{ background: C.bg, overflow: "hidden" }}>
    {art && (
      <div style={{ position: "absolute", left: 0, top: 0, width: 1920, height: 1080, transform: "scale(0.6667)", transformOrigin: "0 0" }}>
        <SceneRenderer {...scene} />
      </div>
    )}
    {/* abstract motif only: a rising line with markers, no axes, labels or figures */}
    <svg width={1280} height={720} style={{ position: "absolute", left: 0, top: 0 }}>
      <polyline points="640,560 730,520 800,540 880,450 960,470 1050,360 1130,300 1210,210" fill="none" stroke={C.primary} strokeWidth={10} strokeLinecap="round" strokeLinejoin="round" opacity={0.75} />
      {[[880, 450], [1050, 360], [1210, 210]].map(([x, y], i) => <circle key={i} cx={x} cy={y} r={14} fill={C.bg} stroke={C.secondary} strokeWidth={6} opacity={0.9} />)}
    </svg>
    <AbsoluteFill style={{ background: "linear-gradient(100deg, rgba(10,18,32,0.92) 0%, rgba(10,18,32,0.72) 48%, rgba(10,18,32,0.05) 100%)" }} />
    <div style={{ position: "absolute", right: -120, top: -80, width: 760, height: 760, borderRadius: "50%", background: `radial-gradient(circle, ${C.primary}44 0%, transparent 68%)` }} />
    
    <div style={{ position: "absolute", left: 64, top: 0, bottom: 0, width: 760, display: "flex", flexDirection: "column", justifyContent: "center", gap: 22,
      fontFamily: fontFor(scene.lang ?? "en") }}>
      <div style={{ width: 96, height: 8, background: C.primary, borderRadius: 4 }} />
      <div style={{ fontSize: 96, fontWeight: 800, lineHeight: 1.05, color: C.text, textShadow: "0 3px 20px rgba(0,0,0,0.6)" }}>{headline}</div>
      <div style={{ fontSize: 34, fontWeight: 700, color: C.primary, letterSpacing: 2 }}>UllasLab Macro</div>
    </div>
  </AbsoluteFill>
);
