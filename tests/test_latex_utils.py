from __future__ import annotations

from quarry.latex_utils import escape_latex, rows_to_latex


class TestEscapeLatex:
    def test_escapes_ampersand(self):
        assert escape_latex("A & B") == r"A \& B"

    def test_escapes_percent(self):
        assert escape_latex("50%") == r"50\%"

    def test_escapes_dollar(self):
        assert escape_latex("$100") == r"\$100"

    def test_escapes_hash(self):
        assert escape_latex("#1") == r"\#1"

    def test_escapes_underscore(self):
        assert escape_latex("my_var") == r"my\_var"

    def test_escapes_braces(self):
        assert escape_latex("{x}") == r"\{x\}"

    def test_escapes_backslash(self):
        assert escape_latex(r"a\b") == r"a\textbackslash{}b"

    def test_plain_text_unchanged(self):
        assert escape_latex("Hello World 123") == "Hello World 123"

    def test_multiple_specials(self):
        result = escape_latex("$100 & 50%")
        assert r"\$" in result
        assert r"\&" in result
        assert r"\%" in result


class TestRowsToLatex:
    def test_basic_table(self):
        result = rows_to_latex(["Name", "Age"], [["Alice", "30"]])
        assert r"\begin{tabular}{ll}" in result
        assert "Name & Age" in result
        assert "Alice & 30" in result
        assert r"\end{tabular}" in result

    def test_empty_headers_returns_empty(self):
        assert rows_to_latex([], [["a", "b"]]) == ""

    def test_sheet_name_prefix(self):
        result = rows_to_latex(["A"], [["1"]], sheet_name="Data")
        assert "% Sheet: Data" in result

    def test_no_sheet_name(self):
        result = rows_to_latex(["A"], [["1"]])
        assert "% Sheet" not in result

    def test_row_padding(self):
        result = rows_to_latex(["A", "B", "C"], [["1"]])
        # Row should be padded to match 3 columns
        assert "1 &  & " in result

    def test_row_truncation(self):
        result = rows_to_latex(["A"], [["1", "2", "3"]])
        # Extra columns should be dropped
        assert "1 \\\\" in result
        assert "2" not in result

    def test_latex_escaping_in_cells(self):
        result = rows_to_latex(["Price"], [["$100"]])
        assert r"\$100" in result

    def test_empty_rows(self):
        result = rows_to_latex(["A", "B"], [])
        assert r"\begin{tabular}" in result
        assert r"\end{tabular}" in result
