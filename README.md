# ullaslab-engine

Generic, secret-free render, TTS, captions and QA engine for the UllasLab Macro content pipeline.

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

## Quick start

```
make setup            # venv, python deps (kokoro + faster-whisper), npm ci
make test             # unit tests (python + node), no models, no Chrome
make test-render      # Remotion audits of all templates in real Chrome (1-2 min)
make render-fixture   # full synthetic item on CPU with a stock voice, QA included
```

Licences: `THIRD_PARTY_LICENSES.md`.
