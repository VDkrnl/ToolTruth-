"""agent/client.py — thin httpx client for the ToolTruth gateway (/agent/*)."""
import httpx

from agent.config import AgentSettings


class GatewayUnavailable(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


class ToolTruthClient:
    def __init__(self, settings: AgentSettings, transport: httpx.BaseTransport | None = None):
        self._s = settings
        self._http = httpx.Client(base_url=settings.gateway_url, transport=transport,
                                  headers={"X-Agent-Key": settings.agent_api_key})

    def _post(self, path: str, body: dict, timeout: float, retries: int) -> dict:
        last = "unreachable"
        for _ in range(retries + 1):
            try:
                r = self._http.post(path, json=body, timeout=timeout)
            except httpx.HTTPError:
                last = "timeout_or_unreachable"
                continue
            if r.status_code == 401:
                raise GatewayUnavailable("agent_not_authorised")
            if r.status_code >= 500:
                last = f"http_{r.status_code}"
                continue
            if r.status_code >= 400:
                raise GatewayUnavailable(f"rejected_{r.status_code}")
            return r.json()
        raise GatewayUnavailable(last)

    def read(self, tool: str, args: dict, session_id: str) -> dict:
        # reads are idempotent: one retry
        return self._post(f"/agent/read/{tool}", {"session_id": session_id, "args": args},
                          self._s.read_timeout, retries=1)

    def write(self, tool: str, args: dict, session_id: str, run_context: dict) -> dict:
        # writes are NEVER retried
        return self._post(f"/agent/write/{tool}",
                          {"session_id": session_id, "args": args, "run_context": run_context},
                          self._s.write_timeout, retries=0)

    def provider(self) -> str | None:
        try:
            r = self._http.get("/agent/tools", timeout=3)
            return r.json().get("provider") if r.status_code == 200 else None
        except (httpx.HTTPError, ValueError):
            return None
