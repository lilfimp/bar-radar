"""Validate that a candidate menu URL actually contains drinks-menu content,
and produce a confidence score + menu_status.

Text extraction:
- HTML_PAGE: strip tags, lowercase, keyword-match.
- PDF: extract text with pypdf (pure Python, no system deps).
- IMAGE: we cannot OCR for free reliably at this volume -> treat as
  POSSIBLE_MENU capped at a modest confidence, flagged for manual review.
- EXTERNAL_PLATFORM: reachable => POSSIBLE_MENU (content lives off-site,
  can't easily verify without a browser).
"""
from __future__ import annotations

import io

from bs4 import BeautifulSoup

from src.utils.config import settings
from src.utils.http_utils import get
from src.utils.logging_utils import get_logger

log = get_logger(__name__)


def _keyword_hit_ratio(text: str) -> float:
    keywords = settings()["menu_content_keywords"]
    text_lower = text.lower()
    hits = sum(1 for kw in keywords if kw in text_lower)
    return min(hits / 6.0, 1.0)  # 6+ distinct keyword hits => full confidence


def _extract_pdf_text(content: bytes) -> str:
    try:
        from pypdf import PdfReader
    except ImportError:
        log.warning("pypdf not installed - cannot extract PDF text")
        return ""
    try:
        reader = PdfReader(io.BytesIO(content))
        return "\n".join((page.extract_text() or "") for page in reader.pages[:6])
    except Exception as exc:  # noqa: BLE001 - malformed PDFs are common in the wild
        log.warning("Failed to parse PDF: %s", exc)
        return ""


def validate_candidate(candidate: dict) -> dict:
    """Returns {"menu_status", "menu_confidence", "menu_url", "menu_source_type"}."""
    url = candidate["url"]
    source_type = candidate["source_type"]
    thresholds = settings()["confidence_thresholds"]

    resp = get(url)
    if resp is None:
        return _result(url, source_type, "WEBSITE_UNAVAILABLE", 0.0)
    if resp.status_code in (403, 429):
        return _result(url, source_type, "BLOCKED", 0.0)
    if resp.status_code >= 400:
        return _result(url, source_type, "WEBSITE_UNAVAILABLE", 0.0)

    if source_type == "PDF":
        text = _extract_pdf_text(resp.content)
        confidence = _keyword_hit_ratio(text) if text else 0.15
    elif source_type == "HTML_PAGE":
        soup = BeautifulSoup(resp.text, "html.parser")
        text = soup.get_text(" ", strip=True)
        confidence = _keyword_hit_ratio(text)
    elif source_type == "IMAGE":
        # reachable image with menu-ish link text but no OCR -> capped confidence
        confidence = 0.4
    elif source_type == "EXTERNAL_PLATFORM":
        confidence = 0.5
    else:
        confidence = 0.0

    if confidence >= thresholds["valid_menu"]:
        status = "VALID_MENU"
    elif confidence >= thresholds["possible_menu"]:
        status = "POSSIBLE_MENU"
    else:
        status = "NO_MENU_FOUND"

    return _result(url, source_type, status, round(confidence, 2))


def _result(url: str, source_type: str, status: str, confidence: float) -> dict:
    return {
        "menu_url": url,
        "menu_source_type": source_type,
        "menu_status": status,
        "menu_confidence": confidence,
    }


def pick_best_valid_menu(candidates: list[dict]) -> dict | None:
    """Validate candidates in score order, return the first VALID_MENU or
    POSSIBLE_MENU result. Stops early on first VALID_MENU to save requests."""
    best_possible = None
    for candidate in candidates:
        result = validate_candidate(candidate)
        if result["menu_status"] == "VALID_MENU":
            return result
        if result["menu_status"] == "POSSIBLE_MENU" and best_possible is None:
            best_possible = result
    return best_possible
