from .base import Domain, Entity, StateTransition, Invariant, ToolResult, now_iso
from datetime import datetime, timedelta, timezone


class TravelDomain(Domain):
    name = "travel"
    schema_version = "1.0"

    def __init__(self):
        super().__init__()
        self.reset()

    def reset(self):
        self.entities = {
            "SEAT-12A": Entity("SEAT-12A", "available", data={"flight_id": "FL-100", "seat_id": "SEAT-12A", "price": 5000}),
            "SEAT-13B": Entity("SEAT-13B", "held", data={"flight_id": "FL-100", "seat_id": "SEAT-13B", "price": 5000}),
            "SEAT-14C": Entity("SEAT-14C", "confirmed", data={"flight_id": "FL-101", "seat_id": "SEAT-14C", "price": 6500}),
            "SEAT-15D": Entity("SEAT-15D", "available", data={"flight_id": "FL-101", "seat_id": "SEAT-15D", "price": 6500}),
            "SEAT-16F": Entity("SEAT-16F", "cancelled", data={"flight_id": "FL-102", "seat_id": "SEAT-16F", "price": 4500}),
            "BKG-100": Entity("BKG-100", "held", data={"seat_id": "SEAT-13B", "hold_expires_at": (datetime.now(timezone.utc)+timedelta(minutes=10)).isoformat()}),
            "BKG-101": Entity("BKG-101", "confirmed", data={"seat_id": "SEAT-14C", "hold_expires_at": (datetime.now(timezone.utc)+timedelta(minutes=10)).isoformat()}),
        }
        self.transitions = [
            StateTransition("available", "held", "hold", ["seat state == available"], ["seat state == held"], 300),
            StateTransition("held", "confirmed", "confirm", ["hold not expired", "seat state == held"], ["booking state == confirmed"], 300),
            StateTransition("confirmed", "checked_in", "check_in", ["booking state == confirmed"], ["booking state == checked_in"], 300),
            StateTransition("checked_in", "boarded", "board", ["booking state == checked_in"], ["booking state == boarded"], 300),
            StateTransition("held", "cancelled", "cancel", ["booking state == held"], ["booking state == cancelled"], 300),
            StateTransition("confirmed", "cancelled", "cancel", ["booking state == confirmed"], ["booking state == cancelled"], 300),
        ]
        self.invariants = [
            Invariant("hold_not_expired", lambda c: (c.get("hold_valid", True), "Booking hold has expired."), "domain_fact"),
            Invariant("seat_available", lambda c: (c.get("seat_available", True), "Seat is already booked or held."), "domain_fact"),
            Invariant("departure_not_passed", lambda c: (not c.get("departure_passed", False), "Booking cannot be created after departure."), "workflow_rule"),
            Invariant("price_budget_exceeded", lambda c: (
                c.get("budget_limit") is None or c.get("price", 0) <= c.get("budget_limit"),
                "Requested fare exceeds the user-provided budget."
            ), "user_constraint"),
        ]

    def simulate_tool_call(self, action, payload):
        ts = now_iso()
        sid = payload.get("seat_id", "SEAT-12A")
        bid = payload.get("booking_id", "BKG-100")
        seat = self.entities.get(sid)
        booking = self.entities.get(bid)
        if action == "get_availability":
            if not seat:
                return ToolResult(False, action, sid, {"error": "seat_not_found"}, timestamp=ts)
            return ToolResult(True, action, sid, {
                "flight_id": seat.data.get("flight_id"), "seat_id": sid,
                "status": seat.state, "price": seat.data.get("price", 0),
                "as_of_timestamp": seat.updated_at}, timestamp=ts)
        if action == "hold":
            if not seat:
                return ToolResult(False, action, sid, {"error": "seat_not_found"}, timestamp=ts)
            if seat.state != "available":
                return ToolResult(False, action, sid, {"error": "seat_unavailable", "status": seat.state}, timestamp=ts)
            seat.state = "held"; seat.updated_at = ts
            booking_id = payload.get("booking_id", "BKG-100")
            if booking_id in self.entities:
                self.entities[booking_id].state = "held"
                self.entities[booking_id].data["seat_id"] = sid
                self.entities[booking_id].data["hold_expires_at"] = (datetime.now(timezone.utc)+timedelta(minutes=10)).isoformat()
            return ToolResult(True, action, sid, {"seat_id": sid, "status": "held", "price": seat.data.get("price", 0), "as_of_timestamp": ts}, timestamp=ts)
        if action == "confirm":
            if not booking:
                return ToolResult(False, action, bid, {"error": "booking_not_found"}, timestamp=ts)
            exp = datetime.fromisoformat(booking.data["hold_expires_at"])
            if exp.tzinfo is None: exp = exp.replace(tzinfo=timezone.utc)
            if datetime.now(timezone.utc) > exp:
                return ToolResult(False, action, bid, {"error": "hold_expired", "hold_expires_at": booking.data["hold_expires_at"]}, timestamp=ts)
            sid = booking.data.get("seat_id"); seat = self.entities.get(sid)
            if not seat or seat.state != "held":
                return ToolResult(False, action, bid, {"error": "seat_not_held", "status": seat.state if seat else None}, timestamp=ts)
            seat.state = "confirmed"; booking.state = "confirmed"; booking.updated_at = seat.updated_at = ts
            return ToolResult(True, action, bid, {"booking_id": bid, "seat_id": sid, "status": "confirmed",
                                                  "price": seat.data.get("price", 0), "hold_expires_at": booking.data["hold_expires_at"],
                                                  "as_of_timestamp": ts}, timestamp=ts)
        if action in {"check_in", "board", "cancel"}:
            if not booking:
                return ToolResult(False, action, bid, {"error": "booking_not_found"}, timestamp=ts)
            target = {"check_in": "checked_in", "board": "boarded", "cancel": "cancelled"}[action]
            if not self.allowed_transition(booking.state, target, action):
                return ToolResult(False, action, bid, {"error": "illegal_state", "state": booking.state}, timestamp=ts)
            booking.state = target; booking.updated_at = ts
            return ToolResult(True, action, bid, {"booking_id": bid, "status": target, "as_of_timestamp": ts}, timestamp=ts)
        return ToolResult(False, action, bid, {"error": "unknown_action"}, timestamp=ts)
