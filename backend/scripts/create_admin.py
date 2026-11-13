"""Create the first admin account (bootstrap). Run from the backend folder:

    python scripts/create_admin.py

- Applies database migrations first (same as the server does at startup).
- Asks for a name, an email, and a password typed at a hidden prompt. The password never appears on the
  command line, in shell history, or in a log.
- Refuses to run when an active admin already exists. Later accounts are created from the Users page.
- Nothing is hardcoded: there are no default credentials.

Migrating from the old shared admin password
    If ADMIN_PASSWORD_HASH is still set in the environment, add --from-legacy-hash. The existing scrypt
    hash is stored for the new admin account, so the same password keeps working. It is upgraded to
    Argon2 on the next sign-in. The plain-text ADMIN_PASSWORD is never read.
    After this succeeds, remove ADMIN_PASSWORD and ADMIN_PASSWORD_HASH from the environment.
"""
import argparse
import getpass
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from models.database import init_db  # noqa: E402
from services import audit, users  # noqa: E402
from services.passwords import password_problem  # noqa: E402


def _prompt_password() -> str:
    first = getpass.getpass("Password (at least 12 characters): ")
    problem = password_problem(first)
    if problem:
        sys.exit(problem)
    if getpass.getpass("Repeat the password: ") != first:
        sys.exit("The two entries do not match.")
    return first


def main() -> None:
    parser = argparse.ArgumentParser(description="Create the first admin account.")
    parser.add_argument("--from-legacy-hash", action="store_true",
                        help="Reuse the existing ADMIN_PASSWORD_HASH from the environment instead of a new password.")
    args = parser.parse_args()

    init_db()
    if users.active_admin_count() > 0:
        sys.exit("An active admin account already exists. Add more accounts from the Users page.")

    name = input("Full name: ").strip()
    email = input("Email address: ").strip()
    try:
        clean_email = users.normalize_email(email)
    except ValueError as exc:
        sys.exit(str(exc))
    if len(name) < 2:
        sys.exit("Enter a name of at least 2 characters.")

    if args.from_legacy_hash:
        legacy = os.getenv("ADMIN_PASSWORD_HASH", "").strip()
        if not legacy:
            sys.exit("ADMIN_PASSWORD_HASH is not set in the environment, so there is no hash to import.")
        if not legacy.startswith("scrypt$"):
            sys.exit("ADMIN_PASSWORD_HASH is not in the expected format.")
        account = users.create_user_with_hash(None, name, clean_email, legacy, "admin")
    else:
        account = users.create_user(None, name, clean_email, _prompt_password(), "admin")

    audit.record(None, "bootstrap.admin_created", "user", account["id"])
    print(f"Admin account created for {clean_email}. Sign in at the app with this email and password.")


if __name__ == "__main__":
    main()
