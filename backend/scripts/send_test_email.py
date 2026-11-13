"""Send ONE clearly marked test email to an address you choose, through the configured provider.

This does not create a restaurant, a draft or a campaign. It is for checking delivery only.

    python scripts/send_test_email.py --to you@example.com --confirm

Safety rules:
- Requires --confirm. Without it the script prints what it would do and sends nothing.
- With MOCK_EMAIL_MODE=true (the default) or EMAIL_PROVIDER=mock, nothing leaves the machine.
  The script says so and records a mock message only.
- A real provider is used only when MOCK_EMAIL_MODE=false and EMAIL_PROVIDER is nodemailer or smtp.
- Sends at most one message per run. The address must be a business-style address that is not a placeholder.
"""
import argparse
import os
import secrets
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

from config import mock_email_mode  # noqa: E402
from services.campaigns import is_valid_business_email  # noqa: E402
from services.email_sender import SendError, get_sender, provider_name  # noqa: E402

SUBJECT = "[TEST] Delivery check from Restaurant Outreach"
BODY = (
    "This is a delivery test from the Restaurant Outreach system.\n\n"
    "No restaurant was contacted and no campaign was started. You can ignore this message.\n"
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--to", required=True, help="The one address to test.")
    parser.add_argument("--confirm", action="store_true", help="Actually send the test message.")
    args = parser.parse_args()

    to = args.to.strip().lower()
    if not is_valid_business_email(to):
        sys.exit("Refused: the address is not a valid, non-placeholder email address.")

    live = (not mock_email_mode()) and provider_name() != "mock"
    mode = f"LIVE via {provider_name()}" if live else "MOCK (nothing is delivered)"
    print(f"Provider mode: {mode}")
    if not args.confirm:
        sys.exit("Dry run only. Add --confirm to send the single test message.")

    try:
        sender = get_sender()
        check = getattr(sender, "check", None)
        if check is not None:
            check()
        message_id = sender.send(
            to=to, subject=SUBJECT, body=BODY,
            idempotency_key=f"test-{secrets.token_hex(8)}",
        )
    except SendError as exc:
        sys.exit(f"Not sent: {exc}")
    print(f"Accepted by provider. Message id: {message_id}")
    if not live:
        print("Mock mode: nothing was delivered. Set MOCK_EMAIL_MODE=false and a real provider to test delivery.")


if __name__ == "__main__":
    main()
