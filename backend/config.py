import os
import secrets

MIN_PASSWORD_LENGTH = 12
MIN_SESSION_SECRET_LENGTH = 32
MIN_UNSUBSCRIBE_SECRET_LENGTH = 16
DEFAULT_CORS_ORIGINS = "http://localhost:5173,http://127.0.0.1:5173"
DEFAULT_MAX_REQUEST_BYTES = 64 * 1024
MAX_REQUEST_BYTES_CEILING = 1024 * 1024

# Used only in development when SESSION_SECRET is not set. It changes on every restart, so sessions
# issued in development end when the server restarts. Production refuses to start without SESSION_SECRET.
_DEVELOPMENT_SESSION_SECRET = secrets.token_urlsafe(48)


def _flag(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def is_production() -> bool:
    return os.getenv("APP_ENV", "development").strip().lower() == "production"


def session_secret() -> str:
    """Key that signs session tokens. Set SESSION_SECRET; never derived from a password."""
    return os.getenv("SESSION_SECRET", "") or _DEVELOPMENT_SESSION_SECRET


def public_app_url() -> str:
    """Where the frontend is served. Invitation links point here. Set PUBLIC_APP_URL in production."""
    return os.getenv("PUBLIC_APP_URL", "http://localhost:5173").strip().rstrip("/")


def cors_origins() -> list[str]:
    raw = os.getenv("CORS_ORIGINS", DEFAULT_CORS_ORIGINS)
    return [origin.strip().rstrip("/") for origin in raw.split(",") if origin.strip()]


def mock_email_mode() -> bool:
    return _flag("MOCK_EMAIL_MODE", True)


def rate_limit_enabled() -> bool:
    return _flag("RATE_LIMIT_ENABLED", is_production())


def trust_proxy_headers() -> bool:
    """Use X-Forwarded-For for the client address. Only enable behind a proxy that sets it (Render does)."""
    return _flag("TRUST_PROXY_HEADERS", is_production())


def max_request_bytes() -> int:
    raw = os.getenv("MAX_REQUEST_BYTES", "").strip()
    try:
        value = int(raw) if raw else DEFAULT_MAX_REQUEST_BYTES
    except ValueError:
        value = DEFAULT_MAX_REQUEST_BYTES
    return max(1024, min(value, MAX_REQUEST_BYTES_CEILING))


def log_json() -> bool:
    return _flag("LOG_JSON", is_production())


def log_level() -> str:
    return os.getenv("LOG_LEVEL", "INFO").strip().upper()


def production_problems() -> list[str]:
    problems = []
    if len(os.getenv("SESSION_SECRET", "")) < MIN_SESSION_SECRET_LENGTH:
        problems.append(f"SESSION_SECRET must be at least {MIN_SESSION_SECRET_LENGTH} characters.")
    if len(os.getenv("UNSUBSCRIBE_SECRET", "")) < MIN_UNSUBSCRIBE_SECRET_LENGTH:
        problems.append(f"UNSUBSCRIBE_SECRET must be at least {MIN_UNSUBSCRIBE_SECRET_LENGTH} characters.")
    if not os.getenv("DATABASE_URL", "").startswith(("postgres://", "postgresql://", "postgresql+psycopg://")):
        problems.append("DATABASE_URL must point to PostgreSQL in production.")
    if "localhost" in ",".join(cors_origins()) or "127.0.0.1" in ",".join(cors_origins()):
        problems.append("CORS_ORIGINS still lists localhost. Set it to the deployed frontend URL.")
    if not mock_email_mode() and os.getenv("EMAIL_PROVIDER", "mock").strip().lower() == "mock":
        problems.append("MOCK_EMAIL_MODE is off but EMAIL_PROVIDER is mock. Choose one explicitly.")
    return problems
