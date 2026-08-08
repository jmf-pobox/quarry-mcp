"""Tests for the ONNX execution-provider doctor check."""

from __future__ import annotations

from unittest.mock import patch

from quarry.doctor_inference import InferenceDiagnostics


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
