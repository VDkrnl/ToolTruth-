"""agent/build.py — build the LangChain agent (Phase 1)."""
import warnings
from langchain.agents import create_agent
from langgraph.checkpoint.memory import InMemorySaver
from agent.config import AgentSettings
from agent.context import RunContext


def build_model(settings: AgentSettings):
    if settings.model:
        from langchain.chat_models import init_chat_model
        extra = {}
        if settings.llm_base_url:
            extra["base_url"] = settings.llm_base_url
        if settings.llm_api_key:
            extra["api_key"] = settings.llm_api_key
        return init_chat_model(settings.model, temperature=0, **extra)
    from agent.scripted import ScriptedShopper
    return ScriptedShopper()


def build_agent(settings: AgentSettings, tools: list, system_prompt: str, middleware: list | None = None):
    """Compile and return a LangChain agent graph.

    Args:
        settings: AgentSettings (from load_settings()).
        tools:    List of @tool-decorated callables.
        system_prompt: Instruction text passed to create_agent.

    Returns:
        A compiled agent (call .invoke() on it).
    """
    model = build_model(settings)
    checkpointer = InMemorySaver()
    return create_agent(
        model,
        tools,
        system_prompt=system_prompt,
        middleware=middleware or [],
        context_schema=RunContext,
        checkpointer=checkpointer,
    )
