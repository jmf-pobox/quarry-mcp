"""Health checks for the optional inference capabilities: OCR and ONNX provider."""

from __future__ import annotations

from typing import final

from quarry.results import CheckResult


@final
class InferenceDiagnostics:
    """``quarry doctor`` checks for OCR and the ONNX execution provider.

    Both are advisory (``required=False``) optional capabilities: quarry's core
    (embedding, search, text ingest) runs without them, so a machine that cannot
    load OpenCV or a GPU provider warns rather than failing ``quarry install``.
    """

    __slots__ = ()

    @staticmethod
    def local_ocr() -> CheckResult:
        """Report local OCR (RapidOCR) availability.

        A headless box where cv2 will not load warns with an actionable message
        (run the printed ``pip install`` fix) rather than failing the run.
        """
        from quarry.ingestion.ocr_availability import OcrAvailability  # noqa: PLC0415

        availability = OcrAvailability.probe()
        if not availability.is_available:
            return CheckResult(
                name="Local OCR",
                passed=False,
                message=availability.reason,
                required=False,
            )
        try:
            from quarry.ingestion.ocr_engine import OcrEngine  # noqa: PLC0415

            OcrEngine.get()
        except Exception as exc:  # noqa: BLE001
            return CheckResult(
                name="Local OCR", passed=False, message=str(exc), required=False
            )
        return CheckResult(
            name="Local OCR", passed=True, message="RapidOCR engine OK", required=False
        )

    @staticmethod
    def onnx_provider() -> CheckResult:
        """Report which ONNX execution provider is selected."""
        from quarry.ingestion.provider import ProviderSelection  # noqa: PLC0415

        try:
            selection = ProviderSelection.from_environment()
        except Exception as exc:  # noqa: BLE001
            return CheckResult(
                name="ONNX provider", passed=False, message=str(exc), required=False
            )
        return CheckResult(
            name="ONNX provider",
            passed=True,
            message=f"{selection.provider} ({selection.model_file})",
            required=False,
        )
