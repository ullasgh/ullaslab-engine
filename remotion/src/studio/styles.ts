// Video style presets (V2 M2). Pure data and helpers, no React, so node tests can import it.
//
// A style is a token set (type scale, motion, layout, backdrop, caption treatment, chart honesty) applied by SceneRenderer on
// top of the existing kit. Colours always come from the brand palette (palettes.ts); a style never introduces a colour.
// Absent style = today's look, byte for byte: every helper returns the neutral value for `undefined`.
import { STUDIO_TYPE, type TypeScale } from "./palettes.ts";

export const STYLE_IDS = ["data-story", "creator-motion", "chalk-talk", "clean-tech", "premium"] as const;
export type StyleId = (typeof STYLE_IDS)[number];
export const isStyleId = (s: unknown): s is StyleId => typeof s === "string" && (STYLE_IDS as readonly string[]).includes(s);

// Scene types the style layer restyles. Footage, map and globe render unchanged (their art is photographic or geographic).
export const STYLED_TYPES = ["chart", "timeline", "flow", "kinetic"] as const;
export const isStyledType = (t: string): boolean => (STYLED_TYPES as readonly string[]).includes(t);

export type BackdropKind = "grid" | "guides" | "glow" | "board" | "clean";

export type StylePreset = {
  id: StyleId | "none";
  /** Multipliers on the studio type scale. Only creator-motion enlarges; none shrinks below the quality.yaml A5 floors. */
  type: { number: number; display: number; headline: number };
  motion: {
    /** 0 = no camera move, 1 = the director's move as is; below 1 is "restrained". */
    camera: number;
    /** Frames between staggered items (words, steps, cards). */
    stagger: number;
    /** Frames an item takes to come in. */
    enter: number;
    /** Overshoot of the pop-in (0 = none). */
    overshoot: number;
  };
  layout: { radius: number; border: number; backdrop: BackdropKind; align: "start" | "center" };
  captions: { emphasiseNumbers: boolean; mergeNotation: boolean };
  /** Charts: axes start at zero and always cover every plotted number (no truncated or stretched scale). */
  chart: { zeroBaseline: boolean; band: boolean; requireSource: boolean };
};

export const PRESETS: Record<StyleId, StylePreset> = {
  "data-story": {
    id: "data-story",
    type: { number: 1, display: 1, headline: 1 },
    motion: { camera: 0.6, stagger: 6, enter: 22, overshoot: 0 },
    layout: { radius: 18, border: 2, backdrop: "guides", align: "start" },
    captions: { emphasiseNumbers: true, mergeNotation: true },
    chart: { zeroBaseline: true, band: true, requireSource: true },
  },
  "creator-motion": {
    id: "creator-motion",
    type: { number: 1.15, display: 1.18, headline: 1.06 },
    motion: { camera: 0.5, stagger: 5, enter: 14, overshoot: 0.12 },
    layout: { radius: 26, border: 3, backdrop: "glow", align: "start" },
    captions: { emphasiseNumbers: true, mergeNotation: true },
    chart: { zeroBaseline: false, band: false, requireSource: true },
  },
  "chalk-talk": {
    id: "chalk-talk",
    type: { number: 1, display: 1, headline: 1 },
    motion: { camera: 0, stagger: 26, enter: 22, overshoot: 0 },
    layout: { radius: 14, border: 4, backdrop: "board", align: "start" },
    captions: { emphasiseNumbers: true, mergeNotation: true },
    chart: { zeroBaseline: true, band: false, requireSource: true },
  },
  "clean-tech": {
    id: "clean-tech",
    type: { number: 1, display: 1, headline: 1 },
    motion: { camera: 0.35, stagger: 9, enter: 20, overshoot: 0 },
    layout: { radius: 28, border: 3, backdrop: "clean", align: "start" },
    captions: { emphasiseNumbers: false, mergeNotation: true },
    chart: { zeroBaseline: true, band: false, requireSource: true },
  },
  // premium: scene art, camera, transitions and end card are drawn by studio/premium/*; these tokens only feed the shared layout and captions.
  premium: {
    id: "premium",
    type: { number: 1, display: 1, headline: 1 },
    motion: { camera: 1, stagger: 6, enter: 18, overshoot: 0.1 },
    layout: { radius: 26, border: 3, backdrop: "grid", align: "center" },
    captions: { emphasiseNumbers: true, mergeNotation: true },
    chart: { zeroBaseline: false, band: false, requireSource: true },
  },
};

/** Neutral preset: what an unstyled scene uses. Identical to the pre-M2 look. */
export const NEUTRAL: StylePreset = {
  id: "none",
  type: { number: 1, display: 1, headline: 1 },
  motion: { camera: 1, stagger: 4, enter: 16, overshoot: 0 },
  layout: { radius: 22, border: 3, backdrop: "grid", align: "start" },
  captions: { emphasiseNumbers: false, mergeNotation: false },
  chart: { zeroBaseline: false, band: true, requireSource: false },
};

export const presetFor = (style: StyleId | undefined): StylePreset => (style ? PRESETS[style] : NEUTRAL);

/** Style of one scene: its own, else the item's, else none. Unknown values fall back to none (the Python side rejects them). */
export const resolveStyle = (item: unknown, scene: unknown): StyleId | undefined =>
  isStyleId(scene) ? scene : isStyleId(item) ? item : undefined;

/** Type scale for an orientation under a style. Sizes are rounded; label and stamp are never scaled (quality.yaml A5 floors). */
export const styledType = (o: "horizontal" | "vertical", style: StyleId | undefined): TypeScale => {
  const base = STUDIO_TYPE[o];
  const k = presetFor(style).type;
  return { ...base, number: Math.round(base.number * k.number), display: Math.round(base.display * k.display), headline: Math.round(base.headline * k.headline) };
};

/** Camera strength under a style: scales the move's distance from the identity transform. */
export const restrainCamera = (c: { scale: number; x: number; y: number }, style: StyleId | undefined): { scale: number; x: number; y: number } => {
  const k = presetFor(style).motion.camera;
  return { scale: 1 + (c.scale - 1) * k, x: c.x * k, y: c.y * k };
};

/* ------------------------------------------------------------------------------------- numbers in text */
// Animated counters only ever count toward the exact token written in the narration or on-screen text; the final frame is the
// token verbatim, so a style can never change a figure. Tokens it cannot parse safely are shown static.
const NUM_RE = /^([$€£₹]?)(\d{1,3}(?:,\d{3})+|\d+)(\.\d+)?(%|x|bn|m|k|bps|pts)?([.,;:!?]?)$/i;

export type NumberToken = { prefix: string; value: number; decimals: number; suffix: string; trail: string; grouped: boolean; raw: string };

export const parseNumberToken = (raw: string): NumberToken | null => {
  const m = NUM_RE.exec(raw);
  if (!m) return null;
  const [, prefix, int, frac = "", suffix = "", trail = ""] = m;
  // a bare year ("2008") is a label, not a quantity: never count it up from 0
  if (!prefix && !frac && !suffix && /^(19|20|21)\d\d$/.test(int)) return null;
  return { prefix, value: Number(int.replace(/,/g, "") + frac), decimals: frac ? frac.length - 1 : 0, suffix, trail, grouped: int.includes(","), raw };
};

/** Text of a counting number at progress p in 0..1. p >= 1 returns the original token verbatim. */
export const countedText = (t: NumberToken, p: number, locale = "en-US"): string => {
  if (p >= 1) return t.raw;
  const e = 1 - Math.pow(1 - Math.max(0, p), 3);
  const v = t.value * e;
  const body = v.toLocaleString(locale, { minimumFractionDigits: t.decimals, maximumFractionDigits: t.decimals, useGrouping: t.grouped });
  return `${t.prefix}${body}${t.suffix}${t.trail}`;
};

/* ------------------------------------------------------------------------------------------- captions */
export type CapWord = { w: string; start: number; end: number };
const CUR = /^[$€£₹]$/;
const SUFFIX_ONLY = /^(%|bps|pts)$/i;

/** Re-attach a stand-alone "%" / unit to the number before it and a stand-alone currency sign to the number after it, so
 *  captions never break "4.5 %" or "$ 85" across tokens. Timing spans the merged pair. Other words pass through. */
export const mergeNotation = (words: CapWord[]): CapWord[] => {
  const out: CapWord[] = [];
  for (let i = 0; i < words.length; i++) {
    const w = words[i];
    const prev = out[out.length - 1];
    if (SUFFIX_ONLY.test(w.w) && prev && /\d$/.test(prev.w)) { prev.w += w.w; prev.end = Math.max(prev.end, w.end); continue; }
    const next = words[i + 1];
    if (CUR.test(w.w) && next && /^\d/.test(next.w)) { out.push({ w: w.w + next.w, start: w.start, end: Math.max(w.end, next.end) }); i++; continue; }
    out.push({ ...w });
  }
  return out;
};

export const isNumberWord = (w: string): boolean => /\d/.test(w);

/* ------------------------------------------------------------------------------------- hand-drawn strokes */
/** Deterministic wobble for hand-drawn strokes (no Math.random: renders must be reproducible). Offsets stay within `amp`. */
export const wobble = (seed: number, i: number, amp: number): number => {
  const s = Math.sin(seed * 12.9898 + i * 78.233) * 43758.5453;
  return (s - Math.floor(s) - 0.5) * 2 * amp;
};

/** Rough polyline through the corners of a rect: a hand-drawn box. Points stay within `amp` px of the true edge. */
export const sketchRect = (w: number, h: number, seed: number, amp = 3): string => {
  const pts: [number, number][] = [[0, 0], [w * 0.5, 0], [w, 0], [w, h * 0.5], [w, h], [w * 0.5, h], [0, h], [0, h * 0.5], [0, 0], [w * 0.12, 0]];
  return pts.map(([x, y], i) => `${i ? "L" : "M"} ${(x + wobble(seed, i * 2, amp)).toFixed(1)} ${(y + wobble(seed, i * 2 + 1, amp)).toFixed(1)}`).join(" ");
};

/** Rough underline of width w: a slightly wavering horizontal stroke. */
export const sketchLine = (w: number, seed: number, amp = 2.5): string => {
  const n = 6;
  return Array.from({ length: n + 1 }, (_, i) => `${i ? "L" : "M"} ${((w * i) / n).toFixed(1)} ${wobble(seed, i, amp).toFixed(1)}`).join(" ");
};

/* ----------------------------------------------------------------------------------------- text markup */
/** `*word*` is emphasis markup for the kinetic styles only. Any other place (step lines, cards, chart and diagram headlines,
 *  footage / map / globe titles) shows the plain words: literal asterisks never reach the screen. */
export const stripEmphasis = (text: string): string => text.replace(/\*([^*]*)\*/g, "$1").replace(/\*/g, "");

/** Chalk-talk steps: "|"-separated lines; a line starting with "=" is the highlighted result (the "=" itself is dropped). */
export const parseSteps = (text: string): { text: string; result: boolean }[] =>
  stripEmphasis(text).split("|").map((l) => l.trim()).filter(Boolean).map((l) => (l.startsWith("=") ? { text: l.replace(/^=+\s*/, ""), result: true } : { text: l, result: false }));

/** Clean-tech cards: "|"-separated; "Title: detail" splits on the first colon. */
export const parseCards = (text: string): { title: string; detail?: string }[] =>
  stripEmphasis(text).split("|").map((l) => l.trim()).filter(Boolean).map((l) => {
    const i = l.indexOf(":");
    return i > 0 && i < l.length - 1 ? { title: l.slice(0, i).trim(), detail: l.slice(i + 1).trim() } : { title: l };
  });

/* ------------------------------------------------------------------------------------------------ fitting */
/** Largest font size <= base at which `lines` fit in a w x h box when each line wraps by an average glyph width of 0.56 em.
 *  Never below `min`: a text that still does not fit at `min` is the director's problem (scenes-check caps on_screen_text at 90 chars). */
export const fitSize = (lines: string[], w: number, h: number, base: number, min: number, lineHeight = 1.12, gap = 0.12): number => {
  for (let size = base; size >= min; size = Math.floor(size * 0.94)) {
    const rows = lines.reduce((n, l) => n + Math.max(1, Math.ceil((l.length * 0.56 * size) / w)), 0);
    if (rows * size * lineHeight + (lines.length - 1) * size * gap <= h) return size;
  }
  return min;
};
