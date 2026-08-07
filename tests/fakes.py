"""The shared stand-in for the ONNX embedding backend.

One fake, installed at the factory by an autouse fixture, replaces the roughly
forty independent ``patch("...get_embedding_backend", ...)`` context managers
that each named a single import site.  Any test reaching the model through a
site none of those patches happened to name would silently load 410 MB and
still pass; the fixture closes that by construction, and this class is what it
installs.
"""

from __future__ import annotations

import zlib
from typing import TYPE_CHECKING, Final, Self, final

import numpy as np

if TYPE_CHECKING:
    from numpy.typing import NDArray

    from quarry.config import Settings

DEFAULT_DIMENSION: Final[int] = 768


@final
class FakeEmbeddingBackend:
    """Deterministic embeddings derived from the text, with no ONNX session.

    Vectors are seeded per text rather than fixed, for two reasons.  Constant
    vectors are degenerate under the cosine metric LanceDB indexes with, and
    identical vectors for distinct documents make any ranking assertion
    meaningless.  Seeding from a checksum of the text keeps the mapping stable
    across processes and runs -- ``hash()`` would not, being salted per process.

    Vectors are unit-length, matching the real backend, so any code that assumes
    cosine similarity equals the dot product behaves the same against both.

    ``embedded`` records every text that passed through, queries included, so a
    test can assert on what was embedded without a second spy.

    Satisfies :class:`quarry.types.EmbeddingBackend` structurally.
    """

    __slots__ = ("_dimension", "_embedded", "_model_name")

    _dimension: int
    _model_name: str
    _embedded: list[str]

    def __new__(
        cls,
        dimension: int = DEFAULT_DIMENSION,
        *,
        model_name: str = "fake-embedder",
    ) -> Self:
        self = super().__new__(cls)
        self._dimension = dimension
        self._model_name = model_name
        self._embedded = []
        return self

    @classmethod
    def for_settings(cls, settings: Settings) -> Self:
        """Return a fake shaped to *settings*, standing in for the cached factory."""
        return cls(settings.embedding_dimension)

    @property
    def dimension(self) -> int:
        """Return the width of the vectors this backend produces."""
        return self._dimension

    @property
    def model_name(self) -> str:
        """Return the name a diagnostic would print for this backend."""
        return self._model_name

    @property
    def embedded(self) -> tuple[str, ...]:
        """Return every text this backend has embedded, in order.

        A snapshot, not the live list: handing out the internal one would let a
        caller mutate the record it is meant to be reading.
        """
        return tuple(self._embedded)

    def embed_texts(self, texts: list[str]) -> NDArray[np.float32]:
        """Return one vector per text, shape ``(len(texts), dimension)``."""
        self._embedded.extend(texts)
        if not texts:
            return np.zeros((0, self._dimension), dtype=np.float32)
        return np.vstack([self._vector(text) for text in texts])

    def embed_query(self, query: str) -> NDArray[np.float32]:
        """Return a single vector of shape ``(dimension,)``."""
        self._embedded.append(query)
        return self._vector(query)

    def _vector(self, text: str) -> NDArray[np.float32]:
        """Return the unit-length vector this text always maps to.

        L2-normalized because the real backend is: quarry stores and queries on
        the understanding that cosine similarity equals the dot product, so a
        fake emitting unnormalized vectors would diverge from production on
        every norm-sensitive path while still looking plausible.
        """
        rng = np.random.default_rng(zlib.crc32(text.encode()))
        vector = rng.standard_normal(self._dimension).astype(np.float32)
        norm = float(np.linalg.norm(vector))
        unit: NDArray[np.float32] = (vector / (norm or 1.0)).astype(np.float32)
        return unit
