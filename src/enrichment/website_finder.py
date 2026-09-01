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


def search_website(venue_name: str, city: str) -> str | None:
    query = f'{venue_name} {city} bar'
    resp = get(DDG_HTML_URL, params={"q": query})
    if resp is None or resp.status_code != 200:
        log.warning("DuckDuckGo search failed for '%s'", query)
        return None

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
