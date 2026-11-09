import React from "react";
import { C, TAG_COLOR, fontFor, stampText, t } from "../brand";
import { useCtx } from "../layout";
import { Chart, Tag } from "../types";

export const Frame: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const { p, L, tpl } = useCtx();
  return (
    <div data-audit="bg" style={{ position: "absolute", inset: 0, background: C.bg, fontFamily: fontFor(p.lang), color: C.text, width: L.w, height: L.h, overflow: "hidden" }}>
      <div style={{ position: "absolute", left: 0, top: 0, width: L.w, height: 10, background: tpl.accent }} />
      {children}
    </div>
  );
};

// Brand wordmark. A fixed brand mark, so it is a 'stamp' (exempt from the on-screen word budget).
export const Header: React.FC = () => {
  const { L, tpl } = useCtx();
  return (
    <div data-audit="stamp" style={{ position: "absolute", left: L.x0, top: L.y0, height: 60, display: "flex", alignItems: "center", gap: 14, fontSize: L.type.label, fontWeight: 700, color: C.muted, letterSpacing: 1 }}>
      <span style={{ width: 14, height: 14, borderRadius: 7, background: tpl.accent, display: "inline-block" }} />
      UllasLab
    </div>
  );
};

export const Content: React.FC<{ children: React.ReactNode; style?: React.CSSProperties }> = ({ children, style }) => {
  const { L } = useCtx();
  return (
    <div style={{ position: "absolute", left: L.x0, top: L.contentTop, width: L.cw, height: L.ch, display: "flex", flexDirection: "column", gap: 24, ...style }}>
      {children}
    </div>
  );
};

export const Headline: React.FC<{ text: string; style?: React.CSSProperties }> = ({ text, style }) => {
  const { L, p } = useCtx();
  return (
    <div data-audit="headline" style={{ fontSize: L.type.headline, fontWeight: 700, lineHeight: 1.2, direction: p.rtl ? "rtl" : "ltr", ...style }}>{text}</div>
  );
};

export const Body: React.FC<{ text: string; style?: React.CSSProperties }> = ({ text, style }) => {
  const { L, p } = useCtx();
  return (
    <div data-audit="body" style={{ fontSize: L.type.body, lineHeight: 1.35, color: C.text, direction: p.rtl ? "rtl" : "ltr", ...style }}>{text}</div>
  );
};

export const FreshnessTag: React.FC<{ tag: Tag; small?: boolean }> = ({ tag, small }) => {
  const { L } = useCtx();
  return (
    <span data-audit="tag" style={{ display: "inline-block", background: TAG_COLOR[tag], color: C.tagText, fontWeight: 700, fontSize: L.type.label, padding: small ? "2px 12px" : "4px 16px", borderRadius: 999, letterSpacing: 1 }}>{tag}</span>
  );
};

// Source stamp + freshness tag: required under every chart (data-licensing gate).
export const SourceStamp: React.FC<{ chart: Chart }> = ({ chart }) => {
  const { L, p } = useCtx();
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 16, flexWrap: "nowrap", minHeight: 56, width: "100%" }}>
      <span data-audit="stamp" style={{ fontSize: L.type.label, color: C.muted, flex: "1 1 0", minWidth: 0, lineHeight: 1.25, overflowWrap: "anywhere", direction: p.rtl ? "rtl" : "ltr" }}>
        {stampText(p.lang, chart.source.name, chart.source.as_of)}
      </span>
      <span style={{ flex: "none" }}><FreshnessTag tag={chart.freshness} /></span>
    </div>
  );
};

export const Card: React.FC<{ children: React.ReactNode; style?: React.CSSProperties }> = ({ children, style }) => (
  <div style={{ background: C.panel, borderRadius: 28, padding: 32, ...style }}>{children}</div>
);

export const Title: React.FC<{ chart: Chart; headline?: string }> = ({ chart, headline }) => {
  const { p } = useCtx();
  return <Headline text={headline || t(chart.title, p.lang)} />;
};
