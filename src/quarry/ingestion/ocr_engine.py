"""Provide a process-wide cached RapidOCR engine behind the headless-cv2 guard."""

from __future__ import annotations

import logging
import threading
from typing import TYPE_CHECKING, ClassVar, Protocol, cast, final

from quarry.ingestion.ocr_availability import OcrAvailability

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
    _lock: ClassVar[threading.Lock] = threading.Lock()

    @classmethod
    def get(cls) -> OcrEngineProtocol:
        """Return the cached engine, building it on first use (thread-safe)."""
        engine = cls._instance
        if engine is None:
            with cls._lock:
                engine = cls._instance
                if engine is None:
                    OcrAvailability.probe().require()
                    from rapidocr import RapidOCR  # noqa: PLC0415

                    engine = cast("OcrEngineProtocol", RapidOCR())
                    cls._instance = engine
                    logger.info("RapidOCR engine initialized")
        return engine

    @classmethod
    def reset(cls) -> None:
        """Drop the cached engine so the next :meth:`get` rebuilds it (tests)."""
        cls._instance = None
