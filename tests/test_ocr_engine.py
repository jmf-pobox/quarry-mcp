"""Tests for the cached RapidOCR engine provider and its headless guard."""

from __future__ import annotations

import importlib
import sys
from types import ModuleType
from unittest.mock import MagicMock, patch

import pytest

from quarry.ingestion.ocr_availability import OcrAvailability, OcrUnavailableError
from quarry.ingestion.ocr_engine import OcrEngine


@pytest.fixture(autouse=True)
def _reset_engine() -> None:
    OcrEngine.reset()


def test_caches_engine(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_cls = MagicMock()
    mock_module = MagicMock()
    mock_module.RapidOCR = mock_cls

    # Stub the headless guard's cv2 probe as available so the test exercises
    # caching, not the real (possibly broken) cv2 build.
    monkeypatch.setattr(
        "quarry.ingestion.ocr_availability.OcrAvailability.probe",
        lambda: OcrAvailability(available=True, reason=""),
    )
    with patch.dict("sys.modules", {"rapidocr": mock_module}):
        first = OcrEngine.get()
        second = OcrEngine.get()

    assert first is second
    mock_cls.assert_called_once()


def test_get_raises_actionable_error_when_cv2_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A headless box surfaces OcrUnavailableError, not a raw libGL ImportError."""
    real = importlib.import_module

    def fake(name: str, package: str | None = None) -> ModuleType:
        if name == "cv2":
            msg = "libGL.so.1: cannot open shared object file"
            raise ImportError(msg)
        return real(name, package)

    monkeypatch.setattr(importlib, "import_module", fake)
    with pytest.raises(OcrUnavailableError, match="opencv-python-headless"):
        OcrEngine.get()


def test_unavailable_probe_runs_once(monkeypatch: pytest.MonkeyPatch) -> None:
    # A headless box must probe cv2 once, then re-raise the cached error on every
    # later call instead of re-attempting the failing native load per document.
    calls = 0

    def counting_probe() -> OcrAvailability:
        nonlocal calls
        calls += 1
        return OcrAvailability(available=False, reason="headless: no cv2")

    monkeypatch.setattr(
        "quarry.ingestion.ocr_availability.OcrAvailability.probe", counting_probe
    )
    with pytest.raises(OcrUnavailableError):
        OcrEngine.get()
    with pytest.raises(OcrUnavailableError):
        OcrEngine.get()

    assert calls == 1


def test_missing_rapidocr_builds_once(monkeypatch: pytest.MonkeyPatch) -> None:
    # A missing/broken rapidocr raises ImportError, not OcrUnavailableError: the
    # build must run once and the cached ImportError re-raise on every later call,
    # mirroring the cv2 path for the other unavailability reason.
    calls = 0

    def counting_probe() -> OcrAvailability:
        nonlocal calls
        calls += 1
        return OcrAvailability(available=True, reason="")

    monkeypatch.setattr(
        "quarry.ingestion.ocr_availability.OcrAvailability.probe", counting_probe
    )
    # A None entry in sys.modules makes `from rapidocr import ...` raise ImportError.
    monkeypatch.setitem(sys.modules, "rapidocr", None)

    with pytest.raises(ImportError) as first:
        OcrEngine.get()
    with pytest.raises(ImportError) as second:
        OcrEngine.get()

    assert calls == 1
    assert first.value is second.value  # the same cached exception re-raised
