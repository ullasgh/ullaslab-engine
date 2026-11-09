import React from "react";
import { AbsoluteFill, OffthreadVideo, staticFile, useCurrentFrame } from "remotion";
import { illustrativeTag } from "../brand";
import { useCameraStyle, useFont, useStudio } from "./context";
import { SceneHeadline } from "./Stamp";
import { LowerThird } from "./Kinetic";
import type { CameraMove } from "./scenes";

export type FootageData = {
  src?: string;               // file under public/ (or an https URL). Missing => procedural placeholder plate
  credit?: string;            // creator / provider line, from the asset ledger
  illustrative?: boolean;     // default true: footage is mood, not evidence
  grade?: { contrast?: number; saturate?: number; brightness?: number; tint?: number };
  startFrom?: number;         // frames into the clip
  lower_third?: { title: string; subtitle?: string };
};

const srcUrl = (s: string) => (/^https?:\/\//.test(s) ? s : staticFile(s));

export const FootageScene: React.FC<{ data: FootageData; headline?: string; camera?: CameraMove }> = ({ data, headline, camera }) => {
  const { L, pal, lang } = useStudio();
  const font = useFont();
  const f = useCurrentFrame();
  const cam = useCameraStyle(camera ?? "push");
  const g = { contrast: 1.08, saturate: 0.82, brightness: 0.8, tint: 0.28, ...data.grade };
  const illustrative = data.illustrative !== false;
  return (
    <AbsoluteFill style={{ background: pal.bg, fontFamily: font, overflow: "hidden" }}>
      <div style={{ position: "absolute", inset: 0, ...cam }}>
        {data.src ? (
          <OffthreadVideo src={srcUrl(data.src)} startFrom={data.startFrom ?? 0} muted
            style={{ width: "100%", height: "100%", objectFit: "cover", filter: `contrast(${g.contrast}) saturate(${g.saturate}) brightness(${g.brightness})` }} />
        ) : (
          // placeholder plate used by fixtures: slow drifting colour field, no external asset
          <div style={{ position: "absolute", inset: 0, background:
            `radial-gradient(ellipse 60% 50% at ${35 + Math.sin(f / 90) * 12}% ${40 + Math.cos(f / 110) * 10}%, ${pal.accent}55 0%, transparent 70%),` +
            `radial-gradient(ellipse 50% 60% at ${70 + Math.cos(f / 100) * 10}% ${65 + Math.sin(f / 80) * 8}%, ${pal.accent2}44 0%, transparent 70%), ${pal.bg2}` }} />
        )}
      </div>
      {/* colour grade: palette tint + scrims for text legibility */}
      <div style={{ position: "absolute", inset: 0, background: pal.bg2, mixBlendMode: "color", opacity: g.tint }} />
      <div style={{ position: "absolute", inset: 0, background: `linear-gradient(to bottom, ${pal.bg}cc 0%, transparent 32%, transparent 55%, ${pal.bg}dd 100%)` }} />
      <div style={{ position: "absolute", inset: 0, background: "radial-gradient(ellipse 85% 85% at 50% 50%, transparent 55%, rgba(0,0,0,0.5) 100%)" }} />
      <SceneHeadline text={headline} />
      <div style={{ position: "absolute", left: L.x0, bottom: L.h - L.y1, width: L.cw, display: "flex", flexDirection: "column", gap: 22 }}>
      {data.lower_third && <LowerThird inline title={data.lower_third.title} subtitle={data.lower_third.subtitle} />}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 16 }}>
        <span data-audit="stamp" style={{ fontSize: L.type.stamp, color: pal.muted, lineHeight: 1.2, flex: "1 1 0", minWidth: 0 }}>{data.credit ?? ""}</span>
        {illustrative && (
          <span data-audit="tag" style={{ flex: "none", fontSize: L.type.stamp, fontWeight: 700, color: pal.ink, border: `2px solid ${pal.muted}`, background: `${pal.bg}b3`, borderRadius: 999, padding: "2px 18px" }}>{illustrativeTag(lang)}</span>
        )}
      </div>
      </div>
    </AbsoluteFill>
  );
};
