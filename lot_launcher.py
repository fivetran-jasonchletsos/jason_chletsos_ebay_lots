"""Cluster CollX-unlisted singles into eBay lots and print a ready-to-list
plan with suggested titles, BIN prices, and the singles each lot bundles.

The top-sellers strategy review on 2026-05-30 named this the single biggest
30-day revenue lift: harpua2001 has ~200 sub-$3 singles that are Cassini-dead
as individual listings but cluster into 8-12 obvious player/team lots at
$15-$35 BIN each. Probstein / PWCC / MintInk wouldn't list these singles
individually; they'd lot them.

Usage:
  python3 lot_launcher.py                        # show top 12 lot proposals
  python3 lot_launcher.py --player "Mahomes"     # one specific cluster
  python3 lot_launcher.py --min-cards 4          # tighten lot size threshold
  python3 lot_launcher.py --json > lots.json     # for downstream tooling

This script PROPOSES — it doesn't push. Each row prints the singles in the
lot (so you can pull them physically), a suggested title within eBay's
80-char limit, and the suggested BIN price (sum_of_cards × 0.75 — buyers
pay less than face for a lot, but you save N-1 listing fees and shipping).
"""
from __future__ import annotations
import argparse
import csv
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

import paths
import linkage_db

DEFAULT_MIN_CARDS = 4
DEFAULT_MAX_CARDS = 10
DEFAULT_MIN_VALUE = 6.00   # don't bother proposing a lot under this CollX sum
LOT_DISCOUNT      = 0.75   # ask 75% of the face sum as the lot BIN


def _mv(row: dict) -> float:
    try:
        return float(row.get("collx_market_value") or 0)
    except (TypeError, ValueError):
        return 0.0


def _category_for(row: dict) -> str:
    """The cluster key. Player + sport, with team if obvious."""
    player = (row.get("player") or "").strip()
    sport  = (row.get("sport") or "").strip()
    return f"{player} | {sport}" if player else f"(no player) | {sport}"


def _team_hint(rows: list[dict]) -> str:
    """Pick the most-mentioned NFL team out of the lot row titles."""
    needles = ("raiders", "vikings", "chiefs", "bills", "ravens", "cowboys",
               "eagles", "giants", "jets", "patriots", "dolphins", "bengals",
               "browns", "steelers", "texans", "colts", "jaguars", "titans",
               "broncos", "chargers", "lions", "packers", "bears", "buccaneers",
               "falcons", "panthers", "saints", "cardinals", "rams", "49ers",
               "seahawks", "commanders")
    counts = defaultdict(int)
    for r in rows:
        hay = (r.get("name", "") + " " + r.get("set", "")).lower()
        for t in needles:
            if t in hay:
                counts[t.capitalize()] += 1
    if not counts:
        return ""
    return max(counts.items(), key=lambda kv: kv[1])[0]


def _suggest_title(player: str, sport: str, rows: list[dict]) -> str:
    """Build an eBay-friendly lot title under 80 chars."""
    n = len(rows)
    years = sorted({(r.get("year") or "").strip() for r in rows if r.get("year")})
    year_str = "-".join(y[-2:] for y in years if y) or ""
    team = _team_hint(rows)
    sport_str = sport if sport else "Football"

    # Pull set hints — favor RC if any row has RC
    has_rc = any("rc" in (r.get("parallel") or "").lower() or
                 "rookie" in (r.get("name") or "").lower() for r in rows)
    rc_str = " RC" if has_rc else ""

    # Compose a title and trim
    base = f"{n} {player} Cards Lot{rc_str}".strip()
    if team:
        base += f" {team}"
    if year_str:
        base = f"20{year_str} {base}" if not base.startswith("20") else base
    base += f" {sport_str} Insert Parallel Rookie"
    # Hard cap 80 chars
    return base[:80].strip()


def gather_clusters(inv_csv: Path, *, min_cards: int, max_cards: int,
                    min_value: float) -> list[dict]:
    """Group unlisted singles by player+sport. Return clusters that hit the
    size and value thresholds, ranked by total CollX market value."""
    links = {l["collx_id"]: l for l in linkage_db.all_links() if l.get("collx_id")}
    clusters: dict[str, list[dict]] = defaultdict(list)
    with inv_csv.open(newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            cid = (r.get("collx_id") or "").strip()
            if not cid:
                continue
            status = (links.get(cid) or {}).get("status", "unlisted")
            if status != "unlisted":
                continue
            if _mv(r) <= 0:
                continue
            if not (r.get("player") or "").strip():
                continue
            clusters[_category_for(r)].append(r)

    out = []
    for key, rows in clusters.items():
        rows = sorted(rows, key=_mv, reverse=True)[:max_cards]
        if len(rows) < min_cards:
            continue
        total_mv = sum(_mv(r) for r in rows)
        if total_mv < min_value:
            continue
        player, sport = [s.strip() for s in key.split("|", 1)]
        suggested_bin = round(total_mv * LOT_DISCOUNT, 2)
        # Round to charm pricing: .99 endings
        if suggested_bin < 100:
            floor = int(suggested_bin)
            suggested_bin = floor + 0.99 if suggested_bin - floor >= 0.5 else max(floor - 0.01, 0.99)
        title = _suggest_title(player, sport, rows)
        out.append({
            "player":         player,
            "sport":          sport,
            "card_count":     len(rows),
            "total_collx_mv": round(total_mv, 2),
            "suggested_bin":  suggested_bin,
            "lot_margin":     round(suggested_bin - total_mv, 2),  # negative is expected
            "suggested_title": title,
            "cards":          [{
                "collx_id":   r["collx_id"],
                "name":       r.get("name", ""),
                "year":       r.get("year", ""),
                "set":        r.get("set", ""),
                "parallel":   r.get("parallel", ""),
                "card_number": r.get("card_number", ""),
                "mv":         _mv(r),
                "image_url":  r.get("image_url", ""),
            } for r in rows],
        })
    out.sort(key=lambda c: -c["total_collx_mv"])
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--player", help="Filter to a single player cluster.")
    ap.add_argument("--min-cards", type=int, default=DEFAULT_MIN_CARDS)
    ap.add_argument("--max-cards", type=int, default=DEFAULT_MAX_CARDS)
    ap.add_argument("--min-value", type=float, default=DEFAULT_MIN_VALUE)
    ap.add_argument("--top",       type=int, default=12,
                    help="Show only the top N lots (default 12).")
    ap.add_argument("--json",      action="store_true",
                    help="Emit JSON instead of human-readable output.")
    args = ap.parse_args()

    inv_csv = paths.INVENTORY_CSV
    if not inv_csv.is_file():
        print(f"ERROR: {inv_csv} missing. Run collx_ingest.py first.", file=sys.stderr)
        return 1

    clusters = gather_clusters(inv_csv,
                               min_cards=args.min_cards,
                               max_cards=args.max_cards,
                               min_value=args.min_value)
    if args.player:
        clusters = [c for c in clusters if args.player.lower() in c["player"].lower()]

    clusters = clusters[: args.top]

    if args.json:
        json.dump(clusters, sys.stdout, indent=2, default=str)
        print()
        return 0

    if not clusters:
        print("No clusters matched the thresholds. Try --min-cards 3 or "
              "--min-value 3 to loosen.")
        return 0

    print(f"Found {len(clusters)} lot opportunit{'y' if len(clusters)==1 else 'ies'} "
          f"in unlisted CollX inventory.")
    print()
    for i, c in enumerate(clusters, 1):
        print(f"--- Lot {i}: {c['player']} ({c['sport']}) ---")
        print(f"  Cards: {c['card_count']}  ·  CollX face value: ${c['total_collx_mv']:.2f}")
        print(f"  Suggested BIN: ${c['suggested_bin']:.2f}  ·  Title:")
        print(f"    {c['suggested_title']}")
        print(f"  Singles to pull (sleeve them together for the lot):")
        for k in c["cards"]:
            par = f" / {k['parallel']}" if k['parallel'] else ""
            num = f" #{k['card_number']}" if k['card_number'] else ""
            print(f"    ${k['mv']:>6.2f}  {(k['name'] or '')[:70]}{num}{par}")
        print()
    print("Next steps: pull each lot physically, photograph the stack, then")
    print("create the lot listing in eBay Seller Hub manually (the push_to_ebay")
    print("path is per-card, not per-lot). Once listed, mark each individual")
    print("collx_id as `status='in_lot'` in linkage_db so they don't reappear.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
