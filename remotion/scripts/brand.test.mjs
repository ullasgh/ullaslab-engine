import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import { C, FONT, END_LINES, endParts, SAFE, TYPE, SOURCE_WORD, ILLUSTRATIVE_FOOTAGE } from "../src/brand.ts";
const tplSrc = fs.readFileSync(new URL("../src/templates.ts", import.meta.url), "utf8");

const lum = (h) => {
  const [r, g, b] = [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16) / 255).map((c) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4));
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
};
const cr = (a, b) => { const [x, y] = [lum(a), lum(b)].sort((p, q) => q - p); return (x + 0.05) / (y + 0.05); };

test("palette pairs meet 4.5:1 contrast", () => {
  const pairs = [[C.text, C.bg], [C.muted, C.bg], [C.muted, C.panel], [C.text, C.panel], [C.text, C.caption], [C.primary, C.panel],
    [C.negative, C.panel], [C.secondary, C.panel], [C.accent, C.panel], ["#0B1424", "#FFFFFF"], ["#1E293B", "#F2F5F9"], [C.primary, C.bg]];
  for (const [a, b] of pairs) assert.ok(cr(a, b) >= 4.5, `${a} on ${b} = ${cr(a, b).toFixed(2)}`);
});

test("end line in all 13 languages, two parts, no freshness tag words, no macro", () => {
  const langs = "en hi ta te kn ml mr bn gu es pt ar ja".split(" ");
  assert.equal(END_LINES.en, "Follow UllasLab. Education only.");
  for (const l of langs) { assert.ok(END_LINES[l].includes("UllasLab"), l); assert.equal(endParts(l).length, 2, l); assert.doesNotMatch(END_LINES[l], /macro|LIVE|RECENT|LAGGED|EXPECTATION|INFERRED/i); }
});

test("fonts cover all 13 languages", () => {
  const langs = "en hi ta te kn ml mr bn gu es pt ar ja".split(" ");
  for (const l of langs) { assert.ok(FONT[l], l); assert.ok(SOURCE_WORD[l], l); assert.ok(ILLUSTRATIVE_FOOTAGE[l], l); }
  assert.match(FONT.ar, /Arabic/); assert.match(FONT.ja, /JP/);
});

test("ten templates, one per format", () => {
  const formats = [...tplSrc.matchAll(/format: (\d+)/g)].map((m) => Number(m[1]));
  const ids = [...tplSrc.matchAll(/id: "([a-z0-9-]+)"/g)].map((m) => m[1]);
  assert.deepEqual(formats, [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]);
  assert.equal(new Set(ids).size, 10);
});

test("safe zones and type scale match config", () => {
  const z = JSON.parse(fs.readFileSync(new URL("../../config/safe_zones.json", import.meta.url)));
  for (const o of ["vertical", "horizontal"]) {
    assert.equal(SAFE[o].top, z[o].top); assert.equal(SAFE[o].bottom, z[o].bottom); assert.equal(SAFE[o].sides, z[o].sides);
    assert.equal(SAFE[o].w, z[o].width); assert.equal(SAFE[o].h, z[o].height);
    assert.ok(TYPE[o].headline >= 44 && TYPE[o].body >= 44 && TYPE[o].caption >= 44 && TYPE[o].label >= 36);
  }
});

test("template accents are readable as text on panel and bg", () => {
  for (const m of tplSrc.matchAll(/accent: "(#[0-9A-Fa-f]{6})"/g)) {
    assert.ok(cr(m[1], C.panel) >= 4.5 && cr(m[1], C.bg) >= 4.5, m[1]);
  }
});
