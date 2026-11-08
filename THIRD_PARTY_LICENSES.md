# Third-party licences

Only components usable commercially are included. Verified against package metadata and the sources in
`docs/feasibility.md` of the private content repo (access date 2026-11-08). This is not legal advice.

## Models

| Component | Use | Licence | Notes |
|---|---|---|---|
| Chatterbox-Multilingual (`chatterbox-tts` 0.1.7, ResembleAI weights) | voice clone: en, hi, es, pt, ar, ja | MIT | Output carries Resemble's PerTh watermark; keep it. Upstream retired Aug 2026, so the version is pinned. |
| Indic Parler-TTS (`ai4bharat/indic-parler-tts`, `parler-tts` library) | stock voice: hi, ta, te, kn, ml, mr, bn, gu | Apache-2.0 | No voice cloning. Library installed from a pinned commit (`scripts/install_parler.sh`). Weights are gated on Hugging Face; the owner accepts the terms and mirrors them (Apache-2.0 allows redistribution with the licence) into a private R2 bucket, never into this repo. |
| Kokoro-82M (`hexgrad/Kokoro-82M`, `kokoro`, `misaki`) | stock fallback: en, hi, es, pt, ja | Apache-2.0 | |
| Whisper large-v3 via `faster-whisper` / CTranslate2 | caption alignment, WER re-transcription | MIT | |
| `num2words` (library, not a model) | number verbalisation: en, es, pt, ar, ja, te, bn | LGPL-2.1 | Used unmodified via `import` (dynamic use is commercial-OK). Hindi uses our own rules. |
| spaCy `en_core_web_sm` (pulled by misaki) | English G2P | MIT | |

Not used on purpose: learned MOS predictors UTMOS, TorchAudio-SQUIM and DNSMOS (weight licences not clearly commercial-OK; the naturalness gate uses objective proxies), IndicF5 (commercial licence UNCLEAR, feasibility B1), NLLB-200 (CC-BY-NC), CosyVoice2 (no Indic/Arabic).

## Software

| Component | Licence | Notes |
|---|---|---|
| Remotion 4.0.541 (`remotion`, `@remotion/*`) | Remotion License (free tier) | Free for individuals and for-profit organisations with up to 3 employees, commercial use included. 4 or more employees need a Company License. The licence changes in Remotion 5.0: re-read before upgrading. |
| React 19 | MIT | |
| Noto Sans families via `@fontsource/*` (Latin, Devanagari, Tamil, Telugu, Kannada, Malayalam, Bengali, Gujarati, Arabic, JP) | SIL OFL 1.1 | Fonts are copied at install time into `remotion/public/fonts` (git-ignored) and embedded in rendered video frames. |
| numpy, SciPy, soundfile, PyAV | BSD | |
| PyTorch | BSD-style | |
| pyloudnorm, PyYAML, jsonschema, onnxruntime | MIT | |
| jiwer, requests, huggingface-hub, transformers, tokenizers | Apache-2.0 | |
| TypeScript | Apache-2.0 | |

## Flags for the owner

1. `phonemizer-fork` (pulled by `misaki[en]` for Kokoro) is GPL-3.0-or-later, and `espeak-ng` is GPL-3.0. Both run only on the CI runner or the local machine as a build/render tool and are never distributed from this repo, so copyleft distribution terms are not triggered. If that position is not acceptable, remove the `kokoro` extra and use Chatterbox for the English fallback.
2. Remotion's free tier depends on the headcount condition above.
3. Chatterbox is unmaintained upstream: pin and keep the weights hash.
