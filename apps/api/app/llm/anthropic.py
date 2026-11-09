"""Anthropic Messages API client.

Written against `httpx` directly rather than the vendor SDK, matching the market
data providers: one fewer dependency to keep current, and the failure mapping
stays visible in this file instead of inside a library.

The key travels in the `x-api-key` header, never a query string, so it cannot
leak into access logs or error messages.

Model default is Haiku: article scoring is a high-volume classification job run
once per article, where cost per call matters far more than depth.
"""

from __future__ import annotations

from typing import Any

import httpx

from app.llm.base import LLMError, LLMRateLimited, LLMResponse
from app.services.rate_limit import TokenBucket

BASE_URL = "https://api.anthropic.com/v1"
API_VERSION = "2023-06-01"
DEFAULT_MODEL = "claude-haiku-4-5-20251001"


class AnthropicClient:
    name = "anthropic"
    is_simulated = False

    def __init__(
        self,
        api_key: str,
        bucket: TokenBucket,
        model: str = DEFAULT_MODEL,
        client: httpx.Client | None = None,
        timeout: float = 30.0,
    ) -> None:
        if not api_key:
            raise ValueError("Anthropic requires an API key")
        self.model = model
        self._bucket = bucket
        self._client = client or httpx.Client(base_url=BASE_URL, timeout=timeout)
        self._headers = {
            "x-api-key": api_key,
            "anthropic-version": API_VERSION,
            "content-type": "application/json",
        }

    def complete(self, system: str, user: str, *, max_tokens: int = 512) -> LLMResponse:
        self._bucket.acquire()
        body: dict[str, Any] = {
            "model": self.model,
            "max_tokens": max_tokens,
            # Zero, so the same article scores the same way twice. A signal that
            # cannot be reproduced cannot be explained to the customer who saw it.
            "temperature": 0,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        }
        try:
            response = self._client.post("/messages", json=body, headers=self._headers)
        except httpx.HTTPError as exc:
            raise LLMError(self.name, f"network error: {type(exc).__name__}") from exc

        if response.status_code == 429:
            raise LLMRateLimited(self.name, "rate limited")
        if response.status_code in (401, 403):
            raise LLMError(self.name, f"{response.status_code} (bad key or no access)")
        if response.status_code >= 400:
            raise LLMError(self.name, f"HTTP {response.status_code}")

        try:
            data = response.json()
        except ValueError as exc:
            raise LLMError(self.name, "non-JSON response") from exc

        blocks = [b.get("text", "") for b in data.get("content", []) if b.get("type") == "text"]
        if not blocks:
            raise LLMError(self.name, "response contained no text block")

        usage = data.get("usage") or {}
        return LLMResponse(
            text="".join(blocks),
            model=data.get("model") or self.model,
            input_tokens=usage.get("input_tokens"),
            output_tokens=usage.get("output_tokens"),
        )
