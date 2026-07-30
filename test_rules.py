"""Approval-rule matrix — run after ANY change to roles, approvals or checkout.

    DATA_DIR=/tmp/rt MAIL_MODE=off GELATO_MODE=dry PRINTFUL_MODE=dry python test_rules.py

Locks in the agreed safety structure:

  employee : EVERY company-card line needs manager approval (cards, docs, swag)
  fse      : cards/docs place immediately; swag places within the $250
             bimonthly budget, over budget goes for approval
  manager  : everything places immediately, no budget

  personal card applies to SWAG ONLY (cards/documents are always company card)
  business cards: 100 per order for employees, 500 for FSEs and managers
  documents: DOC_MAX_QTY (25) per document
"""
import os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("MAIL_MODE", "off")
os.environ.setdefault("GELATO_MODE", "dry")
os.environ.setdefault("PRINTFUL_MODE", "dry")

import app, budget, config                                        # noqa: E402

c = app.app.test_client()
FAILS = []

SHIP = {"firstName": "J", "lastName": "T", "addressLine1": "1501 42nd St",
        "city": "West Des Moines", "state": "IA", "postCode": "50266",
        "country": "US", "email": "j@x.com", "phone": "5155551234"}
CTX = {"purpose": "Customer visit", "recipient": "ACME", "justification": "why"}
CARD = {"type": "card", "name": "Jane Doe", "title": "AE", "email": "j@x", "phone": "5", "qty": 100}
DOC = {"type": "doc", "id": "doc1", "qty": 25}
TEE = {"type": "swag", "id": "ap3", "color": "Navy", "size": "L", "qty": 1, "logo": "white"}


def check(label, got, want):
    ok = got == want
    print(("  PASS " if ok else "  FAIL ") + label + ("" if ok else "  got=%r want=%r" % (got, want)))
    if not ok:
        FAILS.append(label)


def as_user(email, role):
    with c.session_transaction() as s:
        s["user"] = {"name": email.split("@")[0], "email": email, "initials": "X",
                     "role": role, "manager_email": "mgr@mms.com"}
        s.pop("role_override", None)


def co(items, payment="company", ack=False):
    return c.post("/api/checkout", json={"items": items, "context": CTX, "payment": payment,
                                         "ack_not_reimbursable": ack, "ship": SHIP}).get_json()


def statuses(j):
    """{store-kind: status} for a checkout response; 'ERR' when rejected."""
    if not j.get("ok"):
        return "ERR"
    out = {}
    for o in j.get("orders", []):
        out["swag" if o["store"] == "Swag & Apparel" else "print"] = o["status"]
    return out


print("\n=== EMPLOYEE: approval for everything on the company card ===")
budget._save({}); as_user("emp@mms.com", "employee")
check("mixed cart -> both halves pending", statuses(co([CARD, DOC, TEE])),
      {"print": "pending", "swag": "pending"})
check("cards only -> pending", statuses(co([CARD])), {"print": "pending"})
check("documents only -> pending", statuses(co([DOC])), {"print": "pending"})
check("swag only -> pending", statuses(co([TEE])), {"swag": "pending"})
check("employee never accrues budget", budget.spent("emp@mms.com"), 0.0)

print("\n=== FSE: print immediate, swag budget-gated ===")
budget._save({}); as_user("fse@mms.com", "fse")
check("mixed, swag in budget -> both placed", statuses(co([CARD, DOC, TEE])),
      {"print": "placed", "swag": "placed"})
spent_after = budget.spent("fse@mms.com")
check("swag accrued to the FSE", spent_after > 0, True)
budget._save({"fse@mms.com": {budget.period_key(): 249.0}})     # nearly spent
check("over budget -> print STILL places, only swag waits",
      statuses(co([CARD, TEE])), {"print": "placed", "swag": "pending"})
check("pending swag did not accrue", budget.spent("fse@mms.com"), 249.0)

print("\n=== MANAGER: everything immediate, no budget ===")
budget._save({}); as_user("mgr@mms.com", "manager")
check("mixed cart -> both placed", statuses(co([CARD, DOC, dict(TEE, qty=30)])),
      {"print": "placed", "swag": "placed"})
check("manager never accrues", budget.spent("mgr@mms.com"), 0.0)
check("manager has no budget bar", budget.status({"role": "manager", "email": "mgr@mms.com"}), None)
check("employee has no budget bar", budget.status({"role": "employee", "email": "e@x"}), None)
check("FSE HAS a budget bar", (budget.status({"role": "fse", "email": "f@x"}) or {}).get("budget"),
      config.FSE_BUDGET_USD)

print("\n=== PERSONAL CARD: swag only, and it bypasses approval ===")
budget._save({}); as_user("emp2@mms.com", "employee")
check("personal without acknowledgement is rejected",
      co([TEE], payment="personal").get("ok"), False)
s = statuses(co([CARD, TEE], payment="personal", ack=True))
check("swag placed on personal card", s.get("swag"), "placed")
check("cards STILL need approval (always company card)", s.get("print"), "pending")
check("personal card never touches the budget", budget.spent("emp2@mms.com"), 0.0)

print("\n=== QUANTITY LIMITS ===")
as_user("emp3@mms.com", "employee")
check("employee 100 cards ok", statuses(co([dict(CARD, qty=100)])), {"print": "pending"})
check("employee 101 cards rejected", statuses(co([dict(CARD, qty=101)])), "ERR")
as_user("fse2@mms.com", "fse")
check("fse 500 cards ok", statuses(co([dict(CARD, qty=500)])), {"print": "placed"})
check("fse 501 cards rejected", statuses(co([dict(CARD, qty=501)])), "ERR")
as_user("mgr2@mms.com", "manager")
check("manager 500 cards ok", statuses(co([dict(CARD, qty=500)])), {"print": "placed"})
check("manager 501 cards rejected", statuses(co([dict(CARD, qty=501)])), "ERR")
check("document over DOC_MAX_QTY rejected",
      statuses(co([dict(DOC, qty=config.DOC_MAX_QTY + 1)])), "ERR")
check("empty cart rejected", statuses(co([])), "ERR")

print("\n=== APPROVAL PLACES BOTH HALVES ===")
budget._save({}); as_user("emp4@mms.com", "employee")
j = co([CARD, DOC, TEE])
for o in j["orders"]:
    oid = o["order_id"]
    r = c.get("/approve/%s/%s" % (oid, app._sig(oid)))
    check("approving %s succeeds" % o["store"][:14], r.status_code, 200)
check("approved employee swag accrues nothing (no budget)", budget.spent("emp4@mms.com"), 0.0)

print("\n" + ("ALL RULE CHECKS PASSED" if not FAILS else "FAILURES: %r" % FAILS))
sys.exit(1 if FAILS else 0)
