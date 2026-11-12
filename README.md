# ullaslab-engine

Generic, secret-free render, TTS, captions and QA engine for the UllasLab content pipeline.

**This repository is public. It contains no secrets, no content, no voice sample, no scripts and no owner
data, and it never will.** Inputs and outputs travel as presigned R2 URLs in a `repository_dispatch` payload
(see `docs/dispatch-protocol.md`). Workflows run only on `repository_dispatch` (render) and on pushes to `main`
(tests); never on `pull_request`; `permissions: {}` throughout; URLs are masked first in every job.

## Layout

| Path | What |
|---|---|
| `remotion/` | Remotion 4 project: brand kit, safe zones, animated chart components, 10 format templates, caption overlay, Noto fonts for 13 scripts (Arabic RTL), layout audit |
| `src/ullaslab_engine/tts/` | TTS adapters: `tts(text, lang, ref_wav) -> Wav`. Chatterbox (clone), Indic Parler and Kokoro (stock), fallback chain from `config/languages.yaml`, -14 LUFS normalisation |
| `src/ullaslab_engine/captions.py`, `asr.py` | faster-whisper alignment (English master), segment-mapped translated captions, SRT and VTT |
| `src/ullaslab_engine/qa.py` | QA gates A1 to A5 plus duration from `config/quality.yaml`, writes numbers-only `qa.json` |
| `.github/workflows/render.yml` | dispatch, TTS per language (matrix), render, QA, PUT |
| `schema/` | JSON schemas for the bundle manifest and chart JSON |
| `src/ullaslab_engine/voice/` | WP11 voice layer: recording QA and clip selection, number verbalisation, sentence-level narration, post-processing, naturalness gate, local demo (`docs/voice.md`) |
| `config/` | vendored copies of `languages.yaml` and `quality.yaml` (thresholds are not secret); `safe_zones.json` |

## Video styles

An item can carry an optional `style` (`data-story`, `creator-motion`, `chalk-talk`, `clean-tech`) at the item level of
`scenes.json` and, optionally, on a single scene. Absent means the default look, so every existing item renders as before. The
preset layer is `remotion/src/studio/styles.ts` (type scale, motion, layout, backdrop, caption treatment and chart rules, brand
palette only) applied by `SceneRenderer`; the original scene components are in `StyleKit.tsx`, and the chart additions (scenario
range band, zero baseline) are in `Charts.tsx`.

| Style | For | What it adds |
|---|---|---|
| `data-story` | data and asset research | zero-based axes that always cover the data, scenario range band, annotations, timeline, source stamp required |
| `creator-motion` | hooks, surprising numbers | large kinetic type, emphasis words, counters that end on the written figure, restrained camera |
| `chalk-talk` | formulas, worked examples | stroke-on writing, step-by-step build, hand-drawn result box, no camera move |
| `clean-tech` | systems, market structure | cards, flow diagrams, timelines, quiet motion |

Only `chart`, `timeline`, `flow` and `kinetic` scenes are restyled; footage, map and globe render unchanged. Kinetic text markup:
`*word*` emphasis (creator-motion), `|` separates chalk steps or clean-tech cards, a chalk step starting with `=` is the result and
a card may be `Title: detail`. Numbers are never computed or rescaled by a style: counters end on the token as written, and charts
draw only the data passed in. The end card ("Follow UllasLab. Education only."), the caption safe zones and the no-freshness-tag
rule are unchanged by every style.

Check the styles without a full render: `make style-stills` renders one still per scene of each style demo in both aspect ratios
into `out/style-stills` and `python -m ullaslab_engine.studio.style_check out/style-stills` verifies size, content and safe zones
(the same check runs in `RUN_RENDER=1 pytest tests/test_styles.py`). Stills are never committed.

## Per-scene render cache and single-scene re-render

`studio run` renders each output scene by scene and joins the clips (`src/ullaslab_engine/studio/scenecache.py`), so a scene
that did not change is never rendered again.

- **Segments.** An output is cut at every scene start. Each segment is rendered from the full `StudioVideo` composition with
  Remotion's `frameRange` (`studio_render.mjs --segments`, one bundle for all segments), so its frames are exactly the frames
  a full render draws: the outgoing scene under a crossfade or wipe, captions and the end card included. No neighbouring scene
  is re-composited; instead a segment's key covers every scene visible in it, so editing a scene re-renders its own segment and
  the next one when its picture runs under the next scene's enter transition.
- **Key.** sha256 of: the absolute frame span and composition length; for every visible scene its index, frame range and
  overlap, the scene object as rendered, the data its `data_ref` resolves to and the sha256 of any footage file it names; item
  style, orientation, size, scale (preview or final), fps, language, number locale, RTL and platform; the caption cues and end
  card overlapping the span; and a renderer stamp (every file under `remotion/src` and `remotion/public`, `studio_render.mjs`,
  `package.json`, `package-lock.json`, the engine version). Changing any of them re-renders; nothing else does.
- **Join.** Segment clips are H.264 High, yuv420p, 30 fps without B-frames, so the ffmpeg concat demuxer joins them by stream
  copy with no dropped or repeated frame (with B-frames it repeats a frame at short boundaries). The join must have exactly
  `durationInFrames` frames. Audio is mixed once over the joined video; after the mux the studio checks that the video has every
  frame and that audio and video end together (within 50 ms).
- **Safety.** A cached clip is used only after ffprobe confirms its frame count, size, codec and no B-frames; a damaged or
  partial clip is deleted and rendered again. New clips are written under a temporary name first.
- **Storage.** `<item>/work/scene_cache/<sha256>.mp4` plus `index.json`, never committed. Least recently used clips are pruned
  above `ULLASLAB_SCENE_CACHE_MAX_MB` (default 4096); clips used by the current run are never pruned.

Commands:

```
ullaslab-engine studio run <item>                          # renders only segments whose key changed (edit scenes.json, rerun)
ullaslab-engine studio run <item> --scene s03              # re-render the spans showing s03 in every output that has it
ullaslab-engine studio run <item> --scene s03,s05 --output reel
ullaslab-engine studio run <item> --no-scene-cache         # one-pass render of each output (old behaviour)
```

An unknown scene id is an error and nothing runs. Packaging gives a new version file (`reel.v2.mp4`, `captions.reel.v2.srt`)
only to an output whose final changed or that was named with `--scene`; unchanged outputs keep their files. QC runs on the
result as before. Footage clips are re-cut only when their source, length or size changes.

**Approval.** A re-render produces new files, so an approval given for the earlier render no longer covers them and must be
given again; the engine never tries to carry it over and never touches an approval file. When an approval file exists in the
item folder and a re-render publishes a new version, `studio run` warns and QC reports "approval covers the current render" as
WARN until a newer approval exists.

## Narration (long text, pace, markup)

`voice/narrate.py` synthesises sentence by sentence (long sentences split at commas). Sentences under three words are said
together with the next one unless a marker holds the pause after them: very short inputs made the clone engine fail and lose
a whole long call. A failing chunk is retried on new seeds, then merged with the next chunk, and only then reported by name.
With a chunk cache (`cache_dir=`, `ULLASLAB_TTS_CACHE`, or `ullaslab-engine voice-narrate --text script.txt --out voice.wav`,
which caches under `work/tts_cache`) a crash or rerun resumes without redoing finished chunks; the cache key covers text,
language, engine, settings, seed and the reference-voice bytes. Each chunk's model silence is trimmed, edges are faded and
levels matched before the pauses go in.

Pace is a target in words per minute including pauses (`voice_defaults.pace` in `config/languages.yaml`: `target_wpm` 150,
`max_speedup` 1.15, `pause_floor` 0.6; a language may override it). It is met by shortening punctuation pauses first and then
by a pitch-preserving tempo change of at most `max_speedup` (ffmpeg `atempo`); the voice itself is unchanged. A result still
more than 10% under target is flagged, and the naturalness gate still checks pauses and rate. The pronunciation lexicon applies
on every TTS path. Markup: `[[hook]]` and `[[payoff]]` lengthen the pause before a sentence, `[[pause]]` or `[[pause:0.8]]`
inserts a pause anywhere (at most 2 s), and `*word*` emphasis is screen markup whose asterisks are never spoken.

## Sound

Music bed: licensed tracks from the ledger (none ship with the engine), else a generated CC0 pad; it sits about 20 dB under
the voice and rises in pauses, intro and outro. Transition and emphasis SFX (`tick`, `whoosh`, `riser`, `hit`, `page_turn`,
`ambient_low`) are synthesised in-house with ffmpeg lavfi (CC0, own work; no third-party audio). Two-pass loudnorm to -14 LUFS,
true peak at most -1 dBTP. QC fails silence over 1.5 s, an ending that stops mid-sound and a narration track cut off mid-word.

## Quick start

```
make setup            # venv, python deps (kokoro + faster-whisper), npm ci
make test             # unit tests (python + node), no models, no Chrome
make test-render      # Remotion audits of all templates in real Chrome (1-2 min)
make render-fixture   # full synthetic item on CPU with a stock voice, QA included
```

Licences: `THIRD_PARTY_LICENSES.md`.
