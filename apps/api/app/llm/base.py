"""The LLM client interface.

Same shape as `providers/base.py`, for the same reason: the vendor is a
configuration choice, not an architectural one. Everything above this layer
sends a prompt and receives text, so swapping OpenAI for another vendor is a
new implementation of this Protocol and a line in the registry.

Callers never see vendor error types. Every failure arrives as `LLMError` (or
`LLMRateLimited`), because a scoring failure must degrade to "no sentiment yet"
rather than break an ingest run.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol, runtime_checkable


class LLMError(Exception):
    """Any failure talking to an LLM. Callers degrade; they never crash a job."""

    def __init__(self, vendor: str, message: str) -> None:
        super().__init__(f"{vendor}: {message}")
        self.vendor = vendor


class LLMRateLimited(LLMError):
    """Vendor asked us to slow down. The caller retries on the next cycle."""


class LLMRefused(LLMError):
    """The model returned something unusable - not JSON, or failing validation."""


@dataclass(frozen=True)
class LLMResponse:
    text: str
    #: Which model actually answered. Stored with every score, so a score can be
    #: reproduced against the exact model that produced it.
    model: str
    input_tokens: int | None = None
    output_tokens: int | None = None


#: text-embedding-3-small. Must match EMBEDDING_DIMENSIONS on the column.
EMBEDDING_DIMENSIONS = 1536


@runtime_checkable
class LLMClient(Protocol):
    name: str
    model: str
    #: True when answers are generated locally rather than by a real model.
    is_simulated: bool

    #: Which model embeds text. Stored next to every vector, because vectors
    #: from two models are not comparable and a silent swap poisons retrieval.
    embedding_model: str

    def complete(
        self,
        system: str,
        user: str,
        *,
        max_tokens: int = 512,
        json_object: bool = False,
    ) -> LLMResponse:
        """Answer one prompt. Implementations set temperature 0: the same article
        must score the same way twice, or a signal cannot be reproduced.

        `json_object` asks the vendor to guarantee parseable JSON. Opt-in, not
        default: the analyst answers in prose, and OpenAI rejects JSON mode
        unless the prompt itself asks for JSON.
        """
        ...

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        """Embed a batch, returning one vector per input, in the same order."""
        ...
