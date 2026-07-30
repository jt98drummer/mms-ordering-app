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
import config, gelato, printful, catalog, card_render, auth, graph, stripe_pay, branding, budget, popularity
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
    _s["logo_by_color"] = {c: branding.item_logo_options(_s, c) for c in _cols}
    _s["logo_default"] = {c: branding.item_logo_options(_s, c)[0] for c in _cols}
    _s["color_hex"] = {c: branding.item_hex(_s, c) for c in _cols}
    _iv = {}
    for _c in _cols:
        _m = {}
        for _lk in branding.item_logo_options(_s, _c):
            _fn = "%s__%s__%s.png" % (_s["id"], _slug(_c), _lk)
            if os.path.exists(os.path.join(_VAR_DIR, _fn)):
                _m[_lk] = "/asset/products/variants/" + _fn
        if _m:
            _iv[_c] = _m
    _s["img_variants"] = _iv


@app.context_processor
def inject_globals():
    u = auth.current_user()
    return {
        "mode": config.GELATO_MODE,
        "user": u,
        "auth_enabled": config.AUTH_ENABLED,
        "stripe_enabled": config.STRIPE_ENABLED,
        "brand_logos": branding.client_logos(),
        "PRIVILEGED": list(config.PRIVILEGED_ROLES),
        "budget": budget.status(u),
        "caps": {"doc_max": config.DOC_MAX_QTY,
                 "card_emp": config.CARD_MAX_QTY_EMPLOYEE,
                 "card_fse": config.CARD_MAX_QTY_FSE},
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
    for _i in (order.get("items") or []):        # popularity: real orders rank highest
        popularity.ordered(_i.get("id"), _i.get("qty", 1))
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
                       branding.label(branding.item_valid_logo(SWAG_BY_ID.get(i.get("id")), i.get("color"), i.get("logo"))), i.get("qty",1))
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
            logo_key = branding.item_valid_logo(SWAG_BY_ID.get(i.get("id")), i.get("color"), i.get("logo"))
            color = (pf.get("color_map") or {}).get(i.get("color"), i.get("color"))
            vid = printful.resolve_variant(pid, color, i.get("size")) if pid else None
            if vid:
                # Use the SAME placement + position the storefront mockup was
                # rendered with (frozen into the catalog by
                # `gen_products.py printspec`), so the printed garment matches
                # the preview. Without these Printful auto-fits the artwork to
                # the whole print area — e.g. a 12" tee print vs the 7.7" shown.
                f = {"type": pf.get("print_placement") or "default",
                     "url": branding.item_logo_url(SWAG_BY_ID.get(i.get("id")), logo_key)}
                if pf.get("print_position"):
                    f["position"] = pf["print_position"]
                it_item = {"variant_id": vid, "quantity": int(i.get("qty", 1)), "files": [f]}
                if SWAG_BY_ID.get(i.get("id"), {}).get("decoration") == "embroidery":
                    # The option id is PLACEMENT-specific (thread_colors_chest_left,
                    # thread_colors_front_large, ...) and the value must come from
                    # Printful's fixed thread palette — either wrong is a hard 400.
                    it_item["options"] = [{"id": pf.get("thread_option") or "thread_colors",
                                           "value": branding.printful_threads(logo_key)}]
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
                logo_key = branding.item_valid_logo(SWAG_BY_ID.get(i.get("id")), i.get("color"), i.get("logo"))
                g_items.append({"itemReferenceId": "%s-g%d" % (order["oid"], n), "productUid": uid,
                                "files": [{"type": "default",
                                           "url": branding.item_logo_url(SWAG_BY_ID.get(i.get("id")), logo_key)}],
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
    # Role preview: allowed in DEV for anyone, and in PRODUCTION only for an
    # allowlisted signed-in user (config.ROLE_PREVIEW_EMAILS) so they can verify
    # the non-FSE safety net. Everyone else is a no-op.
    role = (role or "").lower()
    u = auth.current_user()
    can = (not config.AUTH_ENABLED) or (u and u.get("can_preview"))
    if can:
        if role in ("reset", "clear", "off", "me"):
            session.pop("role_override", None)
            session.pop("dev_role", None)
        elif role in (config.ROLE_MANAGER, config.ROLE_FSE, config.ROLE_EMPLOYEE):
            if config.AUTH_ENABLED:
                session["role_override"] = role
            else:
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
    docs = catalog.load()
    trending = [d for d in docs if d.get("trending")]
    return render_template("documents.html", docs_json=json.dumps(docs),
                           trending_json=json.dumps(trending),
                           doc_max=config.DOC_MAX_QTY)

@app.route("/documents/cart")
def documents_cart():
    """Documents used to have their own cart; everything shares /cart now."""
    return redirect("/cart")


@app.route("/flyers")
@auth.login_required
def flyers_redirect():
    return documents()

@app.route("/swag")
@auth.login_required
def swag():
    published = [s for s in SWAG if s.get("published")]
    # Crew Favorites: most-ordered first, falling back to most-viewed while
    # order volume is low (popularity.rank), topped up with these defaults.
    favs = popularity.rank(published, limit=5,
                           fallback_ids=("ap3", "ap1", "ap10", "ev4", "ap8"))
    return render_template("swag.html", swag_json=json.dumps(published),
                           favs_json=json.dumps(favs), show_cart=True)

@app.route("/swag/product/<pid>")
@auth.login_required
def swag_product(pid):
    it = SWAG_BY_ID.get(pid)
    if not it or not it.get("published"):
        abort(404)
    popularity.view(pid)                       # drives the Crew Favorites ranking
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
# Business cards + documents no longer have their own checkout endpoints — the
# unified /api/checkout below handles the whole cart so role rules can never
# be bypassed by posting straight to a per-store route.


# ---------------- live cost quotes (cards + documents, printed by Gelato) ----------------
@app.route("/api/quote/print", methods=["POST"])
@auth.login_required
def quote_print():
    """Real cost + shipping + estimated delivery for the PRINT half of the cart
    (business cards and documents together — they ship as one Gelato order, so
    quoting them together is both accurate and cheaper than quoting separately).
    """
    body = request.get_json(force=True)
    u = auth.current_user()
    ship, _nm = _recipient(body.get("ship", {}))
    if not ship["addressLine1"] or not ship["city"]:
        return jsonify(ok=False, error="Enter a shipping address to see the price."), 400
    raw = [i for i in (body.get("items") or []) if i.get("type") in ("card", "doc")]
    print_lines, _swag, err = _split_cart(raw, u.get("role", config.DEFAULT_ROLE))
    if err:
        return jsonify(ok=False, error=err), 400
    q = gelato.quote_summary(_oid("QPRN"), _print_quote_products(print_lines), ship)
    return jsonify(dict(q, lines=len(print_lines),
                        units=sum(l["qty"] for l in print_lines)))


CARD_FIELDS = ("name", "title", "email", "phone", "role", "territory")


def _split_cart(raw, role):
    """Validate a MIXED cart and return (print_lines, swag_items, error).

    print_lines are card/doc lines kept as data (not Gelato payload) so the
    Gelato items — and any business-card PDF — are built at PLACEMENT time,
    which may be after a manager approves. Everything is re-derived from the
    catalog server-side; the client's prices and titles are never trusted.
    """
    cards = [i for i in raw if i.get("type") == "card"]
    docs = [i for i in raw if i.get("type") == "doc"]
    swag = [i for i in raw if i.get("type") == "swag"]
    if not (cards or docs or swag):
        return None, None, "Your cart is empty."

    print_lines = []
    cmax = _card_max_qty(role)
    for c in cards:
        try:
            qty = int(c.get("qty", 250))
        except (TypeError, ValueError):
            return None, None, "Invalid business-card quantity."
        if qty < 1:
            return None, None, "Business-card quantity must be at least 1."
        if cmax and qty > cmax:
            return None, None, ("Your role can order up to %d business cards per order. "
                                "Please reduce the quantity." % cmax)
        emp = {k: (c.get(k) or "").strip() for k in CARD_FIELDS}
        if not emp["name"]:
            return None, None, "Business cards need at least a name."
        print_lines.append({"kind": "card", "emp": emp, "qty": qty,
                            "title": "Business cards - " + emp["name"],
                            "uid": config.CARD_PRODUCT_UID})

    if docs:
        pairs, err = _doc_items(docs)
        if err:
            return None, None, err
        for d, qty in pairs:
            print_lines.append({"kind": "doc", "id": d["id"], "qty": qty,
                                "title": "%s (%s)" % (d["title"], d.get("division", "")),
                                "uid": d.get("gelato_product", config.FLYER_PRODUCT_UID)})

    swag_items = []
    if swag:
        swag_items, err = _price_items(swag)
        if err:
            return None, None, err
    return print_lines, swag_items, None


def _print_quote_products(print_lines):
    """Gelato quote payload for print lines. The file URL doesn't affect price
    (verified against the live quote API), so this needs no PDF to exist yet."""
    out = []
    for n, l in enumerate(print_lines, 1):
        url = (config.PUBLIC_BASE_URL + "/flyerpdf/" + l["id"]) if l["kind"] == "doc" \
            else (config.PUBLIC_BASE_URL + "/asset/print/quote-placeholder.pdf")
        out.append({"itemReferenceId": "q%d" % n, "productUid": l["uid"],
                    "quantity": l["qty"], "files": [{"type": "default", "url": url}]})
    return out


def _build_print_items(oid, print_lines):
    """Turn stored print lines into real Gelato items, generating each business
    card PDF now. Called at placement time — immediately, or after approval."""
    items = []
    for n, l in enumerate(print_lines, 1):
        if l["kind"] == "card":
            pdf = "%s-c%d.pdf" % (oid, n)
            generate_card_pdf(l["emp"], os.path.join(config.FILES_DIR, pdf))
            url = config.PUBLIC_BASE_URL + "/files/" + pdf
        else:
            url = config.PUBLIC_BASE_URL + "/flyerpdf/" + l["id"]
        items.append({"itemReferenceId": "%s-%d" % (oid, n), "productUid": l["uid"],
                      "files": [{"type": "default", "url": url}], "quantity": l["qty"]})
    return items


def _place_print_lines(order):
    """Place the card/document half of an order with Gelato."""
    lines = order.get("print_lines") or []
    if not lines:
        return None, None, ""
    items = _build_print_items(order["oid"], lines)
    return _place_print(order["oid"], order.get("_ship", {}), items)


def approver_for(u):
    """Who approves this person's orders."""
    role = u.get("role", config.DEFAULT_ROLE)
    if role == config.ROLE_MANAGER:               # a manager escalates above themselves
        return config.ESCALATION_EMAIL
    return u.get("manager_email") or config.NOTIFY_EMAIL


def print_needs_approval(role):
    """Cards + documents (always company card).

    Employees need manager approval for anything on the company card.
    FSEs and managers place print orders immediately.
    """
    return role not in (config.ROLE_FSE, config.ROLE_MANAGER)


def swag_needs_approval(role, email, total):
    """Swag on the COMPANY card. Returns (needs_approval, reserved, remaining).

    - employee : always needs approval (no budget involved)
    - fse      : within the $250 bimonthly budget places now (and is reserved
                 atomically); over budget needs approval
    - manager  : always places now
    """
    if role == config.ROLE_MANAGER:
        return False, False, None
    if role != config.ROLE_FSE:                   # employee -> approval, never reserve
        return True, False, None
    cap = budget.budget_for(role)
    reserved, remaining, _left = budget.try_reserve(email, total, cap)
    return (not reserved), reserved, remaining


def _card_max_qty(role):
    """Business-card quantity cap per order: 500 for FSEs and managers,
    100 for everyone else. Documents are capped separately at DOC_MAX_QTY each."""
    if role in (config.ROLE_FSE, config.ROLE_MANAGER):
        return config.CARD_MAX_QTY_FSE
    return config.CARD_MAX_QTY_EMPLOYEE


def _doc_items(raw):
    """Validate a document cart against the catalog. Returns ([(doc, qty)], error)."""
    out = []
    for i in raw:
        d = catalog.by_id((i.get("id") or "").strip())
        if not d:
            return None, "One of those documents is no longer available. Please refresh."
        try:
            qty = int(i.get("qty") or 0)
        except (TypeError, ValueError):
            return None, "Invalid quantity."
        if qty < 1 or qty > config.DOC_MAX_QTY:
            return None, "%s: quantity must be between 1 and %d sheets." % (d["title"], config.DOC_MAX_QTY)
        out.append((d, qty))
    if not out:
        return None, "No documents selected."
    return out, None


MAX_LINE_QTY = int(os.environ.get("SWAG_MAX_LINE_QTY", "500"))


def _price_items(raw):
    """Rebuild cart lines from the CATALOG (authoritative), ignoring any
    client-supplied price/name. Returns (items, error). Every line must name a
    real, published product with a valid colour/size and a sane quantity, so a
    tampered or stale cart can never mis-charge a budget."""
    out = []
    for i in raw:
        pid = (i.get("id") or "").strip()
        prod = SWAG_BY_ID.get(pid)
        if not prod or not prod.get("published"):
            return None, "That item is no longer available. Please refresh the store and rebuild your cart."
        try:
            qty = int(i.get("qty", 1))
        except (TypeError, ValueError):
            return None, "Invalid quantity."
        if qty < 1 or qty > MAX_LINE_QTY:
            return None, "Quantity for %s must be between 1 and %d." % (prod["name"], MAX_LINE_QTY)
        colors = prod.get("colors") or []
        color = i.get("color")
        if colors and color not in colors:
            return None, "%s doesn't come in %s. Please pick an available colour." % (prod["name"], color)
        sizes = prod.get("sizes") or []
        size = i.get("size") or ""
        if sizes and size not in sizes:
            return None, "%s doesn't come in size %s." % (prod["name"], size or "(none)")
        if not sizes:
            size = ""
        out.append({
            "type": "swag", "id": pid,
            "name": prod["name"],                       # catalog name
            "price": item_unit_cost(prod, size),        # catalog cost for THIS size
            "qty": qty, "color": color, "size": size,
            "logo": branding.item_valid_logo(prod, color, i.get("logo")),  # colour-appropriate
            "icon": prod.get("icon"), "image": prod.get("image"),
            "ship_first": round(float(prod.get("ship_first") or 0), 2),
            "ship_addl": round(float(prod.get("ship_addl") or 0), 2),
        })
    if not out:
        return None, "Your cart is empty."
    return out, None


def item_unit_cost(prod, size):
    """Unit cost for a specific size. Extended sizes (2XL+) cost more, so the
    per-size table wins when present; otherwise the base price."""
    by = prod.get("price_by_size") or {}
    if size and size in by:
        return round(float(by[size]), 2)
    return round(float(prod.get("price") or 0), 2)


def estimate_shipping(items):
    """Estimated shipping for a cart, mirroring Printful's model: the highest
    first-item rate in the cart, plus the additional-unit rate for every other
    unit. Shown separately from item cost so the true spend is visible."""
    if not items:
        return 0.0
    first = max((float(i.get("ship_first") or 0) for i in items), default=0.0)
    # the unit that claimed the first-item rate doesn't also pay an additional rate
    lead = max(items, key=lambda i: float(i.get("ship_first") or 0))
    total = first
    for i in items:
        n = int(i.get("qty", 1)) - (1 if i is lead else 0)
        total += max(0, n) * float(i.get("ship_addl") or 0)
    return round(total, 2)


# ---------------- checkout: SWAG/APPAREL (role-based, approval net) ----------------
@app.route("/api/checkout", methods=["POST"])
@auth.login_required
def checkout_all():
    """ONE checkout for the whole cart (business cards + documents + swag).

    Fulfillment is split by line type (Gelato for print, Printful/vendor for
    swag) and the approval rules are applied per half:

      employee : every company-card line needs manager approval -> one request
      fse      : print places now; swag places now within the $250 bimonthly
                 budget, otherwise the SWAG HALF alone goes for approval
      manager  : everything places now

    `payment: "personal"` applies to the SWAG lines only — cards and documents
    are always company card — so a mixed cart can split payment.
    """
    u = auth.current_user()
    role = u.get("role", config.DEFAULT_ROLE)
    body = request.get_json(force=True)
    ctx = body.get("context", {})
    if not _ctx_ok(ctx):
        return jsonify(ok=False, error="Please fill in the purpose and the justification."), 400
    ship, nm = _recipient(body.get("ship", {}))
    if not ship["addressLine1"] or not ship["city"]:
        return jsonify(ok=False, error="Please add at least a shipping address line 1 and city."), 400
    payment = body.get("payment", "company")
    print_lines, swag_items, err = _split_cart(body.get("items") or [], role)
    if err:
        return jsonify(ok=False, error=err), 400
    if payment == "personal" and swag_items and not body.get("ack_not_reimbursable"):
        return jsonify(ok=False,
                       error="Please acknowledge that personal-card swag is NOT reimbursable."), 400

    results, oids = [], []

    # ---------- print half: business cards + documents (always company card) ----------
    if print_lines:
        oid = _oid("PRNT")
        q = gelato.quote_summary(oid + "-q", _print_quote_products(print_lines), ship)
        lines = [{"desc": l["title"], "qty": l["qty"], "line": "-"} for l in print_lines]
        if q.get("ok"):
            lines.append({"desc": "Printing", "qty": "", "line": _money(q["items"])})
            lines.append({"desc": "Shipping (%s)" % (q.get("method") or "standard"),
                          "qty": "", "line": _money(q["shipping"])})
        qty_total = sum(l["qty"] for l in print_lines)
        store = "Business Cards & Documents" if any(l["kind"] == "card" for l in print_lines) \
            and any(l["kind"] == "doc" for l in print_lines) else \
            ("Business Cards" if print_lines[0]["kind"] == "card" else "Documents")
        need = print_needs_approval(role)
        order = _mk_order(store, oid, u, "company", qty_total, lines, ctx, ship, nm,
                          status=("pending" if need else "placed"),
                          total=_money(q["total"]) if q.get("ok") else "priced by printer")
        order["print_lines"] = print_lines
        if q.get("ok"):
            order["quote"] = q
            order["_total_usd"] = q["total"]
        if need:
            approver = approver_for(u)
            order["approver_pending"] = approver
            _save_pending(order); _log(order)
            sent, _ = _notify_approver(order, approver)
            results.append({"store": store, "order_id": oid, "status": "pending",
                            "approver": approver, "notified": sent,
                            "total": order["total"]})
        else:
            st, res, gid = _place_print_lines(order)
            _send_receipt(order); _log(order, st, gid)
            results.append({"store": store, "order_id": oid, "status": "placed",
                            "total": order["total"], "gelato_status": st,
                            "delivery": (q.get("delivery_min"), q.get("delivery_max")) if q.get("ok") else None})
        oids.append(oid)

    # ---------- swag half ----------
    if swag_items:
        oid = _oid("SWAG")
        goods = round(sum(i["price"] * i["qty"] for i in swag_items), 2)
        shipv = estimate_shipping(swag_items)
        total_val = round(goods + shipv, 2)
        units = sum(i["qty"] for i in swag_items)
        lines = [{"desc": "%s (%s%s · %s)" % (i["name"], i["color"],
                                              "/" + i["size"] if i.get("size") else "",
                                              branding.label(i.get("logo"))),
                  "qty": i["qty"], "line": _money(i["price"] * i["qty"])} for i in swag_items]
        lines.append({"desc": "Shipping (estimated)", "qty": "", "line": _money(shipv)})

        if payment == "personal":
            r = _place_personal_swag(oid, u, units, lines, ctx, ship, nm, swag_items, total_val)
            results.append(r)
            oids.append(oid)
        else:
            need, reserved, remaining = swag_needs_approval(role, u.get("email", ""), total_val)
            order = _mk_order("Swag & Apparel", oid, u, "company", units, lines, ctx, ship, nm,
                              status=("pending" if need else "placed"), total=_money(total_val))
            order["items"] = swag_items
            order["_total_usd"] = total_val
            if need:
                approver = approver_for(u)
                order["approver_pending"] = approver
                order["over_budget"] = (role == config.ROLE_FSE)
                _save_pending(order); _log(order)
                sent, _ = _notify_approver(order, approver)
                msg = ("This swag order is %s and would exceed your remaining budget (%s)."
                       % (_money(total_val), _money(remaining))) if role == config.ROLE_FSE \
                    else "Swag on the company card needs your manager's approval."
                results.append({"store": "Swag & Apparel", "order_id": oid, "status": "pending",
                                "approver": approver, "notified": sent,
                                "total": order["total"], "note": msg})
            else:
                try:
                    _fulfill_swag(order)
                except Exception:
                    if reserved:
                        budget.release(u.get("email", ""), total_val, budget.budget_for(role))
                    app.logger.exception("swag fulfillment failed for %s", oid)
                    return jsonify(ok=False, error="We couldn't submit the swag part of your order "
                                                   "to the printer. Nothing was charged - please try again."), 502
                _send_receipt(order); _log(order)
                results.append({"store": "Swag & Apparel", "order_id": oid, "status": "placed",
                                "total": order["total"]})
            oids.append(oid)

    pending = [r for r in results if r["status"] == "pending"]
    placed = [r for r in results if r["status"] == "placed"]
    stripe_r = next((r for r in results if r.get("checkout_url")), None)
    return jsonify(ok=True, orders=results, order_ids=oids,
                   any_pending=bool(pending), any_placed=bool(placed),
                   checkout_url=(stripe_r or {}).get("checkout_url"),
                   receipt_to=config.ACCOUNTING_EMAIL)


def _place_personal_swag(oid, u, units, lines, ctx, ship, nm, items, total_val):
    """Personal-card swag: Stripe hosted Checkout when configured (fulfilled only
    after payment), else the safe demo path. Never touches the budget."""
    if stripe_pay.enabled():
        if total_val < 0.50:
            return {"store": "Swag & Apparel", "order_id": oid, "status": "error",
                    "note": "Card checkout needs a total of at least $0.50."}
        order = _mk_order("Swag & Apparel", oid, u, "personal", units, lines, ctx, ship, nm,
                          status="awaiting_payment", total=_money(total_val))
        order["items"] = items
        success = (config.PUBLIC_BASE_URL + "/swag/pay/return?oid=" + oid
                   + "&session_id={CHECKOUT_SESSION_ID}")
        cancel = config.PUBLIC_BASE_URL + "/swag/pay/cancel?oid=" + oid
        url, ref = stripe_pay.create_checkout_session(order, success, cancel)
        if not url:
            return {"store": "Swag & Apparel", "order_id": oid, "status": "error",
                    "note": "Card checkout is temporarily unavailable."}
        order["stripe_session_id"] = ref
        _save_pending(order); _log(order)
        return {"store": "Swag & Apparel", "order_id": oid, "status": "awaiting_payment",
                "checkout_url": url, "total": _money(total_val)}
    order = _mk_order("Swag & Apparel", oid, u, "personal", units, lines, ctx, ship, nm,
                      status="placed", total=_money(total_val))
    order["items"] = items
    _fulfill_swag(order); _log(order)
    return {"store": "Swag & Apparel", "order_id": oid, "status": "placed",
            "total": _money(total_val), "paid": "personal",
            "note": "Placed on your personal card - NOT reimbursable."}


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
    # Accrue the approved spend against the requester's SWAG budget. Only FSEs
    # have a budget, and only swag draws on it — print orders don't.
    if (o.get("payment") == "company" and o.get("_total_usd") and o.get("items")
            and budget.budget_for(o.get("role")) is not None):
        budget.add_spend(o.get("orderer_email", ""), o.get("_total_usd"))
    gstatus, gid = "", ""
    if o.get("print_lines"):                       # business cards / documents
        gstatus, _res, gid = _place_print_lines(o)
    if o.get("items"):                             # swag
        _fulfill_swag(o)
    _send_receipt(o)
    _save_pending(o)
    _log(o, gstatus, gid)
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


@app.route("/admin/budget")
def admin_budget():
    """Diagnostic: confirm WHERE budgets persist on the live server + that the
    location is writable (i.e. the persistent disk is mounted). Token-gated.
    Reports paths/counts only; pass &detail=1 to include per-user spend."""
    if request.args.get("token") != os.environ.get("ADMIN_TOKEN", "mms-discover"):
        abort(403)
    import budget
    store = budget.STORE
    d = os.path.dirname(store) or "."
    writable, probe_error = False, ""
    try:                                          # prove the live filesystem is writable
        os.makedirs(d, exist_ok=True)
        probe = os.path.join(d, ".probe")
        with open(probe, "w") as f:
            f.write("ok")
        os.remove(probe)
        writable = True
    except Exception as e:
        probe_error = str(e)
    data = budget._load()
    on_disk = config.DATA_DIR not in (config.FILES_DIR,) and not store.replace("\\", "/").endswith("files/budgets.json")
    out = {"data_dir": config.DATA_DIR, "budget_store": store,
           "store_dir_writable": writable, "probe_error": probe_error,
           "store_file_exists": os.path.exists(store),
           "looks_persistent": bool(on_disk),
           "current_period": budget.period_key(), "resets": budget.reset_human(),
           "users_tracked": len(data),
           "fse_budget": config.FSE_BUDGET_USD, "employee_budget": config.EMPLOYEE_BUDGET_USD}
    if request.args.get("detail") == "1":
        out["spend"] = data                        # per-email → period → $ (sensitive)
    return jsonify(**out)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    print("MMS Material Ordering Hub | mode=%s | auth=%s | base=%s"
          % (config.GELATO_MODE, config.AUTH_ENABLED, config.PUBLIC_BASE_URL))
    app.run(host="0.0.0.0", port=port, debug=False)
