"""URL canonicalisation and near-duplicate title matching.

These two decide what the reader sees once and what the signal counts once, so
both failure directions matter: a missed duplicate shows a story three times and
lets it vote three times, while a false merge hides a real article entirely.
"""

from __future__ import annotations

import pytest

from app.services.dedup import (
    NEAR_DUPLICATE_BITS,
    canonical_url,
    hamming,
    is_near_duplicate,
    normalise_title,
    simhash,
)


class TestCanonicalUrl:
    @pytest.mark.parametrize(
        "variant",
        [
            "https://example.com/story",
            "http://example.com/story",
            "https://www.example.com/story",
            "https://EXAMPLE.com/story",
            "https://example.com/story/",
            "https://example.com/story#section-2",
            "https://example.com/story?utm_source=newsletter&utm_medium=email",
            "https://example.com/story?fbclid=abc123",
        ],
    )
    def test_the_same_article_written_many_ways_is_one_key(self, variant: str) -> None:
        assert canonical_url(variant) == canonical_url("https://example.com/story")

    def test_meaningful_query_parameters_are_kept(self) -> None:
        """?id=42 selects the article; dropping it would merge two stories."""
        assert canonical_url("https://example.com/a?id=42") != canonical_url(
            "https://example.com/a?id=43"
        )

    def test_parameter_order_does_not_create_a_second_key(self) -> None:
        assert canonical_url("https://e.com/a?b=1&a=2") == canonical_url("https://e.com/a?a=2&b=1")

    def test_different_articles_stay_different(self) -> None:
        assert canonical_url("https://e.com/one") != canonical_url("https://e.com/two")

    def test_paths_keep_their_case_because_servers_may_care(self) -> None:
        assert canonical_url("https://e.com/Story") != canonical_url("https://e.com/story")


class TestSimhash:
    def test_a_fingerprint_fits_in_a_signed_bigint(self) -> None:
        """Postgres BIGINT is signed; an unsigned 64-bit value would not store."""
        for title in ("Apple beats earnings", "x", "a" * 500, "Ünïcôde ðŸ™‚ headline"):
            value = simhash(title)
            assert -(2**63) <= value < 2**63

    def test_the_same_title_always_fingerprints_the_same(self) -> None:
        assert simhash("Tesla recalls 400,000 vehicles") == simhash(
            "Tesla recalls 400,000 vehicles"
        )

    def test_word_order_and_punctuation_do_not_matter_much(self) -> None:
        a = simhash("Tesla recalls 400,000 vehicles over steering fault")
        b = simhash("Tesla recalls 400,000 vehicles over a steering fault.")
        assert is_near_duplicate(a, b)

    def test_a_syndicated_headline_with_a_suffix_is_the_same_story(self) -> None:
        a = simhash("Nvidia and Groq sign $20 billion licensing deal")
        b = simhash("Nvidia and Groq sign $20 billion licensing deal - report")
        assert is_near_duplicate(a, b)

    def test_the_threshold_separates_the_measured_corpus(self) -> None:
        """The evidence NEAR_DUPLICATE_BITS was chosen from.

        Duplicate pairs are real syndication seen in the Finnhub feed; the
        distinct pairs are different stories about the same company, which is
        the hard case. Measured: duplicates 0-9 bits, distinct 19-33. If a
        change to the fingerprint closes that gap, this fails before a false
        merge starts hiding articles in production.
        """
        duplicates = [
            (
                "Tesla Locks In $30 Billion Credit Line To Fund AI",
                "Tesla Locks In $30 Billion In Credit Line To Fund AI",
            ),
            (
                "Nvidia and Groq sign $20 billion licensing deal",
                "Nvidia and Groq sign $20 billion licensing deal - report",
            ),
            (
                "Top Midday Stories: Micron Shares Fall Despite Strong Earnings",
                "Correction: Top Midday Stories: Micron Shares Fall Despite Strong Earnings",
            ),
            (
                "Amazon announces new AI data centre in Ohio",
                "Amazon announces new AI data center in Ohio",
            ),
            (
                "Meta sued over teen safety claims",
                "Meta sued over teen safety claims, filing shows",
            ),
        ]
        distinct = [
            (
                "Apple beats quarterly earnings expectations",
                "Apple faces antitrust investigation in Europe",
            ),
            ("Nvidia stock hits record high", "Nvidia and Groq sign $20 billion licensing deal"),
            ("Tesla recalls 400,000 vehicles", "Tesla opens new factory in Berlin"),
            ("Amazon announces new AI data centre in Ohio", "Amazon cuts 14,000 corporate jobs"),
            ("Why RXO Stock Soared Today", "Why Rocket Lab Stock Dropped Today"),
        ]

        worst_duplicate = max(hamming(simhash(a), simhash(b)) for a, b in duplicates)
        closest_distinct = min(hamming(simhash(a), simhash(b)) for a, b in distinct)

        assert worst_duplicate <= NEAR_DUPLICATE_BITS < closest_distinct
        # And the gap is real, not a threshold wedged against the data.
        assert closest_distinct - worst_duplicate >= 8

    def test_different_stories_about_the_same_company_are_not_merged(self) -> None:
        a = simhash("Apple beats quarterly earnings expectations")
        b = simhash("Apple faces antitrust investigation in Europe")
        assert not is_near_duplicate(a, b)
        assert hamming(a, b) > NEAR_DUPLICATE_BITS

    def test_an_empty_fingerprint_never_merges(self) -> None:
        """A stopword-only title is no evidence, so it must not swallow articles."""
        assert simhash("the and of") == 0
        assert not is_near_duplicate(0, simhash("Apple beats earnings"))
        assert not is_near_duplicate(0, 0)

    def test_stopwords_are_dropped_from_comparison(self) -> None:
        assert normalise_title("The Apple and the Earnings") == ["apple", "earnings"]
