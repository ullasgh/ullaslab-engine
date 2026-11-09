import { STUDIO_TYPE, type TypeScale } from "./palettes.ts";

export type Orientation = "horizontal" | "vertical";
export const SIZES = { horizontal: { w: 1920, h: 1080 }, vertical: { w: 1080, h: 1920 } } as const;

// Key info (headlines, labels, source stamps, caveats) stays inside the safe box. Art may bleed to the frame edge.
// Vertical: bottom 420 px (21.9% of 1920) is the Shorts/Reels UI + caption zone; right 130 px (12.0% of 1080)
// is the action-button rail. Keep in sync with config/safe_zones.json (top/bottom/left) via studio.test.mjs.
export const SAFE_BOX = {
  horizontal: { top: 54, bottom: 54, left: 96, right: 96 },
  vertical: { top: 220, bottom: 420, left: 60, right: 130 },
} as const;

export type StudioLayout = {
  o: Orientation; vertical: boolean; w: number; h: number;
  x0: number; x1: number; y0: number; y1: number; cw: number; ch: number; type: TypeScale;
};

// Bottom band (px) held back for burned-in captions: scene content stays above it, captions sit at the safe-box bottom.
export const CAPTION_RESERVE = 176;

export const studioLayout = (o: Orientation, reserveBottom = 0): StudioLayout => {
  const { w, h } = SIZES[o];
  const s = SAFE_BOX[o];
  const x0 = s.left, x1 = w - s.right, y0 = s.top, y1 = h - s.bottom - reserveBottom;
  return { o, vertical: o === "vertical", w, h, x0, x1, y0, y1, cw: x1 - x0, ch: y1 - y0, type: STUDIO_TYPE[o] };
};

export const inSafeBox = (L: StudioLayout, r: { x: number; y: number; w: number; h: number }) =>
  r.x >= L.x0 && r.y >= L.y0 && r.x + r.w <= L.x1 && r.y + r.h <= L.y1;
