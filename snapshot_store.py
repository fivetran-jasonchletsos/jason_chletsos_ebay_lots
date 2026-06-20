"""Single API for output/listings_snapshot.json.

Before: three places mutated the file (promote.py overwrites from eBay,
push_to_ebay.py appends after AddItem, end_listing.py removes after EndItem).
Each reimplemented the dict-or-list shape check, the json round-trip, and
the swallow-all try/except. They could and did drift.

After: every read/write goes through this module. All writes are atomic
(tempfile + os.replace) so concurrent readers in a refresh_pipeline wave
never see a half-written file.
"""
from __future__ import annotations
import json
import os
import tempfile
from pathlib import Path

import paths

# Canonical row schema. promote.py's fetch_listings writes a superset; the
# fields below are what we EXPECT every consumer to see. Missing fields are
# fine (consumers should use .get()) but downstream readers can rely on the
# top-level structure being a dict with a 'listings' list.
DEFAULT_LISTING_FIELDS = {
    "item_id":      "",
    "title":        "",
    "price":        0.0,
    "pic":          "",
    "url":          "",
    "category":     "Trading Card Singles",
    "condition":    "",
    "quantity":     1,
    "desc":         "",
    "listing_type": "BIN",
}


# --------------------------------------------------------------------------- #
# Internal helpers                                                            #
# --------------------------------------------------------------------------- #

def _normalize(raw) -> tuple[list, dict | None]:
    """Coerce snapshot file content into (listings_list, wrapper_dict_or_None).
    Handles the two historical shapes: a raw list, or a dict with a 'listings'
    key (and optionally other top-level metadata)."""
    if isinstance(raw, dict):
        return list(raw.get("listings") or []), raw
    if isinstance(raw, list):
        return list(raw), None
    return [], None


def _atomic_write(path: Path, payload) -> None:
    """Write JSON payload via tempfile + os.replace. Concurrent readers will
    see either the old file or the new file — never a partial write."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, separators=(",", ":"))
        os.replace(tmp_name, path)
    except Exception:
        try: os.unlink(tmp_name)
        except OSError: pass
        raise


# --------------------------------------------------------------------------- #
# Public API                                                                  #
# --------------------------------------------------------------------------- #

def load() -> list[dict]:
    """Return the listings list. Empty if file is missing or malformed."""
    if not paths.SNAPSHOT.is_file():
        return []
    try:
        raw = json.loads(paths.SNAPSHOT.read_text())
    except Exception:
        return []
    listings, _ = _normalize(raw)
    return listings


def load_raw() -> tuple[list, dict | None]:
    """Like load() but also returns the wrapper dict if present, so callers
    that want to preserve top-level metadata on write-back can do so."""
    if not paths.SNAPSHOT.is_file():
        return [], None
    try:
        raw = json.loads(paths.SNAPSHOT.read_text())
    except Exception:
        return [], None
    return _normalize(raw)


def _write_back(listings: list, wrapper: dict | None) -> None:
    if wrapper is not None:
        wrapper["listings"] = listings
        _atomic_write(paths.SNAPSHOT, wrapper)
    else:
        _atomic_write(paths.SNAPSHOT, listings)


def replace_all(listings: list[dict], *, wrapper_meta: dict | None = None,
                force: bool = False) -> bool:
    """Wholesale replace the snapshot. Used by refresh_snapshot.py after a
    fresh GetMyeBaySelling fetch. If wrapper_meta is provided, the snapshot
    is written as a dict (so the file preserves saved_at / market / pricing
    keys for callers that need them).

    Guard: refuses to overwrite a non-empty snapshot with an empty list. An
    empty fetch is the signature of a failed or throttled GetMyeBaySelling
    call (e.g. eBay error 518 "call usage limit reached", or a transient
    0-return) — never a real state for an active seller. Clobbering good data
    with 0 rows then starves every --no-fetch consumer (repricing, markdowns,
    offers). Pass force=True for a genuine full delist. Returns True if the
    snapshot was written, False if the write was skipped by the guard."""
    if not listings and not force:
        existing = load()
        if existing:
            print(f"  snapshot_store: refusing to overwrite {len(existing)} cached "
                  f"listings with 0 (failed/throttled fetch). Existing snapshot kept. "
                  f"Pass force=True to override.")
            return False
    if wrapper_meta is not None:
        wrapper = dict(wrapper_meta)
        wrapper["listings"] = listings
        _atomic_write(paths.SNAPSHOT, wrapper)
    else:
        _atomic_write(paths.SNAPSHOT, listings)
    return True


def append_listing(item_id: str, **fields) -> bool:
    """Add a listing row. No-op if item_id is already present. Returns True
    if appended, False if already present."""
    item_id = str(item_id)
    listings, wrapper = load_raw()
    if any(str(l.get("item_id")) == item_id for l in listings):
        return False
    row = {**DEFAULT_LISTING_FIELDS, **fields, "item_id": item_id}
    listings.append(row)
    _write_back(listings, wrapper)
    return True


def remove_listing(item_id: str) -> bool:
    """Drop a listing row. Returns True if removed, False if not present."""
    item_id = str(item_id)
    listings, wrapper = load_raw()
    before = len(listings)
    listings = [l for l in listings if str(l.get("item_id")) != item_id]
    if len(listings) == before:
        return False
    _write_back(listings, wrapper)
    return True


def get_listing(item_id: str) -> dict | None:
    """Look up a single row. Returns None if not present."""
    item_id = str(item_id)
    for l in load():
        if str(l.get("item_id")) == item_id:
            return l
    return None
