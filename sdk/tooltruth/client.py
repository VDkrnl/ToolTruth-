
import requests
from .types import GatewayResponse, EvidenceGraph
class ToolTruthClient:
    def __init__(self,base_url,api_key=None):
        self.base_url=base_url.rstrip("/")
        self.session=requests.Session()
        if api_key: self.session.headers["Authorization"]=f"Bearer {api_key}"
    def call(self,domain,action,payload,context=None):
        r=self.session.post(f"{self.base_url}/gateway/call",json={"domain":domain,"action":action,"payload":payload,"context_snapshot":context or {}})
        r.raise_for_status(); return GatewayResponse.model_validate(r.json())
    def get_evidence(self,entity_id):
        r=self.session.get(f"{self.base_url}/gateway/evidence/{entity_id}")
        r.raise_for_status(); return EvidenceGraph.model_validate(r.json())
    def run_benchmark(self,domain,mode="tooltruth"):
        r=self.session.post(f"{self.base_url}/benchmark/run",json={"domain":domain,"mode":mode})
        r.raise_for_status(); return r.json()
