"""Robust multi-source list-price inference.

Pulls together every price signal we have for a card — eBay active median,
eBay sold history, SportsCardsPro (PSA10/9/8/raw), PriceCharting,
PokemonTCG.io, and CollX market value — drops outliers, and returns a single
recommended list price plus the working set so a human can sanity-check.

Outlier strategy: log-space MAD (median absolute deviation). Prices are
log-distributed in this hobby (a $2 card and a $200 card share a category),
so log-space resists asymmetric outliers better than raw-dollar MAD. Anything
more than 2.5 MAD from the log-median is dropped, with a floor that requires
at least 2 sources to survive (otherwise we keep them all and flag low
confidence).

Why not weighted mean? Weighted mean is sensitive to a single very-confident
high-print source mispricing a card. Median-with-MAD is bounded; an attacker
who controls one source can shift the answer by at most one MAD.

This module is pure (no I/O) and unit-testable. The caller passes a `sources`
dict identical to the one gather_pricing_sources() returns in promote.py,
optionally with extra keys for SCP / CollX added by the caller.
"""
from __future__ import annotations

import math
import statistics
from typing import Iterable

# Source-specific reliability priors. These bias which sources we trust when
# blending, but they DO NOT veto outlier detection — a high-prior source can
# still be dropped if it's an outlier vs the others.
SOURCE_PRIOR = {
    "sold_history":    1.00,   # your own past sales — ground truth
    "scp_psa10":       0.85,   # SportsCardsPro graded prices, very reliable
    "scp_psa9":        0.80,
    "scp_psa8":        0.75,
    "scp_graded":      0.75,
    "scp_ungraded":    0.70,
    "scp_loose":       0.65,
    "pricecharting":   0.75,
    "pokemontcg":      0.70,
    "collx_market":    0.75,
    "ebay_active":     0.55,   # asking prices, not actual sales — discount
}

# Minimum comp count for a source to be considered statistically meaningful.
MIN_COUNT = {
    "sold_history":    2,
    "ebay_active":     3,
    "pricecharting":   1,   # PC's "median" is already aggregated
    "pokemontcg":      1,   # TCGplayer aggregate
    "scp_psa10":       1,   # SCP guide is itself an aggregate
    "scp_psa9":        1,
    "scp_psa8":        1,
    "scp_graded":      1,
    "scp_ungraded":    1,
    "scp_loose":       1,
    "collx_market":    1,   # CollX gives a single number
}

# How many MAD-units away from the log-median earns a "drop as outlier" call.
# 2.5 is conservative — drops only egregious flyers.
OUTLIER_MAD_THRESHOLD = 2.5

# After we converge on a robust center, "list at" = center × this factor.
# 0.97 = 3% under blended comp, which lands between "competitive" and
# "leave money on the table". Tune per Jason's preference.
LIST_DISCOUNT = 0.97


def _log(x: float) -> float:
    return math.log(max(x, 0.01))


def _mad(values: list[float], center: float) -> float:
    if not values:
        return 0.0
    return statistics.median([abs(v - center) for v in values])


def _round_to_dot99(p: float) -> float:
    """Round to a charm-price ending. $X.99 below $100, $XX.95 between
    $100-$500, integer dollars above $500. Output is always >= $0.99 — never
    negative (was bug: p=0.30 used to round to -0.01)."""
    if p <= 0:
        return 0.99
    if p < 1:
        # Below a dollar, charm-rounding to floor-1+0.99 would go negative.
        # Floor at $0.99, the eBay minimum listing price.
        return 0.99
    if p < 100:
        floor_d = int(p)
        # If we're close to the integer below, use that .99; otherwise this
        # integer + .99 (e.g. 8.40 -> 7.99; 8.60 -> 8.99).
        candidate = floor_d - 0.01 if (p - floor_d) < 0.50 else floor_d + 0.99
        return max(candidate, 0.99)
    if p < 500:
        floor_d = int(p)
        return floor_d - 0.05 if (p - floor_d) < 0.50 else floor_d + 0.95
    return round(p)


def _flatten_sources(sources: dict) -> list[dict]:
    """Convert the source dict into a flat list of points with metadata.
    Each point is one (label, median, count, source_key) tuple.
    Sources without a usable numeric median are skipped."""
    out = []
    for key, body in (sources or {}).items():
        if not isinstance(body, dict):
            continue
        med = body.get("median")
        try:
            med = float(med) if med is not None else None
        except (TypeError, ValueError):
            med = None
        if med is None or med <= 0:
            continue
        count = body.get("count") or 1
        try:
            count = int(count)
        except (TypeError, ValueError):
            count = 1
        if count < MIN_COUNT.get(key, 1):
            continue
        out.append({
            "source":  key,
            "label":   body.get("label", key),
            "median":  med,
            "count":   count,
            "prior":   SOURCE_PRIOR.get(key, 0.5),
        })
    return out


def _confidence(kept: list[dict], dropped: list[dict]) -> str:
    """Qualitative confidence: more kept sources + low spread = high."""
    if not kept:
        return "none"
    if len(kept) == 1:
        return "low"
    medians = [k["median"] for k in kept]
    spread = (max(medians) - min(medians)) / statistics.median(medians)
    if len(kept) >= 4 and spread < 0.25:
        return "high"
    if len(kept) >= 3 and spread < 0.40:
        return "medium"
    return "low"


def infer_price(sources: dict, *, list_discount: float = LIST_DISCOUNT) -> dict:
    """Return a recommended list price plus a breakdown of how it was reached.

    Returns:
        dict with:
          recommended      float — the suggested list price, rounded
          center           float — the unrounded statistical center
          confidence       'none' | 'low' | 'medium' | 'high'
          basis            human-readable basis string
          kept             list of source breakdowns kept
          dropped          list of source breakdowns rejected as outliers
          per_source       full table of all sources with kept/dropped flag
          range_low        recommended × 0.85 (suggested floor)
          range_high       recommended × 1.10 (suggested ceiling)
    """
    flat = _flatten_sources(sources)
    if not flat:
        return {
            "recommended": None, "center": None, "confidence": "none",
            "basis": "no comps", "kept": [], "dropped": [], "per_source": [],
            "range_low": None, "range_high": None,
        }

    log_meds = [_log(p["median"]) for p in flat]
    log_center = statistics.median(log_meds)
    log_mad = _mad(log_meds, log_center)

    kept = []
    dropped = []
    for p, lm in zip(flat, log_meds):
        if log_mad > 0 and len(flat) >= 3:
            z = abs(lm - log_center) / log_mad
        else:
            z = 0.0
        p["mad_z"] = round(z, 2)
        if log_mad > 0 and z > OUTLIER_MAD_THRESHOLD and len(flat) >= 3:
            p["status"] = "outlier"
            dropped.append(p)
        else:
            p["status"] = "kept"
            kept.append(p)

    # Always keep at least 2 sources if we have them — collapsing to 1 makes
    # the recommendation no better than the previous priority-pick logic.
    if len(kept) < 2 and len(flat) >= 2:
        kept = flat[:]
        dropped = []
        for p in kept:
            p["status"] = "kept"

    # Weighted median across kept sources.
    weighted = []
    for p in kept:
        # Effective weight = prior × log10(count + 1). Saturates around count=20.
        w = p["prior"] * math.log10(p["count"] + 1 + 0.1)
        weighted.append((p["median"], max(w, 0.05)))

    weighted.sort(key=lambda x: x[0])
    total = sum(w for _, w in weighted)
    if total <= 0:
        center = statistics.median([p["median"] for p in kept])
    else:
        cum = 0.0
        center = weighted[-1][0]
        for v, w in weighted:
            cum += w
            if cum >= total / 2:
                center = v
                break

    recommended = _round_to_dot99(center * list_discount)

    # Basis line is the source list, ordered by influence.
    basis_parts = []
    for p in sorted(kept, key=lambda x: -x["prior"]):
        basis_parts.append(f"{p['label']} ${p['median']:.2f}")
    basis = " · ".join(basis_parts[:4])
    if len(kept) > 4:
        basis += f" · +{len(kept) - 4} more"
    if dropped:
        basis += f"  [dropped {len(dropped)} outlier{'s' if len(dropped) != 1 else ''}]"

    return {
        "recommended": recommended,
        "center":      round(center, 2),
        "confidence":  _confidence(kept, dropped),
        "basis":       basis,
        "kept":        [{"source": p["source"], "label": p["label"],
                         "median": p["median"], "count": p["count"],
                         "mad_z": p["mad_z"]} for p in kept],
        "dropped":     [{"source": p["source"], "label": p["label"],
                         "median": p["median"], "count": p["count"],
                         "mad_z": p["mad_z"]} for p in dropped],
        "per_source":  [{"source": p["source"], "label": p["label"],
                         "median": p["median"], "count": p["count"],
                         "mad_z": p["mad_z"], "status": p["status"]} for p in flat],
        "range_low":   round(recommended * 0.85, 2) if recommended else None,
        "range_high":  round(recommended * 1.10, 2) if recommended else None,
    }


# Adapter: build a sources dict from the raw row + CollX + SCP + sold history
def build_sources_for_row(*, collx_market: float | None = None,
                          scp_prices: dict | None = None,
                          ebay_market: dict | None = None,
                          sold_history_match: dict | None = None,
                          pricecharting: dict | None = None,
                          pokemontcg: dict | None = None) -> dict:
    """Convenience builder that wraps the heterogeneous inputs Jason has into
    the canonical `sources` dict that infer_price() expects.

    `scp_prices` should be the per-card dict from sportscardspro_prices.json,
    e.g. {"psa10_price": 95.0, "psa9_price": 45.0, "ungraded_price": 8.0, ...}.
    """
    out = {}
    if collx_market and float(collx_market) > 0:
        out["collx_market"] = {"median": float(collx_market), "count": 1,
                               "label": "CollX market"}
    if scp_prices:
        for src_key, scp_key, label in (
            ("scp_psa10",    "psa10_price",    "SCP PSA 10"),
            ("scp_psa9",     "psa9_price",     "SCP PSA 9"),
            ("scp_psa8",     "psa8_price",     "SCP PSA 8"),
            ("scp_graded",   "graded_price",   "SCP graded"),
            ("scp_ungraded", "ungraded_price", "SCP ungraded"),
            ("scp_loose",    "loose_price",    "SCP loose"),
        ):
            v = scp_prices.get(scp_key)
            try:
                fv = float(v) if v is not None else 0.0
            except (TypeError, ValueError):
                fv = 0.0
            if fv > 0:
                out[src_key] = {"median": fv, "count": 1, "label": label}
    if ebay_market and ebay_market.get("market_median"):
        out["ebay_active"] = {
            "median": float(ebay_market["market_median"]),
            "count":  int(ebay_market.get("comp_count") or 0) or 1,
            "label":  "eBay Active",
        }
    if sold_history_match and (sold_history_match.get("median") or 0) > 0:
        out["sold_history"] = {
            "median": float(sold_history_match["median"]),
            "count":  int(sold_history_match.get("count") or 1),
            "label":  "Your past sales",
        }
    if pricecharting and (pricecharting.get("median") or 0) > 0:
        out["pricecharting"] = {
            "median": float(pricecharting["median"]),
            "count":  int(pricecharting.get("count") or 1),
            "label":  "PriceCharting",
        }
    if pokemontcg and (pokemontcg.get("median") or 0) > 0:
        out["pokemontcg"] = {
            "median": float(pokemontcg["median"]),
            "count":  int(pokemontcg.get("count") or 1),
            "label":  "PokemonTCG.io",
        }
    return out


# ----- quick self-test ------------------------------------------------------

if __name__ == "__main__":
    # Mock: a card with a sane spread across sources
    sources = build_sources_for_row(
        collx_market=12.0,
        scp_prices={"psa10_price": 95.0, "psa9_price": 38.0, "ungraded_price": 11.5},
        ebay_market={"market_median": 14.5, "comp_count": 12},
        sold_history_match={"median": 11.0, "count": 4},
    )
    r = infer_price(sources)
    print("Recommended:", r["recommended"], "($ center", r["center"], ")")
    print("Confidence:", r["confidence"])
    print("Basis:", r["basis"])
    print("Kept:")
    for k in r["kept"]:
        print(f"  {k['label']:<22} ${k['median']:<8.2f} count={k['count']:<4} z={k['mad_z']}")
    if r["dropped"]:
        print("Dropped:")
        for k in r["dropped"]:
            print(f"  {k['label']:<22} ${k['median']:<8.2f} count={k['count']:<4} z={k['mad_z']}")

    # Mock: outlier present (one wildly high source)
    print("\n--- with outlier ---")
    sources["scp_psa10"]["median"] = 800.0  # absurd flyer
    r = infer_price(sources)
    print("Recommended:", r["recommended"], "($ center", r["center"], ")")
    print("Confidence:", r["confidence"])
    print("Basis:", r["basis"])
    print("Dropped:", [(d["label"], d["median"]) for d in r["dropped"]])
