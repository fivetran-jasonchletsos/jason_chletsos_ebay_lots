"""Single home for "is this CollX row the same physical card as that eBay
listing?" matching logic.

Before: push_to_ebay._detect_duplicates and build_pull_aside_pdf.gate both
implemented the same heuristic with subtle drift. linkage_backfill and
build_collx_vs_ebay each had their own SequenceMatcher version. Future
bug fixes to the matching rule never propagated.

After: every caller imports from here. One place to upgrade.

Matching tiers (cheapest first):
  1. linkage_db lookup by collx_id — exact, authoritative, no fuzzy
  2. Player whole-word + full card-number ("#NNN" or "#A-NNN") — title scan
"""
from __future__ import annotations
import re
import json
from pathlib import Path


# --------------------------------------------------------------------------- #
# Tier 1 — linkage_db authoritative answer                                    #
# --------------------------------------------------------------------------- #

def find_via_linkage(collx_id: str) -> dict | None:
    """If linkage_db says this collx_id is already linked to a 'live' eBay
    listing, return a dict {item_id, status, title, listed_price}. Else None.

    This is the authoritative check — much more reliable than fuzzy title
    matching because hand-edited eBay titles diverge from CollX naming."""
    if not collx_id:
        return None
    try:
        import linkage_db
        link = linkage_db.get_link(collx_id)
    except Exception:
        return None
    if not link:
        return None
    if link.get("status") != "live":
        return None
    return {
        "item_id":      str(link.get("ebay_item_id") or ""),
        "status":       link.get("status"),
        "title":        link.get("title") or "(linkage_db record)",
        "listed_price": link.get("listed_price"),
        "source":       "linkage_db",
    }


# --------------------------------------------------------------------------- #
# Tier 2 — fuzzy title scan with safe word boundaries                         #
# --------------------------------------------------------------------------- #

def card_number_from_title(title: str) -> str | None:
    """Extract a '#NNN' or '#A-NNN' token from a title. Returns the token
    without the leading '#', or None if no card-number token is present."""
    if not title:
        return None
    m = re.search(r'#([A-Za-z]{0,5}-?\d+)', title)
    return m.group(1) if m else None


def find_via_title(player: str, card_number: str, listings,
                   *, exclude_item_id: str | None = None) -> list[dict]:
    """Scan `listings` for entries whose title has the player as a WHOLE WORD
    AND the FULL card number ('#NNN' or '#A-NNN').

    Returns a list of matching listing dicts (each at least with item_id +
    title; price is included when present).

    Why whole-word: 'Drake' substring-matches 'Drake London'. Two different
    players. Whole-word stops it.
    Why full card-number: 'BDC-50' must NOT short-fall to '#50' or it
    collides with every #50 in any other set for the same player.
    """
    player = (player or "").strip().lower()
    card_number = (card_number or "").strip()
    if not player or not card_number:
        return []
    needle_num = f"#{card_number}".lower()
    player_re  = re.compile(rf"\b{re.escape(player)}\b")
    exclude    = str(exclude_item_id) if exclude_item_id else None

    hits = []
    for l in listings or []:
        iid = str(l.get("item_id") or "")
        if exclude and iid == exclude:
            continue
        t = (l.get("title") or "").lower()
        if player_re.search(t) and needle_num in t:
            hits.append({
                "item_id": iid,
                "title":   l.get("title", ""),
                "price":   l.get("price"),
                "source":  "fuzzy title",
            })
    return hits


# --------------------------------------------------------------------------- #
# High-level convenience: combine tiers 1 + 2                                 #
# --------------------------------------------------------------------------- #

def find_live_duplicates(*, collx_id: str = "", player: str = "",
                         card_number: str = "",
                         listings=None,
                         exclude_item_id: str | None = None) -> list[dict]:
    """Return every live duplicate of the described card.

    Order: linkage_db authoritative answer first (if collx_id provided),
    then fuzzy title scan against `listings` (if listings + player +
    card_number provided). Output is deduped by item_id.

    Callers that want only the authoritative tier-1 answer can use
    find_via_linkage() directly.
    """
    seen = set()
    out = []

    if collx_id:
        link = find_via_linkage(collx_id)
        if link and link["item_id"]:
            seen.add(link["item_id"])
            out.append(link)
        elif link:
            out.append(link)

    if listings is not None and player and card_number:
        for hit in find_via_title(player, card_number, listings,
                                  exclude_item_id=exclude_item_id):
            if hit["item_id"] in seen:
                continue
            seen.add(hit["item_id"])
            out.append(hit)

    return out
