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
| `voice/delivery.py` | per-line delivery: the tag vocabulary (hook, tension, reveal, explain, caution, signoff), the `[[d:tag]]` marker, the tag-to-settings mapping per profile (`config/delivery.yaml`) |
| `voice/demo.py` | local listening page + choices form for the owner |

Chatterbox guidance (upstream README, checked 2026-11-08): "Ensure that the reference clip matches the specified language tag. Otherwise, language transfer outputs may inherit the accent of the reference clip's language. To mitigate this, set `cfg_weight` to `0`." Defaults `exaggeration=0.5, cfg_weight=0.5` work for most prompts; we use 0.4 for calmer narration. Upstream now offers a V3 checkpoint (`t3_model="v3"`); we stay on the pinned 0.1.7 (V2) until a deliberate upgrade.
Indic Parler-TTS: recommended speakers from the model card (hi Rohit/Divya, ta Jaya/Kavitha, te Prakash/Lalitha, kn Suresh/Anu, ml Anjali/Harish, mr Sanjay/Sunita, bn Arjun/Aditi, gu Yash/Neha); description asks for a calm, neutral narration tone, "very clear audio", close recording.

CLI (local): `voice-analyze --file F`, `voice-prepare --file F --out DIR`, `voice-score --file W`, `voice-demo --out DIR [--refs DIR] [--langs a,b] [--max-per-lang N]`.
The render dispatch may carry `voice_clip_urls` {"1","2","3"}; `fetch --voice` saves them to `work/clips/` and `narrate()` uses the clip chosen by `ref_clip`, falling back to `voice.wav`.


## Indic Parler-TTS weights in CI (WP12)
The gated `ai4bharat/indic-parler-tts` weights are not fetched from Hugging Face in CI. The `dub` job restores them from the owner's private R2 mirror through the `model` dispatch object (see `dispatch-protocol.md`), verifies the sha256, and the TTS step loads them offline from a dedicated `HF_HUB_CACHE`. No Hugging Face token exists in this repo, and `tests/test_workflows.py` still forbids `secrets.` and `HF_TOKEN`.


## Per-line delivery (voice slice 2)
A scene's `narration.delivery` (scenes.json, one of hook / tension / reveal / explain / caution / signoff; written by the scriptwriter and
director) reaches the voice as a `[[d:<tag>]]` marker that `studio/actions.output_text` puts in front of the scene's text. The marker is
never spoken, counted as a word or shown (`prosody.strip_markers`). `narrate()` turns each sentence's tag into synthesis settings for the
active profile, `voice_defaults.delivery_profile` in `config/languages.yaml` (`baseline`, `mild`, `strong`, `tuned`; the profiles live in
`config/delivery.yaml`): Chatterbox `exaggeration`, `cfg_weight` and `temperature` per sentence, plus a per-line tempo, level offset and
pause before/after (kept by the pacer). `baseline` is empty: every line gets the one global setting, byte for byte as before tags existed.
The default stays `baseline` until the owner picks a profile after listening to the samples. No QA gate or limit depends on the profile:
A3 (wpm 135-175, WER 3%, max silence 1.2 s, loudness), the duration limit and the WER-only retry (seed base + 1000 * attempt, 3 attempts)
measure whatever the profile produces. Bounds on every profile value are enforced when `config/delivery.yaml` is read
(`delivery.BOUNDS`). Chatterbox guidance (upstream README): higher `exaggeration` tends to speed speech up; lower `cfg_weight` (about 0.3)
slows it back down.
