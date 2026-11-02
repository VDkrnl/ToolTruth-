"""Evidence writer + source cross-checks for LIVE (non-simulator) Shopify observations.

The simulator path (gateway/interceptor.py) is untouched. This class reuses the
same ConsistencyEngine, CheckResult objects, EventLog and EvidenceNode tables,
so a live call is judged by the same rules and leaves the same audit trail.
"""
import json
from datetime import datetime, timezone

from engine.schemas import CheckResult
from gateway.models import EvidenceEdge, EvidenceNode

from integrations.shopify.inventory import parse_iso, to_naive_utc

# Shopify: on_hand = available + committed + reserved + damaged + safety_stock + quality_control
# (incoming is excluded from the sum rule per Shopify docs)
ON_HAND_PARTS = ("available", "committed", "reserved", "damaged", "safety_stock", "quality_control")


class LiveShopifyHandler:
    """Writes evidence and performs cross-consistency checks on a Shopify observation.

    This is NOT the main HTTP handler — it is the evidence-recording helper used by
    both order_flow.py (via _record_evidence) and the standalone /shopify/get_inventory
    endpoint (via call()).
    """
    source = "shopify-admin-graphql"
    provider = "shopify"

    def __init__(self, db, client=None, settings=None):
        self.db = db
        self.client = client
        self.settings = settings

    @staticmethod
    def _check_source_consistency(q: dict) -> CheckResult:
        """Shopify's own numbers must add up. If they do not, we do not trust any of them."""
        if "on_hand" not in q:
            return CheckResult(name="source_consistency", passed=True,
                               reason="Shopify did not report on_hand, so the cross-check was skipped.")
        total = sum(q.get(k, 0) for k in ON_HAND_PARTS)
        if q["on_hand"] != total:
            return CheckResult(name="source_consistency", passed=False,
                               reason=f"Shopify's numbers disagree: on_hand={q['on_hand']} "
                                      f"but the parts add up to {total}.")
        return CheckResult(name="source_consistency", passed=True,
                           reason="Shopify's quantities are internally consistent (on_hand equals the sum of its parts).")

    def _record_evidence(self, obs: dict, fields: dict):
        """Write one EvidenceNode per scalar claim in *fields*.

        Args:
            obs:    The raw observation dict containing entity_id, fetched_at,
                    source_updated_at, inventory_item_numeric_id, location_numeric_id.
            fields: Mapping of field_name -> value. Keys beginning with 'as_of_timestamp'
                    are skipped (they are metadata, not claims).

        Returns:
            (evidence_dicts, changes_vs_previous) — both are lists.
        """
        entity = obs["entity_id"]
        fetched = parse_iso(obs.get("fetched_at")) or datetime.now(timezone.utc)
        updated = parse_iso(obs.get("source_updated_at"))
        evidence, changes = [], []

        for field, value in fields.items():
            if field == "as_of_timestamp":
                continue   # metadata key; not a claim

            # Look up the most recent node for this field at this entity
            prev = (self.db.query(EvidenceNode)
                    .filter(EvidenceNode.entity_id == entity,
                            EvidenceNode.provider == "shopify",
                            EvidenceNode.claim.like(f"{field}=%"))
                    .order_by(EvidenceNode.id.desc()).first())

            node = EvidenceNode(
                node_type="claim",
                entity_id=entity,
                claim=f"{field}={value}",
                source=self.source,
                confidence="1.0",
                schema_version="1.0",
                timestamp=to_naive_utc(fetched),
                provider="shopify",
                resource_id=obs.get("inventory_item_numeric_id") or None,
                location_id=obs.get("location_numeric_id") or None,
                source_updated_at=to_naive_utc(updated),
                fetched_at=to_naive_utc(fetched),
            )
            self.db.add(node)
            self.db.flush()

            if prev is not None:
                self.db.add(EvidenceEdge(
                    from_node_id=prev.id, to_node_id=node.id, relation_type="supercedes"))
                before = prev.claim.split("=", 1)[1]
                if before != str(value):
                    changes.append({"field": field, "from": before, "to": str(value)})

            evidence.append({
                "id": node.id,
                "claim": node.claim,
                "source": node.source,
                "confidence": node.confidence,
                "timestamp": fetched.isoformat(),
                "source_updated_at": updated.isoformat() if updated else None,
                "provider": "shopify",
            })

        return evidence, changes
