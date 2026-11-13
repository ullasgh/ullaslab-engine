import { useState } from "react";
import React from "react";
import { continueRender, delayRender, staticFile } from "remotion";
import { fontFor } from "./brand";

// Every string value in a props tree, joined: the sample the font loader uses so each needed unicode-range subset is fetched.
export const collectText = (v: unknown, depth = 0): string => {
  if (depth > 8 || v === null || v === undefined) return "";
  if (typeof v === "string") return v;
  if (Array.isArray(v)) return v.map((x) => collectText(x, depth + 1)).join("");
  if (typeof v === "object") return Object.values(v as Record<string, unknown>).map((x) => collectText(x, depth + 1)).join("");
  return "";
};

// Loads the local Noto faces (public/fonts, copied by the render scripts; no network) for this language and Latin before the
// first frame renders. Shared by Video, StudioVideo, StudioThumb and StyleDemo so no composition falls back to a system font.
// `fontsReady` resolves once the faces are loaded: the layout audit waits for it, because it measures text and would
// otherwise read fallback-font metrics (document.fonts.ready alone resolves before the load has even started).
let settle: () => void = () => undefined;
export let fontsReady: Promise<void> = Promise.resolve();

export const useBrandFonts = (lang: string, text: string) => {
  const [handle] = useState(() => {
    fontsReady = new Promise<void>((r) => { settle = r; });
    return delayRender("fonts", { timeoutInMilliseconds: 60000 });
  });
  React.useEffect(() => {
    const link = document.createElement("link");
    link.rel = "stylesheet";
    link.href = staticFile("fonts/fonts.css");
    link.onload = () => {
      const sample = text + "0123456789 UllasLab";
      const fam = fontFor(lang).split(",")[0].replace(/"/g, "").trim();
      Promise.all([400, 700].flatMap((w) => [...new Set([fam, "Noto Sans"])].map((f) => document.fonts.load(`${w} 40px "${f}"`, sample))))
        .catch(() => undefined).finally(() => { continueRender(handle); settle(); });
    };
    link.onerror = () => { continueRender(handle); settle(); };
    document.head.appendChild(link);
  }, []);
};

// FontFace.weight "400" / "700" for a CSS weight: the bundle ships only these two faces.
export const faceWeight = (w: number) => (w <= 500 ? "400" : "700");

// True when a loaded @font-face exists for this family and weight. The FontFaceSet check method is not used on purpose: it
// returns true when no face is declared at all, which is exactly the missing-CSS failure this guards against.
export const fontLoaded = (family: string, weight: number): boolean => {
  const want = faceWeight(weight);
  for (const f of document.fonts as unknown as Iterable<FontFace>) {
    if (f.family.replace(/["']/g, "") === family && f.weight === want && f.status === "loaded") return true;
  }
  return false;
};
