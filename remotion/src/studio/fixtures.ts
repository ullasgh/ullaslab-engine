// Fixture data for StudioDemo. Values are synthetic layout-test numbers, not market data; every data scene says so.
import type { ChartMeta } from "./Stamp";
import type { StudioScene } from "./scenes";
import type { GlobeData, MapData } from "./geo";
import type { ChartSceneData } from "./SceneRenderer";
import type { TimelineData, FlowData } from "./Diagrams";
import type { FootageData } from "./Footage";

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
    highlights: [{ id: "356", color: "accent2", label: { text: "India", at: [79, 22], anchor: "middle", delay: 30, dot: false } }, { id: "682", color: "accent", label: { text: "Saudi Arabia", at: [41, 17], anchor: "middle", delay: 24, dot: false, vertical: { text: "Saudi", at: [44, 19.5], anchor: "start" } } }],
    routes: [
      { id: "gulf-india", points: [[50.1, 26.6], [56.5, 26.4], [60.5, 23.5], [72.8, 19]], color: "accent2", delay: 10, duration: 60, markers: 2 },
      { id: "asia-europe", points: [[103.8, 1.3], [79.8, 6.9], [43.3, 12.6], [32.5, 29.9], [14, 36], [4.4, 51.9]], color: "accent", delay: 28, duration: 90, markers: 3 },
    ],
    labels: [
      { text: "Hormuz", at: [56.5, 26.4], dx: 16, dy: -16, delay: 36, color: "accent2" },
      { text: "Suez", at: [32.5, 29.9], dx: -16, dy: -16, anchor: "end", delay: 60 },
      { text: "Singapore", at: [103.8, 1.3], dx: -16, dy: 44, anchor: "end", delay: 40 },
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
