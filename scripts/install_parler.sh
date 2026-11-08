#!/usr/bin/env bash
# Indic Parler-TTS (Apache-2.0) library. Pinned commit; git dependency, needs git-lfs (present on GitHub runners).
# Not in uv.lock because it pins transformers 4.46 (conflicts with chatterbox-tts) and pulls a git+LFS dependency.
set -euo pipefail
uv pip install "git+https://github.com/huggingface/parler-tts.git@d108732cd57788ec86bc857d99a6cabd66663d68" "transformers==4.46.1"
