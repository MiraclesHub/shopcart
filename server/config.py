"""
Shopcart — server configuration.
=================================
All sensitive values come from environment variables so no secrets
ever live in source control.

Payment modes
-------------
    PAYMENTS_MODE=paystack   -> live/test charges via the Paystack API
    PAYMENTS_MODE=demo       -> fully local sandbox that mirrors the same
                                initialize -> verify -> paid lifecycle
                                (clearly labelled in the UI; no real money)

To go live with Paystack (recommended — PCI-DSS handled by them):
    export PAYMENTS_MODE=paystack
    export PAYSTACK_SECRET_KEY=sk_live_xxx
    export PAYSTACK_PUBLIC_KEY=pk_live_xxx
Webhook URL to register in the Paystack dashboard:
    https://<your-domain>/api/payments/webhook
"""
import os

# --- payment settings -------------------------------------------------------
MODE = os.environ.get("PAYMENTS_MODE", "demo").lower()          # 'demo' | 'paystack'
PAYSTACK_SECRET_KEY = os.environ.get("PAYSTACK_SECRET_KEY", "") # sk_test_/sk_live_
PAYSTACK_PUBLIC_KEY = os.environ.get("PAYSTACK_PUBLIC_KEY", "") # pk_test_/pk_live_
CURRENCY = os.environ.get("SHOPCART_CURRENCY", "USD")           # display + charge currency
PAYSTACK_API = "https://api.paystack.co"

# --- app settings -----------------------------------------------------------
DB_PATH = os.path.join(os.path.dirname(__file__), "shopcart.db")
ORDER_TTL_MINUTES = 30        # pending-order stock reservations expire after 30 min
COUPONS = {"SHOP10": 0.10}    # server-side coupon table (10% off)
HOST, PORT = "0.0.0.0", 8080

# Server-side demo signing secret (only used to sign receipt links in demo
# deployments). In production set SHOPCART_SECRET via the environment.
SECRET = os.environ.get("SHOPCART_SECRET", "dev-only-secret-change-me")
