"""
lot_generator_agent.py — turn sub-economic singles into themed bundle lots.

The problem: ~half the unlisted CollX inventory has a CollX market value
below $3. After eBay fees + (free) shipping, those cards net negative if
listed individually. Throwing them away wastes inventory; listing them
individually wastes time.

The fix: bundle them into themed lots that DO sell on eBay. Sports-card
buyers search for "Lions team lot," "Caleb Williams rookie lot," "2024
Topps Chrome commons lot," etc. A $14.99 lot of 8 sub-$2 commons converts
better than the same 8 cards as singles.

v1 is heuristic only — no LLM. The rules below are the bundle shapes that
historically move on the platform. v2 can layer Claude on top once Jason
has eyeballed v1 output.

Inputs:
  inventory.csv             — joined on collx_id
  state/linkage.db          — only consider collx_ids with status='unlisted'

Outputs:
  output/lot_generator_plan.json
  docs/lots.html            — Lot Generator page

CLI:
  python3 lot_generator_agent.py             # dry-run, writes JSON + HTML
  python3 lot_generator_agent.py --apply     # NO-OP for v1 (no live push)
"""
from __future__ import annotations

import argparse
import csv
import html
import json
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import linkage_db
import promote

REPO_ROOT = Path(__file__).parent
CSV_PATH  = REPO_ROOT / "inventory.csv"
PLAN_PATH = REPO_ROOT / "output" / "lot_generator_plan.json"
REPORT    = REPO_ROOT / "docs"   / "lots.html"

# Candidate thresholds.
SUB_ECONOMIC_PRICE = 3.00   # cards under this don't net after fees+shipping
MIN_LOT_SIZE       = 3
MAX_LOT_SIZE       = 25
LOT_FLOOR_PRICE    = 9.99

# Bulk vs focused pricing multipliers (against sum of CollX market).
BULK_MULTIPLIER     = 0.60  # team, year, set, rookie-class lots
FOCUSED_MULTIPLIER  = 0.75  # player, parallel lots
BULK_PER_CARD_FLOOR = 1.50  # at minimum $1.50 per card in bulk lots
FOCUSED_FLOOR       = 7.99

# Minimal NFL player → team map for our hottest names. Expanded ad-hoc;
# anything not in here gets skipped from the "team lots" theme.
PLAYER_TO_TEAM: dict[str, str] = {
    "Patrick Mahomes II":  "Kansas City Chiefs",
    "Patrick Mahomes":     "Kansas City Chiefs",
    "Caleb Williams":      "Chicago Bears",
    "Drake Maye":          "New England Patriots",
    "Shedeur Sanders":     "Cleveland Browns",
    "Travis Hunter":       "Jacksonville Jaguars",
    "Cam Ward":            "Tennessee Titans",
    "Joe Burrow":          "Cincinnati Bengals",
    "Amon-Ra St. Brown":   "Detroit Lions",
    "Jared Goff":          "Detroit Lions",
    "Jahmyr Gibbs":        "Detroit Lions",
    "Sam LaPorta":         "Detroit Lions",
    "Tyler Shough":        "New Orleans Saints",
    "Dillon Gabriel":      "Cleveland Browns",
    "Quinn Ewers":         "Miami Dolphins",
    "Trevor Etienne":      "Carolina Panthers",
    "Bhayshul Tuten":      "Jacksonville Jaguars",
    "Matthew Golden":      "Green Bay Packers",
    "Tetairoa McMillan":   "Carolina Panthers",
    "Antwane Wells Jr.":   "Buffalo Bills",
    "Brock Bowers":        "Las Vegas Raiders",
    "Marvin Harrison Jr.": "Arizona Cardinals",
    "Malik Nabers":        "New York Giants",
    "Rome Odunze":         "Chicago Bears",
    "Jayden Daniels":      "Washington Commanders",
    "Bo Nix":              "Denver Broncos",
    "Michael Penix Jr.":   "Atlanta Falcons",
    "J.J. McCarthy":       "Minnesota Vikings",
}


# --------------------------------------------------------------------------- #
# Inventory load + candidate filter                                            #
# --------------------------------------------------------------------------- #

def _as_float(v: Any) -> float | None:
    try:
        f = float(v)
        return f if f > 0 else None
    except (TypeError, ValueError):
        return None


def load_inventory() -> list[dict]:
    if not CSV_PATH.exists():
        return []
    rows: list[dict] = []
    with CSV_PATH.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for r in reader:
            r = {k.strip(): (v or "").strip() for k, v in r.items() if k}
            if not r.get("name"):
                continue
            rows.append(r)
    return rows


def select_candidates(rows: list[dict]) -> list[dict]:
    """A card is a lot candidate if:
       - its linkage status is 'unlisted' (or unknown — pre-linkage rows),
       - AND its market value or asking price is sub-economic (or unknown).
    """
    unlisted = set(linkage_db.list_unlisted_collx_ids())
    # If linkage is empty, treat everything as eligible. Otherwise we'd
    # silently skip the entire inventory.
    use_linkage = bool(unlisted) or bool(linkage_db.all_links())

    candidates: list[dict] = []
    for r in rows:
        cid = r.get("collx_id") or ""
        if use_linkage and cid and cid not in unlisted:
            # we have linkage data and this card is live/sold/etc — skip.
            continue
        mv      = _as_float(r.get("collx_market_value"))
        asking  = _as_float(r.get("collx_asking_price"))
        is_unpriced       = mv is None
        is_sub_economic   = (mv is not None and mv < SUB_ECONOMIC_PRICE)
        is_low_asking     = (asking is not None and asking < SUB_ECONOMIC_PRICE)
        if is_unpriced or is_sub_economic or is_low_asking:
            r["_collx_market"] = mv or 0.0
            r["_team"] = PLAYER_TO_TEAM.get(r.get("player") or "")
            candidates.append(r)
    return candidates


# --------------------------------------------------------------------------- #
# Pricing                                                                      #
# --------------------------------------------------------------------------- #

def _price_bulk(cards: list[dict]) -> float:
    total_mv = sum(c["_collx_market"] for c in cards)
    by_count = len(cards) * BULK_PER_CARD_FLOOR
    return max(round(total_mv * BULK_MULTIPLIER, 2), by_count, LOT_FLOOR_PRICE)


def _price_focused(cards: list[dict]) -> float:
    total_mv = sum(c["_collx_market"] for c in cards)
    return max(round(total_mv * FOCUSED_MULTIPLIER, 2), FOCUSED_FLOOR, LOT_FLOOR_PRICE)


def _slug(s: str, max_len: int = 40) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-")
    return s[:max_len] or "lot"


def _clip_title(t: str) -> str:
    return re.sub(r"\s+", " ", t).strip()[:80]


# --------------------------------------------------------------------------- #
# Theme proposers                                                              #
# --------------------------------------------------------------------------- #

def propose_team_lots(candidates: list[dict]) -> list[dict]:
    """Group by NFL team. Need MIN_LOT_SIZE cards per team to make a lot."""
    by_team: dict[str, list[dict]] = defaultdict(list)
    for c in candidates:
        if c.get("_team"):
            by_team[c["_team"]].append(c)
    lots: list[dict] = []
    for team, cards in sorted(by_team.items()):
        if len(cards) < MIN_LOT_SIZE:
            continue
        # Cap lot size — split into multiple lots if oversized.
        chunks = [cards[i:i+MAX_LOT_SIZE] for i in range(0, len(cards), MAX_LOT_SIZE)]
        for idx, chunk in enumerate(chunks, start=1):
            if len(chunk) < MIN_LOT_SIZE:
                # tail chunk too small — fold back into prior lot if possible
                if lots and lots[-1]["theme"] == "team" and lots[-1]["_team"] == team:
                    prior = lots[-1]
                    prior["collx_ids"].extend(c["collx_id"] for c in chunk)
                    prior["card_count"] = len(prior["collx_ids"])
                    prior["_cards"].extend(chunk)
                    prior["total_collx_market"] = round(sum(x["_collx_market"] for x in prior["_cards"]), 2)
                    prior["suggested_price"] = _price_bulk(prior["_cards"])
                continue
            count = len(chunk)
            years = sorted({c.get("year") for c in chunk if c.get("year")})
            year_str = "-".join(years) if 1 <= len(years) <= 2 else (years[0] if years else "")
            year_prefix = f"{year_str} " if year_str else ""
            title = _clip_title(f"{count} {team} Football Card Lot {year_prefix}NFL Rookies Stars")
            lots.append({
                "lot_id": f"lot-team-{_slug(team)}-{idx:03d}",
                "title": title,
                "theme": "team",
                "theme_label": "Team Lots",
                "card_count": count,
                "collx_ids": [c["collx_id"] for c in chunk],
                "suggested_price": _price_bulk(chunk),
                "justification": f"{team} fans search team-name lots heavily. "
                                  f"{count} cards = strong perceived value at this price.",
                "total_collx_market": round(sum(c["_collx_market"] for c in chunk), 2),
                "_team": team,
                "_cards": chunk,
            })
    return lots


def propose_player_lots(candidates: list[dict]) -> list[dict]:
    """Same player, multiple cards. Tight bundle, focused pricing."""
    by_player: dict[str, list[dict]] = defaultdict(list)
    for c in candidates:
        p = c.get("player")
        if p:
            by_player[p].append(c)
    lots: list[dict] = []
    for player, cards in sorted(by_player.items()):
        if len(cards) < MIN_LOT_SIZE:
            continue
        chunks = [cards[i:i+10] for i in range(0, len(cards), 10)]
        for idx, chunk in enumerate(chunks, start=1):
            if len(chunk) < MIN_LOT_SIZE:
                continue
            count = len(chunk)
            # Distinctive set/parallel names for the title
            sets_used = sorted({(c.get("set") or "").split(" - ")[0] for c in chunk if c.get("set")})
            set_blurb = ", ".join(s.replace("2025 Panini ", "").replace("2025 Topps ", "")
                                  for s in sets_used[:3])
            title = _clip_title(f"{count} {player} Rookie Card Lot {set_blurb}")
            lots.append({
                "lot_id": f"lot-player-{_slug(player)}-{idx:03d}",
                "title": title,
                "theme": "player",
                "theme_label": "Player Lots",
                "card_count": count,
                "collx_ids": [c["collx_id"] for c in chunk],
                "suggested_price": _price_focused(chunk),
                "justification": f"PC collectors of {player} hunt multi-card lots to "
                                  f"complete parallels. {count} cards covers multiple sets.",
                "total_collx_market": round(sum(c["_collx_market"] for c in chunk), 2),
                "_player": player,
                "_cards": chunk,
            })
    return lots


def propose_set_year_lots(candidates: list[dict]) -> list[dict]:
    """Group by (year, set base) — commons-from-one-product lots."""
    def _set_base(s: str) -> str:
        return (s or "").split(" - ")[0].strip()

    by_key: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for c in candidates:
        year = c.get("year") or ""
        sb   = _set_base(c.get("set") or "")
        if not sb or not year:
            continue
        by_key[(year, sb)].append(c)

    lots: list[dict] = []
    for (year, sb), cards in sorted(by_key.items()):
        if len(cards) < 4:  # bulk lots want at least 4 to feel like a "lot"
            continue
        chunks = [cards[i:i+MAX_LOT_SIZE] for i in range(0, len(cards), MAX_LOT_SIZE)]
        for idx, chunk in enumerate(chunks, start=1):
            if len(chunk) < 4:
                continue
            count = len(chunk)
            # CollX set names like "2025 Panini Select" already lead with the
            # year — don't double-print it in the title.
            sb_no_year = sb[len(year):].strip() if sb.startswith(year) else sb
            title = _clip_title(f"{count} Card Lot {year} {sb_no_year} Football NFL Rookies Stars")
            lots.append({
                "lot_id": f"lot-set-{_slug(year+'-'+sb)}-{idx:03d}",
                "title": title,
                "theme": "set_year",
                "theme_label": "Set / Year Lots",
                "card_count": count,
                "collx_ids": [c["collx_id"] for c in chunk],
                "suggested_price": _price_bulk(chunk),
                "justification": f"{sb} buyers want set-builder lots. "
                                  f"{count} cards from the same product = clean bundle.",
                "total_collx_market": round(sum(c["_collx_market"] for c in chunk), 2),
                "_set": sb,
                "_year": year,
                "_cards": chunk,
            })
    return lots


def propose_rookie_class_lots(candidates: list[dict]) -> list[dict]:
    """All cards flagged as rookie ('RC' in parallel or in name) bundled by year."""
    by_year: dict[str, list[dict]] = defaultdict(list)
    for c in candidates:
        parallel = (c.get("parallel") or "").upper()
        name     = (c.get("name") or "").upper()
        is_rookie = "RC" in re.split(r"[,\s]+", parallel) or " RC " in f" {name} "
        # Also treat all 2025 Draft Picks cards as rookie-class
        set_      = (c.get("set") or "").lower()
        if "draft picks" in set_:
            is_rookie = True
        if not is_rookie:
            continue
        year = c.get("year") or ""
        if not year:
            continue
        by_year[year].append(c)

    lots: list[dict] = []
    for year, cards in sorted(by_year.items()):
        if len(cards) < MIN_LOT_SIZE:
            continue
        chunks = [cards[i:i+MAX_LOT_SIZE] for i in range(0, len(cards), MAX_LOT_SIZE)]
        for idx, chunk in enumerate(chunks, start=1):
            if len(chunk) < MIN_LOT_SIZE:
                continue
            count = len(chunk)
            title = _clip_title(f"{count} {year} NFL Rookie Card Lot Football RC Class")
            lots.append({
                "lot_id": f"lot-rookie-{_slug(year)}-{idx:03d}",
                "title": title,
                "theme": "rookie_class",
                "theme_label": "Rookie Class Lots",
                "card_count": count,
                "collx_ids": [c["collx_id"] for c in chunk],
                "suggested_price": _price_bulk(chunk),
                "justification": f"{year} NFL rookie class lot — collectors speculate "
                                  f"on the whole draft class. {count} RCs included.",
                "total_collx_market": round(sum(c["_collx_market"] for c in chunk), 2),
                "_year": year,
                "_cards": chunk,
            })
    return lots


def propose_parallel_lots(candidates: list[dict]) -> list[dict]:
    """Bundle visually-shiny parallel cards together. Focused pricing."""
    PARALLEL_KEYWORDS = ("prizm", "refractor", "mosaic", "phoenix", "select",
                         "silver", "pink", "shock", "wave")
    shiny: list[dict] = []
    for c in candidates:
        s = (c.get("set") or "").lower()
        p = (c.get("parallel") or "").lower()
        if any(k in s for k in PARALLEL_KEYWORDS) or any(k in p for k in PARALLEL_KEYWORDS):
            shiny.append(c)
    if len(shiny) < MIN_LOT_SIZE:
        return []
    chunks = [shiny[i:i+12] for i in range(0, len(shiny), 12)]
    lots: list[dict] = []
    for idx, chunk in enumerate(chunks, start=1):
        if len(chunk) < MIN_LOT_SIZE:
            continue
        count = len(chunk)
        title = _clip_title(f"{count} Card Football Parallel Lot Prizm Refractor Mosaic Shiny")
        lots.append({
            "lot_id": f"lot-parallel-shiny-{idx:03d}",
            "title": title,
            "theme": "parallel",
            "theme_label": "Parallel / Shiny Lots",
            "card_count": count,
            "collx_ids": [c["collx_id"] for c in chunk],
            "suggested_price": _price_focused(chunk),
            "justification": f"Shiny-parallel lots photograph well and convert — "
                              f"{count} colored/refractor cards in one bundle.",
            "total_collx_market": round(sum(c["_collx_market"] for c in chunk), 2),
            "_cards": chunk,
        })
    return lots


# --------------------------------------------------------------------------- #
# Plan build                                                                   #
# --------------------------------------------------------------------------- #

def build_plan() -> dict:
    rows       = load_inventory()
    candidates = select_candidates(rows)

    lots: list[dict] = []
    lots += propose_team_lots(candidates)
    lots += propose_player_lots(candidates)
    lots += propose_set_year_lots(candidates)
    lots += propose_rookie_class_lots(candidates)
    lots += propose_parallel_lots(candidates)

    # Strip internal-only keys (the "_cards" reference is kept for HTML rendering
    # but stripped when writing JSON).
    by_theme: dict[str, int] = defaultdict(int)
    total_value = 0.0
    for lot in lots:
        by_theme[lot["theme_label"]] += 1
        total_value += lot["suggested_price"]

    return {
        "generated_at":   datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "candidate_count": len(candidates),
        "lot_count":      len(lots),
        "by_theme":       dict(by_theme),
        "total_lot_value": round(total_value, 2),
        "avg_lot_price":  round(total_value / len(lots), 2) if lots else 0.0,
        "lots":           lots,
    }


def save_plan(plan: dict) -> Path:
    PLAN_PATH.parent.mkdir(parents=True, exist_ok=True)
    # Serialize without the heavyweight `_cards` payload but keep everything else.
    serializable_lots = []
    for lot in plan["lots"]:
        clean = {k: v for k, v in lot.items() if not k.startswith("_")}
        # Embed minimal per-card snapshot so the JSON is self-describing.
        clean["cards"] = [{
            "collx_id":      c.get("collx_id"),
            "name":          c.get("name"),
            "player":        c.get("player"),
            "set":           c.get("set"),
            "year":          c.get("year"),
            "parallel":      c.get("parallel"),
            "collx_market":  c.get("_collx_market"),
            "image_url":     c.get("image_url"),
        } for c in lot.get("_cards", [])]
        serializable_lots.append(clean)
    out = {**plan, "lots": serializable_lots}
    PLAN_PATH.write_text(json.dumps(out, indent=2), encoding="utf-8")
    return PLAN_PATH


# --------------------------------------------------------------------------- #
# HTML render                                                                  #
# --------------------------------------------------------------------------- #

def _esc(s: Any) -> str:
    return html.escape(str(s or ""))


def _thumb_strip(cards: list[dict], max_thumbs: int = 8) -> str:
    items = []
    for c in cards[:max_thumbs]:
        url = c.get("image_url") or ""
        title = _esc(c.get("name") or c.get("collx_id") or "")
        if url:
            items.append(f'<img class="lot-thumb" src="{_esc(url)}" alt="{title}" loading="lazy" title="{title}">')
        else:
            items.append(f'<div class="lot-thumb lot-thumb--missing" title="{title}">no photo</div>')
    extra = len(cards) - max_thumbs
    if extra > 0:
        items.append(f'<div class="lot-thumb lot-thumb--more">+{extra}</div>')
    return '<div class="lot-thumb-strip">' + "".join(items) + '</div>'


def _card_list_html(cards: list[dict]) -> str:
    if not cards:
        return ""
    rows = []
    for c in cards:
        mv = c.get("_collx_market") or 0.0
        rows.append(
            f"<tr>"
            f"<td class='lot-row-id'>{_esc(c.get('collx_id', ''))}</td>"
            f"<td>{_esc(c.get('name') or '')}</td>"
            f"<td>{_esc(c.get('player') or '')}</td>"
            f"<td>{_esc(c.get('parallel') or '')}</td>"
            f"<td class='num'>${mv:.2f}</td>"
            f"</tr>"
        )
    return (
        "<table class='lot-card-table'><thead><tr>"
        "<th>collx_id</th><th>Card</th><th>Player</th><th>Parallel</th><th class='num'>CollX</th>"
        "</tr></thead><tbody>" + "".join(rows) + "</tbody></table>"
    )


def _render_lot_card(lot: dict) -> str:
    cards = lot.get("_cards", [])
    thumbs = _thumb_strip(cards)
    margin = lot["suggested_price"] - (lot["total_collx_market"] or 0.0)
    margin_class = "lot-margin-pos" if margin >= 0 else "lot-margin-neg"
    return f"""
    <article class="lot-card" data-theme="{_esc(lot['theme'])}">
      <header class="lot-card-head">
        <div class="lot-title-wrap">
          <div class="lot-theme-pill">{_esc(lot['theme_label'])}</div>
          <h3 class="lot-title">{_esc(lot['title'])}</h3>
          <p class="lot-justification">{_esc(lot['justification'])}</p>
        </div>
        <div class="lot-price-wrap">
          <div class="lot-price">${lot['suggested_price']:.2f}</div>
          <div class="lot-price-sub">{lot['card_count']} cards</div>
          <div class="lot-price-sub">CollX total ${lot['total_collx_market']:.2f}</div>
          <div class="lot-price-sub {margin_class}">{"+" if margin >= 0 else ""}${margin:.2f} margin</div>
        </div>
      </header>
      {thumbs}
      <footer class="lot-card-foot">
        <button class="btn btn-gold btn-sm" disabled
                title="Coming soon — needs push_lots_to_ebay.py">Push lot to eBay</button>
        <details class="lot-details">
          <summary>Show {lot['card_count']} card details and collx_id list</summary>
          {_card_list_html(cards)}
        </details>
      </footer>
    </article>
    """


def render_report(plan: dict) -> Path:
    # KPI strip
    kpis = f"""
    <div class="stat-grid">
      <div class="stat-card">
        <div class="num">{plan['candidate_count']}</div>
        <div class="lbl">Lot candidates (sub-$3 / unpriced)</div>
      </div>
      <div class="stat-card">
        <div class="num">{plan['lot_count']}</div>
        <div class="lbl">Proposed lots</div>
      </div>
      <div class="stat-card">
        <div class="num">${plan['total_lot_value']:,.0f}</div>
        <div class="lbl">Total lot value</div>
      </div>
      <div class="stat-card">
        <div class="num">${plan['avg_lot_price']:.2f}</div>
        <div class="lbl">Average lot price</div>
      </div>
    </div>
    """

    # Group lots by theme label for section rendering
    sections_html: list[str] = []
    by_label: dict[str, list[dict]] = defaultdict(list)
    for lot in plan["lots"]:
        by_label[lot["theme_label"]].append(lot)

    THEME_ORDER = [
        "Team Lots", "Player Lots", "Rookie Class Lots",
        "Set / Year Lots", "Parallel / Shiny Lots",
    ]
    for label in THEME_ORDER:
        lots_in = by_label.get(label) or []
        if not lots_in:
            continue
        cards_html = "\n".join(_render_lot_card(lot) for lot in lots_in)
        sections_html.append(f"""
        <section class="lot-section" id="theme-{_slug(label)}">
          <header class="lot-section-head">
            <h2 class="lot-section-title">{_esc(label)}</h2>
            <div class="lot-section-meta">{len(lots_in)} lots</div>
          </header>
          <div class="lot-grid">{cards_html}</div>
        </section>
        """)

    if not sections_html:
        sections_html.append(
            '<div class="lot-empty">No lot candidates found. '
            'Either inventory.csv is empty or every unlisted card already prices above $3.</div>'
        )

    body = f"""
    <div class="section-head section-head--inline">
      <div class="sh-title">
        <div class="eyebrow">AI-assisted bundle proposals · sub-economic singles</div>
        <h1 class="section-title">Lot <span class="accent">Generator</span></h1>
      </div>
      <div class="section-sub sh-sub">
        Cards with CollX market under $3 net negative after eBay fees and shipping
        if listed individually. This page proposes themed bundles that historically
        convert: by team, player, set/year, rookie class, and shiny parallels.
        Each lot has a title, justification, suggested price, and the underlying
        collx_id list. Push-to-eBay is wired in a follow-up agent
        (<code>push_lots_to_ebay.py</code>) — for now this is a planning surface.
      </div>
    </div>

    {kpis}

    <div class="lot-legend">
      <span><b>Pricing model:</b> bulk lots (team, set, rookie) priced at
        60% of CollX total or $1.50/card whichever is higher, floor $9.99. Focused
        lots (player, parallel) priced at 75% of CollX total, floor $7.99.</span>
    </div>

    {''.join(sections_html)}
    """

    extra_css = """
<style>
  .lot-legend { background: var(--surface); border: 1px solid var(--border); border-left: 3px solid var(--gold); border-radius: var(--r-md); padding: 12px 16px; margin: 14px 0 26px; color: var(--text-muted); font-size: 13px; line-height: 1.6; }
  .lot-legend b { color: var(--text); }
  .lot-section { margin: 36px 0; }
  .lot-section-head { display:flex; align-items:baseline; justify-content:space-between; border-bottom: 1px solid var(--border); padding-bottom: 10px; margin-bottom: 18px; }
  .lot-section-title { font-family: 'Fraunces', Georgia, serif; font-style: italic; font-weight: 500; font-variation-settings: 'opsz' 144, 'SOFT' 30, 'WONK' 1; letter-spacing: -0.01em; font-size: 26px; color: var(--text); margin: 0; }
  .lot-section-meta { color: var(--text-muted); font-size: 12px; text-transform: uppercase; letter-spacing: .08em; }
  .lot-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(380px, 1fr)); gap: 18px; }
  .lot-card { background: var(--surface); border: 1px solid var(--border); border-radius: var(--r-md); padding: 18px; display: flex; flex-direction: column; gap: 12px; transition: border-color 0.15s, transform 0.15s; }
  .lot-card:hover { border-color: var(--gold); transform: translateY(-1px); }
  .lot-card-head { display:flex; justify-content: space-between; align-items: flex-start; gap: 12px; }
  .lot-title-wrap { flex: 1 1 auto; min-width: 0; }
  .lot-theme-pill { display:inline-block; font-size: 10px; font-weight: 700; letter-spacing: 0.14em; text-transform: uppercase; color: var(--gold); background: rgba(201,164,74,0.10); border: 1px solid rgba(201,164,74,0.35); border-radius: 999px; padding: 3px 10px; margin-bottom: 8px; }
  .lot-title { font-family: 'Inter', system-ui, sans-serif; font-weight: 600; font-size: 15px; color: var(--text); margin: 0 0 6px 0; line-height: 1.35; }
  .lot-justification { font-size: 12px; color: var(--text-muted); line-height: 1.5; margin: 0; }
  .lot-price-wrap { text-align: right; flex: 0 0 auto; }
  .lot-price { font-family: 'Fraunces', Georgia, serif; font-style: italic; font-weight: 500; font-variation-settings: 'opsz' 144, 'SOFT' 30, 'WONK' 1; letter-spacing: -0.005em; font-size: 30px; color: var(--gold); line-height: 1; }
  .lot-price-sub { font-size: 10px; color: var(--text-muted); margin-top: 4px; font-variant-numeric: tabular-nums; }
  .lot-margin-pos { color: #6bbf6b; }
  .lot-margin-neg { color: #c66; }
  .lot-thumb-strip { display:flex; gap: 6px; flex-wrap: wrap; }
  .lot-thumb { width: 48px; height: 48px; object-fit: cover; border-radius: 4px; border: 1px solid var(--border); background: var(--surface-2); }
  .lot-thumb--missing, .lot-thumb--more { display:flex; align-items:center; justify-content:center; font-size: 9px; color: var(--text-dim); text-align: center; padding: 2px; }
  .lot-thumb--more { color: var(--gold); font-weight: 600; font-size: 12px; border-color: var(--gold); }
  .lot-card-foot { display:flex; flex-direction: column; gap: 10px; margin-top: auto; }
  .lot-details summary { cursor: pointer; color: var(--gold); font-size: 12px; padding: 4px 0; }
  .lot-card-table { width: 100%; border-collapse: collapse; margin-top: 8px; font-size: 11px; }
  .lot-card-table th, .lot-card-table td { padding: 6px 8px; border-bottom: 1px solid var(--border); text-align: left; color: var(--text-muted); }
  .lot-card-table th { color: var(--text-dim); text-transform: uppercase; font-size: 9px; letter-spacing: 0.1em; }
  .lot-card-table td.num, .lot-card-table th.num { text-align: right; font-variant-numeric: tabular-nums; }
  .lot-row-id { font-family: 'JetBrains Mono', monospace; font-size: 10px; color: var(--text-dim); }
  .lot-empty { text-align: center; padding: 60px 20px; color: var(--text-muted); border: 1px dashed var(--border); border-radius: var(--r-md); background: var(--surface); }
</style>
"""
    html_doc = promote.html_shell(
        "Lot Generator · Harpua2001",
        body,
        extra_head=extra_css,
        active_page="lots.html",
    )
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(html_doc, encoding="utf-8")
    return REPORT


# --------------------------------------------------------------------------- #
# CLI                                                                          #
# --------------------------------------------------------------------------- #

def main():
    ap = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    ap.add_argument("--apply", action="store_true",
                    help="v1 NO-OP — live push lives in push_lots_to_ebay.py (TBD).")
    args = ap.parse_args()

    plan = build_plan()
    save_plan(plan)
    out = render_report(plan)

    print(f"  Lot Generator")
    print(f"  Candidates:        {plan['candidate_count']}")
    print(f"  Proposed lots:     {plan['lot_count']}")
    for label, n in plan["by_theme"].items():
        print(f"    {label:24s} {n}")
    print(f"  Total lot value:   ${plan['total_lot_value']:,.2f}")
    print(f"  Average lot price: ${plan['avg_lot_price']:.2f}")
    print(f"  Plan:   {PLAN_PATH}")
    print(f"  Report: {out}")
    if args.apply:
        print("  --apply is a no-op for v1. Lot push agent (push_lots_to_ebay.py)"
              " is the next milestone.")


if __name__ == "__main__":
    main()
