"""Thin SQLite access layer for BAR RADAR.

Deliberately not using an ORM - the schema is small and stable, and raw SQL
keeps the GitHub Actions runs fast and dependency-light.
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path

from src.utils.config import db_path

SCHEMA_PATH = Path(__file__).with_name("schema.sql")


def init_db() -> None:
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with get_conn() as conn:
        with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
            conn.executescript(f.read())
        conn.commit()


@contextmanager
def get_conn():
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Venue operations
# ---------------------------------------------------------------------------

def upsert_venue(venue: dict) -> bool:
    """Insert a venue if venue_id is new. Returns True if inserted, False if
    it already existed (i.e. a duplicate discovery hit, not an error)."""
    with get_conn() as conn:
        existing = conn.execute(
            "SELECT venue_id FROM venues WHERE venue_id = ?", (venue["venue_id"],)
        ).fetchone()
        if existing:
            return False
        conn.execute(
            """
            INSERT INTO venues (
                venue_id, venue_name, city, tier, category, address,
                latitude, longitude, osm_type, osm_id, website_url,
                website_status, discovery_source, discovery_query,
                venue_confidence, status
            ) VALUES (
                :venue_id, :venue_name, :city, :tier, :category, :address,
                :latitude, :longitude, :osm_type, :osm_id, :website_url,
                :website_status, :discovery_source, :discovery_query,
                :venue_confidence, :status
            )
            """,
            venue,
        )
        conn.commit()
        return True


def count_valid_menus_for_city(city: str) -> int:
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT COUNT(*) AS n
            FROM venues v
            JOIN menu_sources m ON m.venue_id = v.venue_id AND m.is_primary = 1
            WHERE v.city = ? AND m.menu_status = 'VALID_MENU'
            """,
            (city,),
        ).fetchone()
        return row["n"]


def count_candidates_for_city(city: str) -> int:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM venues WHERE city = ? AND status != 'DUPLICATE' AND status != 'REJECTED'",
            (city,),
        ).fetchone()
        return row["n"]


def get_venues_needing_enrichment(limit: int) -> list[sqlite3.Row]:
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM venues WHERE status = 'NEW' ORDER BY created_at LIMIT ?",
            (limit,),
        ).fetchall()


def update_venue(venue_id: str, fields: dict) -> None:
    if not fields:
        return
    fields = dict(fields)
    fields["updated_at"] = "CURRENT_TIMESTAMP_PLACEHOLDER"
    set_clause = ", ".join(f"{k} = :{k}" for k in fields if k != "updated_at")
    set_clause += ", updated_at = datetime('now')"
    fields.pop("updated_at")
    fields["venue_id"] = venue_id
    with get_conn() as conn:
        conn.execute(f"UPDATE venues SET {set_clause} WHERE venue_id = :venue_id", fields)
        conn.commit()


def upsert_menu_source(menu_source: dict) -> None:
    with get_conn() as conn:
        # one primary menu_source per venue: replace if exists
        conn.execute(
            "DELETE FROM menu_sources WHERE venue_id = ? AND is_primary = 1",
            (menu_source["venue_id"],),
        )
        conn.execute(
            """
            INSERT INTO menu_sources (
                menu_source_id, venue_id, menu_url, menu_source_type,
                menu_status, menu_confidence, is_primary, last_checked_at
            ) VALUES (
                :menu_source_id, :venue_id, :menu_url, :menu_source_type,
                :menu_status, :menu_confidence, 1, datetime('now')
            )
            """,
            menu_source,
        )
        conn.commit()


def add_manual_review(review_id: str, venue_id: str, stage: str, reason: str) -> None:
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO manual_review (review_id, venue_id, stage, reason) VALUES (?, ?, ?, ?)",
            (review_id, venue_id, stage, reason),
        )
        conn.commit()


def export_rows() -> list[sqlite3.Row]:
    with get_conn() as conn:
        return conn.execute("SELECT * FROM v_export ORDER BY tier, city, venue_name").fetchall()


def manual_review_rows() -> list[sqlite3.Row]:
    with get_conn() as conn:
        return conn.execute(
            """
            SELECT r.review_id, r.stage, r.reason, r.created_at,
                   v.venue_id, v.venue_name, v.city, v.address, v.website_url
            FROM manual_review r
            JOIN venues v ON v.venue_id = r.venue_id
            WHERE r.resolved = 0
            ORDER BY r.created_at
            """
        ).fetchall()
