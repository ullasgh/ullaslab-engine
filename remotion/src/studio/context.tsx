import React, { createContext, useContext } from "react";
import { interpolate, useCurrentFrame, useVideoConfig } from "remotion";
import { fontFor } from "../brand";
import { studioLayout, type Orientation, type StudioLayout } from "./layout";
import { paletteFor, type Palette } from "./palettes";
import { cameraTransform, type CameraMove } from "./scenes";

export type StudioCtx = { L: StudioLayout; pal: Palette; lang: string; numberLocale: string };
const Ctx = createContext<StudioCtx | null>(null);

export const StudioProvider: React.FC<{ orientation: Orientation; topic?: string; lang?: string; numberLocale?: string; reserveBottom?: number; children: React.ReactNode }> = ({
  orientation, topic, lang = "en", numberLocale = "en-US", reserveBottom = 0, children,
}) => <Ctx.Provider value={{ L: studioLayout(orientation, reserveBottom), pal: paletteFor(topic), lang, numberLocale }}>{children}</Ctx.Provider>;

export const useStudio = (): StudioCtx => {
  const c = useContext(Ctx);
  if (!c) throw new Error("useStudio outside StudioProvider");
  return c;
};

export const useFont = () => fontFor(useStudio().lang);

// Eased 0..1 over [from, to] frames (clamped).
export const useRamp = (from: number, to: number) => {
  const f = useCurrentFrame();
  const x = interpolate(f, [from, to], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  return x * x * (3 - 2 * x);
};

// Camera transform style for the art layer of the current scene.
export const useCameraStyle = (move: CameraMove | undefined): React.CSSProperties => {
  const f = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();
  const c = cameraTransform(move, f / Math.max(1, durationInFrames - 1));
  return { transform: `translate(${c.x}%, ${c.y}%) scale(${c.scale})`, transformOrigin: "50% 50%" };
};
