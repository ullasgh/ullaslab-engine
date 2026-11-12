# Dispatch protocol (private content repo to this engine)

This repo is public. It holds no content, no voice sample and no scripts. Everything arrives and leaves through presigned
R2 URLs (S3 domain) in a `repository_dispatch` payload. The URLs live 3 h 15 min (the private repo's 3 h poll window plus
runner queueing), because the dub jobs fetch and every job uploads only after the master job. The one repository secret is
`PIXABAY_API_KEY` (stock-footage search), given to the studio render step only. The shape contract is
`schema/payload.schema.json` (vendored verbatim by the private repo and checked there by a test).

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
    "model": {"url": "https://...  (GET, tar of the Indic Parler-TTS Hugging Face cache; only when a language needs it)",
              "sha256": "<64 hex of the tar>", "revision": "<40 hex model commit>", "size": 3900000000},
    "languages": ["en", "hi", "ta"],
    "studio": {"music_urls": {"<ledger file name>.mp3": "https://...  (GET, licensed music bed files named in config/music_ledger.yaml)"}},
    "outputs": {
      "master.mp4": "PUT url", "timing_en.json": "PUT url",
      "audio_en.wav": "PUT url", "audio_hi.wav": "PUT url",
      "captions_en.srt": "PUT url", "captions_en.vtt": "PUT url", "captions_hi.srt": "PUT url",
      "hi_vertical.mp4": "PUT url",
      "qa_en.json": "PUT url", "qa_hi.json": "PUT url", "qa_hi_vertical.json": "PUT url",
      "studio_reel.mp4": "PUT url", "studio_captions_reel.srt": "PUT url", "studio_thumb.png": "PUT url",
      "studio_contact_sheet_short.png": "PUT url", "studio_qc.json": "PUT url", "studio_publish.md": "PUT url",
      "studio_log.txt": "PUT url"
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

## Parler weights (`model`, optional)

The seven Indic stock-voice languages (ta, te, kn, ml, mr, bn, gu) use `ai4bharat/indic-parler-tts`, which is gated on Hugging Face. This repo holds
no Hugging Face token. The owner mirrors a pinned revision into his private R2 bucket (`ops/owner/parler-mirror.sh` in the private repo) and the
private repo adds `model` (one presigned GET URL plus non-secret `sha256`, `revision`, `size`) only when a job language uses Parler as its primary engine.
It is one nested property, so the payload stays at 8 of GitHub's 10 `client_payload` properties.

- Every `dub` job whose matrix `extras` contain `parler` restores `actions/cache` keyed `parler-model-v1-<revision>` (path `~/.cache/ullaslab-parler`),
  then runs `fetch-model`: on a cache hit (marker `.ok-<sha256>`) it downloads nothing; otherwise it downloads, checks size and sha256, rejects any
  tar entry outside `models--*` (or links leaving the cache), extracts and deletes the tar. A sha256 mismatch fails the job and removes everything.
- The TTS step exports `HF_HUB_CACHE=<that hub>`, `HF_HUB_OFFLINE=1` and `TRANSFORMERS_OFFLINE=1` for Parler only, so it cannot reach Hugging Face. Other steps are unchanged.
- The URL is masked first in every job like the others. Without `model` the Parler languages degrade to captions only, as before.
- Tar layout: a Hugging Face hub cache (`models--ai4bharat--indic-parler-tts` and `models--google--flan-t5-large`, tokenizer files only, each with `refs/main`).
- Cost: R2 egress is free; the cache entry (about 4 GB) counts against the repo's 10 GB cache limit, so a download happens at most once per cache lifetime.

## Bundle (zip)

```
manifest.json            schema/manifest.schema.json
charts/*.json            schema/chart.schema.json
studio/<files>           WP8: the studio queue item (manifest `studio.files`): scenes.json, meta.json,
                         charts.resolved.json, optional visual_data.json and sources.md
```

`studio` (WP8, required by the master job): `primary` (the output published as `master.mp4`: `long` for long-form, `short`
else `reel` for a Short), `outputs` (exactly the outputs in scenes.json), `files`, `target_wpm` (narration pace, 150).

`manifest.json`: slug, orientation (`vertical` 1080x1920 or `horizontal` 1920x1080), `format` 1 to 10 (selects
the template), `languages`, `segments` (id plus text per language; narration unit and caption unit),
`scenes` (kind, segment ids, chart, headline/body/items as plain string or `{lang: text}`), `disclaimer`,
and `variants` such as `{"name": "hi_vertical", "lang": "hi", "orientation": "vertical"}`.

Chart JSON: `line`, `bar`, `compare`, `delta`, `counter`; every chart needs `source` (name, as_of),
`freshness` (LIVE, RECENT, LAGGED, EXPECTATION, INFERRED). `claim_id` is required (A1). `chart_hash`, when
present, must equal the SHA-256 of the canonical JSON without that key (`qa.chart_hash`).

## Job flow (`.github/workflows/render.yml`)

1. `plan`: validates the payload, outputs the dub matrix and the extras each language needs.
2. `master` (WP8, the V2 studio path, `docs/studio.md` "On GitHub Actions"): fetch, rebuild the studio item, one narration
   per output (Chatterbox clone of the reference, pace target), `studio run --asr faster` (per-scene cache, styles, mix,
   package, studio QC), export and QA, upload. Writes `timing_en.json` (the manifest's English segments aligned to the
   published output's words) so the dubs line up with `master.mp4`. Timeout 120 min.
3. `dub` (matrix, one job per language): TTS (clone or stock voice per `config/languages.yaml`), translated
   captions timed from the English segment windows, slot-aligned dub audio, A1 to A5 QA, upload. A language
   with no usable voice (for example Arabic when cloning fails) degrades to captions only.
   `variants` for the language (the Hindi vertical cut) are rendered from a natural-timeline Hindi track. Timeout 50 min.
4. `workflow_dispatch` (by hand, input `fixture`): the master job on the synthetic public-safe fixture
   (`studio/fixture.py`: generic text, a reference voice made with the Kokoro stock voice, generated footage), no payload,
   no fetch, no upload; it prints the studio log and the numbers. Use it to prove a change on a branch:
   `gh workflow run render --ref <branch> -f fixture=studio-short`.

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
- Studio-path logs: the voice and studio steps write to `work/logs/studio.log` (errors there can quote script text). It is
  uploaded only by presigned PUT as `studio_log.txt`; the public Actions log shows exit codes, stage names and gate numbers.
- `job_id` appears in the public Actions UI (concurrency group): use an opaque id, not a topic slug.
- A4 checks the planned visual beats the renderer animates, not measured frame differences.
- Schema errors in logs show only the path and validator, never values.
