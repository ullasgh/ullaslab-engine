import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import { PALETTES, TOPICS } from "../src/studio/palettes.ts";
import { SAFE_BOX, SIZES, studioLayout } from "../src/studio/layout.ts";
import { validateScenes, transitionProgress, cameraTransform, overlapAfter } from "../src/studio/scenes.ts";
import { counterValue, revealPoints, parseX } from "../src/studio/chartMath.ts";
import { sampleRoute, splitJumps, along } from "../src/studio/geoMath.ts";
import { cleanSourceName, stampText } from "../src/brand.ts";

const lum = (h) => {
  const [r, g, b] = [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16) / 255).map((c) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4));
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
};
const cr = (a, b) => { const [x, y] = [lum(a), lum(b)].sort((p, q) => q - p); return (x + 0.05) / (y + 0.05); };

test("five topic palettes, text colours readable", () => {
  assert.equal(TOPICS.length, 5);
  for (const t of TOPICS) {
    const p = PALETTES[t];
    for (const k of ["ink", "muted", "accent", "accent2", "accent3", "negative"]) assert.ok(cr(p[k], p.bg) >= 4.5, `${t}.${k} on bg`);
    for (const k of ["ink", "muted"]) assert.ok(cr(p[k], p.panel) >= 4.5, `${t}.${k} on panel`);
  }
});

test("safe boxes match config; vertical keeps bottom 20% and right 12% free", () => {
  const z = JSON.parse(fs.readFileSync(new URL("../../config/safe_zones.json", import.meta.url)));
  for (const o of ["vertical", "horizontal"]) {
    assert.equal(SAFE_BOX[o].top, z[o].top); assert.equal(SAFE_BOX[o].bottom, z[o].bottom); assert.equal(SAFE_BOX[o].left, z[o].sides);
    assert.equal(SIZES[o].w, z[o].width);
  }
  const L = studioLayout("vertical");
  assert.ok(L.h - L.y1 >= 0.2 * L.h);
  assert.ok(L.w - L.x1 >= 0.12 * L.w);
});

const S = (id, a, b, extra = {}) => ({ id, type: "kinetic", start: a, end: b, ...extra });
test("validateScenes", () => {
  assert.deepEqual(validateScenes([S("a", 0, 10), S("b", 10, 20)]), []);
  assert.ok(validateScenes([S("a", 0, 10), S("a", 10, 20)]).some((e) => /duplicate/.test(e)));
  assert.ok(validateScenes([S("a", 5, 5)]).some((e) => /frame range/.test(e)));
  assert.ok(validateScenes([S("a", 0, 5, { type: "chart", data_ref: "x" })], {}).some((e) => /not found/.test(e)));
  assert.ok(validateScenes([S("a", 0, 5, { type: "bogus" })]).some((e) => /unknown type/.test(e)));
  assert.ok(validateScenes([S("a", 0, 5, { transition: "glitch" })]).some((e) => /transition/.test(e)));
});

test("transitions and camera", () => {
  assert.equal(transitionProgress("cut", 0), 1);
  assert.equal(transitionProgress("crossfade", 0), 0);
  assert.equal(transitionProgress("crossfade", 99), 1);
  assert.equal(overlapAfter([S("a", 0, 10), S("b", 10, 20, { transition: "wipe" })], 0), 14);
  assert.equal(cameraTransform("none", 0.5).scale, 1);
  assert.ok(cameraTransform("push", 1).scale > 1);
});

test("chart math", () => {
  assert.equal(counterValue(0, 10, 0), 0);
  assert.equal(counterValue(0, 10, 1), 10);
  const pts = [{ x: 0, y: 0 }, { x: 10, y: 10 }, { x: 20, y: 0 }];
  assert.equal(revealPoints(pts, 1).length, 3);
  assert.deepEqual(revealPoints(pts, 0.25).at(-1), { x: 5, y: 5 });
  assert.equal(parseX("2024-03"), Date.parse("2024-03-01"));
});

test("geo math", () => {
  const r = sampleRoute([[0, 0], [90, 0]], 10);
  assert.equal(r.length, 11);
  assert.equal(splitJumps([[0, 0], [1, 0], [500, 0], [501, 0]], 100).length, 2);
  assert.deepEqual(along([[0, 0], [10, 10]], 0.5), [5, 5]);
});

test("source stamp never doubles the prefix", () => {
  assert.equal(cleanSourceName("Source: FRED"), "FRED");
  assert.equal(cleanSourceName("Source: Source: FRED"), "FRED");
  assert.equal(cleanSourceName("Fuente - INE"), "INE");
  assert.equal(stampText("en", "Source: FRED", "2026-11"), "Source: FRED · 2026-11");
  assert.equal(stampText("en", "FRED", "2026-11"), "Source: FRED · 2026-11");
});

import { fromDirectorScenes, normalizeScenes, outputFor } from "../src/studio/director.ts";
const dscene = (o) => ({ id: "s01", role: "hook", narration: { text: "x", start_s: 0, end_s: 2.5 }, visual_objective: "show the route", type: "map", palette: "trade", camera_move: "slow_push", transition: "match_cut", sfx: "none", rationale: "because reasons here", on_screen_text: null, data_ref: { kind: "chart", ref: "map_routes" }, ...o });
test("director scenes.json adapter", () => {
  const file = { schema_version: 1, item: "2026-11-09-x", outputs: [{ output: "long", aspect: "16:9", scenes: [dscene({}), dscene({ id: "s02", narration: { text: "y", start_s: 2.5, end_s: null }, camera_move: "pull_back", transition: "pattern_interrupt", on_screen_text: "Hi" }), dscene({ id: "s03", type: "footage", data_ref: null, illustrative: true, transition: "dip_to_black", camera_move: "orbit", narration: { text: "z" } })] }] };
  const out = fromDirectorScenes(outputFor(file, "16:9").scenes, 30);
  assert.equal(out[0].start, 0); assert.equal(out[0].end, 75);
  assert.equal(out[0].data_ref, "map_routes"); assert.equal(out[0].camera_move, "push"); assert.equal(out[0].transition, "match_move");
  assert.equal(out[1].start, 75); assert.equal(out[1].end, 165); assert.equal(out[1].camera_move, "pull"); assert.equal(out[1].transition, "cut"); assert.equal(out[1].on_screen_text, "Hi");
  assert.equal(out[2].start, 165); assert.equal(out[2].transition, "crossfade"); assert.deepEqual(out[2].data, { illustrative: true });
  assert.deepEqual(validateScenes(out, { map_routes: {} }), []);
  assert.deepEqual(normalizeScenes(out), out);
  assert.equal(outputFor(file, "9:16"), undefined);
});
