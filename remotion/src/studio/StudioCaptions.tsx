import React from "react";
import { useCurrentFrame, useVideoConfig } from "remotion";
import { C, fontFor } from "../brand";
import { safeBoxFor, studioLayout, type Orientation, type Platform } from "./layout";
import { isNumberWord, mergeNotation, presetFor, type StyleId } from "./styles";

export type CaptionWord = { w: string; start: number; end: number };
export type CaptionCue = { start: number; end: number; lines: CaptionWord[][] };

// Burned-in captions with word-level highlight. Sits inside the safe box, one stamp row above its bottom edge so the
// source stamp / footage tag stay readable. The active word is highlighted, spoken words stay bright, upcoming words dim.
export const StudioCaptions: React.FC<{ cues: CaptionCue[]; orientation: Orientation; lang: string; rtl?: boolean; platform?: Platform; style?: StyleId }> = ({ cues, orientation, lang, rtl, platform, style }) => {
  const f = useCurrentFrame();
  const { fps } = useVideoConfig();
  const t = f / fps;
  const L = studioLayout(orientation, 0, platform);
  const cue = cues.find((c) => t >= c.start && t < c.end);
  if (!cue) return null;
  const size = L.vertical ? 44 : 50;
  const tr = presetFor(style).captions;   // neutral when no style: captions render exactly as before
  return (
    <div style={{ position: "absolute", left: L.x0, width: L.cw, bottom: safeBoxFor(orientation, platform).bottom, display: "flex", justifyContent: "center", pointerEvents: "none" }}>
      <div data-audit="caption" style={{ background: "rgba(10,18,32,0.82)", color: C.text, fontFamily: fontFor(lang), fontWeight: 700, fontSize: size, lineHeight: 1.28,
        textAlign: "center", padding: "12px 26px", borderRadius: 18, direction: rtl ? "rtl" : "ltr", maxWidth: L.cw }}>
        {cue.lines.map((rawLine, i) => {
          const line = tr.mergeNotation ? mergeNotation(rawLine) : rawLine;
          return (
          <div key={i} style={{ whiteSpace: "nowrap" }}>
            {line.map((w, j) => {
              const active = t >= w.start && t < w.end + 0.04;
              const spoken = t >= w.end;
              return (
                <span key={j} style={{ color: active ? C.primary : tr.emphasiseNumbers && isNumberWord(w.w) ? C.secondary : C.text, opacity: active || spoken ? 1 : 0.62, textShadow: active ? `0 0 18px ${C.primary}66` : "none" }}>
                  {w.w}{j < line.length - 1 ? " " : ""}
                </span>
              );
            })}
          </div>
          );
        })}
      </div>
    </div>
  );
};
