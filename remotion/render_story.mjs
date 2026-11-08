// Render one Story + layout audit. Usage: node render_story.mjs --props p.json --public dir --out story.mp4 --audit layout.json
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { bundle } from "@remotion/bundler";
import { renderMedia, renderStill, selectComposition } from "@remotion/renderer";

const here = path.dirname(fileURLToPath(import.meta.url));
const arg = (k) => { const i = process.argv.indexOf("--" + k); return i > 0 ? process.argv[i + 1] : undefined; };
const props = JSON.parse(fs.readFileSync(arg("props"), "utf8"));
const pub = path.resolve(arg("public")), out = path.resolve(arg("out") ?? "unused.mp4"), auditOut = arg("audit");
fs.cpSync(path.join(here, "public", "fonts"), path.join(pub, "fonts"), { recursive: true, dereference: true });
const serveUrl = await bundle({ entryPoint: path.join(here, "src", "index.ts"), publicDir: pub });
const quiet = { logLevel: "error" };
const comp = await selectComposition({ serveUrl, id: "Story", inputProps: props, ...quiet });
if (auditOut) {
  const ap = { ...props, audit: true };
  const ac = await selectComposition({ serveUrl, id: "Story", inputProps: ap, ...quiet });
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "ull-saudit-"));
  const results = [];
  const n = ac.durationInFrames;
  for (const frame of [0, Math.round(n * 0.3), Math.round(n * 0.6), Math.round(n * 0.85)]) {
    await renderStill({ serveUrl, composition: ac, frame, output: path.join(tmp, "s.png"), inputProps: ap, ...quiet,
      onBrowserLog: (l) => { if (l.text.startsWith("[[AUDIT]]")) results.push({ ...JSON.parse(l.text.slice(9)), frame }); } });
  }
  fs.rmSync(tmp, { recursive: true, force: true });
  fs.writeFileSync(auditOut, JSON.stringify({ width: comp.width, height: comp.height, frames: results }));
}
if (process.argv.includes("--no-video")) { console.log("audited"); process.exit(0); }
await renderMedia({ serveUrl, composition: comp, codec: "h264", audioCodec: "aac", outputLocation: out, inputProps: props,
  crf: 20, pixelFormat: "yuv420p", audioBitrate: "128k", ...quiet });
console.log("rendered");
