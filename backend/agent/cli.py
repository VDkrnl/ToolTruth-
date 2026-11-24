"""agent/cli.py — demo CLI (needs the gateway running with TT_AGENT_API_KEY set on both sides).

    python -m agent.cli "Find a wireless mouse under Rs 1,500 and buy 1."
"""
import sys

from agent.client import ToolTruthClient
from agent.config import load_settings
from agent.runner import make_agent, run_chat


def main() -> None:
    message = " ".join(sys.argv[1:]) or "Find a wireless mouse under Rs 1,500 and buy 1."
    settings = load_settings()
    out = run_chat(make_agent(settings, ToolTruthClient(settings)), settings, message)
    for t in out["trace"]:
        if t["type"] == "tool_call":
            print(f"-> {t['name']}({t['args']})")
        else:
            print(f"   {t['content'].splitlines()[0]}")
    print(f"\n[{out['mode']}] {out['answer']}")


if __name__ == "__main__":
    main()
