"""
collx_ingest.py — turn a CollX Pro CSV export into inventory.csv.

CollX Pro has no public developer API (verified 2026-05-25). The supported
integration path is the CSV download from Settings -> Export. This script reads
that export, maps it onto the schema that inventory_agent.py already consumes,
and writes inventory.csv in place (full replace — Jason hand-edits inside
CollX, not the CSV).

Run:
    python collx_ingest.py                                  # auto-find newest CollX CSV in ~/Downloads
    python collx_ingest.py path/to/download_user....csv     # explicit path

CollX columns observed in the export:
    added, collx_id, category, number, name, team, year, brand, set, flags,
    condition, front_image, back_image, market_value, asking_price,
    sold_for_price, purchase_price, location, notes, quantity

Output inventory.csv columns (extends the schema inventory_agent.py reads —
the agent ignores unknown columns, so additions are safe):
    name, year, set, card_number, player, sport, parallel, grade, grader,
    condition, quantity, acquired_price, image_url, notes, scp_id,
    collx_id, collx_market_value, collx_asking_price

eBay-side state (sold_at, sold_price, ebay_item_id) lives in linkage_db
now, not in inventory.csv — the CSV is a full-replace overwrite every run
and would destroy that state.
"""
from __future__ import annotations

import argparse
import csv
import glob
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import linkage_db

REPO_ROOT  = Path(__file__).parent
INV_PATH   = REPO_ROOT / "inventory.csv"

OUT_COLUMNS = [
    "name", "year", "set", "card_number", "player", "sport", "parallel",
    "grade", "grader", "condition", "quantity", "acquired_price", "image_url",
    "notes", "scp_id",
    "collx_id", "collx_market_value", "collx_asking_price",
]

# CollX category strings -> the keys inventory_agent.EBAY_CATEGORY expects.
CATEGORY_MAP = {
    "football":   "Football",
    "basketball": "Basketball",
    "baseball":   "Baseball",
    "hockey":     "Hockey",
    "pokemon":    "Pokemon",
    "pokémon":    "Pokemon",
    "tcg":        "Pokemon",
    "magic":      "Other",
}


def _find_latest_export() -> Path | None:
    home = Path.home()
    candidates = sorted(
        glob.glob(str(home / "Downloads" / "download_user*-*.csv")),
        key=os.path.getmtime,
        reverse=True,
    )
    return Path(candidates[0]) if candidates else None


def _build_name(row: dict) -> str:
    parts = []
    year = (row.get("year") or "").strip()
    set_ = (row.get("set") or "").strip()
    # CollX `set` often already starts with the year ("2025 Panini Phoenix"),
    # so only prepend year if the set doesn't already lead with it.
    if year and not set_.startswith(year):
        parts.append(year)
    if set_:               parts.append(set_)
    if row.get("name"):    parts.append(row["name"].strip())
    if row.get("number"):  parts.append(f"#{row['number'].strip()}")
    if row.get("flags"):   parts.append(f"({row['flags'].strip()})")
    return " ".join(parts).strip()


def _sport(row: dict) -> str:
    cat = (row.get("category") or "").strip().lower()
    return CATEGORY_MAP.get(cat, "Other")


def _condition(row: dict) -> str:
    raw = (row.get("condition") or "").strip()
    # CollX uses "RAW" to mean ungraded. The modernized eBay trading-card
    # category (261328) only accepts ConditionID 4000 = "Ungraded" for raw
    # cards, so we map RAW directly to "Ungraded" rather than coercing into
    # the older Near Mint / Excellent / etc. scale (which eBay rejects).
    return "Ungraded" if raw.upper() in ("", "RAW") else raw


def _notes(row: dict) -> str:
    chunks = []
    loc = (row.get("location") or "").strip()
    if loc: chunks.append(f"Location: {loc}")
    n = (row.get("notes") or "").strip()
    if n: chunks.append(n)
    return " / ".join(chunks)


def transform(row: dict) -> dict:
    return {
        "name":               _build_name(row),
        "year":               (row.get("year") or "").strip(),
        "set":                (row.get("set") or "").strip(),
        "card_number":        (row.get("number") or "").strip(),
        "player":             (row.get("name") or "").strip(),
        "sport":              _sport(row),
        "parallel":           (row.get("flags") or "").strip(),
        "grade":              "",
        "grader":             "",
        "condition":          _condition(row),
        "quantity":           (row.get("quantity") or "1").strip() or "1",
        "acquired_price":     (row.get("purchase_price") or "").strip(),
        "image_url":          (row.get("front_image") or "").strip(),
        "notes":              _notes(row),
        "scp_id":             "",
        "collx_id":           (row.get("collx_id") or "").strip(),
        "collx_market_value": (row.get("market_value") or "").strip(),
        "collx_asking_price": (row.get("asking_price") or "").strip(),
    }


def ingest(src: Path, dst: Path = INV_PATH) -> dict:
    if not src.is_file():
        raise FileNotFoundError(f"CollX CSV not found: {src}")

    rows_in: list[dict] = []
    with src.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        rows_in = list(reader)

    skipped_sold = 0
    skipped_blank = 0
    out_rows: list[dict] = []
    for r in rows_in:
        if (r.get("sold_for_price") or "").strip():
            skipped_sold += 1
            continue
        if not (r.get("collx_id") or "").strip() and not (r.get("name") or "").strip():
            skipped_blank += 1
            continue
        out_rows.append(transform(r))

    with dst.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=OUT_COLUMNS)
        writer.writeheader()
        writer.writerows(out_rows)

    # Linkage DB handshake — CollX import is the canonical "seen in CollX"
    # signal. We touch every imported card, auto-create new ones as
    # unlisted, and flag rows that disappeared from CollX (likely sold or
    # hand-deleted) so the dashboard can surface them.
    now_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")
    seen_ids = [r["collx_id"] for r in out_rows if r.get("collx_id")]

    new_in_linkage = 0
    for cid in seen_ids:
        if linkage_db.get_link(cid) is None:
            linkage_db.upsert_card(
                cid,
                status="unlisted",
                last_seen_in_collx=now_iso,
                notes="auto-created on CollX import",
            )
            new_in_linkage += 1

    linkage_db.touch_seen_in_collx(seen_ids)

    seen_set = set(seen_ids)
    removed_count = 0
    for link in linkage_db.all_links():
        cid = link.get("collx_id")
        if not cid or cid in seen_set:
            continue
        if link.get("status") in ("unlisted", "live"):
            linkage_db.mark_removed_from_collx(cid)
            removed_count += 1

    sports = {}
    has_photo = 0
    has_collx_mv = 0
    has_asking = 0
    for r in out_rows:
        sports[r["sport"]] = sports.get(r["sport"], 0) + 1
        if r["image_url"]: has_photo += 1
        if r["collx_market_value"]: has_collx_mv += 1
        if r["collx_asking_price"]: has_asking += 1

    return {
        "src":            str(src),
        "dst":            str(dst),
        "rows_in":        len(rows_in),
        "rows_out":       len(out_rows),
        "skipped_sold":   skipped_sold,
        "skipped_blank":  skipped_blank,
        "by_sport":       sports,
        "with_photo":     has_photo,
        "with_collx_mv":  has_collx_mv,
        "with_asking":    has_asking,
        "linkage_new":    new_in_linkage,
        "linkage_removed": removed_count,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("path", nargs="?", help="Path to CollX CSV. Defaults to the newest download_user*.csv in ~/Downloads.")
    args = ap.parse_args()

    src = Path(args.path) if args.path else _find_latest_export()
    if not src:
        print("Could not find a CollX CSV in ~/Downloads (looked for download_user*-*.csv).")
        print("Pass the path explicitly:  python collx_ingest.py path/to/export.csv")
        return 2

    print(f"Reading {src}")
    summary = ingest(src)
    print()
    print(f"Wrote {summary['rows_out']} rows -> {summary['dst']}")
    if summary["skipped_sold"]:
        print(f"  skipped {summary['skipped_sold']} sold rows (sold_for_price present)")
    if summary["skipped_blank"]:
        print(f"  skipped {summary['skipped_blank']} blank rows")
    print()
    print("By sport:")
    for sport, count in sorted(summary["by_sport"].items(), key=lambda kv: -kv[1]):
        print(f"  {sport:<12} {count}")
    print()
    print(f"With photo:          {summary['with_photo']} / {summary['rows_out']}")
    print(f"With CollX market:   {summary['with_collx_mv']} / {summary['rows_out']}")
    print(f"With CollX asking:   {summary['with_asking']} / {summary['rows_out']}")
    print()
    print(f"Linkage DB: {summary['linkage_new']} new card(s) auto-created as unlisted")
    print(f"Linkage DB: {summary['linkage_removed']} card(s) marked removed_from_collx (no longer in export)")
    print()
    print("Next: python inventory_agent.py   to refresh docs/inventory.html with multi-source pricing.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
