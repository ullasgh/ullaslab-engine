import React from "react";
import { AbsoluteFill, Sequence, interpolate, useCurrentFrame } from "remotion";
import { endParts } from "../brand";
import { StudioProvider, useFont, useStudio } from "./context";
import type { Orientation, Platform } from "./layout";

export type EndCardProps = { fromFrame: number; durationInFrames: number };

const Card: React.FC<{ rtl?: boolean }> = ({ rtl }) => {
  const { L, pal, lang } = useStudio();
  const font = useFont();
  const f = useCurrentFrame();
  const k = interpolate(f, [0, 12], [0, 1], { extrapolateRight: "clamp" });
  const [follow, edu] = endParts(lang);
  return (
    <AbsoluteFill style={{ opacity: k }}>
      <AbsoluteFill style={{ background: pal.bg, opacity: 0.92 }} />
      <div data-audit="endcard" style={{ position: "absolute", left: L.x0, top: L.y0, width: L.cw, height: L.ch, display: "flex", flexDirection: "column",
        alignItems: "center", justifyContent: "center", textAlign: "center", gap: 20, fontFamily: font, color: pal.ink, direction: rtl ? "rtl" : "ltr" }}>
        <div data-audit="headline" style={{ fontSize: L.type.headline, fontWeight: 700, lineHeight: 1.15 }}>{follow}</div>
        <div data-audit="body" style={{ fontSize: L.type.body, color: pal.muted, lineHeight: 1.25 }}>{edu}</div>
      </div>
    </AbsoluteFill>
  );
};

// End card over the last seconds of every video: "Follow UllasLab" + "Education only" (owner decision 2026-11-09), inside the safe box
// above the caption band. The full disclaimer is in the description / caption, not in the video.
export const EndCard: React.FC<{ orientation: Orientation; lang: string; rtl?: boolean; card: EndCardProps; reserveBottom: number; platform?: Platform }> = ({ orientation, lang, rtl, card, reserveBottom, platform }) => (
  <Sequence from={card.fromFrame} durationInFrames={Math.max(1, card.durationInFrames)} name="end-card">
    <StudioProvider orientation={orientation} lang={lang} reserveBottom={reserveBottom} platform={platform}><Card rtl={rtl} /></StudioProvider>
  </Sequence>
);
