import pytest
from ullaslab_engine.asr import error_rate
from ullaslab_engine.wer_norm import canonical_for_wer as c

PAIRS = [
    ("Rate is 5.50 percent today", "rate is 5.5% today"),
    ("It rose 25 bp", "It rose 25 basis points"),
    ("Up 25 bps", "up 25 basis points"),
    ("Ceiling 5.75 percent", "ceiling 5.75 per cent"),
    ("the 7 October decision", "the 7th of October decision"),
    ("on 2026-10-07 it moved", "on October 7th, 2026 it moved"),
    ("on 7 October 2026 it moved", "on the 7th of October, 2026 it moved"),
    ("rate 5.25%", "rate 5 ,25%"),
    ("Not SEBI/SEC registered", "Not SEBI SEC registered"),
    ("the RBI lends", "the R B I lends"),
    ("1,250 units", "1250 units"),
    ("A floor-and-ceiling model", "a floor and ceiling model"),
]


@pytest.mark.parametrize("a,b", PAIRS)
def test_equivalent_forms_match(a, b):
    assert c(a) == c(b)


def test_real_difference_kept():
    assert c("rate is 5.50 percent") != c("rate is 5.25 percent")
    assert error_rate("one two three four", "one two three five", "en") == 25.0


def test_tts_spells_central_bank_acronyms():
    from ullaslab_engine.voice.textnorm import normalize_text
    assert normalize_text("the RBI and MPC", "en") == "the R B I and M P C"


def test_wer_zero_for_spelling_variants():
    ref = "The repo rate is 5.50 percent, as of the 7 October decision. Moves of 25 bp are common."
    hyp = "The repo rate is 5.5% as of the 7th October decision. Moves of 25 basis points are common."
    assert error_rate(ref, hyp, "en") == 0.0


def test_compound_tokens_merge():
    assert error_rate("not sebi sec registered", "not sebisec registered", "en") == 0.0
    assert error_rate("not sebisec registered", "not sebi sec registered", "en") == 0.0


def test_pipeline_tts_verbalises_script_before_the_engine(monkeypatch):
    from ullaslab_engine import pipeline as P
    seen = []
    monkeypatch.setattr(P, "_raw_tts", lambda text, lang, ref, **kw: seen.append(text))
    P.default_tts("The RBI rate is 5.25 percent.", "en", None)
    assert seen == ["The R B I rate is five point two five percent."]


# --- non-Latin scripts: marks are part of the word (the old \w pattern split every Indic word at its vowel signs) ---
SCRIPTS = {
    "hi": ("दर 4.25 प्रतिशत है, निवेश सलाह नहीं।", ["दर", "425", "प्रतिशत", "है", "निवेश", "सलाह", "नहीं"]),
    "ta": ("வட்டி விகிதம் உயர்ந்தது, கல்வி மட்டும்.", ["வட்டி", "விகிதம்", "உயர்ந்தது", "கல்வி", "மட்டும்"]),
    "bn": ("সুদের হার বেড়েছে, শুধু শিক্ষা।", ["সুদের", "হার", "বেড়েছে", "শুধু", "শিক্ষা"]),
    "te": ("వడ్డీ రేటు పెరిగింది, విద్య మాత్రమే.", ["వడ్డీ", "రేటు", "పెరిగింది", "విద్య", "మాత్రమే"]),
    "kn": ("ಬಡ್ಡಿ ದರ ಏರಿತು, ಶಿಕ್ಷಣ ಮಾತ್ರ.", ["ಬಡ್ಡಿ", "ದರ", "ಏರಿತು", "ಶಿಕ್ಷಣ", "ಮಾತ್ರ"]),
    "ml": ("പലിശ നിരക്ക് ഉയർന്നു, വിദ്യാഭ്യാസം മാത്രം.", ["പലിശ", "നിരക്ക്", "ഉയർന്നു", "വിദ്യാഭ്യാസം", "മാത്രം"]),
    "gu": ("વ્યાજ દર વધ્યો, ફક્ત શિક્ષણ.", ["વ્યાજ", "દર", "વધ્યો", "ફક્ત", "શિક્ષણ"]),
}


@pytest.mark.parametrize("lang", sorted(SCRIPTS))
def test_indic_words_stay_whole(lang):
    text, want = SCRIPTS[lang]
    assert c(text, lang).split() == want


def test_indic_identical_text_is_zero_error_and_one_wrong_word_is_one_error():
    text = SCRIPTS["hi"][0]
    assert error_rate(text, text, "hi") == 0.0
    other = text.replace("सलाह", "सलाम")
    assert error_rate(text, other, "hi") == pytest.approx(100 / 7)


def test_zero_width_joiners_are_removed_not_split():
    assert c("ക്‍", "ml") == c("ക്", "ml")              # chillu with ZWJ == without
    assert c("क्‍ष", "hi") == c("क्ष", "hi") and len(c("क्‍ष", "hi").split()) == 1
    assert c("می‌خواهم", "fa").split() == [c("میخواهم", "fa")]


def test_arabic_short_vowels_are_removed_not_split():
    assert c("كَتَبَ الوَلَدُ", "ar") == c("كتب الولد", "ar") == "كتب الولد"
    assert c("مُحَمَّد", "ar") == "محمد"


def test_marks_survive_and_punctuation_symbols_go():
    assert c("दर: 5%, ₹10 + १२", "hi") == "दर 5 percent 10 १२"


@pytest.mark.parametrize("lang,text,want", [
    ("en", "The rate's up 0.5 percentage points; it's a_b.", "the rate s up 05 percentage points it s a_b"),
    ("es", "La tasa subió; ¿está bien? Sí.", "la tasa subió está bien sí"),
    ("pt", "Ação rápida, não é 1,234 vezes.", "ação rápida não é 1234 vezes"),
    ("ja", "金利は上がった。ＡＢＣ１２３、です。", "金利は上がった abc123 です"),
])
def test_latin_and_japanese_results_unchanged(lang, text, want):
    assert c(text, lang) == want


def test_japanese_still_uses_the_character_error_rate():
    assert error_rate("金利は上がった", "金利は上がった", "ja") == 0.0
    assert 0 < error_rate("金利は上がった", "金利が上がった", "ja") < 30
