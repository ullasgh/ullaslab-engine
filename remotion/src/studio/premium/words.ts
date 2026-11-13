// Narration word timings as scene-local frames. Pure.
export type Word = { w: string; start: number; end: number };         // seconds from the start of the video (scenes.timed.json)
export type LocalWord = { w: string; a: number; b: number };          // frames from the start of the scene

export const toLocalWords = (words: Word[] | null | undefined, sceneStartFrame: number, fps = 30): LocalWord[] =>
  (words ?? []).map((x) => ({ w: x.w, a: Math.round(x.start * fps) - sceneStartFrame, b: Math.round(x.end * fps) - sceneStartFrame }));

/** Comparable form of a spoken or written word: lower case, punctuation dropped, a leading currency sign and a trailing percent kept out. */
export const norm = (s: string): string => s.toLowerCase().replace(/[^a-z0-9.À-￿]/g, "").replace(/\.+$/, "");

/** First local word at or after index `from` that matches `token` (exact, or one contains the other for tokens like "4.95%"). */
export const findWord = (lw: LocalWord[], token: string, from = 0): { i: number; w: LocalWord } | null => {
  const t = norm(token);
  if (!t) return null;
  for (let i = Math.max(0, from); i < lw.length; i++) if (norm(lw[i].w) === t) return { i, w: lw[i] };
  for (let i = Math.max(0, from); i < lw.length; i++) { const n = norm(lw[i].w); if (n && (n.startsWith(t) || t.startsWith(n)) && Math.min(n.length, t.length) >= 3) return { i, w: lw[i] }; }
  return null;
};

/** Frame a displayed word should land on: its spoken frame when the narration says it (searching forward so a repeated word
 *  matches in order), else `fallback`. Returns the next search index so the caller keeps order. */
export const landFrame = (lw: LocalWord[], token: string, from: number, fallback: number): { f: number; next: number; spoken: boolean } => {
  const hit = findWord(lw, token, from);
  return hit ? { f: Math.max(0, hit.w.a), next: hit.i + 1, spoken: true } : { f: fallback, next: from, spoken: false };
};
