"""
linkage_db.py — thin SQLite ledger that links CollX cards to their eBay
listing state. The unanimous recommendation from the three-agent
architecture review on 2026-05-27.

CollX is source-of-truth for capture + market price (CollX Pro CSV export).
eBay is source-of-truth for commercial state (live, sold, ended). This DB
is the seam where they shake hands — keyed on collx_id, carrying the
eBay item_id assigned at push time, the listed price, the sold state.

Why SQLite (not DuckDB / Postgres): row-by-row writes from push_to_ebay,
small joins for the compare page, ~hundreds of rows, sqlite3 is in stdlib.
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

REPO_ROOT = Path(__file__).parent
DB_PATH = REPO_ROOT / "state" / "linkage.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS listings (
  collx_id              TEXT PRIMARY KEY,
  ebay_item_id          TEXT UNIQUE,
  sku                   TEXT,
  status                TEXT NOT NULL CHECK(status IN
                         ('unlisted','live','sold','ended','removed_from_collx')),
  listed_at             TEXT,
  listed_price          REAL,
  current_price         REAL,
  sold_at               TEXT,
  sold_price            REAL,
  buyer                 TEXT,
  last_seen_in_collx    TEXT,
  last_seen_on_ebay     TEXT,
  removed_from_collx_at TEXT,
  notes                 TEXT,
  created_at            TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at            TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_listings_status ON listings(status);
CREATE INDEX IF NOT EXISTS idx_listings_ebay_item_id ON listings(ebay_item_id);
CREATE INDEX IF NOT EXISTS idx_listings_sku ON listings(sku);

CREATE TABLE IF NOT EXISTS listing_history (
  history_id     INTEGER PRIMARY KEY AUTOINCREMENT,
  collx_id       TEXT NOT NULL,
  ebay_item_id   TEXT NOT NULL,
  event          TEXT NOT NULL,
  event_at       TEXT NOT NULL DEFAULT (datetime('now')),
  price          REAL,
  details        TEXT
);

CREATE INDEX IF NOT EXISTS idx_history_collx_id ON listing_history(collx_id);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init() -> None:
    """Create the schema if it doesn't exist. Safe to call repeatedly."""
    with connect() as conn:
        conn.executescript(SCHEMA)


def upsert_card(collx_id: str, **fields) -> None:
    """Insert or update a card row keyed on collx_id. Only mutates the
    fields you pass — preserves anything else. `updated_at` is always set."""
    if not collx_id:
        return
    init()
    fields = dict(fields)
    fields["updated_at"] = _now()
    with connect() as conn:
        # Check whether the row exists so we know whether to INSERT (with
        # required NOT NULL status) or UPDATE (without touching status).
        existing = conn.execute(
            "SELECT 1 FROM listings WHERE collx_id = ?", (collx_id,)
        ).fetchone()
        if existing:
            cols = ", ".join(f"{k} = :{k}" for k in fields)
            conn.execute(
                f"UPDATE listings SET {cols} WHERE collx_id = :collx_id",
                {**fields, "collx_id": collx_id},
            )
        else:
            if "status" not in fields:
                fields["status"] = "unlisted"
            fields["collx_id"] = collx_id
            cols = ", ".join(fields)
            vals = ", ".join(f":{k}" for k in fields)
            conn.execute(f"INSERT INTO listings({cols}) VALUES({vals})", fields)


def link_listing(collx_id: str, ebay_item_id: str, listed_price: float,
                 title: str = "", sku: str | None = None) -> None:
    """Called by push_to_ebay.py after a successful AddItem. Stamps the
    linkage row with the eBay ItemID and marks the card live."""
    if not collx_id or not ebay_item_id:
        return
    init()
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO listings(collx_id, ebay_item_id, sku, status, listed_at,
                                 listed_price, current_price, updated_at)
            VALUES(?, ?, ?, 'live', ?, ?, ?, ?)
            ON CONFLICT(collx_id) DO UPDATE SET
              ebay_item_id  = excluded.ebay_item_id,
              sku           = excluded.sku,
              status        = 'live',
              listed_at     = excluded.listed_at,
              listed_price  = excluded.listed_price,
              current_price = excluded.current_price,
              updated_at    = excluded.updated_at
            """,
            (collx_id, ebay_item_id, sku or collx_id, _now(),
             listed_price, listed_price, _now()),
        )
        conn.execute(
            """INSERT INTO listing_history(collx_id, ebay_item_id, event, price, details)
               VALUES(?, ?, 'listed', ?, ?)""",
            (collx_id, ebay_item_id, listed_price, title[:200]),
        )


def mark_sold(ebay_item_id: str, sold_price: float, sold_at: str | None = None,
              buyer: str | None = None) -> bool:
    """Called by the sold-reconciler. Returns True if the linkage row was
    updated (False if no CollX card maps to this ItemID — pre-CollX listing)."""
    if not ebay_item_id:
        return False
    init()
    with connect() as conn:
        row = conn.execute(
            "SELECT collx_id FROM listings WHERE ebay_item_id = ?", (ebay_item_id,)
        ).fetchone()
        if not row:
            return False
        when = sold_at or _now()
        conn.execute(
            """UPDATE listings SET status='sold', sold_at=?, sold_price=?,
                                   buyer=?, updated_at=?
               WHERE ebay_item_id = ?""",
            (when, sold_price, buyer, _now(), ebay_item_id),
        )
        conn.execute(
            """INSERT INTO listing_history(collx_id, ebay_item_id, event, price, details)
               VALUES(?, ?, 'sold', ?, ?)""",
            (row["collx_id"], ebay_item_id, sold_price, buyer or ""),
        )
        return True


def touch_seen_in_collx(collx_ids: list[str]) -> None:
    """Called by collx_ingest after a successful CSV import: every row that
    appeared in this import gets `last_seen_in_collx` bumped to now."""
    if not collx_ids:
        return
    init()
    when = _now()
    with connect() as conn:
        conn.executemany(
            "UPDATE listings SET last_seen_in_collx = ?, updated_at = ? WHERE collx_id = ?",
            [(when, when, cid) for cid in collx_ids],
        )


def mark_removed_from_collx(collx_id: str) -> None:
    init()
    with connect() as conn:
        conn.execute(
            """UPDATE listings SET status='removed_from_collx',
                                   removed_from_collx_at=?, updated_at=?
               WHERE collx_id = ? AND status != 'sold'""",
            (_now(), _now(), collx_id),
        )


def get_link(collx_id: str) -> dict | None:
    init()
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM listings WHERE collx_id = ?", (collx_id,)
        ).fetchone()
        return dict(row) if row else None


def get_link_by_ebay(ebay_item_id: str) -> dict | None:
    init()
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM listings WHERE ebay_item_id = ?", (ebay_item_id,)
        ).fetchone()
        return dict(row) if row else None


def list_unlisted_collx_ids() -> list[str]:
    init()
    with connect() as conn:
        rows = conn.execute(
            "SELECT collx_id FROM listings WHERE status='unlisted' ORDER BY updated_at DESC"
        ).fetchall()
        return [r["collx_id"] for r in rows]


def all_links() -> list[dict]:
    init()
    with connect() as conn:
        rows = conn.execute("SELECT * FROM listings ORDER BY updated_at DESC").fetchall()
        return [dict(r) for r in rows]


def summary() -> dict:
    init()
    with connect() as conn:
        counts = {r["status"]: r["n"] for r in conn.execute(
            "SELECT status, COUNT(*) AS n FROM listings GROUP BY status"
        )}
        total = conn.execute("SELECT COUNT(*) AS n FROM listings").fetchone()["n"]
        sold_value = conn.execute(
            "SELECT COALESCE(SUM(sold_price), 0) AS v FROM listings WHERE status='sold'"
        ).fetchone()["v"]
        live_value = conn.execute(
            "SELECT COALESCE(SUM(current_price), 0) AS v FROM listings WHERE status='live'"
        ).fetchone()["v"]
        return {
            "total":      total,
            "by_status":  counts,
            "live_value": live_value,
            "sold_value": sold_value,
        }


if __name__ == "__main__":
    init()
    print("Linkage DB initialized at:", DB_PATH)
    print("Summary:", summary())
