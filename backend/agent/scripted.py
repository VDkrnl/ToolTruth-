"""
agent/scripted.py — Deterministic stand-in for an LLM (no API key required).

Pattern from Appendix C.3: subclass BaseChatModel, override _generate to
replay a scripted sequence of AIMessages.  Used in CI and keyless demos.

ScriptedShopper extends ScriptedModel to inspect the last ToolMessage and
choose the next tool call, making one class serve all test scenarios A-E.
"""
from __future__ import annotations

import re
from typing import Any, Iterator, Optional, Sequence

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import ConfigDict


# ---------------------------------------------------------------------------
# Base class (Appendix C.3 proven pattern)
# ---------------------------------------------------------------------------

class ScriptedModel(BaseChatModel):
    """Deterministic stand-in: replays a fixed script of AIMessages."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    script: list = []
    i: int = 0

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def bind_tools(self, tools: Sequence[Any], **kw: Any) -> "ScriptedModel":
        return self

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: Optional[list[str]] = None,
        run_manager: Any = None,
        **kw: Any,
    ) -> ChatResult:
        msg = self.script[min(self.i, len(self.script) - 1)]
        self.i += 1
        return ChatResult(generations=[ChatGeneration(message=msg)])

    def _stream(
        self,
        messages: list[BaseMessage],
        stop: Optional[list[str]] = None,
        run_manager: Any = None,
        **kw: Any,
    ) -> Iterator[ChatGeneration]:
        yield from self._generate(messages, stop, run_manager, **kw).generations


# ---------------------------------------------------------------------------
# Scripted shopping agent (plan §10.7)
# ---------------------------------------------------------------------------

def _tc(name: str, args: dict, idx: int) -> dict:
    return {"name": name, "args": args, "id": f"scripted-{idx}", "type": "tool_call"}


class ScriptedShopper(BaseChatModel):
    """Shopping-domain scripted model.

    Deterministic flow for 'find a wireless mouse':
      Step 0: call search_products
      Step 1: call get_product_details
      Step 2: call check_inventory
      Step 3: call create_test_order
      Step 4+: compose final answer from last ToolMessage TT_* line
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    @property
    def _llm_type(self) -> str:
        return "scripted-shopper"

    def bind_tools(self, tools: Sequence[Any], **kw: Any) -> "ScriptedShopper":
        return self

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _last_tool_message(messages: list[BaseMessage]) -> Optional[ToolMessage]:
        for m in reversed(messages):
            if isinstance(m, ToolMessage):
                return m
        return None

    @staticmethod
    def _extract(pattern: str, content: str, default: str) -> str:
        m = re.search(pattern, content, re.IGNORECASE)
        return m.group(1) if m else default

    @classmethod
    def _build_final_answer(cls, last_tool: Optional[ToolMessage]) -> str:
        if last_tool is None:
            return "[scripted demo model] Could not confirm stock. Please try again."
        content = getattr(last_tool, "content", "") or ""
        tt_line = next((l for l in content.splitlines() if l.startswith("TT_")), "")
        sku = cls._extract(r"((?:SKU|TT)-[A-Z0-9_-]+)", content, "TT-MOUSE-1")
        if "TT_DECISION=allow" in tt_line and "TT_EXEC=succeeded" in tt_line:
            return f"[scripted demo model] Your test order for {sku} has been placed and verified. {tt_line}"
        if "TT_DECISION=block" in tt_line:
            return f"[scripted demo model] ToolTruth blocked the purchase of {sku}. {content}"
        if "TT_DECISION=request_more_evidence" in tt_line:
            return f"[scripted demo model] ToolTruth needs more evidence for {sku}. {content}"
        return f"[scripted demo model] I found {sku} in the catalogue. Details: {content[:200]}"

    # ------------------------------------------------------------------
    # Main generation logic
    # ------------------------------------------------------------------

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: Optional[list[str]] = None,
        run_manager: Any = None,
        **kw: Any,
    ) -> ChatResult:
        step = sum(1 for m in messages if isinstance(m, ToolMessage))
        last_tool = self._last_tool_message(messages)
        last_content = getattr(last_tool, "content", "") if last_tool else ""

        user = next((m.content for m in messages if m.type == "human"), "") or ""
        qm = re.search(r"(?:buy|order|purchase|get)\s+(\d+)", user, re.IGNORECASE)
        qty = int(qm.group(1)) if qm else 1
        km = re.search(r"(?:find|search for|looking for|show me)\s+(?:me\s+)?(?:a|an|the|some)?\s*([a-z][a-z -]*?)\s*(?:under|below|and|for|$|\.)", user, re.IGNORECASE)
        query = km.group(1).strip().lower() if km and km.group(1).strip() else "wireless mouse"

        if step == 0:
            msg = AIMessage(content="", tool_calls=[_tc("search_products", {"query": query}, 1)])
        elif step == 1:
            sku = self._extract(r"((?:SKU|TT)-[A-Z0-9_-]+)", last_content, "TT-MOUSE-1")
            msg = AIMessage(content="", tool_calls=[_tc("get_product_details", {"sku": sku}, 2)])
        elif step == 2:
            sku = self._extract(r"((?:SKU|TT)-[A-Z0-9_-]+)", last_content, "TT-MOUSE-1")
            msg = AIMessage(content="", tool_calls=[_tc("check_inventory", {"sku": sku}, 3)])
        elif step == 3:
            sku = self._extract(r"((?:SKU|TT)-[A-Z0-9_-]+)", last_content, "TT-MOUSE-1")
            vid = self._extract(r"variant_id[=:]\s*(\S+)", last_content, "var-SKU-100")
            oid = self._extract(r"observation_id[=:]\s*([A-Za-z0-9_-]+)", last_content, "obs-demo-1")
            msg = AIMessage(content="", tool_calls=[
                _tc("create_test_order", {"variant_id": vid, "sku": sku, "quantity": qty, "observation_id": oid}, 4)
            ])
        else:
            msg = AIMessage(content=self._build_final_answer(last_tool))

        return ChatResult(generations=[ChatGeneration(message=msg)])

    def _stream(
        self,
        messages: list[BaseMessage],
        stop: Optional[list[str]] = None,
        run_manager: Any = None,
        **kw: Any,
    ) -> Iterator[ChatGeneration]:
        yield from self._generate(messages, stop, run_manager, **kw).generations
