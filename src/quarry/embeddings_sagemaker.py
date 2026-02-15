"""SageMaker-based text embedding for batch ingestion.

Uses a SageMaker Serverless endpoint running snowflake-arctic-embed-m-v1.5 for
embed_texts() (network-bound, parallelizable) and delegates embed_query() to a
local OnnxEmbeddingBackend (no network latency for search).
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from numpy.typing import NDArray

    from quarry.config import Settings
    from quarry.types import ReadableBody, SageMakerRuntimeClient

logger = logging.getLogger(__name__)

_SAGEMAKER_BATCH_SIZE: int = 32


class SageMakerEmbeddingBackend:
    """Embedding backend delegating to SageMaker for ingestion, local for search.

    ``embed_texts()`` calls a SageMaker endpoint in batches — network I/O that
    parallelizes well with concurrent workers.  ``embed_query()`` uses a local
    ``OnnxEmbeddingBackend`` instance for sub-millisecond search latency.

    The endpoint must serve the same model (snowflake-arctic-embed-m-v1.5) so
    that ingestion and query vectors are compatible.
    """

    def __init__(self, settings: Settings) -> None:
        if not settings.sagemaker_endpoint_name:
            msg = "SAGEMAKER_ENDPOINT_NAME must be set when EMBEDDING_BACKEND=sagemaker"
            raise ValueError(msg)

        self._endpoint_name = settings.sagemaker_endpoint_name
        self._dimension = settings.embedding_dimension

        import boto3  # noqa: PLC0415

        self._client: SageMakerRuntimeClient = boto3.client(
            "sagemaker-runtime",
            region_name=settings.aws_default_region,
            aws_access_key_id=settings.aws_access_key_id or None,
            aws_secret_access_key=settings.aws_secret_access_key or None,
        )

        from quarry.embeddings import OnnxEmbeddingBackend  # noqa: PLC0415

        self._local = OnnxEmbeddingBackend()
        logger.info(
            "SageMaker embedding backend: endpoint=%s, local fallback for queries",
            self._endpoint_name,
        )

    @property
    def dimension(self) -> int:
        return self._dimension

    @property
    def model_name(self) -> str:
        return self._local.model_name

    def embed_texts(self, texts: list[str]) -> NDArray[np.float32]:
        """Embed texts via SageMaker endpoint. Returns shape (n, dimension)."""
        if not texts:
            return np.empty((0, self._dimension), dtype=np.float32)

        n = len(texts)
        n_batches = (n + _SAGEMAKER_BATCH_SIZE - 1) // _SAGEMAKER_BATCH_SIZE
        logger.info("Embedding %d texts via SageMaker in %d batches", n, n_batches)

        parts: list[NDArray[np.float32]] = []
        for i in range(n_batches):
            batch = texts[i * _SAGEMAKER_BATCH_SIZE : (i + 1) * _SAGEMAKER_BATCH_SIZE]
            payload = json.dumps({"inputs": batch}).encode()

            response = self._client.invoke_endpoint(
                EndpointName=self._endpoint_name,
                ContentType="application/json",
                Body=payload,
            )

            # SageMaker returns a StreamingBody; read and parse JSON
            body: ReadableBody = response["Body"]  # type: ignore[assignment]
            raw: bytes = body.read()
            parsed = json.loads(raw)
            arr = np.array(parsed, dtype=np.float32)
            # Custom inference handler returns 2D sentence embeddings.
            # Defensive fallback: if raw token-level 3D output slips
            # through (no custom handler), take the CLS token (first)
            # and L2-normalize to match the custom handler's output.
            if arr.ndim == 3:
                arr = arr[:, 0]
                norms = np.linalg.norm(arr, axis=1, keepdims=True)
                norms = np.maximum(norms, 1e-12)
                arr = arr / norms
            parts.append(arr)
            logger.debug("SageMaker batch %d/%d complete", i + 1, n_batches)

        result: NDArray[np.float32] = np.concatenate(parts)
        return result

    def embed_query(self, query: str) -> NDArray[np.float32]:
        """Embed a search query locally. Returns shape (dimension,)."""
        return self._local.embed_query(query)
