import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { CAM, contentBox, contentPose, layerPose, moveFor, poseKeepsInside, ROLE_MOVE } from "../src/studio/premium/camera.ts";
import { EASE, SPRING, springOut, holdFrames, range, breathe, loop, stagger } from "../src/studio/premium/motion.ts";
import { toLocalWords, findWord, landFrame, norm } from "../src/studio/premium/words.ts";
import { domainAt, viewDomain, windowDomain, SCRUB } from "../src/studio/premium/viewMath.ts";
import { PT, SP, PTYPE } from "../src/studio/premium/tokens.ts";
import { studioLayout, CAPTION_RESERVE } from "../src/studio/layout.ts";
import { CAMERA_MOVES, TRANSITIONS, TRANSITION_FRAMES } from "../src/studio/scenes.ts";
import { PREMIUM_TRANSITION_MAP, TRANSITION_MAP, fromDirectorScenes } from "../src/studio/director.ts";
import { domainCoversData } from "../src/studio/chartMath.ts";

const here = path.dirname(fileURLToPath(import.meta.url));
const PREMIUM_DIR = path.join(here, "..", "src", "studio", "premium");
const safeOf = (o) => { const L = studioLayout(o, CAPTION_RESERVE, "both", "premium"); return { x0: L.x0, y0: L.y0, x1: L.x1, y1: L.y1 }; };

test("camera on content: every pose of every move keeps the content inside the safe box at every frame", () => {
  for (const o of ["vertical", "horizontal"]) {
    const safe = safeOf(o), inner = contentBox(safe);
    assert.ok(inner.x0 > safe.x0 && inner.x1 < safe.x1 && inner.y0 > safe.y0 && inner.y1 < safe.y1, "content box is inset");
    for (const move of [...CAMERA_MOVES, undefined]) {
      for (const dir of [-1, 1]) for (let i = 0; i <= 100; i++) {
        const pose = contentPose(move, i / 100, dir);
        assert.ok(pose.scale >= 1 - 1e-9 && pose.scale <= CAM.maxScale + 1e-9, `${move} scale ${pose.scale}`);
        assert.ok(Math.abs(pose.x) <= CAM.maxShift + 1e-9 && Math.abs(pose.y) <= CAM.maxShift + 1e-9, `${move} shift`);
        assert.ok(poseKeepsInside(inner, safe, pose), `${o} ${move} p=${i / 100} leaves the safe box`);
      }
    }
  }
});

test("the premium composition is wider than the classic centred column but never leaves the same safe box", () => {
  const L = studioLayout("vertical", CAPTION_RESERVE, "both", "premium");
  const inner = contentBox({ x0: L.x0, y0: L.y0, x1: L.x1, y1: L.y1 });
  assert.ok((inner.x1 - inner.x0) / L.cw > 0.9, "content uses over 90% of the safe width");
  assert.equal(L.x0, 65); assert.equal(L.x1, 1080 - 192);   // SAFE_BOX unchanged
});

test("parallax: deeper layers follow the camera more, a layer at depth 0 never moves", () => {
  const pose = contentPose("push", 1);
  const d = [0, 0.2, 0.6, 1].map((k) => layerPose(pose, k));
  assert.equal(d[0].scale, 1); assert.equal(Math.abs(d[0].x), 0); assert.equal(Math.abs(d[0].y), 0);
  for (let i = 1; i < d.length; i++) assert.ok(d[i].scale >= d[i - 1].scale);
});

test("a static director move is replaced by a role default, so no premium scene is a still picture", () => {
  for (const role of Object.keys(ROLE_MOVE)) assert.ok(contentPose(moveFor("none", role, 0), 0.5).scale >= 1);
  const p0 = contentPose("none", 0), p1 = contentPose("none", 1);
  assert.notDeepEqual(p0, p1, "even 'none' drifts");
});

test("motion presets are pure and bounded", () => {
  assert.equal(springOut(0), 0); assert.equal(springOut(1), 1); assert.equal(springOut(2), 1);
  for (const s of Object.values(SPRING)) { let peak = 0; for (let t = 0; t <= 1; t += 0.01) peak = Math.max(peak, springOut(t, s)); assert.ok(peak < 1.25, "overshoot stays small"); }
  for (const k of Object.keys(EASE)) { assert.equal(EASE[k](0), 0); assert.ok(Math.abs(EASE[k](1) - 1) < 1e-9, k); let prev = -1; for (let t = 0; t <= 1; t += 0.05) { const v = EASE[k](t); assert.ok(v >= prev - 1e-12, `${k} monotonic`); prev = v; } }
  assert.equal(holdFrames(0), 15); assert.equal(holdFrames(4), 51);   // 0.5 s + 0.3 s per word
  assert.equal(range(5, 10, 10), 0); assert.equal(range(20, 10, 10), 1);
  assert.equal(stagger(3, 6, 4), 22);
  assert.equal(breathe(7, 40, 3), breathe(7, 40, 3)); assert.ok(loop(130, 60) >= 0 && loop(130, 60) < 1);
});

test("premium sources never use randomness or the clock: a frame is a pure function of its number", () => {
  const bad = /Math\.random|Date\.now|new Date\(|performance\.now|requestAnimationFrame/;
  for (const f of fs.readdirSync(PREMIUM_DIR)) assert.doesNotMatch(fs.readFileSync(path.join(PREMIUM_DIR, f), "utf8"), bad, f);
});

test("word timings become scene-local frames and displayed words land on the spoken frame", () => {
  const words = [{ w: "It", start: 10, end: 10.2 }, { w: "was", start: 10.2, end: 10.4 }, { w: "4.95", start: 10.4, end: 11.0 }, { w: "percent", start: 11.0, end: 11.5 }, { w: "4.88", start: 12, end: 12.6 }];
  const lw = toLocalWords(words, 300);
  assert.deepEqual(lw[0], { w: "It", a: 0, b: 6 });
  assert.equal(lw[2].a, 12);
  assert.equal(norm("4.95%,"), "4.95"); assert.equal(norm("Case,"), "case");
  assert.equal(findWord(lw, "4.88").w.a, 60);
  const r = landFrame(lw, "4.95", 0, 99); assert.deepEqual([r.f, r.spoken, r.next], [12, true, 3]);
  const m = landFrame(lw, "missing", 0, 40); assert.deepEqual([m.f, m.spoken], [40, false]);
  assert.deepEqual(toLocalWords(null, 0), []);
});

test("chart views: the axis always covers the data of the window, and scrubbing interpolates between two honest domains", () => {
  const pts = Array.from({ length: 24 }, (_, i) => ({ x: `2026-10-${String(i + 1).padStart(2, "0")}`, y: 4 + 0.05 * i + 0.3 * Math.sin(i / 3) }));
  const views = [{ window: { from: "2026-10-01", to: "2026-10-12" }, atFrame: 0 }, { window: { from: "2026-10-10", to: "2026-10-24" }, atFrame: 100 }];
  for (const v of views) {
    const d = viewDomain(pts, v);
    const inside = pts.filter((p) => Date.parse(p.x) >= d.x0 && Date.parse(p.x) <= d.x1).map((p) => p.y);
    assert.ok(domainCoversData([d.y0, d.y1], inside), "window axis covers its data");
  }
  const a = domainAt(pts, views, 99), b = domainAt(pts, views, 100 + SCRUB), mid = domainAt(pts, views, 100 + SCRUB / 2);
  assert.equal(a.i, 0); assert.equal(b.i, 1); assert.equal(b.blend, 1);
  assert.ok(mid.dom.x1 > a.dom.x1 && mid.dom.x1 < b.dom.x1, "the window is part-way between the two views");
  assert.ok(windowDomain(pts, Date.parse("2026-10-01"), Date.parse("2026-10-24"))[0] <= Math.min(...pts.map((p) => p.y)));
});

test("transitions: the premium four exist, are mapped from the director's names and take frames the Python side mirrors", () => {
  for (const k of ["push_through", "morph", "sweep", "interrupt"]) { assert.ok(TRANSITIONS.includes(k)); assert.ok(TRANSITION_FRAMES[k] > 0); }
  for (const name of Object.keys(TRANSITION_MAP)) assert.ok(name in PREMIUM_TRANSITION_MAP, name);
  assert.equal(PREMIUM_TRANSITION_MAP.pattern_interrupt, "interrupt");   // the classic map turns it into a plain cut
  assert.equal(TRANSITION_MAP.pattern_interrupt, "cut");
  const py = fs.readFileSync(new URL("../../src/ullaslab_engine/studio/scenecache.py", import.meta.url), "utf8");
  const frames = /^TRANSITION_FRAMES = \{([^}]*)\}/m.exec(py)[1];
  for (const [k, v] of Object.entries(TRANSITION_FRAMES)) assert.match(frames, new RegExp(`"${k}": ${v}\\b`), `scenecache.py ${k}`);
  const pm = /^PREMIUM_TRANSITION_MAP = \{([^}]*)\}/ms.exec(py)[1].replace(/\s+/g, " ");
  for (const [k, v] of Object.entries(PREMIUM_TRANSITION_MAP)) assert.match(pm, new RegExp(`"${k}": "${v}"`), `scenecache.py premium ${k}`);
});

test("director scenes keep word timings and role; premium maps transitions, the classic styles do not change", () => {
  const sc = (t) => ({ id: "s01", role: "hook", narration: { text: "x", start_s: 0, end_s: 2, words: [{ w: "x", start: 0, end: 0.5 }] }, type: "kinetic", palette: "policy", camera_move: "static", transition: t });
  const prem = fromDirectorScenes([sc("pattern_interrupt")], 30, 3, "premium")[0];
  assert.equal(prem.transition, "interrupt"); assert.equal(prem.role, "hook"); assert.equal(prem.words.length, 1);
  assert.equal(fromDirectorScenes([sc("pattern_interrupt")], 30, 3, "data-story")[0].transition, "cut");
  assert.equal(fromDirectorScenes([sc("push")])[0].transition, "match_move");
});

test("design tokens: amber accent, navy base, teal data, an 8-based spacing scale and the A5 type floors", () => {
  assert.equal(PT.amber, "#E8A33D"); assert.equal(PT.navy0, "#0B1424"); assert.equal(PT.teal, "#4FD1C5");
  for (const v of Object.values(SP)) assert.equal(v % 8, 0);
  for (const o of ["vertical", "horizontal"]) { const T = PTYPE[o]; assert.ok(T.headline >= 44 && T.body >= 44 && T.label >= 36 && T.stamp >= 36); assert.ok(T.number > T.display * 0.9); }
});

test("every premium chart and diagram draws the source stamp (data-licensing gate)", () => {
  for (const f of ["PChart.tsx", "PFlow.tsx"]) assert.match(fs.readFileSync(path.join(PREMIUM_DIR, f), "utf8"), /StudioSourceStamp/, f);
});

test("the brand mark is data supplied by the item: the public engine source holds no logo geometry", () => {
  const src = fs.readFileSync(path.join(PREMIUM_DIR, "PEnd.tsx"), "utf8");
  assert.doesNotMatch(src, /M7\.6|8\.8 0|E8A33D/i, "no logo path or brand-square colour literal");
  assert.match(src, /brandMark|BrandMark/);
});

test("camera bounds are pinned to absolute numbers: a pose beyond 5% scale or 14 px shift is a failure, and a pose that exceeds the safe box is detected", () => {
  assert.equal(CAM.maxScale, 1.05); assert.equal(CAM.maxShift, 14);
  for (const o of ["vertical", "horizontal"]) {
    const safe = safeOf(o), inner = contentBox(safe);
    for (const move of [...CAMERA_MOVES, undefined]) for (let i = 0; i <= 50; i++) {
      const p = contentPose(move, i / 50, 1);
      assert.ok(p.scale <= 1.05 + 1e-9 && Math.abs(p.x) <= 14 + 1e-9 && Math.abs(p.y) <= 14 + 1e-9, `${move} pose out of the absolute bound`);
    }
    // the checker itself must fail a pose that is too big
    assert.equal(poseKeepsInside(inner, safe, { scale: 1.12, x: 0, y: 0 }), false);
    assert.equal(poseKeepsInside(inner, safe, { scale: 1, x: 120, y: 0 }), false);
    // and the content box must not shrink away to nothing or grow past the safe box
    assert.ok(inner.x1 - inner.x0 > (safe.x1 - safe.x0) * 0.9 && inner.x0 >= safe.x0 && inner.x1 <= safe.x1);
  }
});
