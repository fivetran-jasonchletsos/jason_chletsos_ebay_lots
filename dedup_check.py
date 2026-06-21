"""dedup_check.py — sold-aware duplicate guard for scan batches.

The oversells of 2026-06-19 happened because cards that had already SOLD (and
thus left the active-listings snapshot) got re-posted. Checking only against
active listings can't catch that. This guard checks every candidate against:

  1. ACTIVE listings (output/listings_snapshot.json)
  2. Recent SALES   (sold_history.json — the last 90 days of orders)
  3. Other candidates in the SAME batch set (within-batch repeats)

Anything matching any of the three is HELD, never posted. Run this before
post_from_scan.py on any batch_scan*.json set.

    python3 dedup_check.py output/batch_scan212.json output/batch_scan213.json ...
        -> writes <batch>_new.json (uniques only) for each, prints a breakdown.
"""
from __future__ import annotations
import json, re, sys
from pathlib import Path

REPO = Path(__file__).parent
SNAP = REPO / "output" / "listings_snapshot.json"
SOLD = REPO / "sold_history.json"

BRANDS = {'select','prizm','optic','phoenix','mosaic','chrome','donruss','contenders',
          'prestige','rookies','tribute','obsidian','score','iconic','signature',
          'revolution','absolute','contours','finest','paragon'}
PARALLELS = {'turbocharged','silver','purple','red','blue','green','gold','orange',
             'pink','holo','zone','xfractor','refractor','auto','fractal','disco',
             'wave','shock','velocity','scope','prizmatic'}
STOP = {'football','panini','topps','the','rc','and'}


def toks(t: str) -> set:
    t = re.sub(r"[^a-z0-9 ]", " ", (t or "").lower())
    return set(w for w in t.split() if w not in STOP and len(w) > 1)


def _load_titles(path: Path, kind: str) -> list[tuple[str, set]]:
    if not path.is_file():
        return []
    raw = json.loads(path.read_text())
    items = raw if isinstance(raw, list) else (raw.get("listings") or list(raw.values()))
    out = []
    for it in items:
        if isinstance(it, dict):
            out.append((it.get("title") or it.get("Title") or "", None))
    return [(t, toks(t)) for t, _ in out if t]


def is_dup(ct: set, refs: list[tuple[str, set]]) -> tuple[bool, str]:
    """Same-card match: identical parallel-status + high token overlap, or
    same-brand + strong overlap. Returns (matched, matched_title)."""
    best, bm = 0.0, None
    for title, rt in refs:
        if not rt or (ct & PARALLELS) != (rt & PARALLELS):
            continue
        j = len(ct & rt) / len(ct | rt)
        if j > best:
            best, bm = j, title
    if bm:
        same_brand = (ct & BRANDS) == (toks(bm) & BRANDS)
        if best >= 0.85 or (best >= 0.72 and same_brand):
            return True, bm
    return False, ""


def main(paths: list[str]) -> int:
    active = _load_titles(SNAP, "active")
    sold = _load_titles(SOLD, "sold")
    print(f"  Guard refs: {len(active)} active listings, {len(sold)} recent sales")
    seen: list[tuple[str, set]] = []
    stats = {"new": 0, "held_active": 0, "held_sold": 0, "held_batch": 0}
    for p in paths:
        cards = json.loads(Path(p).read_text())
        new_cards = []
        for c in cards:
            ct = toks(c["title"])
            dba, _ = is_dup(ct, active)
            dbs, _ = is_dup(ct, sold)
            dbb, _ = is_dup(ct, seen)
            if dbs:
                stats["held_sold"] += 1
            elif dba:
                stats["held_active"] += 1
            elif dbb:
                stats["held_batch"] += 1
            else:
                new_cards.append(c); stats["new"] += 1
            seen.append((c["title"], ct))
        out = Path(p.replace(".json", "_new.json"))
        out.write_text(json.dumps(new_cards, indent=1))
    print(f"  NEW (postable): {stats['new']}")
    print(f"  HELD — already listed: {stats['held_active']}")
    print(f"  HELD — already SOLD (oversell blocked): {stats['held_sold']}")
    print(f"  HELD — within-batch repeat: {stats['held_batch']}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
