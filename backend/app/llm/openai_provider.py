"""OpenAI-compatible provider (OpenAI, Azure OpenAI, vLLM, OpenRouter, …).

Only the ``/chat/completions`` and ``/embeddings`` endpoints are used, with
``response_format: json_schema`` for structured output, so any gateway that
implements the OpenAI wire format works by changing ``OPENAI_BASE_URL``.
"""

from __future__ import annotations

import json
import time
from typing import Any

import httpx

from app.core.config import get_settings
from app.core.errors import (
    EmbeddingServiceError,
    LLMRateLimitError,
    LLMServiceError,
    LLMTimeoutError,
    PermanentError,
    StructuredOutputError,
)
from app.core.logging import get_logger
from app.llm.base import EmbeddingResponse, LLMRequest, LLMResponse, LLMUsage, estimate_tokens

logger = get_logger(__name__)


class OpenAIProvider:
    name = "openai"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        embedding_model: str | None = None,
        timeout: float | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        settings = get_settings()
        self._api_key = api_key or settings.openai_api_key
        if not self._api_key:
            raise PermanentError(
                "OPENAI_API_KEY is required for LLM_PROVIDER=openai. Set the key or use LLM_PROVIDER=fake."
            )
        self._base_url = (base_url or settings.openai_base_url).rstrip("/")
        self.model = model or settings.llm_model
        self.embedding_model = embedding_model or settings.embedding_model
        self._timeout = timeout or settings.llm_timeout_seconds
        self._client = client

    # --- plumbing ---------------------------------------------------------

    def _post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        headers = {"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"}
        client = self._client or httpx.Client(timeout=self._timeout)
        try:
            response = client.post(f"{self._base_url}{path}", headers=headers, json=body)
        except httpx.TimeoutException as error:
            raise LLMTimeoutError(f"LLM request timed out after {self._timeout}s") from error
        except httpx.HTTPError as error:
            raise LLMServiceError(f"LLM transport error: {error}") from error
        finally:
            if self._client is None:
                client.close()

        if response.status_code == 429:
            raise LLMRateLimitError("LLM provider returned 429 (rate limited)")
        if response.status_code >= 500:
            raise LLMServiceError(f"LLM provider returned {response.status_code}")
        if response.status_code == 401:
            raise PermanentError("LLM provider rejected the API key (401)")
        if response.status_code >= 400:
            raise PermanentError(f"LLM provider rejected the request ({response.status_code}): {response.text[:400]}")
        return response.json()

    # --- completion -------------------------------------------------------

    def generate_json(self, request: LLMRequest) -> LLMResponse:
        started = time.perf_counter()
        body = {
            "model": self.model,
            "messages": [{"role": m.role, "content": m.content} for m in request.messages],
            "temperature": request.temperature,
            "max_tokens": request.max_output_tokens,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": request.schema_name,
                    "schema": request.json_schema,
                    "strict": False,
                },
            },
        }
        data = self._post("/chat/completions", body)
        latency_ms = int((time.perf_counter() - started) * 1000)

        try:
            content = data["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError) as error:
            raise LLMServiceError(f"unexpected LLM response envelope: {str(data)[:300]}") from error

        usage_block = data.get("usage") or {}
        usage = LLMUsage(
            provider=self.name,
            model=self.model,
            prompt_tokens=int(usage_block.get("prompt_tokens") or estimate_tokens(request.prompt_text)),
            completion_tokens=int(usage_block.get("completion_tokens") or estimate_tokens(content)),
            latency_ms=latency_ms,
        )

        try:
            payload = json.loads(content)
        except json.JSONDecodeError as error:
            raise StructuredOutputError(
                f"model returned non-JSON content: {content[:300]}",
                details={"schema": request.schema_name},
            ) from error
        if not isinstance(payload, dict):
            raise StructuredOutputError(
                "model returned JSON that is not an object", details={"schema": request.schema_name}
            )
        return LLMResponse(payload=payload, usage=usage, raw_text=content)

    # --- embeddings -------------------------------------------------------

    def embed(self, texts: list[str]) -> EmbeddingResponse:
        if not texts:
            return EmbeddingResponse(vectors=[], usage=LLMUsage(provider=self.name, model=self.embedding_model))
        started = time.perf_counter()
        try:
            data = self._post("/embeddings", {"model": self.embedding_model, "input": texts})
        except (LLMRateLimitError, LLMServiceError, LLMTimeoutError) as error:
            raise EmbeddingServiceError(str(error)) from error
        latency_ms = int((time.perf_counter() - started) * 1000)

        items = sorted(data.get("data", []), key=lambda item: item.get("index", 0))
        vectors = [list(map(float, item["embedding"])) for item in items]
        if len(vectors) != len(texts):
            raise EmbeddingServiceError(f"embedding provider returned {len(vectors)} vectors for {len(texts)} inputs")
        usage_block = data.get("usage") or {}
        return EmbeddingResponse(
            vectors=vectors,
            usage=LLMUsage(
                provider=self.name,
                model=self.embedding_model,
                prompt_tokens=int(usage_block.get("prompt_tokens") or sum(map(estimate_tokens, texts))),
                latency_ms=latency_ms,
            ),
        )
