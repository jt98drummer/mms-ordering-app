"""
Stripe helper for the personal-card swag checkout.

Design goals (money is involved, so keep it boring and safe):
  - Uses Stripe **Checkout** (Stripe-hosted page) so no card data ever touches
    this app. We only ever hold a session id / payment-intent id.
  - Fulfillment happens ONLY after Stripe confirms payment. Two independent
    confirmations both funnel through app._finalize_paid() (which is idempotent):
      1. the checkout.session.completed webhook (primary), and
      2. a server-side session re-fetch on the success redirect (fallback, in
         case the webhook is delayed or the user's browser was the only signal).
  - No-op friendly: every entry point degrades to a harmless value when Stripe
    is not configured (STRIPE_SECRET_KEY unset), so the app still boots and the
    personal-card path falls back to its demo behavior.

Test vs live is decided by the key itself (sk_test_... vs sk_live_...); there is
no separate mode flag like Gelato/Printful have.
"""
import config

try:
    import stripe
except Exception:                     # library not installed -> feature simply off
    stripe = None


def enabled():
    """True only when the library is importable AND a secret key is configured."""
    return bool(stripe and config.STRIPE_ENABLED)


def _client():
    stripe.api_key = config.STRIPE_SECRET_KEY
    return stripe


def _line_items(order):
    """Build Stripe Checkout line_items from the raw swag items on the order.
    Skips any zero-priced line (Stripe rejects $0 line items)."""
    out = []
    for i in order.get("items", []):
        cents = int(round(float(i.get("price", 0) or 0) * 100))
        if cents <= 0:
            continue
        pd = {"name": (i.get("name") or "MMS item")[:250]}
        detail = " / ".join(x for x in (i.get("color", ""), i.get("size", "")) if x)
        if detail:
            pd["description"] = detail[:250]
        out.append({
            "price_data": {
                "currency": config.CURRENCY.lower(),
                "product_data": pd,
                "unit_amount": cents,
            },
            "quantity": max(1, int(i.get("qty", 1))),
        })
    return out


def create_checkout_session(order, success_url, cancel_url):
    """Create a hosted Checkout session for a personal-card order.
    Returns (checkout_url, session_id) on success, or (None, reason) on failure.
    The oid rides along in both client_reference_id and metadata so the webhook
    and the success redirect can find the pending order again."""
    if not enabled():
        return None, "stripe-disabled"
    items = _line_items(order)
    if not items:
        return None, "no-billable-items"
    oid = order.get("oid", "")
    try:
        sess = _client().checkout.Session.create(
            mode="payment",
            line_items=items,
            success_url=success_url,
            cancel_url=cancel_url,
            client_reference_id=oid,
            customer_email=(order.get("orderer_email") or None),
            metadata={"oid": oid, "orderer_email": order.get("orderer_email", ""),
                      "store": order.get("store", "Swag & Apparel")},
            payment_intent_data={
                "description": "MMS swag (personal card) %s" % oid,
                "metadata": {"oid": oid},
            },
        )
        return sess.url, sess.id
    except Exception as e:                                   # network / config / API error
        return None, "stripe-error: %s" % e


def verify_webhook(payload, sig_header):
    """Return the verified Stripe event, or None if it can't be trusted.
    Requires STRIPE_WEBHOOK_SECRET and a valid signature on the raw body."""
    if not (stripe and config.STRIPE_WEBHOOK_SECRET and sig_header):
        return None
    try:
        return stripe.Webhook.construct_event(payload, sig_header, config.STRIPE_WEBHOOK_SECRET)
    except Exception:                                        # bad signature / malformed payload
        return None


def retrieve_session(session_id):
    """Fetch a Checkout session straight from Stripe (source of truth). None on failure."""
    if not (enabled() and session_id):
        return None
    try:
        return _client().checkout.Session.retrieve(session_id)
    except Exception:
        return None


def is_paid(session):
    """True when a Checkout session represents a completed, paid order."""
    try:
        return session.get("payment_status") == "paid" or session.get("status") == "complete"
    except Exception:
        return False
