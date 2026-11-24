"""
agent/context.py — RunContext dataclass passed as LangChain context_schema.

The agent receives this at invoke-time.  The gateway middleware reads it to
apply per-session budget enforcement without trusting the LLM's prose.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class RunContext:
    """Per-run context injected by the caller (UI or CLI).

    All monetary amounts are in the *smallest currency unit* (e.g. paise for INR,
    cents for USD) to avoid float rounding.  None means the user did not state a
    budget; the agent should ask before attempting any purchase.
    """
    session_id: str
    budget_minor: int | None = None   # e.g. 150_000 for ₹1,500 (paise)
    currency: str | None = None       # e.g. "INR", "USD"
    fault: str | None = None          # demo fault injection (UI dropdown); honoured only when the gateway enables it
