// Content camera. The art layer AND the content move, bounded so content never leaves the safe box.
import type { CameraMove } from "../scenes.ts";

/** Hard bounds of any camera pose: scale about the content centre and a translation in px. */
export const CAM = { maxScale: 1.05, maxShift: 14 } as const;

export type Pose = { scale: number; x: number; y: number };   // x, y in px

export type Box = { x0: number; y0: number; x1: number; y1: number };

/** The rectangle premium content is laid out in: the safe content box inset so that the whole camera range (scale up to
 *  CAM.maxScale about the box centre plus CAM.maxShift of drift) still lands inside the safe box at every frame. */
export const contentBox = (safe: Box): Box => {
  const cx = (safe.x0 + safe.x1) / 2, cy = (safe.y0 + safe.y1) / 2;
  const hw = ((safe.x1 - safe.x0) / 2 - CAM.maxShift) / CAM.maxScale;
  const hh = ((safe.y1 - safe.y0) / 2 - CAM.maxShift) / CAM.maxScale;
  return { x0: cx - hw, x1: cx + hw, y0: cy - hh, y1: cy + hh };
};

/** True when a camera pose keeps every point of `inner` inside `outer` (the invariant the tests assert for all p). */
export const poseKeepsInside = (inner: Box, outer: Box, pose: Pose): boolean => {
  const cx = (outer.x0 + outer.x1) / 2, cy = (outer.y0 + outer.y1) / 2;   // camera origin = centre of the safe box
  const m = (v: number, c: number, t: number) => c + (v - c) * pose.scale + t;
  return m(inner.x0, cx, pose.x) >= outer.x0 - 0.01 && m(inner.x1, cx, pose.x) <= outer.x1 + 0.01
    && m(inner.y0, cy, pose.y) >= outer.y0 - 0.01 && m(inner.y1, cy, pose.y) <= outer.y1 + 0.01;
};

const smooth = (p: number) => p * p * (3 - 2 * p);

/** Content pose at progress p (0..1) of the scene. Every move ends inside CAM. "none" still drifts a little: a held frame
 *  must keep living (plan: the frame around a landed number keeps moving). `dir` alternates the drift side by scene. */
export const contentPose = (move: CameraMove | undefined, p: number, dir = 1): Pose => {
  const e = smooth(Math.min(1, Math.max(0, p)));
  switch (move) {
    case "push": return { scale: 1 + (CAM.maxScale - 1) * e, x: 0, y: -CAM.maxShift * 0.5 * e };
    case "pull": return { scale: CAM.maxScale - (CAM.maxScale - 1) * e, x: 0, y: CAM.maxShift * 0.5 * (1 - e) };
    case "pan_left": return { scale: 1.03, x: CAM.maxShift * (1 - 2 * e), y: 0 };
    case "pan_right": return { scale: 1.03, x: CAM.maxShift * (-1 + 2 * e), y: 0 };
    default: return { scale: 1 + 0.02 * e, x: dir * CAM.maxShift * 0.6 * (e - 0.5), y: -CAM.maxShift * 0.35 * e };
  }
};

/** Background pose: the same move at a different depth (parallax). depth 0 = fixed to the frame, 1 = moves with the content. */
export const layerPose = (pose: Pose, depth: number): Pose => ({
  scale: 1 + (pose.scale - 1) * depth * 1.6, x: pose.x * depth * 2.2, y: pose.y * depth * 2.2,
});

/** Default move per scene role when the director left it "static" (the planner default means "none", which reads as a slide). */
export const ROLE_MOVE: Record<string, CameraMove> = {
  hook: "push", setup: "pan_right", evidence: "push", mechanism: "pan_left", consequence: "pull", payoff: "push", interrupt: "push",
  cta: "none", disclaimer: "none",
};
export const moveFor = (move: CameraMove | undefined, role: string | undefined, index: number): CameraMove => {
  if (move && move !== "none") return move;
  const r = role ? ROLE_MOVE[role] : undefined;
  return r ?? (index % 2 ? "pan_left" : "push");
};
