import React from "react";
import { AbsoluteFill, Sequence, useCurrentFrame } from "remotion";
import { evolvePath } from "@remotion/paths";
import { endParts } from "../../brand";
import { StudioProvider, useStudio } from "../context";
import type { Orientation, Platform } from "../layout";
import { EASE, SPRING, breathe, loop, range, springOut } from "./motion";
import { PT, PTYPE, SP } from "./tokens";
import { PremiumBackdrop } from "./Backdrops";
import { fontFor } from "../../brand";

/** The brand mark as data, supplied by the item from the private content side (props.brandMark). The public engine repo holds no
 *  logo geometry: with no mark the end card shows the text only. Coordinates are on a square grid of `viewBox` units. */
export type BrandMark = {
  viewBox: number; radius: number; bg: string; ink: string;
  strokes: { d: string; w: number }[];
  rects: { x: number; y: number; w: number; h: number; r?: number }[];
};

export const isBrandMark = (m: unknown): m is BrandMark => {
  const b = m as BrandMark;
  return !!b && typeof b.viewBox === "number" && b.viewBox > 0 && typeof b.radius === "number" && typeof b.bg === "string" && typeof b.ink === "string"
    && Array.isArray(b.strokes) && Array.isArray(b.rects);
};

export const AnimatedMark: React.FC<{ mark: BrandMark; size: number }> = ({ mark, size }) => {
  const f = useCurrentFrame();
  const pop = springOut(range(f, 0, 22), SPRING.pop);
  const live = 1 + breathe(f, 90, 0.012);
  return (
    <svg width={size} height={size} viewBox={`0 0 ${mark.viewBox} ${mark.viewBox}`} style={{ transform: `scale(${(0.55 + 0.45 * pop) * live})`, opacity: EASE.out(range(f, 0, 8)), overflow: "visible" }}>
      <rect width={mark.viewBox} height={mark.viewBox} rx={mark.radius} fill={mark.bg} />
      {mark.rects.map((r, i) => {
        const k = EASE.outQuint(range(f, 12 + i * 5, 16));
        return <rect key={i} x={r.x} y={r.y + r.h * (1 - k)} width={r.w} height={Math.max(0.001, r.h * k)} rx={r.r ?? 0} fill={mark.ink} />;
      })}
      {mark.strokes.map((p, i) => {
        const e = evolvePath(EASE.inOut(range(f, 8 + i * 6, 22)), p.d);
        return <path key={i} d={p.d} fill="none" stroke={mark.ink} strokeWidth={p.w} strokeLinecap="round" strokeDasharray={e.strokeDasharray} strokeDashoffset={e.strokeDashoffset} />;
      })}
      <rect x={-mark.viewBox * 0.4 + mark.viewBox * 1.8 * loop(f, 120, 20)} y={0} width={mark.viewBox * 0.12} height={mark.viewBox} fill="#FFFFFF" opacity={0.16} transform={`skewX(-14)`} style={{ mixBlendMode: "overlay" }} />
    </svg>
  );
};

const Card: React.FC<{ rtl?: boolean; mark?: BrandMark; showEdu?: boolean }> = ({ rtl, mark, showEdu = false }) => {
  const { L, lang } = useStudio();
  const f = useCurrentFrame();
  const T = PTYPE[L.o];
  const [follow, edu] = endParts(lang);
  const font = fontFor(lang);
  const a = EASE.out(range(f, 0, 10));
  const msize = L.vertical ? 260 : 300;
  return (
    <AbsoluteFill style={{ opacity: a }}>
      <PremiumBackdrop id="quiet" w={L.w} h={L.h} f={f} pose={{ scale: 1, x: 0, y: 0 }} seed={9} />
      <div data-audit="endcard" style={{ position: "absolute", left: L.x0, top: L.y0, width: L.cw, height: L.ch, display: "flex", flexDirection: "column", alignItems: "center",
        justifyContent: "center", textAlign: "center", gap: SP.m, fontFamily: font, color: PT.ink, direction: rtl ? "rtl" : "ltr" }}>
        {mark && <AnimatedMark mark={mark} size={msize} />}
        <div style={{ height: SP.xs }} />
        <div data-audit="headline" style={{ fontSize: T.headline * 1.1, fontWeight: 700, lineHeight: 1.15, opacity: EASE.out(range(f, 24, 12)), transform: `translateY(${(1 - EASE.out(range(f, 24, 14))) * 18}px)` }}>{follow}</div>
        {showEdu && <div data-audit="body" style={{ fontSize: T.body, color: PT.muted, lineHeight: 1.25, opacity: EASE.out(range(f, 34, 12)), transform: `translateY(${(1 - EASE.out(range(f, 34, 14))) * 14}px)` }}>{edu}</div>}
        <div style={{ width: 120 + breathe(f, 80, 28), height: 6, background: PT.amber, borderRadius: 3, marginTop: SP.s, opacity: EASE.out(range(f, 40, 10)) }} />
      </div>
    </AbsoluteFill>
  );
};

export const PremiumEndCard: React.FC<{ orientation: Orientation; lang: string; rtl?: boolean; card: { fromFrame: number; durationInFrames: number }; reserveBottom: number; platform?: Platform; mark?: BrandMark; showEdu?: boolean }> = ({ orientation, lang, rtl, card, reserveBottom, platform, mark, showEdu }) => (
  <Sequence from={card.fromFrame} durationInFrames={Math.max(1, card.durationInFrames)} name="end-card">
    <StudioProvider orientation={orientation} lang={lang} reserveBottom={reserveBottom} platform={platform} style="premium"><Card rtl={rtl} mark={mark} showEdu={showEdu} /></StudioProvider>
  </Sequence>
);
