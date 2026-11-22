"""Fill the Northwind tables with deterministic fake data, including policy edge cases.

Deterministic = same random seed + same fixed "today" -> exactly the same data every run.
That makes evals repeatable: customer 1 is always the same person with the same transactions.

Normally called via src/reset_db.py (which wipes the tables first).
Running this file directly only works on EMPTY tables:
    .venv\\Scripts\\python.exe -m src.seed
"""

import json
import random
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import psycopg

# ---------------------------------------------------------------
# Settings
# ---------------------------------------------------------------
TODAY = date(2026, 11, 20)  # fixed "today": all dates are relative to this, never the real clock
SEED = 42                   # fixed random seed -> same "random" data every time
NUM_CUSTOMERS = 30
TXNS_PER_CARD = 15
DEMO_FILE = Path("data") / "demo_customers.json"

FIRST_NAMES = ["Ava", "Liam", "Maya", "Noah", "Priya", "Ethan", "Sofia", "Lucas", "Amara", "James",
               "Chloe", "Mateo", "Hana", "Owen", "Zara", "Diego", "Grace", "Kai", "Elena", "Samuel"]
LAST_NAMES = ["Patel", "Nguyen", "Garcia", "Okafor", "Kim", "Johnson", "Rossi", "Silva", "Cohen", "Murphy",
              "Tanaka", "Haddad", "Brown", "Lopez", "Fischer", "Ali", "Walker", "Chen", "Novak", "Reyes"]

# (merchant, min amount, max amount): realistic everyday spending, all well under the policy limits.
MERCHANTS = [
    ("Whole Foods Market", 18, 160), ("Trader Joe's", 12, 110), ("Shell", 25, 75),
    ("Chevron", 25, 80), ("Starbucks", 4, 14), ("Chipotle", 10, 28),
    ("Amazon.com", 9, 180), ("Target", 15, 140), ("Walgreens", 5, 55),
    ("Uber", 8, 45), ("Netflix", 15.49, 15.49), ("Spotify", 11.99, 11.99),
    ("Home Depot", 20, 220), ("Costco", 40, 240), ("Delta Air Lines", 120, 240),
]

# ---------------------------------------------------------------
# Edge cases: one per customer (customers 1..10, in this order).
# Each transaction is (merchant, amount, days_ago, status).
# "disputes" are pre-existing disputes: (index into txns, type, reason, filed days_ago).
# ---------------------------------------------------------------
EDGE_CASES = [
    {"key": "fraud_eligible",
     "what": "$480 unrecognized, 10d ago -> fraud, auto credit (P6)",
     "txns": [("LUXETECH ELECTRONICS HK", 480, 10, "posted")]},
    {"key": "fraud_over_limit",
     "what": "$700 unrecognized, 5d ago -> fraud, escalate credit (P6)",
     "txns": [("GLOBAL TRAVEL DEALS LTD", 700, 5, "posted")]},
    {"key": "merchant_non_delivery",
     "what": "$120 not delivered, 20d ago -> merchant, auto credit (P7)",
     "txns": [("Pinewood Furniture Co", 120, 20, "posted")]},
    {"key": "merchant_over_limit",
     "what": "$300 merchant issue, 15d ago -> escalate credit (P7)",
     "txns": [("BrightStar Electronics", 300, 15, "posted")]},
    {"key": "duplicate_charge",
     "what": "$60 charged twice same day, 7d ago -> dispute the 2nd (P7)",
     "txns": [("Bella Italia Restaurant", 60, 7, "posted"),
              ("Bella Italia Restaurant", 60, 7, "posted")]},
    {"key": "date_window",
     "what": "59d old = eligible, 61d old = too late (P5)",
     "txns": [("Grand Hotel Downtown", 150, 59, "posted"),
              ("Harbor View Spa", 95, 61, "posted")]},
    {"key": "pending_txn",
     "what": "pending transaction -> can't dispute yet (P5)",
     "txns": [("Lyft", 45.30, 1, "pending")]},
    {"key": "already_disputed",
     "what": "transaction already has a dispute -> no duplicate (P8)",
     "txns": [("QuickShip Gadgets", 89.99, 25, "posted")],
     "disputes": [(0, "merchant", "Item not received", 12)]},
    {"key": "dispute_limit",
     "what": "3 disputes in last 90d; new one -> escalate (P8)",
     "txns": [("SnapStyle Apparel", 64.00, 75, "posted"),
              ("FitGear Direct", 110.00, 45, "posted"),
              ("HomeChef Meal Kits", 79.99, 20, "posted"),
              ("Urban Sneaker Co", 75.00, 6, "posted")],   # <- the NEW one they want to dispute
     "disputes": [(0, "merchant", "Item not as described", 70),
                  (1, "merchant", "Item not received", 40),
                  (2, "merchant", "Charged after cancelling", 15)]},
    {"key": "frozen_card",
     "what": "card already frozen; $150 charge 3d ago (P6)",
     "card_status": "frozen",
     "txns": [("Online Gaming Credits", 150, 3, "posted")]},
]


# ---------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------
def days_ago(n: int) -> date:
    """A date n days before our fixed TODAY."""
    return TODAY - timedelta(days=n)


def timestamp_days_ago(n: int) -> datetime:
    """Noon UTC, n days before TODAY (for created_at columns)."""
    return datetime.combine(days_ago(n), time(12, 0), tzinfo=timezone.utc)


def money(x: float) -> Decimal:
    """Exact 2-decimal money value. Decimal avoids float rounding errors."""
    return Decimal(f"{x:.2f}")


def insert_returning_ids(cur: psycopg.Cursor, sql: str, rows: list[tuple]) -> list[int]:
    """Insert many rows in ONE batched round trip and return their new ids, in order.

    executemany(..., returning=True) uses psycopg's pipeline mode: it sends all rows
    at once instead of waiting for a reply per row. That's what makes reset take seconds.
    """
    cur.executemany(sql, rows, returning=True)
    ids = []
    while True:
        ids.append(cur.fetchone()[0])  # each row's "RETURNING id" is its own result set
        if not cur.nextset():
            break
    return ids


# ---------------------------------------------------------------
# Main seeding logic
# ---------------------------------------------------------------
def seed(conn: psycopg.Connection) -> dict:
    """Insert all fake data. Assumes empty tables. Returns the edge-case info (also saved to JSON)."""
    rng = random.Random(SEED)  # our own random generator, so nothing else can disturb the sequence
    cur = conn.cursor()

    # --- Customers ---------------------------------------------------------------
    # Pick 30 unique (first, last) name combinations.
    all_names = [(f, l) for f in FIRST_NAMES for l in LAST_NAMES]
    names = rng.sample(all_names, NUM_CUSTOMERS)

    customer_rows = []
    for first, last in names:
        dob = date(1950, 1, 1) + timedelta(days=rng.randint(0, 54 * 365))  # born 1950-2004
        zip_code = f"{rng.randint(10000, 99999)}"
        email = f"{first}.{last}@example.com".lower()
        customer_rows.append((f"{first} {last}", dob, zip_code, email))

    customer_ids = insert_returning_ids(
        cur, "INSERT INTO customers (name, dob, zip, email) VALUES (%s, %s, %s, %s) RETURNING id",
        customer_rows)

    # Customer index -> edge case (customers 0..9 get edge cases 0..9).
    edge_for = {i: case for i, case in enumerate(EDGE_CASES)}

    # --- Cards -------------------------------------------------------------------
    cards_per_customer = [rng.randint(1, 2) for _ in customer_ids]
    # Unique last4 across ALL cards, so last4 + dob + zip always points to exactly one card.
    last4_pool = rng.sample(range(1000, 10000), sum(cards_per_customer))

    card_rows = []
    card_owner = []  # card_owner[k] = customer index of the k-th card
    for i, (cust_id, n_cards) in enumerate(zip(customer_ids, cards_per_customer)):
        for c in range(n_cards):
            status = "active"
            # Edge-case cards: only the customer's FIRST card is affected.
            if c == 0 and i in edge_for:
                status = edge_for[i].get("card_status", "active")
            card_rows.append((cust_id, str(last4_pool.pop()), status))
            card_owner.append(i)

    card_ids = insert_returning_ids(
        cur, "INSERT INTO cards (customer_id, last4, status) VALUES (%s, %s, %s) RETURNING id",
        card_rows)

    # --- Transactions ------------------------------------------------------------
    txn_rows = []
    edge_txn_positions = {}  # customer index -> positions in txn_rows of that customer's edge txns

    for k, card_id in enumerate(card_ids):
        # Normal background spending over the last ~4 months.
        for _ in range(TXNS_PER_CARD):
            merchant, lo, hi = rng.choice(MERCHANTS)
            n_days = rng.randint(0, 120)
            # Very recent purchases are sometimes still pending, like a real card.
            status = "pending" if n_days <= 2 and rng.random() < 0.5 else "posted"
            txn_rows.append((card_id, merchant, money(rng.uniform(lo, hi)), days_ago(n_days), status))

    # Edge-case transactions go on each edge customer's FIRST card.
    first_card_of = {}
    for k, owner in enumerate(card_owner):
        first_card_of.setdefault(owner, card_ids[k])

    for i, case in edge_for.items():
        edge_txn_positions[i] = []
        for merchant, amount, n_days, status in case["txns"]:
            edge_txn_positions[i].append(len(txn_rows))
            txn_rows.append((first_card_of[i], merchant, money(amount), days_ago(n_days), status))

    txn_ids = insert_returning_ids(
        cur, "INSERT INTO transactions (card_id, merchant, amount, txn_date, status) "
             "VALUES (%s, %s, %s, %s, %s) RETURNING id",
        txn_rows)

    # --- Pre-existing disputes (for already_disputed and dispute_limit) ------------
    dispute_rows = []
    for i, case in edge_for.items():
        for txn_index, dtype, reason, filed_days_ago in case.get("disputes", []):
            txn_id = txn_ids[edge_txn_positions[i][txn_index]]
            dispute_rows.append((txn_id, customer_ids[i], dtype, reason, timestamp_days_ago(filed_days_ago)))

    disputed_txn_ids = set()
    if dispute_rows:
        insert_returning_ids(
            cur, "INSERT INTO disputes (transaction_id, customer_id, type, reason, created_at) "
                 "VALUES (%s, %s, %s, %s, %s) RETURNING id",
            dispute_rows)
        disputed_txn_ids = {row[0] for row in dispute_rows}

    # --- Build the demo file: everything a tester needs to "be" each edge customer ---
    demo = {"today": TODAY.isoformat(), "edge_cases": {}}
    for i, case in edge_for.items():
        name, dob, zip_code, _email = customer_rows[i]
        k = card_ids.index(first_card_of[i])
        demo["edge_cases"][case["key"]] = {
            "what": case["what"],
            "customer_id": customer_ids[i],
            "name": name,
            "last4": card_rows[k][1],
            "dob": dob.isoformat(),
            "zip": zip_code,
            "card_status": card_rows[k][2],
            "transactions": [
                {
                    "id": txn_ids[pos],
                    "merchant": txn_rows[pos][1],
                    "amount": str(txn_rows[pos][2]),
                    "txn_date": txn_rows[pos][3].isoformat(),
                    "status": txn_rows[pos][4],
                    "already_disputed": txn_ids[pos] in disputed_txn_ids,
                }
                for pos in edge_txn_positions[i]
            ],
        }

    DEMO_FILE.write_text(json.dumps(demo, indent=2), encoding="utf-8")

    demo["counts"] = {
        "customers": len(customer_ids), "cards": len(card_ids),
        "transactions": len(txn_ids), "disputes": len(dispute_rows),
    }
    return demo


def print_summary(demo: dict) -> None:
    """Print the edge-case cheat sheet."""
    c = demo["counts"]
    print(f"Seeded: {c['customers']} customers, {c['cards']} cards, "
          f"{c['transactions']} transactions, {c['disputes']} disputes  (today = {demo['today']})")
    print()
    header = f"{'edge case':<22} {'cust':>4}  {'name':<16} {'last4':<5} {'dob':<10} {'zip':<5}  {'txn ids':<14} what"
    print(header)
    print("-" * len(header))
    for key, e in demo["edge_cases"].items():
        ids = ",".join(str(t["id"]) for t in e["transactions"])
        print(f"{key:<22} {e['customer_id']:>4}  {e['name']:<16} {e['last4']:<5} {e['dob']:<10} "
              f"{e['zip']:<5}  {ids:<14} {e['what']}")
    print()
    print(f"Details written to {DEMO_FILE}")


if __name__ == "__main__":
    from src.db import get_connection

    with get_connection() as conn:
        # Safety: refuse to double-seed. Use reset_db.py to wipe + seed.
        existing = conn.execute("SELECT count(*) FROM customers").fetchone()[0]
        if existing:
            raise SystemExit(f"customers table already has {existing} rows. Run: python -m src.reset_db")
        print_summary(seed(conn))
