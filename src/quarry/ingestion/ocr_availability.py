"""Probe whether local OCR can run and explain the fix when it cannot."""

from __future__ import annotations

import importlib
from typing import Self, final

__all__ = ["OcrAvailability", "OcrUnavailableError"]

# rapidocr hard-requires the DESKTOP opencv-python, whose cv2 links X11/GL system
# libraries absent on headless boxes; when that build shadows the headless one,
# `import cv2` fails. --force-reinstall makes the headless wheel overwrite the
# shared cv2/ files so it wins (a plain reinstall is a no-op when the headless
# requirement is already satisfied but lost the file collision).
_FIX = "pip install --force-reinstall opencv-python-headless"
_UNAVAILABLE = (
    "local OCR unavailable: the headless OpenCV isn't loadable on this machine "
    f"(scanned-image OCR is off; everything else works) — run `{_FIX}` to enable it"
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
            return cls(available=False, reason=_UNAVAILABLE)
        return cls(available=True, reason="")

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
