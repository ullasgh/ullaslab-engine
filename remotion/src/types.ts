export type I18n = string | Record<string, string>;
export type Tag = "LIVE" | "RECENT" | "LAGGED" | "EXPECTATION" | "INFERRED";
export type Point = { x: string | number; y: number };
export type Series = { name: I18n; color?: "primary" | "secondary" | "accent" | "muted"; points: Point[] };
export type Chart = {
  type: "line" | "bar" | "compare" | "delta" | "counter";
  title: I18n; unit?: string; decimals?: number; series?: Series[]; value?: number; prior?: number; label?: I18n;
  annotations?: { x: string | number; label: I18n }[];
  source: { name: string; url?: string; as_of: string };
  freshness: Tag; claim_id?: string; chart_hash?: string;
};
export type Item = { label: I18n; value?: string; tag?: Tag };
export type Scene = {
  id: string; kind: "hook" | "chart" | "counter" | "compare" | "text" | "grid" | "myth" | "qa" | "disclaimer";
  segments?: string[]; chart_data?: Chart; headline?: I18n; body?: I18n; items?: Item[];
};
export type TlScene = { id: string; kind: string; start: number; end: number; beats: number[] };
export type Cue = { start: number; end: number; lines: string[] };
export type Props = {
  lang: string; orientation: "vertical" | "horizontal"; format: number; template: string; hookStyle: string;
  disclaimer?: I18n; scenes: Scene[]; timeline: { total_s: number; scenes: TlScene[] };
  cues: Cue[]; audio: string; numberLocale: string; rtl: boolean; audit?: boolean;
};
