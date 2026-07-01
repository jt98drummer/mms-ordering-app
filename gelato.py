"""
Minimal Gelato API client (Order API v4).
Docs: https://dashboard.gelato.com/docs/orders/v4/create/
The card on your Gelato account is charged automatically for 'order' type.
"""
import json, urllib.request, urllib.error
import config

def _headers():
    return {"Content-Type": "application/json", "X-API-KEY": config.GELATO_API_KEY}

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

def search_products(catalog, attribute_filters=None, limit=50):
    """List product UIDs in a catalog (e.g. 'cards', 'flyers'). Needs an API key."""
    url = config.PRODUCT_SEARCH.format(catalog=catalog)
    payload = {"attributeFilters": attribute_filters or {}, "limit": limit, "offset": 0}
    return _post(url, payload)
