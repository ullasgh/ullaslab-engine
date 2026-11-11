import { STUDIO_TYPE, type TypeScale } from "./palettes.ts";
import { styledType, type StyleId } from "./styles.ts";

export type Orientation = "horizontal" | "vertical";
export const SIZES = { horizontal: { w: 1920, h: 1080 }, vertical: { w: 1080, h: 1920 } } as const;

// Key info (headlines, labels, source stamps, caveats) stays inside the safe box. Art may bleed to the frame edge.
// Vertical = the stricter of YouTube Shorts and Instagram Reels (config/safe_zones.json "platforms"): top 288, bottom 420
// (Shorts/Reels UI + caption zone, 21.9% of 1920), right rail 192 (17.8% of 1080). Keep in sync with the JSON via studio.test.mjs.
export const SAFE_BOX = {
  horizontal: { top: 54, bottom: 54, left: 96, right: 96 },
  vertical: { top: 288, bottom: 420, left: 65, right: 192 },
} as const;

// Per-platform templates (override when a render serves one platform). Mirrors config/safe_zones.json "platforms".
export type Platform = "both" | "youtube_shorts" | "instagram_reels";
export const PLATFORM_BOX = {
  youtube_shorts: { top: 288, bottom: 420, left: 48, right: 192 },
  instagram_reels: { top: 269, bottom: 420, left: 65, right: 130 },
} as const;
/** Safe box for an orientation. Vertical + a named platform uses that platform's template; "both" is the stricter union. */
export const safeBoxFor = (o: Orientation, platform: Platform = "both") =>
  o === "vertical" && platform !== "both" ? PLATFORM_BOX[platform] : SAFE_BOX[o];

export type StudioLayout = {
  o: Orientation; vertical: boolean; w: number; h: number;
  reserve: number; x0: number; x1: number; y0: number; y1: number; cw: number; ch: number; type: TypeScale;
};

// Bottom band (px) held back for burned-in captions: scene content stays above it, captions sit at the safe-box bottom.
export const CAPTION_RESERVE = 176;

export const studioLayout = (o: Orientation, reserveBottom = 0, platform: Platform = "both", style?: StyleId): StudioLayout => {
  const { w, h } = SIZES[o];
  const s = safeBoxFor(o, platform);
  const x0 = s.left, x1 = w - s.right, y0 = s.top, y1 = h - s.bottom - reserveBottom;
  return { o, vertical: o === "vertical", w, h, reserve: reserveBottom, x0, x1, y0, y1, cw: x1 - x0, ch: y1 - y0, type: style ? styledType(o, style) : STUDIO_TYPE[o] };
};

export const inSafeBox = (L: StudioLayout, r: { x: number; y: number; w: number; h: number }) =>
  r.x >= L.x0 && r.y >= L.y0 && r.x + r.w <= L.x1 && r.y + r.h <= L.y1;
