"""
Printful Mockup Generator client — fetch photorealistic, on-brand product
mockups for the storefront. Printful composites the SAME MMS logo print file
that fulfillment uses onto a real photo of the garment, so the preview matches
what ships.

Read-only w.r.t. orders: creating a mockup task never creates or charges an
order. Requires PRINTFUL_API_KEY. The logo `image_url` must be PUBLICLY
reachable (Printful's servers fetch it) — we point at the deployed app's
/asset/print/ files.

Reuses printful._req() for auth headers + store-id handling.
"""
import re, json, time, urllib.request
import printful


def _retry_secs(data):
    """Pull the 'try again after N seconds' hint out of a 429 body."""
    try:
        m = re.search(r"after (\d+) second", json.dumps(data))
        return int(m.group(1)) if m else None
    except Exception:
        return None


def _req(method, path, payload=None, tries=5):
    """printful._req with automatic 429 backoff (the mockup generator is
    rate-limited to a couple of create-task calls per minute)."""
    st, data = printful._req(method, path, payload)
    for _ in range(tries - 1):
        if st != 429:
            break
        wait = (_retry_secs(data) or 30) + 2
        print("    rate-limited; waiting %ds..." % wait)
        time.sleep(wait)
        st, data = printful._req(method, path, payload)
    return st, data


_pf_cache = {}


def _result(data):
    return (data or {}).get("result") or {}


def printfiles(product_id):
    """Available print placements + areas for a catalog product (cached)."""
    pid = str(product_id)
    if pid in _pf_cache:
        return 200, _pf_cache[pid]
    st, data = _req("GET", "/mockup-generator/printfiles/%s" % product_id)
    if st == 200 and data:
        _pf_cache[pid] = data
    return st, data


def area_for(product_id, variant_id, placement):
    """Print-area (width, height) in px for a variant+placement, from printfiles."""
    _st, data = printfiles(product_id)
    r = _result(data)
    by_id = {p.get("printfile_id"): p for p in (r.get("printfiles") or [])}
    for vp in (r.get("variant_printfiles") or []):
        if vp.get("variant_id") == variant_id:
            p = by_id.get((vp.get("placements") or {}).get(placement))
            if p:
                return p.get("width"), p.get("height")
    pfs = r.get("printfiles") or []
    return (pfs[0].get("width"), pfs[0].get("height")) if pfs else (None, None)


def placement_style(placement):
    if "chest_left" in placement:
        return "chest_left"
    if placement.startswith("embroidery"):
        return "center"
    return "front"


def make_position(aw, ah, style):
    """A file `position` box; Printful fits the logo into it, preserving aspect."""
    if not (aw and ah):
        return None
    if style == "chest_left":
        w = int(aw * 0.34); left = int(aw * 0.10); top = int(ah * 0.12)
    elif style == "center":
        w = int(aw * 0.60); left = (aw - w) // 2; top = int(ah * 0.34)
    else:  # front / large
        w = int(aw * 0.64); left = (aw - w) // 2; top = int(ah * 0.24)
    h = int(w * 0.42)
    if top + h > ah:
        top = max(0, ah - h)
    if left + w > aw:
        left = max(0, aw - w)
    return {"area_width": aw, "area_height": ah, "width": w, "height": h, "top": top, "left": left}


def choose_placement(product_id, prefer_chest=False):
    """Pick a sensible placement key from what the product actually supports.
    prefer_chest → left-chest (embroidery polos/jackets); else front (DTG)."""
    _st, data = printfiles(product_id)
    avail = ((data or {}).get("result") or {}).get("available_placements") or {}
    keys = list(avail.keys())
    if not keys:
        return None
    def first(preds):
        for pred in preds:
            for k in keys:
                if pred(k):
                    return k
        return None
    if prefer_chest:
        return first([lambda k: "chest_left" in k, lambda k: "left_chest" in k,
                      lambda k: "chest" in k, lambda k: k == "front",
                      lambda k: "front" in k]) or keys[0]
    return first([lambda k: k == "front", lambda k: "front" in k,
                  lambda k: "default" in k]) or keys[0]


def create_task(product_id, variant_ids, placement, image_url, position=None):
    f = {"placement": placement, "image_url": image_url}
    if position:
        f["position"] = position
    payload = {"variant_ids": variant_ids, "format": "png", "files": [f]}
    return _req("POST", "/mockup-generator/create-task/%s" % product_id, payload)


def get_task(task_key):
    return _req("GET", "/mockup-generator/task?task_key=%s" % task_key)


def generate(product_id, variant_id, placement, image_url, position=None, timeout=120, poll=3):
    """Create a mockup task and poll until done. Returns (mockup_url, info)."""
    _st, data = create_task(product_id, [variant_id], placement, image_url, position)
    res = (data or {}).get("result") or {}
    task_key = res.get("task_key")
    if not task_key:
        return None, {"stage": "create", "status": _st, "data": data}
    deadline = time.time() + timeout
    while time.time() < deadline:
        _st2, d2 = get_task(task_key)
        r2 = (d2 or {}).get("result") or {}
        status = r2.get("status")
        if status == "completed":
            mocks = r2.get("mockups") or []
            return (mocks[0].get("mockup_url") if mocks else None), {"status": "completed"}
        if status == "failed":
            return None, {"stage": "poll", "status": "failed", "data": d2}
        time.sleep(poll)
    return None, {"stage": "poll", "status": "timeout"}


def download(url, dest):
    """Download a completed mockup to a local file. Returns bytes written."""
    req = urllib.request.Request(url, headers={"User-Agent": "MMS-Ordering-App/1.0"})
    with urllib.request.urlopen(req, timeout=90) as r:
        b = r.read()
    with open(dest, "wb") as f:
        f.write(b)
    return len(b)
