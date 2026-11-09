// Dev helper: render one still per StudioDemo scene in both aspect ratios (bundles once).
// node scripts/studio-stills.mjs <outDir> [sceneIndexes e.g. 0,1,2]   (same renderer as `npx remotion still`)
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { bundle } from "@remotion/bundler";
import { renderStill, selectComposition } from "@remotion/renderer";
const here = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const [outDir = "../out/wp3-stills", only] = process.argv.slice(2);
const names = ["footage", "map", "globe", "chart-line", "chart-bar", "chart-yield", "chart-counter", "timeline", "flow", "kinetic"];
const pick = only ? only.split(",").map(Number) : names.map((_, i) => i);
const serveUrl = await bundle({ entryPoint: path.join(here, "src", "index.ts"), publicDir: path.join(here, "public") });
fs.mkdirSync(outDir, { recursive: true });
for (const id of ["StudioDemo-16x9", "StudioDemo-9x16"]) {
  const composition = await selectComposition({ serveUrl, id, logLevel: "error" });
  for (const i of pick) {
    const frame = i * 90 + 75; // transition done, animations settled
    const output = path.join(outDir, `${id.split("-")[1]}-s${String(i + 1).padStart(2, "0")}-${names[i]}.png`);
    await renderStill({ serveUrl, composition, frame, output, logLevel: "error" });
    console.log(output);
  }
}
