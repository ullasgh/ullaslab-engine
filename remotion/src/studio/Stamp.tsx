import React from "react";
import { TAG_COLOR, stampText } from "../brand";
import type { Tag } from "../types";
import { useFont, useRamp, useStudio } from "./context";
import { PALETTES } from "./palettes";

export type SourceInfo = { name: string; as_of: string; url?: string };

// Source stamp + freshness tag. Required under every data visual (data-licensing gate).
export const StudioSourceStamp: React.FC<{ source: SourceInfo; freshness: Tag; style?: React.CSSProperties }> = ({ source, freshness, style }) => {
  const { L, pal, lang } = useStudio();
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 16, minHeight: 52, width: "100%", ...style }}>
      <span data-audit="stamp" style={{ fontSize: L.type.stamp, color: pal.muted, flex: "1 1 0", minWidth: 0, lineHeight: 1.2, overflowWrap: "anywhere" }}>
        {stampText(lang, source.name, source.as_of)}
      </span>
      <span data-audit="tag" style={{ flex: "none", background: TAG_COLOR[freshness], color: PALETTES.policy.bg, fontWeight: 700, fontSize: L.type.stamp, padding: "2px 14px", borderRadius: 999, letterSpacing: 1 }}>{freshness}</span>
    </div>
  );
};

export type ChartMeta = {
  metric: string; unit: string; period: string;
  source: SourceInfo; freshness: Tag; caveat?: string;
};

// Metric + unit + period header, plot slot, optional caveat, source stamp. Every data chart renders inside this.
export const ChartShell: React.FC<{ meta: ChartMeta; headline?: string; children: React.ReactNode }> = ({ meta, headline, children }) => {
  const { L, pal } = useStudio();
  const font = useFont();
  const k = useRamp(0, 14);
  return (
    <div style={{ position: "absolute", left: L.x0, top: L.y0, width: L.cw, height: L.ch, display: "flex", flexDirection: "column", gap: 14, fontFamily: font, color: pal.ink }}>
      <div style={{ opacity: k, transform: `translateY(${(1 - k) * 18}px)` }}>
        {headline && <div data-audit="headline" style={{ fontSize: L.type.headline, fontWeight: 700, lineHeight: 1.12, marginBottom: 10 }}>{headline}</div>}
        <div data-audit="body" style={{ fontSize: L.type.label, color: pal.accent, fontWeight: 700, lineHeight: 1.2 }}>{meta.metric}</div>
        <div data-audit="body" style={{ fontSize: L.type.label, color: pal.muted, lineHeight: 1.2 }}>{meta.unit} {"·"} {meta.period}</div>
      </div>
      <div style={{ flex: 1, minHeight: 0, position: "relative" }}>{children}</div>
      {meta.caveat && <div data-audit="stamp" style={{ fontSize: L.type.stamp, color: pal.muted, lineHeight: 1.2, fontStyle: "italic" }}>{meta.caveat}</div>}
      <StudioSourceStamp source={meta.source} freshness={meta.freshness} />
    </div>
  );
};

// Scene headline for non-chart scenes (map, globe, footage): top of the safe box.
export const SceneHeadline: React.FC<{ text?: string; style?: React.CSSProperties; maxWidth?: number }> = ({ text, style, maxWidth }) => {
  const { L, pal } = useStudio();
  const font = useFont();
  const k = useRamp(4, 20);
  if (!text) return null;
  return (
    <div data-audit="headline" style={{
      position: "absolute", left: L.x0, top: L.y0, width: maxWidth ?? L.cw, fontFamily: font, fontSize: L.type.headline, fontWeight: 700, lineHeight: 1.12,
      color: pal.ink, textShadow: "0 2px 18px rgba(0,0,0,0.55)", opacity: k, transform: `translateY(${(1 - k) * 22}px)`, ...style,
    }}>
      <span style={{ display: "block", width: 72 * k, height: 6, background: pal.accent, borderRadius: 3, marginBottom: 16 }} />
      {text}
    </div>
  );
};
