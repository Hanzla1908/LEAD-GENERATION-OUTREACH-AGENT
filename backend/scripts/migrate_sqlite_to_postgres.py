"""Copy application data from the local SQLite file into an empty PostgreSQL database.

Run once, with the backend stopped, against an empty target:

    python scripts/migrate_sqlite_to_postgres.py --source restaurant_outreach.db ^
        --target "postgresql+psycopg://USER:PASSWORD@HOST:5432/DBNAME"

The script refuses to write into a target that already contains rows, and it never
modifies the source file.
"""
import argparse
import os
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

# Parents before children, so foreign-style references always point at rows that already exist.
TABLES = [
    "restaurants",
    "leads",
    "email_drafts",
    "campaigns",
    "campaign_recipients",
    "suppression_list",
    "campaign_send_logs",
]
TIMESTAMP_FORMATS = ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S")


def _to_timestamp(value):
    if not isinstance(value, str):
        return value
    for pattern in TIMESTAMP_FORMATS:
        try:
            return datetime.strptime(value, pattern)
        except ValueError:
            continue
    return value


def migrate(source_path: str, target_url: str) -> dict[str, int]:
    from sqlalchemy import inspect, text
    import sqlalchemy as sa

    if not Path(source_path).exists():
        raise FileNotFoundError(f"Source database not found: {source_path}")

    previous_url = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = target_url
    try:
        from models.database import get_engine, init_db, is_postgres

        init_db()
        engine = get_engine()
        with engine.begin() as conn:
            for table in TABLES:
                rows = conn.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar_one()
                if rows:
                    raise SystemExit(f"Target table '{table}' already has {rows} rows. Migrate into an empty database.")

        source = sqlite3.connect(source_path)
        source.row_factory = sqlite3.Row
        source_tables = {row[0] for row in source.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        counts: dict[str, int] = {}
        try:
            with engine.begin() as conn:
                target_columns = {
                    table: {column["name"]: column["type"] for column in inspect(conn).get_columns(table)}
                    for table in TABLES
                }
                for table in TABLES:
                    if table not in source_tables:
                        counts[table] = 0
                        continue
                    source_columns = [row[1] for row in source.execute(f"PRAGMA table_info({table})")]
                    columns = [name for name in source_columns if name in target_columns[table]]
                    records = []
                    for row in source.execute(f"SELECT {', '.join(columns)} FROM {table} ORDER BY rowid"):
                        record = {}
                        for name in columns:
                            value = row[name]
                            if isinstance(target_columns[table][name], (sa.DateTime, sa.DATETIME, sa.TIMESTAMP)):
                                value = _to_timestamp(value)
                            record[name] = value
                        records.append(record)
                    if records:
                        placeholders = ", ".join(f":{name}" for name in columns)
                        conn.execute(
                            text(f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders})"),
                            records,
                        )
                    counts[table] = len(records)
                if is_postgres():
                    for table in TABLES:
                        if "id" in target_columns[table]:
                            conn.execute(text(
                                "SELECT setval(pg_get_serial_sequence(:table, 'id'), "
                                f"COALESCE((SELECT MAX(id) FROM {table}), 1), "
                                f"(SELECT COUNT(*) > 0 FROM {table}))"
                            ), {"table": table})
        finally:
            source.close()
        return counts
    finally:
        if previous_url is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous_url


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source", required=True, help="Path to the SQLite file to copy from.")
    parser.add_argument("--target", required=True, help="SQLAlchemy URL of the empty PostgreSQL database.")
    args = parser.parse_args()
    counts = migrate(args.source, args.target)
    for table, count in counts.items():
        print(f"{table}: {count} rows copied")
    print("Migration complete. Keep the SQLite file as a backup.")


if __name__ == "__main__":
    main()
