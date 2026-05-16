"""
specifics_agent.py — Item Specifics gap-filler for Harpua2001 listings.

eBay's search algo weights Item Specifics heavily. A typical sports-card listing
ships with 1-3 specifics when eBay supports 15+. Every missing required/
recommended specific hurts search ranking. This agent:

  1. Pulls current Item Specifics per listing via Trading API GetItem
     (with IncludeItemSpecifics=true). Results are cached.
  2. Reuses card_price_agent.parse_title() to extract player/year/set/grade
     plus a bunch of additional inference (sport, league, parallel, features,
     team, language, original/reprint) from title (and description if any).
  3. Diffs parsed values against currently filled specifics. Only fills GAPS;
     never overwrites existing values (sellers often customize).
  4. Emits a plan keyed by listing_id with proposed fills + confidence
     (high/medium/low) and reasoning.
  5. Dry-run by default. `--apply` actually pushes ReviseItem with EXISTING +
     NEW specifics (eBay's API replaces the entire ItemSpecifics block, so we
     must send everything together).

Usage:
    python specifics_agent.py                 # dry run — plan + report only
    python specifics_agent.py --apply         # push gap-fills to eBay
    python specifics_agent.py --apply --item 306913311444    # single listing
    python specifics_agent.py --no-fetch      # reuse cached GetItem snapshot
    python specifics_agent.py --report-only   # rebuild docs/specifics.html

Artifacts:
    specifics_config.json              tunable config (created on first run)
    output/specifics_cache.json        cached GetItem responses
    output/specifics_plan.json         latest plan (every gap, every reason)
    output/specifics_history.json      append-only log of applied changes
    docs/specifics.html                human-readable report
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

import requests

import promote
import card_price_agent

REPO_ROOT          = Path(__file__).parent
CONFIG_PATH        = REPO_ROOT / "specifics_config.json"
LISTINGS_SNAPSHOT  = REPO_ROOT / "output" / "listings_snapshot.json"
CACHE_PATH         = REPO_ROOT / "output" / "specifics_cache.json"
PLAN_PATH          = REPO_ROOT / "output" / "specifics_plan.json"
HISTORY_PATH       = REPO_ROOT / "output" / "specifics_history.json"
REPORT_PATH        = promote.OUTPUT_DIR / "specifics.html"

EBAY_NS = "urn:ebay:apis:eBLBaseComponents"
CACHE_TTL_SECONDS = 7 * 24 * 3600   # GetItem cache: 7 days

DEFAULT_CONFIG: dict = {
    "enabled":                       True,
    "auto_apply_high_confidence":    True,
    "auto_apply_medium_confidence":  False,
    "skip_fields":                   [],
    "max_changes_per_run":           25,
    "category_specific_fields": {
        "sports_card":  ["Year", "Manufacturer", "Set", "Sport", "Player",
                         "Card Number", "Parallel", "Features", "League",
                         "Team", "Grade", "Graded", "Original/Reprint"],
        "pokemon_card": ["Year", "Manufacturer", "Set", "Card Type",
                         "Card Number", "Card Name", "Rarity", "Features",
                         "Language", "Graded", "Grade", "Original/Reprint"],
    },
}


# --------------------------------------------------------------------------- #
# Config + history + cache I/O                                                #
# --------------------------------------------------------------------------- #

def load_config() -> dict:
    if not CONFIG_PATH.exists():
        CONFIG_PATH.write_text(json.dumps(DEFAULT_CONFIG, indent=2))
        print(f"  Created default config at {CONFIG_PATH.name}")
        return dict(DEFAULT_CONFIG)
    cfg = json.loads(CONFIG_PATH.read_text())
    for k, v in DEFAULT_CONFIG.items():
        cfg.setdefault(k, v)
    return cfg


def load_history() -> list[dict]:
    if not HISTORY_PATH.exists():
        return []
    try:
        return json.loads(HISTORY_PATH.read_text())
    except json.JSONDecodeError:
        return []


def append_history(entries: list[dict]) -> None:
    if not entries:
        return
    HISTORY_PATH.parent.mkdir(exist_ok=True)
    hist = load_history()
    hist.extend(entries)
    HISTORY_PATH.write_text(json.dumps(hist, indent=2))


def load_cache() -> dict:
    if not CACHE_PATH.exists():
        return {}
    try:
        return json.loads(CACHE_PATH.read_text())
    except json.JSONDecodeError:
        return {}


def save_cache(cache: dict) -> None:
    CACHE_PATH.parent.mkdir(exist_ok=True)
    CACHE_PATH.write_text(json.dumps(cache, indent=2))


# --------------------------------------------------------------------------- #
# Sport / league / category inference                                         #
# --------------------------------------------------------------------------- #

# Player → sport/league hint table. Keep tight; we only fill HIGH-confidence
# when sport is unambiguous (set brand or player on this list).
PLAYER_SPORTS: dict[str, tuple[str, str]] = {
    # Football (NFL)
    "patrick mahomes": ("Football", "NFL"),
    "tom brady": ("Football", "NFL"),
    "joe burrow": ("Football", "NFL"),
    "josh allen": ("Football", "NFL"),
    "justin jefferson": ("Football", "NFL"),
    "ja'marr chase": ("Football", "NFL"),
    "jamarr chase": ("Football", "NFL"),
    "caleb williams": ("Football", "NFL"),
    "jayden daniels": ("Football", "NFL"),
    "marvin harrison": ("Football", "NFL"),
    "junior seau": ("Football", "NFL"),
    "marshall faulk": ("Football", "NFL"),
    "jerry rice": ("Football", "NFL"),
    "barry sanders": ("Football", "NFL"),
    "emmitt smith": ("Football", "NFL"),
    "peyton manning": ("Football", "NFL"),
    "aaron rodgers": ("Football", "NFL"),
    "drew brees": ("Football", "NFL"),
    "lamar jackson": ("Football", "NFL"),
    "saquon barkley": ("Football", "NFL"),
    "christian mccaffrey": ("Football", "NFL"),
    "bo nix": ("Football", "NFL"),
    # Basketball (NBA)
    "michael jordan": ("Basketball", "NBA"),
    "lebron james": ("Basketball", "NBA"),
    "kobe bryant": ("Basketball", "NBA"),
    "stephen curry": ("Basketball", "NBA"),
    "kevin durant": ("Basketball", "NBA"),
    "giannis antetokounmpo": ("Basketball", "NBA"),
    "luka doncic": ("Basketball", "NBA"),
    "victor wembanyama": ("Basketball", "NBA"),
    "jayson tatum": ("Basketball", "NBA"),
    "nikola jokic": ("Basketball", "NBA"),
    "shaquille o'neal": ("Basketball", "NBA"),
    "larry bird": ("Basketball", "NBA"),
    "magic johnson": ("Basketball", "NBA"),
    "scottie pippen": ("Basketball", "NBA"),
    "ja morant": ("Basketball", "NBA"),
    "zion williamson": ("Basketball", "NBA"),
    # Baseball (MLB)
    "mike trout": ("Baseball", "MLB"),
    "shohei ohtani": ("Baseball", "MLB"),
    "aaron judge": ("Baseball", "MLB"),
    "ronald acuna": ("Baseball", "MLB"),
    "fernando tatis": ("Baseball", "MLB"),
    "ken griffey": ("Baseball", "MLB"),
    "derek jeter": ("Baseball", "MLB"),
    "barry bonds": ("Baseball", "MLB"),
    "mickey mantle": ("Baseball", "MLB"),
    "babe ruth": ("Baseball", "MLB"),
    "juan soto": ("Baseball", "MLB"),
    "paul skenes": ("Baseball", "MLB"),
    # Hockey (NHL)
    "wayne gretzky": ("Hockey", "NHL"),
    "connor mcdavid": ("Hockey", "NHL"),
    "sidney crosby": ("Hockey", "NHL"),
    "alex ovechkin": ("Hockey", "NHL"),
    "auston matthews": ("Hockey", "NHL"),
    # Soccer
    "lionel messi": ("Soccer", ""),
    "cristiano ronaldo": ("Soccer", ""),
    "kylian mbappe": ("Soccer", ""),
    "erling haaland": ("Soccer", ""),
}

SET_TO_SPORT: dict[str, tuple[str, str]] = {
    # Sets that imply sport
    "donruss optic football": ("Football", "NFL"),
    "donruss football":       ("Football", "NFL"),
    "score football":         ("Football", "NFL"),
    "topps football":         ("Football", "NFL"),
    "hoops basketball":       ("Basketball", "NBA"),
    "prizm basketball":       ("Basketball", "NBA"),
    "select basketball":      ("Basketball", "NBA"),
    "bowman chrome":          ("Baseball", "MLB"),
    "topps chrome":           ("Baseball", "MLB"),
}

# Manufacturer inference (brand → company).
SET_TO_MFG: dict[str, str] = {
    "topps":         "Topps",
    "bowman":        "Topps",
    "stadium club":  "Topps",
    "chrome":        "Topps",  # weak — only when no other brand present
    "finest":        "Topps",
    "panini":        "Panini",
    "prizm":         "Panini",
    "optic":         "Panini",
    "mosaic":        "Panini",
    "select":        "Panini",
    "donruss":       "Panini",
    "hoops":         "Panini",
    "score":         "Panini",
    "contenders":    "Panini",
    "absolute":      "Panini",
    "upper deck":    "Upper Deck",
    "fleer":         "Fleer",
    "skybox":        "Skybox",
    "leaf":          "Leaf",
    "pinnacle":      "Pinnacle",
    "pokemon":       "Pokemon (Nintendo)",
}

# "Set" specific (the actual set name, e.g. "Prizm", "Optic", "Chrome").
SET_NAMES = [
    "Prizm", "Optic", "Mosaic", "Select", "Chrome", "Bowman", "Stadium Club",
    "Finest", "Hoops", "Contenders", "Absolute", "Donruss", "Score", "Topps",
    "Panini", "Upper Deck", "Fleer", "Skybox", "Leaf", "Pinnacle",
]

# Parallel/variation tokens — look in title (case-insensitive substring).
PARALLEL_TOKENS = [
    "Silver Prizm", "Gold Prizm", "Black Prizm", "Red Prizm", "Blue Prizm",
    "Green Prizm", "Orange Prizm", "Purple Prizm", "Pink Prizm", "White Prizm",
    "Red Ice", "Blue Ice", "Gold Ice", "Black Ice", "Green Ice", "Purple Ice",
    "Silver", "Gold", "Bronze", "Holo", "Holographic", "Refractor",
    "Atomic Refractor", "X-Fractor", "Xfractor", "Superfractor",
    "Rainbow Foil", "Reverse Holo", "Cosmic", "Pulsar", "Hyper",
]

FEATURE_TOKENS = [
    ("Rookie", [r"\brookie\b", r"\brc\b", r"\b1st\b\s*bowman"]),
    ("Autograph", [r"\bauto\b", r"\bautograph\b", r"\bsigned\b"]),
    ("Patch", [r"\bpatch\b", r"\brpa\b"]),
    ("Refractor", [r"\brefractor\b", r"\bx-?fractor\b", r"\bsuperfractor\b"]),
    ("Holo", [r"\bholo\b", r"\bholographic\b"]),
    ("Promo", [r"\bpromo\b", r"\bpromotional\b"]),
    ("Serial Numbered", [r"/\d{1,4}\b", r"#'?d\s*/\d"]),
    ("Short Print", [r"\bsp\b", r"\bssp\b", r"\bshort\s*print\b"]),
]

POKEMON_HINTS = [
    "pokemon", "pikachu", "charizard", "mewtwo", "blastoise", "venusaur",
    "japanese pokemon", "japanese", "obsidian flames", "paldea", "scarlet",
    "violet", "151", "evolutions", "base set", "shining fates", "celebrations",
    "vmax", "vstar", "ex ", " ex,", " gx", "trainer",
]

# eBay category IDs we recognize (top-level / common). Pokemon vs sports.
CATEGORY_POKEMON_IDS = {
    "183454", "2536", "183452",   # Pokémon TCG individual cards & sealed
}
# Sports trading cards live under many sub-IDs; if not Pokemon, assume sports.


def detect_card_type(title: str, category: str, category_id: str, desc: str = "") -> str:
    """Return 'pokemon_card' or 'sports_card'."""
    text = f"{title} {category} {desc}".lower()
    if category_id and category_id in CATEGORY_POKEMON_IDS:
        return "pokemon_card"
    if "pokemon" in text or "pokémon" in text:
        return "pokemon_card"
    for h in POKEMON_HINTS:
        if h in text:
            # Be conservative on common words; require strong signal
            if h in ("pokemon", "charizard", "pikachu", "mewtwo", "vmax",
                     "vstar", "japanese pokemon"):
                return "pokemon_card"
    return "sports_card"


def infer_sport_league(parsed: dict, title: str) -> tuple[str | None, str | None, str]:
    """Return (sport, league, confidence). 'high' if player-table hit or set-table hit."""
    t = title.lower()
    player = (parsed.get("player") or "").lower().strip()
    if player and player in PLAYER_SPORTS:
        s, lg = PLAYER_SPORTS[player]
        return s, (lg or None), "high"
    # Try set-table
    for k, (s, lg) in SET_TO_SPORT.items():
        if all(tok in t for tok in k.split()):
            return s, (lg or None), "high"
    # Pokemon clue
    if any(h in t for h in ("pokemon", "pokémon", "charizard", "pikachu")):
        return "Trading Card Game", None, "high"
    return None, None, "low"


def infer_manufacturer_set(parsed: dict, title: str) -> tuple[str | None, str | None, str]:
    """Return (manufacturer, set, confidence)."""
    t = title.lower()
    set_tokens = parsed.get("set_tokens") or []
    # 'Set' = primary set brand (prefer specific brands over generic 'Topps').
    set_name = None
    priority = ["prizm", "optic", "mosaic", "select", "chrome", "bowman",
                "stadium club", "finest", "contenders", "absolute", "donruss",
                "score", "hoops", "topps", "panini", "upper deck", "fleer",
                "skybox", "leaf", "pinnacle"]
    for p in priority:
        if p in set_tokens:
            # Title-case the set name
            set_name = " ".join(w.capitalize() for w in p.split())
            break

    mfg = None
    # Manufacturer derived from any matched set token (most specific first).
    for p in priority:
        if p in set_tokens and p in SET_TO_MFG:
            mfg = SET_TO_MFG[p]
            break
    # Pokemon special-case
    if mfg is None and ("pokemon" in t or "pokémon" in t):
        mfg = "Pokemon (Nintendo)"

    conf = "high" if (mfg and set_name) else ("medium" if (mfg or set_name) else "low")
    return mfg, set_name, conf


def infer_parallel(title: str) -> tuple[str | None, str]:
    """Find a parallel/variation. Longest match wins."""
    t = title.lower()
    matches = []
    for tok in PARALLEL_TOKENS:
        if tok.lower() in t:
            matches.append(tok)
    if not matches:
        return None, "low"
    matches.sort(key=len, reverse=True)
    return matches[0], "high"


def infer_features(title: str) -> tuple[str | None, str]:
    """Return a comma-joined feature string, or None."""
    feats = []
    for label, patterns in FEATURE_TOKENS:
        for p in patterns:
            if re.search(p, title, re.IGNORECASE):
                feats.append(label)
                break
    if not feats:
        return None, "low"
    return ", ".join(feats), "high"


def infer_grade(parsed: dict) -> tuple[str | None, str | None, str]:
    """Return (graded_yn, grade_label, confidence)."""
    g = parsed.get("grade")
    if not g:
        return "No", None, "high"
    label_map = {
        "psa10": "PSA 10", "psa9": "PSA 9", "psa8": "PSA 8", "psa7": "PSA 7",
        "bgs10": "BGS 10", "bgs95": "BGS 9.5",
        "cgc10": "CGC 10", "sgc10": "SGC 10",
    }
    return "Yes", label_map.get(g, g.upper()), "high"


def infer_language(title: str, desc: str = "") -> tuple[str, str]:
    """Default English; Japanese only with explicit signal. Mostly for Pokemon."""
    text = f"{title} {desc}".lower()
    if "japanese" in text or "japan " in text or "jp " in text:
        return "Japanese", "high"
    return "English", "medium"


def parse_description(desc: str) -> dict:
    """Light enrichment from description: returns dict of overrides if found."""
    out: dict[str, str] = {}
    if not desc:
        return out
    # Look for "Year: 1999" / "Manufacturer: Topps" patterns
    for line in re.split(r"[\n\r]+", desc):
        m = re.match(r"\s*([A-Za-z /]+?)\s*[:=]\s*(.+?)\s*$", line)
        if not m:
            continue
        k, v = m.group(1).strip().title(), m.group(2).strip()
        if 2 < len(v) < 60:
            out[k] = v
    return out


# --------------------------------------------------------------------------- #
# Target specifics builder                                                    #
# --------------------------------------------------------------------------- #

def build_target_specifics(listing: dict, desc: str = "") -> tuple[dict, dict, str]:
    """
    Returns:
        target  - {field: {value, confidence}}
        debug   - parsing info for the report
        card_type - 'sports_card' or 'pokemon_card'
    """
    title = listing.get("title") or ""
    category = listing.get("category") or ""
    category_id = listing.get("category_id") or ""
    card_type = detect_card_type(title, category, category_id, desc)

    parsed = card_price_agent.parse_title(title)
    sport, league, sl_conf = infer_sport_league(parsed, title)
    mfg, set_name, ms_conf = infer_manufacturer_set(parsed, title)
    parallel, par_conf = infer_parallel(title)
    features, feat_conf = infer_features(title)
    graded_yn, grade_label, g_conf = infer_grade(parsed)
    language, lang_conf = infer_language(title, desc)
    desc_kv = parse_description(desc)

    target: dict[str, dict] = {}

    def put(field: str, value, confidence: str):
        if value is None or value == "":
            return
        target[field] = {"value": str(value), "confidence": confidence}

    # Common fields
    if parsed.get("year"):
        put("Year", parsed["year"], "high")
    put("Manufacturer", mfg, ms_conf if ms_conf in ("high", "medium") else "low")
    put("Set", set_name, ms_conf if ms_conf in ("high", "medium") else "low")
    if card_type == "sports_card":
        put("Sport", sport, sl_conf)
        put("League", league, sl_conf)
        if parsed.get("player"):
            # Player confidence: high if it's 2+ tokens
            pconf = "high" if len(parsed["player"].split()) >= 2 else "medium"
            put("Player", parsed["player"], pconf)
            # Athlete is sometimes the eBay-canonical field
            put("Athlete", parsed["player"], pconf)
    else:
        # Pokemon
        if parsed.get("player"):
            put("Card Name", parsed["player"], "medium")
        put("Language", language, "medium" if language == "English" else "high")

    if parsed.get("card_number"):
        put("Card Number", f"#{parsed['card_number']}", "high")

    put("Parallel/Variety", parallel, par_conf)
    put("Parallel", parallel, par_conf)  # alternate field name eBay sometimes uses

    if features:
        put("Features", features, feat_conf)

    put("Graded", graded_yn, "high")
    if grade_label:
        put("Grade", grade_label, "high")
        # eBay also has "Professional Grader" as a field
        if "PSA" in grade_label:
            put("Professional Grader", "Professional Sports Authenticator (PSA)", "high")
        elif "BGS" in grade_label:
            put("Professional Grader", "Beckett Grading Services (BGS)", "high")
        elif "CGC" in grade_label:
            put("Professional Grader", "Certified Guaranty Company (CGC)", "high")
        elif "SGC" in grade_label:
            put("Professional Grader", "Sportscard Guaranty Corporation (SGC)", "high")

    put("Original/Licensed Reprint", "Original", "medium")
    put("Original/Reprint", "Original", "medium")

    # Description overrides (HIGH if user explicitly stated)
    for k, v in desc_kv.items():
        if k in ("Year", "Manufacturer", "Set", "Sport", "Player", "Team",
                 "League", "Grade", "Parallel", "Card Number"):
            target[k] = {"value": v, "confidence": "high"}

    debug = {
        "parsed": parsed,
        "card_type": card_type,
        "inferred": {
            "sport": sport, "league": league, "sport_conf": sl_conf,
            "manufacturer": mfg, "set": set_name, "ms_conf": ms_conf,
            "parallel": parallel, "par_conf": par_conf,
            "features": features, "feat_conf": feat_conf,
            "graded": graded_yn, "grade": grade_label,
            "language": language,
            "desc_overrides": desc_kv,
        },
    }
    return target, debug, card_type


# --------------------------------------------------------------------------- #
# eBay Trading API: GetItem / ReviseItem                                      #
# --------------------------------------------------------------------------- #

def _ebay_headers(call_name: str, cfg: dict) -> dict:
    return {
        "X-EBAY-API-SITEID":              "0",
        "X-EBAY-API-COMPATIBILITY-LEVEL": "967",
        "X-EBAY-API-CALL-NAME":           call_name,
        "X-EBAY-API-APP-NAME":            cfg["client_id"],
        "X-EBAY-API-DEV-NAME":            cfg["dev_id"],
        "X-EBAY-API-CERT-NAME":           cfg["client_secret"],
        "Content-Type":                   "text/xml",
    }


def get_item(item_id: str, token: str, ebay_cfg: dict) -> dict | None:
    """Trading API GetItem with IncludeItemSpecifics=true.
    Returns {item_id, title, category_id, category_name, description, specifics}."""
    xml_body = f"""<?xml version="1.0" encoding="utf-8"?>
<GetItemRequest xmlns="{EBAY_NS}">
  <RequesterCredentials><eBayAuthToken>{token}</eBayAuthToken></RequesterCredentials>
  <ItemID>{item_id}</ItemID>
  <IncludeItemSpecifics>true</IncludeItemSpecifics>
  <DetailLevel>ReturnAll</DetailLevel>
  <ErrorLanguage>en_US</ErrorLanguage>
  <WarningLevel>High</WarningLevel>
</GetItemRequest>"""
    try:
        r = requests.post("https://api.ebay.com/ws/api.dll",
                          headers=_ebay_headers("GetItem", ebay_cfg),
                          data=xml_body.encode(), timeout=30)
    except Exception as e:
        print(f"    GetItem network error for {item_id}: {e}")
        return None
    if r.status_code != 200:
        print(f"    GetItem HTTP {r.status_code} for {item_id}")
        return None
    try:
        root = ET.fromstring(r.text)
    except ET.ParseError as e:
        print(f"    GetItem parse error for {item_id}: {e}")
        return None
    ack = root.findtext(f".//{{{EBAY_NS}}}Ack", "")
    if ack not in ("Success", "Warning"):
        msg_el = root.find(f".//{{{EBAY_NS}}}Errors/{{{EBAY_NS}}}ShortMessage")
        msg = msg_el.text if msg_el is not None else "unknown error"
        print(f"    GetItem failed {item_id}: {msg}")
        return None

    title_el = root.find(f".//{{{EBAY_NS}}}Item/{{{EBAY_NS}}}Title")
    desc_el  = root.find(f".//{{{EBAY_NS}}}Item/{{{EBAY_NS}}}Description")
    cat_id   = root.find(f".//{{{EBAY_NS}}}Item/{{{EBAY_NS}}}PrimaryCategory/{{{EBAY_NS}}}CategoryID")
    cat_name = root.find(f".//{{{EBAY_NS}}}Item/{{{EBAY_NS}}}PrimaryCategory/{{{EBAY_NS}}}CategoryName")

    specifics: dict[str, str] = {}
    for nv in root.findall(f".//{{{EBAY_NS}}}ItemSpecifics/{{{EBAY_NS}}}NameValueList"):
        name = nv.findtext(f"{{{EBAY_NS}}}Name", "")
        values = [v.text for v in nv.findall(f"{{{EBAY_NS}}}Value") if v.text]
        if name and values:
            specifics[name.strip()] = " | ".join(v.strip() for v in values)

    return {
        "item_id":       item_id,
        "title":         (title_el.text if title_el is not None else "") or "",
        "description":   (desc_el.text if desc_el is not None else "") or "",
        "category_id":   (cat_id.text if cat_id is not None else "") or "",
        "category_name": (cat_name.text if cat_name is not None else "") or "",
        "specifics":     specifics,
        "fetched_at":    int(time.time()),
    }


def revise_item_specifics(item_id: str, all_specifics: dict[str, str],
                          token: str, ebay_cfg: dict) -> dict:
    """ReviseItem with the FULL specifics block (existing + new merged).
    eBay's API replaces the entire ItemSpecifics block when present, so we
    must send all values together — never just the new ones."""
    nvls = []
    for name, value in all_specifics.items():
        # Escape XML special chars
        safe_name  = (name or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        safe_value = (value or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        nvls.append(
            f"<NameValueList>"
            f"<Name>{safe_name}</Name>"
            f"<Value>{safe_value}</Value>"
            f"</NameValueList>"
        )
    xml_body = f"""<?xml version="1.0" encoding="utf-8"?>
<ReviseItemRequest xmlns="{EBAY_NS}">
  <RequesterCredentials><eBayAuthToken>{token}</eBayAuthToken></RequesterCredentials>
  <Item>
    <ItemID>{item_id}</ItemID>
    <ItemSpecifics>{''.join(nvls)}</ItemSpecifics>
  </Item>
</ReviseItemRequest>"""
    try:
        r = requests.post("https://api.ebay.com/ws/api.dll",
                          headers=_ebay_headers("ReviseItem", ebay_cfg),
                          data=xml_body.encode("utf-8"), timeout=30)
    except Exception as e:
        return {"ok": False, "ack": "Failure", "errors": [{"code": "net", "msg": str(e)}], "http": 0}
    try:
        root = ET.fromstring(r.text)
    except ET.ParseError as e:
        return {"ok": False, "ack": "Failure", "errors": [{"code": "parse", "msg": str(e)}], "http": r.status_code}
    ack = root.findtext(f".//{{{EBAY_NS}}}Ack", "")
    errors = []
    for err in root.findall(f".//{{{EBAY_NS}}}Errors"):
        sm   = err.findtext(f"{{{EBAY_NS}}}ShortMessage", "") or ""
        code = err.findtext(f"{{{EBAY_NS}}}ErrorCode", "") or ""
        errors.append({"code": code, "msg": sm})
    return {"ok": ack in ("Success", "Warning"), "ack": ack, "errors": errors, "http": r.status_code}


# --------------------------------------------------------------------------- #
# Planning                                                                    #
# --------------------------------------------------------------------------- #

def plan_listing(listing: dict, item_data: dict, cfg: dict) -> dict:
    """Diff parsed targets vs current specifics. Return decision/gap list."""
    title = listing.get("title") or item_data.get("title", "")
    item_id = listing.get("item_id") or item_data.get("item_id", "")
    enriched_listing = dict(listing)
    # Pull in category info from GetItem if not in snapshot
    if not enriched_listing.get("category_id"):
        enriched_listing["category_id"] = item_data.get("category_id", "")
    if not enriched_listing.get("category"):
        enriched_listing["category"] = item_data.get("category_name", "")

    target, debug, card_type = build_target_specifics(
        enriched_listing, desc=item_data.get("description", "")
    )
    current = item_data.get("specifics", {}) or {}
    allowed = set(cfg["category_specific_fields"].get(card_type, []))
    skip_fields = set(cfg.get("skip_fields") or [])

    # Map our internal field names to eBay-canonical names where they diverge.
    # We try the canonical name first; if user already has a synonym filled, skip.
    SYNONYMS = {
        "Player":  ["Player", "Athlete", "Player/Athlete"],
        "Athlete": ["Athlete", "Player", "Player/Athlete"],
        "Parallel": ["Parallel/Variety", "Parallel", "Variation"],
        "Parallel/Variety": ["Parallel/Variety", "Parallel", "Variation"],
        "Original/Reprint": ["Original/Licensed Reprint", "Original/Reprint", "Reprint"],
        "Original/Licensed Reprint": ["Original/Licensed Reprint", "Original/Reprint"],
    }

    gaps: list[dict] = []
    for field, info in target.items():
        if field in skip_fields:
            continue
        # Pull synonyms to detect "already filled by another name"
        syns = SYNONYMS.get(field, [field])
        already_filled = any(s in current and current[s].strip() for s in syns)
        if already_filled:
            continue
        # Restrict to allowed category fields (if known). Loose match: also allow
        # the canonical synonym list members.
        canon_ok = (
            field in allowed
            or any(s in allowed for s in syns)
            or field in ("Athlete", "Parallel/Variety", "Original/Licensed Reprint",
                         "Professional Grader")
        )
        if not canon_ok:
            continue
        gaps.append({
            "field":          field,
            "current_value":  None,
            "proposed_value": info["value"],
            "confidence":     info["confidence"],
        })

    # Decide auto-apply status per config
    auto_high = cfg.get("auto_apply_high_confidence", True)
    auto_med  = cfg.get("auto_apply_medium_confidence", False)
    applicable = []
    for g in gaps:
        if g["confidence"] == "high" and auto_high:
            applicable.append(g)
        elif g["confidence"] == "medium" and auto_med:
            applicable.append(g)
        # low always skipped

    decision = "apply" if applicable else ("review" if gaps else "ok")
    return {
        "item_id":   item_id,
        "title":     title,
        "url":       listing.get("url") or f"https://www.ebay.com/itm/{item_id}",
        "card_type": card_type,
        "current_specifics": current,
        "gaps":      gaps,
        "applicable_gaps": applicable,
        "decision":  decision,
        "debug":     debug,
    }


def plan_all(listings: list[dict], cache: dict, cfg: dict, token: str,
             ebay_cfg: dict, use_cache: bool = True) -> list[dict]:
    plans: list[dict] = []
    now = int(time.time())
    for i, l in enumerate(listings, 1):
        iid = str(l.get("item_id"))
        cached = cache.get(iid)
        is_fresh = (
            use_cache
            and cached
            and (now - cached.get("fetched_at", 0)) < CACHE_TTL_SECONDS
            and "specifics" in cached
        )
        if is_fresh:
            item_data = cached
        elif not token:
            # Cache-only / no-token mode: skip network entirely. Use cached if
            # present (even if stale), else listing-only fallback.
            if cached:
                item_data = cached
            else:
                item_data = {
                    "item_id": iid, "title": l.get("title", ""),
                    "description": "", "category_id": "", "category_name": "",
                    "specifics": {}, "fetched_at": now,
                }
        else:
            print(f"  [{i}/{len(listings)}] GetItem {iid} ...")
            item_data = get_item(iid, token, ebay_cfg)
            if item_data is None:
                # Network/API miss — fall back to listing-only info
                item_data = {
                    "item_id": iid, "title": l.get("title", ""),
                    "description": "", "category_id": "", "category_name": "",
                    "specifics": {}, "fetched_at": now,
                }
            else:
                cache[iid] = item_data
                # Persist incrementally — GetItem is expensive
                if i % 5 == 0:
                    save_cache(cache)
            time.sleep(0.4)   # gentle pacing
        plans.append(plan_listing(l, item_data, cfg))
    save_cache(cache)
    return plans


# --------------------------------------------------------------------------- #
# Apply                                                                       #
# --------------------------------------------------------------------------- #

def apply_plan(plans: list[dict], cfg: dict, ebay_cfg: dict,
               only_item: str | None = None) -> list[dict]:
    token = promote.get_access_token(ebay_cfg)
    applied: list[dict] = []
    to_apply = [p for p in plans if p["decision"] == "apply" and p["applicable_gaps"]]
    if only_item:
        to_apply = [p for p in to_apply if str(p["item_id"]) == str(only_item)]
    cap = cfg.get("max_changes_per_run", 25)
    if len(to_apply) > cap:
        print(f"  Capping run at {cap} of {len(to_apply)} eligible listings")
        to_apply = to_apply[:cap]

    for p in to_apply:
        merged = dict(p["current_specifics"])
        added: list[str] = []
        for g in p["applicable_gaps"]:
            merged[g["field"]] = g["proposed_value"]
            added.append(f"{g['field']}={g['proposed_value']}")
        print(f"  → {p['item_id']}: adding {len(added)} specifics ({', '.join(added)[:120]})")
        result = revise_item_specifics(p["item_id"], merged, token, ebay_cfg)
        applied.append({
            "applied_at":  datetime.now(timezone.utc).isoformat(),
            "item_id":     p["item_id"],
            "title":       p["title"],
            "added":       added,
            "ok":          result["ok"],
            "ack":         result["ack"],
            "error":       (result["errors"][0]["msg"] if result["errors"] else None),
            "error_code":  (result["errors"][0]["code"] if result["errors"] else None),
            "url":         p.get("url"),
        })
        time.sleep(0.5)
    return applied


# --------------------------------------------------------------------------- #
# HTML report                                                                 #
# --------------------------------------------------------------------------- #

def _esc(s: str) -> str:
    if s is None:
        return ""
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def build_report(plans: list[dict], history: list[dict], cfg: dict) -> Path:
    run_ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    total_listings   = len(plans)
    listings_w_gaps  = sum(1 for p in plans if p["gaps"])
    total_gaps       = sum(len(p["gaps"]) for p in plans)
    auto_fixable     = sum(len(p["applicable_gaps"]) for p in plans)
    pct_w_gaps       = (100.0 * listings_w_gaps / total_listings) if total_listings else 0.0

    def _row(p: dict) -> str:
        gap_rows = []
        for g in p["gaps"]:
            conf = g["confidence"]
            gap_rows.append(
                f"<tr class='gap-row gap-{conf}'>"
                f"<td class='field'>{_esc(g['field'])}</td>"
                f"<td class='current'>{_esc(g.get('current_value') or '—')}</td>"
                f"<td class='proposed'>{_esc(g['proposed_value'])}</td>"
                f"<td><span class='conf conf-{conf}'>{conf}</span></td>"
                f"</tr>"
            )
        if not gap_rows:
            return ""
        current_n = len(p["current_specifics"])
        return f"""
        <div class="listing-card decision-{p['decision']}">
          <div class="listing-head">
            <a href="{_esc(p['url'])}" target="_blank" rel="noopener" class="lhead-link">
              <span class="ltitle">{_esc((p['title'] or '')[:110])}</span>
              <span class="liid">{_esc(p['item_id'])}</span>
            </a>
            <div class="lmeta">
              <span class="badge badge-{p['card_type']}">{p['card_type'].replace('_', ' ')}</span>
              <span class="muted">{current_n} existing · {len(p['gaps'])} gap{'s' if len(p['gaps'])!=1 else ''}</span>
              <span class="dec dec-{p['decision']}">{p['decision'].upper()}</span>
            </div>
          </div>
          <table class="gap-tbl">
            <thead><tr><th>Specific</th><th>Current</th><th>Proposed</th><th>Confidence</th></tr></thead>
            <tbody>{''.join(gap_rows)}</tbody>
          </table>
        </div>
        """

    cards_html = "\n".join(_row(p) for p in plans if p["gaps"])
    if not cards_html:
        cards_html = "<p class='empty'>No fixable gaps detected. All listings have their inferred specifics filled.</p>"

    # History
    recent = list(reversed(history))[:30]
    if recent:
        hist_rows = "\n".join(
            f"<tr><td>{_esc(h.get('applied_at','')[:19])}</td>"
            f"<td><a href='{_esc(h.get('url','#'))}' target='_blank'>{_esc(h.get('item_id'))}</a></td>"
            f"<td class='added'>{_esc((', '.join(h.get('added',[])))[:140])}</td>"
            f"<td>{'OK' if h.get('ok') else 'FAIL: ' + _esc(h.get('error') or '')}</td></tr>"
            for h in recent
        )
        hist_block = (
            f"<div class='tbl-wrap'><table class='reprice-tbl'>"
            f"<thead><tr><th>Applied</th><th>Item</th><th>Added</th><th>Result</th></tr></thead>"
            f"<tbody>{hist_rows}</tbody></table></div>"
        )
    else:
        hist_block = "<p class='empty'>No specifics changes applied yet.</p>"

    body = f"""
<section class="hero">
  <h1>Item Specifics Agent</h1>
  <p class="sub">Last run: <code>{run_ts}</code></p>
  <div class="stat-grid">
    <div class="stat"><div class="stat-n">{auto_fixable}</div><div class="stat-l">gaps fixable today</div></div>
    <div class="stat"><div class="stat-n">{total_gaps}</div><div class="stat-l">total gaps detected</div></div>
    <div class="stat"><div class="stat-n">{listings_w_gaps}/{total_listings}</div><div class="stat-l">listings with gaps</div></div>
    <div class="stat"><div class="stat-n">{pct_w_gaps:.0f}%</div><div class="stat-l">coverage opportunity</div></div>
  </div>
  <p class="headline">{auto_fixable} gaps fixable today across {listings_w_gaps} listings.</p>
</section>

<section class="cfg">
  <h3>Active rules</h3>
  <ul class="cfg-list">
    <li>Auto-apply <strong>high</strong> confidence: {'yes' if cfg['auto_apply_high_confidence'] else 'no'}</li>
    <li>Auto-apply <strong>medium</strong> confidence: {'yes' if cfg['auto_apply_medium_confidence'] else 'no'}</li>
    <li>Low confidence: always skipped (review only)</li>
    <li>Max ReviseItem calls per run: {cfg.get('max_changes_per_run', 25)}</li>
    <li>Never overwrites existing specifics — gap-fill only</li>
  </ul>
  <p class="hint">Edit <code>specifics_config.json</code> at repo root to tune. Run: <code>python specifics_agent.py</code> (dry) or <code>--apply</code>.</p>
</section>

<section>
  <h3>Per-listing gap detail</h3>
  {cards_html}
</section>

<section>
  <h3>Recent applies</h3>
  {hist_block}
</section>
"""

    extra_css = """
<style>
  .hero { padding: 24px 0 12px; }
  .hero h1 { margin: 0 0 4px; font-family: 'Bebas Neue', sans-serif; font-size: 56px; letter-spacing: .02em; }
  .hero .sub { color: var(--text-muted); }
  .hero .headline { font-size: 18px; color: var(--gold); margin-top: 14px; }
  .stat-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 12px; margin: 18px 0; }
  .stat { background: var(--surface); border: 1px solid var(--border); border-radius: var(--r-md); padding: 14px 16px; }
  .stat-n { font-family: 'Bebas Neue', sans-serif; font-size: 36px; color: var(--gold); line-height: 1; }
  .stat-l { color: var(--text-muted); font-size: 12px; text-transform: uppercase; letter-spacing: .08em; margin-top: 4px; }
  .cfg { background: var(--surface-2); border: 1px solid var(--border); border-radius: var(--r-md); padding: 14px 18px; margin: 18px 0; }
  .cfg h3 { margin: 0 0 8px; font-size: 14px; text-transform: uppercase; letter-spacing: .1em; color: var(--text-muted); }
  .cfg-list { list-style: none; padding: 0; margin: 0; display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 6px 18px; }
  .cfg-list li { color: var(--text); }
  .cfg .hint { color: var(--text-muted); font-size: 13px; margin: 10px 0 0; }
  .listing-card { background: var(--surface); border: 1px solid var(--border); border-radius: var(--r-md); padding: 14px 16px; margin: 12px 0; }
  .listing-card.decision-apply { border-left: 3px solid var(--success); }
  .listing-card.decision-review { border-left: 3px solid var(--warning); }
  .listing-head { display: flex; justify-content: space-between; align-items: flex-start; gap: 12px; flex-wrap: wrap; margin-bottom: 10px; }
  .lhead-link { text-decoration: none; flex: 1; min-width: 240px; }
  .ltitle { display: block; color: var(--text); font-weight: 600; }
  .liid { display: block; color: var(--text-dim); font-size: 11px; font-family: 'JetBrains Mono', monospace; margin-top: 2px; }
  .lhead-link:hover .ltitle { color: var(--gold); }
  .lmeta { display: flex; gap: 8px; align-items: center; }
  .badge { font-size: 10px; text-transform: uppercase; letter-spacing: .08em; padding: 3px 8px; border-radius: 4px; background: var(--surface-2); color: var(--text-muted); }
  .badge-pokemon_card { background: rgba(255, 220, 0, 0.12); color: #d4a000; }
  .badge-sports_card { background: rgba(80, 150, 255, 0.12); color: #6aa8ff; }
  .muted { color: var(--text-muted); font-size: 12px; }
  .dec { font-size: 11px; font-weight: 700; letter-spacing: .08em; padding: 3px 8px; border-radius: 4px; }
  .dec-apply { background: rgba(127,199,122,0.15); color: var(--success); }
  .dec-review { background: rgba(232,168,56,0.15); color: var(--warning); }
  .dec-ok { background: var(--surface-2); color: var(--text-muted); }
  .gap-tbl { width: 100%; border-collapse: collapse; font-size: 13px; }
  .gap-tbl th, .gap-tbl td { padding: 7px 10px; text-align: left; border-bottom: 1px solid var(--border); }
  .gap-tbl th { background: var(--surface-2); color: var(--text-muted); font-size: 11px; text-transform: uppercase; letter-spacing: .08em; }
  .gap-tbl .field { font-weight: 600; color: var(--text); }
  .gap-tbl .current { color: var(--text-dim); font-style: italic; }
  .gap-tbl .proposed { color: var(--gold); font-family: 'JetBrains Mono', monospace; font-size: 12px; }
  .conf { font-size: 10px; text-transform: uppercase; letter-spacing: .08em; padding: 2px 6px; border-radius: 3px; }
  .conf-high { background: rgba(127,199,122,0.15); color: var(--success); }
  .conf-medium { background: rgba(232,168,56,0.15); color: var(--warning); }
  .conf-low { background: var(--surface-2); color: var(--text-dim); }
  .tbl-wrap { overflow-x: auto; border-radius: var(--r-md); border: 1px solid var(--border); margin: 8px 0 24px; }
  table.reprice-tbl { width: 100%; border-collapse: collapse; font-size: 13px; }
  .reprice-tbl th, .reprice-tbl td { padding: 10px 12px; text-align: left; border-bottom: 1px solid var(--border); vertical-align: top; }
  .reprice-tbl th { background: var(--surface-2); color: var(--text-muted); font-size: 11px; text-transform: uppercase; letter-spacing: .08em; }
  .reprice-tbl .added { font-family: 'JetBrains Mono', monospace; color: var(--gold); font-size: 12px; }
  .empty { color: var(--text-muted); padding: 20px; text-align: center; background: var(--surface); border: 1px dashed var(--border); border-radius: var(--r-md); }
</style>
"""
    html = promote.html_shell("Item Specifics Agent · Harpua2001", body,
                              extra_head=extra_css, active_page="specifics.html")
    REPORT_PATH.parent.mkdir(exist_ok=True)
    REPORT_PATH.write_text(html, encoding="utf-8")
    return REPORT_PATH


# --------------------------------------------------------------------------- #
# Orchestration                                                               #
# --------------------------------------------------------------------------- #

def load_listings_snapshot() -> list[dict]:
    if not LISTINGS_SNAPSHOT.exists():
        sys.exit(f"Missing {LISTINGS_SNAPSHOT}. Run promote.py first.")
    data = json.loads(LISTINGS_SNAPSHOT.read_text())
    if isinstance(data, list):
        return data
    return data.get("listings", [])


def summarize(plans: list[dict]) -> None:
    apply_n  = sum(1 for p in plans if p["decision"] == "apply")
    review_n = sum(1 for p in plans if p["decision"] == "review")
    ok_n     = sum(1 for p in plans if p["decision"] == "ok")
    total_g  = sum(len(p["gaps"]) for p in plans)
    auto_g   = sum(len(p["applicable_gaps"]) for p in plans)
    print(f"\n  Plan summary: {apply_n} to apply · {review_n} review-only · {ok_n} clean")
    print(f"  Gaps: {total_g} total · {auto_g} auto-fixable today")


def main() -> int:
    ap = argparse.ArgumentParser(description="Item Specifics gap-filler for Harpua2001 listings.")
    ap.add_argument("--apply", action="store_true", help="Actually push specifics to eBay (default: dry run)")
    ap.add_argument("--no-fetch", action="store_true", help="Reuse cached GetItem responses (don't refresh)")
    ap.add_argument("--item", help="Limit apply to a single item_id (plan still computed for all)")
    ap.add_argument("--report-only", action="store_true", help="Rebuild docs/specifics.html from last plan")
    args = ap.parse_args()

    cfg = load_config()
    if not cfg.get("enabled", True):
        print("Specifics agent is disabled in specifics_config.json (set 'enabled': true).")
        return 0

    if args.report_only:
        plan_data = json.loads(PLAN_PATH.read_text()) if PLAN_PATH.exists() else {"plans": []}
        plans = plan_data.get("plans", []) if isinstance(plan_data, dict) else plan_data
        path = build_report(plans, load_history(), cfg)
        print(f"  Wrote {path}")
        return 0

    listings = load_listings_snapshot()
    print(f"  Loaded {len(listings)} listings from snapshot")

    ebay_cfg = json.loads(promote.CONFIG_FILE.read_text())
    cache = load_cache()

    # Token fetched lazily — only if we'll actually hit the API.
    # --no-fetch forces cache-only mode (skips all GetItem calls).
    if args.no_fetch:
        need_fetch = False
    else:
        need_fetch = any(
            str(l.get("item_id")) not in cache
            or (int(time.time()) - cache[str(l.get("item_id"))].get("fetched_at", 0)) > CACHE_TTL_SECONDS
            for l in listings
        )
    token = None
    if need_fetch:
        try:
            print("  Getting eBay access token...")
            token = promote.get_access_token(ebay_cfg)
        except Exception as e:
            print(f"  Could not get eBay token ({e}); falling back to cache-only mode")
            token = None

    plans = plan_all(listings, cache, cfg, token or "", ebay_cfg,
                     use_cache=(args.no_fetch or token is None))

    PLAN_PATH.parent.mkdir(exist_ok=True)
    PLAN_PATH.write_text(json.dumps({
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "config":       cfg,
        "plans":        plans,
    }, indent=2))
    summarize(plans)

    applied: list[dict] = []
    if args.apply:
        if token is None:
            print("  Cannot --apply without an eBay token.")
            return 1
        print("\n  Applying gap-fills to eBay...")
        applied = apply_plan(plans, cfg, ebay_cfg, only_item=args.item)
        append_history(applied)
        ok = sum(1 for a in applied if a["ok"])
        print(f"\n  Result: {ok}/{len(applied)} listings updated successfully.")
    else:
        print("\n  Dry run only. Re-run with --apply to push changes to eBay.")

    report = build_report(plans, load_history(), cfg)
    print(f"  Report: {report}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
