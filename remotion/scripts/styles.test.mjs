import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import {
  STYLE_IDS, PRESETS, NEUTRAL, presetFor, resolveStyle, styledType, restrainCamera, isStyledType, isStyleId,
  parseNumberToken, countedText, mergeNotation, parseSteps, parseCards, wobble, sketchRect, sketchLine, fitSize,
} from "../src/studio/styles.ts";
import { PALETTES, BASE, STUDIO_TYPE } from "../src/studio/palettes.ts";
import { studioLayout } from "../src/studio/layout.ts";
import { validateScenes, cameraTransform } from "../src/studio/scenes.ts";
import { fromDirectorScenes } from "../src/studio/director.ts";
import { niceExtent, domainCoversData, plotValues } from "../src/studio/chartMath.ts";

const SRC = (f) => fs.readFileSync(new URL(`../src/studio/${f}`, import.meta.url), "utf8");

test("four presets, ids match the scenes.json schema enum and the Python side", () => {
  assert.deepEqual([...STYLE_IDS], ["data-story", "creator-motion", "chalk-talk", "clean-tech"]);
  for (const id of STYLE_IDS) assert.equal(PRESETS[id].id, id);
  const py = fs.readFileSync(new URL("../../src/ullaslab_engine/studio/assemble.py", import.meta.url), "utf8");
  const m = /^STYLES = \(([^)]*)\)/m.exec(py);
  assert.deepEqual(m[1].split(",").map((s) => s.trim().replace(/"/g, "")), [...STYLE_IDS]);
});

test("style resolution: scene wins, then item, then none; unknown values fall back", () => {
  assert.equal(resolveStyle("data-story", "chalk-talk"), "chalk-talk");
  assert.equal(resolveStyle("data-story", undefined), "data-story");
  assert.equal(resolveStyle(undefined, "clean-tech"), "clean-tech");
  assert.equal(resolveStyle(undefined, undefined), undefined);
  assert.equal(resolveStyle("hologram", "nope"), undefined);
  assert.equal(resolveStyle("clean-tech", "nope"), "clean-tech");
  assert.equal(isStyleId("chalk-talk"), true); assert.equal(isStyleId(""), false); assert.equal(isStyleId(null), false);
});

test("absent style is the pre-M2 look", () => {
  assert.equal(presetFor(undefined), NEUTRAL);
  for (const o of ["horizontal", "vertical"]) {
    assert.deepEqual(styledType(o, undefined), STUDIO_TYPE[o]);
    assert.deepEqual(studioLayout(o).type, STUDIO_TYPE[o]);
  }
  assert.deepEqual(restrainCamera({ scale: 1.09, x: 1, y: 0 }, undefined), { scale: 1.09, x: 1, y: 0 });
  assert.equal(NEUTRAL.layout.backdrop, "grid");
  assert.equal(NEUTRAL.captions.emphasiseNumbers, false); assert.equal(NEUTRAL.captions.mergeNotation, false);
});

test("styled type scale never drops below the A5 floors; only creator-motion enlarges", () => {
  for (const id of STYLE_IDS) for (const o of ["horizontal", "vertical"]) {
    const t = styledType(o, id), b = STUDIO_TYPE[o];
    assert.ok(t.body >= 44 && t.label >= 36 && t.stamp >= 36, `${id} ${o} floors`);
    assert.ok(t.number >= b.number && t.display >= b.display && t.headline >= b.headline, `${id} ${o} never smaller`);
    assert.equal(t.label, b.label); assert.equal(t.stamp, b.stamp); assert.equal(t.body, b.body);
    assert.deepEqual(studioLayout(o, 0, "both", id).type, t);
  }
  assert.ok(styledType("vertical", "creator-motion").display > STUDIO_TYPE.vertical.display);
  assert.deepEqual(styledType("vertical", "chalk-talk"), STUDIO_TYPE.vertical);
});

test("safe box and caption reserve are identical under every style", () => {
  for (const o of ["horizontal", "vertical"]) for (const id of STYLE_IDS) {
    const a = studioLayout(o, 176), b = studioLayout(o, 176, "both", id);
    for (const k of ["x0", "x1", "y0", "y1", "cw", "ch", "w", "h"]) assert.equal(a[k], b[k], `${id} ${o} ${k}`);
  }
});

test("camera is restrained under styles, off for chalk-talk", () => {
  const c = cameraTransform("push", 1);
  const base = restrainCamera(c, undefined);
  for (const id of STYLE_IDS) assert.ok(Math.abs(restrainCamera(c, id).scale - 1) <= Math.abs(base.scale - 1) + 1e-9, id);
  assert.deepEqual(restrainCamera(c, "chalk-talk"), { scale: 1, x: 0, y: 0 });
  assert.ok(restrainCamera(c, "creator-motion").scale < base.scale);
});

test("presets use only brand-palette colours: no colour literals in style code", () => {
  const hex = /#[0-9a-fA-F]{3,8}\b/g;
  for (const f of ["styles.ts", "StyleKit.tsx", "Backdrop.tsx"]) {
    const found = SRC(f).replace(/\$\{pal\.\w+\}[0-9a-fA-F]{2}/g, "").match(hex) ?? [];
    assert.deepEqual(found, [], `${f} has colour literals ${found}`);
  }
  for (const k of Object.keys(PALETTES)) assert.equal(PALETTES[k].bg, BASE.bg);
});

test("no freshness tag word and no banned audience word can reach the screen from style code", () => {
  for (const f of ["styles.ts", "StyleKit.tsx", "Backdrop.tsx", "SceneRenderer.tsx", "StudioCaptions.tsx"]) {
    const src = SRC(f);
    assert.ok(!/\b(LIVE|RECENT|LAGGED|EXPECTATION|INFERRED)\b/.test(src), `${f} mentions a freshness tag`);
    assert.ok(!/macro/i.test(src), `${f} contains the banned audience word`);
  }
});

test("animated counters end on the written token verbatim and never overshoot", () => {
  for (const raw of ["6.4%", "$85", "1,200", "4.50%", "12x", "€3.2bn", "250bps", "7."]) {
    const t = parseNumberToken(raw);
    assert.ok(t, raw);
    assert.equal(countedText(t, 1), raw, raw);
    assert.equal(countedText(t, 2), raw);
    let last = -1;
    for (let p = 0; p < 1; p += 0.05) {
      const v = Number(countedText(t, p).replace(/[^0-9.]/g, "") || 0);
      assert.ok(v <= t.value + 1e-9, `${raw} overshoots at ${p}`);
      assert.ok(v >= last - 1e-9, `${raw} not monotonic`); last = v;
    }
    assert.equal(countedText(t, 0).replace(/[0.,]/g, "").replace(/^[$€£₹]/, "").includes("1"), false);
  }
  assert.equal(countedText(parseNumberToken("6.4%"), 0), "0.0%");     // decimals and notation are kept while counting
  assert.equal(countedText(parseNumberToken("$85"), 0), "$0");
  for (const raw of ["abc", "4.5.6", "1e5", "five", "10-year", "1,2", "%"]) assert.equal(parseNumberToken(raw), null, raw);
});

test("caption notation: stand-alone % and currency signs are re-attached, words pass through", () => {
  const w = (s, a, b) => ({ w: s, start: a, end: b });
  const out = mergeNotation([w("rose", 0, 1), w("4.5", 1, 1.5), w("%", 1.5, 1.8), w("to", 1.8, 2), w("$", 2, 2.1), w("85", 2.1, 2.5), w("a", 2.5, 2.6), w("barrel", 2.6, 3)]);
  assert.deepEqual(out.map((x) => x.w), ["rose", "4.5%", "to", "$85", "a", "barrel"]);
  assert.equal(out[1].start, 1); assert.equal(out[1].end, 1.8);
  assert.equal(out[3].start, 2); assert.equal(out[3].end, 2.5);
  const input = [w("%", 0, 1), w("$", 1, 2)];               // nothing to attach to: unchanged
  assert.deepEqual(mergeNotation(input).map((x) => x.w), ["%", "$"]);
  const src = [w("4.5", 0, 1), w("%", 1, 2)];
  mergeNotation(src); assert.equal(src[0].w, "4.5");        // input not mutated
});

test("markup parsers: chalk steps, result line and clean-tech cards", () => {
  assert.deepEqual(parseSteps("Price = 100 | x 5% | = Interest 5"), [{ text: "Price = 100", result: false }, { text: "x 5%", result: false }, { text: "Interest 5", result: true }]);
  assert.deepEqual(parseSteps(" | a | "), [{ text: "a", result: false }]);
  assert.deepEqual(parseCards("Oil: costs more|Currency|Policy: responds"), [{ title: "Oil", detail: "costs more" }, { title: "Currency" }, { title: "Policy", detail: "responds" }]);
  assert.deepEqual(parseCards("Ratio 3:"), [{ title: "Ratio 3:" }]);
});

test("hand-drawn strokes are deterministic and stay near the true edge", () => {
  assert.equal(wobble(3, 4, 2), wobble(3, 4, 2));
  for (let i = 0; i < 50; i++) assert.ok(Math.abs(wobble(7, i, 3)) <= 3);
  assert.equal(sketchRect(300, 80, 2, 3), sketchRect(300, 80, 2, 3));
  assert.notEqual(sketchRect(300, 80, 2, 3), sketchRect(300, 80, 5, 3));
  for (const n of sketchRect(300, 80, 2, 3).match(/-?\d+\.\d/g).map(Number)) assert.ok(n >= -3.1 && n <= 303.1);
  assert.ok(sketchLine(200, 1).startsWith("M "));
});

test("text fitting shrinks to fit and respects the minimum", () => {
  assert.equal(fitSize(["Short"], 800, 800, 120, 40), 120);
  const long = ["A fairly long line of text that must wrap over several rows in a narrow column"];
  const s = fitSize(long, 600, 500, 120, 40);
  assert.ok(s < 120 && s >= 40);
  assert.ok(Math.ceil(long[0].length * 0.56 * s / 600) * s * 1.12 <= 500 || s === 40);
  assert.equal(fitSize([long[0].repeat(8)], 300, 100, 120, 44), 44);
});

test("honest axes: the domain always covers every plotted number, and zero for zero-baseline styles", () => {
  const cases = [[4.2, 4.6, 4.4], [-3, 2, 9], [100, 100, 100], [0.01, 0.02], [1200, 1850, 990]];
  for (const vals of cases) {
    for (const zero of [false, true]) {
      const d = niceExtent(vals, 0.1, zero);
      assert.ok(domainCoversData(d, vals, zero), `${vals} zero=${zero} -> ${d}`);
    }
  }
  assert.equal(domainCoversData([4, 5], [3, 4.5]), false);
  assert.equal(domainCoversData([1, 5], [2, 3], true), false);
  const series = [{ points: [{ y: 2.1 }, { y: 3.4 }] }];
  assert.deepEqual(plotValues(series, { lo: 1.5, hi: 4.9, label: "range" }).sort(), [1.5, 2.1, 3.4, 4.9]);
  assert.ok(domainCoversData(niceExtent(plotValues(series, { lo: 1.5, hi: 4.9, label: "r" }), 0.1, true), [1.5, 2.1, 3.4, 4.9], true));
  assert.equal(PRESETS["data-story"].chart.zeroBaseline, true);
  assert.equal(PRESETS["data-story"].chart.requireSource, true);
});

test("scene validation and director adapter carry style", () => {
  assert.deepEqual(validateScenes([{ id: "a", type: "kinetic", start: 0, end: 30, style: "chalk-talk" }]), []);
  assert.ok(validateScenes([{ id: "a", type: "kinetic", start: 0, end: 30, style: "hologram" }])[0].includes('unknown style "hologram"'));
  const d = (extra) => ({ id: "s01", narration: { text: "x" }, type: "kinetic", palette: "policy", camera_move: "static", transition: "cut", ...extra });
  const out = fromDirectorScenes([d({ style: "clean-tech" }), d({ id: "s02", style: "nope" }), d({ id: "s03" })]);
  assert.equal(out[0].style, "clean-tech"); assert.equal(out[1].style, undefined); assert.equal(out[2].style, undefined);
  assert.ok(isStyledType("chart") && isStyledType("kinetic") && isStyledType("flow") && isStyledType("timeline"));
  assert.ok(!isStyledType("footage") && !isStyledType("map") && !isStyledType("globe"));
});
