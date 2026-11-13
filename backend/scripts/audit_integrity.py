"""Report orphan records and invalid relationships before migrating. Reads only: it changes nothing.

    python scripts/audit_integrity.py

Exit code 0: the data satisfies the new constraints. Exit code 1: problems are listed. Fix each row (or export
it with scripts/logical_backup.py and correct it by hand) and run the audit again. Nothing is deleted by this
tool or by the migration.
"""
import importlib.util
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

from models.database import get_engine  # noqa: E402


def _load_audit():
    path = BACKEND / "migrations" / "versions" / "0007_relational_integrity.py"
    spec = importlib.util.spec_from_file_location("relational_integrity", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> int:
    module = _load_audit()
    with get_engine().connect() as connection:
        problems = module.audit(connection)
    if not problems:
        print("No orphan records or invalid relationships found. The data satisfies the new constraints.")
        return 0
    print("Problems found. The migration will not run until they are fixed:")
    print(module.describe(problems))
    print("Nothing was changed.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
