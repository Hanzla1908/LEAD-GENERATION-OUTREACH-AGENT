"""Set a new password for an existing account, from the command line. Run from the backend folder:

    python scripts/reset_admin_password.py ali@gmail.com

- Both passwords are typed at hidden prompts. They never appear on the command line or in a log.
- Uses the same rules as every other password change (at least 12 characters, Argon2 hashing).
- Ends every active session for that account, so anyone signed in elsewhere must sign in again.
- Writes an audit entry. Nothing else in the account changes.
"""
import argparse
import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from models.database import fetch_one, init_db  # noqa: E402
from services import users  # noqa: E402
from services.passwords import password_problem  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Set a new password for an existing account.")
    parser.add_argument("email", help="The account's email address.")
    args = parser.parse_args()

    init_db()
    try:
        clean_email = users.normalize_email(args.email)
    except ValueError as exc:
        sys.exit(str(exc))
    row = fetch_one("SELECT id, name, status FROM users WHERE email = :email", {"email": clean_email})
    if row is None:
        sys.exit(f"No account exists for {clean_email}.")

    first = getpass.getpass("New password (at least 12 characters): ")
    problem = password_problem(first)
    if problem:
        sys.exit(problem)
    if getpass.getpass("Repeat the new password: ") != first:
        sys.exit("The two entries do not match. Nothing was changed.")

    # The script runs outside a request, so there is no signed-in actor; the audit entry records the change as a
    # system action.
    users.reset_password({"id": None}, row["id"], first)
    print(f"Password updated for {clean_email}. Sign in at the app with the new password.")


if __name__ == "__main__":
    main()
