import React from "react";
import { Audio, staticFile } from "remotion";
import { useBrandFonts } from "./fonts";
import { END_LINES, FONT_FAMILIES } from "./brand";
import { Audit } from "./components/audit";
import { Captions } from "./components/captions";
import { Frame, Header } from "./components/common";
import { Scenes } from "./components/scenes";
import { CtxR, computeLayout } from "./layout";
import { TEMPLATES } from "./templates";
import { Props } from "./types";

const allText = (p: Props) => [END_LINES[p.lang] ?? END_LINES.en, ...p.scenes.flatMap((s) => [s.headline, s.body, ...(s.items ?? []).map((i) => i.label), s.chart_data?.title])]
  .flatMap((v) => (v === undefined ? [] : typeof v === "string" ? [v] : Object.values(v))).join("") + p.cues.flatMap((c) => c.lines).join("");

const useFonts = (p: Props) => useBrandFonts(p.lang, allText(p));
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
