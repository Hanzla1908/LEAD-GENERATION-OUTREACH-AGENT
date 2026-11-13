"""Logical backup and restore of the application database, without pg_dump.

export   Writes one JSON Lines file per table, plus manifest.json with row counts and the SHA-256
         of every file. Sessions are not exported: they are short-lived and should not survive a restore.

restore  Loads a backup folder into an EMPTY database. Every file is checked against the manifest
         first, and the restore stops if any checksum or row count does not match. The target is
         created with the normal migrations (init_db), so the schema always matches the code.

Examples (run from the backend folder):

    python scripts/logical_backup.py export --database-url "$DATABASE_URL" --out backups/2026-11-04
    python scripts/logical_backup.py restore --from backups/2026-11-04 --database-url "postgresql+psycopg://..."

Keep backups private: they contain restaurant contact details and the suppression list.
"""
import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

# Parents before children, so references always point at rows that already exist.
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


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 16), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _encode(row: dict) -> dict:
    return {key: (value.isoformat(sep=" ") if isinstance(value, datetime) else value) for key, value in row.items()}


def _parse_timestamp(value):
    if not isinstance(value, str):
        return value
    for pattern in TIMESTAMP_FORMATS:
        try:
            return datetime.strptime(value, pattern)
        except ValueError:
            continue
    raise ValueError(f"Unrecognised timestamp in backup: {value!r}")


class BackupError(Exception):
    """The backup is incomplete or damaged, or the target is not empty."""


def export_database(out_dir: str, database_url: str | None = None) -> dict:
    from sqlalchemy import text

    previous = os.environ.get("DATABASE_URL")
    if database_url:
        os.environ["DATABASE_URL"] = database_url
    try:
        from models.database import get_engine, is_postgres

        # Export reads the database as it is. It must not run migrations: a backup never changes the schema.
        out = Path(out_dir)
        out.mkdir(parents=True, exist_ok=True)
        manifest = {
            "format": 1,
            "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "database": "postgresql" if is_postgres() else "sqlite",
            "tables": {},
        }
        with get_engine().connect() as conn:
            for table in TABLES:
                rows = [dict(r) for r in conn.execute(text(f"SELECT * FROM {table} ORDER BY 1")).mappings()]
                path = out / f"{table}.jsonl"
                with path.open("w", encoding="utf-8", newline="\n") as handle:
                    for row in rows:
                        handle.write(json.dumps(_encode(row), sort_keys=True) + "\n")
                manifest["tables"][table] = {"rows": len(rows), "sha256": _sha256(path)}
        (out / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        return manifest
    finally:
        _restore_env(previous)


def verify_backup(backup_dir: str) -> dict:
    folder = Path(backup_dir)
    manifest_path = folder / "manifest.json"
    if not manifest_path.exists():
        raise BackupError("manifest.json is missing; this is not a complete backup.")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for table in TABLES:
        entry = manifest["tables"].get(table)
        path = folder / f"{table}.jsonl"
        if entry is None or not path.exists():
            raise BackupError(f"{table}.jsonl is missing from the backup.")
        if _sha256(path) != entry["sha256"]:
            raise BackupError(f"Checksum mismatch in {table}.jsonl; the backup is damaged and was not restored.")
        lines = sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())
        if lines != entry["rows"]:
            raise BackupError(f"{table}.jsonl has {lines} rows but the manifest lists {entry['rows']}.")
    return manifest


def restore_database(backup_dir: str, database_url: str) -> dict:
    from sqlalchemy import inspect, text
    import sqlalchemy as sa

    verify_backup(backup_dir)
    previous = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = database_url
    try:
        from models.database import get_engine, init_db, is_postgres

        init_db()
        engine = get_engine()
        with engine.begin() as conn:
            for table in TABLES:
                existing = conn.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar_one()
                if existing:
                    raise BackupError(f"Target table '{table}' already has {existing} rows. Restore into an empty database.")

            inspector = inspect(conn)
            counts = {}
            for table in TABLES:
                columns = {column["name"]: column["type"] for column in inspector.get_columns(table)}
                records = []
                with (Path(backup_dir) / f"{table}.jsonl").open(encoding="utf-8") as handle:
                    for line in handle:
                        if not line.strip():
                            continue
                        record = json.loads(line)
                        for name, value in list(record.items()):
                            if name not in columns:
                                del record[name]
                            elif isinstance(columns[name], (sa.DateTime, sa.DATETIME, sa.TIMESTAMP)):
                                parsed = _parse_timestamp(value)
                                if parsed is not None and not is_postgres():
                                    parsed = parsed.strftime("%Y-%m-%d %H:%M:%S")
                                record[name] = parsed
                        records.append(record)
                if records:
                    names = list(records[0].keys())
                    conn.execute(
                        text(f"INSERT INTO {table} ({', '.join(names)}) VALUES ({', '.join(':' + n for n in names)})"),
                        records,
                    )
                counts[table] = len(records)

            if is_postgres():
                for table in TABLES:
                    if "id" in {c["name"] for c in inspector.get_columns(table)}:
                        conn.execute(text(
                            "SELECT setval(pg_get_serial_sequence(:table, 'id'), "
                            f"COALESCE((SELECT MAX(id) FROM {table}), 1), (SELECT COUNT(*) > 0 FROM {table}))"
                        ), {"table": table})
        return counts
    finally:
        _restore_env(previous)


def _restore_env(previous: str | None) -> None:
    if previous is None:
        os.environ.pop("DATABASE_URL", None)
    else:
        os.environ["DATABASE_URL"] = previous


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    export = sub.add_parser("export", help="Write a backup folder.")
    export.add_argument("--database-url", default=os.getenv("DATABASE_URL"))
    export.add_argument("--out", required=True)

    restore = sub.add_parser("restore", help="Load a backup folder into an empty database.")
    restore.add_argument("--from", dest="source", required=True)
    restore.add_argument("--database-url", required=True)

    args = parser.parse_args()
    try:
        if args.command == "export":
            manifest = export_database(args.out, args.database_url)
            for table, entry in manifest["tables"].items():
                print(f"{table}: {entry['rows']} rows")
            print(f"Backup written to {args.out}. Keep it private.")
        else:
            counts = restore_database(args.source, args.database_url)
            for table, count in counts.items():
                print(f"{table}: {count} rows restored")
            print("Restore complete.")
    except BackupError as exc:
        sys.exit(f"Backup error: {exc}")


if __name__ == "__main__":
    main()
