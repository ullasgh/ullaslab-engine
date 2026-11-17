// Fixture data for StudioDemo. Values are synthetic layout-test numbers, not market data; every data scene says so.
import type { ChartMeta } from "./Stamp";
import type { StudioScene } from "./scenes";
import type { GlobeData, MapData } from "./geo";
import type { ChartSceneData } from "./SceneRenderer";
import type { TimelineData, FlowData } from "./Diagrams";
import type { FootageData } from "./Footage";
import type { StyleId } from "./styles";

const FIXTURE_SOURCE = { name: "UllasLab fixture (synthetic, not real figures)", as_of: "2026-11" };
const meta = (metric: string, unit: string, period: string): ChartMeta => ({
  metric, unit, period, source: FIXTURE_SOURCE, freshness: "INFERRED", caveat: "Demo values for layout testing only.",
});

const months = (start: number, n: number) => Array.from({ length: n }, (_, i) => {
  const m = start * 12 + i;
  return `${Math.floor(m / 12)}-${String((m % 12) + 1).padStart(2, "0")}`;
});
const wave = (n: number, base: number, amp: number, phase: number, drift: number) =>
  Array.from({ length: n }, (_, i) => +(base + drift * (i / n) + amp * Math.sin(i / 7 + phase) + (amp / 3) * Math.sin(i / 2.3 + phase)).toFixed(2));

const xs = months(2021, 60);
const MAP_META = { source: { name: "Natural Earth (public domain); lanes illustrative", as_of: "2026-11" }, freshness: "INFERRED" as const, caveat: "Illustrative lanes, not live vessel data." };

export const DEMO_REFS: Record<string, unknown> = {
  line_rates: {
    kind: "line", meta: meta("Policy rate vs inflation", "% per year", "Jan 2021 - Dec 2025"), decimals: 1,
    series: [
      { name: "Policy rate", points: xs.map((x, i) => ({ x, y: wave(60, 2.2, 0.35, 0, 3.4)[i] })) },
      { name: "Inflation", color: "accent2", points: xs.map((x, i) => ({ x, y: wave(60, 3.4, 0.9, 1.2, 1.4)[i] })) },
    ],
    annotations: [{ x: "2022-09", label: "Tightening" }, { x: "2024-04", label: "Plateau" }],
  } satisfies ChartSceneData,
  bar_lanes: {
    kind: "bar", meta: meta("Relative lane traffic index", "index, 100 = lane A", "Q3 2026"), decimals: 0,
    bars: [{ label: "Gulf to India", value: 100, highlight: true }, { label: "Asia to Europe", value: 86 }, { label: "Pacific", value: 71 }, { label: "Atlantic", value: 54 }, { label: "Intra-Asia", value: 39 }],
  } satisfies ChartSceneData,
  yield_curve: {
    kind: "yield", meta: meta("Government bond yield curve", "% per year", "snapshot, Nov 2026"), tenors: ["3M", "2Y", "5Y", "10Y", "30Y"],
    now: [4.9, 4.4, 4.2, 4.3, 4.6], nowLabel: "Now", prior: [5.3, 5.0, 4.6, 4.5, 4.6], priorLabel: "A year ago",
  } satisfies ChartSceneData,
  counter_cpi: {
    kind: "counter", meta: meta("Headline consumer inflation", "% year on year", "Oct 2026"), value: 6.4, decimals: 1, suffix: "%",
    delta: { text: "+0.3 pts vs prior month", tone: "up" }, spark: wave(30, 5.6, 0.5, 0.4, 0.8),
  } satisfies ChartSceneData,
  map_routes: {
    meta: MAP_META, focus: { center: [62, 24], zoom: 1.75 }, focusVertical: { center: [52, 15], zoom: 2.7 },
    highlights: [{ id: "356", color: "accent2", label: { text: "India", at: [79, 22], anchor: "middle", delay: 30, dot: false } }, { id: "682", color: "accent", label: { text: "Saudi Arabia", at: [43, 17], anchor: "start", delay: 24, dot: false, vertical: { at: [42.5, 16.3] } } }],
    routes: [
      { id: "gulf-india", points: [[50.1, 26.6], [52, 26.9], [56.3, 26.5], [58.5, 24.5], [64, 21.5], [72.8, 19]], color: "accent2", delay: 10, duration: 60, markers: 2 },
      { id: "asia-europe", points: [[103.8, 1.4], [98, 5.5], [80, 5.5], [60, 12], [45, 12.5], [43.3, 12.6], [41.8, 15], [39.8, 19], [37, 22.5], [35.2, 26.3], [33.6, 28.6], [32.6, 30], [29, 33.5], [18, 36], [5, 37], [-5.5, 36], [-9, 38.5], [-5, 48.5], [4.4, 51.9]], color: "accent", delay: 28, duration: 90, markers: 3 },
    ],
    labels: [
      { text: "Hormuz", at: [56.3, 26.5], dx: 14, dy: -14, delay: 36, color: "accent2" },
      { text: "Suez", at: [32.5, 30], dx: -16, dy: -12, anchor: "end", delay: 60 },
      { text: "Singapore", at: [103.8, 1.4], dx: -16, dy: 44, anchor: "end", delay: 40 },
    ],
  } satisfies MapData,
  globe_arcs: {
    meta: { ...MAP_META, caveat: "Illustrative arcs, not live trade data." }, lon0: 20, lonSpeed: 0.5, lat: 18,
    highlights: [{ id: "356", color: "accent2" }],
    routes: [
      { id: "a", points: [[50.1, 26.6], [72.8, 19]], color: "accent2", delay: 8, duration: 50, markers: 1 },
      { id: "b", points: [[72.8, 19], [103.8, 1.3]], color: "accent", delay: 22, duration: 50, markers: 1 },
      { id: "c", points: [[50.1, 26.6], [4.4, 51.9]], color: "accent3", delay: 36, duration: 60, markers: 1 },
    ],
    labels: [{ text: "Mumbai", at: [72.8, 19], dx: 14, dy: 40, delay: 24, color: "accent2" }, { text: "Gulf", at: [50.1, 26.6], dx: -14, dy: -14, anchor: "end", delay: 14 }],
  } satisfies GlobeData,
  timeline: {
    meta: meta("Policy sequence", "events", "2022 - 2026"),
    events: [
      { when: "2022", title: "Tightening begins" }, { when: "2023", title: "Rate peak" }, { when: "2024", title: "First pause" },
      { when: "2025", title: "Curve steepens" }, { when: "2026", title: "Easing debate" },
    ],
  } satisfies TimelineData,
  flow: {
    meta: meta("Transmission channel", "qualitative", "illustrative"),
    nodes: [
      { id: "a", label: "Oil price rises", level: 0, tone: "accent2" }, { id: "b", label: "Import bill grows", level: 1 }, { id: "c", label: "Inflation expectations", level: 1, tone: "accent3" },
      { id: "d", label: "Currency pressure", level: 2 }, { id: "e", label: "Policy response", level: 3, tone: "accent2" },
    ],
    edges: [{ from: "a", to: "b" }, { from: "a", to: "c" }, { from: "b", to: "d" }, { from: "c", to: "d" }, { from: "d", to: "e" }],
  } satisfies FlowData,
  footage_plate: {
    credit: "Placeholder plate (fixture), no external footage", illustrative: true,
    lower_third: { title: "Why rates matter", subtitle: "Policy desk explainer" },
  } satisfies FootageData,
};

const L = 90;
const seq = (type: StudioScene["type"], id: string, i: number, extra: Partial<StudioScene>): StudioScene => ({ id, type, start: i * L, end: (i + 1) * L, ...extra });
export const DEMO_SCENES: StudioScene[] = [
  seq("footage", "s1-footage", 0, { on_screen_text: "Rates set the price of time", data_ref: "footage_plate", palette: "policy", camera_move: "push", transition: "cut" }),
  seq("map", "s2-map", 1, { on_screen_text: "Where the cargo moves", data_ref: "map_routes", palette: "trade", camera_move: "push", transition: "crossfade" }),
  seq("globe", "s3-globe", 2, { on_screen_text: "One shock, many ports", data_ref: "globe_arcs", palette: "commodities", camera_move: "none", transition: "wipe" }),
  seq("chart", "s4-line", 3, { on_screen_text: "Rates chase inflation", data_ref: "line_rates", palette: "policy", camera_move: "pull", transition: "match_move" }),
  seq("chart", "s5-bar", 4, { on_screen_text: "Which lanes carry the load", data_ref: "bar_lanes", palette: "commodities", transition: "crossfade" }),
  seq("chart", "s6-yield", 5, { on_screen_text: "The curve, then and now", data_ref: "yield_curve", palette: "policy", transition: "cut" }),
  seq("chart", "s7-counter", 6, { on_screen_text: "The number to watch", data_ref: "counter_cpi", palette: "volatility", camera_move: "push", transition: "crossfade" }),
  seq("timeline", "s8-timeline", 7, { on_screen_text: "How we got here", data_ref: "timeline", palette: "tech", transition: "wipe" }),
  seq("flow", "s9-flow", 8, { on_screen_text: "How a shock travels", data_ref: "flow", palette: "trade", transition: "crossfade" }),
  seq("kinetic", "s10-kinetic", 9, { on_screen_text: "Rates don't move *markets*|they move *expectations*", palette: "volatility", camera_move: "push", transition: "match_move" }),
];

// ---- style demos (V2 M2). Layout-test numbers only, same synthetic fixture source as above. One signature scene first.
const scenario = DEMO_REFS.line_rates as Extract<ChartSceneData, { kind: "line" }>;
export const STYLE_DEMO_REFS: Record<string, unknown> = {
  ...DEMO_REFS,
  line_scenario: {
    ...scenario, meta: meta("Policy rate vs inflation, scenario range", "% per year", "Jan 2021 - Dec 2025"),
    band: { lo: 3, hi: 5, label: "Scenario range", from: "2024-07" },
    annotations: [{ x: "2022-09", label: "Tightening" }],
  } satisfies ChartSceneData,
};
// premium demo: a chart sequence (two views of one series), a converging relationship diagram and a number reveal. Fixture values only.
const premiumPts = Array.from({ length: 24 }, (_, i) => ({ x: `2026-10-${String(i + 1).padStart(2, "0")}`, y: +(4.2 + 0.06 * i - 0.5 * Math.sin(i / 3.2)).toFixed(2) }));
STYLE_DEMO_REFS.line_sequence = {
  kind: "line",
  meta: { ...meta("Demo yield", "Percent", "1 Oct to 24 Oct 2026"), caveat: undefined }, decimals: 2,
  series: [{ name: "Demo", points: premiumPts }],
  views: [
    { window: { from: "2026-10-01", to: "2026-10-16" }, marks: [{ x: "2026-10-09", label: "High", value: premiumPts[8].y }], point: { x: "2026-10-16", label: "Latest", value: premiumPts[15].y } },
    { window: { from: "2026-10-09", to: "2026-10-24" }, highlight: { from: "2026-10-16", to: "2026-10-24", label: "Last week" }, point: { x: "2026-10-24", label: "Latest", value: premiumPts[23].y } },
  ],
};
STYLE_DEMO_REFS.flow_converge = {
  meta: meta("Demo relationship", "no scale", "illustration"),
  nodes: [{ id: "a", label: "Firm supply", level: 0 }, { id: "b", label: "Sticky inflation", level: 0 }, { id: "c", label: "Longer yields pay more", level: 1, tone: "accent2" }],
  edges: [{ from: "a", to: "c" }, { from: "b", to: "c", label: "if both hold" }],
} satisfies FlowData;
const row = (style: StyleId, specs: Partial<StudioScene>[]): StudioScene[] =>
  specs.map((x, i) => ({ id: `${style}-${i + 1}`, type: "kinetic", start: i * L, end: (i + 1) * L, palette: "policy", camera_move: "push", transition: i ? "crossfade" : "cut", ...x }) as StudioScene);
export const STYLE_DEMO_SCENES: Record<StyleId, StudioScene[]> = {
  "data-story": row("data-story", [
    { type: "chart", data_ref: "line_scenario", on_screen_text: "Where rates could settle" },
    { type: "chart", data_ref: "bar_lanes", on_screen_text: "Which lanes carry the load", palette: "commodities" },
    { type: "timeline", data_ref: "timeline", on_screen_text: "How we got here", palette: "tech" },
  ]),
  "creator-motion": row("creator-motion", [
    { on_screen_text: "Inflation hit *6.4%*|and rates held at *4.5%*" },
    { on_screen_text: "A *$85* barrel|moves more than you think", palette: "commodities" },
    { type: "chart", data_ref: "counter_cpi", on_screen_text: "The number to watch", palette: "volatility" },
  ]),
  "chalk-talk": row("chalk-talk", [
    { on_screen_text: "Principal: 100|Rate: 5%|100 x 0.05|= Interest: 5" },
    { on_screen_text: "Real rate = nominal - inflation|4.5% - 3.0%|= 1.5%" },
    { type: "chart", data_ref: "line_rates", on_screen_text: "Rates chase inflation" },
  ]),
  premium: row("premium", [
    { type: "chart", data_ref: "line_sequence", on_screen_text: "Two views, one line", camera_move: "none" },
    { type: "flow", data_ref: "flow_converge", on_screen_text: "Two forces, one result", camera_move: "none", transition: "sweep" },
    { on_screen_text: "A yield of *4.7%*", camera_move: "none", transition: "push_through" },
  ]),
  "clean-tech": row("clean-tech", [
    { on_screen_text: "Oil: the price rises|Imports: the bill grows|Currency: pressure builds|Policy: the response" },
    { type: "flow", data_ref: "flow", on_screen_text: "How a shock travels", palette: "trade" },
    { type: "timeline", data_ref: "timeline", on_screen_text: "How we got here", palette: "tech" },
  ]),
};
export const STYLE_DEMO_CUE = { start: 0, end: 9, lines: [[{ w: "Inflation", start: 0, end: 1 }, { w: "reached", start: 1, end: 2 }, { w: "6.4", start: 2, end: 3 }, { w: "%", start: 3, end: 3.5 }, { w: "in", start: 3.5, end: 4 }, { w: "October", start: 4, end: 5 }]] };
