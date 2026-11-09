"""A deterministic stand-in for a real model.

Lets the whole news pipeline - ingest, score, aggregate, feed the signal - run in
development, tests and CI without an API key, a network call or a bill. It is
never a stand-in for a real model in front of a customer: `is_simulated` is True
and every score it produces is stored with its model name, so a simulated score
is always identifiable in the database.

It is a keyword scorer, not a language model. It exists to exercise the contract
(valid JSON, bounded score, sane materiality), not to be accurate.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Sequence

from app.llm.base import EMBEDDING_DIMENSIONS, LLMResponse

MODEL = "simulated-keyword-scorer"
EMBEDDING_MODEL = "simulated-hash-embedding"

#: Words that move a business, with the direction they usually move it. Chosen to
#: cover the material-event categories the prompt asks the model to weigh.
_POSITIVE = {
    "beats": 0.7,
    "raises": 0.6,
    "upgrade": 0.5,
    "approval": 0.6,
    "wins": 0.5,
    "record": 0.5,
    "expands": 0.4,
    "partnership": 0.4,
    "buyback": 0.4,
}
_NEGATIVE = {
    "fraud": -1.0,
    "bankruptcy": -1.0,
    "investigation": -0.7,
    "lawsuit": -0.6,
    "recall": -0.6,
    "misses": -0.6,
    "cuts": -0.5,
    "downgrade": -0.5,
    "layoffs": -0.4,
    "probe": -0.6,
}
#: Material events get full weight; anything else is routine coverage.
_MATERIAL = {
    "earnings",
    "guidance",
    "lawsuit",
    "investigation",
    "probe",
    "regulation",
    "ceo",
    "acquisition",
    "merger",
    "recall",
    "fraud",
    "bankruptcy",
}


#: Words that hint at a category, checked against the keys offered in the prompt.
_CATEGORY_HINTS = {
    "earnings": ("earnings", "guidance", "revenue", "beats", "misses"),
    "regulation": ("investigation", "probe", "lawsuit", "regulator", "antitrust"),
    "oil": ("oil", "crude", "opec", "barrel"),
    "bitcoin": ("bitcoin", "crypto", "ethereum", "token"),
    "central-banks": ("fed", "rates", "inflation", "ecb"),
    "tech": ("ai", "chip", "software", "cloud", "device"),
}


def _category(prompt: str) -> str | None:
    """Pick a category key that the prompt actually offered, or none."""
    body = prompt.lower()
    offered = [key for key in _CATEGORY_HINTS if f"- {key}:" in body]
    for key in offered:
        if any(word in body for word in _CATEGORY_HINTS[key]):
            return key
    return offered[0] if offered else None


class FakeLLM:
    name = "simulated"
    model = MODEL
    embedding_model = EMBEDDING_MODEL
    is_simulated = True

    def complete(
        self,
        system: str,
        user: str,
        *,
        max_tokens: int = 512,
        json_object: bool = False,
    ) -> LLMResponse:
        words = set(re.findall(r"[a-z]+", user.lower()))
        hits = [_POSITIVE[w] for w in words & _POSITIVE.keys()]
        hits += [_NEGATIVE[w] for w in words & _NEGATIVE.keys()]

        score = round(sum(hits) / len(hits), 2) if hits else 0.0
        score = max(-1.0, min(1.0, score))
        material = bool(words & _MATERIAL)

        if score > 0.15:
            label = "positive"
        elif score < -0.15:
            label = "negative"
        else:
            label = "neutral"

        payload = {
            "sentiment": score,
            "label": label,
            "materiality": "high" if material else "low",
            "rationale": f"Simulated keyword score from {len(hits)} matched term(s).",
            # The prompt lists the categories in the user message; pick the first
            # whose key appears there, so the stub exercises the same field the
            # real model fills rather than leaving it permanently null.
            "category": _category(user),
            "summary": "Simulated one-line summary.",
        }
        return LLMResponse(text=json.dumps(payload), model=MODEL)

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        """Deterministic unit vectors derived from the text's own words.

        Not semantic - it cannot know that "lawsuit" and "litigation" are
        related - but it is stable, normalised, and gives texts sharing words a
        higher cosine similarity than texts that share none. That is enough to
        exercise retrieval end to end without a key or a bill.
        """
        return [_hash_vector(text) for text in texts]


def _hash_vector(text: str, dimensions: int = EMBEDDING_DIMENSIONS) -> list[float]:
    vector = [0.0] * dimensions
    for word in re.findall(r"[a-z0-9]+", text.lower()):
        digest = hashlib.blake2b(word.encode("utf-8"), digest_size=8).digest()
        index = int.from_bytes(digest[:4], "big") % dimensions
        # Sign from a separate byte, so two words rarely cancel by accident.
        vector[index] += 1.0 if digest[4] & 1 else -1.0
    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0.0:
        # A zero vector has no direction; cosine distance against it is
        # undefined, so give it one deterministic fixed direction instead.
        vector[0] = 1.0
        return vector
    return [value / norm for value in vector]
