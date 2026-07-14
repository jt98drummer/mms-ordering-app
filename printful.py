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

def catalog_products(limit=100, offset=0):
    """Printful blank catalog (garments you can choose)."""
    return _req("GET", "/products?limit=%d&offset=%d" % (limit, offset))


DARK_COLORS = {"navy", "black", "charcoal", "red"}

def logo_url_for(color):
    """Pick the print file by garment color: white logo on dark garments, brand logo on light."""
    fn = "mms_logo_dark.png" if (color or "").strip().lower() in DARK_COLORS else "mms_logo_light.png"
    return config.PUBLIC_BASE_URL + "/asset/print/" + fn
