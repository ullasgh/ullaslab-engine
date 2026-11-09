// Render a StudioVideo (mp4, silent: narration and music are mixed in ffmpeg) or a still.
// Usage: node studio_render.mjs --props p.json --public dir --out file [--id StudioVideo|StudioThumb] [--scale 0.5] [--frame N]
// A mp4 is rendered when --id is StudioVideo (default); a png when --frame is given.
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { bundle } from "@remotion/bundler";
import { renderMedia, renderStill, selectComposition } from "@remotion/renderer";

const here = path.dirname(fileURLToPath(import.meta.url));
const arg = (k, d) => { const i = process.argv.indexOf("--" + k); return i > 0 ? process.argv[i + 1] : d; };
const props = JSON.parse(fs.readFileSync(arg("props"), "utf8"));
const pub = path.resolve(arg("public")), out = path.resolve(arg("out"));
const id = arg("id", "StudioVideo"), scale = Number(arg("scale", "1")), frame = arg("frame");
const concurrency = Number(process.env.ULLASLAB_RENDER_CONCURRENCY || 0) || undefined;

fs.cpSync(path.join(here, "public", "fonts"), path.join(pub, "fonts"), { recursive: true, dereference: true });
const serveUrl = await bundle({ entryPoint: path.join(here, "src", "index.ts"), publicDir: pub });
const quiet = { logLevel: "error" };
const comp = await selectComposition({ serveUrl, id, inputProps: props, ...quiet });
if (frame !== undefined) {
  await renderStill({ serveUrl, composition: comp, frame: Number(frame), output: out, inputProps: props, ...quiet });
  console.log("still");
} else {
  await renderMedia({ serveUrl, composition: comp, codec: "h264", outputLocation: out, inputProps: props, muted: true,
    crf: 18, pixelFormat: "yuv420p", x264Preset: "medium", scale, concurrency, ...quiet });
  console.log(`rendered ${comp.width * scale}x${comp.height * scale} ${comp.durationInFrames}f`);
}
