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

Seams for the next milestone (not built here): per-scene render cache and single-scene re-render would key on a hash of one scene
object plus the item style and `refs` it uses, at the `Sequence` per scene in `SceneRenderer`; the music library and narration
pace sit in `studio/audio.py` and `studio/timings.py`.

## Quick start

```
make setup            # venv, python deps (kokoro + faster-whisper), npm ci
make test             # unit tests (python + node), no models, no Chrome
make test-render      # Remotion audits of all templates in real Chrome (1-2 min)
make render-fixture   # full synthetic item on CPU with a stock voice, QA included
```

Licences: `THIRD_PARTY_LICENSES.md`.
