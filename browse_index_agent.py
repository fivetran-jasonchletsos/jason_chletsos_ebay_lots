"""
browse_index_agent.py — Buyer-facing browsing by SET, PLAYER, and YEAR.

Reads output/listings_snapshot.json, extracts set/player/year via regex
keyword inference, and renders three public docs pages:
  • docs/browse.html    — landing tiles
  • docs/by_set.html    — every set, sorted by listing count desc
  • docs/by_player.html — every player, sorted by listing count desc

eBay URLs route through `promote._epn_wrap()` for EPN tracking. Reuses
the existing `pk-card` visual style.
"""
from __future__ import annotations

import html
import json
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import promote

REPO_ROOT = Path(__file__).parent
SNAPSHOT  = REPO_ROOT / "output" / "listings_snapshot.json"
OUTPUT    = REPO_ROOT / "output"
DOCS_DIR  = REPO_ROOT / "docs"


# --------------------------------------------------------------------------- #
# Set & player vocabularies                                                    #
# --------------------------------------------------------------------------- #

# Curated set keywords (lower-cased input is matched). Order matters: longer /
# more-specific names go first so "Topps Chrome" beats "Topps".
SET_KEYWORDS: list[tuple[str, str]] = [
    ("topps chrome update", "Topps Chrome Update"),
    ("topps chrome", "Topps Chrome"), ("topps update", "Topps Update"),
    ("topps heritage", "Topps Heritage"), ("topps finest", "Topps Finest"),
    ("topps stadium club", "Topps Stadium Club"),
    ("topps allen & ginter", "Topps Allen & Ginter"),
    ("topps allen and ginter", "Topps Allen & Ginter"),
    ("topps gypsy queen", "Topps Gypsy Queen"),
    ("topps archives", "Topps Archives"), ("topps fire", "Topps Fire"),
    ("topps tribute", "Topps Tribute"), ("topps big league", "Topps Big League"),
    ("topps now", "Topps Now"), ("topps", "Topps"),
    ("panini prizm draft picks", "Panini Prizm Draft Picks"),
    ("panini prizm", "Panini Prizm"), ("panini mosaic", "Panini Mosaic"),
    ("panini select", "Panini Select"), ("panini optic", "Panini Optic"),
    ("panini donruss optic", "Panini Donruss Optic"),
    ("panini donruss", "Panini Donruss"),
    ("panini contenders", "Panini Contenders"),
    ("panini absolute", "Panini Absolute"),
    ("panini certified", "Panini Certified"),
    ("panini score", "Panini Score"), ("panini phoenix", "Panini Phoenix"),
    ("panini chronicles", "Panini Chronicles"),
    ("panini immaculate", "Panini Immaculate"),
    ("panini national treasures", "Panini National Treasures"),
    ("panini playbook", "Panini Playbook"),
    ("panini illusions", "Panini Illusions"),
    ("panini elements", "Panini Elements"),
    ("panini gold standard", "Panini Gold Standard"),
    ("panini", "Panini"),
    ("prizm draft picks", "Panini Prizm Draft Picks"),
    ("prizm", "Panini Prizm"), ("mosaic", "Panini Mosaic"),
    ("select", "Panini Select"), ("optic", "Panini Optic"),
    ("donruss optic", "Panini Donruss Optic"),
    ("donruss", "Panini Donruss"), ("contenders", "Panini Contenders"),
    ("absolute", "Panini Absolute"), ("certified", "Panini Certified"),
    ("score", "Panini Score"),
    ("bowman chrome", "Bowman Chrome"), ("bowman draft", "Bowman Draft"),
    ("bowman platinum", "Bowman Platinum"),
    ("bowman sterling", "Bowman Sterling"),
    ("bowman's best", "Bowman's Best"), ("bowman", "Bowman"),
    ("upper deck young guns", "Upper Deck Young Guns"),
    ("upper deck sp authentic", "Upper Deck SP Authentic"),
    ("upper deck", "Upper Deck"),
    ("fleer ultra", "Fleer Ultra"), ("fleer metal", "Fleer Metal"),
    ("fleer", "Fleer"),
    ("leaf", "Leaf"), ("sage", "Sage"), ("wild card", "Wild Card"),
    ("classic pro line", "Classic Pro Line"), ("classic", "Classic"),
    ("playoff", "Playoff"), ("press pass", "Press Pass"),
    ("pacific", "Pacific"), ("skybox", "SkyBox"), ("pinnacle", "Pinnacle"),
    ("metal universe", "Metal Universe"),
    ("collector's edge", "Collector's Edge"),
    ("action packed", "Action Packed"), ("o-pee-chee", "O-Pee-Chee"),
    ("o pee chee", "O-Pee-Chee"), ("hoops", "Hoops"),
    ("sp authentic", "SP Authentic"), ("sportflics", "Sportflics"),
    # Pokemon / TCG sets
    ("base set", "Pokemon Base Set"), ("celebrations", "Pokemon Celebrations"),
    ("pokemon go", "Pokemon GO"), ("evolving skies", "Pokemon Evolving Skies"),
    ("hidden fates", "Pokemon Hidden Fates"),
    ("shining fates", "Pokemon Shining Fates"),
    ("crown zenith", "Pokemon Crown Zenith"),
    ("paldea evolved", "Pokemon Paldea Evolved"),
    ("paldean fates", "Pokemon Paldean Fates"),
    ("obsidian flames", "Pokemon Obsidian Flames"),
    ("scarlet & violet", "Pokemon Scarlet & Violet"),
    ("scarlet and violet", "Pokemon Scarlet & Violet"),
    ("sword & shield", "Pokemon Sword & Shield"),
    ("sword and shield", "Pokemon Sword & Shield"),
    ("brilliant stars", "Pokemon Brilliant Stars"),
    ("astral radiance", "Pokemon Astral Radiance"),
    ("lost origin", "Pokemon Lost Origin"),
    ("silver tempest", "Pokemon Silver Tempest"),
    ("fusion strike", "Pokemon Fusion Strike"),
    ("battle styles", "Pokemon Battle Styles"),
    ("chilling reign", "Pokemon Chilling Reign"),
    ("vivid voltage", "Pokemon Vivid Voltage"),
    ("rebel clash", "Pokemon Rebel Clash"),
    ("darkness ablaze", "Pokemon Darkness Ablaze"),
    ("cosmic eclipse", "Pokemon Cosmic Eclipse"),
    ("unbroken bonds", "Pokemon Unbroken Bonds"),
    ("hidden mew", "Pokemon 151"), ("scarlet violet 151", "Pokemon 151"),
    ("151", "Pokemon 151"), ("pokemon tcg", "Pokemon TCG"),
    ("pokemon", "Pokemon"),
    ("rookie card", "Rookie Cards"),
]

# Players we explicitly look for. Lower-case substring match against the title.
PLAYER_KEYWORDS: list[str] = [
    # NFL
    "Patrick Mahomes", "Mahomes", "Justin Jefferson", "Jefferson",
    "Joe Burrow", "Burrow", "CJ Stroud", "C.J. Stroud", "Stroud",
    "Caleb Williams", "Jayden Daniels", "Anthony Richardson",
    "Bijan Robinson", "Trevor Lawrence", "Josh Allen", "Lamar Jackson",
    "Jalen Hurts", "Tua Tagovailoa", "Justin Herbert", "Deshaun Watson",
    "Aaron Rodgers", "Tom Brady", "Peyton Manning", "Eli Manning",
    "Russell Wilson", "Dak Prescott", "Saquon Barkley",
    "Christian McCaffrey", "Derrick Henry", "Jonathan Taylor", "Nick Chubb",
    "Travis Kelce", "Tyreek Hill", "Justin Fields", "Drake Maye",
    "Marvin Harrison Jr", "Garrett Wilson", "Ja'Marr Chase", "Jamarr Chase",
    "Davante Adams", "DK Metcalf", "Stefon Diggs", "Cooper Kupp",
    "Drake London", "Chris Olave", "Garrett Nussmeier", "Jeremiyah Love",
    "Chuba Hubbard", "Deion Sanders", "Junior Seau", "Marshall Faulk",
    "Jerome Bettis", "Tim Brown", "Carl Banks", "Marcus Allen",
    "Steve Atwater", "Boomer Esiason", "Aaron Glenn", "Steve Emtman",
    "Jim Everett", "Charles Haley", "Jerry Rice", "Joe Montana",
    "Steve Young", "Walter Payton", "Barry Sanders", "Emmitt Smith",
    "Brett Favre", "Reggie White", "Lawrence Taylor", "Bo Jackson",
    "Dan Marino", "John Elway",
    # MLB
    "Shohei Ohtani", "Ohtani", "Aaron Judge", "Ronald Acuna", "Juan Soto",
    "Mike Trout", "Mookie Betts", "Fernando Tatis Jr", "Bryce Harper",
    "Vladimir Guerrero Jr", "Bobby Witt Jr", "Julio Rodriguez",
    "Paul Skenes", "Jackson Holliday", "Wyatt Langford", "Jasson Dominguez",
    "Marcelo Mayer", "Derek Jeter", "Ken Griffey Jr", "Cal Ripken",
    "Frank Thomas", "Barry Bonds", "Tony Gwynn", "Roberto Alomar",
    # NBA
    "LeBron James", "Stephen Curry", "Kevin Durant",
    "Giannis Antetokounmpo", "Luka Doncic", "Nikola Jokic", "Joel Embiid",
    "Jayson Tatum", "Devin Booker", "Anthony Edwards",
    "Victor Wembanyama", "Wembanyama", "Chet Holmgren", "Paolo Banchero",
    "Scoot Henderson", "Michael Jordan", "Kobe Bryant", "Magic Johnson",
    "Larry Bird", "Shaquille O'Neal",
    # NHL
    "Connor McDavid", "Connor Bedard", "Auston Matthews",
    "Nathan MacKinnon", "Sidney Crosby", "Wayne Gretzky",
    # Pokemon (treated as "players" for buyer browsing)
    "Pikachu", "Charizard", "Mewtwo", "Mew", "Eevee", "Lugia", "Rayquaza",
    "Gengar", "Snorlax", "Umbreon", "Espeon", "Sylveon", "Lucario",
    "Greninja",
]

# Canonicalize player aliases.
PLAYER_CANONICAL: dict[str, str] = {
    "mahomes": "Patrick Mahomes",
    "jefferson": "Justin Jefferson",
    "burrow": "Joe Burrow",
    "stroud": "CJ Stroud",
    "c.j. stroud": "CJ Stroud",
    "ohtani": "Shohei Ohtani",
    "wembanyama": "Victor Wembanyama",
    "jamarr chase": "Ja'Marr Chase",
    "ja'marr chase": "Ja'Marr Chase",
}

YEAR_RE = re.compile(r"\b(19[5-9]\d|20\d{2})\b")


# --------------------------------------------------------------------------- #
# Extraction                                                                   #
# --------------------------------------------------------------------------- #

def extract_set(title: str) -> str | None:
    t = (title or "").lower()
    for needle, label in SET_KEYWORDS:
        if needle in t:
            return label
    return None


def extract_players(title: str) -> list[str]:
    t = (title or "").lower()
    found: list[str] = []
    seen: set[str] = set()
    for name in PLAYER_KEYWORDS:
        n = name.lower()
        if n in t:
            canon = PLAYER_CANONICAL.get(n, name)
            if canon not in seen:
                seen.add(canon)
                found.append(canon)
    return found


def extract_year(title: str) -> str | None:
    m = YEAR_RE.search(title or "")
    return m.group(1) if m else None


# --------------------------------------------------------------------------- #
# Indexing                                                                     #
# --------------------------------------------------------------------------- #

def build_index(listings: list[dict]) -> dict[str, dict[str, list[dict]]]:
    by_set:    dict[str, list[dict]] = defaultdict(list)
    by_player: dict[str, list[dict]] = defaultdict(list)
    by_year:   dict[str, list[dict]] = defaultdict(list)

    for l in listings:
        title = l.get("title") or ""
        enriched = dict(l)
        # Route through EPN (no-op for own store, but stays safe & idempotent).
        enriched["url"] = promote._epn_wrap(l.get("url") or "")

        s = extract_set(title)
        if s:
            by_set[s].append(enriched)
        players = extract_players(title)
        for p in players:
            by_player[p].append(enriched)
        y = extract_year(title)
        if y:
            by_year[y].append(enriched)

    return {"by_set": by_set, "by_player": by_player, "by_year": by_year}


# --------------------------------------------------------------------------- #
# Rendering                                                                    #
# --------------------------------------------------------------------------- #

def _esc(s: Any) -> str:
    return html.escape(str(s or ""))


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


_CARD_CSS = """
<style>
  .br-kpis { display:grid; grid-template-columns:repeat(auto-fit,minmax(170px,1fr)); gap:12px; margin:22px 0; }
  .br-kpi { background:var(--surface); border:1px solid var(--border); border-radius:var(--r-md); padding:16px 18px; border-left:3px solid var(--accent-gold,#d4af37); }
  .br-n { font-family:'Bebas Neue',sans-serif; font-size:40px; color:var(--accent-gold,#d4af37); line-height:1; }
  .br-l { color:var(--text-muted); font-size:11px; text-transform:uppercase; letter-spacing:.1em; margin-top:6px; }
  .br-section { margin:36px 0; }
  .br-section-head { display:flex; align-items:baseline; justify-content:space-between; gap:14px; flex-wrap:wrap; padding-bottom:10px; margin-bottom:16px; border-bottom:1px solid var(--border); }
  .br-section-head h2 { margin:0; font-family:'Bebas Neue',sans-serif; font-size:30px; letter-spacing:.03em; color:var(--text); }
  .br-section-head .br-count { font-size:12px; letter-spacing:.12em; text-transform:uppercase; color:var(--text-muted); font-weight:700; }
  .br-anchor-jump { display:flex; flex-wrap:wrap; gap:6px; margin:14px 0 20px; }
  .br-anchor-jump a { font-size:11px; padding:6px 10px; background:var(--surface-2); border:1px solid var(--border); border-radius:999px; color:var(--text); text-decoration:none; letter-spacing:.04em; }
  .br-anchor-jump a:hover { border-color:var(--accent-gold,#d4af37); color:var(--accent-gold,#d4af37); }
  .pk-grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(210px,1fr)); gap:14px; }
  .pk-card { display:block; background:var(--surface); border:1px solid var(--border); border-radius:var(--r-md); overflow:hidden; text-decoration:none; color:inherit; transition:transform .18s ease, border-color .18s ease, box-shadow .18s ease; position:relative; }
  .pk-card:hover { transform:translateY(-3px) scale(1.025); border-color:var(--accent-gold,#d4af37); box-shadow:0 10px 28px rgba(212,175,55,.25); z-index:2; }
  .pk-img { aspect-ratio:1/1; background-size:cover; background-position:center; background-color:var(--surface-2); transition:transform .25s ease; }
  .pk-card:hover .pk-img { transform:scale(1.05); }
  .pk-meta { padding:10px 12px; }
  .pk-price-row { display:flex; justify-content:space-between; align-items:baseline; margin-bottom:6px; }
  .pk-price { font-family:'Bebas Neue',sans-serif; font-size:24px; color:var(--accent-gold,#d4af37); }
  .pk-title { font-size:12px; line-height:1.4; color:var(--text); min-height:32px; }
  .pk-buying { font-size:10px; color:var(--text-muted); margin-top:6px; letter-spacing:.04em; }
  .br-tile-grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(240px,1fr)); gap:14px; margin:24px 0 40px; }
  .br-tile { display:block; background:var(--surface); border:1px solid var(--border); border-radius:var(--r-md); padding:18px; text-decoration:none; color:inherit; transition:transform .18s ease, border-color .18s ease, box-shadow .18s ease; border-left:3px solid var(--accent-gold,#d4af37); }
  .br-tile:hover { transform:translateY(-3px); border-color:var(--accent-gold,#d4af37); box-shadow:0 10px 26px rgba(212,175,55,.18); }
  .br-tile-name { font-family:'Bebas Neue',sans-serif; font-size:24px; letter-spacing:.02em; color:var(--text); line-height:1.1; }
  .br-tile-count { margin-top:8px; color:var(--text-muted); font-size:13px; }
  .br-tile-count strong { color:var(--accent-gold,#d4af37); font-family:'Bebas Neue',sans-serif; font-size:20px; vertical-align:middle; }
  .br-landing-card { display:block; background:linear-gradient(180deg,rgba(0,0,0,.06),transparent); border:1px solid var(--border); border-radius:var(--r-md); padding:26px; text-decoration:none; color:inherit; transition:transform .2s ease, border-color .2s ease, box-shadow .2s ease; border-top:4px solid var(--accent-gold,#d4af37); }
  .br-landing-card:hover { transform:translateY(-4px); border-color:var(--accent-gold,#d4af37); box-shadow:0 14px 36px rgba(0,0,0,.4); }
  .br-landing-name { font-family:'Bebas Neue',sans-serif; font-size:38px; color:var(--accent-gold,#d4af37); letter-spacing:.03em; line-height:1; }
  .br-landing-sub { margin-top:8px; color:var(--text-muted); font-size:13px; line-height:1.5; }
  .br-landing-stat { margin-top:14px; font-size:12px; color:var(--text-muted); text-transform:uppercase; letter-spacing:.12em; }
  .br-landing-stat strong { color:var(--text); font-family:'Bebas Neue',sans-serif; font-size:20px; }
  .br-back { display:inline-block; margin-top:10px; font-size:13px; color:var(--accent-gold,#d4af37); text-decoration:none; }
  .br-back:hover { text-decoration:underline; }
  @media (max-width:640px) { .pk-grid { grid-template-columns:repeat(auto-fill,minmax(150px,1fr)); gap:8px; } }
</style>
"""


def _render_card(it: dict) -> str:
    url   = _esc(it.get("url") or "")
    pic   = _esc(it.get("pic") or "")
    title = _esc((it.get("title") or "")[:84])
    try:
        price = float(it.get("price") or 0)
    except (TypeError, ValueError):
        price = 0.0
    ltype = _esc(it.get("listing_type") or "")
    return f"""
    <a class="pk-card" href="{url}" target="_blank" rel="noopener">
      <div class="pk-img" style="background-image:url('{pic}');"></div>
      <div class="pk-meta">
        <div class="pk-price-row">
          <span class="pk-price">${price:.2f}</span>
        </div>
        <div class="pk-title">{title}</div>
        <div class="pk-buying">{ltype}</div>
      </div>
    </a>"""


def _render_group_page(group_label_singular: str, group_label_plural: str,
                       buckets: dict[str, list[dict]], active_page: str,
                       intro: str) -> str:
    # Sort buckets by item count desc.
    items_sorted = sorted(buckets.items(), key=lambda kv: -len(kv[1]))
    total_items = sum(len(v) for v in buckets.values())

    # Anchor jump strip
    anchor_links = "".join(
        f'<a href="#g-{_slug(name)}">{_esc(name)} <span style="opacity:.6">({len(v)})</span></a>'
        for name, v in items_sorted
    )

    sections = []
    for name, items in items_sorted:
        sid = _slug(name)
        # Sort items inside each group by price desc (grail first feels right).
        try:
            items_local = sorted(items, key=lambda x: -float(x.get("price") or 0))
        except (TypeError, ValueError):
            items_local = items
        cards = "".join(_render_card(it) for it in items_local)
        sections.append(f"""
        <section class="br-section" id="g-{sid}">
          <div class="br-section-head">
            <h2>{_esc(name)}</h2>
            <span class="br-count">{len(items)} listing{"s" if len(items) != 1 else ""}</span>
          </div>
          <div class="pk-grid">{cards}</div>
        </section>""")

    kpis = f"""
    <div class="br-kpis">
      <div class="br-kpi"><div class="br-n">{len(buckets)}</div><div class="br-l">{_esc(group_label_plural)}</div></div>
      <div class="br-kpi"><div class="br-n">{total_items}</div><div class="br-l">Total listings tagged</div></div>
      <div class="br-kpi"><div class="br-n">{datetime.now().strftime('%H:%M')}</div><div class="br-l">Last refreshed (local)</div></div>
    </div>"""

    body = f"""
    <div class="section-head">
      <div>
        <div class="eyebrow">Browse &middot; by {_esc(group_label_singular)}</div>
        <h1 class="section-title">Browse by <span class="accent">{_esc(group_label_singular)}</span></h1>
        <div class="section-sub">
          {intro}
          <br>
          <a class="br-back" href="browse.html">&larr; Back to Browse</a> &nbsp;&middot;&nbsp;
          <a class="br-back" href="index.html">&larr; Back to Storefront</a>
        </div>
      </div>
    </div>

    {kpis}

    <div class="br-anchor-jump">{anchor_links}</div>

    {''.join(sections)}
    """
    return promote.html_shell(
        f"Browse by {group_label_singular} &middot; {promote.SELLER_NAME}",
        body,
        extra_head=_CARD_CSS,
        active_page=active_page,
    )


def render_by_set(index: dict[str, dict[str, list[dict]]]) -> Path:
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    page = _render_group_page(
        "Set", "Sets",
        index["by_set"], "by_set.html",
        "Every listing in our store grouped by the set it came from. "
        "Bigger sets float to the top.",
    )
    out = DOCS_DIR / "by_set.html"
    out.write_text(page, encoding="utf-8")
    return out


def render_by_player(index: dict[str, dict[str, list[dict]]]) -> Path:
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    page = _render_group_page(
        "Player", "Players",
        index["by_player"], "by_player.html",
        "Every listing in our store grouped by the player (or Pokemon) "
        "named in the title. Most-listed names float to the top.",
    )
    out = DOCS_DIR / "by_player.html"
    out.write_text(page, encoding="utf-8")
    return out


def render_landing(index: dict[str, dict[str, list[dict]]],
                   total_listings: int) -> Path:
    """docs/browse.html — three big tile groups + landing tile rows."""
    DOCS_DIR.mkdir(parents=True, exist_ok=True)

    # Top tiles
    def _top(buckets: dict[str, list[dict]], page: str, label: str,
             top_n: int = 12) -> str:
        items_sorted = sorted(buckets.items(), key=lambda kv: -len(kv[1]))[:top_n]
        tiles = []
        for name, v in items_sorted:
            tiles.append(f"""
            <a class="br-tile" href="{page}#g-{_slug(name)}">
              <div class="br-tile-name">{_esc(name)}</div>
              <div class="br-tile-count"><strong>{len(v)}</strong> {label}</div>
            </a>""")
        return "".join(tiles)

    set_tiles    = _top(index["by_set"],    "by_set.html",    "listings")
    player_tiles = _top(index["by_player"], "by_player.html", "listings")
    year_tiles   = _top(index["by_year"],   "by_set.html",    "listings")  # year jumps not yet on a dedicated page

    # Big top-level browse cards
    landing_cards = f"""
    <div class="br-tile-grid" style="grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 18px;">
      <a class="br-landing-card" href="by_set.html">
        <div class="br-landing-name">By Set</div>
        <div class="br-landing-sub">
          Think "show me everything from 2024 Topps Chrome." Browse every product line in the store.
        </div>
        <div class="br-landing-stat"><strong>{len(index['by_set'])}</strong> sets</div>
      </a>
      <a class="br-landing-card" href="by_player.html">
        <div class="br-landing-name">By Player</div>
        <div class="br-landing-sub">
          Think "all Mahomes cards." Names pulled straight from listing titles.
        </div>
        <div class="br-landing-stat"><strong>{len(index['by_player'])}</strong> players</div>
      </a>
      <a class="br-landing-card" href="#by-year">
        <div class="br-landing-name">By Year</div>
        <div class="br-landing-sub">
          Vintage vs. modern. Jump to any year that shows up in our titles.
        </div>
        <div class="br-landing-stat"><strong>{len(index['by_year'])}</strong> years</div>
      </a>
    </div>
    """

    kpis = f"""
    <div class="br-kpis">
      <div class="br-kpi"><div class="br-n">{total_listings}</div><div class="br-l">Live listings</div></div>
      <div class="br-kpi"><div class="br-n">{len(index['by_set'])}</div><div class="br-l">Unique sets</div></div>
      <div class="br-kpi"><div class="br-n">{len(index['by_player'])}</div><div class="br-l">Unique players</div></div>
      <div class="br-kpi"><div class="br-n">{len(index['by_year'])}</div><div class="br-l">Unique years</div></div>
    </div>
    """

    # Year jump list
    year_items = sorted(index["by_year"].items(),
                        key=lambda kv: (-int(kv[0]) if kv[0].isdigit() else 0))
    year_tile_html = "".join(
        f'<a class="br-tile" href="#y-{_slug(y)}"><div class="br-tile-name">{_esc(y)}</div>'
        f'<div class="br-tile-count"><strong>{len(v)}</strong> listings</div></a>'
        for y, v in year_items
    )
    # Year sections (inline, since there's no dedicated by_year.html per spec)
    year_sections = []
    for y, items in year_items:
        try:
            items_local = sorted(items, key=lambda x: -float(x.get("price") or 0))
        except (TypeError, ValueError):
            items_local = items
        cards = "".join(_render_card(it) for it in items_local[:18])  # cap to keep page tight
        more = ""
        if len(items_local) > 18:
            more = (f'<div style="margin-top:10px;font-size:12px;color:var(--text-muted);">'
                    f'+ {len(items_local) - 18} more {_esc(y)} listing'
                    f'{"s" if len(items_local) - 18 != 1 else ""} '
                    f'&mdash; see <a href="index.html" style="color:var(--accent-gold,#d4af37);">the full grid</a>.</div>')
        year_sections.append(f"""
        <section class="br-section" id="y-{_slug(y)}">
          <div class="br-section-head">
            <h2>{_esc(y)}</h2>
            <span class="br-count">{len(items)} listing{"s" if len(items) != 1 else ""}</span>
          </div>
          <div class="pk-grid">{cards}</div>
          {more}
        </section>""")

    body = f"""
    <div class="section-head">
      <div>
        <div class="eyebrow">Browse &middot; buyer-friendly</div>
        <h1 class="section-title">Browse the <span class="accent">Store</span></h1>
        <div class="section-sub">
          Pick a set, a player, or a year. The main storefront is one big grid &mdash;
          this view lets you slice it the way buyers actually think.
          <br><a class="br-back" href="index.html">&larr; Back to Storefront</a>
        </div>
      </div>
    </div>

    {kpis}

    {landing_cards}

    <section class="br-section">
      <div class="br-section-head">
        <h2>Top Sets</h2>
        <span class="br-count"><a class="br-back" href="by_set.html">See all &rarr;</a></span>
      </div>
      <div class="br-tile-grid">{set_tiles}</div>
    </section>

    <section class="br-section">
      <div class="br-section-head">
        <h2>Top Players</h2>
        <span class="br-count"><a class="br-back" href="by_player.html">See all &rarr;</a></span>
      </div>
      <div class="br-tile-grid">{player_tiles}</div>
    </section>

    <section class="br-section" id="by-year">
      <div class="br-section-head">
        <h2>Browse by Year</h2>
        <span class="br-count">{len(index['by_year'])} years</span>
      </div>
      <div class="br-anchor-jump">{year_tile_html}</div>
      {''.join(year_sections)}
    </section>
    """

    page = promote.html_shell(
        f"Browse &middot; {promote.SELLER_NAME}",
        body,
        extra_head=_CARD_CSS,
        active_page="browse.html",
    )
    out = DOCS_DIR / "browse.html"
    out.write_text(page, encoding="utf-8")
    return out


# --------------------------------------------------------------------------- #
# Orchestration                                                                #
# --------------------------------------------------------------------------- #

def main() -> None:
    if not SNAPSHOT.exists():
        raise SystemExit(f"missing snapshot: {SNAPSHOT}")
    listings: list[dict] = json.loads(SNAPSHOT.read_text())
    index = build_index(listings)

    OUTPUT.mkdir(parents=True, exist_ok=True)
    plan = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "total_listings": len(listings),
        "unique_sets": len(index["by_set"]),
        "unique_players": len(index["by_player"]),
        "unique_years": len(index["by_year"]),
        "top_sets": sorted(((k, len(v)) for k, v in index["by_set"].items()),
                           key=lambda kv: -kv[1])[:10],
        "top_players": sorted(((k, len(v)) for k, v in index["by_player"].items()),
                              key=lambda kv: -kv[1])[:10],
    }
    (OUTPUT / "browse_index_plan.json").write_text(
        json.dumps(plan, indent=2), encoding="utf-8")

    landing = render_landing(index, total_listings=len(listings))
    by_set  = render_by_set(index)
    by_play = render_by_player(index)

    print(f"  Browse landing : {landing}")
    print(f"  By set         : {by_set}")
    print(f"  By player      : {by_play}")
    print(f"  Listings       : {len(listings)}")
    print(f"  Unique sets    : {len(index['by_set'])}")
    print(f"  Unique players : {len(index['by_player'])}")
    print(f"  Unique years   : {len(index['by_year'])}")
    if plan["top_sets"]:
        print(f"  Top 3 sets     : {plan['top_sets'][:3]}")
    if plan["top_players"]:
        print(f"  Top 3 players  : {plan['top_players'][:3]}")


if __name__ == "__main__":
    main()
