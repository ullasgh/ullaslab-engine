#!/usr/bin/env bash
# Indic Parler-TTS (Apache-2.0) library. Pinned commit; git dependency, needs git-lfs (present on GitHub runners).
# Not in uv.lock because it pins transformers 4.46 (conflicts with chatterbox-tts) and pulls a git+LFS dependency.
set -euo pipefail
# CPU runner: the default Linux torch wheels pull the CUDA stack (several GB of nvidia-* packages, never used). Install the CPU
# build first, so the next install sees torch satisfied. Soft failure: if the CPU index is unreachable the default wheels follow.
if [ "$(uname -s)" = Linux ] && [ -z "${PARLER_KEEP_CUDA_TORCH:-}" ]; then
  uv pip install torch torchaudio --index-url https://download.pytorch.org/whl/cpu || echo "cpu torch unavailable, using the default build"
fi
# sentencepiece==0.2.0: 0.2.3 ships a pb2 module that needs protobuf>=5.26, while this stack resolves protobuf 4.25.x, so the
# T5 description tokenizer (flan-t5-large) died with "cannot import name 'runtime_version' from 'google.protobuf'".
uv pip install "sentencepiece==0.2.0" "git+https://github.com/huggingface/parler-tts.git@d108732cd57788ec86bc857d99a6cabd66663d68" "transformers==4.46.1"
