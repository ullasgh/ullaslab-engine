import React, { createContext, useContext } from "react";
import { fontFor } from "../../brand";
import { useStudio } from "../context";
import { contentBox, type Box } from "./camera";
import { PTYPE, type PTypeScale } from "./tokens";
import type { LocalWord } from "./words";

/** The key element a scene hands to the next one in a shared-element morph: the figure and where it sits (scene-local px). */
export type Carry = { text: string; x: number; y: number; size: number; color: string };

export type PremiumCtx = {
  box: Box;                 // content rectangle (frame px): safe box inset for the camera range
  bw: number; bh: number;   // its size
  T: PTypeScale;
  font: string;
  dur: number;              // frames of the scene proper (the Sequence runs `overlap` frames longer)
  overlap: number;          // frames the next scene's transition crosses over this one
  words: LocalWord[];       // narration words, scene-local frames
  role?: string;
  index: number;
  carryIn: Carry | null;    // the previous scene's key figure when this scene is entered by a morph
  morphOut: boolean;        // the next scene's transition is a morph (hide the carried figure while it travels)
};

const Ctx = createContext<PremiumCtx | null>(null);

export const PremiumProvider: React.FC<{ dur: number; overlap: number; words: LocalWord[]; role?: string; index: number; carryIn: Carry | null; morphOut: boolean; children: React.ReactNode }> = ({ children, ...rest }) => {
  const { L, lang } = useStudio();
  const box = contentBox({ x0: L.x0, y0: L.y0, x1: L.x1, y1: L.y1 });
  return <Ctx.Provider value={{ box, bw: box.x1 - box.x0, bh: box.y1 - box.y0, T: PTYPE[L.o], font: fontFor(lang), ...rest }}>{children}</Ctx.Provider>;
};

export const usePremium = (): PremiumCtx => {
  const c = useContext(Ctx);
  if (!c) throw new Error("usePremium outside PremiumProvider");
  return c;
};
