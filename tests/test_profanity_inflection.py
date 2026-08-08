"""Tests for quarry.profanity_inflection — English inflection expansion."""

from __future__ import annotations

import pytest

from quarry.profanity_inflection import ProfanityInflector


@pytest.mark.parametrize(
    "base,expected",
    [
        ("fuck", "fucking"),
        ("fuck", "fucked"),
        ("idiot", "idiots"),
        ("shit", "shitting"),
        ("shit", "shitted"),
        ("crap", "crapped"),
        ("crap", "crapping"),
        ("bitch", "bitches"),
        ("bitch", "bitching"),
        ("damn", "damning"),
        ("stupid", "stupider"),
        ("dumb", "dumber"),
        ("asshole", "assholes"),
        ("douche", "douching"),
        ("douche", "douched"),
    ],
)
def test_expand_covers_inflected_form(base: str, expected: str) -> None:
    assert expected in ProfanityInflector().expand([base])


def test_expand_always_includes_the_base_word() -> None:
    assert "fuck" in ProfanityInflector().expand(["fuck"])


def test_expand_excludes_dicker_real_word_collision() -> None:
    forms = ProfanityInflector().expand(["dick"])
    assert "dicker" not in forms
    assert "dickers" not in forms


def test_expand_excludes_heller_surname_collision() -> None:
    forms = ProfanityInflector().expand(["hell"])
    assert "heller" not in forms
    assert "hellers" not in forms


def test_expand_empty_bases_returns_empty_set() -> None:
    assert ProfanityInflector().expand([]) == frozenset()
