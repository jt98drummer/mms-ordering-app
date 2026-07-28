"""
Minimal Printful API client (Orders API v1) for ALL apparel (print + embroidery).
Key from env (PRINTFUL_API_KEY). Mode dry|draft|live mirrors gelato.py:
  dry   -> build payload, no API call
  draft -> create order with confirm=false (not fulfilled/charged)
  live  -> confirm=true (submitted for fulfillment)
"""
import json, urllib.request, urllib.error
import config

API = "https://api.printful.com"

def _headers():
    h = {"Content-Type": "application/json", "User-Agent": "MMS-Ordering-App/1.0"}
    if config.PRINTFUL_API_KEY:
        h["Authorization"] = "Bearer " + config.PRINTFUL_API_KEY
    if config.PRINTFUL_STORE_ID:
        h["X-PF-Store-Id"] = str(config.PRINTFUL_STORE_ID)
    return h

def _req(method, path, payload=None):
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(API + path, data=data, headers=_headers(), method=method)
    try:
        with urllib.request.urlopen(req, timeout=40) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, {"error": e.read().decode("utf-8", "ignore")}
    except Exception as e:
        return 0, {"error": str(e)}

_store_cache = {"id": None}

def stores():
    """List stores on the account (needs stores_list/read)."""
    return _req("GET", "/stores")

def store_id():
    """Resolve the store id: env override, else first store on the account (cached)."""
    if config.PRINTFUL_STORE_ID:
        return str(config.PRINTFUL_STORE_ID)
    if _store_cache["id"]:
        return _store_cache["id"]
    _st, data = stores()
    lst = (data or {}).get("result") or []
    if lst:
        _store_cache["id"] = str(lst[0].get("id"))
    return _store_cache["id"]

def create_order(items, recipient):
    """items: [{variant_id, quantity, files:[{url}]}]. Honors config.PRINTFUL_MODE."""
    mode = config.PRINTFUL_MODE
    if mode == "dry" or not config.PRINTFUL_API_KEY:
        return 0, {"mode": "dry", "note": "No Printful call made.", "items": items}
    payload = {"recipient": recipient, "items": items, "confirm": (mode == "live")}
    hdrs = _headers()
    sid = store_id()
    if sid:
        hdrs["X-PF-Store-Id"] = sid
    import urllib.request, urllib.error
    try:
        req = urllib.request.Request(API + "/orders", data=json.dumps(payload).encode("utf-8"),
                                     headers=hdrs, method="POST")
        with urllib.request.urlopen(req, timeout=40) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, {"error": e.read().decode("utf-8", "ignore")}
    except Exception as e:
        return 0, {"error": str(e)}

def store_products(limit=100):
    """Products already set up in your Printful store (with variant ids + files)."""
    return _req("GET", "/store/products?limit=%d" % limit)

def product(pid):
    """Catalog product + its variant ids (GET /products/{id})."""
    return _req("GET", "/products/%s" % pid)

def catalog_products(limit=100, offset=0):
    """Printful blank catalog (garments you can choose)."""
    return _req("GET", "/products?limit=%d&offset=%d" % (limit, offset))


def logo_url_for(color):
    """Default logo print-file URL for a garment colour (delegates to branding)."""
    import branding
    return branding.logo_url(branding.default_logo(color))

def thread_colors_for(color):
    """Default embroidery thread palette for a garment colour (delegates to branding)."""
    import branding
    return branding.threads(branding.default_logo(color))


_variant_cache = {}
COLOR_ALIASES = {
    "gray": ["athletic heather", "dark grey heather", "sport grey", "graphite heather", "grey"],
    "grey": ["athletic heather", "dark grey heather", "sport grey"],
    "navy": ["navy", "true navy", "heather navy", "heather midnight navy"],
    "charcoal": ["dark grey heather", "charcoal", "graphite heather"],
    "white": ["white", "vintage white"],
    "black": ["black", "black heather", "vintage black"],
    "red": ["red", "cardinal", "true red", "heather red"],
    "natural": ["natural", "heather natural", "tan"],
}

def _variants(product_id):
    pid = str(product_id)
    if pid in _variant_cache:
        return _variant_cache[pid]
    _st, data = product(pid)
    vs = ((data or {}).get("result") or {}).get("variants") or []
    _variant_cache[pid] = vs
    return vs

def resolve_variant(product_id, color, size):
    """Return the Printful variant id for a product + color + size, or None.

    Matching is deliberately strict-first: EXACT colour, then a known alias,
    then (last resort) a candidate that is a substring OF the variant colour.

    ⚠️ Never match in the reverse direction (variant colour inside the
    candidate). That once let the variant "Black" satisfy a request for
    "Heather Grey / Black" — i.e. ship the wrong colour cap. Two-tone Printful
    colours ("Heather Grey / Black", "Black / Charcoal") make that a real risk.
    """
    if not product_id:
        return None
    vs = _variants(product_id)
    if not vs:
        return None
    c = (color or "").strip().lower()
    s = (size or "").strip().upper()
    # products whose variants all share one size (caps/beanies) ignore size
    one_size = len({(v.get("size") or "").strip().upper() for v in vs}) <= 1

    def size_ok(v):
        if not s or one_size:
            return True
        return (v.get("size") or "").strip().upper() == s

    cands = [x for x in ([c] + COLOR_ALIASES.get(c, [])) if x]
    for v in vs:                                   # 1. exact colour
        if (v.get("color") or "").strip().lower() == c and size_ok(v):
            return v.get("id")
    for v in vs:                                   # 2. known alias, exact
        if (v.get("color") or "").strip().lower() in cands and size_ok(v):
            return v.get("id")
    for x in sorted(cands, key=len, reverse=True):  # 3. candidate inside variant colour
        for v in vs:
            if x in (v.get("color") or "").strip().lower() and size_ok(v):
                return v.get("id")
    # 4. products with NO colour axis at all (e.g. golf towel, drawstring bag):
    #    every variant is colourless, so match on size only. Safe because there
    #    is no colour to get wrong.
    if all(not (v.get("color") or "").strip() for v in vs):
        for v in vs:
            if size_ok(v):
                return v.get("id")
    return None
