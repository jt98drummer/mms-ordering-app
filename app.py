"""
MMS Material Ordering Hub - ordering app (v3).
Three INDEPENDENT stores, each with its own checkout:
  - Business Cards : company card only, own checkout, receipt auto-sent to accounting
  - Documents      : company card only, max 25 sheets/doc, receipt auto-sent to accounting
  - Swag/Apparel   : cart + role-based checkout with an approval safety net
M365 (Entra) sign-in gates the store; the signed-in role drives the swag rules.
Run:  pip install -r requirements.txt && python app.py   (http://localhost:8000)
Modes (env GELATO_MODE): dry | draft | live
"""
import os, json, csv, time, datetime, hmac, hashlib, re
from flask import (Flask, render_template, request, jsonify, send_from_directory,
                   abort, Response, redirect, session)
import config, gelato, printful, catalog, card_render, auth, graph, stripe_pay, branding
from card_engine import generate_card_pdf

app = Flask(__name__)
app.secret_key = config.SECRET_KEY
for d in (config.FILES_DIR, config.OUTBOX_DIR, config.PENDING_DIR):
    os.makedirs(d, exist_ok=True)
ORDER_LOG = os.path.join(config.BASE_DIR, "orders.csv")
SWAG = json.load(open(os.path.join(config.BASE_DIR, "swag_catalog.json")))
SWAG_BY_ID = {s["id"]: s for s in SWAG}
# precompute the per-colour logo choices, colour chips, and the pre-rendered
# colour x logo mockup image map so the product page can preview any combination.
_VAR_DIR = os.path.join(config.ASSET_DIR, "products", "variants")

def _slug(s):
    return re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-")

for _s in SWAG:
    _cols = _s.get("colors", [])
    _s["logo_by_color"] = {c: branding.logo_options(c) for c in _cols}
    _s["logo_default"] = {c: branding.default_logo(c) for c in _cols}
    _s["color_hex"] = {c: branding.color_hex(c) for c in _cols}
    _iv = {}
    for _c in _cols:
        _m = {}
        for _lk in branding.logo_options(_c):
            _fn = "%s__%s__%s.png" % (_s["id"], _slug(_c), _lk)
            if os.path.exists(os.path.join(_VAR_DIR, _fn)):
                _m[_lk] = "/asset/products/variants/" + _fn
        if _m:
            _iv[_c] = _m
    _s["img_variants"] = _iv


@app.context_processor
def inject_globals():
    return {
        "mode": config.GELATO_MODE,
        "user": auth.current_user(),
        "auth_enabled": config.AUTH_ENABLED,
        "stripe_enabled": config.STRIPE_ENABLED,
        "brand_logos": branding.client_logos(),
        "PRIVILEGED": list(config.PRIVILEGED_ROLES),
        "caps": {"fse_mgr_usd": config.FSE_MGR_AUTO_APPROVE_USD,
                 "emp_units": config.EMPLOYEE_MAX_UNITS,
                 "emp_usd": config.EMPLOYEE_MAX_ORDER_USD,
                 "doc_max": config.DOC_MAX_QTY},
    }


# ---------------- helpers ----------------
def _oid(prefix):
    return "%s-%s-%03d" % (prefix, datetime.datetime.now().strftime("%Y%m%d-%H%M%S"),
                           int(time.time() * 1000) % 1000)

def _sig(oid):
    return hmac.new(config.SECRET_KEY.encode(), oid.encode(), hashlib.sha256).hexdigest()[:16]

def _money(x):
    try:
        return "$%.2f" % float(x)
    except Exception:
        return "$0.00"

def _log(order, gstatus="", gid=""):
    new = not os.path.exists(ORDER_LOG)
    with open(ORDER_LOG, "a", newline="") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["timestamp", "order_id", "store", "orderer", "orderer_email", "role",
                        "payment", "qty", "amount_est", "purpose", "recipient", "justification",
                        "status", "approver", "mode", "gelato_status", "gelato_order_id"])
        w.writerow([datetime.datetime.now().isoformat(timespec="seconds"), order["oid"],
                    order["store"], order["orderer"], order["orderer_email"], order["role"],
                    order["payment"], order["qty"], order.get("total", ""), order["purpose"],
                    order.get("recipient_ctx", ""), order.get("justification", ""),
                    order["status"], order.get("approver", ""), config.GELATO_MODE, gstatus, gid])
    try:
        graph.log_to_sharepoint(order)
    except Exception:
        pass

def _recipient(d):
    nm = (d.get("firstName", "") + " " + d.get("lastName", "")).strip()
    return {
        "firstName": (d.get("firstName") or "MMS")[:25], "lastName": (d.get("lastName") or "Team")[:25],
        "companyName": config.COMPANY_NAME[:60],
        "addressLine1": d.get("addressLine1", "")[:35], "addressLine2": d.get("addressLine2", "")[:35],
        "city": d.get("city", "")[:30], "state": d.get("state", "")[:35],
        "postCode": d.get("postCode", "")[:15], "country": (d.get("country") or "US")[:2].upper(),
        "email": d.get("email", ""), "phone": d.get("phone", ""),
    }, nm

def _ctx_ok(c):
    return bool((c.get("purpose") or "").strip() and (c.get("justification") or "").strip())

def _mk_order(store, oid, u, payment, qty, lines, ctx, ship, ship_name, status, total="-", approver=""):
    pay_label = {"company": "Company card (MMS)",
                 "personal": "Personal card - NOT reimbursable"}.get(payment, payment)
    return {
        "store": store, "oid": oid,
        "orderer": u.get("name", ""), "orderer_email": u.get("email", ""), "role": u.get("role", ""),
        "payment": payment, "payment_label": pay_label,
        "qty": qty, "lines": lines, "total": total,
        "purpose": ctx.get("purpose", ""), "recipient_ctx": ctx.get("recipient", ""),
        "justification": ctx.get("justification", ""),
        "status": status, "approver": approver,
        "ship_summary": "%s, %s, %s %s %s" % (ship_name, ship.get("addressLine1", ""),
                        ship.get("city", ""), ship.get("state", ""), ship.get("postCode", "")),
        "_ship": ship,
    }

def _place_print(oid, ship, print_items):
    payload = gelato.build_order_payload(oid, ship.get("email") or "mms", print_items, ship)
    status, result = gelato.create_order(payload)
    gid = (result or {}).get("id", "")
    with open(os.path.join(config.FILES_DIR, oid + ".json"), "w") as f:
        json.dump({"payload": payload, "result": result}, f, indent=2)
    return status, result, gid

def _receipt_html(o):
    rows = "".join(
        "<tr><td style='padding:5px 10px;border-bottom:1px solid #eee'>%s</td>"
        "<td style='padding:5px 10px;border-bottom:1px solid #eee;text-align:center'>%s</td>"
        "<td style='padding:5px 10px;border-bottom:1px solid #eee;text-align:right'>%s</td></tr>"
        % (i["desc"], i["qty"], i.get("line", "-")) for i in o["lines"])
    appr = ("<tr><td style='padding:5px 10px;color:#6b7884'>Approved by</td>"
            "<td style='padding:5px 10px' colspan='2'>%s</td></tr>" % o["approver"]) if o.get("approver") else ""
    return ("""<div style="font-family:Arial,sans-serif;color:#22303c;max-width:640px">
<h2 style="color:#1e2d3b;margin:0 0 4px">MMS Order Receipt - %s</h2>
<div style="color:#c8102e;font-weight:700;margin-bottom:14px">Order %s &middot; %s</div>
<table style="border-collapse:collapse;width:100%%;font-size:14px">
<tr><td style="padding:5px 10px;color:#6b7884;width:120px">Ordered by</td><td style="padding:5px 10px" colspan="2"><b>%s</b> &lt;%s&gt; &middot; role: %s</td></tr>
<tr><td style="padding:5px 10px;color:#6b7884">Payment</td><td style="padding:5px 10px" colspan="2">%s</td></tr>
<tr><td style="padding:5px 10px;color:#6b7884">Purpose</td><td style="padding:5px 10px" colspan="2">%s</td></tr>
<tr><td style="padding:5px 10px;color:#6b7884">For / event</td><td style="padding:5px 10px" colspan="2">%s</td></tr>
<tr><td style="padding:5px 10px;color:#6b7884">Justification</td><td style="padding:5px 10px" colspan="2">%s</td></tr>
%s</table>
<table style="border-collapse:collapse;width:100%%;font-size:14px;margin-top:12px">
<tr style="background:#f7f7f7"><th style="text-align:left;padding:6px 10px">Item</th><th style="padding:6px 10px">Qty</th><th style="text-align:right;padding:6px 10px">Est. line</th></tr>
%s
<tr><td></td><td style="text-align:right;padding:6px 10px;font-weight:700">Est. total</td><td style="text-align:right;padding:6px 10px;font-weight:700">%s</td></tr>
</table>
<p style="color:#6b7884;font-size:12px;margin-top:14px">Ship to: %s<br>Order mode: %s &middot; Auto-generated by the MMS Material Ordering Hub.</p>
</div>""" % (o["store"], o["oid"], o["status"].upper(), o["orderer"], o["orderer_email"],
            o["role"], o["payment_label"], o["purpose"], o.get("recipient_ctx", "-"),
            o.get("justification", "-"), appr, rows, o.get("total", "-"),
            o.get("ship_summary", "-"), config.GELATO_MODE.upper()))

def _send_receipt(o):
    subj = "[MMS Order] %s - %s - %s (%s)" % (o["store"], o["orderer"], o["oid"], o["status"])
    sent, detail = graph.send_mail(subj, _receipt_html(o), [config.ACCOUNTING_EMAIL], cc=[o["orderer_email"]], bcc=[config.ARCHIVE_EMAIL])
    o["receipt_sent"] = sent
    o["receipt_detail"] = detail
    return sent

def _approval_links(oid):
    s = _sig(oid)
    return (config.PUBLIC_BASE_URL + "/approve/" + oid + "/" + s,
            config.PUBLIC_BASE_URL + "/reject/" + oid + "/" + s)

def _notify_approver(o, approver_email):
    ok_url, no_url = _approval_links(o["oid"])
    rows = "".join("<li>%s - qty %s (%s)</li>" % (i["desc"], i["qty"], i.get("line", "-")) for i in o["lines"])
    html = ("""<div style="font-family:Arial,sans-serif;color:#22303c;max-width:640px">
<h2 style="color:#1e2d3b">Approval needed - %s order</h2>
<p><b>%s</b> &lt;%s&gt; (%s) requests to order on the <b>company card</b>:</p>
<ul>%s</ul>
<p><b>Est. total:</b> %s<br><b>Purpose:</b> %s<br><b>For / event:</b> %s<br><b>Justification:</b> %s</p>
<p style="margin-top:16px">
<a href="%s" style="background:#2f7a34;color:#fff;padding:11px 20px;border-radius:8px;text-decoration:none;font-weight:700">Approve &amp; place order</a>
&nbsp;&nbsp;
<a href="%s" style="background:#c8102e;color:#fff;padding:11px 20px;border-radius:8px;text-decoration:none;font-weight:700">Reject</a></p>
<p style="color:#6b7884;font-size:12px">If approved, the order places automatically and a receipt goes to accounting.</p>
</div>""" % (o["store"], o["orderer"], o["orderer_email"], o["role"], rows, o.get("total", "-"),
            o["purpose"], o.get("recipient_ctx", "-"), o.get("justification", "-"), ok_url, no_url))
    subj = "[MMS Approval] %s - %s - %s" % (o["orderer"], o["store"], o.get("total", ""))
    return graph.send_mail(subj, html, [approver_email], cc=[config.NOTIFY_EMAIL])

def _save_pending(o):
    with open(os.path.join(config.PENDING_DIR, o["oid"] + ".json"), "w") as f:
        json.dump(o, f, indent=2)

def _load_pending(oid):
    p = os.path.join(config.PENDING_DIR, oid + ".json")
    return json.load(open(p)) if os.path.exists(p) else None


def _fulfill_swag(order):
    """Route each swag line to its maker: Gelato (print), Printful (apparel), emailed PO (promo)."""
    items = order.get("items", [])
    groups = {"gelato": [], "printful": [], "vendor": []}
    for it in items:
        ch = SWAG_BY_ID.get(it.get("id"), {}).get("fulfillment", "vendor")
        groups.get(ch, groups["vendor"]).append(it)
    # promo / specialty -> emailed PO to the swag vendor
    if groups["vendor"] and config.VENDOR_EMAIL:
        rows = "".join("<li>%s (%s%s) &mdash; logo: %s &times;%s</li>" % (
                       i.get("name",""), i.get("color",""), "/"+i["size"] if i.get("size") else "",
                       branding.label(branding.valid_logo(i.get("color"), i.get("logo"))), i.get("qty",1))
                       for i in groups["vendor"])
        html = ("<h3>MMS Swag PO - %s</h3><p>Please fulfill for <b>%s</b> &lt;%s&gt;:</p><ul>%s</ul>"
                "<p>Ship to: %s<br>Purpose: %s / %s</p>"
                % (order["oid"], order["orderer"], order["orderer_email"], rows,
                   order.get("ship_summary","-"), order["purpose"], order.get("recipient_ctx","-")))
        graph.send_mail("[MMS Swag PO] %s - %s" % (order["oid"], order["orderer"]),
                        html, [config.VENDOR_EMAIL], cc=[config.NOTIFY_EMAIL])
    if groups["printful"] and config.PRINTFUL_ENABLED:
        pf_items = []
        for i in groups["printful"]:
            pf = SWAG_BY_ID.get(i.get("id"), {}).get("printful", {})
            pid = pf.get("product_id")
            logo_key = branding.valid_logo(i.get("color"), i.get("logo"))
            color = (pf.get("color_map") or {}).get(i.get("color"), i.get("color"))
            vid = printful.resolve_variant(pid, color, i.get("size")) if pid else None
            if vid:
                it_item = {"variant_id": vid, "quantity": int(i.get("qty", 1)),
                           "files": [{"type": "default", "url": branding.logo_url(logo_key)}]}
                if SWAG_BY_ID.get(i.get("id"), {}).get("decoration") == "embroidery":
                    it_item["options"] = [{"id": "thread_colors", "value": branding.threads(logo_key)}]
                pf_items.append(it_item)
        if pf_items:
            sh = order.get("_ship", {})
            rcpt = {"name": (sh.get("firstName","") + " " + sh.get("lastName","")).strip() or "MMS Team",
                    "address1": sh.get("addressLine1",""), "city": sh.get("city",""),
                    "state_code": sh.get("state",""), "country_code": (sh.get("country") or "US"),
                    "zip": sh.get("postCode",""), "email": sh.get("email",""), "phone": sh.get("phone","")}
            st, _res = printful.create_order(pf_items, rcpt)
            order["printful_result"] = {"status": st, "line_items": len(pf_items)}
    if groups["gelato"]:
        g_items = []; n = 0
        for i in groups["gelato"]:
            g = SWAG_BY_ID.get(i.get("id"), {}).get("gelato", {})
            uid = (g.get("color_map") or {}).get(i.get("color")) or g.get("product_uid")
            if uid and uid != "TBD":
                n += 1
                logo_key = branding.valid_logo(i.get("color"), i.get("logo"))
                g_items.append({"itemReferenceId": "%s-g%d" % (order["oid"], n), "productUid": uid,
                                "files": [{"type": "default", "url": branding.logo_url(logo_key)}],
                                "quantity": int(i.get("qty", 1))})
        if g_items:
            sh = order.get("_ship", {})
            payload = gelato.build_order_payload(order["oid"], sh.get("email") or "mms", g_items, sh)
            st, _r = gelato.create_order(payload)
            order["gelato_result"] = {"status": st, "line_items": len(g_items)}
    # gelato / printful lines are dispatched once product UIDs + artwork + keys are in place
    order["fulfillment_plan"] = {k: len(v) for k, v in groups.items() if v}
    return order["fulfillment_plan"]


def _finalize_paid(oid, session=None):
    """Fulfill a personal-card order once Stripe has confirmed payment.
    Idempotent: safe to call from both the webhook and the success redirect;
    the `fulfilled` flag guarantees the order is only placed (and logged) once.
    Personal-card orders create NO accounting receipt (matches the demo path)."""
    o = _load_pending(oid)
    if not o or o.get("payment") != "personal":
        return None
    if o.get("fulfilled"):
        return o
    o["status"] = "paid"
    o["fulfilled"] = True
    if session is not None:
        o["stripe_session_id"] = session.get("id", o.get("stripe_session_id", ""))
        if session.get("payment_intent"):
            o["stripe_payment_intent"] = session.get("payment_intent")
    _fulfill_swag(o)
    _save_pending(o)
    _log(o)
    return o


# ---------------- auth ----------------
@app.route("/login")
def login():
    return auth.login()

@app.route(config.MS_REDIRECT_PATH)
def auth_callback():
    return auth.callback()

@app.route("/logout")
def logout():
    return auth.logout()

@app.route("/setrole/<role>")
def setrole(role):
    if not config.AUTH_ENABLED:                       # dev-only role preview
        session["dev_role"] = role
    return redirect(request.args.get("next") or "/swag")


# ---------------- pages ----------------
@app.route("/")
@auth.login_required
def index():
    return render_template("index.html")

@app.route("/cards")
@auth.login_required
def cards():
    return render_template("cards.html")

@app.route("/documents")
@auth.login_required
def documents():
    return render_template("documents.html", docs_json=json.dumps(catalog.load()),
                           doc_max=config.DOC_MAX_QTY)

@app.route("/flyers")
@auth.login_required
def flyers_redirect():
    return documents()

@app.route("/swag")
@auth.login_required
def swag():
    published = [s for s in SWAG if s.get("published")]
    return render_template("swag.html", swag_json=json.dumps(published), show_cart=True)

@app.route("/swag/product/<pid>")
@auth.login_required
def swag_product(pid):
    it = SWAG_BY_ID.get(pid)
    if not it or not it.get("published"):
        abort(404)
    return render_template("product.html", item=it, item_json=json.dumps(it), show_cart=True)

@app.route("/cart")
@auth.login_required
def cart():
    return render_template("cart.html", show_cart=True)


# ---------------- public files (Gelato fetches these; keep unauthenticated) ----------------
@app.route("/files/<path:name>")
def files(name):
    return send_from_directory(config.FILES_DIR, name)

@app.route("/flyerpdf/<cid>")
def flyerpdf(cid):
    d = catalog.by_id(cid)
    if not d:
        abort(404)
    return send_from_directory(os.path.join(config.ASSET_DIR, "flyers"), d["pdf"])

@app.route("/asset/<path:name>")
def asset(name):
    return send_from_directory(config.ASSET_DIR, name)

@app.route("/api/card_front.png")
def card_front_png():
    emp = {k: request.args.get(k, "") for k in ("name", "title", "email", "phone")}
    png = card_render.front_png_bytes(emp, scale=2)
    return Response(png, mimetype="image/png", headers={"Cache-Control": "no-store"})

@app.route("/health")
def health():
    return jsonify(ok=True, mode=config.GELATO_MODE, base=config.PUBLIC_BASE_URL,
                   auth=config.AUTH_ENABLED)


# ---------------- checkout: BUSINESS CARDS (company card only) ----------------
@app.route("/api/checkout/cards", methods=["POST"])
@auth.login_required
def checkout_cards():
    u = auth.current_user()
    body = request.get_json(force=True)
    ctx = body.get("context", {})
    if not _ctx_ok(ctx):
        return jsonify(ok=False, error="Please fill in the purpose and the justification."), 400
    ship, nm = _recipient(body.get("ship", {}))
    if not ship["addressLine1"] or not ship["city"]:
        return jsonify(ok=False, error="Please add at least a shipping address line 1 and city."), 400
    card = body.get("card", {})
    qty = int(card.get("qty", 250))
    oid = _oid("CARD")
    emp = {k: card.get(k, "") for k in ("name", "title", "email", "phone", "role", "territory")}
    pdf_name = oid + ".pdf"
    generate_card_pdf(emp, os.path.join(config.FILES_DIR, pdf_name))
    print_items = [{"itemReferenceId": oid + "-1", "productUid": config.CARD_PRODUCT_UID,
                    "files": [{"type": "default", "url": config.PUBLIC_BASE_URL + "/files/" + pdf_name}],
                    "quantity": qty}]
    status, result, gid = _place_print(oid, ship, print_items)
    order = _mk_order("Business Cards", oid, u, "company", qty,
                      [{"desc": "Business cards - " + emp.get("name", ""), "qty": qty,
                        "line": "priced by printer"}], ctx, ship, nm,
                      status="placed", total="priced by printer")
    _send_receipt(order)
    _log(order, status, gid)
    ok = status in (0, 200, 201)
    return jsonify(ok=ok, order_id=oid, status="placed", receipt_to=config.ACCOUNTING_EMAIL,
                   receipt_sent=order.get("receipt_sent"), gelato_status=status,
                   gelato=None if ok else result)


# ---------------- checkout: DOCUMENTS (company card only, max 25) ----------------
@app.route("/api/checkout/documents", methods=["POST"])
@auth.login_required
def checkout_documents():
    u = auth.current_user()
    body = request.get_json(force=True)
    ctx = body.get("context", {})
    if not _ctx_ok(ctx):
        return jsonify(ok=False, error="Please fill in the purpose and the justification."), 400
    d = catalog.by_id(body.get("id"))
    if not d:
        return jsonify(ok=False, error="Unknown document."), 400
    qty = int(body.get("qty", config.DOC_MAX_QTY))
    if qty < 1 or qty > config.DOC_MAX_QTY:
        return jsonify(ok=False, error="Quantity must be between 1 and %d sheets." % config.DOC_MAX_QTY), 400
    ship, nm = _recipient(body.get("ship", {}))
    if not ship["addressLine1"] or not ship["city"]:
        return jsonify(ok=False, error="Please add at least a shipping address line 1 and city."), 400
    oid = _oid("DOC")
    print_items = [{"itemReferenceId": oid + "-1",
                    "productUid": d.get("gelato_product", config.FLYER_PRODUCT_UID),
                    "files": [{"type": "default", "url": config.PUBLIC_BASE_URL + "/flyerpdf/" + d["id"]}],
                    "quantity": qty}]
    status, result, gid = _place_print(oid, ship, print_items)
    order = _mk_order("Documents", oid, u, "company", qty,
                      [{"desc": "%s (%s)" % (d["title"], d.get("division", "")), "qty": qty,
                        "line": "priced by printer"}], ctx, ship, nm,
                      status="placed", total="priced by printer")
    _send_receipt(order)
    _log(order, status, gid)
    ok = status in (0, 200, 201)
    return jsonify(ok=ok, order_id=oid, status="placed", receipt_to=config.ACCOUNTING_EMAIL,
                   receipt_sent=order.get("receipt_sent"), gelato_status=status,
                   gelato=None if ok else result)


# ---------------- checkout: SWAG/APPAREL (role-based, approval net) ----------------
@app.route("/api/checkout/swag", methods=["POST"])
@auth.login_required
def checkout_swag():
    u = auth.current_user()
    role = u.get("role", config.DEFAULT_ROLE)
    body = request.get_json(force=True)
    ctx = body.get("context", {})
    payment = body.get("payment", "company")
    items = [i for i in body.get("items", []) if i.get("type") == "swag"]
    if not items:
        return jsonify(ok=False, error="Your cart is empty."), 400
    if not _ctx_ok(ctx):
        return jsonify(ok=False, error="Please fill in the purpose and the justification."), 400
    ship, nm = _recipient(body.get("ship", {}))
    if not ship["addressLine1"] or not ship["city"]:
        return jsonify(ok=False, error="Please add at least a shipping address line 1 and city."), 400

    # normalise the chosen logo to one valid for the garment colour (so the
    # receipt, approval and fulfillment all agree with what the shopper saw)
    for i in items:
        i["logo"] = branding.valid_logo(i.get("color"), i.get("logo"))
    units = sum(int(i.get("qty", 1)) for i in items)
    total_val = sum(float(i.get("price", 0)) * int(i.get("qty", 1)) for i in items)
    lines = [{"desc": "%s (%s%s · %s)" % (i.get("name", ""), i.get("color", ""),
                                          "/" + i["size"] if i.get("size") else "",
                                          branding.label(i.get("logo"))),
              "qty": int(i.get("qty", 1)),
              "line": _money(float(i.get("price", 0)) * int(i.get("qty", 1)))} for i in items]
    oid = _oid("SWAG")

    # ---- personal card: no approval, no accounting receipt, must acknowledge ----
    if payment == "personal":
        if not body.get("ack_not_reimbursable"):
            return jsonify(ok=False,
                           error="Please acknowledge that personal-card orders are NOT reimbursable."), 400

        # When Stripe is configured, actually charge the card via hosted Checkout;
        # the order is fulfilled only after Stripe confirms payment (see _finalize_paid).
        if stripe_pay.enabled():
            if total_val < 0.50:
                return jsonify(ok=False,
                               error="Card checkout needs an order total of at least $0.50. "
                                     "Add items or use the company card."), 400
            order = _mk_order("Swag & Apparel", oid, u, "personal", units, lines, ctx, ship, nm,
                              status="awaiting_payment", total=_money(total_val))
            order["items"] = items
            success_url = (config.PUBLIC_BASE_URL + "/swag/pay/return?oid=" + oid
                           + "&session_id={CHECKOUT_SESSION_ID}")
            cancel_url = config.PUBLIC_BASE_URL + "/swag/pay/cancel?oid=" + oid
            checkout_url, ref = stripe_pay.create_checkout_session(order, success_url, cancel_url)
            if not checkout_url:
                return jsonify(ok=False,
                               error="Card checkout is temporarily unavailable. Please try again "
                                     "or use the company card."), 502
            order["stripe_session_id"] = ref
            _save_pending(order)
            _log(order)
            return jsonify(ok=True, order_id=oid, status="awaiting_payment", stripe=True,
                           checkout_url=checkout_url,
                           message="Redirecting you to secure card checkout...")

        # No Stripe configured -> demo path: place directly, nothing is charged.
        order = _mk_order("Swag & Apparel", oid, u, "personal", units, lines, ctx, ship, nm,
                          status="placed", total=_money(total_val))
        order["items"] = items
        _fulfill_swag(order)
        _log(order)
        return jsonify(ok=True, order_id=oid, status="placed", paid="personal",
                       message="Order placed on your personal card. This is NOT reimbursable "
                               "and was not sent to accounting.")

    # ---- company card ----
    if role == config.ROLE_EMPLOYEE:
        if units > config.EMPLOYEE_MAX_UNITS or total_val > config.EMPLOYEE_MAX_ORDER_USD:
            return jsonify(ok=False,
                           error="Employee company-card orders are capped at %d units and %s. "
                                 "Reduce the order, or use your personal card."
                                 % (config.EMPLOYEE_MAX_UNITS, _money(config.EMPLOYEE_MAX_ORDER_USD))), 400
        need_approval = True
    else:
        need_approval = total_val > config.FSE_MGR_AUTO_APPROVE_USD

    order = _mk_order("Swag & Apparel", oid, u, "company", units, lines, ctx, ship, nm,
                      status=("pending" if need_approval else "placed"), total=_money(total_val))
    order["items"] = items

    if need_approval:
        approver = config.ESCALATION_EMAIL if role == config.ROLE_MANAGER else \
            (u.get("manager_email") or config.NOTIFY_EMAIL)
        order["approver_pending"] = approver
        _save_pending(order)
        sent, _ = _notify_approver(order, approver)
        _log(order)
        return jsonify(ok=True, order_id=oid, status="pending", approver=approver, notified=sent,
                       message="Sent to %s for approval. The order places automatically once approved."
                               % approver)
    _fulfill_swag(order)
    _send_receipt(order)
    _log(order)
    return jsonify(ok=True, order_id=oid, status="placed", receipt_to=config.ACCOUNTING_EMAIL,
                   receipt_sent=order.get("receipt_sent"),
                   message="Approved automatically (under your limit). Receipt sent to accounting.")


# ---------------- approvals (signed links from the approver email) ----------------
def _approval_page(title, body, color):
    return ("""<html><body style="font-family:Arial,sans-serif;background:#f7f7f7;padding:60px;text-align:center">
<div style="max-width:520px;margin:0 auto;background:#fff;border-radius:14px;padding:34px;box-shadow:0 10px 30px rgba(0,0,0,.12)">
<div style="width:54px;height:54px;border-radius:50%%;background:%s;color:#fff;font-size:30px;line-height:54px;margin:0 auto 16px">&#10003;</div>
<h2 style="color:#1e2d3b;margin:0 0 8px">%s</h2><p style="color:#6b7884">%s</p></div></body></html>""" % (color, title, body))

@app.route("/approve/<oid>/<sig>")
def approve(oid, sig):
    if not hmac.compare_digest(sig, _sig(oid)):
        return "Invalid or expired approval link.", 403
    o = _load_pending(oid)
    if not o:
        return "This order was not found.", 404
    if o.get("status") != "pending":
        return _approval_page("Already processed", "Order %s is already %s." % (oid, o.get("status")), "#5b6b78")
    o["status"] = "placed"
    o["approver"] = o.get("approver_pending", "approver")
    _fulfill_swag(o)
    _send_receipt(o)
    _save_pending(o)
    _log(o)
    return _approval_page("Approved", "Order %s approved and placed. Receipt sent to accounting." % oid, "#2f7a34")

@app.route("/reject/<oid>/<sig>")
def reject(oid, sig):
    if not hmac.compare_digest(sig, _sig(oid)):
        return "Invalid or expired approval link.", 403
    o = _load_pending(oid)
    if not o:
        return "This order was not found.", 404
    if o.get("status") != "pending":
        return _approval_page("Already processed", "Order %s is already %s." % (oid, o.get("status")), "#5b6b78")
    o["status"] = "rejected"
    o["approver"] = o.get("approver_pending", "approver")
    _save_pending(o)
    _log(o)
    graph.send_mail("[MMS Order] Your swag order %s was not approved" % oid,
                    "<p>Your order %s was not approved. Please reach out to your manager for details.</p>" % oid,
                    [o["orderer_email"]])
    return _approval_page("Rejected", "Order %s was rejected. The requester has been notified." % oid, "#c8102e")


# ---------------- Stripe (personal-card swag checkout) ----------------
@app.route("/api/stripe/webhook", methods=["POST"])
def stripe_webhook():
    """Primary payment confirmation. Stripe POSTs here; we verify the signature
    against the RAW body (never parse it first) and fulfill on a paid session."""
    event = stripe_pay.verify_webhook(request.get_data(), request.headers.get("Stripe-Signature", ""))
    if event is None:
        abort(400)
    if event.get("type") == "checkout.session.completed":
        session = event["data"]["object"]
        if stripe_pay.is_paid(session):
            oid = (session.get("metadata") or {}).get("oid") or session.get("client_reference_id")
            if oid:
                _finalize_paid(oid, session)
    return jsonify(received=True)


@app.route("/swag/pay/return")
@auth.login_required
def swag_pay_return():
    """Where Stripe redirects the shopper after a successful payment. Acts as a
    fallback confirmation: re-fetch the session from Stripe and finalize if the
    webhook hasn't landed yet (idempotent)."""
    oid = request.args.get("oid", "")
    session_id = request.args.get("session_id", "")
    o = _load_pending(oid)
    if o and not o.get("fulfilled") and session_id:
        session = stripe_pay.retrieve_session(session_id)
        if session and stripe_pay.is_paid(session):
            o = _finalize_paid(oid, session)
    paid = bool(o and o.get("fulfilled"))
    return render_template("pay_result.html", result=("success" if paid else "pending"),
                           oid=oid, session_id=session_id, total=(o or {}).get("total", ""))


@app.route("/swag/pay/cancel")
@auth.login_required
def swag_pay_cancel():
    """Shopper backed out of Stripe Checkout. Nothing was charged; mark the
    pending order canceled so it doesn't linger as awaiting_payment."""
    oid = request.args.get("oid", "")
    o = _load_pending(oid)
    if o and not o.get("fulfilled") and o.get("status") == "awaiting_payment":
        o["status"] = "canceled"
        _save_pending(o)
    return render_template("pay_result.html", result="cancel", oid=oid,
                           session_id="", total=(o or {}).get("total", ""))


@app.route("/health/graph")
def health_graph():
    return jsonify(auth_enabled=config.AUTH_ENABLED, **graph.diag())


@app.route("/admin/gelato")
def admin_gelato():
    if request.args.get("token") != os.environ.get("ADMIN_TOKEN", "mms-discover"):
        abort(403)
    if request.args.get("what", "catalogs") == "catalogs":
        status, data = gelato.list_catalogs()
        return jsonify(status=status, data=data)
    cat = request.args.get("catalog", "apparel")
    status, data = gelato.search_products(cat, {}, limit=int(request.args.get("limit", "80")))
    prods = [{"uid": p.get("productUid"), "attrs": p.get("attributes", {})}
             for p in (data.get("products") or [])]
    return jsonify(status=status, catalog=cat, count=len(prods),
                   products=prods, raw=(None if prods else data))


@app.route("/admin/printful")
def admin_printful():
    if request.args.get("token") != os.environ.get("ADMIN_TOKEN", "mms-discover"):
        abort(403)
    what = request.args.get("what", "store")
    if what == "stores":
        status, data = printful.stores()
        return jsonify(status=status, what=what, data=data)
    if what == "find":
        q = request.args.get("q", "").lower()
        status, data = printful._req("GET", "/products")
        res = (data or {}).get("result") or []
        out = []
        for p in res:
            hay = ((p.get("brand") or "") + " " + (p.get("model") or "") + " " + (p.get("type_name") or "")).lower()
            if all(w in hay for w in q.split()):
                out.append({"id": p.get("id"), "brand": p.get("brand"), "model": p.get("model"),
                            "type_name": p.get("type_name"), "variant_count": p.get("variant_count")})
        return jsonify(status=status, q=q, count=len(out), scanned=len(res), products=out)
    if what == "variants":
        pid = request.args.get("id")
        status, data = printful.product(pid)
        res = data.get("result") or {}
        variants = [{"id": v.get("id"), "size": v.get("size"), "color": v.get("color"),
                     "in_stock": v.get("in_stock")} for v in (res.get("variants") or [])]
        return jsonify(status=status, id=pid, count=len(variants), variants=variants)
    if what == "store":
        status, data = printful.store_products()
        return jsonify(status=status, what=what, data=data)
    status, data = printful.catalog_products(limit=int(request.args.get("limit", "100")))
    return jsonify(status=status, what=what, data=data)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    print("MMS Material Ordering Hub | mode=%s | auth=%s | base=%s"
          % (config.GELATO_MODE, config.AUTH_ENABLED, config.PUBLIC_BASE_URL))
    app.run(host="0.0.0.0", port=port, debug=False)
