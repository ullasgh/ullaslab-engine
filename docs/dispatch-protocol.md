# Dispatch protocol (private content repo to this engine)

This repo is public. It holds no secrets, no content, no voice sample and no scripts. Everything arrives and
leaves through presigned R2 URLs (S3 domain, 2 h expiry) in a `repository_dispatch` payload.

## Trigger

`POST /repos/<owner>/ullaslab-engine/dispatches` with `event_type: "render"` and a fine-grained PAT with
Contents: write on this repo only (held by the private repo).

```json
{
  "event_type": "render",
  "client_payload": {
    "job_id": "2026-11-08-chart-of-the-week",
    "bundle_url": "https://<acct>.r2.cloudflarestorage.com/...  (GET, zip of the bundle)",
    "voice_url": "https://...  (GET, optional reference wav; only on the runner, never uploaded)",
    "voice_clip_urls": {"1": "https://...", "2": "...", "3": "..."},  (GET, optional: the 3 reference clips; ref_clip in languages.yaml picks one, voice_url is the fallback)
    "timing_url": "https://...  (GET timing_en.json written by the master job; needed by dub jobs)",
    "languages": ["en", "hi", "ta"],
    "outputs": {
      "master.mp4": "PUT url", "timing_en.json": "PUT url",
      "audio_en.wav": "PUT url", "audio_hi.wav": "PUT url",
      "captions_en.srt": "PUT url", "captions_en.vtt": "PUT url", "captions_hi.srt": "PUT url",
      "hi_vertical.mp4": "PUT url",
      "qa_en.json": "PUT url", "qa_hi.json": "PUT url", "qa_hi_vertical.json": "PUT url"
    }
  }
}
```

Rules enforced in code (`ullaslab_engine/io.py`, `tests/test_io_cli.py`):

- Every URL must be `https` on `*.r2.cloudflarestorage.com`; anything else fails the job before any download.
- `job_id` is `[A-Za-z0-9_-]{1,64}`, language codes are two letters, output keys are `[A-Za-z0-9._-]`.
- Each job masks every URL, its query string and its path with `::add-mask::` as its first step. The
  payload is never echoed, never put in an artifact, and transport errors never include a URL.
- Outputs missing from `outputs` are simply not uploaded. `qa_*.json` is uploaded even when QA fails
  (`if: always()`), so the private repo can see which gate broke. It contains numbers only.

## Bundle (zip)

```
manifest.json            schema/manifest.schema.json
charts/*.json            schema/chart.schema.json
```

`manifest.json`: slug, orientation (`vertical` 1080x1920 or `horizontal` 1920x1080), `format` 1 to 10 (selects
the template), `languages`, `segments` (id plus text per language; narration unit and caption unit),
`scenes` (kind, segment ids, chart, headline/body/items as plain string or `{lang: text}`), `disclaimer`,
and `variants` such as `{"name": "hi_vertical", "lang": "hi", "orientation": "vertical"}`.

Chart JSON: `line`, `bar`, `compare`, `delta`, `counter`; every chart needs `source` (name, as_of),
`freshness` (LIVE, RECENT, LAGGED, EXPECTATION, INFERRED). `claim_id` is required (A1). `chart_hash`, when
present, must equal the SHA-256 of the canonical JSON without that key (`qa.chart_hash`).

## Job flow (`.github/workflows/render.yml`)

1. `plan`: validates the payload, outputs the dub matrix and the extras each language needs.
2. `master`: TTS (en), faster-whisper aligned captions, Remotion render, QA, upload. Writes `timing_en.json`.
3. `dub` (matrix, one job per language): TTS (clone or stock voice per `config/languages.yaml`), translated
   captions timed from the English segment windows, slot-aligned dub audio, A1 to A5 QA, upload. A language
   with no usable voice (for example Arabic when cloning fails) degrades to captions only.
   `variants` for the language (the Hindi vertical cut) are rendered from a natural-timeline Hindi track.

Dub audio is slot-aligned to the master: each dubbed segment starts at the master segment start. A segment
that runs into the next one is reported as `dub_overruns` and fails QA; the translator must shorten it.
Dub tracks are WAV (PCM 16-bit, 48 kHz): there is no ffmpeg on the Python side.

## Local run

`make render-fixture` runs the synthetic fixture on CPU with Kokoro. `make test` runs unit tests;
`make test-render` audits all 10 templates, both orientations and hi/ar/ja in real Chrome.

## Known limits and open items

- Safe-zone numbers (top 220, bottom 420, sides 60) come from `config/quality.yaml` and are not verified
  against the live YouTube Shorts and Instagram Reels UI overlays.
- WER on Indic languages with Whisper may exceed the 3% gate even for good audio; the gate is blocking as
  configured. Calibrate on the first approved videos (threshold changes need owner approval).
- CPU real-time factors for Chatterbox and Indic Parler on a 4 vCPU runner are not measured yet. Each TTS job
  logs `rtf=<x>` (a number); read the first CI runs. Kokoro measured 0.21 on a 10-core laptop.

## Notes for the private repo
- The private repo must gate on `qa_*.json` (`passed: true`) and `status_<lang>.json` (`voice: false` means that
  language is captions only); `master.mp4` is uploaded even when QA fails.
- `job_id` appears in the public Actions UI (concurrency group): use an opaque id, not a topic slug.
- A4 checks the planned visual beats the renderer animates, not measured frame differences.
- Schema errors in logs show only the path and validator, never values.
