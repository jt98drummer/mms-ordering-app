"""
MMS Material Ordering Hub - ordering app (v2).
Cards + Documents + Swag/Apparel, shared cart, single checkout.
Run:  pip install -r requirements.txt && python app.py   (open http://localhost:8000)
Modes (env GELATO_MODE): dry | draft | live
"""
import os, json, csv, time, datetime
from flask import Flask, render_template, request, jsonify, send_from_directory, abort, Response
import config, gelato, catalog, card_render
from card_engine import generate_card_pdf

app = Flask(__name__)
os.makedirs(config.FILES_DIR, exist_ok=True)
ORDER_LOG = os.path.join(config.BASE_DIR, "orders.csv")
SWAG = json.load(open(os.path.join(config.BASE_DIR, "swag_catalog.json")))

@app.context_processor
def inject_mode():
    return {"mode": config.GELATO_MODE}

def _oid(prefix): return f"{prefix}-{datetime.datetime.now():%Y%m%d-%H%M%S}-{int(time.time()*1000)%1000:03d}"

def _log(row):
    new = not os.path.exists(ORDER_LOG)
    with open(ORDER_LOG, "a", newline="") as f:
        w = csv.writer(f)
        if new: w.writerow(["timestamp","order_id","recipient","print_items","swag_items","summary","mode","gelato_status","gelato_order_id"])
        w.writerow(row)

def _recipient(d):
    nm = (d.get("firstName","")+" "+d.get("lastName","")).strip()
    return {
        "firstName": (d.get("firstName") or "MMS")[:25], "lastName": (d.get("lastName") or "Team")[:25],
        "companyName": config.COMPANY_NAME[:60],
        "addressLine1": d.get("addressLine1","")[:35], "addressLine2": d.get("addressLine2","")[:35],
        "city": d.get("city","")[:30], "state": d.get("state","")[:35],
        "postCode": d.get("postCode","")[:15], "country": (d.get("country") or "US")[:2].upper(),
        "email": d.get("email",""), "phone": d.get("phone",""),
    }, nm

# ---------------- pages ----------------
@app.route("/")
def index(): return render_template("index.html")

@app.route("/cards")
def cards(): return render_template("cards.html")

@app.route("/documents")
def documents(): return render_template("documents.html", docs_json=json.dumps(catalog.load()))

@app.route("/flyers")
def flyers_redirect(): return documents()

@app.route("/swag")
def swag(): return render_template("swag.html", swag_json=json.dumps(SWAG))

@app.route("/cart")
def cart(): return render_template("cart.html")

# ---------------- public files (Gelato fetches these) ----------------
@app.route("/files/<path:name>")
def files(name): return send_from_directory(config.FILES_DIR, name)

@app.route("/flyerpdf/<cid>")
def flyerpdf(cid):
    d = catalog.by_id(cid)
    if not d: abort(404)
    return send_from_directory(os.path.join(config.ASSET_DIR, "flyers"), d["pdf"])

@app.route("/asset/<path:name>")
def asset(name): return send_from_directory(config.ASSET_DIR, name)

@app.route("/api/card_front.png")
def card_front_png():
    emp = {k: request.args.get(k, "") for k in ("name", "title", "email", "phone")}
    png = card_render.front_png_bytes(emp, scale=2)
    return Response(png, mimetype="image/png", headers={"Cache-Control": "no-store"})

@app.route("/health")
def health(): return jsonify(ok=True, mode=config.GELATO_MODE, base=config.PUBLIC_BASE_URL)

# ---------------- checkout (whole cart) ----------------
@app.route("/api/checkout", methods=["POST"])
def checkout():
    body = request.get_json(force=True)
    items = body.get("items", [])
    ship, nm = _recipient(body.get("ship", {}))
    oid = _oid("CART")
    print_items, swag_items, summary = [], [], []
    idx = 0

    for it in items:
        t = it.get("type")
        if t == "card":
            idx += 1
            emp = {k: it.get(k, "") for k in ("name","title","email","phone","role","territory")}
            pdf_name = f"{oid}-card{idx}.pdf"
            generate_card_pdf(emp, os.path.join(config.FILES_DIR, pdf_name))
            print_items.append({
                "itemReferenceId": f"{oid}-{idx}", "productUid": config.CARD_PRODUCT_UID,
                "files": [{"type": "default", "url": f"{config.PUBLIC_BASE_URL}/files/{pdf_name}"}],
                "quantity": int(it.get("qty", 250))})
            summary.append(f"Cards:{emp.get('name','')}")
        elif t == "doc":
            d = catalog.by_id(it.get("id"))
            if not d: continue
            idx += 1
            print_items.append({
                "itemReferenceId": f"{oid}-{idx}", "productUid": d.get("gelato_product", config.FLYER_PRODUCT_UID),
                "files": [{"type": "default", "url": f"{config.PUBLIC_BASE_URL}/flyerpdf/{d['id']}"}],
                "quantity": int(it.get("qty", 25))})
            summary.append(f"Doc:{d['title']}")
        elif t == "swag":
            swag_items.append(it)
            summary.append(f"Swag:{it.get('name','')}({it.get('size','')}/{it.get('color','')})x{it.get('qty',1)}")

    status, result = 0, {"mode": config.GELATO_MODE, "note": "no print items"}
    gid = ""
    if print_items:
        payload = gelato.build_order_payload(oid, ship["email"] or "mms", print_items, ship)
        status, result = gelato.create_order(payload)
        gid = (result or {}).get("id", "")
        with open(os.path.join(config.FILES_DIR, f"{oid}.json"), "w") as f:
            json.dump({"payload": payload, "result": result, "swag": swag_items}, f, indent=2)

    _log([datetime.datetime.now().isoformat(timespec="seconds"), oid, nm,
          len(print_items), len(swag_items), "; ".join(summary)[:300], config.GELATO_MODE, status, gid])

    ok = True if not print_items else status in (0, 200, 201)
    return jsonify(ok=ok, order_id=oid, mode=config.GELATO_MODE,
                   print_items=len(print_items), swag_items=len(swag_items),
                   gelato_status=status, gelato=result if not ok else None)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    print(f"MMS Material Ordering Hub | mode={config.GELATO_MODE} | base={config.PUBLIC_BASE_URL}")
    app.run(host="0.0.0.0", port=port, debug=False)
