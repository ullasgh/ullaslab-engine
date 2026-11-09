.PHONY: studio-e2e setup test test-py test-js test-render render-fixture clean
PY := .venv/bin/python

setup:
	uv venv --python 3.12 .venv
	uv sync --extra dev --extra kokoro --extra asr
	cd remotion && npm ci --no-audit --no-fund

test: test-py test-js

test-py:
	$(PY) -m pytest -q

test-js:
	cd remotion && npm run typecheck && npm test

# Real Remotion + Chrome audits of all 10 templates, both orientations, hi/ar/ja (slow, ~1-2 min).
test-render:
	RUN_RENDER=1 $(PY) -m pytest tests/test_render_smoke.py -q

# End to end on CPU with a stock voice (Kokoro). Network: model downloads and Chrome, nothing else.
render-fixture:
	scripts/render_fixture.sh

clean:
	rm -rf out work remotion/out

# Real studio dry-run (macOS: say + mlx-whisper + Remotion), 3 outputs at preview resolution.
studio-e2e:
	RUN_STUDIO_E2E=1 $(PY) -m pytest tests/test_studio.py -q -k e2e
