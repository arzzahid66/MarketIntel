"""LLM registry.

One function decides which model answers, from configuration alone:

    LLM_PROVIDER=fake    -> the deterministic keyword scorer
    LLM_PROVIDER=openai  -> OpenAI (boot fails without OPENAI_API_KEY)
    LLM_PROVIDER=auto    -> OpenAI if OPENAI_API_KEY is set, else fake

Swapping vendors is a new implementation of the `LLMClient` Protocol and a line
here - nothing above this layer changes.

The bucket is shared through Redis for the same reason the market data one is:
the API and the worker spend the same vendor quota.
"""

from __future__ import annotations

from functools import lru_cache

from app.core.config import Settings, settings
from app.core.redis import get_redis
from app.llm.base import (
    LLMClient,
    LLMError,
    LLMRateLimited,
    LLMRefused,
    LLMResponse,
)
from app.llm.fake import FakeLLM
from app.llm.openai import OpenAIClient
from app.services.rate_limit import TokenBucket


def build_llm_client(config: Settings) -> LLMClient:
    key = config.openai_api_key.get_secret_value()
    mode = config.llm_provider
    if mode == "fake" or (mode == "auto" and not key):
        return FakeLLM()
    if not key:
        raise RuntimeError("LLM_PROVIDER=openai but OPENAI_API_KEY is not set")
    return OpenAIClient(
        key,
        TokenBucket("openai", config.llm_calls_per_minute, client=get_redis()),
        model=config.llm_model,
        timeout=config.llm_timeout_seconds,
    )


@lru_cache(maxsize=1)
def get_llm_client() -> LLMClient:
    return build_llm_client(settings)


__all__ = [
    "FakeLLM",
    "LLMClient",
    "LLMError",
    "LLMRateLimited",
    "LLMRefused",
    "LLMResponse",
    "OpenAIClient",
    "build_llm_client",
    "get_llm_client",
]
