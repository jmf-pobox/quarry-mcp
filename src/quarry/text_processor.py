from __future__ import annotations

import re
from pathlib import Path

from quarry.models import PageContent, PageType

MD_HEADER = re.compile(r"^(?=#+\s)", re.MULTILINE)
LATEX_SECTION = re.compile(r"(?=\\(?:sub)?section\{)")
BLANK_LINE_SPLIT = re.compile(r"\n\s*\n")

_TEXT_FORMATS: dict[str, str] = {
    ".txt": "plain",
    ".md": "markdown",
    ".tex": "latex",
    ".docx": "docx",
}

SUPPORTED_TEXT_EXTENSIONS = frozenset(_TEXT_FORMATS)


def process_text_file(file_path: Path) -> list[PageContent]:
    """Read a text file and split into sections.

    Dispatches to format-specific processor based on file extension.
    Supported: .txt, .md, .tex, .docx.

    Args:
        file_path: Path to text file.

    Returns:
        List of PageContent objects, one per section.

    Raises:
        ValueError: If file extension is not supported.
    """
    suffix = file_path.suffix.lower()
    fmt = _TEXT_FORMATS.get(suffix)
    if fmt is None:
        msg = f"Unsupported text format: {suffix}"
        raise ValueError(msg)

    if fmt == "docx":
        return _process_docx(file_path)

    text = file_path.read_text(encoding="utf-8")
    return _split_by_format(text, fmt, file_path.name, str(file_path.resolve()))


def process_raw_text(
    text: str,
    document_name: str,
    format_hint: str = "auto",
) -> list[PageContent]:
    """Process raw text string into sections.

    Args:
        text: Raw text content.
        document_name: Name for the document.
        format_hint: One of 'auto', 'plain', 'markdown', 'latex'.

    Returns:
        List of PageContent objects, one per section.
    """
    if format_hint == "auto":
        format_hint = _detect_format(text)

    return _split_by_format(text, format_hint, document_name, "<string>")


def _detect_format(text: str) -> str:
    """Detect text format from content.

    Checks for markdown headers and LaTeX section commands.
    Falls back to plain text.
    """
    if MD_HEADER.search(text):
        return "markdown"
    if LATEX_SECTION.search(text):
        return "latex"
    return "plain"


def _split_by_format(
    text: str,
    fmt: str,
    document_name: str,
    document_path: str,
) -> list[PageContent]:
    """Split text into sections based on format."""
    if fmt == "markdown":
        sections = _split_markdown(text)
    elif fmt == "latex":
        sections = _split_latex(text)
    else:
        sections = _split_plain(text)

    return _sections_to_pages(sections, document_name, document_path)


def _split_markdown(text: str) -> list[str]:
    """Split markdown on heading lines (any level)."""
    parts = MD_HEADER.split(text)
    return [p for p in parts if p.strip()]


def _split_latex(text: str) -> list[str]:
    """Split LaTeX on \\section{} or \\subsection{} commands."""
    parts = LATEX_SECTION.split(text)
    return [p for p in parts if p.strip()]


def _split_plain(text: str) -> list[str]:
    """Split plain text on blank lines (paragraph boundaries)."""
    parts = BLANK_LINE_SPLIT.split(text)
    return [p for p in parts if p.strip()]


def _process_docx(file_path: Path) -> list[PageContent]:
    """Extract text from DOCX, splitting on Heading styles."""
    import docx  # noqa: PLC0415

    doc = docx.Document(str(file_path))
    sections: list[str] = []
    current: list[str] = []

    for para in doc.paragraphs:
        is_heading = para.style is not None and para.style.name.startswith("Heading")
        if is_heading and current:
            sections.append("\n".join(current))
            current = []
        if para.text.strip():
            current.append(para.text)

    if current:
        sections.append("\n".join(current))

    document_path = str(file_path.resolve())
    return _sections_to_pages(sections, file_path.name, document_path)


def _sections_to_pages(
    sections: list[str],
    document_name: str,
    document_path: str,
) -> list[PageContent]:
    """Convert section strings to PageContent objects."""
    total = len(sections)
    return [
        PageContent(
            document_name=document_name,
            document_path=document_path,
            page_number=i + 1,
            total_pages=total,
            text=section,
            page_type=PageType.SECTION,
        )
        for i, section in enumerate(sections)
    ]
