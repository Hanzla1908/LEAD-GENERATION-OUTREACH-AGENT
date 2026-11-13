import logging
import re
import time
import uuid

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from config import is_production, max_request_bytes
from services import rate_limit
from services.auth import COOKIE_NAME, current_user
from services.membership import resolve_active
from services.tenancy import workspace_scope

logger = logging.getLogger("app.http")

# Machine-to-machine and link targets. Each one is protected by its own check instead of the session:
# unsubscribe by a signed token, the provider webhook by an HMAC signature over the body and a timestamp.
PUBLIC_PATHS = {"/health", "/health/ready", "/auth/login", "/auth/logout", "/auth/session", "/auth/setup",
                "/auth/setup-status", "/auth/register", "/invitations/preview", "/invitations/accept", "/unsubscribe",
                "/webhooks/email-events"}
CSRF_EXEMPT_PATHS = {"/unsubscribe", "/webhooks/email-events"}
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
CSRF_HEADER = "x-requested-with"

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "geolocation=(), microphone=(), camera=()",
    "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; frame-ancestors 'none'",
}


def _request_id(incoming: str | None) -> str:
    if incoming and re.fullmatch(r"[A-Za-z0-9-]{8,64}", incoming):
        return incoming
    return uuid.uuid4().hex


def _deny(request: Request, path: str, method: str) -> tuple[int, str] | None:
    """Coarse gate for every request: a live session, the CSRF header, and rate limits.

    What a signed-in account may do is decided per endpoint by services.access.require(...).
    """
    if method == "OPTIONS":
        return None
    if path not in PUBLIC_PATHS:
        user = current_user(request.cookies.get(COOKIE_NAME))
        if user is None:
            return 401, "Sign in required."
        request.state.user = user
        # The workspace this request works in. Every query in the request is scoped to it (services/tenancy.py).
        request.state.workspace_id, _ = resolve_active(user)
    if method not in SAFE_METHODS and path not in CSRF_EXEMPT_PATHS:
        if not request.headers.get(CSRF_HEADER):
            return 403, "Missing X-Requested-With header."
    if not rate_limit.check(request):
        return 429, "Too many requests. Wait a moment and try again."
    return None


class BodyTooLarge(Exception):
    """Raised when a request body grows beyond MAX_REQUEST_BYTES while it is being read."""


class BodyLimitMiddleware:
    """Refuses request bodies over the configured size, before the handler reads them.

    Requests that declare Content-Length above the limit are refused immediately. Requests
    without a declared length (chunked uploads) are counted as they arrive and refused once the
    limit is passed.
    """

    def __init__(self, app: ASGIApp, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        for name, value in scope.get("headers", []):
            if name == b"content-length":
                try:
                    declared = int(value)
                except ValueError:
                    response = JSONResponse({"detail": "Invalid Content-Length."}, status_code=400)
                    await response(scope, receive, send)
                    return
                if declared > self.max_bytes:
                    response = JSONResponse({"detail": "Request body is too large."}, status_code=413)
                    await response(scope, receive, send)
                    return
                break

        received = 0

        async def limited_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    raise BodyTooLarge()
            return message

        await self.app(scope, limited_receive, send)


async def _body_too_large(request: Request, exc: BodyTooLarge) -> JSONResponse:
    return JSONResponse({"detail": "Request body is too large."}, status_code=413)


def install(app: FastAPI) -> None:
    app.add_middleware(BodyLimitMiddleware, max_bytes=max_request_bytes())
    app.add_exception_handler(BodyTooLarge, _body_too_large)

    @app.middleware("http")
    async def gateway(request: Request, call_next):
        request_id = _request_id(request.headers.get("x-request-id"))
        request.state.request_id = request_id
        started = time.perf_counter()
        path = request.url.path
        method = request.method

        denial = _deny(request, path, method)
        if denial is not None:
            response = JSONResponse(status_code=denial[0], content={"detail": denial[1]})
        else:
            try:
                with workspace_scope(getattr(request.state, "workspace_id", None)):
                    response = await call_next(request)
            except Exception:
                logger.exception("Unhandled error", extra={"request_id": request_id, "method": method, "path": path})
                response = JSONResponse(
                    status_code=500,
                    content={"detail": "Internal server error.", "request_id": request_id},
                )

        for name, value in SECURITY_HEADERS.items():
            response.headers.setdefault(name, value)
        if is_production():
            response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        if path.startswith("/auth"):
            response.headers["Cache-Control"] = "no-store"
        response.headers["X-Request-ID"] = request_id

        logger.info(
            "request",
            extra={
                "request_id": request_id,
                "method": method,
                "path": path,
                "status": response.status_code,
                "duration_ms": round((time.perf_counter() - started) * 1000, 1),
            },
        )
        return response
