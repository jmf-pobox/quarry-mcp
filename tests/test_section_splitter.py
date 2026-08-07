"""Section splitting: what counts as a section, and what does not."""

from __future__ import annotations

from quarry.ingestion.section_splitter import SectionSplitter


class TestMarkdownSplitter:
    """Headings open sections; comment-only fragments are not sections."""

    def test_splits_on_each_heading(self) -> None:
        text = "# One\n\nalpha\n\n# Two\n\nbeta\n"
        assert len(SectionSplitter.markdown().split(text)) == 2

    def test_leading_lint_directive_is_not_a_section(self) -> None:
        """The defect this guards: a directive-only chunk reaching the index."""
        text = "<!-- markdownlint-disable MD025 -->\n\n# One\n\nalpha\n"
        sections = SectionSplitter.markdown().split(text)
        assert len(sections) == 1
        assert sections[0].startswith("# One")

    def test_genuine_preamble_prose_is_kept(self) -> None:
        """Only comment-only parts are dropped, never real content."""
        text = "<!-- a directive -->\n\nIntro prose.\n\n# One\n\nalpha\n"
        sections = SectionSplitter.markdown().split(text)
        assert len(sections) == 2
        assert "Intro prose." in sections[0]

    def test_comment_inside_a_section_is_retained(self) -> None:
        """Stripping is a content test, not a rewrite: the text is untouched."""
        text = "# One\n\n<!-- note -->\n\nalpha\n"
        sections = SectionSplitter.markdown().split(text)
        assert len(sections) == 1
        assert "<!-- note -->" in sections[0]

    def test_multiline_comment_only_part_is_dropped(self) -> None:
        text = "<!--\nmultiple\nlines\n-->\n\n# One\n\nalpha\n"
        assert len(SectionSplitter.markdown().split(text)) == 1

    def test_headings_of_any_level_open_a_section(self) -> None:
        text = "# One\n\nalpha\n\n### Three\n\nbeta\n"
        assert len(SectionSplitter.markdown().split(text)) == 2

    def test_empty_document_has_no_sections(self) -> None:
        assert SectionSplitter.markdown().split("") == []


class TestOtherFormats:
    """LaTeX and plain text keep comments as content -- the rule is markdown's."""

    def test_latex_splits_on_section_commands(self) -> None:
        text = "\\section{One}\nalpha\n\\section{Two}\nbeta\n"
        assert len(SectionSplitter.latex().split(text)) == 2

    def test_plain_splits_on_blank_lines(self) -> None:
        assert len(SectionSplitter.plain().split("alpha\n\nbeta\n")) == 2

    def test_plain_keeps_a_comment_only_paragraph(self) -> None:
        """Outside markdown an HTML comment is just text, not a directive."""
        assert len(SectionSplitter.plain().split("<!-- x -->\n\nalpha\n")) == 2
