import React, { useEffect, useState } from "react";
import { continueRender, delayRender, useCurrentFrame } from "remotion";
import { C } from "../brand";
import { fontLoaded, fontsReady } from "../fonts";

// Layout audit for QA A5. Only active when props.audit is true (still renders). Emits geometry,
// font size and colours (never text) through console.log; scripts/render.mjs collects it.
const hex = (rgb: string): string | null => {
  const m = rgb.match(/rgba?\(([^)]+)\)/);
  if (!m) return null;
  const [r, g, b, a = "1"] = m[1].split(",").map((x) => x.trim());
  if (Number(a) < 0.95) return null;
  return "#" + [r, g, b].map((v) => Math.round(Number(v)).toString(16).padStart(2, "0")).join("");
};

const effOpacity = (el: Element) => {
  let o = 1;
  for (let n: Element | null = el; n; n = n.parentElement) o *= Number(getComputedStyle(n).opacity);
  return o;
};

const bgOf = (el: Element) => {
  for (let n: Element | null = el; n; n = n.parentElement) {
    const c = hex(getComputedStyle(n).backgroundColor);
    if (c) return c;
  }
  return C.bg;
};

export const Audit: React.FC<{ enabled: boolean; sceneId: string }> = ({ enabled, sceneId }) => {
  const frame = useCurrentFrame();
  const [handle] = useState(() => (enabled ? delayRender("layout audit", { timeoutInMilliseconds: 60000 }) : null));
  useEffect(() => {
    if (!enabled || handle === null) return;
    fontsReady.then(() => document.fonts?.ready ?? Promise.resolve()).then(() => requestAnimationFrame(() => requestAnimationFrame(() => {
      const els: unknown[] = [];
      const fonts = new Map<string, { family: string; weight: number; loaded: boolean }>();
      document.querySelectorAll("[data-audit]").forEach((el) => {
        const role = el.getAttribute("data-audit")!;
        if (effOpacity(el) < 0.5) return;
        const r = el.getBoundingClientRect();
        if (r.width === 0 || r.height === 0) return;
        const cs = getComputedStyle(el);
        const text = (el.textContent ?? "").trim();
        // Rendered-font check: the first family of every audited element must have a loaded @font-face at its weight.
        const family = cs.fontFamily.split(",")[0].replace(/["']/g, "").trim();
        const weight = Number(cs.fontWeight) || 400;
        const fk = `${family}/${weight <= 500 ? 400 : 700}`;
        if (text && !fonts.has(fk)) fonts.set(fk, { family, weight: weight <= 500 ? 400 : 700, loaded: fontLoaded(family, weight) });
        els.push({ role, x: r.x, y: r.y, w: r.width, h: r.height, fontPx: parseFloat(cs.fontSize), fg: hex(cs.color), bg: bgOf(el),
          words: text ? Math.max(text.split(/\s+/).length, Math.ceil((text.match(/[\u3040-\u30ff\u4e00-\u9fff]/g) ?? []).length / 2)) : 0 });
      });
      console.log("[[AUDIT]]" + JSON.stringify({ frame, scene: sceneId, elements: els, fonts: [...fonts.values()] }));
      continueRender(handle);
    })));
  }, []);
  return null;
};
