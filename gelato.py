"""
Minimal Gelato API client (Order API v4).
Docs: https://dashboard.gelato.com/docs/orders/v4/create/
The card on your Gelato account is charged automatically for 'order' type.
"""
import json, urllib.request, urllib.error
import config

def _headers():
    return {"Content-Type": "application/json", "X-API-KEY": config.GELATO_API_KEY, "User-Agent": "MMS-Ordering-App/1.0"}

def _post(url, payload):
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=_headers(), method="POST")
    try:
        with urllib.request.urlopen(req, timeout=40) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, {"error": e.read().decode("utf-8", "ignore")}
    except Exception as e:
        return 0, {"error": str(e)}

def build_order_payload(order_ref, customer_ref, items, recipient, order_type="order"):
    """items: [{itemReferenceId, productUid, files:[{type,url}], quantity}]"""
    return {
        "orderType": order_type,                 # 'order' (live) or 'draft'
        "orderReferenceId": str(order_ref),
        "customerReferenceId": str(customer_ref),
        "currency": config.CURRENCY,
        "items": items,
        "shipmentMethodUid": config.SHIPMENT_METHOD,
        "shippingAddress": recipient,
    }

def create_order(payload):
    """Returns (status_code, response_json). Honors config.GELATO_MODE."""
    mode = config.GELATO_MODE
    if mode == "dry":
        return 0, {"mode": "dry", "note": "No Gelato call made. Payload saved for review.", "payload": payload}
    if mode == "draft":
        payload = dict(payload, orderType="draft")
    # mode == 'live' keeps orderType 'order'
    return _post(config.ORDER_API, payload)

def quote(order_ref, customer_ref, products, recipient):
    """Best-effort price/shipping quote. Returns (status, json) or (0, {...})."""
    if config.GELATO_MODE == "dry" or not config.GELATO_API_KEY:
        return 0, {"mode": "dry", "note": "Quote skipped in dry mode."}
    payload = {
        "orderReferenceId": str(order_ref),
        "customerReferenceId": str(customer_ref),
        "currency": config.CURRENCY,
        "allowMultipleQuotes": False,
        "recipient": recipient,
        "products": products,
    }
    return _post(config.QUOTE_API, payload)

def quote_summary(order_ref, products, recipient):
    """Real cost breakdown for a Gelato order, for showing BEFORE checkout.

    Returns a dict: {ok, items, shipping, total, method, delivery_min,
    delivery_max, days_min, days_max} — or {ok: False, error} when unavailable
    (dry mode, no key, network). Picks the cheapest shipment method of the same
    type we actually order with (config.SHIPMENT_METHOD), so the quoted shipping
    matches what will be charged.
    """
    st, res = quote(order_ref, "mms-quote", products, recipient)
    if st not in (200, 201) or not isinstance(res, dict):
        return {"ok": False, "error": (res or {}).get("error") or "quote unavailable",
                "status": st}
    qs = res.get("quotes") or []
    if not qs:
        return {"ok": False, "error": "no quote returned"}
    q = qs[0]
    items_total = round(sum(float(p.get("price") or 0) for p in (q.get("products") or [])), 2)
    methods = q.get("shipmentMethods") or []
    if not methods:
        return {"ok": False, "error": "no shipping options"}
    want = (config.SHIPMENT_METHOD or "normal").lower()
    same = [m for m in methods if (m.get("type") or "").lower() == want] or methods
    m = min(same, key=lambda x: float(x.get("price") or 9999))
    shipping = round(float(m.get("price") or 0), 2)
    return {"ok": True, "items": items_total, "shipping": shipping,
            "total": round(items_total + shipping, 2),
            "method": m.get("name"), "currency": q.get("currency") or config.CURRENCY,
            "delivery_min": m.get("minDeliveryDate"), "delivery_max": m.get("maxDeliveryDate"),
            "days_min": m.get("minDeliveryDays"), "days_max": m.get("maxDeliveryDays")}


def search_products(catalog, attribute_filters=None, limit=50):
    """List product UIDs in a catalog (e.g. 'cards', 'flyers'). Needs an API key."""
    url = config.PRODUCT_SEARCH.format(catalog=catalog)
    payload = {"attributeFilters": attribute_filters or {}, "limit": limit, "offset": 0}
    return _post(url, payload)


def _get(url):
    req = urllib.request.Request(url, headers=_headers(), method="GET")
    try:
        with urllib.request.urlopen(req, timeout=40) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, {"error": e.read().decode("utf-8", "ignore")}
    except Exception as e:
        return 0, {"error": str(e)}

def list_catalogs():
    return _get("https://product.gelatoapis.com/v3/catalogs")
