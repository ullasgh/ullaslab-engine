import React, { useState } from "react";
import { Audio, continueRender, delayRender, staticFile } from "remotion";
import { END_LINES, FONT_FAMILIES, fontFor } from "./brand";
import { Audit } from "./components/audit";
import { Captions } from "./components/captions";
import { Frame, Header } from "./components/common";
import { Scenes } from "./components/scenes";
import { CtxR, computeLayout } from "./layout";
import { TEMPLATES } from "./templates";
import { Props } from "./types";

const allText = (p: Props) => [END_LINES[p.lang] ?? END_LINES.en, ...p.scenes.flatMap((s) => [s.headline, s.body, ...(s.items ?? []).map((i) => i.label), s.chart_data?.title])]
  .flatMap((v) => (v === undefined ? [] : typeof v === "string" ? [v] : Object.values(v))).join("") + p.cues.flatMap((c) => c.lines).join("");

// Loads the Noto faces needed for this language (and Latin) before the first frame renders.
const useFonts = (p: Props) => {
  const [handle] = useState(() => delayRender("fonts", { timeoutInMilliseconds: 60000 }));
  React.useEffect(() => {
    const link = document.createElement("link");
    link.rel = "stylesheet";
    link.href = staticFile("fonts/fonts.css");
    link.onload = () => {
      const sample = allText(p) + "0123456789 UllasLab";
      const fam = fontFor(p.lang).split(",")[0].replace(/"/g, "").trim();
      Promise.all([400, 700].flatMap((w) => [...new Set([fam, "Noto Sans"])].map((f) => document.fonts.load(`${w} 40px "${f}"`, sample))))
        .catch(() => undefined).finally(() => continueRender(handle));
    };
    link.onerror = () => continueRender(handle);
    document.head.appendChild(link);
  }, []);
};
void FONT_FAMILIES;

export const Video: React.FC<Props> = (p) => {
  useFonts(p);
  const L = computeLayout(p.orientation);
  const tpl = TEMPLATES[Math.min(10, Math.max(1, p.format)) - 1];
  return (
    <CtxR.Provider value={{ p, L, tpl }}>
      <Frame>
        <Header />
        <Scenes />
        <Captions />
      </Frame>
      {p.audio ? <Audio src={staticFile(p.audio)} /> : null}
      <Audit enabled={!!p.audit} sceneId="" />
    </CtxR.Provider>
  );
};
