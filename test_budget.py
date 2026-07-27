"""Budget accuracy test suite - run before touching anything money-related.

    DATA_DIR=/tmp/budtest MAIL_MODE=off python test_budget.py

Covers: client price tampering, invalid/unpublished items, exact budget
boundaries, CONCURRENT orders (no overspend), per-person isolation, approval
attribution + double-approval, personal card, refund on fulfillment failure,
and period rollover. Exits non-zero on any failure.
"""
import json, threading, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import app, budget, config

c = app.app.test_client()
FAILS = []

def check(label, got, want):
    ok = (got == want)
    print(("  PASS " if ok else "  FAIL ") + label + "  got=%r want=%r" % (got, want))
    if not ok:
        FAILS.append(label)

def as_user(email, role):
    with c.session_transaction() as s:
        s["user"] = {"name": email.split("@")[0], "email": email, "initials": "X",
                     "role": role, "manager_email": "mgr@mms.com"}
        s.pop("role_override", None)

SHIP = {"addressLine1": "1 Main", "city": "DSM", "state": "IA", "postCode": "50266",
        "country": "US", "firstName": "A", "lastName": "B", "email": "x@y.com", "phone": "5"}
CTX = {"purpose": "Customer visit", "recipient": "x", "justification": "y"}

def order(items, payment="company"):
    return c.post("/api/checkout/swag", json={"items": items, "context": CTX,
                                              "payment": payment, "ship": SHIP}).get_json()

def line(id="ap3", price=16.0, qty=1, color="Navy", size="L", logo="white"):
    return {"type": "swag", "id": id, "name": "Tee", "price": price, "qty": qty,
            "color": color, "size": size, "logo": logo}

print("\n=== 1. PRICE TAMPERING (client price must be ignored) ===")
budget._save({})
as_user("mallory@mms.com", "employee")           # $100 budget; tee really costs $16
j = order([line(price=0.01, qty=5)])             # claims 5 tees cost $0.05
check("tampered cheap price -> charged catalog price 5x$16=$80",
      budget.spent("mallory@mms.com"), 80.0)
check("order placed", j.get("status"), "placed")

budget._save({})
j = order([line(price=-500.0, qty=1)])           # negative price to inflate budget
check("negative price ignored -> $16 charged", budget.spent("mallory@mms.com"), 16.0)

print("\n=== 2. INVALID ITEMS REJECTED ===")
budget._save({})
check("unknown id rejected", order([line(id="nope")]).get("ok"), False)
check("unpublished item (sw2 mug) rejected", order([line(id="sw2", color="White", size="")]).get("ok"), False)
check("invalid colour rejected", order([line(color="Chartreuse")]).get("ok"), False)
check("invalid size rejected", order([line(size="XXS")]).get("ok"), False)
check("qty 0 rejected", order([line(qty=0)]).get("ok"), False)
check("qty 99999 rejected", order([line(qty=99999)]).get("ok"), False)
check("nothing charged by rejects", budget.spent("mallory@mms.com"), 0.0)

print("\n=== 3. BUDGET GATE EXACTNESS ===")
budget._save({})
as_user("edge@mms.com", "employee")              # $100
j = order([line(qty=6)])                         # 6 x 16 = 96 -> fits
check("$96 placed", j.get("status"), "placed")
check("spent 96", budget.spent("edge@mms.com"), 96.0)
j = order([line(qty=1)])                         # 16 > 4 remaining -> approval
check("$16 over $4 remaining -> pending", j.get("status"), "pending")
check("pending did NOT accrue", budget.spent("edge@mms.com"), 96.0)

budget._save({})
as_user("exact@mms.com", "employee")
j = order([line(price=16.0, qty=6)])             # 96
j = order([line(qty=1, id="ap3")])               # would be 112 -> pending
budget._save({"exact@mms.com": {budget.period_key(): 84.0}})
j = order([line(qty=1)])                         # exactly 16 left, 16 charged -> allowed
check("exact-to-the-penny fit allowed", j.get("status"), "placed")
check("spent exactly 100", budget.spent("exact@mms.com"), 100.0)
j = order([line(qty=1)])
check("$0 remaining -> next order pending", j.get("status"), "pending")

print("\n=== 4. CONCURRENCY (no overspend under parallel orders) ===")
budget._save({})
as_user("race@mms.com", "fse")                   # $250 budget
results = []
def fire():
    cl = app.app.test_client()
    with cl.session_transaction() as s:
        s["user"] = {"name": "race", "email": "race@mms.com", "initials": "R",
                     "role": "fse", "manager_email": "mgr@mms.com"}
    r = cl.post("/api/checkout/swag", json={"items": [line(qty=5)],  # $80 each order
                                            "context": CTX, "payment": "company", "ship": SHIP})
    results.append(r.get_json().get("status"))
ts = [threading.Thread(target=fire) for _ in range(6)]   # 6 x $80 = $480 vs $250 cap
[t.start() for t in ts]; [t.join() for t in ts]
placed = results.count("placed"); pending = results.count("pending")
spent = budget.spent("race@mms.com")
print("   placed=%d pending=%d spent=$%.2f" % (placed, pending, spent))
check("3 placed (3x$80=$240 <= $250)", placed, 3)
check("spend never exceeds cap", spent <= 250.0, True)
check("spend exactly 240", spent, 240.0)

print("\n=== 5. PER-PERSON ISOLATION + APPROVAL ATTRIBUTION ===")
budget._save({})
as_user("ann@mms.com", "fse");   order([line(qty=5)])          # $80
as_user("ben@mms.com", "employee"); order([line(qty=2)])       # $32
as_user("cam@mms.com", "manager");  order([line(qty=50)])      # unlimited
check("ann 80", budget.spent("ann@mms.com"), 80.0)
check("ben 32", budget.spent("ben@mms.com"), 32.0)
check("manager never accrues", budget.spent("cam@mms.com"), 0.0)
as_user("ben@mms.com", "employee")
j = order([line(qty=10)])                                       # $160 > $68 left -> pending
oid = j["order_id"]
c.get("/approve/%s/%s" % (oid, app._sig(oid)))
check("approval accrues to BEN (32+160)", budget.spent("ben@mms.com"), 192.0)
check("ann untouched by ben's approval", budget.spent("ann@mms.com"), 80.0)
# double-approval must not double-charge
c.get("/approve/%s/%s" % (oid, app._sig(oid)))
check("re-approving does NOT double-charge", budget.spent("ben@mms.com"), 192.0)

print("\n=== 6. PERSONAL CARD NEVER TOUCHES BUDGET ===")
budget._save({})
as_user("pers@mms.com", "employee")
c.post("/api/checkout/swag", json={"items": [line(qty=5)], "context": CTX,
                                   "payment": "personal", "ack_not_reimbursable": True, "ship": SHIP})
check("personal card accrues nothing", budget.spent("pers@mms.com"), 0.0)

print("\n=== 7. REFUND ON FULFILLMENT FAILURE ===")
budget._save({})
as_user("fail@mms.com", "employee")
orig = app._fulfill_swag
app._fulfill_swag = lambda o: (_ for _ in ()).throw(RuntimeError("printer down"))
j = order([line(qty=3)])                                        # $48
app._fulfill_swag = orig
check("failed order returns error", j.get("ok"), False)
check("budget released on failure", budget.spent("fail@mms.com"), 0.0)

print("\n=== 8. PERIOD ROLLOVER ===")
import datetime
budget._save({})
budget.add_spend("roll@mms.com", 90.0)
this_p = budget.period_key()
next_p = budget.period_key(datetime.datetime(2026, 9, 15))
check("periods differ (Jul-Aug vs Sep-Oct)", this_p != next_p, True)
check("spend is period-scoped (next period starts at 0)",
      budget.spent("roll@mms.com", datetime.datetime(2026, 9, 15)), 0.0)
check("current period retains 90", budget.spent("roll@mms.com"), 90.0)

print("\n" + ("ALL CHECKS PASSED" if not FAILS else "FAILURES: %r" % FAILS))
sys.exit(1 if FAILS else 0)
