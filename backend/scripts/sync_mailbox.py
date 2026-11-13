"""Read new bounce messages and replies from the sending mailbox, once.

Run it on a schedule (for example every 15 minutes with Windows Task Scheduler or cron). It needs the same
environment as the backend: MAILBOX_IMAP_HOST, MAILBOX_USERNAME, MAILBOX_PASSWORD, and the database settings.

    python scripts/sync_mailbox.py

It prints counts only. It never prints message content, and it never sends anything.
"""
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

from services.mailbox_monitor import MailboxError, sync_mailbox  # noqa: E402


def main() -> None:
    try:
        counts = sync_mailbox()
    except MailboxError as exc:
        sys.exit(f"Mailbox sync did not run: {exc}")
    print("Mailbox sync complete: " + ", ".join(f"{key}={value}" for key, value in counts.items()))


if __name__ == "__main__":
    main()
