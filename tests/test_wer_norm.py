import pytest
from ullaslab_engine.asr import error_rate
from ullaslab_engine.wer_norm import canonical_for_wer as c

PAIRS = [
    ("Rate is 5.50 percent today", "rate is 5.5% today"),
    ("It rose 25 bp", "It rose 25 basis points"),
    ("Up 25 bps", "up twenty five basis points"),
    ("Ceiling 5.75 percent", "ceiling five point seven five per cent"),
    ("the 7 October decision", "the 7th of October decision"),
    ("on 2026-10-07 it moved", "on October 7th, 2026 it moved"),
    ("on 7 October 2026 it moved", "on the seventh of October, twenty twenty-six it moved"),
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


def test_wer_zero_for_spelling_variants():
    ref = "The repo rate is 5.50 percent, as of the 7 October decision. Moves of 25 bp are common."
    hyp = "The repo rate is 5.5% as of the 7th October decision. Moves of 25 basis points are common."
    assert error_rate(ref, hyp, "en") == 0.0
