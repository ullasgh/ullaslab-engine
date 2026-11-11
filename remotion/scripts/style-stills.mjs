// Dev/QA helper: one still per scene of every style demo in both aspect ratios, plus the layout audit (geometry only, no text).
// node scripts/style-stills.mjs <outDir> [--styles data-story,chalk-talk] [--frames 75,165,255]
// Writes <outDir>/<style>-<16x9|9x16>-f<frame>.png and <outDir>/audit.json. Keep outDir outside the repo: stills are never committed.
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { bundle } from "@remotion/bundler";
import { renderStill, selectComposition } from "@remotion/renderer";

const here = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const arg = (k, d) => { const i = process.argv.indexOf("--" + k); return i > 0 ? process.argv[i + 1] : d; };
const outDir = path.resolve(process.argv[2] ?? "../out/style-stills");
const styles = arg("styles", "data-story,creator-motion,chalk-talk,clean-tech").split(",");
const frames = arg("frames", "75,165,255").split(",").map(Number);
const aspects = [["16:9", "horizontal"], ["9:16", "vertical"]];

const serveUrl = await bundle({ entryPoint: path.join(here, "src", "index.ts"), publicDir: path.join(here, "public") });
fs.mkdirSync(outDir, { recursive: true });
const audit = [];
for (const style of styles) {
  for (const [aspect, orientation] of aspects) {
    const inputProps = { orientation, style, audit: true };
    const composition = await selectComposition({ serveUrl, id: "StudioStyle", inputProps, logLevel: "error" });
    for (const frame of frames) {
      const output = path.join(outDir, `${style}-${aspect.replace(":", "x")}-f${frame}.png`);
      const rec = { style, aspect, frame, file: path.basename(output), width: composition.width, height: composition.height, elements: [] };
      await renderStill({ serveUrl, composition, frame, output, inputProps, logLevel: "error",
        onBrowserLog: (l) => { if (l.text.startsWith("[[AUDIT]]")) rec.elements = JSON.parse(l.text.slice(9)).elements; } });
      audit.push(rec);
      console.log(output);
    }
  }
}
fs.writeFileSync(path.join(outDir, "audit.json"), JSON.stringify(audit));
