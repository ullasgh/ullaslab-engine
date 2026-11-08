import { C } from "./brand";

export type TemplateSpec = {
  id: string; format: number; name: string; accent: string;
  enter: "rise" | "slide" | "fade" | "flip" | "wipe";
  chartArea: boolean; chartDots: boolean;
  gridStyle: "cards" | "calendar" | "ticker";
  compareStyle: "lines" | "mirror";
  textStyle: "card" | "whiteboard" | "comment";
};

const base = { chartArea: false, chartDots: false, gridStyle: "cards", compareStyle: "lines", textStyle: "card" } as const;

// The 10 format templates of docs/formats.md. Each has its own motion, accent and layout choices;
// manifest.template names the sub-template (e.g. "annotated-bands") and is carried through for logging.
export const TEMPLATES: TemplateSpec[] = [
  { ...base, id: "chart-of-the-week", format: 1, name: "Chart of the Week", accent: C.primary, enter: "wipe", chartArea: true },
  { ...base, id: "macro-in-60s", format: 2, name: "Macro in 60s", accent: C.secondary, enter: "slide", gridStyle: "ticker" },
  { ...base, id: "bond-market-says", format: 3, name: "Bond Market Says", accent: C.accent, enter: "rise", chartDots: true },
  { ...base, id: "india-vs-us", format: 4, name: "India vs US Side-by-Side", accent: "#FF9F68", enter: "slide", compareStyle: "mirror" },
  { ...base, id: "week-ahead", format: 5, name: "Week-Ahead Calendar", accent: "#C4B5FD", enter: "fade", gridStyle: "calendar" },
  { ...base, id: "myth-vs-data", format: 6, name: "Myth vs Data", accent: C.negative, enter: "flip" },
  { ...base, id: "concept-explainer", format: 7, name: "Concept Explainer", accent: "#7EE2A8", enter: "rise", textStyle: "whiteboard" },
  { ...base, id: "commodity-cycle", format: 8, name: "Commodity Cycle", accent: "#E6B450", enter: "wipe", chartArea: true, gridStyle: "ticker" },
  { ...base, id: "fx-map", format: 9, name: "FX Map", accent: "#5EC4F0", enter: "fade", gridStyle: "calendar", chartDots: true },
  { ...base, id: "viewer-qa", format: 10, name: "Viewer Q&A", accent: "#F28BB8", enter: "rise", textStyle: "comment" },
];
