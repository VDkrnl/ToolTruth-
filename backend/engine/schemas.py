from pydantic import BaseModel
from typing import Optional

class InventoryFact(BaseModel):
    product_id: str
    quantity: int
    as_of_timestamp: str

class BookingFact(BaseModel):
    booking_id: str
    seat_id: str
    status: str
    hold_expires_at: Optional[str]=None

class IssueFact(BaseModel):
    issue_id: str
    state: str
    blocking: bool=False
    linked_pr: Optional[str]=None

class CheckResult(BaseModel):
    name: str
    passed: bool
    reason: str
    category: Optional[str] = None

class ConsistencyReport(BaseModel):
    passed: bool
    decision: str = "allow"
    checks: list[CheckResult]
    fault_type: Optional[str]=None
    blocked_reason: Optional[str]=None
