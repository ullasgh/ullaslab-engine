# Studio CLI (WP4)

`uv run ullaslab-engine studio run <queue-item> [--preview] [--until STAGE] [--force] [--asr auto|mlx|faster]`

Stages (each checkpoints in `<item>/work/studio.json`; a rerun skips completed stages whose inputs are unchanged):
`timings -> broll -> assemble -> render -> mix -> package`.

Inputs in the queue item: `scenes.json` (director, schema v1), `voice.<output>.wav` or `voice.wav` (Chatterbox clone), resolved
`chart_specs.json` (or `charts.resolved.json`; entries are engine charts or kit charts), optional `visual_data.json`
(map/globe/timeline/flow data keyed by `data_ref.ref` or scene id), optional `meta.json` (`title`, `title_options`, `hashtags`).

- timings: mlx-whisper large-v3-turbo on Apple Silicon, faster-whisper elsewhere; words are text-aligned to each output's narration
  (numbers and punctuation normalised, fuzzy match). Coverage under 95% fails. Writes `work/scenes.timed.json` (`start_s`, `end_s`, `words`).
- broll: WP2 `broll fetch` unless the asset ledger already covers every footage scene.
- assemble/render: one Remotion `StudioVideo` per output (long 1920x1080, short/reel 1080x1920), burned-in word-highlight captions
  inside the safe box, localised "Illustrative footage" tag. `--preview` renders at half resolution into `preview/<output>.mp4`.
- mix: narration, music and SFX stems stay in `work/<mode>/stems/<output>/`; the music bed is light and calm (piano/ambient, no vocals) and is ducked by an envelope (`apply_duck`): about 20 dB or more below the voice while narration is active (K-weighted), a gentle rise (+9 dB) only in the intro, the outro and pauses longer than 1 s, smooth attack/release with lookahead. Levels live in the `MIX:` block of `config/quality.yaml`. ffmpeg loudnorm two-pass to
  -14 LUFS, true peak <= -1 dBTP (target -1.5); mux AAC 48 kHz, faststart.
- package: `long.mp4 short.mp4 reel.mp4 thumb.png captions.<output>.srt cost.md assets.md publish.md`. Finals are versioned
  (`long.v2.mp4`, ...) and never overwritten.

Music: `config/music_ledger.yaml` + `assets/music/` (Pixabay Music with licence recorded, or CC0). YouTube Audio Library tracks are
refused. With no track the studio generates a CC0 pad. SFX are synthesised in-house with ffmpeg.

Tests: `pytest tests/test_studio.py`; real dry-run `make studio-e2e` (needs macOS `say`, mlx-whisper, node + Chrome).
Known limits: word alignment assumes space-delimited languages. ja (and zh) are not supported: `studio run --lang ja` stops with a clear message instead of failing silently; non-English "Illustrative footage" strings are machine-seeded
and need native review before first publication.

## Automated QC (`studio qc <item>`, final stage of `studio run`)
`ullaslab-engine studio qc <item> [--preview]` (also run by `studio run`, which now defaults to `--until qc`) checks the latest
`long`, `short`, `reel` mp4s and writes `qc.md`, `qc.json` and `contact_sheet.<output>.png` (4x6 frames, timestamped) into the queue
folder. Each check is PASS / WARN / FAIL; the overall verdict is the worst one, and `studio qc` exits 1 on FAIL. Code: `studio/qc.py`;
thresholds are `DEFAULTS` there and can be overridden in a `QC:` block of `config/quality.yaml`.

| Group | Check | Fails when |
|---|---|---|
| spec | video/audio format, duration, faststart | wrong size (1920x1080 long, 1080x1920 short/reel; half in preview), not 30 fps H.264 yuv420p, not AAC 48 kHz, duration differs from the voice track by more than 0.5 s, moov after mdat |
| visual | black frames | black segment >= 0.5 s that is not a start/end fade (<= 1 s) or a `dip_to_black` transition |
| visual | frozen frames | frozen >= 2 s unless inside a scene marked `"hold": true` in scenes.json |
| visual | repeated assets | same asset sha256 used by two scenes of one output (assets.json) |
| visual | near-duplicate shots | perceptual signature (16x16 grey thumbnail at 1 fps, shots split on jumps and scene starts) within 0.12 of another shot; FAIL for footage/unscened video, WARN between non-footage scenes |
| audio | narration / mix silence | silence > 1.5 s (-45 dB) in the voice track or the final mix |
| audio | loudness | integrated outside -14 +-1 LUFS, true peak above -1 dBTP, or any run of >= 3 samples at full scale |
| captions | layout limits, safe area, SRT sync | cue over 2 lines / 32 chars; caption plate located outside the renderer safe box in sampled frames (OCR-free colour locator; WARN when the plate cannot be told from the backdrop); SRT start/end drift over 150 ms from the aligned word timings (the deliberate 0.35 s hold after a cue is allowed) |
| data | data_ref, chart hash, tags, footage ledger, deny-list | chart `data_ref` not in chart specs; `chart_hash` (spec or sources.md) differs from the computed hash (WARN when none recorded); chart without a LIVE/RECENT/LAGGED/EXPECTATION/INFERRED tag or on-screen number without a tagged sources.md row; footage scene without a complete ledger entry or `illustrative` flag; Schwab / FYERS / NSE feed / Atlas / yfinance / investing.com in on-screen text, refs or captions |
| platform | disclaimer first line, end line, on-screen labels, synthetic voice, AI label | full disclaimer not the first description line in publish.md / meta.json; a video does not end with "Follow UllasLab." (spoken) or lacks the end card; a freshness tag word (LIVE / RECENT / LAGGED / EXPECTATION / INFERRED) or a "Not SEBI/SEC registered" / "Data may be delayed" read-out in on-screen text, captions or narration; `synthetic_voice` not true in meta.json; no AI disclosure recommendation (publish.md or `ai_label`) |

QC reads the render's own props (`work/<mode>/props.<output>.json`) and `work/scenes.timed.json`, so what it checks is what was rendered.

## Video ending and on-screen labels (owner decisions 2026-11-09; sign-off shortened 2026-11-13)
Every video (Short, Reel, long-form, all 13 languages) ends with "Follow UllasLab." spoken and on the end card ("Education only" is no longer said or shown; an item whose narration still ends with the retired two-sentence line FAILS the end-line check; ships together with content PR 71) (`remotion/src/studio/EndCard.tsx`, last 3 s, inside the safe area; strings in `src/ullaslab_engine/endline.py` and `remotion/src/brand.ts`). The full disclaimer is the first line of the YouTube description and the Instagram caption (`publish.md`). Freshness tags are never drawn: charts show only "Source: <name> · <as-of>"; the tags stay in the data ledgers and QC still requires every number to be tagged there.

## On GitHub Actions (WP8)
The unattended render runs the studio in `.github/workflows/render.yml` (`master` job, ubuntu-24.04, CPU, headless Chrome,
ffmpeg from apt). Code: `studio/actions.py`, `studio/safe_audit.py`, `studio/fixture.py`.

1. `fetch --studio` (presigned bundle, the owner's reference and clips, licensed music files) and `studio-prepare`
   (rebuilds the queue item in `work/item` from `bundle/studio/`, checks it against the manifest `studio` block).
2. `studio-voice`: one narration per output (`narrate()`, Chatterbox clone of `work/voice.wav` / `work/clips/clipN.wav`,
   pace target from the bundle, 150 wpm); outputs with the same narration share one synthesis. The chunk cache lives in
   `work/tts_cache` and is never cached by Actions.
3. `studio run work/item --asr faster` (faster-whisper large-v3 int8; mlx-whisper is macOS only).
4. `studio-export`: `master.mp4` = the published output (manifest `studio.primary`), `studio_<output>.mp4` for the others,
   captions (SRT + VTT), `audio_en.wav` (the published output's narration at -14 LUFS), `timing_en.json` for the dubs and
   the story, `status_en.json`, and `qa_en.json`.

`qa_en.json` gates (limits from `config/quality.yaml`, unchanged):
- A1 claim ids and chart hashes; A2 chart scenes in the published output; A3 on the published narration (loudness, true peak,
  silence, wpm 135-175, sentence length, WER <= 3% against the narrated text with the words the timings stage transcribed);
  duration (30-60 s Short, 6-10 min long-form).
- A4 on every output's voice-timed scenes: hook scene starts within 3 s, every scene except the end-line scene lasts 2-12 s,
  and the picture-change limits are checked on the measured picture: studio QC's frozen-frame detection (fails at 2 s, below
  both A4 change limits) must pass, and a scene marked `hold` may not last longer than `max_static_frame_s`.
- A5 from a layout audit (one still per timed scene of every output, `audit` on): nothing outside the safe zone (content box
  for headline, body, label, axis and stamp; safe box for captions, end card and footage tag), body roles (headline, body,
  caption) at least 44 px and label roles (label, axis, stamp, tag) at least 36 px, contrast at least 4.5:1, at most 12 words of
  headline, body and label text per still. Studio text set at label size carries the `label` role; a chart's unit and period
  line is `axis` (exempt from the word budget like axis tick labels in `qa.gate_a5`).
- Studio QC verdict (any FAIL fails), and `runner_budget` when the voice step refused the item (below).

Runner budget: Chatterbox on the runner's CPU ran at 11.6x to 15.6x real time (37 s of speech took 429 s; 41 s took 641 s on
run 43178997058); the guard uses 16 (`RUNNER_RTF`). `studio-voice` projects
the synthesis time of the item's distinct narrations at 150 wpm and that rate and refuses, before any synthesis, an item over
`ULLASLAB_VOICE_BUDGET_MIN` (60 in render.yml), so the job fails in seconds with a `runner_budget` gate instead of timing out.
A daily Short (about 130 words, about 14 min of synthesis per distinct narration) fits; a 6-10 min long-form does not and
renders locally (`studio run`) until a faster voice path exists. Job timeouts: plan 5, master 120, dub 50 minutes (175 min,
inside the private repo's 3 h poll window and the 3 h 15 min URL lifetime).

Logs: everything the voice and studio steps print goes to `work/logs/studio.log`, uploaded privately as `studio_log.txt`; the
public log shows exit codes, stage names and gate numbers (`tests/test_workflows.py` enforces this). Proof runs:
`gh workflow run render --ref <branch> -f fixture=studio-short` renders the synthetic fixture and uploads nothing.

What the first Actions fixture runs showed, and the fixes (no limit changed):
- A3 wpm 172-183 (limit 175): Chatterbox read faster than the 150 wpm target and the pacer only ever sped speech up. The
  pacer now works both ways (`voice/narrate.py fit_pace`): a fast read is slowed by tempo (at most `max_slowdown` 1.15),
  then punctuation pauses grow (at most `pause_ceiling` 1.3, never past 0.55 s), and the engine's own mid-sentence pauses
  stretched by the slow-down are capped too, so A3 max_silence_s (1.2 s) still holds. Fixture: 153.9 wpm, 1.02 s.
- A3 WER: Whisper writes numbers as digits while scripts often spell them, splits some ("100 and 12"), and heard the
  sign-off brand as "Ullis lab". `wer_norm` turns spelled cardinals into digits and joins split numbers on both sides, the
  ASR prompt carries the sign-off spelling, and the lexicon speaks the brand as "Ullas Lab". Fixture: 7.5% -> 2.0%.
- A5: the audit found a chart's end value label 13 px past the safe box on a vertical chart; the label now goes left of
  the line's tip when it would not fit.

Known limits: the footage search needs the repository secret `PIXABAY_API_KEY` (without it a footage scene fails the render
unless the director used none); the b-roll history that avoids reusing a clip across episodes starts empty on every runner;
the CLIP ranker (`rank` extra) is not installed on the runner, so the keyword ranker picks footage.
