"""
Shopcart — persistence layer (SQLite).
======================================
Two tables:

    products  — live stock counters (`stock`) plus `reserved` units held by
                unpaid orders.  sellable = stock - reserved.
    orders    — one row per order with a JSON snapshot of the purchased
                lines (name/unit-price/qty frozen at purchase time), the
                computed money fields, status and payment metadata.

Concurrency: a single module-level lock + SQLite transactions keep stock
updates atomic (important when two checkouts race for the last unit).
"""
import json, sqlite3, threading, time, uuid, hmac, hashlib

import config
from catalog import CATALOG, COLOURS

_lock = threading.Lock()


def _connect():
    """Open a connection with row access by name + FK enforcement."""
    con = sqlite3.connect(config.DB_PATH, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")     # better concurrent reads
    return con


def init_db():
    """Create tables on first boot and seed stock from the static catalog."""
    with _lock, _connect() as con:
        con.execute("""CREATE TABLE IF NOT EXISTS products(
            id TEXT PRIMARY KEY, stock INTEGER NOT NULL, reserved INTEGER NOT NULL DEFAULT 0)""")
        con.execute("""CREATE TABLE IF NOT EXISTS orders(
            id TEXT PRIMARY KEY,          -- 'SC-XXXXXX' public order number
            reference TEXT UNIQUE NOT NULL, -- payment reference (idempotency key)
            email TEXT, lines TEXT NOT NULL, coupon TEXT,
            subtotal REAL NOT NULL, discount REAL NOT NULL, total REAL NOT NULL,
            currency TEXT NOT NULL, status TEXT NOT NULL,   -- pending|paid|failed|cancelled|placed
            method TEXT,                      -- card|bank|crypto|pod
            payer TEXT,                       -- safe payer metadata (never PAN/CVV)
            receipt_token TEXT NOT NULL,      -- secret token guarding the receipt URL
            created REAL NOT NULL, paid REAL)""")
        for pid, p in CATALOG.items():
            con.execute("INSERT OR IGNORE INTO products(id,stock,reserved) VALUES(?,?,0)",
                        (pid, p["stock"]))


# ---------------------------------------------------------------------------
# Stock helpers
# ---------------------------------------------------------------------------

def get_availability():
    """Return {product_id: sellable_units} for every catalog product."""
    with _lock, _connect() as con:
        rows = con.execute("SELECT id, stock, reserved FROM products").fetchall()
    return {r["id"]: max(0, r["stock"] - r["reserved"]) for r in rows}


def sweep_expired():
    """Release reservations of pending orders older than ORDER_TTL_MINUTES."""
    cutoff = time.time() - config.ORDER_TTL_MINUTES * 60
    with _lock, _connect() as con:
        stale = con.execute(
            "SELECT id, lines FROM orders WHERE status='pending' AND created<?",
            (cutoff,)).fetchall()
        for o in stale:
            for line in json.loads(o["lines"]):
                con.execute("""UPDATE products SET reserved=MAX(0,reserved-?)
                               WHERE id=?""", (line["qty"], line["id"]))
            con.execute("UPDATE orders SET status='cancelled' WHERE id=?", (o["id"],))


# ---------------------------------------------------------------------------
# Order lifecycle
# ---------------------------------------------------------------------------

def compute_totals(lines, coupon=None):
    """
    Authoritative price maths. `lines` = [{'id', 'qty'}] from the client.
    Returns (clean_lines, subtotal, discount, total) where clean_lines carry
    server-supplied names/prices, or raises ValueError on bad input.
    """
    clean, subtotal = [], 0.0
    for l in lines:
        pid, qty = str(l.get("id", "")), int(l.get("qty", 0) or 0)
        if pid not in CATALOG or qty <= 0:
            raise ValueError(f"invalid line: {pid}")
        p = CATALOG[pid]
        clean.append(dict(id=pid, name=p["name"], price=p["price"], qty=qty,
                          img=p["img"], colour=COLOURS.get(pid, "—")))
        subtotal += p["price"] * qty
    discount = round(subtotal * config.COUPONS.get((coupon or "").upper(), 0), 2)
    return clean, round(subtotal, 2), discount, round(subtotal - discount, 2)


def create_order(lines, email, coupon, method):
    """
    Validate stock, reserve the units and create a PENDING order —
    all inside ONE transaction so two shoppers can't reserve the same
    last item. Returns the order row dict, or None on stock conflict.
    """
    clean, subtotal, discount, total = compute_totals(lines, coupon)
    with _lock, _connect() as con:
        for l in clean:  # conditional reserve: fails if sellable < qty
            cur = con.execute("""UPDATE products SET reserved=reserved+?
                                 WHERE id=? AND stock-reserved>=?""",
                              (l["qty"], l["id"], l["qty"]))
            if cur.rowcount == 0:
                return None  # transaction rolls back automatically
        oid = "SC-" + uuid.uuid4().hex[:8].upper()
        ref = "PAY-" + uuid.uuid4().hex[:12].upper()
        token = hmac.new(config.SECRET.encode(), oid.encode(),
                         hashlib.sha256).hexdigest()[:24]
        con.execute("""INSERT INTO orders(id,reference,email,lines,coupon,subtotal,
                       discount,total,currency,status,method,receipt_token,created)
                       VALUES(?,?,?,?,?,?,?,?,?, 'pending', ?,?,?)""",
                    (oid, ref, email or "", json.dumps(clean), (coupon or "").upper(),
                     subtotal, discount, total, config.CURRENCY, method, token,
                     time.time()))
    return get_order(oid)


def get_order(oid):
    with _lock, _connect() as con:
        r = con.execute("SELECT * FROM orders WHERE id=?", (oid,)).fetchone()
    return dict(r) if r else None


def get_order_by_ref(ref):
    with _lock, _connect() as con:
        r = con.execute("SELECT * FROM orders WHERE reference=?", (ref,)).fetchone()
    return dict(r) if r else None


def _fulfill(con, order_row, payer_meta):
    """Convert reservations into sales exactly once (idempotent)."""
    if order_row["status"] in ("paid", "placed"):
        return  # already fulfilled — duplicate webhook/verify is a no-op
    for line in json.loads(order_row["lines"]):
        con.execute("""UPDATE products
                       SET stock=MAX(0,stock-?), reserved=MAX(0,reserved-?)
                       WHERE id=?""", (line["qty"], line["qty"], line["id"]))
    con.execute("""UPDATE orders SET status=?, payer=?, paid=? WHERE id=?""",
                ("paid" if order_row["method"] != "pod" else "placed",
                 json.dumps(payer_meta), time.time(), order_row["id"]))


def mark_paid(order_id, payer_meta=None):
    """Idempotently mark an order paid and decrement real stock."""
    with _lock, _connect() as con:
        row = con.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
        if not row:
            return None
        _fulfill(con, row, payer_meta or {})
    return get_order(order_id)


def mark_failed(order_id):
    """Payment failed/declined -> release the reserved stock."""
    with _lock, _connect() as con:
        row = con.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
        if not row or row["status"] != "pending":
            return get_order(order_id)
        for line in json.loads(row["lines"]):
            con.execute("UPDATE products SET reserved=MAX(0,reserved-?) WHERE id=?",
                        (line["qty"], line["id"]))
        con.execute("UPDATE orders SET status='failed' WHERE id=?", (order_id,))
    return get_order(order_id)


def cancel_pending(order_id):
    """User closed the payment window -> release reservation, cancel order."""
    with _lock, _connect() as con:
        row = con.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
        if row and row["status"] == "pending":
            for line in json.loads(row["lines"]):
                con.execute("UPDATE products SET reserved=MAX(0,reserved-?) WHERE id=?",
                            (line["qty"], line["id"]))
            con.execute("UPDATE orders SET status='cancelled' WHERE id=?", (order_id,))
    return get_order(order_id)
