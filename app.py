"""
MMS Branded Store — ordering app.
Run:  pip install -r requirements.txt  &&  python app.py
Open: http://localhost:8000
Modes (env GELATO_MODE): dry (default, no charge) | draft | live
"""
import os, json, csv, time, datetime
from flask import (Flask, render_template, request, jsonify,
                   send_from_directory, abort)
import config, gelato, catalog
from card_engine import generate_card_pdf

app = Flask(__name__)
os.makedirs(config.FILES_DIR, exist_ok=True)
ORDER_LOG = os.path.join(config.BASE_DIR, "orders.csv")

def _order_id(prefix):
    return f"{prefix}-{datetime.datetime.now():%Y%m%d-%H%M%S}-{int(time.time()*1000)%1000:03d}"

def _log(row):
    new = not os.path.exists(ORDER_LOG)
    with open(ORDER_LOG, "a", newline="") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["timestamp","type","order_id","recipient","summary","qty","mode","gelato_status","gelato_order_id"])
        w.writerow(row)

def _save_payload(order_id, payload, result):
    with open(os.path.join(config.FILES_DIR, f"{order_id}.json"), "w") as f:
        json.dump({"payload": payload, "result": result}, f, indent=2)

def _recipient(d):
    return {
        "firstName": d.get("firstName","")[:25], "lastName": d.get("lastName","")[:25],
        "companyName": d.get("companyName", config.COMPANY_NAME)[:60],
        "addressLine1": d.get("addressLine1","")[:35], "addressLine2": d.get("addressLine2","")[:35],
        "city": d.get("city","")[:30], "state": d.get("state","")[:35],
        "postCode": d.get("postCode","")[:15], "country": (d.get("country") or "US")[:2].upper(),
        "email": d.get("email",""), "phone": d.get("phone",""),
    }

# ---------------- pages ----------------
@app.route("/")
def index():
    return render_template("index.html", mode=config.GELATO_MODE)

@app.route("/cards")
def cards():
    return render_template("cards.html", mode=config.GELATO_MODE)

@app.route("/flyers")
def flyers():
    return render_template("flyers.html", mode=config.GELATO_MODE, docs=catalog.load())

# ---------------- public files (Gelato fetches these) ----------------
@app.route("/files/<path:name>")
def files(name):
    return send_from_directory(config.FILES_DIR, name)

@app.route("/flyerpdf/<cid>")
def flyerpdf(cid):
    d = catalog.by_id(cid)
    if not d: abort(404)
    return send_from_directory(os.path.join(config.ASSET_DIR, "flyers"), d["pdf"])

@app.route("/asset/<path:name>")
def asset(name):
    return send_from_directory(config.ASSET_DIR, name)

@app.route("/health")
def health():
    return jsonify(ok=True, mode=config.GELATO_MODE, base=config.PUBLIC_BASE_URL)

# ---------------- ordering ----------------
@app.route("/api/order/card", methods=["POST"])
def order_card():
    d = request.get_json(force=True)
    emp = {k: d.get(k, "") for k in ("name","title","email","phone","role","territory")}
    qty = int(d.get("quantity", 250))
    ship = _recipient(d.get("ship", {}))
    if not ship["addressLine1"] or not ship["firstName"]:
        # default ship-to = the employee themselves if not provided
        nm = emp["name"].split(" ", 1) + [""]
        ship["firstName"] = ship["firstName"] or nm[0]
        ship["lastName"] = ship["lastName"] or nm[1]
        ship["email"] = ship["email"] or emp["email"]

    oid = _order_id("CARD")
    pdf_name = f"{oid}.pdf"
    generate_card_pdf(emp, os.path.join(config.FILES_DIR, pdf_name))
    file_url = f"{config.PUBLIC_BASE_URL}/files/{pdf_name}"

    items = [{
        "itemReferenceId": oid + "-1",
        "productUid": config.CARD_PRODUCT_UID,
        "files": [{"type": "default", "url": file_url}],
        "quantity": qty,
    }]
    payload = gelato.build_order_payload(oid, emp["email"] or "mms", items, ship)
    status, result = gelato.create_order(payload)
    _save_payload(oid, payload, result)
    gid = (result or {}).get("id", "")
    _log([datetime.datetime.now().isoformat(timespec="seconds"), "card", oid,
          f'{ship["firstName"]} {ship["lastName"]}', f'Business cards ({emp["role"]})',
          qty, config.GELATO_MODE, status, gid])
    return jsonify(ok=status in (0,200,201), order_id=oid, mode=config.GELATO_MODE,
                   file_url=file_url, gelato_status=status, gelato=result)

@app.route("/api/order/flyer", methods=["POST"])
def order_flyer():
    d = request.get_json(force=True)
    sel = d.get("items", [])   # [{id, quantity}]
    ship = _recipient(d.get("ship", {}))
    if not sel: return jsonify(ok=False, error="No documents selected"), 400

    oid = _order_id("DOC")
    items, summary = [], []
    for i, s in enumerate(sel, 1):
        doc = catalog.by_id(s["id"])
        if not doc: continue
        url = f"{config.PUBLIC_BASE_URL}/flyerpdf/{doc['id']}"
        items.append({
            "itemReferenceId": f"{oid}-{i}",
            "productUid": doc.get("gelato_product", config.FLYER_PRODUCT_UID),
            "files": [{"type": "default", "url": url}],
            "quantity": int(s.get("quantity", 25)),
        })
        summary.append(f'{doc["title"]} x{int(s.get("quantity",25))}')
    payload = gelato.build_order_payload(oid, ship["email"] or "mms", items, ship)
    status, result = gelato.create_order(payload)
    _save_payload(oid, payload, result)
    gid = (result or {}).get("id", "")
    _log([datetime.datetime.now().isoformat(timespec="seconds"), "flyer", oid,
          f'{ship["firstName"]} {ship["lastName"]}', "; ".join(summary),
          sum(int(s.get("quantity",25)) for s in sel), config.GELATO_MODE, status, gid])
    return jsonify(ok=status in (0,200,201), order_id=oid, mode=config.GELATO_MODE,
                   items=len(items), gelato_status=status, gelato=result)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    print(f"MMS Order App | mode={config.GELATO_MODE} | base={config.PUBLIC_BASE_URL}")
    app.run(host="0.0.0.0", port=port, debug=False)
