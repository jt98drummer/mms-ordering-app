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


# --- expected-cost helpers: derive from the CATALOG so the suite stays valid
# when real Printful costs change (prices are per-size; shipping is added
# because the budget is charged the true spend). ---
_CAT = {i["id"]: i for i in json.load(open(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "swag_catalog.json"), encoding="utf-8"))}

def expected(iid="ap3", qty=1, size=None):
    """Total the server will charge: per-size item cost x qty + estimated shipping."""
    p = _CAT[iid]
    by = p.get("price_by_size") or {}
    unit = float(by[size]) if (size and size in by) else float(p["price"])
    ship = float(p.get("ship_first") or 0) + max(0, qty - 1) * float(p.get("ship_addl") or 0)
    return round(unit * qty + ship, 2)

def unit_cost(iid="ap3", size=None):
    p = _CAT[iid]; by = p.get("price_by_size") or {}
    return float(by[size]) if (size and size in by) else float(p["price"])

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
check("tampered cheap price -> charged real catalog cost + shipping",
      budget.spent("mallory@mms.com"), expected("ap3", 5, "L"))
check("order placed", j.get("status"), "placed")

budget._save({})
j = order([line(price=-500.0, qty=1)])           # negative price to inflate budget
check("negative price ignored -> real cost charged",
      budget.spent("mallory@mms.com"), expected("ap3", 1, "L"))

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
e6 = expected("ap3", 6, "L")                     # fits inside $100
j = order([line(qty=6)])
check("in-budget order placed", j.get("status"), "placed")
check("spent == real cost + shipping", budget.spent("edge@mms.com"), e6)
j = order([line(qty=6)])                         # another 6 would exceed the rest
check("over remaining -> pending", j.get("status"), "pending")
check("pending did NOT accrue", budget.spent("edge@mms.com"), e6)

budget._save({})
as_user("exact@mms.com", "employee")
# leave EXACTLY the cost of one unit-order remaining, then order it
e1 = expected("ap3", 1, "L")
budget._save({"exact@mms.com": {budget.period_key(): round(100.0 - e1, 2)}})
j = order([line(qty=1)])                         # exact fit -> allowed
check("exact-to-the-penny fit allowed", j.get("status"), "placed")
check("spent exactly the $100 cap", budget.spent("exact@mms.com"), 100.0)
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
ts = [threading.Thread(target=fire) for _ in range(6)]
[t.start() for t in ts]; [t.join() for t in ts]
placed = results.count("placed"); pending = results.count("pending")
spent = budget.spent("race@mms.com")
each = expected("ap3", 5, "L")
fits = int(250.0 // each)                        # how many can legitimately fit
print("   placed=%d pending=%d spent=$%.2f (each $%.2f, max fits %d)" % (placed, pending, spent, each, fits))
check("exactly the number that fit were placed", placed, fits)
check("spend never exceeds cap", spent <= 250.0, True)
check("spend == placed x cost", spent, round(placed * each, 2))

print("\n=== 5. PER-PERSON ISOLATION + APPROVAL ATTRIBUTION ===")
budget._save({})
as_user("ann@mms.com", "fse");   order([line(qty=5)])
as_user("ben@mms.com", "employee"); order([line(qty=2)])
as_user("cam@mms.com", "manager");  order([line(qty=50)])      # unlimited
ann_exp = expected("ap3", 5, "L"); ben_exp = expected("ap3", 2, "L")
check("ann charged her own order", budget.spent("ann@mms.com"), ann_exp)
check("ben charged his own order", budget.spent("ben@mms.com"), ben_exp)
check("manager never accrues", budget.spent("cam@mms.com"), 0.0)
as_user("ben@mms.com", "employee")
j = order([line(qty=10)])                                      # exceeds his remaining -> pending
oid = j["order_id"]
big = expected("ap3", 10, "L")
c.get("/approve/%s/%s" % (oid, app._sig(oid)))
check("approval accrues to BEN", budget.spent("ben@mms.com"), round(ben_exp + big, 2))
check("ann untouched by ben's approval", budget.spent("ann@mms.com"), ann_exp)
# double-approval must not double-charge
c.get("/approve/%s/%s" % (oid, app._sig(oid)))
check("re-approving does NOT double-charge", budget.spent("ben@mms.com"), round(ben_exp + big, 2))

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
