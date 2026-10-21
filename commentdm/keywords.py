"""Keyword parsing and matching.

Rules (documented in the README):
  * Case-insensitive.
  * Partial ("substring") match anywhere in the comment.
  * Keywords are separated by commas or newlines.
  * When several campaigns on a post match, the longest keyword wins (more
    specific beats more generic), then the newest campaign.
"""

from __future__ import annotations

import re

MAX_KEYWORDS = 25
MAX_KEYWORD_LENGTH = 60


def split_keywords(raw: str | None) -> list[str]:
    """Return de-duplicated keywords in the order the user entered them."""
    if not raw:
        return []
    parts = re.split(r"[,\n]", raw)
    seen: set[str] = set()
    result: list[str] = []
    for part in parts:
        keyword = " ".join(part.strip().split())
        if not keyword:
            continue
        key = keyword.casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append(keyword)
    return result


def normalize_keywords(raw: str | None) -> str:
    """Canonical form stored in the database (``"price, cost, how much"``)."""
    return ", ".join(split_keywords(raw))


def normalize_text(value: str | None) -> str:
    return " ".join((value or "").casefold().split())


def keyword_matches(keyword: str, text: str) -> bool:
    needle = normalize_text(keyword)
    return bool(needle) and needle in normalize_text(text)


def best_keyword(keywords: list[str], text: str) -> str | None:
    """Longest matching keyword wins."""
    haystack = normalize_text(text)
    matches = [kw for kw in keywords if kw.strip() and normalize_text(kw) in haystack]
    if not matches:
        return None
    return max(matches, key=lambda kw: (len(kw), kw.casefold()))
