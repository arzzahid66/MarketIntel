"""Article deduplication: canonical URL, then near-duplicate title matching.

Wire stories arrive many times over. The same Reuters piece reaches us from
Finnhub under three publishers, with three URLs, each carrying its own tracking
parameters - and a feed that shows it three times looks broken, while an LLM
that scores it three times charges us three times and lets one story vote three
times in the signal.

Two layers, cheapest first:

  1. **Canonical URL.** Strip tracking parameters, fragments, trailing slashes
     and the scheme. Catches the same article linked twice. Enforced by a unique
     constraint, so a race between two workers cannot insert both.
  2. **Title simhash.** A 64-bit fingerprint where similar titles differ in few
     bits. Catches the same story syndicated under different URLs, which layer 1
     cannot see. Compared with Hamming distance; `NEAR_DUPLICATE_BITS` is the
     threshold.

Simhash rather than exact title hashing because publishers rewrite headlines
slightly - a suffix, a different dash, "Inc." dropped. Exact hashing would catch
almost none of those.
"""

from __future__ import annotations

import hashlib
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

#: Query parameters that identify the referrer, not the article.
TRACKING_PREFIXES = ("utm_", "ga_", "_hs", "mc_")
TRACKING_PARAMS = {
    "fbclid",
    "gclid",
    "igshid",
    "mkt_tok",
    "ref",
    "ref_src",
    "referrer",
    "source",
    "spm",
    "yptr",
    "cmpid",
    "ncid",
    "partner",
    "__source",
}

#: Titles differing in at most this many of 64 bits are the same story.
#:
#: Measured, not guessed. Over the corpus in `test_dedup.py` - real syndication
#: pairs seen in the Finnhub feed against genuinely different stories about the
#: same company - duplicates fall at 0-9 bits and distinct stories at 19-33,
#: with nothing in between. 12 sits in that gap with margin either side.
#:
#: Widen it only with evidence: a false merge hides a real article, which is
#: worse than showing a near-duplicate twice. `test_the_threshold_separates_the
#: _measured_corpus` fails if a change breaks the separation.
NEAR_DUPLICATE_BITS = 12

#: A title shorter than this carries too little evidence to merge on - see
#: `simhash`. Four is below any real headline and above the degenerate cases.
MIN_TOKENS = 4

#: Words carrying no signal for "is this the same story".
_STOPWORDS = frozenset(
    # fmt: off
    [
        "a",
        "an",
        "the",
        "and",
        "or",
        "but",
        "of",
        "for",
        "to",
        "in",
        "on",
        "at",
        "by",
        "with",
        "from",
        "as",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "it",
        "its",
        "this",
        "that",
        "these",
        "those",
        "will",
        "would",
        "can",
        "could",
        "has",
        "have",
        "had",
        "not",
        "no",
    ]
    # fmt: on
)
_WORD = re.compile(r"[a-z0-9']+")


def canonical_url(url: str) -> str:
    """A URL reduced to what identifies the article.

    Scheme and `www.` go because http/https and the www variant are the same
    page. The host is lower-cased; the path is not, because paths can be
    case-sensitive. Remaining query parameters are sorted so that two orderings
    of the same parameters produce one key.
    """
    parts = urlsplit(url.strip())
    host = parts.netloc.lower().removeprefix("www.").rstrip(".")
    # Strip a default port, which is the same address written two ways.
    for scheme, port in (("http", ":80"), ("https", ":443")):
        if parts.scheme.lower() == scheme and host.endswith(port):
            host = host[: -len(port)]

    kept = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=False)
        if key.lower() not in TRACKING_PARAMS and not key.lower().startswith(TRACKING_PREFIXES)
    ]
    path = parts.path.rstrip("/") or "/"
    # Fragment dropped entirely: it never identifies a different article.
    return urlunsplit(("", host, path, urlencode(sorted(kept)), ""))


def normalise_title(title: str) -> list[str]:
    """Title to comparable tokens: lower-cased, punctuation and stopwords gone."""
    return [w for w in _WORD.findall(title.lower()) if w not in _STOPWORDS]


def simhash(title: str) -> int:
    """A 64-bit fingerprint of a title. Similar titles differ in few bits.

    Each token votes on every bit, weighted by how often it appears; the sign of
    each column becomes that bit. Two titles sharing most tokens therefore agree
    on most bits, however the shared tokens are ordered.

    Returns 0 - "no evidence", which never merges - for a title with fewer than
    MIN_TOKENS meaningful words. With two or three tokens a single different
    word still leaves the fingerprints close, so "Story 1" and "Story 2" would
    merge as the same article. Real headlines run well past this floor.
    """
    tokens = normalise_title(title)
    if len(tokens) < MIN_TOKENS:
        return 0

    columns = [0] * 64
    for token in tokens:
        digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
        value = int.from_bytes(digest, "big")
        for bit in range(64):
            columns[bit] += 1 if value >> bit & 1 else -1

    result = 0
    for bit, column in enumerate(columns):
        if column > 0:
            result |= 1 << bit
    # Postgres BIGINT is signed; map the top half into the negative range so the
    # value round-trips through the database unchanged.
    return result - (1 << 64) if result >= 1 << 63 else result


def hamming(left: int, right: int) -> int:
    return ((left ^ right) & ((1 << 64) - 1)).bit_count()


def is_near_duplicate(left: int, right: int, max_bits: int = NEAR_DUPLICATE_BITS) -> bool:
    """Whether two title fingerprints are the same story.

    A zero fingerprint means an empty or stopword-only title, which carries no
    evidence either way - never merge on it.
    """
    if not left or not right:
        return False
    return hamming(left, right) <= max_bits
