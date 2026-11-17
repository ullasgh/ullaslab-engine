import React from "react";
import { noise2D } from "@remotion/noise";
import { PT } from "./tokens";
import { loop } from "./motion";
import { layerPose, type Pose } from "./camera";

// Four deterministic backdrops, each built from three parallax layers (far, mid, near) that follow the camera at different depths.
// Pure SVG and CSS gradients: no blur filters, no per-frame canvas work, so they stay cheap on a CPU-only runner. Everything is a
// function of the frame number (noise2D is seeded), never of time or randomness.
export const BACKDROPS = ["grid", "sweep", "horizon", "quiet"] as const;
export type BackdropId = (typeof BACKDROPS)[number];

/** Backdrop for a scene role and type; never the same as the previous scene's, so a cut always changes the light. */
export const backdropFor = (role: string | undefined, type: string, prev?: BackdropId): BackdropId => {
  const want: BackdropId = role === "hook" || role === "payoff" || role === "interrupt" ? "sweep"
    : type === "chart" ? "horizon"
    : role === "consequence" || role === "cta" || role === "disclaimer" ? "quiet"
    : "grid";
  if (want !== prev) return want;
  return BACKDROPS[(BACKDROPS.indexOf(want) + 1) % BACKDROPS.length];
};

type Props = { id: BackdropId; w: number; h: number; f: number; pose: Pose; seed: number };

const Base: React.FC<{ w: number; h: number; tint?: string }> = ({ w, h, tint }) => (
  <div style={{ position: "absolute", left: 0, top: 0, width: w, height: h,
    background: `radial-gradient(ellipse 90% 70% at 50% 28%, ${PT.navy1} 0%, ${PT.navy0} 78%)${tint ? `, ${tint}` : ""}` }} />
);

const layer = (p: Pose, depth: number): React.CSSProperties => {
  const q = layerPose(p, depth);
  return { position: "absolute", inset: 0, transform: `translate(${q.x}px, ${q.y}px) scale(${q.scale})`, transformOrigin: "50% 45%" };
};

export const PremiumBackdrop: React.FC<Props> = ({ id, w, h, f, pose, seed }) => {
  const drift = (k: number) => noise2D(`bd-${seed}-${k}`, f / 160, k) * 18;
  return (
    <div style={{ position: "absolute", left: 0, top: 0, width: w, height: h, overflow: "hidden", background: PT.navy0 }}>
      <Base w={w} h={h} />
      {id === "grid" && (<>
        <svg width={w} height={h} style={{ ...layer(pose, 0.15), opacity: 0.5 }}>
          {Array.from({ length: Math.ceil(w / 60) + 2 }, (_, i) => <line key={`a${i}`} x1={i * 60 - 30 + drift(1)} x2={i * 60 - 30 + drift(1)} y1={-40} y2={h + 40} stroke={PT.grid} strokeWidth={1} opacity={0.35} />)}
          {Array.from({ length: Math.ceil(h / 60) + 2 }, (_, i) => <line key={`b${i}`} y1={i * 60 - 30} y2={i * 60 - 30} x1={-40} x2={w + 40} stroke={PT.grid} strokeWidth={1} opacity={0.35} />)}
        </svg>
        <svg width={w} height={h} style={{ ...layer(pose, 0.45), opacity: 0.7 }}>
          {Array.from({ length: Math.ceil(w / 240) + 2 }, (_, i) => <line key={`c${i}`} x1={i * 240 + drift(2)} x2={i * 240 + drift(2)} y1={-40} y2={h + 40} stroke={PT.panelLine} strokeWidth={2} opacity={0.5} />)}
          {Array.from({ length: Math.ceil(h / 240) + 2 }, (_, i) => <line key={`d${i}`} y1={i * 240 + drift(3)} y2={i * 240 + drift(3)} x1={-40} x2={w + 40} stroke={PT.panelLine} strokeWidth={2} opacity={0.5} />)}
        </svg>
        <svg width={w} height={h} style={{ ...layer(pose, 1), opacity: 0.55 }}>
          {Array.from({ length: 14 }, (_, i) => {
            const x = ((i * 397 + seed * 53) % 1000) / 1000 * w, y = ((i * 613 + seed * 31) % 1000) / 1000 * h;
            return <rect key={i} x={x + drift(4 + i) * 0.6} y={y} width={6} height={6 + (i % 3) * 8} rx={2} fill={i % 4 === 0 ? PT.amber : PT.teal} opacity={0.35} />;
          })}
        </svg>
      </>)}
      {id === "sweep" && (<>
        <svg width={w} height={h} style={{ ...layer(pose, 0.2), opacity: 0.45 }}>
          {Array.from({ length: Math.ceil(h / 120) + 2 }, (_, i) => <line key={i} y1={i * 120 - 40} y2={i * 120 - 40} x1={0} x2={w} stroke={PT.grid} strokeWidth={1} opacity={0.4} />)}
        </svg>
        <div style={{ ...layer(pose, 0.6), background: `linear-gradient(100deg, transparent ${(loop(f, 260, seed * 40) * 150) - 55}%, #ffffff10 ${(loop(f, 260, seed * 40) * 150) - 40}%, ${PT.teal}14 ${(loop(f, 260, seed * 40) * 150) - 28}%, transparent ${(loop(f, 260, seed * 40) * 150) - 15}%)` }} />
        <div style={{ ...layer(pose, 1), background: `radial-gradient(ellipse 60% 40% at ${50 + drift(6)}% 24%, ${PT.teal}1f 0%, transparent 70%)` }} />
      </>)}
      {id === "horizon" && (() => {
        const hy = h * 0.34, vx = w * 0.5;
        const phase = (f / 90) % 1;
        const rows = Array.from({ length: 16 }, (_, i) => {
          const t = ((i + phase) / 16);
          return hy + (h - hy) * Math.pow(t, 2.1);
        });
        return (<>
          <div style={{ ...layer(pose, 0.1), background: `linear-gradient(180deg, transparent ${(hy / h) * 100 - 14}%, ${PT.teal}16 ${(hy / h) * 100}%, transparent ${(hy / h) * 100 + 16}%)` }} />
          <svg width={w} height={h} style={{ ...layer(pose, 0.55), opacity: 0.8 }}>
            {rows.map((y, i) => <line key={`r${i}`} x1={0} x2={w} y1={y} y2={y} stroke={PT.teal} strokeWidth={1.5} opacity={0.05 + 0.2 * ((y - hy) / (h - hy))} />)}
            {Array.from({ length: 21 }, (_, i) => {
              const bx = vx + (i - 10) * (w * 0.2);
              return <line key={`v${i}`} x1={vx} y1={hy} x2={bx} y2={h} stroke={PT.teal} strokeWidth={1.5} opacity={0.14} />;
            })}
          </svg>
          <svg width={w} height={h} style={{ ...layer(pose, 1), opacity: 0.5 }}>
            {Array.from({ length: 10 }, (_, i) => <circle key={i} cx={((i * 331 + seed * 71) % 1000) / 1000 * w + drift(10 + i) * 0.5} cy={((i * 517 + seed * 19) % 1000) / 1000 * hy} r={2.5} fill={PT.ink} opacity={0.22} />)}
          </svg>
        </>);
      })()}
      {id === "quiet" && (<>
        <div style={{ ...layer(pose, 0.2), background: `radial-gradient(ellipse 70% 45% at ${28 + drift(7)}% 30%, ${PT.teal}1a 0%, transparent 70%)` }} />
        <div style={{ ...layer(pose, 0.55), background: `radial-gradient(ellipse 60% 40% at ${72 + drift(8)}% 72%, ${PT.amber}18 0%, transparent 70%)` }} />
        <svg width={w} height={h} style={{ ...layer(pose, 1), opacity: 0.5 }}>
          {Array.from({ length: 24 }, (_, i) => <circle key={i} cx={((i * 251 + seed * 47) % 1000) / 1000 * w} cy={((i * 439 + seed * 23) % 1000) / 1000 * h + drift(20 + i) * 0.4} r={2} fill={PT.muted} opacity={0.22} />)}
        </svg>
      </>)}
      <div style={{ position: "absolute", inset: 0, background: "radial-gradient(ellipse 88% 88% at 50% 50%, transparent 52%, rgba(0,0,0,0.5) 100%)" }} />
    </div>
  );
};
