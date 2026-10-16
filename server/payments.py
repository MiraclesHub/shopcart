"""
Shopcart — payments layer.
==========================
Provider-pluggable design. Two interchangeable gateways:

  PAYSTACK (production)  – card charge happens entirely on Paystack's PCI-DSS
                           certified hosted page, so raw card data NEVER
                           touches our site. We only ever see the transaction
                           reference, which we verify server-to-server.
  DEMO (local sandbox)   – mirrors the exact same initialize -> verify ->
                           paid lifecycle locally so the full order pipeline
                           (stock reservation, fulfilment, receipts) can be
                           exercised without keys. Clearly labelled in the UI.

Also supported: bank transfer (issues a dedicated payment reference that is
confirmed via webhook/manual confirmation) and crypto (issues a deposit
address + memo; in production a Coinbase-Commerce/BitPay webhook confirms).

SECURITY RULES ENFORCED HERE
  * Amounts are ALWAYS taken from the server-side order, never the request.
  * Verification matches reference AND amount before marking paid.
  * Webhook authenticity is proven with the provider's HMAC signature.
  * Card payloads carry only {network, last4, token} — full PAN/CVV must
    never reach this server (see checkout.js tokenisation comments).
  * Fulfilment (stock decrement) is idempotent on the order reference.
"""
import json, time, hashlib, hmac, urllib.request, urllib.error

import config
import db


# ---------------------------------------------------------------------------
# Paystack REST helper
# ---------------------------------------------------------------------------

def _paystack_call(path, payload=None):
    """Minimal JSON client for Paystack (stdlib only)."""
    req = urllib.request.Request(
        config.PAYSTACK_API + path,
        data=None if payload is None else json.dumps(payload).encode(),
        headers={"Authorization": f"Bearer {config.PAYSTACK_SECRET_KEY}",
                 "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return {"status": False, "message": f"gateway error {e.code}"}
    except Exception as e:
        return {"status": False, "message": str(e)}


# ---------------------------------------------------------------------------
# Initialise a payment for a pending order
# ---------------------------------------------------------------------------

def initialize(order, method, email, extra):
    """
    Return a method-specific instruction payload for the frontend.
    `extra` may contain e.g. the chosen crypto asset — never prices.
    """
    ref = order["reference"]
    amount_minor = int(round(order["total"] * 100))  # kobo/cents

    if method == "card" and config.MODE == "paystack":
        r = _paystack_call("/transaction/initialize", {
            "email": email, "amount": amount_minor, "reference": ref,
            "currency": config.CURRENCY,
            "callback_url": f"/checkout.html?ref={ref}",
            "metadata": {"order_id": order["id"], "custom_fields": []}})
        if not r.get("status"):
            return {"error": r.get("message", "could not initialise payment")}
        d = r["data"]
        return {"gateway": "paystack", "reference": ref,
                "publicKey": config.PAYSTACK_PUBLIC_KEY,
                "authorizationUrl": d.get("authorization_url"),
                "accessCode": d.get("access_code")}

    if method == "card":
        # DEMO gateway: card entry + tokenisation happen client-side; the
        # browser then posts only {network, last4, token} to /demo-card-pay.
        return {"gateway": "demo", "reference": ref,
                "amount": order["total"], "currency": order["currency"]}

    if method == "bank":
        # Dedicated transfer reference derived deterministically from the
        # order reference (production: provider assigns a virtual account).
        acct = "9" + hashlib.sha256(ref.encode()).hexdigest()[:9]
        return {"gateway": "bank", "reference": ref, "account": acct,
                "bank": "Shopcart Demo Bank", "amount": order["total"],
                "currency": order["currency"]}

    if method == "crypto":
        asset = (extra or {}).get("asset", "USDT")
        addr = ("0x" if asset != "BTC" else "tb1q") + \
               hmac.new(config.SECRET.encode(),
                        (ref + asset).encode(), hashlib.sha256).hexdigest()[:34]
        return {"gateway": "crypto", "reference": ref, "asset": asset,
                "address": addr, "network": "TRC20" if asset == "USDT" else "Bitcoin",
                "amount": order["total"], "currency": order["currency"]}

    if method == "pod":
        return {"gateway": "pod", "reference": ref}

    return {"error": "unknown payment method"}


# ---------------------------------------------------------------------------
# Verification / confirmation
# ---------------------------------------------------------------------------

def verify(reference):
    """
    Unified verify used by the UI's success screen.
    Returns (order_dict, payment_status) where payment_status is
    'paid' | 'pending' | 'failed'.
    """
    order = db.get_order_by_ref(reference)
    if not order:
        return None, "failed"
    if order["status"] in ("paid", "placed"):
        return order, "paid"          # idempotent replay
    if order["status"] in ("cancelled", "failed"):
        return order, "failed"

    if config.MODE == "paystack" and order["method"] == "card":
        r = _paystack_call(f"/transaction/verify/{reference}")
        ok = (r.get("status") and r["data"]["status"] == "success"
              and int(r["data"]["amount"]) == int(round(order["total"] * 100)))
        if ok:
            d = r["data"]
            auth = d.get("authorization", {})
            payer = {"network": auth.get("card_type", "card"),
                     "last4": auth.get("last4", "----"),
                     "bank": auth.get("bank", "")}
            return db.mark_paid(order["id"], payer), "paid"
        if r.get("status") and r["data"].get("status") in ("failed", "abandoned"):
            return db.mark_failed(order["id"]), "failed"
        return order, "pending"

    return order, "pending"  # demo flows confirm through their own endpoints


def demo_card_pay(reference, network, last4, email):
    """
    DEMO-ONLY card settlement. Receives card metadata (network + last4) —
    never the full number. Deterministic outcomes so declines can be tested:
        last4 0002 -> card declined | last4 0000 -> insufficient funds
    """
    order = db.get_order_by_ref(reference)
    if not order or order["status"] != "pending":
        return order, ("paid" if order and order["status"] in ("paid", "placed")
                       else "failed"), "Order is no longer payable."
    if last4 == "0002":
        return db.mark_failed(order["id"]), "failed", "Your card was declined."
    if last4 == "0000":
        return db.mark_failed(order["id"]), "failed", "Insufficient funds."
    payer = {"network": network, "last4": last4, "email": email}
    time.sleep(0)  # hook point for latency simulation
    return db.mark_paid(order["id"], payer), "paid", "Payment approved."


def confirm_manual(reference, kind, detail):
    """
    DEMO confirmations for bank transfer & crypto. In production these are
    replaced by signed provider webhooks (bank) or chain watchers (crypto).
    """
    order = db.get_order_by_ref(reference)
    if not order:
        return None, "failed"
    payer = {"method": kind, **detail}
    return db.mark_paid(order["id"], payer), "paid"


# ---------------------------------------------------------------------------
# Paystack webhook
# ---------------------------------------------------------------------------

def verify_webhook_signature(raw_body, signature):
    """HMAC-SHA512 as published in Paystack's docs — proves the sender."""
    mac = hmac.new(config.PAYSTACK_SECRET_KEY.encode(), raw_body, hashlib.sha512)
    return hmac.compare_digest(mac.hexdigest(), (signature or "").lower())


def handle_paystack_webhook(raw_body, signature):
    """charge.success -> mark paid (idempotent; also covers abandoned UIs)."""
    if config.MODE != "paystack" or not verify_webhook_signature(raw_body, signature):
        return False
    try:
        event = json.loads(raw_body.decode())
    except Exception:
        return False
    if event.get("event") == "charge.success":
        ref = event["data"]["reference"]
        order = db.get_order_by_ref(ref)
        if order and int(event["data"]["amount"]) == int(round(order["total"] * 100)):
            auth = event["data"].get("authorization", {})
            db.mark_paid(order["id"], {"network": auth.get("card_type", "card"),
                                       "last4": auth.get("last4", "----")})
    return True
