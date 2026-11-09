"""The OpenAI client and the registry, against recorded-shape HTTP responses.

No test here touches the network. `httpx.MockTransport` stands in for OpenAI, so
request shaping and error mapping are exercised exactly as they run in
production.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from app.core.config import Settings
from app.llm import build_llm_client
from app.llm.base import LLMError, LLMRateLimited
from app.llm.fake import FakeLLM
from app.llm.openai import BASE_URL, OpenAIClient
from app.services.news_sentiment import SYSTEM_PROMPT
from app.services.rate_limit import TokenBucket

Handler = Callable[[httpx.Request], httpx.Response]


def unlimited() -> TokenBucket:
    return TokenBucket("test-llm", per_minute=60_000, capacity=1_000, client=None)


def openai(handler: Handler, model: str = "gpt-4.1-mini") -> OpenAIClient:
    client = httpx.Client(base_url=BASE_URL, transport=httpx.MockTransport(handler))
    return OpenAIClient("openai-test-key", unlimited(), model=model, client=client)


def reply(content: str, **extra: Any) -> httpx.Response:
    body = {
        "model": "gpt-4.1-mini-2025-04-14",
        "choices": [
            {"message": {"role": "assistant", "content": content}, "finish_reason": "stop"}
        ],
        "usage": {"prompt_tokens": 310, "completion_tokens": 42},
        **extra,
    }
    return httpx.Response(200, json=body)


# --------------------------------------------------------------------------
# Request shaping
# --------------------------------------------------------------------------


def test_the_key_travels_in_a_header_not_the_url() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return reply('{"sentiment": 0.3}')

    openai(handler).complete("sys", "user")

    assert seen[0].headers["authorization"] == "Bearer openai-test-key"
    assert "openai-test-key" not in str(seen[0].url)


def test_it_pins_temperature_to_zero() -> None:
    """A score that is the same on a second run, or it cannot be reproduced."""
    seen: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return reply('{"sentiment": 0.3}')

    openai(handler).complete("sys", "user")

    body = seen[0]
    assert body["temperature"] == 0
    assert [m["role"] for m in body["messages"]] == ["system", "user"]


def test_json_mode_is_opt_in_because_prose_callers_would_get_a_400() -> None:
    """The scorer wants guaranteed JSON. The analyst answers in prose, and
    OpenAI rejects response_format unless the prompt asks for JSON - sending it
    unconditionally made every analyst call fail with a 400."""
    seen: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return reply('{"sentiment": 0.3}')

    client = openai(handler)
    client.complete("sys", "user")
    client.complete("sys", "user", json_object=True)

    assert "response_format" not in seen[0]
    assert seen[1]["response_format"] == {"type": "json_object"}


def test_the_prompt_says_json_as_the_json_mode_api_requires() -> None:
    """OpenAI rejects response_format=json_object unless the prompt asks for
    JSON. Rewording SYSTEM_PROMPT without that phrase would break every call."""
    assert "JSON" in SYSTEM_PROMPT


def test_it_reports_the_model_that_actually_answered() -> None:
    """Stored with every score: "gpt-4.1-mini" can silently become a new build."""
    result = openai(lambda r: reply('{"sentiment": 0.1}')).complete("sys", "user")
    assert result.model == "gpt-4.1-mini-2025-04-14"
    assert (result.input_tokens, result.output_tokens) == (310, 42)


# --------------------------------------------------------------------------
# Failure mapping
# --------------------------------------------------------------------------


def test_a_429_becomes_rate_limited_so_the_caller_can_back_off() -> None:
    with pytest.raises(LLMRateLimited):
        openai(lambda r: httpx.Response(429, json={})).complete("sys", "user")


@pytest.mark.parametrize("status", [401, 403])
def test_a_bad_key_is_an_llm_error_not_a_crash(status: int) -> None:
    with pytest.raises(LLMError, match=str(status)):
        openai(lambda r: httpx.Response(status, json={})).complete("sys", "user")


def test_a_400_carries_the_reason_so_the_log_is_actionable() -> None:
    """An unknown model and an unsupported parameter both arrive as a bare 400."""
    body = {"error": {"message": "The model `gpt-9` does not exist."}}
    with pytest.raises(LLMError, match="does not exist"):
        openai(lambda r: httpx.Response(400, json=body)).complete("sys", "user")


def test_a_truncated_reply_names_the_reason_rather_than_returning_half_a_score() -> None:
    truncated = httpx.Response(
        200,
        json={
            "model": "gpt-4.1-mini",
            "choices": [{"message": {"content": ""}, "finish_reason": "length"}],
        },
    )
    with pytest.raises(LLMError, match="length"):
        openai(lambda r: truncated).complete("sys", "user")


def test_a_network_failure_is_mapped_not_leaked() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route to host")

    with pytest.raises(LLMError, match="network error"):
        openai(handler).complete("sys", "user")


# --------------------------------------------------------------------------
# The registry
# --------------------------------------------------------------------------


def base_settings(**overrides: Any) -> Settings:
    return Settings(database_url="postgresql+psycopg://u:p@localhost/db", **overrides)


def test_auto_without_a_key_is_simulated() -> None:
    client = build_llm_client(base_settings(llm_provider="auto", openai_api_key=""))
    assert isinstance(client, FakeLLM)
    assert client.is_simulated


def test_auto_with_a_key_uses_openai() -> None:
    client = build_llm_client(base_settings(llm_provider="auto", openai_api_key="k"))
    assert isinstance(client, OpenAIClient)
    assert not client.is_simulated


def test_openai_without_a_key_refuses_to_build_rather_than_falling_back() -> None:
    """Silently scoring with a stub because a key was missing would put fake
    sentiment inside a real signal."""
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        build_llm_client(base_settings(llm_provider="openai", openai_api_key=""))


def test_the_configured_model_reaches_the_client() -> None:
    client = build_llm_client(
        base_settings(llm_provider="openai", openai_api_key="k", llm_model="some-other-model")
    )
    assert client.model == "some-other-model"


def test_the_default_model_is_one_that_accepts_temperature_zero() -> None:
    """Newer OpenAI models refuse temperature=0 and demand max_completion_tokens,
    which would cost reproducibility and 400 on every call. Verified live."""
    client = build_llm_client(base_settings(llm_provider="openai", openai_api_key="k"))
    assert client.model == "gpt-4.1-mini"
