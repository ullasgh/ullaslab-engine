import React, { createContext, useContext } from "react";
import { SAFE, TYPE } from "./brand";
import { Props } from "./types";

export type L = {
  w: number; h: number; x0: number; x1: number; y0: number; y1: number; cw: number;
  capH: number; contentTop: number; contentBottom: number; ch: number;
  type: { headline: number; body: number; label: number; caption: number };
  vertical: boolean;
};

export const computeLayout = (o: "vertical" | "horizontal"): L => {
  const s = SAFE[o];
  const type = TYPE[o];
  const capH = Math.round(type.caption * 1.3 * 2 + 40);  // two lines plus padding
  const x0 = s.sides, x1 = s.w - s.sides, y0 = s.top, y1 = s.h - s.bottom;
  const header = 60;
  const contentTop = y0 + header + 20, contentBottom = y1 - capH - 20;
  return { w: s.w, h: s.h, x0, x1, y0, y1, cw: x1 - x0, capH, contentTop, contentBottom, ch: contentBottom - contentTop, type, vertical: o === "vertical" };
};

export type Ctx = { p: Props; L: L; tpl: import("./templates").TemplateSpec };
export const CtxR = createContext<Ctx | null>(null);
export const useCtx = () => useContext(CtxR)!;
