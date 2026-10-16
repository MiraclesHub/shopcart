# Shopcart — Full-Stack E-Commerce Replica

A complete e-commerce build: replica storefront + production-grade
cart/stock management + pluggable payments (cards, bank transfer, crypto,
pay-on-delivery) + printable receipts.

## Run

```bash
cd server
python3 app.py            # http://localhost:8080
```

The storefront auto-seeds a SQLite database (products/orders) on first boot
at `server/shopcart.db`. All product photos in `assets/img/` were generated
for this project.

## Architecture

```
index.html / product.html / cart.html / checkout.html   ← storefront pages
assets/js/app.js                                        ← shared UI + cart client
assets/js/checkout.js                                   ← payment orchestrator
server/app.py                                           ← Flask API + receipt page
server/catalog.py                                       ← names/prices (server-trusted)
server/db.py                                            ← SQLite: stock, reservations, orders
server/payments.py                                      ← Paystack + demo gateway + webhooks
server/config.py                                        ← env-driven config (no secrets in git)
```

### Money & stock rules (server-enforced)

- Prices/totals are **only** computed on the server from `catalog.py` — the
  browser sends `{id, qty}` and nothing else (`price` fields are ignored).
- Ordering **reserves** stock atomically (`stock - reserved >= qty`), so an
  item can never be oversold; reservations expire after 30 minutes unpaid.
- Payment confirmation **fulfils** the order inside one transaction and is
  **idempotent** on the payment reference (replays can't double-decrement).
- Declined/cancelled payments release the reservation automatically.
- Coupons are validated server-side (`SHOP10` = 10%).

## Payments

Ships in **demo mode**: a local sandbox that mirrors the real
initialize → pay → verify lifecycle end-to-end (clearly labelled in the UI;
no real charge). To accept real payments, flip the env:

```bash
export PAYMENTS_MODE=paystack
export PAYSTACK_SECRET_KEY=sk_live_xxx      # also test keys work
export PAYSTACK_PUBLIC_KEY=pk_live_xxx
python3 app.py
```

Then register the webhook in your Paystack dashboard:
`https://<your-domain>/api/payments/webhook` — its HMAC-SHA512 signature is
verified before anything is marked paid. With Paystack enabled, card entry
happens inside Paystack's PCI-DSS hosted popup, so **raw card data never
touches this site**. The UI still performs live card-network detection
(Visa / Mastercard / **Verve** / Amex / Discover / UnionPay / JCB) and Luhn
validation for the best UX before redirecting.

Demo-mode test cards: any Luhn-valid number approves; ending `0002`
= declined, `0000` = insufficient funds. The demo card form tokenises
(SHA-256) and transmits only `{network, last4, token}` — never PAN/CVV.

- **Bank transfer** issues a dedicated account number + payment reference;
  confirmation is reconciled to the order (demo button ≙ bank webhook).
- **Crypto** (USDT-TRC20 / BTC) issues a deterministic deposit address +
  memo per order; confirmation records the tx hash (demo ≙
  Coinbase-Commerce/BitPay webhook — swap in `payments.py`).
- **Pay on Delivery** places the order as `placed` and converts stock
  immediately; payment is collected at the doorstep.

Every successful payment: order marked `paid`, purchased items cleared from
the cart, and an HMAC-tokenised receipt URL is issued at
`/receipt/<order>?t=<token>` (print / Save-as-PDF ready).

## Responsive

Mobile-first breakpoints at 1080px (tablet), 860px (drawer nav, stacked
hero/PDP/checkout) and 640px (phone). Grids reflow 4→3→2 columns.

## Going fully live checklist

1. Set the three env vars above (use `sk_test_*`/`pk_test_*` to rehearse).
2. Serve behind a production WSGI server (`gunicorn -w2 app:app`) + HTTPS.
3. Point Paystack's dashboard webhook at your HTTPS domain.
4. For crypto, replace the demo confirm endpoint with a
   Coinbase-Commerce/BitPay webhook handler (same order-fulfil hooks).
5. Rotate `SHOPCART_SECRET` (signs receipt URLs) per environment.
