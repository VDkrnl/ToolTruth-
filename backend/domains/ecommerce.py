from .base import Domain, Entity, StateTransition, Invariant, ToolResult, now_iso


class EcommerceDomain(Domain):
    name = "ecommerce"
    schema_version = "1.0"

    def __init__(self):
        super().__init__()
        self.reset()

    def reset(self):
        self.entities = {
            "SKU-100": Entity("SKU-100", "in_stock", data={"quantity_available": 10, "price": 999}),
            "SKU-101": Entity("SKU-101", "in_stock", data={"quantity_available": 5, "price": 799}),
            "SKU-102": Entity("SKU-102", "reserved", data={"quantity_available": 3, "price": 599}),
            "SKU-103": Entity("SKU-103", "sold", data={"quantity_available": 0, "price": 1299}),
            "SKU-104": Entity("SKU-104", "returned", data={"quantity_available": 0, "price": 499}),
            "ORD-100": Entity("ORD-100", "created", data={"product_id": "SKU-100", "quantity": 1}),
        }
        self.transitions = [
            StateTransition("in_stock", "reserved", "reserve",
                            ["quantity_available > 0", "state == in_stock"],
                            ["state == reserved", "quantity_available decreased by qty"], 300),
            StateTransition("reserved", "sold", "sell",
                            ["state == reserved"], ["state == sold"], 300),
            StateTransition("sold", "returned", "return",
                            ["state == sold"], ["state == returned"], 300),
        ]
        self.invariants = [
            Invariant("stock_non_negative",
                      lambda c: (c.get("quantity_available", 0) >= 0, "Inventory cannot be negative."),
                      "domain_fact"),
            Invariant("price_non_negative",
                      lambda c: (c.get("price", 0) >= 0, "Price cannot be negative."),
                      "domain_fact"),
            Invariant("quantity_positive_for_reserve",
                      lambda c: (c.get("quantity", 1) > 0, "Reservation quantity must be greater than zero."),
                      "workflow_rule"),
            Invariant("budget_not_exceeded",
                      lambda c: (
                          c.get("budget_limit") is None or
                          c.get("price", 0) * c.get("quantity", 1) <= c.get("budget_limit"),
                          "Requested purchase exceeds the user-provided budget."
                      ),
                      "user_constraint"),
        ]

    def simulate_tool_call(self, action, payload):
        ts = now_iso()
        pid = payload.get("product_id", "SKU-100")
        e = self.entities.get(pid)
        if action == "get_inventory":
            if not e:
                return ToolResult(False, action, pid, {"error": "product_not_found"}, timestamp=ts)
            return ToolResult(True, action, pid, {
                "product_id": pid, "quantity": e.data.get("quantity_available", 0),
                "quantity_available": e.data.get("quantity_available", 0),
                "price": e.data.get("price", 0), "state": e.state,
                "as_of_timestamp": e.updated_at}, timestamp=ts)
        if action == "reserve":
            if not e:
                return ToolResult(False, action, pid, {"error": "product_not_found"}, timestamp=ts)
            try:
                qty = int(payload.get("quantity", 1))
            except (TypeError, ValueError):
                return ToolResult(False, action, pid, {"error": "invalid_quantity"}, timestamp=ts)
            if qty <= 0:
                return ToolResult(False, action, pid, {"error": "invalid_quantity"}, timestamp=ts)
            if e.state != "in_stock":
                return ToolResult(False, action, pid, {"error": "not_in_stock", "state": e.state}, timestamp=ts)
            if e.data.get("quantity_available", 0) < qty:
                return ToolResult(False, action, pid, {"error": "insufficient_stock",
                                                       "available": e.data.get("quantity_available", 0)}, timestamp=ts)
            e.data["quantity_available"] -= qty
            e.state = "reserved"
            e.updated_at = ts
            return ToolResult(True, action, pid, {
                "product_id": pid, "reserved": qty,
                "quantity_remaining": e.data["quantity_available"],
                "quantity_available": e.data["quantity_available"],
                "price": e.data.get("price", 0), "state": e.state,
                "as_of_timestamp": ts}, timestamp=ts)
        if action == "sell":
            if not e or e.state != "reserved":
                return ToolResult(False, action, pid, {"error": "illegal_state", "state": e.state if e else None}, timestamp=ts)
            e.state = "sold"; e.updated_at = ts
            return ToolResult(True, action, pid, {"product_id": pid, "state": "sold", "as_of_timestamp": ts}, timestamp=ts)
        if action == "return":
            if not e or e.state != "sold":
                return ToolResult(False, action, pid, {"error": "illegal_state", "state": e.state if e else None}, timestamp=ts)
            e.state = "returned"; e.updated_at = ts
            return ToolResult(True, action, pid, {"product_id": pid, "state": "returned", "as_of_timestamp": ts}, timestamp=ts)
        return ToolResult(False, action, pid, {"error": "unknown_action"}, timestamp=ts)
