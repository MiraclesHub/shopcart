"""
Shopcart — Flask application.
=============================
Serves the storefront (static files) plus the JSON API that powers
stock, cart validation, orders, payments and receipts.

API surface
    GET  /api/config                public runtime config (mode, public key)
    GET  /api/catalog               products + live availability
    POST /api/cart/validate         repair a client cart against live stock
    POST /api/orders                create PENDING order (reserves stock)
    POST /api/payments/init         method-specific payment instructions
    POST /api/payments/demo-card-pay     DEMO card settlement
    POST /api/payments/manual-confirm    DEMO bank/crypto confirmation
    POST /api/payments/cancel       user aborted -> release reservation
    GET  /api/payments/verify/<ref> authoritative payment/order status
    POST /api/payments/webhook      Paystack webhook (HMAC verified)
    GET  /api/orders/<id>           order JSON (requires receipt token)
    GET  /receipt/<id>              printable invoice (requires token)

Money & stock are ONLY ever computed here; the browser is just a renderer.
"""
import json, os, re, time

from flask import Flask, jsonify, request, send_from_directory, render_template_string

import config
import db
import payments
from catalog import CATALOG, VALID_NETWORKS

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # shopcart/
app = Flask(__name__, static_folder=ROOT, static_url_path="")

db.init_db()


# ---------------------------------------------------------------------------
# Security headers for every response
# ---------------------------------------------------------------------------

@app.after_request
def secure_headers(resp):
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "SAMEORIGIN"
    resp.headers["Referrer-Policy"] = "same-origin"
    return resp


def bad(msg, code=400):
    return jsonify({"error": msg}), code


# ---------------------------------------------------------------------------
# Storefront pages (static)
# ---------------------------------------------------------------------------

@app.get("/")
def home():
    return send_from_directory(ROOT, "index.html")


# ---------------------------------------------------------------------------
# Config & catalog
# ---------------------------------------------------------------------------

@app.get("/api/config")
def api_config():
    return jsonify({
        "mode": config.MODE,
        "currency": config.CURRENCY,
        "paystackPublicKey": config.PAYSTACK_PUBLIC_KEY if config.MODE == "paystack" else "",
        "cryptoAssets": ["USDT", "BTC"],
        "methods": ["card", "bank", "crypto", "pod"],
    })


@app.get("/api/catalog")
def api_catalog():
    db.sweep_expired()                       # release stale pending reservations
    avail = db.get_availability()
    return jsonify({pid: {**p, "available": avail.get(pid, 0)}
                    for pid, p in CATALOG.items()})


# ---------------------------------------------------------------------------
# Cart validation (repairs qty>stock, stale prices, unknown ids)
# ---------------------------------------------------------------------------

@app.post("/api/cart/validate")
def api_cart_validate():
    body = request.get_json(silent=True) or {}
    lines = body.get("lines", [])[:50]
    avail = db.get_availability()
    clean, warnings = [], []
    subtotal = 0.0
    for l in lines:
        pid = str(l.get("id", ""))
        qty = max(0, int(l.get("qty", 0) or 0))
        if pid not in CATALOG:
            warnings.append(f"Removed an unavailable product.")
            continue
        stock = avail.get(pid, 0)
        if stock == 0:
            warnings.append(f"'{CATALOG[pid]['name']}' is out of stock.")
            continue
        if qty > stock:
            warnings.append(f"Only {stock} × '{CATALOG[pid]['name']}' available — quantity adjusted.")
            qty = stock
        if qty > 0:
            clean.append({"id": pid, "qty": qty})
            subtotal += CATALOG[pid]["price"] * qty
    coupon = (body.get("coupon") or "").upper()
    discount = round(subtotal * config.COUPONS.get(coupon, 0), 2)
    return jsonify({"lines": clean, "warnings": warnings,
                    "subtotal": round(subtotal, 2), "discount": discount,
                    "total": round(subtotal - discount, 2)})


# ---------------------------------------------------------------------------
# Orders
# ---------------------------------------------------------------------------

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@app.post("/api/orders")
def api_orders_create():
    body = request.get_json(silent=True) or {}
    email = (body.get("email") or "").strip()[:120]
    if not EMAIL_RE.match(email):
        return bad("A valid email address is required for your receipt.")
    method = (body.get("method") or "card").lower()
    if method not in ("card", "bank", "crypto", "pod"):
        return bad("Unknown payment method.")
    try:
        order = db.create_order(body.get("lines", []), email,
                                body.get("coupon"), method)
    except (ValueError, TypeError):
        return bad("Your cart could not be processed. Please review it.")
    if order is None:
        return bad("Some items are no longer available in that quantity.", 409)
    if method == "pod":
        # Pay on delivery: stock converts to sale immediately, order marked
        # 'placed' (payment collected at the doorstep).
        order = db.mark_paid(order["id"], {"method": "pod", "email": email})
    return jsonify(public_order(order))


def public_order(o):
    """Order shape exposed to the browser (no internals beyond safe fields)."""
    return {"id": o["id"], "reference": o["reference"], "email": o["email"],
            "lines": json.loads(o["lines"]), "coupon": o["coupon"],
            "subtotal": o["subtotal"], "discount": o["discount"],
            "total": o["total"], "currency": o["currency"],
            "status": o["status"], "method": o["method"],
            "payer": json.loads(o["payer"] or "{}"),
            "created": o["created"], "paid": o["paid"],
            "receiptUrl": f"/receipt/{o['id']}?t={o['receipt_token']}"}


@app.post("/api/payments/init")
def api_pay_init():
    body = request.get_json(silent=True) or {}
    order = db.get_order(str(body.get("orderId", "")))
    if not order:
        return bad("Unknown order.", 404)
    if order["status"] != "pending":
        return bad("Order is no longer payable.", 409)
    payload = payments.initialize(order, order["method"],
                                  order["email"], body)
    if "error" in payload:
        return bad(payload["error"], 502)
    return jsonify(payload)


@app.post("/api/payments/demo-card-pay")
def api_demo_card_pay():
    """DEMO gateway settlement. Accepts ONLY card metadata — the full card
    number and CVC must never be sent (see tokenisation in checkout.js)."""
    if config.MODE != "demo":
        return bad("Demo gateway disabled in paystack mode.", 403)
    body = request.get_json(silent=True) or {}
    network = (body.get("network") or "").lower()
    last4 = re.sub(r"\D", "", str(body.get("last4", "")))[-4:]
    token = str(body.get("token", ""))
    if network not in VALID_NETWORKS or len(last4) != 4:
        return bad("Invalid card metadata.")
    if not re.fullmatch(r"[0-9a-f]{64}", token):
        return bad("Invalid payment token.")
    order, status, msg = payments.demo_card_pay(
        str(body.get("reference", "")), network, last4,
        str(body.get("email", ""))[:120])
    if not order:
        return bad(msg, 404)
    return jsonify({"status": status, "message": msg, "order": public_order(order)})


@app.post("/api/payments/manual-confirm")
def api_manual_confirm():
    """DEMO: confirm a bank transfer or crypto deposit (production: provider
    webhook performs this). Provided tx detail is stored as safe metadata."""
    if config.MODE != "demo":
        return bad("Manual confirmation disabled in paystack mode.", 403)
    body = request.get_json(silent=True) or {}
    kind = (body.get("kind") or "")[:12]
    detail = {k: str(v)[:120] for k, v in (body.get("detail") or {}).items()}
    order, status = payments.confirm_manual(str(body.get("reference", "")), kind, detail)
    if not order:
        return bad("Unknown reference.", 404)
    return jsonify({"status": status, "order": public_order(order)})


@app.post("/api/payments/cancel")
def api_pay_cancel():
    body = request.get_json(silent=True) or {}
    order = db.get_order(str(body.get("orderId", "")))
    if order:
        db.cancel_pending(order["id"])
    return jsonify({"ok": True})


@app.get("/api/payments/verify/<ref>")
def api_verify(ref):
    order, status = payments.verify(ref)
    if not order:
        return bad("Unknown reference.", 404)
    return jsonify({"status": status, "order": public_order(order)})


@app.post("/api/payments/webhook")
def api_webhook():
    ok = payments.handle_paystack_webhook(
        request.get_data(), request.headers.get("x-paystack-signature", ""))
    return ("", 200) if ok else ("", 401)


@app.get("/api/orders/<oid>")
def api_order_get(oid):
    order = db.get_order(oid)
    if not order or request.args.get("t") != order["receipt_token"]:
        return bad("Not found.", 404)
    return jsonify(public_order(order))


# ---------------------------------------------------------------------------
# Printable receipt / invoice
# ---------------------------------------------------------------------------

RECEIPT_HTML = """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Receipt {{o.id}} — Shopcart</title>
<style>
  :root{--green:#003D29;--line:#E6E8EA;--muted:#5F6C72;--star:#0AAD0A;--text:#231F1E}
  *{margin:0;padding:0;box-sizing:border-box}
  body{font-family:"Inter",-apple-system,"Segoe UI",Roboto,Arial,sans-serif;color:var(--text);
       background:#F2F4F3;padding:40px 16px;font-size:14px}
  .sheet{max-width:720px;margin:0 auto;background:#fff;border-radius:18px;
         box-shadow:0 10px 40px rgba(0,61,41,.08);overflow:hidden}
  .head{background:var(--green);color:#fff;padding:30px 36px;display:flex;
        justify-content:space-between;align-items:center}
  .head h1{font-size:22px;letter-spacing:-.4px}
  .head .logo{font-weight:800;font-size:20px}
  .stamp{display:inline-block;border:2.5px solid var(--star);color:var(--star);
         font-weight:800;letter-spacing:2px;padding:6px 16px;border-radius:8px;
         transform:rotate(-4deg);font-size:15px}
  .body{padding:32px 36px}
  .meta{display:flex;justify-content:space-between;gap:24px;flex-wrap:wrap;margin-bottom:26px}
  .meta .lbl{font-size:11px;text-transform:uppercase;letter-spacing:1px;color:var(--muted)}
  .meta .val{font-weight:600;margin-top:3px}
  table{width:100%;border-collapse:collapse;margin:8px 0 22px}
  th{font-size:11px;text-transform:uppercase;letter-spacing:1px;color:var(--muted);
     text-align:left;padding:10px 8px;border-bottom:2px solid var(--line)}
  td{padding:13px 8px;border-bottom:1px solid var(--line);vertical-align:top}
  td.name{font-weight:600}
  td small{display:block;color:var(--muted);font-weight:400;margin-top:2px}
  td.num,th.num{text-align:right}
  .totals{margin-left:auto;max-width:280px}
  .trow{display:flex;justify-content:space-between;padding:6px 0;color:var(--muted)}
  .trow b{color:var(--text)}
  .trow.disc b{color:var(--star)}
  .trow.grand{border-top:2px solid var(--text);margin-top:8px;padding-top:12px;
              font-size:17px;color:var(--text);font-weight:800}
  .pay{background:#F5F6F6;border-radius:12px;padding:16px 18px;margin-top:24px;
       font-size:13px}
  .pay b{font-weight:700}
  .foot{text-align:center;color:var(--muted);font-size:12px;padding:22px 36px 30px}
  .actions{max-width:720px;margin:18px auto 0;display:flex;gap:12px;justify-content:center}
  .actions button,.actions a{cursor:pointer;border:none;font-weight:600;font-size:14px;
       padding:13px 28px;border-radius:999px;text-decoration:none;display:inline-block}
  .p1{background:var(--green);color:#fff}
  .p2{background:#fff;color:var(--text);border:1.5px solid var(--line)}
  @media print{ body{background:#fff;padding:0} .sheet{box-shadow:none;border-radius:0}
                .actions{display:none} }
</style></head><body>
<div class="actions">
  <button class="p1" onclick="window.print()">Print / Save as PDF</button>
  <a class="p2" href="/">Back to store</a>
</div>
<div class="sheet" style="margin-top:18px">
  <div class="head">
    <div><div class="logo">🛒 Shopcart</div><div style="opacity:.7;font-size:12px;margin-top:4px">Official Payment Receipt</div></div>
    <div class="stamp">{{ 'PAID' if o.status=='paid' else o.status.upper() }}</div>
  </div>
  <div class="body">
    <div class="meta">
      <div><div class="lbl">Receipt No.</div><div class="val">{{o.id}}</div></div>
      <div><div class="lbl">Payment Ref.</div><div class="val">{{o.reference}}</div></div>
      <div><div class="lbl">Date</div><div class="val">{{date}}</div></div>
      <div><div class="lbl">Billed To</div><div class="val">{{o.email}}</div></div>
    </div>
    <table>
      <thead><tr><th>Item</th><th class="num">Unit</th><th class="num">Qty</th><th class="num">Amount</th></tr></thead>
      <tbody>
      {% for l in o.lines %}
        <tr><td class="name">{{l.name}}<small>Colour: {{l.colour}}</small></td>
            <td class="num">${{'%.2f'|format(l.price)}}</td>
            <td class="num">{{'%02d'|format(l.qty)}}</td>
            <td class="num"><b>${{'%.2f'|format(l.price*l.qty)}}</b></td></tr>
      {% endfor %}
      </tbody>
    </table>
    <div class="totals">
      <div class="trow"><span>Subtotal</span><b>${{'%.2f'|format(o.subtotal)}}</b></div>
      {% if o.discount %}<div class="trow disc"><span>Discount ({{o.coupon}})</span><b>−${{'%.2f'|format(o.discount)}}</b></div>{% endif %}
      <div class="trow"><span>Shipping</span><b style="color:var(--star)">Free</b></div>
      <div class="trow grand"><span>Total Paid</span><span>${{'%.2f'|format(o.total)}} {{o.currency}}</span></div>
    </div>
    <div class="pay"><b>Payment method:</b> {{method_line}}</div>
  </div>
  <div class="foot">Thank you for shopping with Shopcart · support@shopcart.com · +001234567890<br>
  This is a computer-generated receipt and does not require a signature.</div>
</div>
</body></html>"""


@app.get("/receipt/<oid>")
def receipt(oid):
    order = db.get_order(oid)
    if not order or request.args.get("t") != order["receipt_token"]:
        return bad("Receipt not found.", 404)
    order["lines"] = json.loads(order["lines"])
    payer = json.loads(order["payer"] or "{}")
    if order["method"] == "card":
        method_line = (f"{payer.get('network','card').title()} card "
                       f"ending •••• {payer.get('last4','----')}")
    elif order["method"] == "bank":
        method_line = f"Bank transfer (ref {payer.get('sender','—')})"
    elif order["method"] == "crypto":
        method_line = f"Crypto — {payer.get('asset','USDT')} · tx {str(payer.get('txhash','—'))[:20]}…"
    else:
        method_line = "Pay on delivery"
    date = time.strftime("%d %b %Y, %H:%M",
                         time.localtime(order.get("paid") or order["created"]))
    return render_template_string(RECEIPT_HTML, o=order,
                                  method_line=method_line, date=date)


if __name__ == "__main__":
    print(f"Shopcart server ({config.MODE} payments) on http://{config.HOST}:{config.PORT}")
    app.run(host=config.HOST, port=config.PORT, debug=False)
