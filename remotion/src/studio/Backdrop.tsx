import React from "react";
import { useCurrentFrame } from "remotion";
import { useStudio } from "./context";
import { sketchLine } from "./styles";

// Quiet depth: a slowly drifting radial glow, a fine grid and a vignette. Never flashes, never loops visibly.
// A video style swaps the texture (guides, glow, board, clean); all colours stay on the brand palette.
export const Backdrop: React.FC<{ grid?: boolean }> = ({ grid = true }) => {
  const { L, pal, preset } = useStudio();
  const f = useCurrentFrame();
  const kind = grid ? preset.layout.backdrop : "grid";
  const gx = 30 + Math.sin(f / 140) * 12, gy = 35 + Math.cos(f / 170) * 10;
  const glow = kind === "glow" ? `radial-gradient(ellipse 80% 55% at ${gx + 20}% ${gy + 15}%, ${pal.accent}26 0%, ${pal.bg2} 45%, ${pal.bg} 85%)`
    : kind === "clean" ? `linear-gradient(160deg, ${pal.bg2} 0%, ${pal.bg} 100%)`
    : `radial-gradient(ellipse 75% 65% at ${gx}% ${gy}%, ${pal.bg2} 0%, ${pal.bg} 70%)`;
  const rows = Math.ceil(L.h / 120);
  return (
    <div style={{ position: "absolute", inset: 0, width: L.w, height: L.h, background: pal.bg, overflow: "hidden" }}>
      <div style={{ position: "absolute", inset: 0, background: glow }} />
      {grid && kind === "grid" && (
        <svg width={L.w} height={L.h} style={{ position: "absolute", inset: 0, opacity: 0.55 }}>
          {Array.from({ length: Math.ceil(L.w / 120) }, (_, i) => <line key={`v${i}`} x1={i * 120 + 60} x2={i * 120 + 60} y1={0} y2={L.h} stroke={pal.grid} strokeWidth={1} opacity={0.35} />)}
          {Array.from({ length: rows }, (_, i) => <line key={`h${i}`} y1={i * 120 + 60} y2={i * 120 + 60} x1={0} x2={L.w} stroke={pal.grid} strokeWidth={1} opacity={0.35} />)}
        </svg>
      )}
      {kind === "guides" && (
        <svg width={L.w} height={L.h} style={{ position: "absolute", inset: 0, opacity: 0.5 }}>
          {Array.from({ length: rows }, (_, i) => <line key={`h${i}`} y1={i * 120 + 60} y2={i * 120 + 60} x1={0} x2={L.w} stroke={pal.grid} strokeWidth={1} opacity={0.4} />)}
        </svg>
      )}
      {kind === "board" && (
        <svg width={L.w} height={L.h} style={{ position: "absolute", inset: 0, opacity: 0.5 }}>
          {Array.from({ length: Math.ceil(L.h / 160) }, (_, i) => (
            <path key={i} d={sketchLine(L.w, i + 1, 2.5)} transform={`translate(0 ${i * 160 + 100})`} stroke={pal.grid} strokeWidth={2} fill="none" strokeLinecap="round" opacity={0.55} />
          ))}
        </svg>
      )}
      {kind === "clean" && (
        <svg width={L.w} height={L.h} style={{ position: "absolute", inset: 0, opacity: 0.5 }}>
          {Array.from({ length: Math.ceil(L.w / 80) }, (_, i) => Array.from({ length: Math.ceil(L.h / 80) }, (_, j) => (
            <circle key={`${i}-${j}`} cx={i * 80 + 40} cy={j * 80 + 40} r={2} fill={pal.grid} opacity={0.6} />
          )))}
        </svg>
      )}
      <div style={{ position: "absolute", inset: 0, background: "radial-gradient(ellipse 85% 85% at 50% 50%, transparent 55%, rgba(0,0,0,0.45) 100%)" }} />
    </div>
  );
};
