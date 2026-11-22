"""Create (or re-create) the Northwind database tables from data/schema.sql.

Run from the project root:
    .venv\\Scripts\\python.exe -m src.setup_db

WARNING: this DROPS all tables first, so any existing data is deleted.
"""

from pathlib import Path  # easy, cross-platform file paths

from src.db import get_connection  # our one place that knows how to connect

# Path to the SQL file, relative to the project root (where we run from).
SCHEMA_PATH = Path("data") / "schema.sql"


def main() -> None:
    # Read the whole SQL file as one string.
    schema_sql = SCHEMA_PATH.read_text(encoding="utf-8")

    # "with" = one transaction. If ANY statement fails, Postgres rolls back everything,
    # so we never end up with half the tables created. If all succeed, it commits at the end.
    with get_connection() as conn:
        # psycopg can run a file with many statements in one go, as long as we pass no parameters.
        conn.execute(schema_sql)

        # Verify: list our tables and whether row level security is on.
        # pg_tables is a built-in Postgres view describing every table.
        rows = conn.execute(
            """
            SELECT tablename, rowsecurity
            FROM pg_tables
            WHERE schemaname = 'public'
            ORDER BY tablename
            """
        ).fetchall()

    print("Schema applied. Tables in 'public':")
    for name, rls_on in rows:
        print(f"  {name:<14} RLS: {'ON' if rls_on else 'OFF  <-- problem'}")


if __name__ == "__main__":
    main()
