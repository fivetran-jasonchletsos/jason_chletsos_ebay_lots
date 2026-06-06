#!/usr/bin/env python3
"""
Daily pricing cache validator.  Run this before promote.py to purge any
entries where PriceCharting returned a mismatched product (different sport /
set with the same card number).

Exit 0 always — pipeline should continue even if nothing is purged.
"""
import json, re, time
from pathlib import Path

CACHE_FILE = Path(__file__).parent / "pricing_cache.json"
DLQ_FILE   = Path(__file__).parent / "output" / "pricing_dlq.json"

# Words that are common to many card products and are not player/set identifiers.
NOISE = {
    'panini', 'topps', 'prizm', 'select', 'optic', 'donruss', 'chrome',
    'refractor', 'rookie', 'cards', 'card', 'silver', 'gold', 'blue',
    'red', 'green', 'pink', 'black', 'white', 'base', 'holo', 'foil',
    '2025', '2024', '2023', '2022', '2021', '2020', 'with', 'from',
    'football', 'basketball', 'baseball', 'hockey', 'pokemon', 'nfl', 'nba', 'mlb',
    'psa', 'bgs', 'sgc', 'rare', 'ultra', 'super', 'parallel', 'variation',
    'shock', 'wave', 'disco', 'flash', 'mojo', 'hyper', 'scope',
}


def _mismatch(query: str, matched_title: str) -> bool:
    q_toks = {w for w in re.findall(r'[a-z]{4,}', query.lower()) if w not in NOISE}
    m_toks = {w for w in re.findall(r'[a-z]{4,}', matched_title.lower())}
    return bool(q_toks) and not (q_toks & m_toks)


def main() -> None:
    if not CACHE_FILE.exists():
        print("No pricing_cache.json found — skipping.")
        return

    data = json.loads(CACHE_FILE.read_text())
    purged = []
    stale  = []
    now    = time.time()
    TTL_7D = 7 * 24 * 3600

    for k, v in list(data.items()):
        if not isinstance(v, dict):
            continue
        d = v.get("data") or {}
        matched = d.get("matched_title", "")
        ts      = v.get("ts", 0)

        # Purge confirmed mismatches
        if matched and _mismatch(k, matched):
            del data[k]
            purged.append({"key": k, "median": d.get("median"), "matched": matched})
            continue

        # Flag entries older than 7 days as stale (they missed TTL refresh somehow)
        if now - ts > TTL_7D:
            stale.append(k)

    CACHE_FILE.write_text(json.dumps(data, indent=2))

    dlq = {"ts": now, "purged": purged, "stale_keys": stale}
    DLQ_FILE.parent.mkdir(exist_ok=True)
    DLQ_FILE.write_text(json.dumps(dlq, indent=2))

    print(f"  Pricing cache: {len(purged)} bad matches purged, {len(stale)} stale entries flagged")
    print(f"  DLQ: {DLQ_FILE}")
    if purged:
        print("  Purged entries (first 10):")
        for e in purged[:10]:
            print(f"    ${e['median']}  {e['key'][:60]}  →  {e['matched']}")


if __name__ == "__main__":
    main()
