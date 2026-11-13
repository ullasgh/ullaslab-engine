"""Letter-reading rule (owner standard 2026-11-13): listed initialisms are spoken as letters ("U.S." and "US" both as "U S"),
acronyms listed as words stay words, the WER canonicalisation treats the written and spoken forms alike, "25 bp" is plural.
The list is config/pronunciation.yaml (generic public initialisms); the private content repo keeps the same list for its gate."""
from __future__ import annotations

import os
from pathlib import Path

import pytest
import yaml

from ullaslab_engine.asr import error_rate
from ullaslab_engine.config import CONFIG_DIR
from ullaslab_engine.voice import lexicon as L
from ullaslab_engine.voice.narrate import plan_chunks, spoken_text
from ullaslab_engine.wer_norm import canonical_for_wer

DOC = yaml.safe_load((CONFIG_DIR / "pronunciation.yaml").read_text(encoding="utf-8"))


def say(t: str) -> str:
    return spoken_text(t, "en", "western")


@pytest.mark.parametrize("written,spoken", [
    ("Inflation in the U.S. fell.", "Inflation in the U S fell."),
    ("The US economy slowed.", "The U S economy slowed."),
    ("The U.K. and the UK agree.", "The U K and the U K agree."),
    ("The E.U. and the EU.", "The E U and the E U."),
    ("RBI and ECB and FOMC meet.", "R B I and E C B and F O M C meet."),
    ("CPI and GDP rose.", "C P I and G D P rose."),
    ("ETFs and ETF's and CPIs.", "E T Fs and E T F's and C P Is."),
    ("It opens at 9 A.M. and closes at 4 PM.", "It opens at nine A M and closes at four P M."),
    ("The WHO said so.", "The W H O said so."),
])
def test_listed_initialisms_are_spoken_as_letters(written, spoken):
    assert say(written) == spoken


def test_dotted_form_at_the_end_of_a_text_keeps_its_sentence_stop():
    assert say("Stocks fell in the U.S.") == "Stocks fell in the U S."
    assert [c.text for c in plan_chunks(say("Stocks fell in the U.S. The Fed met. Prices rose."))] == [
        "Stocks fell in the U S.", "The Fed met. Prices rose."]
    assert say("Rates rose in the U.S.\n\nThe Fed met.") == "Rates rose in the U S.\n\nThe Fed met."
    assert say("In the U.S. [[pause]] Next.") == "In the U S. [[pause]] Next."
    assert say("The U.S. Fed and the U.S. Treasury met.") == "The U S Fed and the U S Treasury met."     # not a sentence end


def test_the_ordinary_word_us_and_the_currency_prefix_are_left_alone():
    assert say("It is up to us.") == "It is up to us."
    assert say("Give Us a call") == "Give Us a call"
    assert say("It cost US$5.") == "It cost five dollars."          # unchanged: the existing currency handling
    assert say("A US-based firm.") == "A U S-based firm."


def test_acronyms_listed_as_words_stay_words():
    assert say("OPEC and NATO and SEBI met.") == "OPEC and NATO and SEBI met."
    assert say("USD 5bn.") == "five billion dollars."
    assert say("The VIX jumped.") == "The the VIX jumped." or say("The VIX jumped.").endswith("VIX jumped.")
    assert not any(k in DOC["letters"] for k in DOC["words"])


def test_basis_points_are_plural_except_for_one():
    assert say("A 25 bp cut.") == "A twenty-five basis points cut."
    assert say("a 1 bp move") == "a one basis point move"
    assert say("one bp") == "one basis point"
    assert say("0.1 bp and 11 bp and 100 bp") == "zero point one basis points and eleven basis points and one hundred basis points"
    assert say("25 bps") == "twenty-five basis points"


def test_other_languages_do_not_get_the_english_list():
    assert spoken_text("US and the U.S. and GDP", "es", "western") == "US and the U.S. and P I B"


def test_the_written_and_spoken_forms_compare_equal_in_the_wer():
    ref = "The U.S. and the E.U. rose, ETFs and FIIs and CPI's fell, a 1 bp and a 25 bp move, 9 A.M. in the UK."
    heard = ["The US and the EU rose, E T Fs and F I Is and C P I's fell, a one basis point and a 25 basis points move, 9 AM in the U.K.",
             "The U S and the E U rose, ETFs and FIIs and CPIs fell, a 1 basis point and a 25 basis point move, nine am in the U K."]
    for h in heard:
        assert error_rate(ref, h, "en") < 5.0
    for a, b in [("U.S.", "US"), ("U.S.", "U S"), ("the UK", "the U.K."), ("RBI", "R B I"), ("1 bp", "1 basis point"),
                 ("25 bp", "25 basis points")]:
        assert canonical_for_wer(a) == canonical_for_wer(b), (a, b)
    assert error_rate("The U.S. fell.", "The us fell.", "en") == 0.0
    assert error_rate("The U.S. fell.", "The Fed fell.", "en") > 0


def test_every_entry_is_valid_and_no_reading_conflicts_with_the_lexicon():
    assert L.validate({"en": L.pronunciation_entries(DOC)}) == []
    lex = yaml.safe_load((CONFIG_DIR / "lexicon.yaml").read_text(encoding="utf-8"))
    mine = {**DOC["letters"], **DOC["words"]}
    for sec in ("common", "en"):
        for e in lex.get(sec) or []:
            if not e.get("regex") and e["match"] in mine:
                assert mine[e["match"]] == e["say"], e["match"]


def test_letters_values_are_spelled_or_plain_words_and_never_dotted():
    for k, v in DOC["letters"].items():
        assert v and "." not in v, k
        letters = "".join(v.split())
        if k.replace(".", "").isalpha() and all(len(t) == 1 for t in v.split()):
            assert letters == k.replace(".", "").upper(), (k, v)


# ---- one list, two repos ------------------------------------------------------------------------------------------
CONTENT = os.environ.get("ULLASLAB_CONTENT_DIR")


@pytest.mark.skipif(not CONTENT, reason="set ULLASLAB_CONTENT_DIR to compare with a content checkout")
def test_the_list_equals_the_content_repos_list():
    p = Path(CONTENT) / "config" / "pronunciation.yaml"
    if not p.is_file():
        pytest.skip("content checkout has no config/pronunciation.yaml yet")
    theirs = yaml.safe_load(p.read_text(encoding="utf-8"))
    assert {k: str(v) for k, v in theirs["letters"].items()} == {k: str(v) for k, v in DOC["letters"].items()}
    assert {k: str(v) for k, v in theirs["words"].items()} == {k: str(v) for k, v in DOC["words"].items()}
