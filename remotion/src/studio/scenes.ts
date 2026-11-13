// scenes.json contract consumed by SceneRenderer (produced by the director agent, WP1). Pure helpers, no React.
import type { Topic } from "./palettes";
import { isStyleId, type StyleId } from "./styles.ts";

export const SCENE_TYPES = ["footage", "map", "globe", "chart", "timeline", "flow", "kinetic"] as const;
export type SceneType = (typeof SCENE_TYPES)[number];
export const CAMERA_MOVES = ["none", "push", "pull", "pan_left", "pan_right"] as const;
export type CameraMove = (typeof CAMERA_MOVES)[number];
// The first four are the restrained set every style may use. The last four belong to the premium style (director.ts PREMIUM_TRANSITION_MAP
// maps the director's names onto them); their frame mirror is studio/scenecache.py.
export const TRANSITIONS = ["cut", "crossfade", "wipe", "match_move", "push_through", "morph", "sweep", "interrupt"] as const;
export type TransitionKind = (typeof TRANSITIONS)[number];

export type StudioScene = {
  id: string;
  type: SceneType;
  start: number; // frames, inclusive
  end: number;   // frames, exclusive
  on_screen_text?: string;
  data_ref?: string;               // key into the refs map (chart data, route data, ...)
  data?: unknown;                  // inline data; wins over data_ref
  palette?: Topic;
  camera_move?: CameraMove;
  transition?: TransitionKind;     // how this scene enters
  style?: StyleId;                 // per-scene style preset (V2 M2); falls back to the item style
  // Passed through from the director's scene (premium style): the narration's word timings (seconds from the video start), the
  // scene role, and the camera the director asked for. Absent for kit-shaped scenes.
  words?: { w: string; start: number; end: number }[] | null;
  role?: string;
};

export const TRANSITION_FRAMES: Record<TransitionKind, number> = { cut: 0, crossfade: 12, wipe: 14, match_move: 16, push_through: 20, morph: 20, sweep: 16, interrupt: 8 };

export const validateScenes = (scenes: StudioScene[], refs: Record<string, unknown> = {}): string[] => {
  const errs: string[] = [];
  const ids = new Set<string>();
  scenes.forEach((s, i) => {
    const at = `scene ${s.id ?? i}`;
    if (!s.id) errs.push(`${at}: missing id`);
    else if (ids.has(s.id)) errs.push(`${at}: duplicate id`);
    ids.add(s.id);
    if (!SCENE_TYPES.includes(s.type)) errs.push(`${at}: unknown type "${s.type}"`);
    if (!Number.isInteger(s.start) || !Number.isInteger(s.end) || s.end <= s.start) errs.push(`${at}: bad frame range ${s.start}-${s.end}`);
    if (s.camera_move && !CAMERA_MOVES.includes(s.camera_move)) errs.push(`${at}: unknown camera_move "${s.camera_move}"`);
    if (s.transition && !TRANSITIONS.includes(s.transition)) errs.push(`${at}: unknown transition "${s.transition}"`);
    if (s.style !== undefined && !isStyleId(s.style)) errs.push(`${at}: unknown style "${s.style}"`);
    if (s.data === undefined && s.data_ref && !(s.data_ref in refs)) errs.push(`${at}: data_ref "${s.data_ref}" not found`);
    if (s.data === undefined && !s.data_ref && s.type !== "kinetic") errs.push(`${at}: ${s.type} scene needs data or data_ref`);
    if (i > 0 && s.start < scenes[i - 1].start) errs.push(`${at}: scenes must be ordered by start`);
  });
  return errs;
};

export const resolveData = (s: StudioScene, refs: Record<string, unknown>): unknown =>
  s.data !== undefined ? s.data : s.data_ref ? refs[s.data_ref] : undefined;

export const totalFrames = (scenes: StudioScene[]) => scenes.reduce((m, s) => Math.max(m, s.end), 0);

// Frames a scene's own sequence is extended after its end so the next scene can cross over it.
export const overlapAfter = (scenes: StudioScene[], i: number): number => {
  const next = scenes[i + 1];
  return next ? TRANSITION_FRAMES[next.transition ?? "cut"] : 0;
};

// 0..1 progress of the entering transition at a frame local to the incoming scene's start (cut => always 1).
export const transitionProgress = (kind: TransitionKind, localFrame: number): number => {
  const n = TRANSITION_FRAMES[kind];
  if (n === 0) return 1;
  const t = Math.min(1, Math.max(0, localFrame / n));
  return t * t * (3 - 2 * t); // smoothstep
};

// Camera move transform for progress p in 0..1 (art layer only, never text).
export const cameraTransform = (move: CameraMove | undefined, p: number): { scale: number; x: number; y: number } => {
  const e = p * p * (3 - 2 * p);
  switch (move) {
    case "push": return { scale: 1 + 0.09 * e, x: 0, y: 0 };
    case "pull": return { scale: 1.09 - 0.09 * e, x: 0, y: 0 };
    case "pan_left": return { scale: 1.07, x: 1.5 - 3 * e, y: 0 };   // x in % of width
    case "pan_right": return { scale: 1.07, x: -1.5 + 3 * e, y: 0 };
    default: return { scale: 1, x: 0, y: 0 };
  }
};
