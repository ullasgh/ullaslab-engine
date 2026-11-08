import React from "react";
import { useCurrentFrame, useVideoConfig } from "remotion";
import { C, fontFor } from "../brand";
import { useCtx } from "../layout";

// Burned-in captions: <= 2 lines of <= 32 chars (cue builder enforces). Hidden during the
// disclaimer card, which already shows its text on screen.
export const Captions: React.FC = () => {
  const { p, L } = useCtx();
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const t = frame / fps;
  const disc = p.timeline.scenes.find((s) => s.kind === "disclaimer");
  if (disc && t >= disc.start && t < disc.end) return null;
  const cue = p.cues.find((c) => t >= c.start && t < c.end);
  if (!cue) return null;
  return (
    <div style={{ position: "absolute", left: L.x0, width: L.cw, top: L.y1 - L.capH, height: L.capH, display: "flex", alignItems: "flex-end", justifyContent: "center" }}>
      <div data-audit="caption" style={{ background: C.caption, color: C.text, fontFamily: fontFor(p.lang), fontWeight: 700, fontSize: L.type.caption, lineHeight: 1.3,
        textAlign: "center", padding: "14px 24px", borderRadius: 18, direction: p.rtl ? "rtl" : "ltr", whiteSpace: "nowrap", maxWidth: L.cw }}>
        {cue.lines.map((l, i) => <div key={i}>{l}</div>)}
      </div>
    </div>
  );
};
