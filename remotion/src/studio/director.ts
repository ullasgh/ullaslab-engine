// Adapter from the director's scenes.json (content repo schemas/scenes.schema.json v1) to the kit's StudioScene.
// Pure, no React. SceneRenderer accepts either shape; normalizeScenes is idempotent.
import type { Topic } from "./palettes";
import type { CameraMove, StudioScene, TransitionKind } from "./scenes";

export type DirectorScene = {
  id: string; role?: string;
  narration: { text: string; start_s?: number | null; end_s?: number | null };
  type: StudioScene["type"]; palette: Topic;
  camera_move: string; transition: string;
  on_screen_text?: string | null; illustrative?: boolean;
  data_ref?: { kind: "chart" | "data_point" | "ledger"; ref: string } | null;
  [k: string]: unknown;
};
export type DirectorOutput = { output: "long" | "short" | "reel"; aspect: "16:9" | "9:16"; scenes: DirectorScene[] };
export type DirectorFile = { schema_version: 1; item: string; outputs: DirectorOutput[] };

export const CAMERA_MAP: Record<string, CameraMove> = {
  static: "none", slow_push: "push", pull_back: "pull", pan_left: "pan_left", pan_right: "pan_right",
  tilt_up: "push", orbit: "pan_right", zoom_to_region: "push",
};
export const TRANSITION_MAP: Record<string, TransitionKind> = {
  cut: "cut", crossfade: "crossfade", wipe: "wipe", match_cut: "match_move",
  push: "match_move", dip_to_black: "crossfade", pattern_interrupt: "cut",
};

export const isDirectorScene = (s: unknown): s is DirectorScene => !!s && typeof s === "object" && "narration" in (s as object);

export const fromDirectorScenes = (scenes: DirectorScene[], fps = 30, fallbackSeconds = 3): StudioScene[] => {
  let cursor = 0;
  return scenes.map((d) => {
    const a = d.narration.start_s, b = d.narration.end_s;
    const start = typeof a === "number" ? Math.round(a * fps) : cursor;
    const end = typeof b === "number" ? Math.max(start + 1, Math.round(b * fps)) : start + Math.round(fallbackSeconds * fps);
    cursor = end;
    const out: StudioScene = {
      id: d.id, type: d.type, start, end, palette: d.palette,
      camera_move: CAMERA_MAP[d.camera_move] ?? "none", transition: TRANSITION_MAP[d.transition] ?? "cut",
    };
    if (d.on_screen_text) out.on_screen_text = d.on_screen_text;
    if (d.data_ref?.ref) out.data_ref = d.data_ref.ref;
    else if (d.type === "footage") out.data = { illustrative: d.illustrative !== false };
    return out;
  });
};

export const outputFor = (file: DirectorFile, aspect: "16:9" | "9:16", which?: string): DirectorOutput | undefined =>
  file.outputs.find((o) => o.aspect === aspect && (!which || o.output === which));

export const normalizeScenes = (scenes: (StudioScene | DirectorScene)[], fps = 30): StudioScene[] =>
  scenes.length && isDirectorScene(scenes[0]) ? fromDirectorScenes(scenes as DirectorScene[], fps) : (scenes as StudioScene[]);
