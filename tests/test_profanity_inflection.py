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


def test_expand_excludes_craps_real_word_collision() -> None:
    """ "craps" (the dice game) is a real word, unrelated to "crap"."""
    forms = ProfanityInflector().expand(["crap"])
    assert "craps" not in forms


def test_expand_excludes_jerker_real_word_collision() -> None:
    """ "jerker" (archaic: one who jerks, e.g. "soda jerker") is a real word."""
    forms = ProfanityInflector().expand(["jerk"])
    assert "jerker" not in forms
    assert "jerkers" not in forms


def test_expand_does_not_exclude_crapper_slang() -> None:
    """ "crapper"/"crappers" (toilet slang) is not a real dictionary word."""
    forms = ProfanityInflector().expand(["crap"])
    assert "crapper" in forms
    assert "crappers" in forms


@pytest.mark.parametrize(
    "base,form",
    [
        ("damn", "damned"),
        ("damn", "damning"),
        ("damn", "damner"),
    ],
)
def test_expand_keeps_same_lexeme_inflections_of_damn(base: str, form: str) -> None:
    """ "damned"/"damning"/"damner" are damn's OWN paradigm, not a collision.

    Unlike dicker/heller/jerker/craps (separate, unrelated lexemes that
    happen to collide in spelling), these are direct morphological
    inflections of the listed word itself -- the same standard this
    scrubber already applies to base words (e.g. "hell" redacts even in
    "what the hell", with no sense discrimination).
    """
    assert form in ProfanityInflector().expand([base])


# Every real-dictionary hit found by cross-checking every generated form of
# every DEFAULT_PROFANITY word against /usr/share/dict/{web2,web2a,
# propernames} -- after "craps", an untested -s/-es plural, was found
# colliding with the dice game. Hardcoded rather than re-run against the
# live filesystem dictionary at test time: portable across CI environments
# that may not ship /usr/share/dict, and pins the exact audit result as a
# regression guard rather than re-deriving it.
_AUDITED_DICTIONARY_HITS: dict[str, frozenset[str]] = {
    "crap": frozenset({"craps"}),
    "damn": frozenset({"damned", "damner", "damning"}),
    "dick": frozenset({"dicker"}),
    "hell": frozenset({"heller"}),
    "jerk": frozenset({"jerker"}),
}
# Of those, the ones that must NOT appear in expand()'s output: separate,
# unrelated lexemes that happen to collide in spelling. "damned"/"damning"/
# "damner" are damn's own paradigm (see test above) and are expected to
# remain.
_MUST_BE_EXCLUDED = frozenset({"craps", "dicker", "heller", "jerker"})


@pytest.mark.parametrize("base", sorted(_AUDITED_DICTIONARY_HITS))
def test_expand_excludes_every_audited_unrelated_collision(base: str) -> None:
    """Regression guard for the full by-hand collision audit across all forms.

    "craps" slipped through an ``-er``-only audit because it is an ``-s``
    plural, not an agent noun. This test pins every dictionary collision
    found by auditing ALL inflection classes (-s/-es, -ed, -ing, -er/-ers)
    for all 19 DEFAULT_PROFANITY words, so a future regression in any class
    is caught the same way this one should have been.
    """
    forms = ProfanityInflector().expand([base])
    for hit in _AUDITED_DICTIONARY_HITS[base]:
        if hit in _MUST_BE_EXCLUDED:
            assert hit not in forms, f"{hit!r} is a real word colliding with {base!r}"
        else:
            assert hit in forms, f"{hit!r} is {base!r}'s own paradigm, expected present"


@pytest.mark.parametrize(
    "form",
    ["moronned", "moronning", "moronner", "moronners"],
)
def test_expand_does_not_double_final_consonant_of_disyllabic_moron(
    form: str,
) -> None:
    """ "moron" is stressed on its first syllable — English doesn't double.

    Doubling ("morON" -> "moronned") is only correct for a stressed final
    syllable; "moron" is the one 5-character CVC-shaped word on the list
    that isn't monosyllabic, so it must not double.
    """
    assert form not in ProfanityInflector().expand(["moron"])


@pytest.mark.parametrize(
    "base,doubled_form",
    [
        ("crap", "crapped"),
        ("crap", "crapping"),
        ("shit", "shitted"),
        ("shit", "shitting"),
    ],
)
def test_expand_still_doubles_true_monosyllables(base: str, doubled_form: str) -> None:
    """The moron fix must not regress genuine monosyllabic doubling."""
    assert doubled_form in ProfanityInflector().expand([base])


def test_expand_empty_bases_returns_empty_set() -> None:
    assert ProfanityInflector().expand([]) == frozenset()
