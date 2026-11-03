import requests
from .types import GatewayResponse, EvidenceGraph


class ToolTruthClient:
    def __init__(self, base_url: str, api_key: str | None = None):
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        if api_key:
            self.session.headers["Authorization"] = f"Bearer {api_key}"

    def call(
        self,
        domain: str,
        action: str,
        payload: dict,
        *,
        agent_id: str = "sdk-client",
        context: dict | None = None,
        fault_config: dict | None = None,
    ) -> GatewayResponse:
        """Submit a tool call for consistency verification.

        Args:
            domain:       Domain name ("ecommerce", "devops", "travel").
            action:       Action name within the domain.
            payload:      Tool call payload dict.
            agent_id:     Identifier for the calling agent.
            context:      Optional context snapshot for user-constraint checks.
            fault_config: Optional fault-injection config (prototype only).
        """
        body: dict = {
            "domain": domain,
            "action": action,
            "payload": payload,
            "agent_id": agent_id,
            "context_snapshot": context or {},
        }
        if fault_config is not None:
            body["fault_config"] = fault_config
        r = self.session.post(f"{self.base_url}/gateway/call", json=body)
        r.raise_for_status()
        return GatewayResponse.model_validate(r.json())

    def get_evidence(self, entity_id: str) -> EvidenceGraph:
        r = self.session.get(f"{self.base_url}/gateway/evidence/{entity_id}")
        r.raise_for_status()
        return EvidenceGraph.model_validate(r.json())

    def run_benchmark(self, domain: str, mode: str = "tooltruth") -> dict:
        """Run a benchmark suite.

        .. note::
            This endpoint requires an **admin token**.  Pass your admin JWT as
            ``api_key`` when constructing the client:

            .. code-block:: python

                client = ToolTruthClient(base_url, api_key=admin_token)
                client.run_benchmark("ecommerce")
        """
        r = self.session.post(
            f"{self.base_url}/benchmark/run",
            json={"domain": domain, "mode": mode},
        )
        r.raise_for_status()
        return r.json()
