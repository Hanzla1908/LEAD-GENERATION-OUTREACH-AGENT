"""
Website availability and online-ordering detection service.

Security notes:
- SSRF protection: each hop of a request (the first URL and every redirect) is resolved
  once, every returned address is checked, and the connection is made to that validated
  IP address. The Host header and TLS server name keep the original hostname. This also
  closes DNS-rebinding races between the check and the connection.
- Redirects are followed manually so a redirect to a private address is refused before
  any request reaches it.
- Only http/https on ports 80 and 443. URLs with login details are refused.
- Proxies from the environment are ignored (trust_env=False) so they cannot bypass pinning.
- Size cap: page bodies are streamed and truncated at MAX_RESPONSE_BYTES.
- A deadline bounds the whole fetch, so a slow response cannot hold the worker.
- No JavaScript execution: BeautifulSoup + html.parser only.
- Robots.txt: checked before fetching; an unreachable robots.txt is treated as allowed,
  but a robots.txt that points at a blocked address stops the check.
"""

import asyncio
import ipaddress
import socket
from urllib.parse import urljoin, urlparse, urlunparse
from urllib.robotparser import RobotFileParser

import httpx
from bs4 import BeautifulSoup

from services import industries

USER_AGENT = "RestaurantOutreachBot/1.0 (website availability check)"
MAX_RESPONSE_BYTES = 1_000_000  # 1 MB
CONNECT_TIMEOUT = 5.0
READ_TIMEOUT = 10.0
MAX_REDIRECTS = 5
FETCH_DEADLINE_SECONDS = 25.0
ALLOWED_PORTS = frozenset({80, 443})
REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})


class UnsafeTarget(Exception):
    """The URL or the address it resolves to is not a public web server, so it is never contacted."""


# ---------------------------------------------------------------------------
# SSRF: IP ranges that must never be contacted
# ---------------------------------------------------------------------------
_BLOCKED_NETWORKS = [
    ipaddress.ip_network(n)
    for n in [
        "0.0.0.0/8",       # this network
        "10.0.0.0/8",      # RFC 1918
        "100.64.0.0/10",   # shared address space (RFC 6598)
        "127.0.0.0/8",     # loopback
        "169.254.0.0/16",  # link-local (includes cloud metadata 169.254.169.254)
        "172.16.0.0/12",   # RFC 1918
        "192.0.0.0/24",    # IETF protocol assignments
        "192.0.2.0/24",    # documentation
        "192.88.99.0/24",  # 6to4 relay anycast
        "192.168.0.0/16",  # RFC 1918
        "198.18.0.0/15",   # benchmarking
        "198.51.100.0/24", # documentation
        "203.0.113.0/24",  # documentation
        "224.0.0.0/4",     # multicast
        "240.0.0.0/4",     # reserved
        "::/128",          # unspecified
        "::1/128",         # IPv6 loopback
        "::ffff:0:0/96",   # IPv4-mapped IPv6 (checked again after unmapping)
        "64:ff9b::/96",    # NAT64 (can point at internal IPv4)
        "100::/64",        # discard prefix
        "2001:db8::/32",   # documentation
        "2002::/16",       # 6to4 (can point at internal IPv4)
        "fc00::/7",        # IPv6 unique local
        "fe80::/10",       # IPv6 link-local
        "ff00::/8",        # IPv6 multicast
    ]
]

# ---------------------------------------------------------------------------
# Online-ordering detection signals
# ---------------------------------------------------------------------------
_ORDERING_DOMAINS = frozenset([
    "doordash.com", "ubereats.com", "grubhub.com", "toasttab.com",
    "olo.com", "chownow.com", "slice.com", "seamless.com",
    "postmates.com", "caviar.com", "delivery.com", "bopple.me",
    "popmenu.com", "ordercounter.com", "hungerrush.com",
    "order.online", "bentobox.com",
])

_ORDERING_KEYWORDS = frozenset([
    "order online", "order now", "order food", "place order",
    "start order", "order delivery", "get delivery", "order here",
    "order pickup", "online ordering", "add to cart",
])


# ---------------------------------------------------------------------------
# Address and URL validation
# ---------------------------------------------------------------------------

def _unmapped(ip):
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        return ip.ipv4_mapped
    return ip


def ip_is_blocked(ip) -> bool:
    """True when *ip* is private, loopback, link-local, multicast, reserved or otherwise internal."""
    ip = _unmapped(ip)
    if any(ip in network for network in _BLOCKED_NETWORKS):
        return True
    return ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved or ip.is_unspecified


def resolve_public_addresses(hostname: str) -> list[str]:
    """Resolve *hostname* once and return its addresses. Raises UnsafeTarget if any is internal."""
    try:
        infos = socket.getaddrinfo(hostname, None)
    except (socket.gaierror, UnicodeError, ValueError, OSError):
        raise UnsafeTarget("Could not resolve the website address.")
    addresses: list[str] = []
    for _family, _type, _proto, _canon, sockaddr in infos:
        try:
            ip = ipaddress.ip_address(sockaddr[0])
        except ValueError:
            raise UnsafeTarget("Could not resolve the website address.")
        if ip_is_blocked(ip):
            raise UnsafeTarget("Blocked: destination resolves to a private/internal address")
        text = str(_unmapped(ip))
        if text not in addresses:
            addresses.append(text)
    if not addresses:
        raise UnsafeTarget("Could not resolve the website address.")
    return addresses


def validate_url_syntax(url: str):
    """Check scheme, port and credentials without any network lookup. Returns the parsed URL."""
    try:
        parsed = urlparse(url)
        port = parsed.port
    except ValueError:
        raise UnsafeTarget("Invalid URL.")
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise UnsafeTarget("Invalid URL: must begin with http:// or https://")
    if parsed.username is not None or parsed.password is not None:
        raise UnsafeTarget("URLs with login details are not checked.")
    effective_port = port or (443 if parsed.scheme == "https" else 80)
    if effective_port not in ALLOWED_PORTS:
        raise UnsafeTarget("Only standard web ports (80 and 443) are checked.")
    return parsed


def is_blocked_ip(hostname: str) -> bool:
    """Return True if *hostname* resolves to any private/reserved IP, or cannot be resolved."""
    try:
        resolve_public_addresses(hostname)
        return False
    except UnsafeTarget:
        return True


def get_base_domain(hostname: str) -> str:
    """Return the eTLD+1 approximation (last two labels)."""
    parts = hostname.rstrip(".").lower().split(".")
    return ".".join(parts[-2:]) if len(parts) >= 2 else hostname.lower()


def make_client(timeout: httpx.Timeout) -> httpx.AsyncClient:
    """HTTP client for website checks. Ignores environment proxies and never follows redirects itself."""
    return httpx.AsyncClient(
        timeout=timeout,
        headers={"User-Agent": USER_AGENT},
        trust_env=False,
        follow_redirects=False,
    )


# ---------------------------------------------------------------------------
# Fetching
# ---------------------------------------------------------------------------

async def check_robots(client: httpx.AsyncClient, url: str) -> bool:
    """Return True (allow) if robots.txt permits fetching *url*. Raises UnsafeTarget if robots.txt is internal."""
    parsed = urlparse(url)
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
    try:
        status, body, _final_url = await fetch_page(client, robots_url)
    except UnsafeTarget:
        raise
    except Exception:
        return True  # fail open: inability to read robots.txt is not a disallow
    if status != 200:
        return True
    rp = RobotFileParser()
    rp.parse(body.decode("utf-8", errors="replace").splitlines())
    return rp.can_fetch("*", url) and rp.can_fetch(USER_AGENT, url)


def _pinned_request(parsed, address: str) -> tuple[str, str]:
    """Return the URL to connect to (the validated IP) and the Host header to send."""
    port = parsed.port
    default_port = 443 if parsed.scheme == "https" else 80
    host_part = f"[{address}]" if ":" in address else address
    if port in (None, default_port):
        netloc, host_header = host_part, parsed.hostname
    else:
        netloc, host_header = f"{host_part}:{port}", f"{parsed.hostname}:{port}"
    url = urlunparse((parsed.scheme, netloc, parsed.path or "/", "", parsed.query, ""))
    return url, host_header


async def fetch_page(client: httpx.AsyncClient, url: str) -> tuple[int, bytes, str]:
    """
    Fetch *url* safely; return (status_code, body_capped_1MB, final_url).

    Every hop is validated and pinned to the address that passed validation.
    Redirect targets are validated before any request is sent to them.
    """
    current = url
    for _hop in range(MAX_REDIRECTS + 1):
        parsed = validate_url_syntax(current)
        address = resolve_public_addresses(parsed.hostname)[0]
        target, host_header = _pinned_request(parsed, address)
        extensions = {"sni_hostname": parsed.hostname} if parsed.scheme == "https" else {}
        async with client.stream(
            "GET", target, headers={"Host": host_header}, extensions=extensions, follow_redirects=False,
        ) as response:
            if response.status_code in REDIRECT_STATUSES:
                location = response.headers.get("location")
                if not location:
                    return response.status_code, b"", current
                current = urljoin(current, location)
                continue
            content = bytearray()
            if response.status_code == 200:
                async for chunk in response.aiter_bytes(8192):
                    content.extend(chunk)
                    if len(content) >= MAX_RESPONSE_BYTES:
                        break
            return response.status_code, bytes(content[:MAX_RESPONSE_BYTES]), current
    raise httpx.TooManyRedirects("Too many redirects")


def find_feature_evidence(soup: BeautifulSoup, page_url: str, feature: dict) -> list[str]:
    """Scan parsed HTML for one website feature (from an industry profile). Up to 10 evidence strings."""
    keywords = tuple(str(k).lower() for k in feature.get("keywords", []))
    domains = tuple(str(d).lower() for d in feature.get("domains", []))
    seen: set[str] = set()
    evidence: list[str] = []

    def _add(item: str) -> None:
        norm = item.strip()
        if norm and norm not in seen and len(evidence) < 10:
            seen.add(norm)
            evidence.append(norm)

    for a_tag in soup.find_all("a", href=True):
        href: str = a_tag.get("href", "")
        text: str = a_tag.get_text(separator=" ", strip=True).lower()
        href_lower = href.lower()

        # href contains a platform domain for this feature
        if any(domain in href_lower for domain in domains):
            _add(href[:200])

        # link text matches a keyword for this feature
        if any(kw in text for kw in keywords):
            _add(href[:200] if href else f"link:{text[:80]}")

    for tag in soup.find_all(["button", "input"]):
        text = tag.get_text(separator=" ", strip=True).lower()
        if any(kw in text for kw in keywords):
            _add(f"button:{text[:80]}")

    return evidence


def find_ordering_evidence(soup: BeautifulSoup, page_url: str) -> list[str]:
    """Online-ordering evidence for restaurants. Kept for existing callers; the logic is shared with every feature."""
    feature = industries.feature_by_key(industries.DEFAULT_INDUSTRY, "ordering")
    return find_feature_evidence(soup, page_url, feature)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def _unknown_features(features: list[dict]) -> dict[str, dict]:
    """Until a page has been read, every feature is unknown. An unread page is never evidence of absence."""
    return {f["key"]: {"label": f["label"], "status": "unknown", "evidence": []} for f in features}


async def check_website(url: str, industry: str | None = None) -> dict:
    """
    Check a business website for availability and the features its industry cares about.

    Returns a dict with keys:
        website_status:    "present" | "not_found" | "unknown"
        features:          {feature_key: {"label", "status": "present"|"not_found"|"unknown", "evidence": [urls]}}
        ordering_status:   "present" | "not_found" | "unknown"   (restaurants online ordering, for existing callers)
        ordering_evidence: list[str]
        error:             str | None
    """
    features = industries.features(industry)
    result: dict = {
        "website_status": "unknown",
        "ordering_status": "unknown",
        "ordering_evidence": [],
        "features": _unknown_features(features),
        "error": None,
    }

    # ── validate URL (no network yet) ───────────────────────────────────────
    try:
        parsed = validate_url_syntax(url)
    except UnsafeTarget as exc:
        result["error"] = str(exc)
        return result

    # ── SSRF guard: initial hostname (each hop is re-checked and pinned in fetch_page) ──
    if is_blocked_ip(parsed.hostname):
        result["error"] = "Blocked: destination resolves to a private/internal address"
        return result

    timeout = httpx.Timeout(CONNECT_TIMEOUT, read=READ_TIMEOUT)
    try:
        async with make_client(timeout) as client:

            # ── robots.txt ──────────────────────────────────────────────────
            try:
                if not await check_robots(client, url):
                    result["error"] = "Crawling disallowed by robots.txt"
                    return result

                # ── fetch page (bounded by a deadline) ──────────────────────
                status_code, content, final_url = await asyncio.wait_for(
                    fetch_page(client, url), timeout=FETCH_DEADLINE_SECONDS,
                )
            except UnsafeTarget as exc:
                result["error"] = str(exc)
                return result
            except asyncio.TimeoutError:
                result["error"] = "Request timed out"
                return result
            except httpx.TooManyRedirects:
                result["error"] = "Too many redirects"
                return result
            except httpx.TimeoutException:
                result["error"] = "Request timed out"
                return result
            except httpx.ConnectError as exc:
                result["error"] = f"Connection failed: {exc}"
                return result
            except httpx.HTTPError as exc:
                result["error"] = str(exc)
                return result

            final_hostname = urlparse(final_url).hostname or ""

            # ── domain-change detection ─────────────────────────────────────
            orig_base = get_base_domain(parsed.hostname)
            final_base = get_base_domain(final_hostname) if final_hostname else ""

            if final_base and final_base != orig_base:
                matched = [f for f in features if any(d in final_base for d in f.get("domains", []))]
                if matched:
                    # Site itself redirects to a platform that provides one of its features
                    result["website_status"] = "present"
                    for feature in matched:
                        result["features"][feature["key"]] = {
                            "label": feature["label"], "status": "present", "evidence": [final_url[:200]],
                        }
                    if any(f["key"] == "ordering" for f in matched):
                        result["ordering_status"] = "present"
                        result["ordering_evidence"] = [final_url[:200]]
                else:
                    result["website_status"] = "unknown"
                    result["error"] = f"Redirected to unrelated domain ({final_hostname})"
                return result

            # ── HTTP status ─────────────────────────────────────────────────
            if status_code == 404:
                result["website_status"] = "not_found"
                return result
            if 200 <= status_code < 300:
                result["website_status"] = "present"
            else:
                result["website_status"] = "unknown"
                result["error"] = f"HTTP {status_code}"
                return result

            # ── feature detection (evidence is read only from a page we actually have) ──
            if not content:
                return result

            soup = BeautifulSoup(content, "html.parser")
            for feature in features:
                evidence = find_feature_evidence(soup, final_url, feature)
                result["features"][feature["key"]] = {
                    "label": feature["label"],
                    "status": "present" if evidence else "not_found",
                    "evidence": evidence,
                }
            ordering = result["features"].get("ordering")
            if ordering is not None:
                result["ordering_evidence"] = ordering["evidence"]
                result["ordering_status"] = ordering["status"]

    except Exception as exc:
        result["error"] = str(exc) or "Website check failed."

    return result
