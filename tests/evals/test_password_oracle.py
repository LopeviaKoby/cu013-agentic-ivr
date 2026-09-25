"""Unit tests for the evaluation-only spoken-password oracle.

The oracle is test tooling: it never runs in the runtime and it stores no
password. These tests pin its closed verdict vocabulary and its order/case
handling with synthetic values.
"""

from evals.password_oracle import decode_match, match_count, spoken_variants


def test_spoken_variants_cover_case_and_symbols() -> None:
    assert "a mayuscula" in spoken_variants("A")
    assert "a minuscula" in spoken_variants("a")
    assert "uno" in spoken_variants("1")
    assert "dolar" in spoken_variants("$")
    assert "interrogacion" in spoken_variants("?")


def test_decode_match_full_partial_none_and_order() -> None:
    assert decode_match("A1b", "A mayúscula, uno, be") == "full"
    assert decode_match("A1b", "A mayúscula y uno") == "partial"
    assert decode_match("A1b", "no te escuché") == "none"
    # Out-of-order characters do not count as a full match.
    assert decode_match("AB", "be, a") == "partial"


def test_match_count_ignores_accents_and_extra_prose() -> None:
    assert match_count("Qx9", "creo que es cu, equis, nueve") == 3
    assert match_count("z", "zeta") == 1
    assert match_count("", "zeta") == 0
