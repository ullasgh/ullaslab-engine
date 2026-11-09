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
- mix: narration, music and SFX stems stay in `work/<mode>/stems/<output>/`; music ducked by sidechain; ffmpeg loudnorm two-pass to
  -14 LUFS, true peak <= -1 dBTP (target -1.5); mux AAC 48 kHz, faststart.
- package: `long.mp4 short.mp4 reel.mp4 thumb.png captions.<output>.srt cost.md assets.md publish.md`. Finals are versioned
  (`long.v2.mp4`, ...) and never overwritten.

Music: `config/music_ledger.yaml` + `assets/music/` (Pixabay Music with licence recorded, or CC0). YouTube Audio Library tracks are
refused. With no track the studio generates a CC0 pad. SFX are synthesised in-house with ffmpeg.

Tests: `pytest tests/test_studio.py`; real dry-run `make studio-e2e` (needs macOS `say`, mlx-whisper, node + Chrome).
Known limits: word alignment assumes space-delimited languages. ja (and zh) are not supported: `studio run --lang ja` stops with a clear message instead of failing silently; non-English "Illustrative footage" strings are machine-seeded
and need native review before first publication.
