// Render a StudioVideo (mp4, silent: narration and music are mixed in ffmpeg) or a still.
// Usage: node studio_render.mjs --props p.json --public dir --out file [--id StudioVideo|StudioThumb] [--scale 0.5] [--frame N]
//        node studio_render.mjs --props p.json --public dir --segments segs.json [--scale 0.5]
// A mp4 is rendered when --id is StudioVideo (default); a png when --frame is given.
// --segments renders frame spans of the same composition (one bundle) for the per-scene cache (studio/scenecache.py):
// segs.json = [{"from": first frame, "to": last frame (inclusive), "out": path}]. Segment clips carry no B-frames so the
// ffmpeg concat demuxer can join them by stream copy with exact frame timing.
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { bundle } from "@remotion/bundler";
import { renderMedia, renderStill, selectComposition } from "@remotion/renderer";

const here = path.dirname(fileURLToPath(import.meta.url));
const arg = (k, d) => { const i = process.argv.indexOf("--" + k); return i > 0 ? process.argv[i + 1] : d; };
const props = JSON.parse(fs.readFileSync(arg("props"), "utf8"));
const pub = path.resolve(arg("public")), out = arg("out") ? path.resolve(arg("out")) : null;
const id = arg("id", "StudioVideo"), scale = Number(arg("scale", "1")), frame = arg("frame"), segFile = arg("segments");
const concurrency = Number(process.env.ULLASLAB_RENDER_CONCURRENCY || 0) || undefined;

fs.cpSync(path.join(here, "public", "fonts"), path.join(pub, "fonts"), { recursive: true, dereference: true });
const serveUrl = await bundle({ entryPoint: path.join(here, "src", "index.ts"), publicDir: pub });
const quiet = { logLevel: "error" };
const comp = await selectComposition({ serveUrl, id, inputProps: props, ...quiet });
// x264 without B-frames: the output path is the last ffmpeg argument; only the encoding (libx264) command is changed.
const noBFrames = ({ args }) => (args.includes("libx264") ? [...args.slice(0, -1), "-bf", "0", args[args.length - 1]] : args);
const video = { serveUrl, composition: comp, codec: "h264", inputProps: props, muted: true, crf: 18, pixelFormat: "yuv420p",
  x264Preset: "medium", scale, concurrency, ...quiet };
if (segFile) {
  const segs = JSON.parse(fs.readFileSync(segFile, "utf8"));
  for (const s of segs) {
    if (!(Number.isInteger(s.from) && Number.isInteger(s.to) && s.from >= 0 && s.to >= s.from && s.to < comp.durationInFrames)) {
      throw new Error(`bad segment ${JSON.stringify(s)} for ${comp.durationInFrames} frames`);
    }
    await renderMedia({ ...video, outputLocation: path.resolve(s.out), frameRange: [s.from, s.to], ffmpegOverride: noBFrames });
    console.log(`segment ${s.from}-${s.to}`);
  }
} else if (frame !== undefined) {
  await renderStill({ serveUrl, composition: comp, frame: Number(frame), output: out, inputProps: props, ...quiet });
  console.log("still");
} else {
  await renderMedia({ ...video, outputLocation: out });
  console.log(`rendered ${comp.width * scale}x${comp.height * scale} ${comp.durationInFrames}f`);
}
