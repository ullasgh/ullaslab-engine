import React, { useEffect, useState } from "react";
import { continueRender, delayRender, useCurrentFrame } from "remotion";
import { C } from "../brand";

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
    (document.fonts?.ready ?? Promise.resolve()).then(() => requestAnimationFrame(() => requestAnimationFrame(() => {
      const els: unknown[] = [];
      document.querySelectorAll("[data-audit]").forEach((el) => {
        const role = el.getAttribute("data-audit")!;
        if (effOpacity(el) < 0.5) return;
        const r = el.getBoundingClientRect();
        if (r.width === 0 || r.height === 0) return;
        const cs = getComputedStyle(el);
        const text = (el.textContent ?? "").trim();
        els.push({ role, x: r.x, y: r.y, w: r.width, h: r.height, fontPx: parseFloat(cs.fontSize), fg: hex(cs.color), bg: bgOf(el),
          words: text ? text.split(/\s+/).length : 0 });
      });
      console.log("[[AUDIT]]" + JSON.stringify({ frame, scene: sceneId, elements: els }));
      continueRender(handle);
    })));
  }, []);
  return null;
};
