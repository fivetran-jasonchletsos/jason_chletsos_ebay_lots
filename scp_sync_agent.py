"""
scp_sync_agent.py — Bidirectional sync bridge between SportsCardsPro.com
collection management and this repo's inventory.csv / sold_history.json.

Flows
-----
1. SCP -> eBay-ready
   Reads a SportsCardsPro "My Collection" CSV export, fuzzily maps its
   columns onto our `inventory.csv` schema, derives missing fields from
   the product title (year, set, player, sport, parallel, grade/grader),
   and merges into inventory.csv preserving existing manual rows.

2. eBay -> SCP sold-back
   Cross-references inventory.csv against sold_history.json. Any inventory
   row whose title token-overlaps (>= 4) with a sold eBay item is treated
   as "this card sold". We:
     - emit output/scp_mark_sold.csv (id, status=sold, sold_date, sold_price)
       that JC bulk-imports into SCP's collection-management tool,
     - rewrite inventory.csv adding sold_at / sold_price / ebay_item_id
       columns; sold rows are kept in the CSV but marked so the inventory
       page renderer can hide them from "active" inventory.

CLI
---
  python3 scp_sync_agent.py --import-scp PATH/TO/scp_export.csv
  python3 scp_sync_agent.py --sync-sold
  python3 scp_sync_agent.py            # render page + run sold-back sync

Outputs
-------
  inventory.csv                       (mutated in place; backup as .bak)
  output/scp_mark_sold.csv            (bulk-import into SCP)
  output/scp_sync_plan.json           (machine-readable run report)
  docs/scp_sync.html                  (UI: import + sold-back + bookmarklet)
"""
from __future__ import annotations

import argparse
import csv
import html
import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

REPO_ROOT      = Path(__file__).parent
INVENTORY_CSV  = REPO_ROOT / "inventory.csv"
SOLD_HISTORY   = REPO_ROOT / "sold_history.json"
OUTPUT_DIR     = REPO_ROOT / "output"
DOCS_DIR       = REPO_ROOT / "docs"
MARK_SOLD_CSV  = OUTPUT_DIR / "scp_mark_sold.csv"
PLAN_PATH      = OUTPUT_DIR / "scp_sync_plan.json"
REPORT_PATH    = DOCS_DIR   / "scp_sync.html"

# Our canonical inventory column set (matches inventory_agent.py + new sold cols).
CORE_COLS = [
    "name", "year", "set", "card_number", "player", "sport",
    "parallel", "grade", "grader", "condition", "quantity",
    "acquired_price", "image_url", "notes",
]
SOLD_COLS = ["scp_id", "sold_at", "sold_price", "ebay_item_id"]
ALL_COLS  = CORE_COLS + SOLD_COLS


# --------------------------------------------------------------------------- #
# Column mapping rules                                                         #
# --------------------------------------------------------------------------- #

# SCP header (lower-cased, alnum-only) -> our canonical column.
# Heuristic / fuzzy: we match by these contains-substrings, longest first.
SCP_HEADER_RULES: list[tuple[str, str]] = [
    ("productname",      "name"),
    ("product",          "name"),
    ("title",            "name"),
    ("cardname",         "name"),
    ("name",             "name"),
    ("consolename",      "set"),
    ("console",          "set"),
    ("set",              "set"),
    ("category",         "sport"),
    ("sport",            "sport"),
    ("genre",            "sport"),
    ("cardnumber",       "card_number"),
    ("number",           "card_number"),
    ("cardno",           "card_number"),
    ("year",             "year"),
    ("player",           "player"),
    ("character",        "player"),
    ("parallel",         "parallel"),
    ("variant",          "parallel"),
    ("variation",        "parallel"),
    ("grade",            "grade"),
    ("grader",           "grader"),
    ("condition",        "condition"),
    ("quantity",         "quantity"),
    ("qty",              "quantity"),
    ("loosepriceprice",  "acquired_price"),   # never matches but kept for clarity
    ("looseprice",       "acquired_price"),
    ("cibprice",         "acquired_price"),
    ("newprice",         "acquired_price"),
    ("price",            "acquired_price"),
    ("value",            "acquired_price"),
    ("cost",             "acquired_price"),
    ("imageurl",         "image_url"),
    ("imageurl",         "image_url"),
    ("image",            "image_url"),
    ("photo",            "image_url"),
    ("note",             "notes"),
    ("comment",          "notes"),
    ("id",               "scp_id"),
]


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def guess_mapping(headers: Iterable[str]) -> dict[str, str]:
    """Map SCP CSV headers -> canonical column names.

    Returns a dict {scp_header: canonical_col}. Earlier rules in
    SCP_HEADER_RULES win when multiple SCP columns claim the same target.
    """
    mapping: dict[str, str] = {}
    taken_targets: set[str] = set()
    headers = list(headers)
    norm_headers = [(h, _norm(h)) for h in headers]
    # Try rules in order; longest rule keys first so 'productname' beats 'name'.
    rules = sorted(SCP_HEADER_RULES, key=lambda kv: -len(kv[0]))
    for rule_key, target in rules:
        if target in taken_targets:
            continue
        for orig, norm in norm_headers:
            if orig in mapping:
                continue
            if rule_key in norm:
                mapping[orig] = target
                taken_targets.add(target)
                break
    return mapping


# --------------------------------------------------------------------------- #
# Title-derived field extraction                                               #
# --------------------------------------------------------------------------- #

_FOOTBALL_KW   = ("nfl", "football", "panini prizm", "donruss", "score",
                  "select football", "mosaic football")
_BASKETBALL_KW = ("nba", "basketball", "hoops", "select basketball")
_BASEBALL_KW   = ("mlb", "baseball", "topps", "bowman")
_HOCKEY_KW     = ("nhl", "hockey", "upper deck hockey")
_POKEMON_KW    = ("pokemon", "pikachu", "charizard", "eevee", "mewtwo",
                  "mew ", "trainer gallery", "scarlet", "violet", "tcg")

_GRADERS = {"PSA", "BGS", "SGC", "CGC", "CSG", "HGA"}

_PARALLEL_KW = [
    "Refractor", "Silver Prizm", "Prizm", "Holo", "Reverse Holo", "Gold",
    "Red Prizm", "Blue Prizm", "Green Prizm", "Pink Prizm", "Camo",
    "Shimmer", "Disco", "Mojo", "Sparkle", "Cracked Ice", "Lazer",
    "Press Proof", "Optic", "Wave", "Pulsar", "Choice", "Hyper",
]


def categorize_sport(title: str, hint: str = "") -> str:
    """Cheap-and-cheerful sport categorization. Pokemon wins ties."""
    t = (title + " " + hint).lower()
    if any(k in t for k in _POKEMON_KW):
        return "Pokemon"
    if any(k in t for k in _BASKETBALL_KW):
        return "Basketball"
    if any(k in t for k in _BASEBALL_KW):
        return "Baseball"
    if any(k in t for k in _HOCKEY_KW):
        return "Hockey"
    if any(k in t for k in _FOOTBALL_KW):
        return "Football"
    return "Other"


def parse_year(text: str) -> str:
    m = re.search(r"\b(19[5-9]\d|20[0-3]\d)\b", text or "")
    return m.group(1) if m else ""


def parse_card_number(text: str) -> str:
    # Match #287, #58/102, #BS-1, etc.
    m = re.search(r"#\s*([A-Za-z]{0,4}-?\d+(?:/\d+)?)", text or "")
    return m.group(1) if m else ""


def parse_grade(text: str) -> tuple[str, str]:
    """Returns (grade, grader). e.g. 'PSA 10' -> ('10', 'PSA')."""
    if not text:
        return ("", "")
    for g in _GRADERS:
        m = re.search(rf"\b{g}\s*([0-9]{{1,2}}(?:\.[05])?)\b", text, re.IGNORECASE)
        if m:
            return (m.group(1), g)
        if re.search(rf"\b{g}\b", text, re.IGNORECASE):
            return ("", g)
    return ("", "")


def parse_parallel(text: str) -> str:
    if not text:
        return ""
    for p in _PARALLEL_KW:
        if re.search(rf"\b{re.escape(p)}\b", text, re.IGNORECASE):
            return p
    return ""


def parse_player(text: str) -> str:
    """Cheap heuristic — strip year/set/numbers, grab first 1-3 proper-noun-ish
    tokens. SCP titles often look like '2024 Topps Chrome Cam Ward #287'."""
    if not text:
        return ""
    s = re.sub(r"#\s*[A-Za-z0-9/\-]+", " ", text)
    s = re.sub(r"\b(19|20)\d{2}\b", " ", s)
    s = re.sub(r"[^A-Za-z\.\'\-\s]", " ", s)
    junk = {
        "topps", "chrome", "panini", "prizm", "donruss", "select", "mosaic",
        "optic", "hoops", "score", "bowman", "upper", "deck", "fleer", "leaf",
        "refractor", "silver", "gold", "rookie", "rc", "holo", "reverse",
        "pokemon", "tcg", "scarlet", "violet", "the", "a", "an", "of", "and",
        "base", "set", "trading", "card", "nfl", "nba", "mlb", "nhl",
        "football", "basketball", "baseball", "hockey", "lot", "cards",
    }
    toks = [t for t in s.split() if t.lower() not in junk and len(t) > 1]
    return " ".join(toks[:3]).strip()


# --------------------------------------------------------------------------- #
# Inventory I/O                                                                #
# --------------------------------------------------------------------------- #

def load_inventory_rows(path: Path = INVENTORY_CSV) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as f:
        return [
            {k.strip(): (v or "").strip() for k, v in row.items() if k}
            for row in csv.DictReader(f)
        ]


def write_inventory_rows(rows: list[dict[str, str]], path: Path = INVENTORY_CSV) -> None:
    # Preserve all columns ever seen; ensure canonical ordering then extras.
    seen: list[str] = []
    for c in ALL_COLS:
        seen.append(c)
    for r in rows:
        for k in r.keys():
            if k not in seen:
                seen.append(k)
    if path.exists():
        try:
            shutil.copy2(path, path.with_suffix(".csv.bak"))
        except OSError:
            pass
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=seen, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in seen})


def _dedupe_key(row: dict[str, str]) -> str:
    """Prefer SCP id; otherwise fall back to name+set+grade."""
    sid = (row.get("scp_id") or "").strip()
    if sid:
        return f"scp:{sid}"
    parts = [row.get("name", ""), row.get("set", ""), row.get("grade", "")]
    return "k:" + "|".join(p.strip().lower() for p in parts)


# --------------------------------------------------------------------------- #
# Import flow: SCP CSV -> inventory.csv                                        #
# --------------------------------------------------------------------------- #

def _row_from_scp(scp_row: dict[str, str], mapping: dict[str, str]) -> dict[str, str]:
    out: dict[str, str] = {c: "" for c in ALL_COLS}
    for scp_h, val in scp_row.items():
        target = mapping.get(scp_h)
        if not target:
            continue
        if not out.get(target):
            out[target] = (val or "").strip()

    title = out.get("name") or ""
    set_hint = out.get("set") or ""

    if not out.get("year"):
        out["year"] = parse_year(title) or parse_year(set_hint)
    if not out.get("card_number"):
        out["card_number"] = parse_card_number(title)
    if not out.get("parallel"):
        out["parallel"] = parse_parallel(title) or parse_parallel(set_hint)
    grade, grader = parse_grade(title)
    if not out.get("grade"):
        out["grade"] = grade
    if not out.get("grader"):
        out["grader"] = grader
    if not out.get("player"):
        out["player"] = parse_player(title)
    if not out.get("sport"):
        out["sport"] = categorize_sport(title, set_hint)
    if not out.get("condition"):
        # SCP 'loose' rough-equivalents.
        out["condition"] = "Near Mint"
    if not out.get("quantity"):
        out["quantity"] = "1"
    # Acquired price: strip $/commas.
    ap = out.get("acquired_price") or ""
    ap = re.sub(r"[^0-9.]", "", ap)
    out["acquired_price"] = ap
    return out


def import_scp_csv(scp_csv_path: str | Path,
                   inventory_csv_path: Path = INVENTORY_CSV) -> dict[str, Any]:
    """Import a SCP collection CSV into inventory.csv (merge + dedupe)."""
    src = Path(scp_csv_path)
    if not src.exists():
        raise FileNotFoundError(src)

    with src.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        headers = list(reader.fieldnames or [])
        mapping = guess_mapping(headers)
        scp_rows = list(reader)

    new_rows = [_row_from_scp(r, mapping) for r in scp_rows]
    new_rows = [r for r in new_rows if r.get("name")]

    existing = load_inventory_rows(inventory_csv_path)
    by_key: dict[str, dict[str, str]] = {}
    for r in existing:
        by_key[_dedupe_key(r)] = r

    added = 0
    updated = 0
    for r in new_rows:
        k = _dedupe_key(r)
        if k in by_key:
            # Fill missing fields without clobbering manual edits.
            cur = by_key[k]
            for col, val in r.items():
                if val and not cur.get(col):
                    cur[col] = val
            updated += 1
        else:
            by_key[k] = r
            added += 1

    merged = list(by_key.values())
    write_inventory_rows(merged, inventory_csv_path)
    return {
        "source": str(src),
        "headers": headers,
        "mapping": mapping,
        "added": added,
        "updated": updated,
        "total_rows_after": len(merged),
    }


# --------------------------------------------------------------------------- #
# Sold-back flow                                                               #
# --------------------------------------------------------------------------- #

_STOP_TOKENS = {
    "a", "an", "the", "of", "and", "or", "for", "with",
    "rc", "rookie", "card", "cards", "lot", "nfl", "nba", "mlb", "nhl",
}


def _tokens(s: str) -> set[str]:
    return {
        t for t in re.findall(r"[a-z0-9]+", (s or "").lower())
        if len(t) > 1 and t not in _STOP_TOKENS
    }


def find_sold_inventory(inventory_csv_path: Path = INVENTORY_CSV,
                        sold_history_path: Path = SOLD_HISTORY) -> dict[str, Any]:
    """Cross-reference inventory rows with sold_history.json sales.

    Returns:
      {
        "matched":   [{"inv": row, "sale": sale, "overlap": n, "tokens": [...]}],
        "unmatched": [sale, ...]   # ebay sales with no inventory hit
      }
    """
    inv = load_inventory_rows(inventory_csv_path)
    try:
        sales = json.loads(sold_history_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        sales = []
    if not isinstance(sales, list):
        sales = []

    # Skip inventory rows that are already marked sold.
    active = [r for r in inv if not (r.get("sold_at") or r.get("ebay_item_id"))]
    active_tokens = [(r, _tokens(r.get("name", ""))) for r in active]

    matched: list[dict[str, Any]] = []
    used_inv_keys: set[str] = set()
    unmatched: list[dict[str, Any]] = []

    for sale in sales:
        sale_toks = _tokens(sale.get("title", ""))
        if len(sale_toks) < 4:
            unmatched.append(sale)
            continue
        best, best_overlap = None, 0
        for r, toks in active_tokens:
            ik = _dedupe_key(r)
            if ik in used_inv_keys:
                continue
            overlap = len(sale_toks & toks)
            if overlap > best_overlap:
                best_overlap, best = overlap, r
        if best is not None and best_overlap >= 4:
            used_inv_keys.add(_dedupe_key(best))
            matched.append({
                "inv": best,
                "sale": sale,
                "overlap": best_overlap,
                "shared_tokens": sorted(_tokens(best.get("name", "")) & sale_toks),
            })
        else:
            unmatched.append(sale)

    return {"matched": matched, "unmatched": unmatched}


def generate_scp_mark_sold_csv(matched_pairs: list[dict[str, Any]],
                               out_path: Path = MARK_SOLD_CSV) -> Path:
    """Write SCP's bulk-import format: id, status, sold_date, sold_price, name."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cols = ["id", "status", "sold_date", "sold_price", "name", "ebay_item_id"]
    with out_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for m in matched_pairs:
            r = m["inv"]
            s = m["sale"]
            sold_date = (s.get("sold_date") or "").split("T")[0]
            w.writerow([
                r.get("scp_id", ""),
                "sold",
                sold_date,
                s.get("sale_price", ""),
                r.get("name", ""),
                s.get("item_id", ""),
            ])
    return out_path


def update_inventory_with_sold(matched_pairs: list[dict[str, Any]],
                               inventory_csv_path: Path = INVENTORY_CSV) -> int:
    """Stamp sold_at/sold_price/ebay_item_id on the matched inventory rows."""
    if not matched_pairs:
        return 0
    rows = load_inventory_rows(inventory_csv_path)
    # Index existing rows by canonical dedupe key.
    index: dict[str, dict[str, str]] = {_dedupe_key(r): r for r in rows}
    n = 0
    for m in matched_pairs:
        k = _dedupe_key(m["inv"])
        row = index.get(k)
        if row is None:
            continue
        if row.get("sold_at"):
            continue
        s = m["sale"]
        row["sold_at"]      = s.get("sold_date") or ""
        row["sold_price"]   = str(s.get("sale_price") or "")
        row["ebay_item_id"] = s.get("item_id") or ""
        n += 1
    write_inventory_rows(rows, inventory_csv_path)
    return n


# --------------------------------------------------------------------------- #
# HTML report                                                                  #
# --------------------------------------------------------------------------- #

_BOOKMARKLET_JS = (
    "javascript:(function(){"
    "var rows=document.querySelectorAll('table tr');"
    "var out=[];"
    "rows.forEach(function(tr){"
    "var cells=tr.querySelectorAll('td,th');"
    "var r=[];cells.forEach(function(c){r.push((c.innerText||'').trim());});"
    "if(r.length)out.push(r);});"
    "var blob=new Blob([JSON.stringify(out,null,2)],{type:'application/json'});"
    "var a=document.createElement('a');"
    "a.href=URL.createObjectURL(blob);"
    "a.download='scp_collection_'+Date.now()+'.json';"
    "document.body.appendChild(a);a.click();a.remove();"
    "})();"
)


def render_html(plan: dict[str, Any], out_path: Path = REPORT_PATH) -> Path:
    matched = plan.get("matched", [])
    unmatched_n = plan.get("unmatched_count", 0)
    import_info = plan.get("last_import") or {}
    generated_at = plan.get("generated_at", "")

    rows_html: list[str] = []
    for m in matched:
        inv = m.get("inv", {})
        sale = m.get("sale", {})
        sold_date = (sale.get("sold_date") or "").split("T")[0]
        rows_html.append(
            "<tr>"
            f"<td>{html.escape(inv.get('name','') or '')}</td>"
            f"<td>{html.escape(inv.get('scp_id','') or '')}</td>"
            f"<td>{html.escape(sale.get('title','') or '')}</td>"
            f"<td class='num'>${html.escape(str(sale.get('sale_price','')))}</td>"
            f"<td>{html.escape(sold_date)}</td>"
            f"<td class='num'>{m.get('overlap',0)}</td>"
            "</tr>"
        )
    matched_tbody = "\n".join(rows_html) or (
        "<tr><td colspan='6' style='text-align:center;opacity:.6;padding:24px;'>"
        "No matches yet — sell an inventory card on eBay and it will land here."
        "</td></tr>"
    )

    mapping_rows = ""
    if import_info.get("mapping"):
        for scp_h, tgt in (import_info.get("mapping") or {}).items():
            mapping_rows += (
                f"<tr><td>{html.escape(scp_h)}</td>"
                f"<td><code>{html.escape(tgt)}</code></td></tr>"
            )
    mapping_block = (
        f"<table class='mini'><thead><tr><th>SCP header</th><th>inventory.csv</th></tr></thead>"
        f"<tbody>{mapping_rows}</tbody></table>"
        if mapping_rows else
        "<p class='muted'>No SCP import has been run yet. Use the file picker above to map columns.</p>"
    )

    bookmarklet = html.escape(_BOOKMARKLET_JS, quote=True)

    body = f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>SportsCardsPro Sync · harpua2001</title>
<style>
  :root {{ color-scheme: dark; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, Segoe UI, Roboto, sans-serif;
         background:#0b0d12; color:#e6e9ef; margin:0; padding:24px; max-width:1100px;
         margin-left:auto; margin-right:auto; }}
  h1 {{ font-size: 1.6rem; margin: 0 0 8px; }}
  h2 {{ font-size: 1.15rem; margin: 28px 0 10px; border-bottom:1px solid #222; padding-bottom:6px; }}
  .muted {{ opacity:.65; }}
  .pill {{ display:inline-block; padding:2px 8px; border-radius:99px; background:#1b2030; font-size:.78rem; }}
  .card {{ background:#12151c; border:1px solid #1d2230; border-radius:12px; padding:18px; margin:14px 0; }}
  table {{ width:100%; border-collapse:collapse; font-size:.88rem; }}
  th, td {{ text-align:left; padding:8px 10px; border-bottom:1px solid #1d2230; vertical-align:top; }}
  th {{ background:#161a25; font-weight:600; }}
  td.num, th.num {{ text-align:right; font-variant-numeric: tabular-nums; }}
  .btn {{ display:inline-block; padding:10px 16px; border-radius:8px; background:#3a6cff;
          color:#fff; text-decoration:none; font-weight:600; cursor:pointer; border:0; }}
  .btn.alt {{ background:#1b2030; border:1px solid #2c3550; }}
  .drop {{ border:2px dashed #2c3550; border-radius:12px; padding:32px; text-align:center;
           background:#101319; }}
  .drop.over {{ border-color:#3a6cff; background:#161c2e; }}
  table.mini th, table.mini td {{ font-size:.8rem; padding:4px 8px; }}
  code {{ background:#1b2030; padding:1px 6px; border-radius:4px; }}
  a.book {{ display:inline-block; padding:10px 16px; background:#5a4cff; color:#fff;
            text-decoration:none; border-radius:8px; font-weight:600; }}
  .grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(200px,1fr)); gap:10px; }}
  .stat {{ background:#161a25; padding:12px; border-radius:8px; }}
  .stat .v {{ font-size:1.4rem; font-weight:700; }}
  .stat .l {{ opacity:.65; font-size:.78rem; text-transform:uppercase; letter-spacing:.04em; }}
</style>
</head><body>
  <h1>SportsCardsPro Sync</h1>
  <p class="muted">Bidirectional bridge between your <strong>SCP "My Collection"</strong>
     and this site's <code>inventory.csv</code> / eBay sold history.
     Generated {html.escape(generated_at)}.</p>

  <div class="grid">
    <div class="stat"><div class="v">{len(matched)}</div><div class="l">Sold matches</div></div>
    <div class="stat"><div class="v">{unmatched_n}</div><div class="l">eBay sales not in inventory</div></div>
    <div class="stat"><div class="v">{import_info.get('total_rows_after', '—')}</div><div class="l">Inventory rows</div></div>
  </div>

  <h2>1 · Import from SCP</h2>
  <div class="card">
    <div class="drop" id="drop">
      <p><strong>Drop a SCP collection CSV here</strong> or
         <input type="file" id="file" accept=".csv,text/csv"></p>
      <p class="muted" style="margin-top:0">We'll guess the column mapping. You can edit it before importing.</p>
    </div>
    <div id="preview" style="margin-top:14px"></div>
    <p class="muted" style="margin-top:14px">
      <strong>Server-side import:</strong>
      <code>python3 scp_sync_agent.py --import-scp PATH/TO/scp_export.csv</code>
    </p>
    <h3 style="font-size:1rem;margin-top:18px">Last import mapping</h3>
    {mapping_block}
  </div>

  <h2>2 · Sold-back to SCP</h2>
  <div class="card">
    <p class="muted">eBay sales matched (token overlap ≥ 4) to inventory rows.
       Download the CSV, then bulk-import it into SCP to mark these cards sold.</p>
    <p>
      <a class="btn" href="../output/scp_mark_sold.csv" download>Download SCP mark-sold CSV</a>
      <a class="btn alt" href="../output/scp_sync_plan.json" download>Plan JSON</a>
    </p>
    <table>
      <thead><tr>
        <th>Inventory card</th><th>SCP id</th><th>eBay title</th>
        <th class="num">Sale $</th><th>Sold</th><th class="num">Tokens</th>
      </tr></thead>
      <tbody>{matched_tbody}</tbody>
    </table>
  </div>

  <h2>3 · Bookmarklet</h2>
  <div class="card">
    <p class="muted">Drag this button to your bookmarks bar. On SCP's
       <em>My Collection</em> page, click it to scrape the table and download a JSON
       snapshot. (A future Lambda route <code>/ebay/scp-import</code> will accept POSTs.)</p>
    <p><a class="book" href="{bookmarklet}">SCP → JSON</a></p>
    <details>
      <summary class="muted">View bookmarklet source</summary>
      <pre style="overflow:auto;background:#0a0c12;padding:12px;border-radius:8px;font-size:.78rem">{html.escape(_BOOKMARKLET_JS)}</pre>
    </details>
  </div>

<script>
(function() {{
  var drop = document.getElementById('drop');
  var fileInput = document.getElementById('file');
  var preview = document.getElementById('preview');
  function handle(file) {{
    if (!file) return;
    var fr = new FileReader();
    fr.onload = function(e) {{
      var text = e.target.result;
      var lines = text.split(/\\r?\\n/).filter(Boolean).slice(0, 8);
      var rows = lines.map(function(l) {{ return l.split(/,(?=(?:[^"]*"[^"]*")*[^"]*$)/); }});
      var headers = rows[0] || [];
      var rules = {json.dumps({k: v for k, v in SCP_HEADER_RULES})};
      // Build a normalized lookup once.
      function norm(s) {{ return (s || '').toLowerCase().replace(/[^a-z0-9]/g, ''); }}
      var guessed = {{}};
      var taken = {{}};
      var ruleEntries = Object.keys(rules).sort(function(a,b) {{ return b.length - a.length; }}).map(function(k) {{ return [k, rules[k]]; }});
      headers.forEach(function(h, idx) {{
        var nh = norm(h);
        for (var i = 0; i < ruleEntries.length; i++) {{
          var rk = ruleEntries[i][0], tgt = ruleEntries[i][1];
          if (taken[tgt]) continue;
          if (nh.indexOf(rk) !== -1) {{
            guessed[h] = tgt; taken[tgt] = true; break;
          }}
        }}
      }});
      var html = '<h3 style="font-size:1rem;margin:8px 0">Preview · ' + file.name + '</h3>';
      html += '<table class="mini"><thead><tr>';
      headers.forEach(function(h) {{
        var g = guessed[h] || '';
        html += '<th>' + (h || '') + '<br><small style="opacity:.6">→ ' + (g || '(skip)') + '</small></th>';
      }});
      html += '</tr></thead><tbody>';
      rows.slice(1).forEach(function(r) {{
        html += '<tr>';
        r.forEach(function(c) {{ html += '<td>' + (c || '').replace(/^"|"$/g, '') + '</td>'; }});
        html += '</tr>';
      }});
      html += '</tbody></table>';
      html += '<p style="margin-top:12px"><button class="btn" type="button" onclick="alert(\\'Run on the server:\\\\npython3 scp_sync_agent.py --import-scp \\' + ' + JSON.stringify(file.name) + ')">Import to inventory.csv</button></p>';
      preview.innerHTML = html;
    }};
    fr.readAsText(file);
  }}
  if (fileInput) fileInput.addEventListener('change', function(e) {{ handle(e.target.files[0]); }});
  if (drop) {{
    ['dragenter','dragover'].forEach(function(ev) {{
      drop.addEventListener(ev, function(e) {{ e.preventDefault(); drop.classList.add('over'); }});
    }});
    ['dragleave','drop'].forEach(function(ev) {{
      drop.addEventListener(ev, function(e) {{ e.preventDefault(); drop.classList.remove('over'); }});
    }});
    drop.addEventListener('drop', function(e) {{
      var f = e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0];
      handle(f);
    }});
  }}
}})();
</script>
</body></html>
"""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(body, encoding="utf-8")
    return out_path


# --------------------------------------------------------------------------- #
# Orchestrator                                                                 #
# --------------------------------------------------------------------------- #

def run(args: argparse.Namespace) -> dict[str, Any]:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    DOCS_DIR.mkdir(parents=True, exist_ok=True)

    plan: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }

    if args.import_scp:
        info = import_scp_csv(args.import_scp)
        plan["last_import"] = info
        print(f"  SCP import: +{info['added']} new, {info['updated']} updated, "
              f"{info['total_rows_after']} total rows.")

    if args.sync_sold or not args.import_scp:
        res = find_sold_inventory()
        matched = res["matched"]
        unmatched = res["unmatched"]

        out = generate_scp_mark_sold_csv(matched)
        n_updated = update_inventory_with_sold(matched)

        plan["matched"] = [
            {
                "inv": {k: m["inv"].get(k, "") for k in ALL_COLS},
                "sale": {
                    "item_id":   m["sale"].get("item_id"),
                    "title":     m["sale"].get("title"),
                    "sold_date": m["sale"].get("sold_date"),
                    "sale_price": m["sale"].get("sale_price"),
                },
                "overlap":       m["overlap"],
                "shared_tokens": m["shared_tokens"],
            }
            for m in matched
        ]
        plan["unmatched_count"] = len(unmatched)
        plan["mark_sold_csv"]   = str(out.relative_to(REPO_ROOT))
        plan["inventory_marked_sold"] = n_updated

        print(f"  Sold-back: {len(matched)} inventory rows matched against "
              f"{len(matched) + len(unmatched)} eBay sales "
              f"({len(unmatched)} unmatched). "
              f"{n_updated} inventory rows newly stamped sold.")
        print(f"  Wrote {out.relative_to(REPO_ROOT)}")

    PLAN_PATH.write_text(json.dumps(plan, indent=2, default=str), encoding="utf-8")
    page = render_html(plan)
    print(f"  Rendered {page.relative_to(REPO_ROOT)}")
    return plan


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="SportsCardsPro <-> eBay sync bridge.")
    p.add_argument("--import-scp", metavar="PATH",
                   help="Import a SportsCardsPro collection CSV into inventory.csv.")
    p.add_argument("--sync-sold", action="store_true",
                   help="Run eBay -> SCP sold-back sync (default if no flags).")
    args = p.parse_args(argv)
    run(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
