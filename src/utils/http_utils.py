"""Small wrapper around requests with retries, timeout and a politeness delay.

Kept deliberately dependency-light (requests only) since Playwright is only
pulled in by the enrichment step for JS-heavy sites, and only as a fallback.
"""
from __future__ import annotations

import time
from typing import Optional

import requests

from src.utils.config import settings
from src.utils.logging_utils import get_logger

log = get_logger(__name__)

_last_request_time_by_host: dict[str, float] = {}


def _host(url: str) -> str:
    from urllib.parse import urlparse

    return urlparse(url).netloc


def _respect_delay(url: str) -> None:
    cfg = settings()["http"]
    delay = cfg["request_delay_seconds"]
    host = _host(url)
    last = _last_request_time_by_host.get(host, 0.0)
    elapsed = time.time() - last
    if elapsed < delay:
        time.sleep(delay - elapsed)
    _last_request_time_by_host[host] = time.time()


def get(url: str, **kwargs) -> Optional[requests.Response]:
    """GET with retries. Returns None (never raises) on failure so callers
    can treat network failure as a normal pipeline outcome (WEBSITE_UNAVAILABLE)."""
    cfg = settings()["http"]
    headers = kwargs.pop("headers", {})
    headers.setdefault("User-Agent", cfg["user_agent"])
    timeout = kwargs.pop("timeout", cfg["timeout_seconds"])

    for attempt in range(cfg["max_retries"] + 1):
        _respect_delay(url)
        try:
            resp = requests.get(
                url,
                headers=headers,
                timeout=timeout,
                allow_redirects=True,
                **kwargs,
            )
            if resp.status_code == 403 or resp.status_code == 429:
                log.warning("Blocked (%s) on %s", resp.status_code, url)
                return resp  # let caller decide BLOCKED vs retry
            return resp
        except requests.RequestException as exc:
            log.warning("Request failed (attempt %d) for %s: %s", attempt + 1, url, exc)
            time.sleep(0.5 * (attempt + 1))
    return None
