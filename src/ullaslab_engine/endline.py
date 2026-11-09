"""The in-video end line (owner decision 2026-11-09): every video ends with "Follow UllasLab. Education only."
spoken and on screen, in all 13 languages. The full standard disclaimer lives in the description / caption
(studio/pack.py DISCLAIMER), not in the video. Keep in sync with END_LINES in remotion/src/brand.ts and with
`end_line` in the content repo's config/glossary/<lang>.yaml (machine-seeded; native review owed)."""
from __future__ import annotations
import re

END_LINES: dict[str, str] = {
    "en": "Follow UllasLab. Education only.",
    "hi": "UllasLab को फ़ॉलो करें। केवल शिक्षा के लिए।",
    "ta": "UllasLab-ஐ பின்தொடருங்கள். கல்வி நோக்கத்திற்கு மட்டும்.",
    "te": "UllasLab ను ఫాలో అవ్వండి. విద్యా ప్రయోజనం కోసం మాత్రమే.",
    "kn": "UllasLab ಅನ್ನು ಫಾಲೋ ಮಾಡಿ. ಶಿಕ್ಷಣಕ್ಕಾಗಿ ಮಾತ್ರ.",
    "ml": "UllasLab ഫോളോ ചെയ്യൂ. വിദ്യാഭ്യാസ ആവശ്യത്തിന് മാത്രം.",
    "mr": "UllasLab ला फॉलो करा. केवळ शिक्षणासाठी.",
    "bn": "UllasLab ফলো করুন। শুধুমাত্র শিক্ষামূলক।",
    "gu": "UllasLab ને ફોલો કરો. ફક્ત શિક્ષણ માટે.",
    "es": "Sigue a UllasLab. Solo con fines educativos.",
    "pt": "Siga a UllasLab. Apenas para fins educacionais.",
    "ar": "تابع UllasLab. للأغراض التعليمية فقط.",
    "ja": "UllasLabをフォローしてください。教育目的のみ。",
}
END_CARD_S = 3.0          # the card shows over the last N seconds (or the whole last scene if shorter)
_SPLIT = re.compile(r"(?<=[.।。])\s*")


def end_line(lang: str) -> str:
    return END_LINES.get(lang) or END_LINES["en"]


def end_parts(lang: str) -> list[str]:
    """['Follow UllasLab.', 'Education only.'] - the two lines of the end card."""
    return [p for p in _SPLIT.split(end_line(lang)) if p]


def _norm(s: str) -> str:
    return re.sub(r"[\s.।。!?,]+", " ", s).strip().lower()


def ends_with_end_line(text: str, lang: str) -> bool:
    return _norm(text).endswith(_norm(end_line(lang)))
