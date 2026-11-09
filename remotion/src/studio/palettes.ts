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

export const PALETTES: Record<Topic, Palette> = {
  policy: {
    topic: "policy", bg: "#0E1726", bg2: "#18294A", panel: "#16233A", ink: "#F2F5F9", muted: "#A9B6C8",
    accent: "#8AB4F8", accent2: "#F6C177", accent3: "#4FD1C5", negative: "#F28B82",
    land: "#1E2E48", landLine: "#34496B", water: "#0A1220", grid: "#2A3A55",
  },
  commodities: {
    topic: "commodities", bg: "#14100B", bg2: "#2E2113", panel: "#211A12", ink: "#F6F1E9", muted: "#BDB0A0",
    accent: "#E6B450", accent2: "#E08A5B", accent3: "#9BD0A4", negative: "#F28B82",
    land: "#2B2216", landLine: "#4A3B26", water: "#0D0A07", grid: "#3A2E20",
  },
  trade: {
    topic: "trade", bg: "#08182A", bg2: "#0F3050", panel: "#0F2540", ink: "#EEF5FA", muted: "#9FB6CB",
    accent: "#5EC4F0", accent2: "#FF9F68", accent3: "#7EE2A8", negative: "#F28B82",
    land: "#14304F", landLine: "#2A4F78", water: "#061220", grid: "#1F3B5C",
  },
  tech: {
    topic: "tech", bg: "#110F20", bg2: "#241F45", panel: "#1C1932", ink: "#F3F1FA", muted: "#B1ACCB",
    accent: "#C4B5FD", accent2: "#7EE2A8", accent3: "#5EC4F0", negative: "#F28BB8",
    land: "#221F3E", landLine: "#3B3669", water: "#0B0A16", grid: "#2E2A52",
  },
  volatility: {
    topic: "volatility", bg: "#190F14", bg2: "#35182A", panel: "#2A1820", ink: "#F9F0F1", muted: "#C9AEB4",
    accent: "#F28B82", accent2: "#F6C177", accent3: "#8AB4F8", negative: "#FF9AA2",
    land: "#2C1A22", landLine: "#4F2D3A", water: "#0F080B", grid: "#40242F",
  },
};

export const paletteFor = (topic: string | undefined): Palette => PALETTES[(topic as Topic) ?? "policy"] ?? PALETTES.policy;

// Type scale (px) per orientation. Minimums follow quality.yaml A5 (body 44, label 36); stamp never below 36.
export type TypeScale = { number: number; display: number; headline: number; body: number; label: number; stamp: number };
export const STUDIO_TYPE: Record<"horizontal" | "vertical", TypeScale> = {
  horizontal: { number: 240, display: 132, headline: 80, body: 52, label: 38, stamp: 36 },
  vertical: { number: 200, display: 112, headline: 68, body: 48, label: 36, stamp: 36 },
};
