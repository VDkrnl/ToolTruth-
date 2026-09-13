from datetime import datetime, timedelta, timezone
from domains.ecommerce import EcommerceDomain
from domains.devops import DevOpsDomain
from domains.travel import TravelDomain


def test_ecommerce_reserve():
    d=EcommerceDomain(); r=d.simulate_tool_call("reserve",{"product_id":"SKU-100","quantity":2})
    assert r.success and r.data["quantity_remaining"]==8

def test_devops_blocks_blocking_issue():
    d=DevOpsDomain(); d.entities["ISS-100"].data["blocking"]=True
    r=d.simulate_tool_call("deploy",{"environment":"prod"})
    assert not r.success

def test_travel_hold():
    d=TravelDomain(); r=d.simulate_tool_call("hold",{"seat_id":"SEAT-12A"})
    assert r.success and d.entities["SEAT-12A"].state=="held"

def test_ecommerce_reset():
    d=EcommerceDomain(); d.entities["SKU-100"].data["quantity_available"]=0; d.entities["SKU-100"].state="sold"
    d.reset(); assert d.entities["SKU-100"].state=="in_stock" and d.entities["SKU-100"].data["quantity_available"]==10

def test_ecommerce_apply_setup_state():
    d=EcommerceDomain(); d.apply_setup_state({"SKU-100":{"state":"sold","quantity_available":0}})
    assert d.entities["SKU-100"].state=="sold" and d.entities["SKU-100"].data["quantity_available"]==0

def test_devops_staging_required_before_prod():
    d=DevOpsDomain(); d.apply_setup_state({"DEP-100":{"state":"staging"}}); r=d.simulate_tool_call("deploy",{"deployment_id":"DEP-100","environment":"prod","staging_complete":False})
    assert not r.success

def test_travel_hold_expired():
    d=TravelDomain(); d.apply_setup_state({"BKG-100":{"state":"held","hold_expires_at":(datetime.now(timezone.utc)-timedelta(minutes=1)).isoformat()}})
    assert not d.simulate_tool_call("confirm",{"booking_id":"BKG-100"}).success
