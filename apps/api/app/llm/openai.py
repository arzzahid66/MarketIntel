"""OpenAI Chat Completions client.

Written against `httpx` directly rather than the vendor SDK, matching the market
data providers: one fewer dependency to keep current, and the failure mapping
stays visible in this file instead of inside a library.

The key travels in the Authorization header, never a query string, so it cannot
leak into access logs or error messages.

Two settings earn their place:

  * `response_format={"type": "json_object"}` makes the API itself reject a
    non-JSON answer, which removes the most common scoring failure. It requires
    the word "JSON" in the prompt - `SYSTEM_PROMPT` says "Return ONLY valid
    JSON", so that holds. If you ever reword the prompt, keep that phrase.
  * `temperature=0`, so the same article scores the same way twice. A signal
    that cannot be reproduced cannot be explained to the customer who saw it.

The model is `gpt-4.1-mini`: article scoring is a high-volume classification job
run once per article, where cost per call matters far more than depth. It is
also the choice that keeps the two settings above legal - OpenAI's newer models
(`gpt-5.6-luna` and friends) reject `max_tokens` in favour of
`max_completion_tokens` **and** refuse any temperature but the default, so they
cannot be pinned to 0 and will not score the same article identically twice.
Verified against the live account on 2026-10-05. `LLM_MODEL` can override this,
but check both parameters still apply before changing it.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import httpx

from app.llm.base import LLMError, LLMRateLimited, LLMResponse
from app.services.rate_limit import TokenBucket

BASE_URL = "https://api.openai.com/v1"
DEFAULT_MODEL = "gpt-4.1-mini"
DEFAULT_EMBEDDING_MODEL = "text-embedding-3-small"


class OpenAIClient:
    name = "openai"
    is_simulated = False

    def __init__(
        self,
        api_key: str,
        bucket: TokenBucket,
        model: str = DEFAULT_MODEL,
        client: httpx.Client | None = None,
        timeout: float = 30.0,
        embedding_model: str = DEFAULT_EMBEDDING_MODEL,
    ) -> None:
        if not api_key:
            raise ValueError("OpenAI requires an API key")
        self.model = model
        self.embedding_model = embedding_model
        self._bucket = bucket
        self._client = client or httpx.Client(base_url=BASE_URL, timeout=timeout)
        self._headers = {
            "Authorization": f"Bearer {api_key}",
            "content-type": "application/json",
        }

    def complete(
        self,
        system: str,
        user: str,
        *,
        max_tokens: int = 512,
        json_object: bool = False,
    ) -> LLMResponse:
        self._bucket.acquire()
        body: dict[str, Any] = {
            "model": self.model,
            "max_tokens": max_tokens,
            "temperature": 0,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        if json_object:
            # Rejected with a 400 unless the prompt contains the word "JSON".
            body["response_format"] = {"type": "json_object"}
        try:
            response = self._client.post("/chat/completions", json=body, headers=self._headers)
        except httpx.HTTPError as exc:
            raise LLMError(self.name, f"network error: {type(exc).__name__}") from exc

        if response.status_code == 429:
            raise LLMRateLimited(self.name, "rate limited")
        if response.status_code in (401, 403):
            raise LLMError(self.name, f"{response.status_code} (bad key or no access)")
        if response.status_code >= 400:
            raise LLMError(self.name, f"HTTP {response.status_code}: {_detail(response)}")

        try:
            data = response.json()
        except ValueError as exc:
            raise LLMError(self.name, "non-JSON response") from exc

        choices = data.get("choices") or []
        if not choices:
            raise LLMError(self.name, "response contained no choices")
        text = (choices[0].get("message") or {}).get("content")
        if not text:
            # A finish_reason of "length" means max_tokens truncated the JSON.
            reason = choices[0].get("finish_reason")
            raise LLMError(self.name, f"empty content (finish_reason={reason!r})")

        usage = data.get("usage") or {}
        return LLMResponse(
            text=text,
            model=data.get("model") or self.model,
            input_tokens=usage.get("prompt_tokens"),
            output_tokens=usage.get("completion_tokens"),
        )

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        """Embed a batch in one request.

        Batched because the per-request overhead dominates for short texts, and
        because the embed job runs over the whole backlog. The response is
        re-sorted by `index`: the API does not promise input order back, and a
        shuffled batch would attach every vector to the wrong article.
        """
        if not texts:
            return []
        self._bucket.acquire()
        body = {"model": self.embedding_model, "input": list(texts)}
        try:
            response = self._client.post("/embeddings", json=body, headers=self._headers)
        except httpx.HTTPError as exc:
            raise LLMError(self.name, f"network error: {type(exc).__name__}") from exc

        if response.status_code == 429:
            raise LLMRateLimited(self.name, "rate limited")
        if response.status_code in (401, 403):
            raise LLMError(self.name, f"{response.status_code} (bad key or no access)")
        if response.status_code >= 400:
            raise LLMError(self.name, f"HTTP {response.status_code}: {_detail(response)}")

        try:
            rows = response.json()["data"]
        except (ValueError, KeyError, TypeError) as exc:
            raise LLMError(self.name, "embeddings response had no data") from exc
        if len(rows) != len(texts):
            raise LLMError(self.name, f"asked for {len(texts)} vectors, got {len(rows)}")
        return [row["embedding"] for row in sorted(rows, key=lambda r: r["index"])]


def _detail(response: httpx.Response) -> str:
    """OpenAI explains a 400 in the body; without it the error is unactionable
    (an unknown model and an unsupported parameter both arrive as a bare 400)."""
    try:
        return str((response.json().get("error") or {}).get("message") or "")[:200]
    except ValueError:
        return ""
