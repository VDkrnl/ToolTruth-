"""
agent/config.py — agent-side settings loaded exclusively from environment variables.

Design: The agent process has NO Shopify credentials.  Only TT_GATEWAY_URL and
TT_AGENT_API_KEY are needed here.  All Shopify env vars live in the gateway's
separate EnvironmentFile (tooltruth-api.service).

Agent modes
-----------
  shopping        — the default mode; search/buy tools against the Shopify store.
  shopify_content — read/write Shopify store content (products, pages, blogs,
                    collections, metafields).  No order placement.
"""
import os
from dataclasses import dataclass

# Valid agent-mode identifiers.
AGENT_MODES = ("shopping", "shopify_content")


@dataclass(frozen=True)
class AgentSettings:
    # Where the ToolTruth gateway lives (gateway process only, never Shopify directly).
    gateway_url: str = "http://127.0.0.1:8000"
    # Shared secret: gateway validates X-Agent-Key on /agent/* routes.
    agent_api_key: str = ""
    # e.g. "google_genai:gemini-2.0-flash" — None → use ScriptedShopper (keyless CI).
    model: str | None = None
    # Optional OpenAI-compatible endpoint (Groq, OpenRouter, ...). Key is TT_LLM_API_KEY.
    llm_base_url: str | None = None
    llm_api_key: str | None = None
    # Safety caps forwarded to the agent loop.
    max_tool_calls: int = 8
    max_model_calls: int = 12
    # HTTP timeouts for gateway calls (seconds).
    read_timeout: float = 10.0
    write_timeout: float = 15.0
    # Agent operating mode: "shopping" (default) or "shopify_content".
    agent_mode: str = "shopping"


def load_settings() -> AgentSettings:
    """Read settings from environment variables.

    Call once at startup; the returned object is frozen (immutable).
    """
    raw_mode = os.getenv("TT_AGENT_MODE", "shopping").lower().strip()
    agent_mode = raw_mode if raw_mode in AGENT_MODES else "shopping"
    return AgentSettings(
        gateway_url=os.getenv("TT_GATEWAY_URL", "http://127.0.0.1:8000").rstrip("/"),
        agent_api_key=os.getenv("TT_AGENT_API_KEY", ""),
        model=os.getenv("TT_AGENT_MODEL") or None,
        llm_base_url=os.getenv("TT_LLM_BASE_URL") or None,
        llm_api_key=os.getenv("TT_LLM_API_KEY") or None,
        max_tool_calls=int(os.getenv("TT_MAX_TOOL_CALLS", "8")),
        max_model_calls=int(os.getenv("TT_MAX_MODEL_CALLS", "12")),
        read_timeout=float(os.getenv("TT_READ_TIMEOUT", "10")),
        write_timeout=float(os.getenv("TT_WRITE_TIMEOUT", "15")),
        agent_mode=agent_mode,
    )
