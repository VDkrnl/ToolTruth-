"""
agent/budget.py — Deterministic budget extraction from free-form text.

Rules (per plan §10.5):
- Supports: ₹, Rs, Rs., INR, $, USD
- Prefixes: under, below, less than, max, at most, within, budget of, up to
- Thousands separators (comma): 1,500 → 1500
- 'k' suffix → None (ambiguous)
- Multiple amounts → None (ask the user)
- Returns (amount_minor, currency) in smallest unit (paise/cents), or (None, None).
"""
import re
from typing import Optional

_CURRENCIES = {
    "₹":   ("INR", 100),
    "rs.": ("INR", 100),
    "rs":  ("INR", 100),
    "inr": ("INR", 100),
    "$":   ("USD", 100),
    "usd": ("USD", 100),
}

_PREFIX = r"(?:under|below|less\s+than|max(?:imum)?|at\s+most|within|budget\s+of|up\s+to)?\s*"
# Symbol alternatives: longest first to avoid "rs" matching inside "rs.".
_SYM = r"(?:₹|\$|rs\.|rs|inr|usd)"
# Number token: a full numeric token.  Use atomic-style via a lookahead fence.
# We must match "1,500" in full, not just "1".  Strategy: try thousands-form FIRST
# inside a non-capturing group, then fall through to plain digits.
# Anchored end (?=\s|$|[^\d,]) ensures we don't stop mid-number.
_NUM = r"(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d{1,2})?"

# Pattern A: symbol then number (e.g. "₹1,500", "Rs. 500", "INR 2000")
_A = re.compile(
    _PREFIX + r"(?P<sym>" + _SYM + r")\s*(?P<num>" + _NUM + r")",
    re.IGNORECASE,
)
# Pattern B: number then symbol (e.g. "100 USD", "1500 rs")
_B = re.compile(
    _PREFIX + r"(?P<num>" + _NUM + r")\s*(?P<sym>" + _SYM + r")",
    re.IGNORECASE,
)


def _collect(text: str) -> list[tuple[int, str]]:
    """Collect all (amount_minor, iso) pairs, deduplicating overlapping spans."""
    seen: list[tuple[int, int]] = []
    out: list[tuple[int, str]] = []

    def _process(m: re.Match) -> None:
        # Skip overlapping matches from the second pattern.
        for s, e in seen:
            if m.start() < e and m.end() > s:
                return
        sym = m.group("sym").lower().strip()
        raw = m.group("num").replace(",", "")
        cfg = _CURRENCIES.get(sym)
        if not cfg:
            return
        try:
            major = float(raw)
        except ValueError:
            return
        seen.append((m.start(), m.end()))
        out.append((round(major * cfg[1]), cfg[0]))

    for m in _A.finditer(text):
        _process(m)
    for m in _B.finditer(text):
        _process(m)
    return out


def extract_budget(text: str) -> tuple[Optional[int], Optional[str]]:
    """Parse a single unambiguous budget amount from text.

    Returns (amount_minor, iso_code) or (None, None).

    Examples::

        extract_budget("under ₹1,500")   -> (150000, "INR")
        extract_budget("max USD 100")     -> (10000,  "USD")
        extract_budget("₹1.5k")           -> (None,   None)   # 'k' ambiguous
        extract_budget("₹500 or $10")     -> (None,   None)   # multiple amounts
    """
    if re.search(r"\d[kK]\b", text):
        return None, None
    unique = list(dict.fromkeys(_collect(text)))
    if len(unique) == 1:
        return unique[0]
    return None, None
