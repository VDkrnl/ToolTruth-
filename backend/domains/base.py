from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class Entity:
    id: str
    state: str
    updated_at: str = field(default_factory=now_iso)
    provenance: dict[str, Any] = field(default_factory=dict)
    data: dict[str, Any] = field(default_factory=dict)


@dataclass
class StateTransition:
    from_state: str
    to_state: str
    action: str
    preconditions: list[str] = field(default_factory=list)
    postconditions: list[str] = field(default_factory=list)
    freshness_ttl_seconds: int = 300


@dataclass
class Invariant:
    name: str
    check: Callable[[dict[str, Any]], tuple[bool, str]]
    fact_type: str = "domain_fact"


@dataclass
class ToolResult:
    success: bool
    action: str
    entity_id: str | None
    data: dict[str, Any]
    source: str = "simulator"
    timestamp: str = field(default_factory=now_iso)


class Domain:
    name = "base"
    schema_version = "1.0"

    def __init__(self):
        self.entities: dict[str, Entity] = {}
        self.transitions: list[StateTransition] = []
        self.invariants: list[Invariant] = []

    def snapshot(self) -> dict[str, Any]:
        return {
            k: {"id": v.id, "state": v.state, "updated_at": v.updated_at,
                "provenance": dict(v.provenance), "data": dict(v.data)}
            for k, v in self.entities.items()
        }

    def restore(self, snapshot: dict[str, Any]) -> None:
        for entity_id, values in snapshot.items():
            entity = self.entities.get(entity_id)
            if entity is None:
                entity = Entity(entity_id, values.get("state", "available"))
                self.entities[entity_id] = entity
            entity.state = values["state"]
            entity.updated_at = values["updated_at"]
            entity.provenance = dict(values.get("provenance", {}))
            entity.data = dict(values.get("data", {}))

    def allowed_transition(self, from_state: str, to_state: str, action: str) -> bool:
        return any(t.from_state == from_state and t.to_state == to_state and t.action == action
                   for t in self.transitions)

    def target_state_for_action(self, action: str):
        targets = {t.action: t.to_state for t in self.transitions}
        return targets.get(action)

    def transition_for(self, action: str, from_state: str | None = None) -> StateTransition | None:
        matches = [t for t in self.transitions if t.action == action]
        if from_state is not None:
            matches = [t for t in matches if t.from_state == from_state]
        return matches[0] if matches else None

    def check_invariants(self, context: dict[str, Any]) -> list[tuple[str, bool, str]]:
        return [(inv.name, *inv.check(context)) for inv in self.invariants]

    def reset(self):
        raise NotImplementedError

    def apply_setup_state(self, state: dict[str, Any]):
        for entity_id, values in (state or {}).items():
            entity = self.entities.get(entity_id)
            if entity is None:
                entity = Entity(entity_id, values.get("state", "available"))
                self.entities[entity_id] = entity
            if "state" in values:
                entity.state = values["state"]
            entity.data.update({k: v for k, v in values.items() if k not in {"state", "updated_at"}})
            entity.updated_at = values.get("updated_at", entity.updated_at)

    def simulate_tool_call(self, action: str, payload: dict[str, Any]) -> ToolResult:
        raise NotImplementedError
