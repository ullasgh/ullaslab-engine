import React, { useState } from "react";
import { Audio, continueRender, delayRender, interpolate, spring, staticFile, useCurrentFrame, useVideoConfig } from "remotion";
import { C, FPS, fontFor } from "./brand";
import { Audit } from "./components/audit";
import { STORY_SAFE as S, StoryProps } from "./storyConfig";

const useFonts = (p: StoryProps) => {
  const [handle] = useState(() => delayRender("story fonts", { timeoutInMilliseconds: 60000 }));
  React.useEffect(() => {
    const link = document.createElement("link");
    link.rel = "stylesheet";
    link.href = staticFile("fonts/fonts.css");
    link.onload = () => {
      const fam = fontFor(p.lang).split(",")[0].replace(/"/g, "").trim();
      const sample = p.text + p.sub + p.cta + p.edu + p.aiVoice + p.source + "UllasLab";
      Promise.all([400, 700].flatMap((w) => [...new Set([fam, "Noto Sans"])].map((f) => document.fonts.load(`${w} 40px "${f}"`, sample))))
        .catch(() => undefined).finally(() => continueRender(handle));
    };
    link.onerror = () => continueRender(handle);
    document.head.appendChild(link);
  }, []);
};

export const Story: React.FC<StoryProps> = (p) => {
  useFonts(p);
  const frame = useCurrentFrame();
  const { fps, durationInFrames } = useVideoConfig();
  const t = frame / fps;
  const words = p.text.split(/\s+/).filter(Boolean);
  const dir = p.rtl ? "rtl" : "ltr";
  const fadeOut = interpolate(frame, [durationInFrames - 12, durationInFrames - 1], [1, 0.0], { extrapolateLeft: "clamp" });
  const subIn = spring({ frame: frame - Math.round(1.4 * fps), fps, config: { damping: 200 }, durationInFrames: 20 });
  const ctaIn = spring({ frame: frame - Math.round(3 * fps), fps, config: { damping: 200 }, durationInFrames: 20 });
  const pulse = 0.5 + 0.5 * Math.sin(t * 2.2);
  // Calm decorative bars (no data, no claims): purely brand ambience.
  const bars = Array.from({ length: 24 }, (_, i) => 0.25 + 0.55 * (0.5 + 0.5 * Math.sin(t * 1.3 + i * 0.55)) * (0.4 + 0.6 * (i / 23)));
  return (
    <div data-audit="bg" style={{ position: "absolute", inset: 0, width: S.w, height: S.h, overflow: "hidden", background: C.bg, fontFamily: fontFor(p.lang), color: C.text }}>
      <div style={{ position: "absolute", left: 0, top: 0, width: S.w, height: 10, background: p.accent }} />
      <div style={{ position: "absolute", left: S.sides, right: S.sides, top: 880, height: 360, display: "flex", alignItems: "flex-end", gap: 10, opacity: 0.22 }}>
        {bars.map((b, i) => <div key={i} style={{ flex: 1, height: `${b * 100}%`, background: i % 5 === 0 ? C.secondary : p.accent, borderRadius: 6 }} />)}
      </div>
      <div style={{ position: "absolute", inset: 0, opacity: fadeOut }}>
        <div data-audit="stamp" style={{ position: "absolute", left: S.sides, top: S.top, height: 60, display: "flex", alignItems: "center", gap: 14, fontSize: 36, fontWeight: 700, color: C.muted, letterSpacing: 1 }}>
          <span style={{ width: 14, height: 14, borderRadius: 7, background: p.accent, display: "inline-block", opacity: 0.6 + 0.4 * pulse }} />
          UllasLab
        </div>
        <div style={{ position: "absolute", left: S.sides, width: S.w - 2 * S.sides, top: 400, direction: dir, display: "flex", flexWrap: "wrap", gap: "0 22px", fontSize: 92, fontWeight: 700, lineHeight: 1.15 }}>
          {words.map((w, i) => {
            const k = spring({ frame: frame - 6 - i * 5, fps, config: { damping: 200 }, durationInFrames: 16 });
            return <span key={i} data-audit="headline" style={{ opacity: k, transform: `translateY(${(1 - k) * 36}px)`, display: "inline-block" }}>{w}</span>;
          })}
        </div>
        {p.sub ? (
          <div data-audit="body" style={{ position: "absolute", left: S.sides, width: S.w - 2 * S.sides, top: 900, direction: dir, fontSize: 52, lineHeight: 1.3, color: C.muted, opacity: subIn, transform: `translateY(${(1 - subIn) * 24}px)` }}>{p.sub}</div>
        ) : null}
        <div style={{ position: "absolute", left: S.sides, width: S.w - 2 * S.sides, bottom: S.bottom, display: "flex", flexDirection: "column", justifyContent: "flex-end", gap: 16, direction: dir }}>
          <div data-audit="body" style={{ alignSelf: "flex-start", background: p.accent, color: C.tagText, fontWeight: 700, fontSize: 48, padding: "10px 28px", borderRadius: 999, opacity: ctaIn, transform: `scale(${0.92 + 0.08 * ctaIn})` }}>{p.cta}</div>
          <div data-audit="label" style={{ fontSize: 38, color: C.muted }}>{p.edu}{p.aiVoice ? ` · ${p.aiVoice}` : ""}</div>
          {p.source ? <div data-audit="stamp" style={{ fontSize: 36, color: C.muted }}>{p.source}</div> : null}
        </div>
      </div>
      {p.audio ? <Audio src={staticFile(p.audio)} /> : null}
      <Audit enabled={!!p.audit} sceneId="story" />
    </div>
  );
};
void FPS;
