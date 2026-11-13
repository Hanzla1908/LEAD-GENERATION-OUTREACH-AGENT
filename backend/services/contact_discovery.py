"""
Contact discovery service.

Finds publicly published business email addresses from restaurant websites.
Rules:
- Only extracts emails that appear on the page. No guessing, no synthesis.
- Checks homepage + up to 4 contact/about subpaths per site.
- Reuses SSRF protection and robots.txt logic from website_checker.
- Marks every result 'unverified' — never claims deliverability.
- Deduplicates by normalising to lowercase.
"""

import re
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from services.website_checker import (
    CONNECT_TIMEOUT,
    READ_TIMEOUT,
    UnsafeTarget,
    check_robots,
    fetch_page,
    is_blocked_ip,
    make_client,
    validate_url_syntax,
)

_CONTACT_PATHS = ["/contact", "/contact-us", "/about", "/about-us"]
MAX_PAGES_TO_CHECK = 5

# RFC 5322 simplified regex — good enough for published addresses
_EMAIL_RE = re.compile(r"\b[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}\b")

# Common placeholder / no-reply domains to exclude
_EXCLUDED_DOMAINS = frozenset([
    "example.com", "domain.com", "test.com", "yoursite.com",
    "yourdomain.com", "email.com", "sentry.io", "sentry.com",
    "cloudflare.com", "wixpress.com", "squarespace.com",
])

# Asset-extension false positives (e.g. icon.png@2x)
_ASSET_EXT = frozenset([
    ".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp",
    ".css", ".js", ".woff", ".woff2", ".ttf", ".eot",
])


def _clean(emails: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for raw in emails:
        norm = raw.lower().strip()
        domain = norm.split("@", 1)[-1] if "@" in norm else ""
        if domain in _EXCLUDED_DOMAINS:
            continue
        if any(domain.endswith(ext) for ext in _ASSET_EXT):
            continue
        if norm not in seen:
            seen.add(norm)
            out.append(norm)
    return out


def extract_emails_from_html(html: bytes) -> list[str]:
    """Return deduplicated, cleaned email addresses found in *html*."""
    text = html.decode("utf-8", errors="replace")
    soup = BeautifulSoup(text, "html.parser")

    for tag in soup(["script", "style"]):
        tag.decompose()

    emails: list[str] = []

    # mailto: links are the most reliable signal
    for a in soup.find_all("a", href=True):
        href: str = a["href"]
        if href.lower().startswith("mailto:"):
            addr = href[7:].split("?")[0].strip()
            if addr:
                emails.append(addr)

    # Scan visible text
    emails.extend(_EMAIL_RE.findall(soup.get_text(separator=" ")))

    return _clean(emails)


async def _fetch_safe(
    client: httpx.AsyncClient, url: str
) -> tuple[bytes, str] | None:
    """Fetch *url* respecting SSRF rules and robots.txt. Returns (body, final_url) or None."""
    try:
        parsed = validate_url_syntax(url)
        if is_blocked_ip(parsed.hostname):
            return None
        if not await check_robots(client, url):
            return None
        status, body, final_url = await fetch_page(client, url)
        if status == 200 and body:
            return body, final_url
    except UnsafeTarget:
        return None
    except Exception:
        pass
    return None


async def discover_contact_emails(website_url: str) -> dict:
    """
    Discover publicly published business email addresses for a restaurant.

    Returns:
        {
            "emails": [{"email": str, "source_url": str, "status": "unverified"}],
            "pages_checked": int,
            "error": str | None,
        }
    """
    result: dict = {"emails": [], "pages_checked": 0, "error": None}

    try:
        parsed = validate_url_syntax(website_url)
    except UnsafeTarget as exc:
        result["error"] = str(exc)
        return result
    except Exception as exc:
        result["error"] = f"URL error: {exc}"
        return result

    if is_blocked_ip(parsed.hostname):
        result["error"] = "Blocked: private/internal address"
        return result

    base_url = f"{parsed.scheme}://{parsed.netloc}"
    timeout = httpx.Timeout(CONNECT_TIMEOUT, read=READ_TIMEOUT)

    try:
        async with make_client(timeout) as client:
            pages_to_check = [website_url] + [
                urljoin(base_url, path) for path in _CONTACT_PATHS
            ]

            seen: set[str] = set()

            for url in pages_to_check[:MAX_PAGES_TO_CHECK]:
                fetched = await _fetch_safe(client, url)
                if fetched is None:
                    continue
                body, final_url = fetched
                result["pages_checked"] += 1

                for email in extract_emails_from_html(body):
                    if email not in seen:
                        seen.add(email)
                        result["emails"].append(
                            {"email": email, "source_url": final_url, "status": "unverified"}
                        )
    except Exception as exc:
        result["error"] = str(exc)

    return result
