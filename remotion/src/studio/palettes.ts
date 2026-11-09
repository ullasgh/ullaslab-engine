// Per-topic palettes and type scale for the studio visual kit. Consistent with docs/brand.md (content repo):
// calm, data-first, no hype colours. Every text/accent colour is >= 4.5:1 on its bg and panel (see studio.test.mjs).
export type Topic = "policy" | "commodities" | "trade" | "tech" | "volatility";
export const TOPICS: Topic[] = ["policy", "commodities", "trade", "tech", "volatility"];

export type Palette = {
  topic: Topic;
  bg: string; bg2: string; panel: string; ink: string; muted: string;
  accent: string; accent2: string; accent3: string; negative: string;
  land: string; landLine: string; water: string; grid: string;
};

// Base brand palette (owner direction 2026-11-09): dark navy and charcoal surfaces, teal and gold accents, strong white type.
// Every topic shares the base surfaces and neutrals; a topic only re-orders / tints the accents (teal, gold, soft blue, coral).
export const BASE = {
  bg: "#0B1424",       // dark navy
  bg2: "#15233C",      // navy, lifted (gradient end)
  panel: "#1A2230",    // charcoal card surface
  ink: "#FFFFFF",      // strong white type
  muted: "#B4BFCE",
  teal: "#4FD1C5",
  gold: "#E8BB55",
  blue: "#8AB4F8",     // third series colour for charts
  coral: "#F28B82",    // negative / warning only
  land: "#1B2638", landLine: "#33425A", water: "#070D18", grid: "#2C3647",
} as const;

const mk = (topic: Topic, accent: string, accent2: string, accent3: string, over: Partial<Palette> = {}): Palette => ({
  topic, bg: BASE.bg, bg2: BASE.bg2, panel: BASE.panel, ink: BASE.ink, muted: BASE.muted,
  accent, accent2, accent3, negative: BASE.coral,
  land: BASE.land, landLine: BASE.landLine, water: BASE.water, grid: BASE.grid, ...over,
});

export const PALETTES: Record<Topic, Palette> = {
  policy: mk("policy", BASE.teal, BASE.gold, BASE.blue),
  commodities: mk("commodities", BASE.gold, BASE.teal, BASE.blue, { bg2: "#1D2231" }),           // warmer charcoal lift
  trade: mk("trade", "#6FE0D4", BASE.gold, BASE.blue, { bg2: "#10294A", land: "#162B48" }),        // deeper navy, lighter teal
  tech: mk("tech", BASE.blue, BASE.teal, BASE.gold, { bg2: "#18213F" }),                           // blue-led, navy-indigo lift
  volatility: mk("volatility", BASE.gold, BASE.coral, BASE.teal, { bg2: "#231D2E", negative: "#FF9AA2" }), // charcoal-plum lift
};

export const paletteFor = (topic: string | undefined): Palette => PALETTES[(topic as Topic) ?? "policy"] ?? PALETTES.policy;

// Type scale (px) per orientation. Minimums follow quality.yaml A5 (body 44, label 36); stamp never below 36.
export type TypeScale = { number: number; display: number; headline: number; body: number; label: number; stamp: number };
export const STUDIO_TYPE: Record<"horizontal" | "vertical", TypeScale> = {
  horizontal: { number: 240, display: 132, headline: 80, body: 52, label: 38, stamp: 36 },
  vertical: { number: 200, display: 112, headline: 68, body: 48, label: 36, stamp: 36 },
};
