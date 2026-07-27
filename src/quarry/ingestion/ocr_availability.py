"""Probe whether local OCR can run and explain the fix when it cannot."""

from __future__ import annotations

import importlib
import sys
from typing import Self, final

from quarry.opencv_headless import HeadlessOpenCv

__all__ = ["OcrAvailability", "OcrUnavailableError"]

# The remediation command lives on HeadlessOpenCv so doctor and this runtime
# warning quote the SAME working command (uv/--python/--no-deps when uv is
# present); a bare `pip install` would misdirect the uv-tool installs this
# guard exists to cover. `{fix}` is filled from HeadlessOpenCv.remediation().
_UNAVAILABLE_TEMPLATE = (
    "local OCR unavailable: the headless OpenCV isn't loadable on this machine "
    "(scanned-image OCR is off; everything else works) — run `{fix}` to enable it"
)


class OcrUnavailableError(RuntimeError):
    """Raised when local OCR is invoked but OpenCV (cv2) will not load."""


@final
class OcrAvailability:
    """Whether local OCR can run, and the actionable reason when it cannot.

    Local OCR is an optional capability: rapidocr imports cv2, and the desktop
    OpenCV build it hard-requires links GUI system libraries a headless machine
    lacks. Probing cv2 once lets callers degrade cleanly — a clear message, OCR
    off — instead of crashing on a raw ``libGL``/``libxcb`` ``ImportError``.
    """

    __slots__ = ("_available", "_reason")

    _available: bool
    _reason: str

    def __new__(cls, *, available: bool, reason: str) -> Self:
        self = super().__new__(cls)
        self._available = available
        self._reason = reason
        return self

    @classmethod
    def probe(cls) -> Self:
        """Return current OCR availability by attempting to load cv2.

        A boundary probe of an optional native dependency: any failure to load
        cv2 means OCR is off. A headless GUI-linked build raises ``ImportError``
        (``libGL``/``libxcb``), but a broken cv2 can also raise ``AttributeError``
        (mismatched typing stubs) or other errors on import, so every load
        failure is treated as unavailable rather than only ``ImportError``.
        """
        try:
            # Execute the cv2 module (its bootstrap loads the native library that
            # fails on a GUI-linked build) — rapidocr's transitive dependency.
            importlib.import_module("cv2")
        except Exception:  # noqa: BLE001  # any cv2 load failure = OCR unavailable
            return cls(available=False, reason=cls._unavailable_reason())
        return cls(available=True, reason="")

    @classmethod
    def _unavailable_reason(cls) -> str:
        """Return the unavailability message quoting the live headless-fix command."""
        fix = HeadlessOpenCv(sys.executable).remediation()
        return _UNAVAILABLE_TEMPLATE.format(fix=fix)

    @property
    def is_available(self) -> bool:
        """Return whether local OCR can run on this machine."""
        return self._available

    @property
    def reason(self) -> str:
        """Return the actionable unavailability message, or ``""`` when available."""
        return self._reason

    def require(self) -> None:
        """Raise :class:`OcrUnavailableError` when OCR is unavailable."""
        if not self._available:
            raise OcrUnavailableError(self._reason)
