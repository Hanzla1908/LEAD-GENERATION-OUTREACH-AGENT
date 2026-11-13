import re
import threading
import time
from collections import defaultdict, deque

from fastapi import Request

from config import rate_limit_enabled, trust_proxy_headers

# method, path pattern, hits allowed, window in seconds
RULES = [
    ("POST", re.compile(r"^/auth/login$"), 10, 900),
    ("POST", re.compile(r"^/auth/setup$"), 10, 900),
    ("POST", re.compile(r"^/auth/register$"), 5, 900),
    ("POST", re.compile(r"^/invitations/(preview|accept)$"), 20, 900),
    ("POST", re.compile(r"^/restaurants/discover$"), 20, 60),
    ("POST", re.compile(r"^/outreach/generate$"), 30, 60),
    ("POST", re.compile(r"^/campaigns$"), 10, 60),
    ("POST", re.compile(r"^/campaigns/\d+/(send|resume|approve-sending|retry-failed|retry-drafts)$"), 30, 60),
]


class RateLimiter:
    def __init__(self) -> None:
        self._hits: dict[str, deque] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key: str, limit: int, window: int) -> bool:
        now = time.monotonic()
        with self._lock:
            hits = self._hits[key]
            while hits and now - hits[0] > window:
                hits.popleft()
            if len(hits) >= limit:
                return False
            hits.append(now)
            return True

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


limiter = RateLimiter()


def client_ip(request: Request) -> str:
    """
    The address that rate limits apply to.

    X-Forwarded-For is only read when TRUST_PROXY_HEADERS is on (production default). Each proxy
    appends the address it received from, so the RIGHTMOST entry is the one the trusted proxy
    saw. The leftmost entry is supplied by the client and can be any value, so it is never used.
    """
    if trust_proxy_headers():
        hops = [hop.strip() for hop in request.headers.get("x-forwarded-for", "").split(",") if hop.strip()]
        if hops:
            return hops[-1][:64]
    return request.client.host if request.client else "unknown"


def rule_for(method: str, path: str):
    for rule_method, pattern, limit, window in RULES:
        if rule_method == method and pattern.match(path):
            return pattern.pattern, limit, window
    return None


def check(request: Request) -> bool:
    """True when the request may proceed."""
    if not rate_limit_enabled():
        return True
    rule = rule_for(request.method, request.url.path)
    if rule is None:
        return True
    scope, limit, window = rule
    return limiter.allow(f"{scope}|{client_ip(request)}", limit, window)
