from __future__ import annotations

from keywords import best_keyword, keyword_matches, normalize_keywords, split_keywords


def test_split_keywords_trims_dedupes_and_keeps_order():
    assert split_keywords(" Price, cost ,, HOW  MUCH\nprice ") == [
        "Price",
        "cost",
        "HOW MUCH",
    ]


def test_split_keywords_handles_empty_values():
    assert split_keywords(None) == []
    assert split_keywords(" , , ") == []


def test_normalize_keywords():
    assert normalize_keywords("price,PRICE, cost ") == "price, cost"


def test_keyword_matching_is_case_insensitive_and_partial():
    assert keyword_matches("price", "Can I get the PRICE list?")
    assert keyword_matches("how much", "so... HOW   MUCH is it?")
    assert keyword_matches("guide", "GUIDE")
    assert not keyword_matches("price", "prince")


def test_best_keyword_prefers_longest_match():
    keywords = ["price", "how much", "much"]
    assert best_keyword(keywords, "How much is the price?") == "how much"


def test_best_keyword_returns_none_without_match():
    assert best_keyword(["price"], "nice photo") is None
