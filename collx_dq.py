"""collx_dq.py — CollX market-value data-quality gate.

Single entry point: validate_collx_value(card) -> (adjusted_value | None, reason)

None means "do not display — needs manual review."  A float means the value
passed all checks and has been multiplied by the appropriate pricing tier.

How to wire in:
  In sync_docs_json.py (and any other place that surfaces unlisted cards),
  replace the raw collx_market_value with the result of validate_collx_value.
  If the result is None, exclude the card from List These Next and log it to
  output/collx_dq_flags.json for the daily digest.

Design goals:
  1. Catch retail-vs-hobby parallel confusion (Cam Ward type).
  2. Catch outlier-inflated averages on low-demand players (Shough type).
  3. Hard-cap on value above which manual review is mandatory.
  4. All rules are data-driven from fields already in inventory.csv:
     name, set, parallel, notes, collx_market_value, player, year.
  5. Pure function — no I/O, no eBay calls, testable offline.
"""
from __future__ import annotations

import re
from typing import Optional

# ---------------------------------------------------------------------------
# Pricing tier multipliers — mirror the rules shown in seller.html
# ---------------------------------------------------------------------------
MULT_VETERAN      = 0.60   # retired / older veterans
MULT_MODERN       = 0.55   # modern non-RC non-star base
MULT_MODERN_RC    = 0.50   # modern non-star RCs
MULT_HOT_PARALLEL = 0.65   # numbered / premium parallels of any player
MULT_HOT_RC       = 0.70   # hot RCs + SPs (must qualify by player tier)

# ---------------------------------------------------------------------------
# Thresholds
# ---------------------------------------------------------------------------

# Any single CollX value above this trips a mandatory manual-review hold,
# regardless of player or parallel type.  At p99 the inventory tops out
# at ~$12.50; $40 is 3x that, which captures only genuine outliers.
MANUAL_REVIEW_THRESHOLD = 40.0

# A "suspicious spike": CollX value is more than this multiple above the
# per-set median for that parallel type.  Catches outlier-inflated averages
# even when no explicit BAD_COLLX note is present.  3x is conservative —
# a $1.24 median card would only trip at $3.72+, which is not a real concern.
# The check is most useful at higher absolute values.
SPIKE_RATIO_THRESHOLD = 5.0

# Minimum absolute value before the spike ratio check fires.  Below this
# dollar amount, ratio noise is irrelevant.
SPIKE_MIN_ABS = 8.0

# ---------------------------------------------------------------------------
# Retail-parallel set fragments — these are Mega/retail-exclusive parallels
# that CollX frequently misidentifies as the higher-value hobby equivalents.
# Match against card['set'].lower().
# ---------------------------------------------------------------------------
RETAIL_PARALLEL_FRAGMENTS = (
    "pink refractor",          # Topps Chrome Mega Exclusive — NOT hobby X-Fractor
    "pink x-fractor",          # Topps Chrome retail blaster
    "hot pink x-fractor",      # Topps Chrome retail blaster variant
    "pink lava refractor",     # Bowman University Chrome retail
    "pink prizm shock",        # Panini Select retail
    "pink prizm",              # Panini Prizm retail (non-hobby)
    "silver hyper prizm",      # Panini Phoenix retail blaster
    "press proofs blue",       # Donruss retail
)

# For retail parallels, a value above this per-SN tier warrants a hold.
# Keys are max serial-number (inclusive); "none" means unnumbered.
# Values are the maximum CollX dollar before the card is flagged.
# Rationale: a /250 retail parallel of a non-star RC should not exceed ~$15.
SN_RETAIL_CAP: dict[str, float] = {
    "1":    500.0,   # 1/1 anything can be high — let it through to manual review threshold
    "5":    200.0,
    "10":   100.0,
    "25":    50.0,
    "49":    30.0,
    "99":    20.0,
    "150":   12.0,
    "249":   10.0,
    "250":   15.0,   # Cam Ward case: $110 for a /250 retail parallel is impossible
    "499":    8.0,
    "none":   6.0,   # unnumbered retail parallel, e.g. base Prizm — should be very cheap
}

# ---------------------------------------------------------------------------
# Explicit bad-data players: any CollX value above their player cap is held.
# These are journeyman / low-demand players where a single eBay sale has
# permanently inflated the CollX "average."
# Format: lowercase player name -> max_allowed_collx_value
# ---------------------------------------------------------------------------
JOURNEYMAN_VALUE_CAP: dict[str, float] = {
    "tyler shough":       8.0,
    "dallas nussmeier":   8.0,
    "tommy devito":       6.0,
    "tim boyle":          4.0,
    "jake haener":        4.0,
    "hendon hooker":      5.0,
    "spencer rattler":    5.0,
}

# ---------------------------------------------------------------------------
# Helper: parse the SN (serial number) from the parallel field.
# parallel field examples: "RC, SN250", "SN10", "RC", ""
# Returns the SN as a string like "250", or "none" if unnumbered.
# ---------------------------------------------------------------------------
_SN_RE = re.compile(r"\bSN(\d+)\b", re.IGNORECASE)


def _parse_sn(parallel: str) -> str:
    """Return the serial-number string, or 'none' if unnumbered."""
    m = _SN_RE.search(parallel or "")
    return m.group(1) if m else "none"


def _retail_cap_for_sn(sn_str: str) -> float:
    """Return the retail-parallel value cap for this SN tier."""
    try:
        sn_int = int(sn_str)
    except (ValueError, TypeError):
        return SN_RETAIL_CAP["none"]
    for tier_str, cap in sorted(SN_RETAIL_CAP.items(), key=lambda x: (int(x[0]) if x[0] != "none" else 9999)):
        if tier_str == "none":
            continue
        if sn_int <= int(tier_str):
            return cap
    return SN_RETAIL_CAP["none"]


def _is_retail_parallel(set_name: str) -> bool:
    s = (set_name or "").lower()
    return any(frag in s for frag in RETAIL_PARALLEL_FRAGMENTS)


def _pricing_tier(card: dict) -> tuple[float, str]:
    """Return (multiplier, label) for the card's pricing tier."""
    parallel = (card.get("parallel") or "").lower()
    set_name  = (card.get("set") or "").lower()
    notes     = (card.get("notes") or "").lower()
    player    = (card.get("player") or "").lower()
    year_str  = str(card.get("year") or "")

    # Numbered parallels are "hot parallels" regardless of player
    has_sn = bool(_SN_RE.search(card.get("parallel") or ""))
    is_rc  = "rc" in parallel or "rookie" in set_name

    # Veteran heuristic: year <= 2020 and no RC tag
    try:
        yr = int(year_str)
    except (ValueError, TypeError):
        yr = 9999
    is_veteran = (yr <= 2020 and not is_rc)

    if is_veteran:
        return MULT_VETERAN, f"veteran ×{MULT_VETERAN}"
    if has_sn:
        return MULT_HOT_PARALLEL, f"numbered parallel ×{MULT_HOT_PARALLEL}"
    if is_rc:
        return MULT_MODERN_RC, f"modern RC ×{MULT_MODERN_RC}"
    return MULT_MODERN, f"modern ×{MULT_MODERN}"


# ---------------------------------------------------------------------------
# Main public function
# ---------------------------------------------------------------------------

def validate_collx_value(card: dict) -> tuple[Optional[float], str]:
    """Validate and adjust a CollX market value before surfacing it.

    Parameters
    ----------
    card : dict
        One row from inventory.csv as a dict.  Required keys:
        name, set, parallel, notes, collx_market_value, player, year.
        Missing keys are treated as empty string / 0.

    Returns
    -------
    (adjusted_value, reason)
        adjusted_value is None if the card should be withheld from
        display and queued for manual review.
        adjusted_value is a positive float if the value is trustworthy
        after applying the pricing-tier multiplier.
        reason is always a human-readable string explaining the decision.
    """
    name     = card.get("name") or ""
    set_name = card.get("set") or ""
    parallel = card.get("parallel") or ""
    notes    = card.get("notes") or ""
    player   = (card.get("player") or "").strip().lower()
    year_str = str(card.get("year") or "")

    # --- Parse raw CollX value ---
    raw_str = card.get("collx_market_value") or ""
    try:
        raw = float(raw_str) if str(raw_str).strip() else 0.0
    except (ValueError, TypeError):
        raw = 0.0

    if raw <= 0:
        return None, "no CollX value on record"

    # -----------------------------------------------------------------------
    # CHECK 1: Explicit BAD_COLLX flag in the notes field.
    # This is the human-curated kill switch.  If Jason or any pipeline step
    # has written BAD_COLLX: into the notes, honor it unconditionally.
    # -----------------------------------------------------------------------
    if notes.upper().startswith("BAD_COLLX"):
        reason_body = notes[len("BAD_COLLX"):].lstrip(":").strip()
        return None, f"BAD_COLLX flag: {reason_body or 'manual override'}"

    # -----------------------------------------------------------------------
    # CHECK 2: Hard cap — any value above MANUAL_REVIEW_THRESHOLD is held
    # for manual review regardless of player or parallel.
    # Legitimate high-value cards (Lamar Jackson SN6 = $38) are just below
    # the $40 threshold; $110 for any card in this inventory is a red flag.
    # -----------------------------------------------------------------------
    if raw >= MANUAL_REVIEW_THRESHOLD:
        return None, (
            f"CollX value ${raw:.2f} exceeds manual-review threshold "
            f"(${MANUAL_REVIEW_THRESHOLD:.0f}). Verify before listing."
        )

    # -----------------------------------------------------------------------
    # CHECK 3: Retail-parallel value cap by serial number.
    # Pink Refractor /250, Pink X-Fractor, Mega Exclusive pulls, etc. have
    # far lower demand than hobby parallels.  If CollX confuses them with
    # hobby versions the value can be 5-10x too high.
    # -----------------------------------------------------------------------
    if _is_retail_parallel(set_name):
        sn_str = _parse_sn(parallel)
        cap = _retail_cap_for_sn(sn_str)
        if raw > cap:
            return None, (
                f"Retail parallel ({set_name}) with SN={sn_str}: CollX ${raw:.2f} "
                f"exceeds retail-parallel cap ${cap:.2f}. "
                f"Likely hobby/retail confusion — verify card identity."
            )

    # -----------------------------------------------------------------------
    # CHECK 4: Journeyman player value cap.
    # For known low-demand QBs / bench players where a single outlier sale
    # has permanently inflated the CollX average, cap at the configured max.
    # -----------------------------------------------------------------------
    if player in JOURNEYMAN_VALUE_CAP:
        cap = JOURNEYMAN_VALUE_CAP[player]
        if raw > cap:
            return None, (
                f"{card.get('player', player)} is a journeyman/low-demand player. "
                f"CollX ${raw:.2f} exceeds outlier-adjusted cap ${cap:.2f}. "
                f"Single sale likely inflated average — use $4-6 floor instead."
            )

    # -----------------------------------------------------------------------
    # CHECK 5: Within-set spike detection.
    # If this card's CollX value is more than SPIKE_RATIO_THRESHOLD × the
    # median value for OTHER unnumbered cards in the same set, it may be an
    # outlier-inflated average (Shough type).
    #
    # Exemptions — spike check is skipped when:
    #   a) Card has a serial number <= 25.  Low-numbered cards legitimately
    #      command a premium over set-median; the spike ratio is expected.
    #   b) Card belongs to a known "star player" tier.  Mahomes, Burrow,
    #      Jackson, Williams, Jefferson etc. are expected to be outliers vs.
    #      the bulk of their sets.
    #   c) Fewer than 3 same-set peers are available.
    #
    # Requires the caller to enrich_with_set_peers() before calling.
    # -----------------------------------------------------------------------
    set_peers: list[float] = card.get("_set_peers") or []

    # Exemption (a): low-serial cards are legitimately expensive
    sn_for_spike = _parse_sn(parallel)
    try:
        sn_int_for_spike = int(sn_for_spike)
    except (ValueError, TypeError):
        sn_int_for_spike = 99999
    spike_sn_exempt = (sn_int_for_spike <= 25)

    # Exemption (b): recognised star players — spike ratio is expected
    STAR_PLAYERS = {
        "patrick mahomes", "lamar jackson", "joe burrow", "justin jefferson",
        "ceedee lamb", "jaylen waddle", "stefon diggs", "tyreek hill",
        "travis kelce", "caleb williams", "jayden daniels", "drake maye",
        "brock bowers", "marvin harrison jr", "tetairoa mcmillan",
        "aidan hutchinson", "bijan robinson", "puka nacua", "sam darnold",
        "jalen hurts", "josh allen", "tua tagovailoa", "dak prescott",
        "deebo samuel", "amon-ra st. brown", "cooper kupp",
    }
    spike_star_exempt = (player in STAR_PLAYERS)

    if (set_peers and raw >= SPIKE_MIN_ABS and len(set_peers) >= 3
            and not spike_sn_exempt and not spike_star_exempt):
        import statistics
        # Use only unnumbered peer values to avoid the low-SN premium inflating
        # the median and making the check useless.
        unnumbered_peers = [
            v for r2, v in zip(
                card.get("_set_peer_rows") or [],
                set_peers
            )
            if not _SN_RE.search((r2.get("parallel") or "") if isinstance(r2, dict) else "")
        ] or set_peers  # fallback: use all peers if row data not available
        if len(unnumbered_peers) >= 3:
            peer_median = statistics.median(unnumbered_peers)
            if peer_median > 0:
                ratio = raw / peer_median
                if ratio >= SPIKE_RATIO_THRESHOLD:
                    return None, (
                        f"Spike detected: CollX ${raw:.2f} is {ratio:.1f}x the set median "
                        f"${peer_median:.2f} ({len(unnumbered_peers)} unnumbered peers in "
                        f"'{set_name}'). Outlier-inflated average — manual review required."
                    )

    # -----------------------------------------------------------------------
    # All checks passed — apply the pricing-tier multiplier and return.
    # -----------------------------------------------------------------------
    mult, label = _pricing_tier(card)
    adjusted = round(raw * mult, 2)
    # Floor: never return less than $0.99 for a card with a real CollX value.
    adjusted = max(adjusted, 0.99)
    return adjusted, label


# ---------------------------------------------------------------------------
# Batch helper: enrich a list of inventory rows with _set_peers before
# calling validate_collx_value.  Call this once at the top of sync_docs_json
# or any agent that renders unlisted inventory.
# ---------------------------------------------------------------------------

def enrich_with_set_peers(rows: list[dict]) -> list[dict]:
    """Add '_set_peers' and '_set_peer_rows' keys to each row.

    _set_peers      : list[float] — CollX values of other cards in the same set.
    _set_peer_rows  : list[dict]  — the corresponding row dicts (needed so the
                      spike check can filter to unnumbered peers only).

    Modifies rows in place and returns them for chaining.
    """
    from collections import defaultdict
    # Group rows by set name
    set_rows: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        set_rows[r.get("set") or ""].append(r)

    for r in rows:
        own_set = r.get("set") or ""
        peer_rows: list[dict] = []
        peer_vals: list[float] = []
        for other in set_rows[own_set]:
            if other is r:
                continue
            other_str = other.get("collx_market_value") or ""
            try:
                v = float(other_str) if str(other_str).strip() else 0.0
            except (ValueError, TypeError):
                v = 0.0
            if v > 0:
                peer_rows.append(other)
                peer_vals.append(v)

        r["_set_peers"] = peer_vals
        r["_set_peer_rows"] = peer_rows
    return rows


# ---------------------------------------------------------------------------
# CLI: quick audit of the entire inventory.csv
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import csv
    import json
    from pathlib import Path

    REPO = Path(__file__).parent
    INV  = REPO / "inventory.csv"
    OUT  = REPO / "output" / "collx_dq_flags.json"

    rows = []
    with INV.open() as f:
        rows = list(csv.DictReader(f))

    enrich_with_set_peers(rows)

    flags: list[dict] = []
    passed: list[dict] = []

    for r in rows:
        mv_raw = r.get("collx_market_value") or ""
        try:
            mv = float(mv_raw) if str(mv_raw).strip() else 0.0
        except (ValueError, TypeError):
            mv = 0.0
        if mv <= 0:
            continue

        adj, reason = validate_collx_value(r)
        entry = {
            "name":           r.get("name", ""),
            "player":         r.get("player", ""),
            "set":            r.get("set", ""),
            "parallel":       r.get("parallel", ""),
            "collx_id":       r.get("collx_id", ""),
            "collx_mv":       mv,
            "adj_value":      adj,
            "reason":         reason,
        }
        if adj is None:
            flags.append(entry)
        else:
            passed.append(entry)

    # Sort flags by collx_mv descending — highest-risk first
    flags.sort(key=lambda x: x["collx_mv"], reverse=True)

    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps({"flagged": flags, "passed_count": len(passed)}, indent=2))

    print(f"CollX DQ audit complete.")
    print(f"  Flagged for review : {len(flags)}")
    print(f"  Passed             : {len(passed)}")
    print()
    if flags:
        print(f"{'CollX$':>8}  {'Player':<20}  Reason")
        print("-" * 80)
        for f in flags[:20]:
            print(f"  {f['collx_mv']:>6.2f}  {f['player']:<20}  {f['reason'][:55]}")
        if len(flags) > 20:
            print(f"  ... and {len(flags)-20} more — see {OUT}")
    print(f"\nFull output: {OUT}")
