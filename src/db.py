"""Database connection for the Northwind dispute agent.

This is the ONLY place that knows how to reach the database.
Everything else calls get_connection().
"""

import os  # read environment variables

import psycopg  # the Postgres driver (psycopg v3)
from dotenv import load_dotenv  # loads key=value pairs from .env into the environment

# Read .env once, when this module is imported.
# After this, DATABASE_URL is available via os.environ, without us ever opening the file ourselves.
load_dotenv()


def get_connection() -> psycopg.Connection:
    """Open and return a new connection to the Supabase Postgres database."""
    database_url = os.getenv("DATABASE_URL")

    # Fail closed: if the setting is missing, stop with a clear message.
    # We never print the value itself, only whether it exists.
    if not database_url:
        raise RuntimeError("DATABASE_URL is not set. Add it to .env in the project root.")

    # prepare_threshold=None turns off server-side prepared statements.
    # Supabase's connection pooler (pgbouncer-style) doesn't support them,
    # and leaving them on causes confusing errors later.
    return psycopg.connect(database_url, prepare_threshold=None)


# This block only runs when you execute the file directly:
#   .venv\Scripts\python.exe -m src.db
# It does NOT run when another file does `from src.db import get_connection`.
if __name__ == "__main__":
    # "with" closes the connection automatically, even if something fails.
    with get_connection() as conn:
        # A cursor is what you use to send SQL and read results back.
        with conn.cursor() as cur:
            # Ask the database for its version and its own clock time.
            cur.execute("SELECT version(), now()")
            version, db_time = cur.fetchone()  # one row, two columns

    print("Connected to the database OK")
    print("Postgres version:", version)
    print("Database time:   ", db_time)
    print("Connection closed.")
