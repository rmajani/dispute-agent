"""Wipe every table and re-seed it with the same deterministic data.

Evals call reset_db() before every scenario, so each one starts from an identical bank.

Run from the project root:
    .venv\\Scripts\\python.exe -m src.reset_db
"""

import time

from src.db import get_connection
from src.seed import print_summary, seed

# All our tables. TRUNCATE empties them all in one fast statement.
TABLES = "audit_log, escalations, credits, disputes, transactions, cards, customers"


def reset_db(verbose: bool = True) -> dict:
    """Empty all tables, re-seed, and return the edge-case info."""
    start = time.perf_counter()

    # One transaction: wipe + seed either BOTH happen or NEITHER does,
    # so an eval can never see a half-empty database.
    with get_connection() as conn:
        # RESTART IDENTITY resets the id counters to 1, so ids are identical every reset
        # (customer 1 is always the same person, transaction ids never drift).
        # CASCADE lets us truncate tables that reference each other.
        conn.execute(f"TRUNCATE {TABLES} RESTART IDENTITY CASCADE")
        demo = seed(conn)

    elapsed = time.perf_counter() - start
    if verbose:
        print_summary(demo)
        print(f"Reset complete in {elapsed:.1f}s")
    return demo


if __name__ == "__main__":
    reset_db()
