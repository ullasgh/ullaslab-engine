import React, { createContext, useContext } from "react";
import { interpolate, useCurrentFrame, useVideoConfig } from "remotion";
import { fontFor } from "../brand";
import { studioLayout, type Orientation, type Platform, type StudioLayout } from "./layout";
import { paletteFor, type Palette } from "./palettes";
import { cameraTransform, type CameraMove } from "./scenes";
import { presetFor, restrainCamera, type StyleId, type StylePreset } from "./styles";

export type StudioCtx = { L: StudioLayout; pal: Palette; lang: string; numberLocale: string; style?: StyleId; preset: StylePreset };
const Ctx = createContext<StudioCtx | null>(null);

export const StudioProvider: React.FC<{ orientation: Orientation; topic?: string; lang?: string; numberLocale?: string; reserveBottom?: number; platform?: Platform; style?: StyleId; children: React.ReactNode }> = ({
  orientation, topic, lang = "en", numberLocale = "en-US", reserveBottom = 0, platform = "both", style, children,
}) => <Ctx.Provider value={{ L: studioLayout(orientation, reserveBottom, platform, style), pal: paletteFor(topic), lang, numberLocale, style, preset: presetFor(style) }}>{children}</Ctx.Provider>;

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
  const { style } = useStudio();
  const c = restrainCamera(cameraTransform(move, f / Math.max(1, durationInFrames - 1)), style);
  return { transform: `translate(${c.x}%, ${c.y}%) scale(${c.scale})`, transformOrigin: "50% 50%" };
};
