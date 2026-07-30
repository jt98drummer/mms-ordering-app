"""
What's popular in the swag store — drives the "Crew Favorites" carousel.

Ranking rule (as requested): order by how many times an item has actually been
ORDERED. While order volume is still low, fall back to how many times its
product page has been opened, so the section is never empty or stale.

Storage mirrors budget.py: one JSON file under DATA_DIR, written atomically
under a cross-process lock, so several gunicorn workers can't clobber each
other. This is presentation data, not money — a lost increment is harmless, so
reads never block and failures are swallowed.
"""
import os, json

import config
from budget import _FileLock                      # same OS-level lock helper

STORE = os.environ.get("POPULARITY_STORE",
                       os.path.join(config.DATA_DIR, "popularity.json"))
# An order counts this much more than a page view when ranking.
ORDER_WEIGHT = float(os.environ.get("POPULARITY_ORDER_WEIGHT", "25"))


def _load():
    try:
        with open(STORE) as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _save(d):
    os.makedirs(os.path.dirname(STORE) or ".", exist_ok=True)
    tmp = STORE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(d, f, indent=2)
    os.replace(tmp, STORE)


def _bump(item_id, field, n=1):
    if not item_id:
        return
    try:
        with _FileLock():
            d = _load()
            rec = d.setdefault(str(item_id), {"orders": 0, "views": 0})
            rec[field] = int(rec.get(field, 0)) + n
            _save(d)
    except Exception:
        pass                                       # never break a page/order over stats


def view(item_id):
    """Someone opened this product's page."""
    _bump(item_id, "views")


def ordered(item_id, qty=1):
    """This item was actually ordered (counts units)."""
    _bump(item_id, "orders", max(1, int(qty or 1)))


def counts():
    return _load()


def score(rec):
    return int(rec.get("orders", 0)) * ORDER_WEIGHT + int(rec.get("views", 0))


def top_ids(limit=6):
    """Item ids ranked most→least popular. Orders dominate; views break ties and
    carry the ranking while order volume is low. Returns [] when nothing is
    tracked yet, so callers can fall back to their own default picks."""
    d = _load()
    ranked = sorted(d.items(), key=lambda kv: (-score(kv[1]), kv[0]))
    return [k for k, v in ranked if score(v) > 0][:limit]


def rank(items, limit=5, fallback_ids=()):
    """Pick the most popular published items, topping up with sensible defaults.

    items: the published catalog list. Returns a list of catalog dicts.
    """
    by_id = {i["id"]: i for i in items}
    out, seen = [], set()
    for iid in top_ids(limit * 2):
        it = by_id.get(iid)
        if it and iid not in seen:
            out.append(it); seen.add(iid)
        if len(out) >= limit:
            return out
    for iid in list(fallback_ids) + [i["id"] for i in items]:
        it = by_id.get(iid)
        if it and iid not in seen:
            out.append(it); seen.add(iid)
        if len(out) >= limit:
            break
    return out
