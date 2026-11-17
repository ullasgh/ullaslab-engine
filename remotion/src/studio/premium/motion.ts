// Premium motion presets. Pure functions of a frame number: no randomness, no clock, nothing stateful, so a frame is the same
// whether it is rendered in a full video or in a cached segment (scenecache parity).
export const FPS = 30;
export const clamp01 = (x: number): number => (x < 0 ? 0 : x > 1 ? 1 : x);

/** 0..1 progress of frame `f` over `dur` frames starting at `from`. */
export const range = (f: number, from: number, dur: number): number => clamp01((f - from) / Math.max(1, dur));

export const EASE = {
  out: (t: number) => 1 - Math.pow(1 - clamp01(t), 3),
  outQuint: (t: number) => 1 - Math.pow(1 - clamp01(t), 5),
  outExpo: (t: number) => { const c = clamp01(t); return c >= 1 ? 1 : 1 - Math.pow(2, -10 * c); },
  inOut: (t: number) => { const c = clamp01(t); return c < 0.5 ? 4 * c * c * c : 1 - Math.pow(-2 * c + 2, 3) / 2; },
  smooth: (t: number) => { const c = clamp01(t); return c * c * (3 - 2 * c); },
  in: (t: number) => Math.pow(clamp01(t), 3),
} as const;

// Closed-form damped spring (a settling cosine), so there is no simulation state. 0 at t=0, exactly 1 for t>=1.
export type SpringSpec = { freq: number; decay: number };
export const SPRING = {
  snappy: { freq: 1.35, decay: 6.5 },   // UI pieces landing: one small overshoot
  soft: { freq: 1.0, decay: 5.5 },      // large elements settling
  pop: { freq: 1.6, decay: 5.5 },      // a number or a mark landing: visible overshoot
} as const satisfies Record<string, SpringSpec>;
export const springOut = (t: number, s: SpringSpec = SPRING.snappy): number =>
  t <= 0 ? 0 : t >= 1 ? 1 : 1 - Math.exp(-s.decay * t) * Math.cos(2 * Math.PI * s.freq * t);

/** Start frame of item i in a staggered group. */
export const stagger = (i: number, gap: number, start = 0): number => start + i * gap;

/** Frames a line of text stays on screen fully built before it may be replaced: 0.5 s + 0.3 s per word (plan Step 1). */
export const holdFrames = (words: number, fps = FPS): number => Math.round(fps * (0.5 + 0.3 * Math.max(0, words)));

/** Slow continuous motion that keeps a held frame alive: a sine in [-amp, amp]. */
export const breathe = (f: number, period: number, amp: number, phase = 0): number => Math.sin((2 * Math.PI * f) / period + phase) * amp;

/** Looping 0..1 sawtooth, for light sweeps and pulses. */
export const loop = (f: number, period: number, offset = 0): number => (((f + offset) % period) + period) % period / period;

/** Linear interpolation. */
export const mix = (a: number, b: number, t: number): number => a + (b - a) * t;
