"""Tests for the Markdown code-fence scanner."""

from __future__ import annotations

from quarry.fence import FenceScanner


def _shield_flags(text: str) -> list[bool]:
    """Return the per-line shield decision for *text* (keepends split)."""
    scanner = FenceScanner()
    return [scanner.shields(line) for line in text.splitlines(keepends=True)]


def test_plain_lines_are_never_shielded() -> None:
    assert _shield_flags("alpha\nbeta\n") == [False, False]


def test_fenced_block_shields_open_body_and_close() -> None:
    assert _shield_flags("```\nbody\n```\nafter\n") == [True, True, True, False]


def test_indented_backticks_do_not_open_a_fence() -> None:
    """An indented ``` is code-block content, not a fence delimiter."""
    assert _shield_flags("top\n    ```\nstill top\n") == [False, True, False]


def test_tilde_line_does_not_close_a_backtick_fence() -> None:
    """A fence closes only on the SAME character; ~~~ leaves a ```-fence open."""
    flags = _shield_flags("```\n~~~\ninside\n```\nafter\n")
    assert flags == [True, True, True, True, False]


def test_backtick_line_does_not_close_a_tilde_fence() -> None:
    flags = _shield_flags("~~~\n```\ninside\n~~~\nafter\n")
    assert flags == [True, True, True, True, False]


def test_shorter_run_does_not_close_a_longer_fence() -> None:
    """A 3-backtick line cannot close a 4-backtick fence (length < opener)."""
    flags = _shield_flags("````\n```\ninside\n````\nafter\n")
    assert flags == [True, True, True, True, False]


def test_longer_run_closes_a_shorter_fence() -> None:
    flags = _shield_flags("```\n````\nafter\n")
    assert flags == [True, True, False]


def test_info_string_after_fence_still_opens() -> None:
    assert _shield_flags("```python\ncode\n```\ndone\n") == [True, True, True, False]


def test_indented_line_inside_fence_does_not_close_it() -> None:
    """An indented line inside a fence is literal content, never a closer."""
    flags = _shield_flags("```\n    ```\ninside\n```\nafter\n")
    assert flags == [True, True, True, True, False]


def test_info_string_line_does_not_close_a_fence() -> None:
    """A closing fence carries only whitespace; a ```note line keeps it open."""
    flags = _shield_flags("```\n```note\ninside\n```\nafter\n")
    assert flags == [True, True, True, True, False]


def test_trailing_whitespace_after_closer_still_closes() -> None:
    """Spaces/tabs after the closing marker are allowed (CommonMark §4.5)."""
    flags = _shield_flags("```\nbody\n```   \nafter\n")
    assert flags == [True, True, True, False]
