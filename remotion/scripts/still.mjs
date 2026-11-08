// Dev helper: render stills for visual inspection. node scripts/still.mjs props.json public outdir f1,f2,...
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { bundle } from "@remotion/bundler";
import { renderStill, selectComposition } from "@remotion/renderer";
const here = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const [propsPath, pub, outDir, frames] = process.argv.slice(2);
const props = JSON.parse(fs.readFileSync(propsPath, "utf8"));
fs.cpSync(path.join(here, "public", "fonts"), path.join(pub, "fonts"), { recursive: true, dereference: true });
const serveUrl = await bundle({ entryPoint: path.join(here, "src", "index.ts"), publicDir: pub });
const composition = await selectComposition({ serveUrl, id: "Main", inputProps: props, logLevel: "error" });
fs.mkdirSync(outDir, { recursive: true });
for (const f of frames.split(",")) await renderStill({ serveUrl, composition, frame: Number(f), output: path.join(outDir, `f${f}.png`), inputProps: props, logLevel: "error" });
