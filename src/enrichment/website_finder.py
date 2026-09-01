"""Find the official website for a venue.

Order of operations (cheapest/most reliable first):
1. Already have it from OSM tags (website_status == 'FOUND' at discovery time).
2. Free fallback: scrape DuckDuckGo's non-JS HTML search results
   (html.duckduckgo.com/html/) - no API key required, respects robots via
   low-volume polite requests. This is a fallback, not a bulk scraping tool.
"""
from __future__ import annotations

from urllib.parse import parse_qs, urlparse

from bs4 import BeautifulSoup

from src.utils.http_utils import get
from src.utils.logging_utils import get_logger

log = get_logger(__name__)

DDG_HTML_URL = "https://html.duckduckgo.com/html/"

# DuckDuckGo's HTML endpoint has no official API contract and, in practice,
# blocks shared/datacenter IP ranges (like GitHub Actions runners) far more
# aggressively than a residential IP. Once it starts blocking, it keeps
# blocking for the rest of that run - so after a handful of consecutive
# failures we stop calling it entirely rather than burning the whole batch's
# time budget on requests that were never going to succeed. This resets
# naturally every run (each GitHub Actions job is a fresh process).
DDG_CIRCUIT_BREAKER_THRESHOLD = 5
_ddg_consecutive_failures = 0
_ddg_circuit_open = False

# domains that are never the venue's own website
BLOCKED_RESULT_DOMAINS = (
    "facebook.com", "instagram.com", "tripadvisor.", "yelp.",
    "google.com", "maps.google", "wikipedia.org", "opentable.",
    "thefork.", "lieferando.", "ubereats.",
)


def _clean_ddg_redirect(href: str) -> str | None:
    """DuckDuckGo HTML results wrap real URLs behind /l/?uddg=<encoded>."""
    if href.startswith("//duckduckgo.com/l/"):
        href = "https:" + href
    parsed = urlparse(href)
    if parsed.path == "/l/":
        qs = parse_qs(parsed.query)
        target = qs.get("uddg", [None])[0]
        return target
    return href


def _record_ddg_outcome(success: bool) -> None:
    global _ddg_consecutive_failures, _ddg_circuit_open
    if success:
        _ddg_consecutive_failures = 0
        return
    _ddg_consecutive_failures += 1
    if _ddg_consecutive_failures >= DDG_CIRCUIT_BREAKER_THRESHOLD and not _ddg_circuit_open:
        _ddg_circuit_open = True
        log.error(
            "DuckDuckGo circuit breaker OPEN after %d consecutive failures - "
            "skipping DuckDuckGo search for the rest of this run. Venues "
            "without an OSM website tag will go straight to manual review.",
            _ddg_consecutive_failures,
        )


def reset_ddg_circuit_breaker() -> None:
    """Exposed for tests and for a future --retry-failed-style rerun."""
    global _ddg_consecutive_failures, _ddg_circuit_open
    _ddg_consecutive_failures = 0
    _ddg_circuit_open = False


def search_website(venue_name: str, city: str) -> str | None:
    if _ddg_circuit_open:
        return None

    query = f'{venue_name} {city} bar'
    # Fail fast: a 403/timeout here means "blocked", and retrying the exact
    # same blocked request 2-3 more times within the same call wastes time
    # without ever succeeding.
    resp = get(DDG_HTML_URL, params={"q": query}, timeout=8, max_retries=0)
    if resp is None or resp.status_code != 200:
        log.warning("DuckDuckGo search failed for '%s'", query)
        _record_ddg_outcome(success=False)
        return None
    _record_ddg_outcome(success=True)

    soup = BeautifulSoup(resp.text, "html.parser")
    for link in soup.select("a.result__a"):
        href = link.get("href", "")
        real_url = _clean_ddg_redirect(href)
        if not real_url:
            continue
        if any(bad in real_url for bad in BLOCKED_RESULT_DOMAINS):
            continue
        return real_url
    return None


def find_website(venue: dict) -> tuple[str | None, str]:
    """Returns (website_url, website_status)."""
    if venue.get("website_url"):
        return venue["website_url"], "FOUND"

    url = search_website(venue["venue_name"], venue["city"])
    if url:
        return url, "FOUND"
    return None, "UNAVAILABLE"


def verify_website_reachable(url: str) -> str:
    """Quick reachability check. Returns FOUND, UNAVAILABLE, or BLOCKED."""
    resp = get(url)
    if resp is None:
        return "UNAVAILABLE"
    if resp.status_code in (403, 429):
        return "BLOCKED"
    if resp.status_code >= 400:
        return "UNAVAILABLE"
    return "FOUND"
