"""Sentence-transformer embedding wrapper."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol


class SupportsEmbedding(Protocol):
    def encode(self, texts: Sequence[str]) -> list[list[float]]:
        """Encode input texts into fixed-size float vectors."""


class SentenceTransformerEmbedder:
    """Lazy wrapper around a sentence-transformers encoder."""

    def __init__(self, model_name: str = "all-MiniLM-L6-v2") -> None:
        self.model_name = model_name
        self._model = None

    def encode(self, texts: Sequence[str]) -> list[list[float]]:
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(self.model_name)
        vectors = self._model.encode(list(texts), normalize_embeddings=True)
        return [list(map(float, vector)) for vector in vectors]

