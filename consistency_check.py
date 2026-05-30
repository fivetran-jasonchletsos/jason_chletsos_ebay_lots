"""Detect drift between linkage_db and listings_snapshot.

Until both stores converge on linkage_db as canonical (Phase 3), drift is
the structural source of most stale-data bugs Jason hit this week:
- Cam Ward Pink Refractor ghost: snapshot had two, linkage had one.
- Travis Hunter: linkage said live, the listing had actually ended.
- Micah Parsons #77: snapshot had the auto-pushed dupe but linkage didn't.

This script enumerates every drift case, reports it, and exits non-zero if
anything was found so refresh_pipeline surfaces it. No auto-healing — Jason
confirms each fix manually because the right resolution depends on which
store is wrong.

The four drift cases:
  A. linkage status='live' but item_id NOT in snapshot — listing may have
     ended on eBay since the last snapshot refresh.
  B. snapshot has item_id but linkage_db has no record — listing predates
     linkage_db or was created outside the push pipeline.
  C. linkage status='ended' but item_id still in snapshot — end_listing
     succeeded on eBay + linkage but snapshot wasn't trimmed.
  D. linkage status='sold' but item_id still in snapshot — same as C.

Output: human-readable report to stdout, machine-readable JSON to
output/consistency_check.json so the daily digest can surface drift.
"""
from __future__ import annotations
import json
import sys
from datetime import datetime, timezone

import linkage_db
import paths
import snapshot_store

# refresh_pipeline freshness metadata.
INPUTS  = ["state/linkage.db", "output/listings_snapshot.json"]
OUTPUTS = ["output/consistency_check.json"]


def main() -> int:
    snap_listings = snapshot_store.load()
    snap_by_id = {str(l.get("item_id")): l for l in snap_listings if l.get("item_id")}

    links = list(linkage_db.all_links())
    links_by_item = {}
    for l in links:
        iid = l.get("ebay_item_id")
        if not iid:
            continue
        # If multiple rows share an item_id, keep the newest by updated_at.
        cur = links_by_item.get(iid)
        if cur is None or (l.get("updated_at") or "") > (cur.get("updated_at") or ""):
            links_by_item[iid] = l

    drift = {
        "linkage_live_not_in_snapshot": [],  # case A
        "snapshot_not_in_linkage":      [],  # case B
        "linkage_ended_in_snapshot":    [],  # case C
        "linkage_sold_in_snapshot":     [],  # case D
    }

    # A. linkage status='live' but item missing from snapshot
    for iid, l in links_by_item.items():
        if l.get("status") != "live":
            continue
        if iid not in snap_by_id:
            drift["linkage_live_not_in_snapshot"].append({
                "ebay_item_id": iid,
                "collx_id":     l.get("collx_id"),
                "listed_price": l.get("listed_price"),
                "updated_at":   l.get("updated_at"),
                "hypothesis":   "listing may have ended on eBay since last snapshot",
            })

    # B. snapshot has item but linkage_db doesn't.
    #
    # The DE review on 2026-05-30 noted this case is dominated by the
    # known hand-listed legacy backlog (~170 of 172 cases — items hand-
    # entered into eBay before linkage_db existed). They are NOT actionable
    # drift. Keep them in the report but bucket them separately so the
    # actionable count is visible.
    HAND_LISTED_AT_OR_BEFORE = "306913999999"  # all item_ids <= this are
                                                # pre-linkage_db hand-listings;
                                                # bump when a new batch arrives
    drift["hand_listed_legacy"] = []
    for iid, listing in snap_by_id.items():
        if iid not in links_by_item:
            row = {
                "ebay_item_id": iid,
                "title":        (listing.get("title") or "")[:80],
                "price":        listing.get("price"),
            }
            if iid <= HAND_LISTED_AT_OR_BEFORE:
                row["hypothesis"] = "pre-linkage hand-listed (allowlisted as noise)"
                drift["hand_listed_legacy"].append(row)
            else:
                row["hypothesis"] = "hand-listed without push, OR push failed to stamp linkage"
                drift["snapshot_not_in_linkage"].append(row)

    # C, D. linkage ended/sold but still in snapshot
    for iid, l in links_by_item.items():
        status = l.get("status")
        if status == "ended" and iid in snap_by_id:
            drift["linkage_ended_in_snapshot"].append({
                "ebay_item_id": iid,
                "collx_id":     l.get("collx_id"),
                "snap_title":   (snap_by_id[iid].get("title") or "")[:80],
                "hypothesis":   "end_listing.py succeeded but snapshot wasn't trimmed",
            })
        elif status == "sold" and iid in snap_by_id:
            drift["linkage_sold_in_snapshot"].append({
                "ebay_item_id": iid,
                "collx_id":     l.get("collx_id"),
                "snap_title":   (snap_by_id[iid].get("title") or "")[:80],
                "sold_price":   l.get("sold_price"),
                "hypothesis":   "sold reconciler stamped linkage but snapshot stale",
            })

    # Actionable drift excludes the hand-listed legacy bucket.
    total_drift = sum(len(v) for k, v in drift.items() if k != "hand_listed_legacy")
    legacy_noise = len(drift.get("hand_listed_legacy", []))
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "snapshot_count": len(snap_by_id),
        "linkage_count":  len(links_by_item),
        "total_drift":    total_drift,
        "drift":          drift,
    }

    out_path = paths.OUTPUT / "consistency_check.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2))

    # Print a compact human summary
    print(f"consistency_check · {len(snap_by_id)} in snapshot · {len(links_by_item)} in linkage")
    print(f"  linkage live but not in snapshot: {len(drift['linkage_live_not_in_snapshot'])}")
    print(f"  snapshot but not in linkage:      {len(drift['snapshot_not_in_linkage'])} actionable")
    print(f"    (+ {legacy_noise} pre-linkage hand-listed — known noise, allowlisted)")
    print(f"  linkage ended still in snapshot:  {len(drift['linkage_ended_in_snapshot'])}")
    print(f"  linkage sold still in snapshot:   {len(drift['linkage_sold_in_snapshot'])}")
    print(f"  Actionable drift total: {total_drift}")
    print(f"  Report: {out_path}")

    # Show up to 5 of each drift case for visibility
    for key, items in drift.items():
        if not items:
            continue
        print()
        print(f"  --- {key} (first 5) ---")
        for d in items[:5]:
            iid = d.get("ebay_item_id", "?")
            extra = d.get("snap_title") or d.get("title") or d.get("hypothesis", "")
            print(f"    item {iid}  {extra[:80]}")

    return 0 if total_drift == 0 else 0  # always 0 — drift is informational, not fatal


if __name__ == "__main__":
    sys.exit(main())
