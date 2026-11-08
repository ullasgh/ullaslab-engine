# Voice layer (WP11)

Generic code only; no voice data lives in this repo (`tests` assert no audio files are tracked).

| module | job |
|---|---|
| `voice/prepare.py` | recording QA (SNR, clipping, noise floor, reverb hint, hum, loudness, verdict), light spectral-gate denoise, pause tightening, reference clip scoring and selection |
| `voice/textnorm.py` | numbers, currency, percent, dates to words per language (hi lakh/crore own rules; en, es, pt, ar, ja, te, bn via num2words; others pass digits through) |
| `voice/prosody.py` | sentence split, pause by punctuation (. 0.42 s, ? 0.48, ! 0.40, ellipsis 0.55, ; : 0.30, comma 0.16, paragraph 0.80), long sentences split at commas |
| `voice/post.py` | 70 Hz high-pass, +1.2 dB presence at 3 kHz, de-esser (5 to 9 kHz, max 6 dB), fixed room tone at -63 dBFS; no reverb or heavy effects |
| `voice/naturalness.py` | MOS-style 0-100 proxy score, thresholds in `config/quality.yaml` (`A3b_naturalness`); `extra_scorer` hook for a learned model |
| `voice/narrate.py` | `narrate()`: verbalise, split, synthesise per sentence, post-process, gate (regenerate once, then `Wav.flags`) |
| `voice/settings.py` | `voice_defaults` + per-language overrides; `accent: native` forces Chatterbox `cfg_weight=0` for non-English targets |
| `voice/demo.py` | local listening page + choices form for the owner |

Chatterbox guidance (upstream README, checked 2026-11-08): "Ensure that the reference clip matches the specified language tag. Otherwise, language transfer outputs may inherit the accent of the reference clip's language. To mitigate this, set `cfg_weight` to `0`." Defaults `exaggeration=0.5, cfg_weight=0.5` work for most prompts; we use 0.4 for calmer narration. Upstream now offers a V3 checkpoint (`t3_model="v3"`); we stay on the pinned 0.1.7 (V2) until a deliberate upgrade.
Indic Parler-TTS: recommended speakers from the model card (hi Rohit/Divya, ta Jaya/Kavitha, te Prakash/Lalitha, kn Suresh/Anu, ml Anjali/Harish, mr Sanjay/Sunita, bn Arjun/Aditi, gu Yash/Neha); description asks for a calm, neutral narration tone, "very clear audio", close recording.

CLI (local): `voice-analyze --file F`, `voice-prepare --file F --out DIR`, `voice-score --file W`, `voice-demo --out DIR [--refs DIR] [--langs a,b] [--max-per-lang N]`.
The render dispatch may carry `voice_clip_urls` {"1","2","3"}; `fetch --voice` saves them to `work/clips/` and `narrate()` uses the clip chosen by `ref_clip`, falling back to `voice.wav`.
