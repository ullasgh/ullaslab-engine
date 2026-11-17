// Premium style design tokens. Pure data, no React. Colours follow the owner's choice of 2026-11-13: navy base, teal for data,
// amber (#E8A33D, the Candle U mark) for the key number and the mark, coral only for falls, soft blue only for a second series.
export const PT = {
  navy0: "#0B1424", navy1: "#15233C", navy2: "#1B2C48",
  panel: "#16233A", panelLine: "#2C3F5E",
  ink: "#FFFFFF", muted: "#B4BFCE",
  teal: "#4FD1C5", amber: "#E8A33D", coral: "#F28B82", blue: "#8AB4F8",
  grid: "#2C3647",
} as const;

// Spacing scale (px). Every gap, padding and margin in the premium components is one of these.
export const SP = { xs: 8, s: 16, m: 24, l: 32, xl: 48, xxl: 72 } as const;

// Premium type scale. Floors from quality.yaml A5 (body 44, label 36) are never undercut; display sizes are larger than the
// classic kit so a figure reads at phone size (390 px wide) from across the room.
export const PTYPE: Record<"vertical" | "horizontal", PTypeScale> = {
  vertical: { hero: 220, number: 148, display: 120, headline: 64, body: 48, label: 38, stamp: 36 },
  horizontal: { hero: 300, number: 190, display: 150, headline: 84, body: 54, label: 40, stamp: 36 },
} as const;
export type PTypeScale = { hero: number; number: number; display: number; headline: number; body: number; label: number; stamp: number };

export const RADIUS = 26;
