"""
Per-user swag budget tracker.

Each FSE gets a company-card swag budget (default $250) and each employee a
smaller one (default $100), spanning a 2-month period that resets on a fixed
bimonthly calendar (Jan-Feb, Mar-Apr, May-Jun, Jul-Aug, Sep-Oct, Nov-Dec).
Managers have NO budget (unlimited). Spend accrues only on COMPANY-card swag
orders that actually place (auto-placed or approved); personal-card orders and
manager orders never count.

Storage: a JSON file keyed by email -> period -> dollars spent.
  ⚠️ Render's free tier has an EPHEMERAL filesystem, so this resets on redeploy
  / spin-down. For durable budgets, point BUDGET_STORE at a persistent disk or
  swap _load/_save for the SharePoint list (graph.log_to_sharepoint) or a DB.
  The rest of the app only touches spent()/add_spend()/status(), so the backing
  store can change without touching callers.
"""
import os, json, datetime
import config

_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
           "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

STORE = config.BUDGET_STORE   # resolves from DATA_DIR / BUDGET_STORE env (see config.py)


def budget_for(role):
    """Dollar budget for a role, or None for unlimited (manager)."""
    if role == config.ROLE_FSE:
        return config.FSE_BUDGET_USD
    if role == config.ROLE_EMPLOYEE:
        return config.EMPLOYEE_BUDGET_USD
    return None                                   # manager / unknown -> unlimited


def _now():
    return datetime.datetime.now()


def period_key(dt=None):
    dt = dt or _now()
    return "%04d-P%d" % (dt.year, (dt.month - 1) // 2)   # 0..5


def reset_date(dt=None):
    """First day of the NEXT bimonthly period (when the budget resets)."""
    dt = dt or _now()
    start_month = ((dt.month - 1) // 2) * 2 + 1          # 1,3,5,7,9,11
    nm = start_month + 2
    year = dt.year + (1 if nm > 12 else 0)
    nm = nm - 12 if nm > 12 else nm
    return datetime.date(year, nm, 1)


def reset_human(dt=None):
    d = reset_date(dt)
    return "%s %d, %d" % (_MONTHS[d.month - 1], d.day, d.year)


def _load():
    try:
        with open(STORE) as f:
            return json.load(f)
    except Exception:
        return {}


def _save(d):
    os.makedirs(os.path.dirname(STORE), exist_ok=True)
    tmp = STORE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(d, f, indent=2)
    os.replace(tmp, STORE)


def spent(email, dt=None):
    if not email:
        return 0.0
    rec = _load().get(email.strip().lower(), {})
    return float(rec.get(period_key(dt), 0.0))


def add_spend(email, amount, dt=None):
    """Accrue spend for this user in the current period. Returns new total."""
    if not email or not amount:
        return spent(email, dt)
    e = email.strip().lower()
    pk = period_key(dt)
    d = _load()
    d.setdefault(e, {})
    d[e][pk] = round(float(d[e].get(pk, 0.0)) + float(amount), 2)
    _save(d)
    return d[e][pk]


def status(user):
    """Budget snapshot for the storefront banner."""
    if not user:
        return None
    role = user.get("role")
    cap = budget_for(role)
    email = user.get("email", "")
    s = round(spent(email), 2)
    if cap is None:
        return {"role": role, "unlimited": True, "spent": s,
                "reset_h": reset_human(), "reset": reset_date().isoformat()}
    remaining = round(cap - s, 2)
    pct = 0 if cap <= 0 else max(0, min(100, int(round(s / cap * 100))))
    return {"role": role, "unlimited": False, "budget": cap, "spent": s,
            "remaining": remaining, "over": remaining < 0, "pct": pct,
            "reset_h": reset_human(), "reset": reset_date().isoformat()}
