import React from "react";
import { useCurrentFrame } from "remotion";
import { useStudio } from "./context";

// Quiet depth: a slowly drifting radial glow, a fine grid and a vignette. Never flashes, never loops visibly.
export const Backdrop: React.FC<{ grid?: boolean }> = ({ grid = true }) => {
  const { L, pal } = useStudio();
  const f = useCurrentFrame();
  const gx = 30 + Math.sin(f / 140) * 12, gy = 35 + Math.cos(f / 170) * 10;
  return (
    <div style={{ position: "absolute", inset: 0, width: L.w, height: L.h, background: pal.bg, overflow: "hidden" }}>
      <div style={{ position: "absolute", inset: 0, background: `radial-gradient(ellipse 75% 65% at ${gx}% ${gy}%, ${pal.bg2} 0%, ${pal.bg} 70%)` }} />
      {grid && (
        <svg width={L.w} height={L.h} style={{ position: "absolute", inset: 0, opacity: 0.55 }}>
          {Array.from({ length: Math.ceil(L.w / 120) }, (_, i) => <line key={`v${i}`} x1={i * 120 + 60} x2={i * 120 + 60} y1={0} y2={L.h} stroke={pal.grid} strokeWidth={1} opacity={0.35} />)}
          {Array.from({ length: Math.ceil(L.h / 120) }, (_, i) => <line key={`h${i}`} y1={i * 120 + 60} y2={i * 120 + 60} x1={0} x2={L.w} stroke={pal.grid} strokeWidth={1} opacity={0.35} />)}
        </svg>
      )}
      <div style={{ position: "absolute", inset: 0, background: "radial-gradient(ellipse 85% 85% at 50% 50%, transparent 55%, rgba(0,0,0,0.45) 100%)" }} />
    </div>
  );
};
