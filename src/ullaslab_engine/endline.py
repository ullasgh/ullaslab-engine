"""The in-video end line (owner decision 2026-11-13, replacing 2026-11-09): every video ends with "Follow UllasLab."
spoken and on screen, in all 13 languages; "Education only" is no longer said or shown at the end. The full standard disclaimer lives in the description / caption
(studio/pack.py DISCLAIMER), not in the video. Keep in sync with END_LINES in remotion/src/brand.ts and with
`end_line` in the content repo's config/glossary/<lang>.yaml (machine-seeded; native review owed)."""
from __future__ import annotations
import re

END_LINES: dict[str, str] = {
    "en": "Follow UllasLab.",
    "hi": "UllasLab को फ़ॉलो करें।",
    "ta": "UllasLab-ஐ பின்தொடருங்கள்.",
    "te": "UllasLab ను ఫాలో అవ్వండి.",
    "kn": "UllasLab ಅನ್ನು ಫಾಲೋ ಮಾಡಿ.",
    "ml": "UllasLab ഫോളോ ചെയ്യൂ.",
    "mr": "UllasLab ला फॉलो करा.",
    "bn": "UllasLab ফলো করুন।",
    "gu": "UllasLab ને ફોલો કરો.",
    "es": "Sigue a UllasLab.",
    "pt": "Siga a UllasLab.",
    "ar": "تابع UllasLab.",
    "ja": "UllasLabをフォローしてください。",
}
END_CARD_S = 3.0          # the card shows over the last N seconds (or the whole last scene if shorter)
_SPLIT = re.compile(r"(?<=[.।。])\s*")


def end_line(lang: str) -> str:
    return END_LINES.get(lang) or END_LINES["en"]


def end_parts(lang: str) -> list[str]:
    """['Follow UllasLab.'] - the end card is one line; the retired second sentence is gone."""
    return [p for p in _SPLIT.split(end_line(lang)) if p]


def _norm(s: str) -> str:
    return re.sub(r"[\s.।。!?,]+", " ", s).strip().lower()


# Changeover decision: an item whose narration still ends with the retired two-sentence line FAILS the end-line check
# (stricter option); the message says so. The retired wording per language is derived from nothing here: English only is
# detected by name, other languages simply do not end with the new line and fail the same way.
RETIRED_EN = "Follow UllasLab. Education only."


def is_retired_end_line(text: str) -> bool:
    return _norm(text).endswith(_norm(RETIRED_EN))


def ends_with_end_line(text: str, lang: str) -> bool:
    return _norm(text).endswith(_norm(end_line(lang)))
