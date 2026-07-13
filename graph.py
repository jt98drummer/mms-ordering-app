"""
Microsoft Graph helpers (app-only / client-credentials):
  - send_mail():        receipts + approval requests (needs application Mail.Send)
  - get_manager_email(): resolve a user's manager (needs application User.Read.All)
When Graph is unavailable, emails are written to files/outbox/ so nothing is lost.
"""
import os, json, time, datetime
import config

try:
    import msal, requests
except Exception:
    msal, requests = None, None

_cache = {"tok": None, "exp": 0}


def _app_token():
    if not (msal and requests and config.AUTH_ENABLED):
        return None
    if _cache["tok"] and _cache["exp"] > time.time() + 60:
        return _cache["tok"]
    app = msal.ConfidentialClientApplication(
        config.MS_CLIENT_ID, authority=config.MS_AUTHORITY,
        client_credential=config.MS_CLIENT_SECRET)
    res = app.acquire_token_for_client(scopes=["https://graph.microsoft.com/.default"])
    if "access_token" in res:
        _cache["tok"] = res["access_token"]
        _cache["exp"] = time.time() + int(res.get("expires_in", 3600))
        return _cache["tok"]
    return None


def _save_outbox(subject, html, to, cc=None):
    os.makedirs(config.OUTBOX_DIR, exist_ok=True)
    fn = os.path.join(config.OUTBOX_DIR,
                      "%s-%04d.html" % (datetime.datetime.now().strftime("%Y%m%d-%H%M%S"),
                                        abs(hash(subject)) % 10000))
    with open(fn, "w") as f:
        f.write("<!-- TO: %s | CC: %s -->\n<!-- SUBJECT: %s -->\n%s"
                % (", ".join(to), ", ".join(cc or []), subject, html))
    return fn


def send_mail(subject, html, to, cc=None, bcc=None, sender=None):
    """Returns (sent: bool, detail). Falls back to outbox file when Graph unavailable."""
    to = [t for t in (to or []) if t]
    cc = [c for c in (cc or []) if c]
    bcc = [b for b in (bcc or []) if b]
    sender = sender or config.MAIL_SENDER
    tok = _app_token() if config.MAIL_MODE in ("auto", "send") else None
    if not tok:
        return False, _save_outbox(subject, html, to, cc)
    payload = {"message": {
        "subject": subject,
        "body": {"contentType": "HTML", "content": html},
        "toRecipients": [{"emailAddress": {"address": a}} for a in to],
        "ccRecipients": [{"emailAddress": {"address": a}} for a in cc],
        "bccRecipients": [{"emailAddress": {"address": a}} for a in bcc],
    }, "saveToSentItems": True}
    try:
        r = requests.post("%s/users/%s/sendMail" % (config.GRAPH_BASE, sender),
                          headers={"Authorization": "Bearer " + tok,
                                   "Content-Type": "application/json"},
                          data=json.dumps(payload), timeout=30)
        if r.status_code in (200, 202):
            return True, "sent"
        return False, _save_outbox("%s [graph %s]" % (subject, r.status_code), html, to, cc)
    except Exception as e:
        return False, _save_outbox("%s [err %s]" % (subject, e), html, to, cc)


def get_manager_email(user):
    tok = _app_token()
    if not (tok and user):
        return ""
    try:
        r = requests.get("%s/users/%s/manager" % (config.GRAPH_BASE, user),
                         headers={"Authorization": "Bearer " + tok}, timeout=20)
        if r.status_code == 200:
            d = r.json()
            return d.get("mail") or d.get("userPrincipalName") or ""
    except Exception:
        pass
    return ""


def diag():
    """Diagnostic: verify app-only credentials (client secret) + sender mailbox.
    Returns booleans / HTTP status only - never a token or secret."""
    d = {"app_token_ok": False, "sender": config.MAIL_SENDER, "sender_status": None}
    tok = _app_token()
    d["app_token_ok"] = bool(tok)
    if tok and requests:
        try:
            r = requests.get("%s/users/%s" % (config.GRAPH_BASE, config.MAIL_SENDER),
                             headers={"Authorization": "Bearer " + tok}, timeout=20)
            d["sender_status"] = r.status_code
        except Exception as e:
            d["sender_status"] = "err: %s" % e
    return d


def log_to_sharepoint(order):
    """Mirror an order to a SharePoint list (durable audit log). No-op unless SP_ENABLED."""
    if not (config.SP_ENABLED and requests):
        return False, "sp-disabled"
    tok = _app_token()
    if not tok:
        return False, "no-token"
    fields = {
        "Title": order.get("oid", ""), "Store": order.get("store", ""),
        "Orderer": order.get("orderer", ""), "Email": order.get("orderer_email", ""),
        "Role": order.get("role", ""), "Payment": order.get("payment", ""),
        "Qty": order.get("qty", 0), "Amount": str(order.get("total", "")),
        "Purpose": order.get("purpose", ""), "ForWhom": order.get("recipient_ctx", ""),
        "Justification": order.get("justification", ""), "Status": order.get("status", ""),
        "Approver": order.get("approver", ""),
    }
    try:
        r = requests.post(
            "%s/sites/%s/lists/%s/items" % (config.GRAPH_BASE, config.SP_SITE_ID, config.SP_LIST_ID),
            headers={"Authorization": "Bearer " + tok, "Content-Type": "application/json"},
            data=json.dumps({"fields": fields}), timeout=25)
        return (r.status_code in (200, 201)), ("sp %s" % r.status_code)
    except Exception as e:
        return False, "sp-err: %s" % e
