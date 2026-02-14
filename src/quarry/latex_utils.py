"""LaTeX table serialization: escaping and tabular generation."""

from __future__ import annotations

# Characters that must be escaped in LaTeX tabular cells.
_LATEX_SPECIAL = str.maketrans(
    {
        "&": r"\&",
        "%": r"\%",
        "$": r"\$",
        "#": r"\#",
        "_": r"\_",
        "{": r"\{",
        "}": r"\}",
        "~": r"\textasciitilde{}",
        "^": r"\textasciicircum{}",
        "\\": r"\textbackslash{}",
    }
)


def escape_latex(text: str) -> str:
    """Escape LaTeX special characters in a cell value."""
    return text.translate(_LATEX_SPECIAL)


def rows_to_latex(
    headers: list[str],
    rows: list[list[str]],
    sheet_name: str | None = None,
) -> str:
    """Render headers + data rows as a LaTeX tabular block.

    Returns an empty string when *headers* is empty.
    """
    if not headers:
        return ""

    ncols = len(headers)
    col_spec = "l" * ncols

    lines: list[str] = []
    if sheet_name:
        lines.append(f"% Sheet: {sheet_name}")
    lines.append(f"\\begin{{tabular}}{{{col_spec}}}")
    lines.append("\\hline")
    lines.append(" & ".join(escape_latex(h) for h in headers) + " \\\\")
    lines.append("\\hline")

    for row in rows:
        padded = row[:ncols] + [""] * max(0, ncols - len(row))
        lines.append(" & ".join(escape_latex(c) for c in padded) + " \\\\")

    lines.append("\\hline")
    lines.append("\\end{tabular}")

    return "\n".join(lines)
