from __future__ import annotations

import json
from io import BytesIO
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from quarry.backends import clear_caches
from quarry.config import Settings
from quarry.embeddings_sagemaker import SageMakerEmbeddingBackend


def _settings(**overrides: object) -> Settings:
    defaults: dict[str, object] = {
        "aws_access_key_id": "test",
        "aws_secret_access_key": "test",
        "embedding_backend": "sagemaker",
        "sagemaker_endpoint_name": "test-endpoint",
    }
    defaults.update(overrides)
    return Settings.model_validate(defaults)


def _mock_onnx() -> tuple[MagicMock, MagicMock, MagicMock]:
    """Return (session, tokenizer, sagemaker_client) mocks."""
    session = MagicMock()
    rng = np.random.default_rng(0)
    session.run.return_value = (
        rng.standard_normal((1, 5, 768)).astype(np.float32),
        rng.standard_normal((1, 768)).astype(np.float32),
    )
    tokenizer = MagicMock()
    enc = MagicMock()
    enc.ids = [101, 2023, 2003, 1037, 102]
    enc.attention_mask = [1, 1, 1, 1, 1]
    tokenizer.encode_batch.side_effect = lambda texts: [enc for _ in texts]

    sagemaker_client = MagicMock()
    return session, tokenizer, sagemaker_client


def _make_sagemaker_response(embeddings: object) -> dict[str, object]:
    """Build a mock SageMaker invoke_endpoint response."""
    body = BytesIO(json.dumps(embeddings).encode())
    return {"Body": body}


class TestSageMakerEmbeddingBackend:
    def setup_method(self) -> None:
        clear_caches()

    def _build_backend(
        self,
        settings: Settings | None = None,
        sagemaker_client: MagicMock | None = None,
    ) -> SageMakerEmbeddingBackend:
        session, tokenizer, sm_client = _mock_onnx()
        if sagemaker_client is not None:
            sm_client = sagemaker_client

        with (
            patch(
                "quarry.embeddings._load_model_files",
                return_value=("/fake/model.onnx", "/fake/tokenizer.json"),
            ),
            patch("tokenizers.Tokenizer.from_file", return_value=tokenizer),
            patch("onnxruntime.InferenceSession", return_value=session),
            patch("boto3.client", return_value=sm_client),
        ):
            return SageMakerEmbeddingBackend(settings or _settings())

    def test_raises_when_endpoint_name_missing(self) -> None:
        with (
            pytest.raises(ValueError, match="SAGEMAKER_ENDPOINT_NAME must be set"),
            patch(
                "quarry.embeddings._load_model_files",
                return_value=("/fake/model.onnx", "/fake/tokenizer.json"),
            ),
            patch("tokenizers.Tokenizer.from_file"),
            patch("onnxruntime.InferenceSession"),
            patch("boto3.client"),
        ):
            SageMakerEmbeddingBackend(
                _settings(sagemaker_endpoint_name=""),
            )

    def test_embed_texts_returns_correct_shape(self) -> None:
        rng = np.random.default_rng(42)
        embeddings = rng.standard_normal((3, 768)).tolist()
        sm_client = MagicMock()
        sm_client.invoke_endpoint.return_value = _make_sagemaker_response(embeddings)

        backend = self._build_backend(sagemaker_client=sm_client)
        result = backend.embed_texts(["a", "b", "c"])
        assert result.shape == (3, 768)
        sm_client.invoke_endpoint.assert_called_once()

    def test_embed_texts_batches_large_input(self) -> None:
        rng = np.random.default_rng(42)
        sm_client = MagicMock()

        # 40 texts → 2 batches (32 + 8)
        batch1 = rng.standard_normal((32, 768)).tolist()
        batch2 = rng.standard_normal((8, 768)).tolist()
        sm_client.invoke_endpoint.side_effect = [
            _make_sagemaker_response(batch1),
            _make_sagemaker_response(batch2),
        ]

        backend = self._build_backend(sagemaker_client=sm_client)
        texts = [f"text {i}" for i in range(40)]
        result = backend.embed_texts(texts)
        assert result.shape == (40, 768)
        assert sm_client.invoke_endpoint.call_count == 2

    def test_embed_texts_empty_returns_empty_array(self) -> None:
        backend = self._build_backend()
        result = backend.embed_texts([])
        assert result.shape == (0, 768)

    def test_embed_query_delegates_to_local(self) -> None:
        session, tokenizer, sm_client = _mock_onnx()

        with (
            patch(
                "quarry.embeddings._load_model_files",
                return_value=("/fake/model.onnx", "/fake/tokenizer.json"),
            ),
            patch("tokenizers.Tokenizer.from_file", return_value=tokenizer),
            patch("onnxruntime.InferenceSession", return_value=session),
            patch("boto3.client", return_value=sm_client),
        ):
            backend = SageMakerEmbeddingBackend(_settings())
            result = backend.embed_query("search term")

        assert result.shape == (768,)
        # Verify the query prefix was applied (via local ONNX)
        texts = tokenizer.encode_batch.call_args[0][0]
        assert texts[0].startswith(
            "Represent this sentence for searching relevant passages: "
        )
        # SageMaker client should NOT have been called for query
        sm_client.invoke_endpoint.assert_not_called()

    def test_dimension_property(self) -> None:
        backend = self._build_backend()
        assert backend.dimension == 768

    def test_model_name_property(self) -> None:
        backend = self._build_backend()
        assert backend.model_name == "Snowflake/snowflake-arctic-embed-m-v1.5"

    def test_response_parsing(self) -> None:
        """Verify JSON response body is correctly parsed into numpy array."""
        expected = [[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]]
        sm_client = MagicMock()
        sm_client.invoke_endpoint.return_value = _make_sagemaker_response(expected)

        settings = _settings(embedding_dimension=3)
        backend = self._build_backend(settings=settings, sagemaker_client=sm_client)
        result = backend.embed_texts(["a", "b"])
        expected_arr = np.array(expected, dtype=np.float32)
        np.testing.assert_array_almost_equal(result, expected_arr)

    def test_embed_texts_pools_3d_token_embeddings(self) -> None:
        """HF feature-extraction can return 3D (batch, tokens, dim).

        Mean-pooling over the token axis should produce 2D (batch, dim).
        """
        # 2 texts, 4 tokens each, dim=3
        token_embeddings = [
            [[1.0, 2.0, 3.0], [3.0, 4.0, 5.0], [5.0, 6.0, 7.0], [7.0, 8.0, 9.0]],
            [[0.0, 0.0, 0.0], [2.0, 2.0, 2.0], [4.0, 4.0, 4.0], [6.0, 6.0, 6.0]],
        ]
        sm_client = MagicMock()
        sm_client.invoke_endpoint.return_value = _make_sagemaker_response(
            token_embeddings,
        )

        settings = _settings(embedding_dimension=3)
        backend = self._build_backend(settings=settings, sagemaker_client=sm_client)
        result = backend.embed_texts(["a", "b"])

        assert result.shape == (2, 3)
        # Mean of first text: (1+3+5+7)/4=4, (2+4+6+8)/4=5, (3+5+7+9)/4=6
        expected = np.array([[4.0, 5.0, 6.0], [3.0, 3.0, 3.0]], dtype=np.float32)
        np.testing.assert_array_almost_equal(result, expected)
