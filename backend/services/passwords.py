"""Password hashing for user accounts.

New hashes use Argon2id (argon2-cffi defaults). Hashes written by the earlier shared-admin code
(scrypt, format scrypt$N$r$p$salt$digest) are still accepted, so a migrated admin can sign in. After
such a sign-in the hash is replaced with an Argon2 hash. Plain-text passwords are never stored.
"""
import base64
import hashlib
import hmac
import re

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from config import MIN_PASSWORD_LENGTH

_hasher = PasswordHasher()
_SCRYPT_MAXMEM = 64 * 1024 * 1024


def password_problem(password: str) -> str | None:
    """Why a password is refused, or None when it is acceptable."""
    if len(password) < MIN_PASSWORD_LENGTH:
        return f"Use at least {MIN_PASSWORD_LENGTH} characters."
    if len(password) > 200:
        return "Use 200 characters or fewer."
    return None


REGISTRATION_PASSWORD_LENGTH = 8
_REGISTRATION_PASSWORD = re.compile(r"[A-Za-z0-9]+")


def registration_password_problem(password: str) -> str | None:
    """Sign-up rule only: exactly 8 letters and numbers. Every other password change keeps password_problem."""
    if len(password) != REGISTRATION_PASSWORD_LENGTH:
        return f"Use exactly {REGISTRATION_PASSWORD_LENGTH} characters."
    if not _REGISTRATION_PASSWORD.fullmatch(password):
        return "Use letters and numbers only (A to Z and 0 to 9)."
    return None


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def _verify_legacy_scrypt(candidate: str, encoded: str) -> bool:
    try:
        _scheme, n, r, p, salt_text, digest_text = encoded.split("$")
        salt = base64.b64decode(salt_text)
        expected = base64.b64decode(digest_text)
        actual = hashlib.scrypt(candidate.encode(), salt=salt, n=int(n), r=int(r), p=int(p),
                                dklen=len(expected), maxmem=_SCRYPT_MAXMEM)
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(actual, expected)


def verify_password(candidate: str, stored: str | None) -> bool:
    if not stored:
        return False
    if stored.startswith("$argon2"):
        try:
            return _hasher.verify(stored, candidate)
        except (VerifyMismatchError, VerificationError, InvalidHashError):
            return False
    if stored.startswith("scrypt$"):
        return _verify_legacy_scrypt(candidate, stored)
    return False


def needs_rehash(stored: str) -> bool:
    """True when a correct password should be stored again under the current scheme."""
    if not stored.startswith("$argon2"):
        return True
    try:
        return _hasher.check_needs_rehash(stored)
    except InvalidHashError:
        return True


# Checked when no account matches the email, so an unknown address takes about as long to refuse as a
# wrong password for a real one.
_DUMMY_HASH = _hasher.hash("not-a-real-password-for-timing")


def verify_dummy(candidate: str) -> None:
    """Spend the same time as a real verification. The result is ignored."""
    verify_password(candidate, _DUMMY_HASH)
