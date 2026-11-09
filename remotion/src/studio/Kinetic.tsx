import React from "react";
import { useCurrentFrame, useVideoConfig } from "remotion";
import { useFont, useRamp, useStudio } from "./context";

const clamp01 = (x: number) => Math.min(1, Math.max(0, x));
const ease = (x: number) => 1 - Math.pow(1 - clamp01(x), 3);

// Text format: lines separated by "|", *word* marks an emphasised word (accent colour + underline sweep).
export const parseKinetic = (text: string): { words: { w: string; em: boolean }[] }[] =>
  text.split("|").map((line) => ({
    words: line.trim().split(/\s+/).filter(Boolean).map((raw) => {
      const em = /^\*.+\*[.,;:!?]?$/.test(raw);
      return { w: em ? raw.replace(/\*/g, "") : raw, em };
    }),
  })).filter((l) => l.words.length);

export const KineticText: React.FC<{ text: string }> = ({ text }) => {
  const { L, pal } = useStudio();
  const font = useFont();
  const f = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();
  const lines = parseKinetic(text);
  const size = L.type.display * (lines.reduce((m, l) => Math.max(m, l.words.length), 0) > 4 ? 0.8 : 1);
  const per = Math.max(14, Math.min(26, Math.floor((durationInFrames - 30) / Math.max(1, lines.length))));
  const drift = f * 0.15;
  let wi = 0;
  return (
    <div style={{ position: "absolute", left: L.x0, top: L.y0, width: L.cw, height: L.ch, fontFamily: font, display: "flex", flexDirection: "column", justifyContent: "center", gap: size * 0.1 }}>
      <svg width={L.cw * 0.9} height={L.vertical ? 420 : 520} style={{ position: "absolute", right: -L.cw * 0.12, top: L.vertical ? 0 : L.ch * 0.05, opacity: 0.55, overflow: "visible" }}>
        <circle cx={L.cw * 0.5 - drift} cy={L.vertical ? 110 : 200} r={L.vertical ? 220 : 280} fill="none" stroke={pal.accent} strokeWidth={2} opacity={0.5} />
        <circle cx={L.cw * 0.5 - drift} cy={L.vertical ? 110 : 200} r={L.vertical ? 150 : 190} fill="none" stroke={pal.grid} strokeWidth={2} />
      </svg>
      <div style={{ width: ease(f / 22) * 120, height: 8, background: pal.accent, borderRadius: 4, marginBottom: size * 0.2 }} />
      {lines.map((line, li) => (
        <div key={li} data-audit="headline" style={{ display: "flex", flexWrap: "wrap", gap: `0 ${size * 0.26}px`, fontSize: size, fontWeight: 700, lineHeight: 1.08, letterSpacing: -1.5, color: pal.ink }}>
          {line.words.map((wd, i) => {
            const idx = wi++;
            const s = 6 + li * per + i * 4;
            const k = ease((f - s) / 16);
            const sweep = ease((f - s - 10) / 18);
            return (
              <span key={i} style={{ position: "relative", display: "inline-block", overflow: "hidden", paddingBottom: size * 0.08, verticalAlign: "top" }}>
                <span style={{ display: "inline-block", opacity: k, transform: `translateY(${(1 - k) * size * 0.55}px)`, color: wd.em ? pal.accent : pal.ink }}>{wd.w}</span>
                {wd.em && <span style={{ position: "absolute", left: 0, bottom: size * 0.02, height: 7, width: `${sweep * 100}%`, background: pal.accent2, borderRadius: 4, opacity: 0.9 }} />}
              </span>
            );
          })}
        </div>
      ))}
    </div>
  );
};

export const LowerThird: React.FC<{ title: string; subtitle?: string; delay?: number; inline?: boolean }> = ({ title, subtitle, delay = 12, inline }) => {
  const { L, pal } = useStudio();
  const font = useFont();
  const f = useCurrentFrame();
  const k = ease((f - delay) / 16);
  const bar = ease((f - delay) / 10);
  return (
    <div style={{ ...(inline ? {} : { position: "absolute", left: L.x0, bottom: L.h - L.y1 + 70 }), maxWidth: L.cw, fontFamily: font, display: "flex", gap: 22, alignItems: "stretch" }}>
      <div style={{ width: 8, background: pal.accent, borderRadius: 4, transform: `scaleY(${bar})`, transformOrigin: "bottom" }} />
      <div style={{ opacity: k, transform: `translateX(${(1 - k) * -40}px)`, textShadow: "0 2px 16px rgba(0,0,0,0.6)" }}>
        <div data-audit="headline" style={{ fontSize: L.type.body, fontWeight: 700, color: pal.ink, lineHeight: 1.1 }}>{title}</div>
        {subtitle && <div data-audit="body" style={{ fontSize: L.type.label, color: pal.muted, lineHeight: 1.2 }}>{subtitle}</div>}
      </div>
    </div>
  );
};
