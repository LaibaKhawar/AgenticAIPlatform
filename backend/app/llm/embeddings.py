"""Embeddings.

Two providers, one vector space dimension (``EMBEDDING_DIM``, matching
``text-embedding-3-small``) so the database column never has to change:

* ``local`` — a deterministic hashed bag-of-features embedding. No network, no
  cost, reproducible, and good enough for the semantic-retrieval *behaviour*
  the tests assert (same-topic text ranks above unrelated text).
* ``openai`` — real embeddings when a key is configured.

The local embedder is not a semantic model. It is documented as a development
and CI stand-in; ``EMBEDDING_PROVIDER=openai`` is the production setting.
"""

from __future__ import annotations

import hashlib
import itertools
import math
import re
from functools import lru_cache

from app.core.config import get_settings
from app.core.errors import EmbeddingServiceError
from app.core.failure_injection import get_injector
from app.core.logging import get_logger
from app.llm.base import EmbeddingResponse, LLMUsage, estimate_tokens

logger = get_logger(__name__)

_TOKEN_RE = re.compile(r"[a-z0-9]+")
_STOPWORDS = frozenset(
    [
        "the",
        "a",
        "an",
        "and",
        "or",
        "of",
        "to",
        "in",
        "on",
        "for",
        "with",
        "at",
        "by",
        "from",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "this",
        "that",
        "these",
        "those",
        "it",
        "its",
        "their",
        "there",
        "has",
        "have",
        "had",
        "do",
        "does",
        "did",
        "not",
        "as",
        "we",
        "they",
        "you",
        "i",
        "he",
        "she",
        "them",
        "our",
        "your",
    ]
)


def _tokens(text: str) -> list[str]:
    return [token for token in _TOKEN_RE.findall(text.lower()) if token not in _STOPWORDS]


def _bucket(token: str, dim: int) -> int:
    return int(hashlib.blake2b(token.encode("utf-8"), digest_size=8).hexdigest(), 16) % dim


def local_embedding(text: str, dim: int | None = None) -> list[float]:
    """Deterministic hashed embedding, L2-normalised.

    Unigrams and bigrams are hashed into ``dim`` buckets with sublinear term
    weighting, so documents that share vocabulary and phrases end up close under
    cosine similarity.
    """
    dim = dim or get_settings().embedding_dim
    vector = [0.0] * dim
    tokens = _tokens(text)
    if not tokens:
        # A zero vector has undefined cosine distance; use a stable unit vector.
        vector[0] = 1.0
        return vector

    counts: dict[str, int] = {}
    for token in tokens:
        counts[token] = counts.get(token, 0) + 1
    for first, second in itertools.pairwise(tokens):
        bigram = f"{first}_{second}"
        counts[bigram] = counts.get(bigram, 0) + 1

    for term, count in counts.items():
        weight = 1.0 + math.log(count)
        index = _bucket(term, dim)
        # Sign spreads terms across the space instead of piling up positives.
        sign = 1.0 if _bucket(term + "#sign", 2) == 0 else -1.0
        vector[index] += sign * weight

    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0.0:
        vector[0] = 1.0
        return vector
    return [value / norm for value in vector]


class LocalEmbeddingProvider:
    name = "local"

    def __init__(self, dim: int | None = None) -> None:
        self.dim = dim or get_settings().embedding_dim
        self.model = "deterministic-hash-embedding"

    def embed(self, texts: list[str]) -> EmbeddingResponse:
        return EmbeddingResponse(
            vectors=[local_embedding(text, self.dim) for text in texts],
            usage=LLMUsage(
                provider=self.name,
                model=self.model,
                prompt_tokens=sum(estimate_tokens(text) for text in texts),
            ),
        )


class EmbeddingService:
    """Batches, injects faults (dev only) and validates dimensionality."""

    def __init__(self, provider: object | None = None) -> None:
        settings = get_settings()
        if provider is not None:
            self._provider = provider
        elif settings.effective_embedding_provider == "openai":
            from app.llm.openai_provider import OpenAIProvider

            self._provider = OpenAIProvider()
        else:
            self._provider = LocalEmbeddingProvider()
        self.provider_name = getattr(self._provider, "name", "unknown")
        self.dim = settings.embedding_dim
        self._batch_size = settings.embedding_batch_size

    def embed_texts(self, texts: list[str]) -> tuple[list[list[float]], LLMUsage]:
        if not texts:
            return [], LLMUsage(provider=self.provider_name, model="", prompt_tokens=0)

        get_injector().maybe_fail("llm", operation="embed")
        vectors: list[list[float]] = []
        usage = LLMUsage(provider=self.provider_name, model=getattr(self._provider, "model", ""))
        for start in range(0, len(texts), self._batch_size):
            batch = texts[start : start + self._batch_size]
            response = self._provider.embed(batch)  # type: ignore[attr-defined]
            for vector in response.vectors:
                if len(vector) != self.dim:
                    raise EmbeddingServiceError(
                        f"embedding provider returned dimension {len(vector)}, expected {self.dim}"
                    )
            vectors.extend(response.vectors)
            usage = usage.merged(response.usage)
        return vectors, usage

    def embed_query(self, text: str) -> list[float]:
        vectors, _usage = self.embed_texts([text])
        return vectors[0]


@lru_cache(maxsize=1)
def get_embedding_service() -> EmbeddingService:
    return EmbeddingService()


def reset_embedding_service() -> None:
    get_embedding_service.cache_clear()
