"""Tests for the optional-inference (OCR + ONNX provider) doctor checks."""

from __future__ import annotations

from unittest.mock import patch

from quarry.doctor_inference import InferenceDiagnostics
from quarry.ingestion.ocr_availability import OcrAvailability


class TestLocalOcr:
    def test_reports_result(self) -> None:
        result = InferenceDiagnostics.local_ocr()
        assert result.name == "Local OCR"
        # OCR is an optional capability — always advisory, never a hard failure.
        assert result.required is False
        if result.passed:
            assert "RapidOCR" in result.message

    def test_advisory_warning_when_cv2_unavailable(self) -> None:
        # A headless box where cv2 won't load: OCR warns with an actionable
        # message, but does NOT fail (required=False) — install.sh must not abort.
        unavailable = OcrAvailability(
            available=False,
            reason="run `pip install --force-reinstall opencv-python-headless`",
        )
        with patch(
            "quarry.ingestion.ocr_availability.OcrAvailability.probe",
            return_value=unavailable,
        ):
            result = InferenceDiagnostics.local_ocr()
        assert result.passed is False
        assert result.required is False
        assert "opencv-python-headless" in result.message


class TestOnnxProvider:
    def test_reports_provider_on_success(self) -> None:
        from quarry.ingestion.provider import ProviderSelection

        selection = ProviderSelection(
            provider="CPUExecutionProvider",
            model_file="onnx/model_int8.onnx",
        )
        with patch.object(
            ProviderSelection, "from_environment", return_value=selection
        ):
            result = InferenceDiagnostics.onnx_provider()
        assert result.passed is True
        assert result.required is False
        assert result.name == "ONNX provider"
        assert "CPUExecutionProvider" in result.message
        assert "onnx/model_int8.onnx" in result.message

    def test_reports_cuda_provider(self) -> None:
        from quarry.ingestion.provider import ProviderSelection

        selection = ProviderSelection(
            provider="CUDAExecutionProvider",
            model_file="onnx/model_fp16.onnx",
        )
        with patch.object(
            ProviderSelection, "from_environment", return_value=selection
        ):
            result = InferenceDiagnostics.onnx_provider()
        assert result.passed is True
        assert "CUDAExecutionProvider" in result.message

    def test_reports_failure_on_exception(self) -> None:
        from quarry.ingestion.provider import ProviderSelection

        with patch.object(
            ProviderSelection,
            "from_environment",
            side_effect=RuntimeError("CUDA not available"),
        ):
            result = InferenceDiagnostics.onnx_provider()
        assert result.passed is False
        assert result.required is False
        assert "CUDA not available" in result.message
