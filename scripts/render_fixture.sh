#!/usr/bin/env bash
# Render the synthetic fixture end to end on CPU with a stock voice (Kokoro). No secrets, no R2.
# Network use: one-time model downloads (Kokoro, faster-whisper) and Remotion's headless Chrome.
set -euo pipefail
cd "$(dirname "$0")/.."
WORK="${WORK:-out/fixture}"
rm -rf "$WORK" && mkdir -p "$WORK"
cp -r fixtures/fixture-bundle "$WORK/bundle"
export ULLASLAB_TTS_FORCE="${ULLASLAB_TTS_FORCE:-kokoro}"
export ULLASLAB_ASR_MODEL="${ULLASLAB_ASR_MODEL:-small}"
PY=".venv/bin/python -m ullaslab_engine"
$PY tts --work "$WORK" --lang en
$PY captions --work "$WORK" --lang en
$PY render --work "$WORK"
$PY qa --work "$WORK" --lang en
echo "master:   $WORK/en/master/video.mp4"
echo "captions: $WORK/en/captions.srt $WORK/en/captions.vtt"
echo "qa:       $WORK/en/master/qa.json"
