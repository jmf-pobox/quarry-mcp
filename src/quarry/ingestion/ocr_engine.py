"""Provide a process-wide cached RapidOCR engine behind the headless-cv2 guard."""

from __future__ import annotations

import logging
import threading
from typing import TYPE_CHECKING, ClassVar, Protocol, cast, final

from quarry.ingestion.ocr_availability import OcrAvailability, OcrUnavailableError

if TYPE_CHECKING:
    from PIL import Image

logger = logging.getLogger(__name__)


class OcrResult(Protocol):
    """Structural type for RapidOCR v3 output."""

    @property
    def txts(self) -> tuple[str, ...] | None: ...


class OcrEngineProtocol(Protocol):
    """Structural type for a callable RapidOCR engine."""

    def __call__(self, img: Image.Image) -> OcrResult: ...


@final
class OcrEngine:
    """Lazily create and cache one RapidOCR engine for the whole process.

    The engine is expensive to construct (loads ONNX models), so it is built
    once under a lock and reused. :meth:`get` runs the headless-OpenCV guard
    first, turning a raw ``libGL``/``libxcb`` ``ImportError`` into a clear
    :class:`OcrUnavailableError` before RapidOCR imports the GUI-linked ``cv2``.
    """

    __slots__ = ()

    _instance: ClassVar[OcrEngineProtocol | None] = None
    _unavailable: ClassVar[OcrUnavailableError | None] = None
    _lock: ClassVar[threading.Lock] = threading.Lock()

    @classmethod
    def get(cls) -> OcrEngineProtocol:
        """Return the cached engine, building it on first use (thread-safe).

        The cv2 probe runs at most once per process. A headless box caches the
        resulting :class:`OcrUnavailableError` and re-raises it on every later
        call, so repeated ``ocr_document``/``ocr_image_bytes`` calls never
        re-attempt the failing native ``cv2`` load.
        """
        cached = cls._cached()
        if cached is not None:
            return cached
        with cls._lock:
            cached = cls._cached()
            if cached is not None:
                return cached
            return cls._build()

    @classmethod
    def _cached(cls) -> OcrEngineProtocol | None:
        """Return the cached engine, re-raise the cached error, or None if unprobed.

        None is the "not yet probed" state of the tri-state cache (engine built /
        unavailable / unknown); the caller then probes under the lock.
        """
        if cls._instance is not None:
            return cls._instance
        if cls._unavailable is not None:
            raise cls._unavailable
        return None

    @classmethod
    def _build(cls) -> OcrEngineProtocol:
        """Probe cv2 then construct the engine, caching the outcome (called locked)."""
        availability = OcrAvailability.probe()
        if not availability.is_available:
            cls._unavailable = OcrUnavailableError(availability.reason)
            raise cls._unavailable
        from rapidocr import RapidOCR  # noqa: PLC0415

        engine = cast("OcrEngineProtocol", RapidOCR())
        cls._instance = engine
        logger.info("RapidOCR engine initialized")
        return engine

    @classmethod
    def reset(cls) -> None:
        """Drop the cached engine and probe outcome so the next :meth:`get` rebuilds."""
        cls._instance = None
        cls._unavailable = None
