#!/usr/bin/env python3
"""competitive_audit.py — quarterly differentiation audit for Harpua2001.

A card-collector-tuned fork of the Nexscope eBay differentiation tool.
Standalone script — NOT in the daily pipeline. Run on demand, typically
once a quarter when reviewing positioning across the catalog.

What it does
============
1. Reads the existing listings snapshot, sold history, market scrape and
   pricing sources you already maintain.
2. Filters to a user-chosen slice (e.g. "Charizard", "PSA 10", "1986 Topps").
3. Surfaces:
     - Price positioning vs market (overpriced / underpriced / parked at median)
     - Title-keyword gaps (which of your listings are missing the words
       buyers search for: grade, parallel, set, year, serial)
     - Selling-point coverage (PSA10, gem mint, fresh pack, etc.)
     - Pain-point exposure (centering, surface, edges, fake, trimmed)
     - Differentiation opportunities — quick-win + medium-lift
4. Writes a markdown report to output/competitive_audit.md.

Usage
=====
    python3 scripts/competitive_audit.py                                    # full catalog
    python3 scripts/competitive_audit.py --filter "Charizard"               # title contains
    python3 scripts/competitive_audit.py --filter "PSA 10" --limit 30
    python3 scripts/competitive_audit.py --category "pokemon" --json        # also dump JSON

Output
======
    output/competitive_audit.md     markdown report (default)
    output/competitive_audit.json   structured data (with --json)

This is intentionally text-only — no eBay API calls, no scraping. It
reads what's already on disk and reasons over it.
"""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

# --- Roster ---
AGENT_NAME = "Bobby Valentine"   # Mets manager — meticulous tactician, the audit guy
AGENT_ROLE = "Competitive Audit (Quarterly)"

ROOT = Path(__file__).resolve().parent.parent
LISTINGS_SNAPSHOT = ROOT / "output" / "listings_snapshot.json"
SOLD_HISTORY      = ROOT / "sold_history.json"
WATCHLIST_PLAN    = ROOT / "output" / "buyer_watchlist_plan.json"
REPORT_MD         = ROOT / "output" / "competitive_audit.md"
REPORT_JSON       = ROOT / "output" / "competitive_audit.json"


# =============================================================================
# Card-collector keyword libraries
# =============================================================================
# These replace the Nexscope electronics dictionaries. Tuned for sports
# cards, trading-card games (Pokémon, MTG), and graded items.

PAIN_POINT_KEYWORDS = {
    "centering": [
        "off center", "off-center", "miscut", "poor centering", "bad centering",
        "diamond cut", "skewed", "tilted",
    ],
    "surface": [
        "scratch", "scratched", "scuff", "scuffed", "print line", "print defect",
        "surface damage", "stain", "discolor", "stained", "marks on surface",
    ],
    "edges": [
        "edge wear", "white edges", "chipping", "chipped corner", "edge whitening",
        "frayed", "soft corners", "rough edges",
    ],
    "corners": [
        "dinged corners", "rounded corners", "soft corners", "corner ding",
        "corner wear", "creased corner",
    ],
    "authenticity": [
        "fake", "counterfeit", "reprint", "proxy", "boot", "fugazi",
        "not authentic", "questionable",
    ],
    "alteration": [
        "trimmed", "recolored", "doctored", "altered", "restored",
        "color enhanced",
    ],
    "grading_issue": [
        "questionable grade", "overgraded", "should be lower", "label damage",
        "cracked slab", "broken case", "wrong grade",
    ],
    "shipping": [
        "bent in shipping", "damaged in transit", "no top loader", "no penny sleeve",
        "poor packaging", "loose in envelope",
    ],
    "pricing": [
        "overpriced", "way too much", "not worth", "ripoff",
    ],
    "description_mismatch": [
        "not as described", "different card", "wrong year", "wrong parallel",
        "missing detail",
    ],
}

SELLING_POINT_KEYWORDS = {
    "grade_top": ["psa 10", "psa10", "bgs 10", "bgs9.5", "bgs 9.5", "sgc 10", "cgc 10", "gem mint", "pristine"],
    "grade_high": ["psa 9", "psa9", "bgs 9", "sgc 9", "near mint", "nm/m", "nm-m"],
    "rarity": ["1st edition", "first edition", "shadowless", "no symbol", "error card", "misprint", "ssp", "short print"],
    "parallel": ["refractor", "prizm", "holo", "holofoil", "rainbow", "gold", "atomic", "wave", "pulsar", "cracked ice", "negative"],
    "freshness": ["fresh from pack", "case break", "pulled today", "live break", "from sealed", "untouched"],
    "centering_good": ["well centered", "perfectly centered", "centered", "great centering"],
    "presentation": ["loader included", "top loader", "magnetic case", "screwdown", "one-touch", "sleeve included"],
    "provenance": ["from my collection", "personal collection", "long-time collector", "estate find"],
    "best_offer": ["best offer", "obo", "make offer", "open to offers"],
    "shipping_perks": ["free shipping", "ships same day", "ships fast", "tracked", "signature confirmation"],
}

CATEGORY_KEYWORDS = {
    "pokemon": ["pokemon", "pokémon", "charizard", "pikachu", "blastoise", "venusaur", "mewtwo", "umbreon",
                "japanese", "vmax", "vstar", "gx", "ex", "tcg"],
    "sports": ["topps", "panini", "donruss", "bowman", "fleer", "upper deck",
               "rookie", "rc", "auto", "patch", "jersey card", "prizm"],
    "vintage": ["1986", "1989", "1990", "1991", "vintage", "junk wax", "ungraded"],
    "magic": ["mtg", "magic the gathering", "alpha", "beta", "unlimited", "revised"],
}

# Title features we expect for a "complete" listing on a graded card.
# Missing any of these is a positioning weakness.
EXPECTED_TITLE_FEATURES = [
    ("player_or_card", r"\b[A-Z][a-z]+\b"),                        # at least one proper noun
    ("year", r"\b(19|20)\d{2}\b"),                                  # 4-digit year
    ("set_or_series", r"\b(?:Topps|Panini|Donruss|Bowman|Fleer|Pokemon|Pokémon|MTG|Magic|Prizm|Mosaic|Optic|Select|Chronicles|Heritage|Stadium)\b"),
    ("grade_or_condition", r"\b(?:PSA|BGS|SGC|CGC|NM|GEM|MT|RAW|Ungraded|Mint)\s*\d*"),
    ("parallel_or_variant", r"\b(?:Refractor|Prizm|Holo|Rainbow|Gold|Silver|Pulsar|Wave|Atomic|1st|First|Shadowless|RC|Rookie)\b"),
]


# =============================================================================
# Data shape
# =============================================================================
@dataclass
class Listing:
    item_id: str
    title: str
    price: float
    market: dict[str, Any] = field(default_factory=dict)
    pricing: dict[str, Any] = field(default_factory=dict)

    @property
    def market_flag(self) -> str:
        return (self.market or {}).get("flag", "UNKNOWN") or "UNKNOWN"

    @property
    def market_median(self) -> float | None:
        v = (self.market or {}).get("market_median")
        return float(v) if v is not None else None

    @property
    def gap_pct(self) -> float | None:
        v = (self.market or {}).get("gap_pct")
        return float(v) if v is not None else None


@dataclass
class AuditResult:
    total: int
    matched: int
    by_market_flag: dict[str, int]
    title_feature_coverage: dict[str, float]
    pain_point_hits: dict[str, int]
    selling_point_hits: dict[str, int]
    top_overpriced: list[dict]
    top_underpriced: list[dict]
    missing_features: list[dict]
    differentiation_actions: list[dict]


# =============================================================================
# Helpers
# =============================================================================
def _money(n: float | None) -> str:
    if n is None: return "—"
    return f"${n:,.2f}"

def _pct(n: float | None) -> str:
    if n is None: return "—"
    return f"{n:+.1f}%"

def _load_snapshot() -> tuple[list[Listing], dict]:
    if not LISTINGS_SNAPSHOT.exists():
        raise SystemExit(f"  Missing {LISTINGS_SNAPSHOT}. Run inventory_agent.py first to refresh.")
    raw = json.loads(LISTINGS_SNAPSHOT.read_text())
    rows = []
    for L in raw.get("listings", []):
        if not isinstance(L, dict): continue
        item_id = str(L.get("item_id", "")) or ""
        if not item_id: continue
        rows.append(Listing(
            item_id=item_id,
            title=str(L.get("title") or ""),
            price=float(L.get("price") or 0.0),
            market=(raw.get("market") or {}).get(item_id, {}) or {},
            pricing=(raw.get("pricing") or {}).get(item_id, {}) or {},
        ))
    return rows, raw

def _filter(rows: list[Listing], q: str | None, category: str | None) -> list[Listing]:
    out = rows
    if q:
        ql = q.lower()
        out = [r for r in out if ql in r.title.lower()]
    if category:
        keys = CATEGORY_KEYWORDS.get(category.lower(), [])
        if keys:
            out = [r for r in out if any(k in r.title.lower() for k in keys)]
    return out

def _title_coverage(rows: list[Listing]) -> dict[str, float]:
    if not rows: return {}
    counts: dict[str, int] = {f[0]: 0 for f in EXPECTED_TITLE_FEATURES}
    for r in rows:
        for name, pattern in EXPECTED_TITLE_FEATURES:
            if re.search(pattern, r.title, re.IGNORECASE):
                counts[name] += 1
    return {k: v / len(rows) for k, v in counts.items()}

def _missing_features(rows: list[Listing], limit: int = 20) -> list[dict]:
    """Listings missing required title signals. Sort by (price desc, gaps desc)
    so the most valuable broken listings rise to the top — that's where fixing
    the title returns the most revenue per minute of work."""
    miss = []
    for r in rows:
        gaps = [name for name, pattern in EXPECTED_TITLE_FEATURES
                if not re.search(pattern, r.title, re.IGNORECASE)]
        if gaps:
            miss.append({"item_id": r.item_id, "title": r.title, "price": r.price, "missing": gaps})
    # Primary sort: highest-price first (rev/min). Secondary: most gaps first.
    miss.sort(key=lambda m: (-(m["price"] or 0), -len(m["missing"])))
    return miss[:limit]

def _scan_keywords(rows: list[Listing], lib: dict[str, list[str]]) -> dict[str, int]:
    hits: Counter = Counter()
    for r in rows:
        haystack = r.title.lower()
        for cat, kws in lib.items():
            for k in kws:
                if k in haystack:
                    hits[cat] += 1
                    break
    return dict(hits.most_common())

def _market_distribution(rows: list[Listing]) -> dict[str, int]:
    c: Counter = Counter()
    for r in rows: c[r.market_flag] += 1
    return dict(c.most_common())

def _top_priced_gaps(rows: list[Listing], direction: str, n: int = 10) -> list[dict]:
    """direction='over' returns most overpriced, 'under' returns most underpriced."""
    have_gap = [r for r in rows if r.gap_pct is not None]
    if direction == "over":
        have_gap.sort(key=lambda r: -(r.gap_pct or 0))
    else:
        have_gap.sort(key=lambda r: (r.gap_pct or 0))
    out = []
    for r in have_gap[:n]:
        out.append({
            "item_id": r.item_id, "title": r.title[:80],
            "price": r.price, "market_median": r.market_median,
            "gap_pct": r.gap_pct,
        })
    return out

def _differentiation_actions(result: AuditResult) -> list[dict]:
    """Surface actions whose value scales with match count.

    Thresholds are *ratios* of the matched set, not absolutes, so a
    five-item Pokémon slice and a 200-item full-catalog scan both get
    useful suggestions.
    """
    actions = []
    n = max(result.matched, 1)

    # Title-feature gaps
    for feature, ratio in sorted(result.title_feature_coverage.items(), key=lambda kv: kv[1]):
        if ratio < 0.75:
            missing = int(round((1 - ratio) * n))
            if missing < 1: continue
            actions.append({
                "priority": "HIGH" if ratio < 0.4 else ("MEDIUM" if ratio < 0.65 else "LOW"),
                "lever": "Title",
                "action": f"Add `{feature}` to titles missing it — "
                          f"{(1 - ratio) * 100:.0f}% of listings lack it ({missing} items).",
                "impact": "Search match-rate — eBay Cassini weights title-keyword overlap heavily.",
            })

    # Market positioning — scale threshold to slice size
    over = result.by_market_flag.get("OVERPRICED", 0)
    under = result.by_market_flag.get("UNDERPRICED", 0)
    if over / n >= 0.15:    # ≥15% overpriced
        actions.append({
            "priority": "HIGH" if over / n >= 0.30 else "MEDIUM",
            "lever": "Pricing",
            "action": f"{over} of {n} listings ({over/n:.0%}) flagged OVERPRICED. "
                      f"Run `python3 repricing_agent.py --apply` after reviewing the table above.",
            "impact": "Lift watcher → buyer conversion. Overpriced sits, market-band moves.",
        })
    if under / n >= 0.08:   # ≥8% underpriced
        actions.append({
            "priority": "MEDIUM",
            "lever": "Pricing",
            "action": f"{under} listings priced below median. If rarity supports it, raise — leaving money on the table.",
            "impact": "Revenue per sale.",
        })

    sp = result.selling_point_hits
    if sp.get("grade_top", 0) == 0 and sp.get("grade_high", 0) == 0 and n >= 5:
        actions.append({
            "priority": "MEDIUM",
            "lever": "Positioning",
            "action": "Zero graded-card language. If any of these are slabs, surface PSA/BGS/SGC + grade in the title.",
            "impact": "Average sale price — graded cards command 2-4x raw.",
        })
    if sp.get("freshness", 0) == 0 and n >= 10:
        actions.append({
            "priority": "LOW",
            "lever": "Positioning",
            "action": "Seed 'Fresh from pack' / 'From sealed case' on items where it's true. Hobby buyers respond to provenance.",
            "impact": "Watcher engagement, message volume.",
        })
    if sp.get("centering_good", 0) == 0 and sp.get("grade_top", 0) == 0 and n >= 10:
        actions.append({
            "priority": "LOW",
            "lever": "Description",
            "action": "Add explicit centering language ('well-centered', 'sharp corners') in body copy — competitors almost never make centering claims.",
            "impact": "Conversion on raw cards where centering is the #1 buyer fear.",
        })

    return actions


# =============================================================================
# Report renderer
# =============================================================================
def render_markdown(filter_label: str, result: AuditResult) -> str:
    lines: list[str] = []
    lines.append(f"# Competitive audit — {filter_label}")
    lines.append("")
    lines.append(f"_Generated by **{AGENT_NAME}** ({AGENT_ROLE}). "
                 f"Scanned {result.total} active listings, "
                 f"matched **{result.matched}**._")
    lines.append("")
    lines.append("## Market positioning")
    lines.append("")
    lines.append("| Flag | Count |")
    lines.append("|---|---|")
    for flag, n in result.by_market_flag.items():
        lines.append(f"| `{flag}` | {n} |")
    lines.append("")

    lines.append("## Title feature coverage")
    lines.append("")
    lines.append("Each listing should ideally signal player, year, set, grade and parallel.")
    lines.append("")
    lines.append("| Feature | Coverage |")
    lines.append("|---|---|")
    for feature, ratio in result.title_feature_coverage.items():
        bar = "█" * round(ratio * 10) + "░" * (10 - round(ratio * 10))
        lines.append(f"| {feature} | `{bar}` {ratio:.0%} |")
    lines.append("")

    lines.append("## Selling-point hits in titles")
    lines.append("")
    if result.selling_point_hits:
        for cat, n in result.selling_point_hits.items():
            lines.append(f"- **{cat}** — {n} listing(s)")
    else:
        lines.append("_No selling-point keywords detected. Likely a positioning gap._")
    lines.append("")

    lines.append("## Pain-point exposure in titles")
    lines.append("")
    if result.pain_point_hits:
        for cat, n in result.pain_point_hits.items():
            lines.append(f"- **{cat}** — {n} listing(s) (intentional disclosure or marketing weakness)")
    else:
        lines.append("_No pain-point keywords detected — clean titles, but no buyer-fear addressing either._")
    lines.append("")

    if result.top_overpriced:
        lines.append("## Top 10 overpriced vs market")
        lines.append("")
        lines.append("| Item | Price | Market median | Gap |")
        lines.append("|---|---|---|---|")
        for r in result.top_overpriced:
            lines.append(f"| {r['title']} | {_money(r['price'])} | "
                         f"{_money(r['market_median'])} | {_pct(r['gap_pct'])} |")
        lines.append("")

    if result.top_underpriced:
        lines.append("## Top 10 underpriced vs market")
        lines.append("")
        lines.append("| Item | Price | Market median | Gap |")
        lines.append("|---|---|---|---|")
        for r in result.top_underpriced:
            lines.append(f"| {r['title']} | {_money(r['price'])} | "
                         f"{_money(r['market_median'])} | {_pct(r['gap_pct'])} |")
        lines.append("")

    if result.missing_features:
        lines.append("## Listings missing the most title features")
        lines.append("")
        lines.append("| Item | Price | Missing |")
        lines.append("|---|---|---|")
        for r in result.missing_features:
            lines.append(f"| {r['title'][:80]} | {_money(r['price'])} | {', '.join(r['missing'])} |")
        lines.append("")

    lines.append("## Differentiation actions")
    lines.append("")
    if not result.differentiation_actions:
        lines.append("_No actions surfaced — either too few matches or already strong positioning._")
    else:
        lines.append("| Priority | Lever | Action | Impact |")
        lines.append("|---|---|---|---|")
        for a in result.differentiation_actions:
            lines.append(f"| **{a['priority']}** | {a['lever']} | {a['action']} | {a['impact']} |")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("_This is a standalone quarterly tool, not part of the daily pipeline. "
                 "Re-run with `python3 scripts/competitive_audit.py` whenever positioning needs review._")
    return "\n".join(lines)


# =============================================================================
# Entry point
# =============================================================================
def main() -> int:
    print(f"  {AGENT_NAME} ({AGENT_ROLE}) reporting in.")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--filter", help="Substring filter on listing title (case-insensitive).")
    ap.add_argument("--category", choices=sorted(CATEGORY_KEYWORDS.keys()),
                    help="Predefined category filter (pokemon, sports, vintage, magic).")
    ap.add_argument("--limit", type=int, default=10, help="Top-N for over/underpriced tables (default 10).")
    ap.add_argument("--json", action="store_true", help="Also write JSON to output/competitive_audit.json.")
    args = ap.parse_args()

    rows, _raw = _load_snapshot()
    filtered = _filter(rows, args.filter, args.category)
    label_parts = []
    if args.category: label_parts.append(f"category={args.category}")
    if args.filter:   label_parts.append(f'filter="{args.filter}"')
    label = ", ".join(label_parts) if label_parts else "full catalog"

    print(f"  Scanned {len(rows)} listings, matched {len(filtered)} for {label}.")
    if not filtered:
        print("  No listings matched the filter. Nothing to audit.")
        return 0

    result = AuditResult(
        total=len(rows),
        matched=len(filtered),
        by_market_flag=_market_distribution(filtered),
        title_feature_coverage=_title_coverage(filtered),
        pain_point_hits=_scan_keywords(filtered, PAIN_POINT_KEYWORDS),
        selling_point_hits=_scan_keywords(filtered, SELLING_POINT_KEYWORDS),
        top_overpriced=_top_priced_gaps(filtered, "over", n=args.limit),
        top_underpriced=_top_priced_gaps(filtered, "under", n=args.limit),
        missing_features=_missing_features(filtered, limit=15),
        differentiation_actions=[],
    )
    result.differentiation_actions = _differentiation_actions(result)

    md = render_markdown(label, result)
    REPORT_MD.parent.mkdir(parents=True, exist_ok=True)
    REPORT_MD.write_text(md, encoding="utf-8")
    print(f"  Wrote {REPORT_MD}")

    if args.json:
        REPORT_JSON.write_text(json.dumps(asdict(result), indent=2, default=str), encoding="utf-8")
        print(f"  Wrote {REPORT_JSON}")

    print(f"  Differentiation actions surfaced: {len(result.differentiation_actions)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
