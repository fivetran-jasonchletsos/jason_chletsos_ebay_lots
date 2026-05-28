"""
build_collx_vs_ebay.py — generate docs/collx_vs_ebay.html comparing the
CollX-sourced inventory (inventory.csv) against live eBay listings
(output/listings_snapshot.json).

Three buckets:
  1. On both — listed on eBay AND tracked in CollX. Shows price drift if any.
  2. CollX only — in CollX inventory but no eBay match. Ready to list.
  3. eBay only — live on eBay but no CollX match. Pre-CollX inventory or
     non-card items the seller hasn't loaded into CollX yet.

Matching strategy:
  - Linkage DB exact match first. Any CollX card with status='live' AND a
    stamped ebay_item_id is treated as a confirmed match — pull the matching
    eBay listing from the snapshot by item_id, no fuzzy comparison needed.
  - Remaining inventory rows fall through to the legacy fuzzy matcher
    (SequenceMatcher + player + card-number boost) against eBay listings
    that haven't been claimed yet.
  - Each matched row carries a match_source so Jason can see migration
    progress as more cards get stamped through push_to_ebay.py.

Run:
    python3 build_collx_vs_ebay.py
"""
from __future__ import annotations

import csv
import html
import json
import re
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path

import linkage_db
import promote

REPO_ROOT = Path(__file__).parent
INV_PATH  = REPO_ROOT / "inventory.csv"
SNAP_PATH = REPO_ROOT / "output" / "listings_snapshot.json"
OUT_HTML  = REPO_ROOT / "docs" / "collx_vs_ebay.html"

MATCH_THRESHOLD = 0.62

MATCH_SOURCE_LINKAGE = "linkage DB (exact)"
MATCH_SOURCE_FUZZY   = "fuzzy (legacy)"


def normalize(s: str) -> str:
    s = (s or "").lower()
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def title_tokens(s: str) -> set[str]:
    return set(normalize(s).split())


def best_match(needle: str, hay_titles: list[str]) -> tuple[int, float]:
    """Return (index_into_hay, ratio) for the best fuzzy match. -1 if none."""
    nn = normalize(needle)
    best_idx, best_ratio = -1, 0.0
    for i, h in enumerate(hay_titles):
        ratio = SequenceMatcher(None, nn, normalize(h)).ratio()
        if ratio > best_ratio:
            best_idx, best_ratio = i, ratio
    return best_idx, best_ratio


def load_inventory() -> list[dict]:
    rows = []
    with INV_PATH.open(newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            rows.append(r)
    return rows


def load_listings() -> list[dict]:
    data = json.loads(SNAP_PATH.read_text())
    return data.get("listings", []) if isinstance(data, dict) else data


def _make_matched_row(row: dict, listing: dict, collx_title: str,
                      match_source: str, match_ratio: float) -> dict:
    try:
        ebay_price = float(listing.get("price") or 0)
    except (TypeError, ValueError):
        ebay_price = 0.0
    try:
        collx_market = float(row.get("collx_market_value") or 0)
    except ValueError:
        collx_market = 0.0
    return {
        "collx_title":   collx_title,
        "ebay_title":    listing.get("title", ""),
        "ebay_item_id":  listing.get("item_id", ""),
        "ebay_url":      listing.get("url", ""),
        "ebay_price":    ebay_price,
        "collx_market":  collx_market,
        "collx_id":      row.get("collx_id", ""),
        "match_ratio":   round(match_ratio, 3),
        "match_source":  match_source,
        "player":        row.get("player", ""),
        "card_number":   row.get("card_number", ""),
        "year":          row.get("year", ""),
        "image_url":     row.get("image_url", ""),
    }


def build_comparison() -> dict:
    inv = load_inventory()
    listings = load_listings()
    listing_titles = [l.get("title", "") for l in listings]
    listing_used = [False] * len(listings)

    # Build a fast index of eBay snapshot rows by item_id for the SQL-join path
    listings_by_id: dict[str, int] = {}
    for i, l in enumerate(listings):
        item_id = str(l.get("item_id") or "").strip()
        if item_id:
            listings_by_id[item_id] = i

    # Linkage DB exact matches first. status='live' and ebay_item_id present.
    link_index: dict[str, dict] = {}
    linkage_summary = {"total": 0, "by_status": {}}
    try:
        linkage_summary = linkage_db.summary()
        for row in linkage_db.all_links():
            cid = (row.get("collx_id") or "").strip()
            if cid:
                link_index[cid] = row
    except Exception:
        # If the linkage DB is unavailable we silently fall back to fuzzy.
        link_index = {}

    matched: list[dict] = []
    collx_only: list[dict] = []

    linkage_match_count = 0
    fuzzy_match_count   = 0

    for row in inv:
        collx_title = row.get("name") or " ".join([row.get("year", ""), row.get("set", ""), row.get("player", "")]).strip()
        cid = (row.get("collx_id") or "").strip()

        # ---- SQL JOIN: linkage DB exact match ----
        link = link_index.get(cid) if cid else None
        if link and (link.get("status") or "") == "live" and link.get("ebay_item_id"):
            item_id = str(link["ebay_item_id"]).strip()
            listing_idx = listings_by_id.get(item_id)
            if listing_idx is not None and not listing_used[listing_idx]:
                listing_used[listing_idx] = True
                matched.append(_make_matched_row(
                    row, listings[listing_idx], collx_title,
                    MATCH_SOURCE_LINKAGE, 1.0,
                ))
                linkage_match_count += 1
                continue

        # ---- FUZZY (legacy) path for everything else ----
        idx, ratio = best_match(collx_title, listing_titles)
        # Strengthen the match if player + card number are both present in the candidate title
        player_in = (row.get("player", "").lower() in (listing_titles[idx].lower() if idx >= 0 else ""))
        num = (row.get("card_number") or "").strip().lstrip("#")
        num_in = bool(num) and (f"#{num}" in (listing_titles[idx] if idx >= 0 else "") or
                                 f" {num} " in (listing_titles[idx] if idx >= 0 else "") or
                                 f" {num}$" in (listing_titles[idx] if idx >= 0 else ""))
        confident = ratio >= MATCH_THRESHOLD or (player_in and num_in)
        if idx >= 0 and confident and not listing_used[idx]:
            listing_used[idx] = True
            matched.append(_make_matched_row(
                row, listings[idx], collx_title,
                MATCH_SOURCE_FUZZY, ratio,
            ))
            fuzzy_match_count += 1
        else:
            try:
                collx_market = float(row.get("collx_market_value") or 0)
            except ValueError:
                collx_market = 0.0
            try:
                asking = float(row.get("collx_asking_price") or 0)
            except ValueError:
                asking = 0.0
            collx_only.append({
                "title":         collx_title,
                "collx_id":      row.get("collx_id", ""),
                "player":        row.get("player", ""),
                "year":          row.get("year", ""),
                "card_number":   row.get("card_number", ""),
                "parallel":      row.get("parallel", ""),
                "image_url":     row.get("image_url", ""),
                "collx_market":  collx_market,
                "asking":        asking,
                "best_guess":    listing_titles[idx][:80] if idx >= 0 else "",
                "best_ratio":    round(ratio, 3),
            })

    ebay_only: list[dict] = []
    for i, l in enumerate(listings):
        if not listing_used[i]:
            try:
                ebay_price = float(l.get("price") or 0)
            except (TypeError, ValueError):
                ebay_price = 0.0
            ebay_only.append({
                "title":        l.get("title", ""),
                "ebay_item_id": l.get("item_id", ""),
                "ebay_url":     l.get("url", ""),
                "ebay_price":   ebay_price,
                "image_url":    l.get("pic", ""),
            })

    return {
        "generated_at":         datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "collx_count":          len(inv),
        "ebay_count":           len(listings),
        "matched":              matched,
        "collx_only":           collx_only,
        "ebay_only":            ebay_only,
        "linkage_match_count":  linkage_match_count,
        "fuzzy_match_count":    fuzzy_match_count,
        "linkage_summary":      linkage_summary,
    }


def esc(s) -> str:
    return html.escape(str(s or ""))


def _linkage_banner(data: dict) -> str:
    """Render the linkage DB summary strip above the stat grid."""
    summary = data.get("linkage_summary") or {}
    by_status = summary.get("by_status") or {}
    total = summary.get("total") or 0
    live = by_status.get("live", 0)
    unlisted = by_status.get("unlisted", 0)
    sold = by_status.get("sold", 0)
    ended = by_status.get("ended", 0)
    removed = by_status.get("removed_from_collx", 0)
    if total == 0:
        return ('<div class="linkage-banner">'
                '<span class="lb-lbl">Linkage DB</span> '
                '<span>Not initialized &mdash; no CollX cards stamped yet.</span>'
                '</div>')
    parts = [
        f'<span class="lb-lbl">Linkage DB</span>',
        f'<span><b>{total}</b> total cards</span>',
        f'<span><b>{live}</b> live on eBay</span>',
        f'<span><b>{unlisted}</b> unlisted</span>',
    ]
    if sold:
        parts.append(f'<span><b>{sold}</b> sold</span>')
    if ended:
        parts.append(f'<span><b>{ended}</b> ended</span>')
    if removed:
        parts.append(f'<span><b>{removed}</b> removed from CollX</span>')
    parts.append(
        f'<span><b>{data["linkage_match_count"]}</b> compare-page matches via exact join, '
        f'<b>{data["fuzzy_match_count"]}</b> via fuzzy fallback</span>'
    )
    return '<div class="linkage-banner">' + "".join(parts) + '</div>'


PAGE_CSS = """
  .cve-wrap { max-width: 1280px; margin: 0 auto; padding: 16px 24px 80px; color: var(--text, #f1eadd); }
  .cve-wrap { --cve-gold: #c9a44a; --cve-surface: #161616; --cve-border: rgba(255,255,255,0.08);
              --cve-text: #f1eadd; --cve-text-muted: #b8a98d; --cve-text-dim: #6c5a2e;
              --cve-danger: #e07b6f; --cve-good: #8fb95f; }
  .cve-wrap header.cve-head { border-bottom: 1px solid var(--cve-border); padding-bottom: 18px; margin-bottom: 24px; }
  .cve-wrap .eyebrow { font-size: 10px; font-weight: 800; letter-spacing: 0.22em; text-transform: uppercase; color: var(--cve-gold); margin-bottom: 8px; }
  .cve-wrap h1 { font-family: 'Fraunces', Georgia, serif; font-style: italic; font-weight: 600; font-size: 40px; letter-spacing: -0.01em; margin: 0; color: var(--cve-text); }
  .cve-wrap h1 em { color: var(--cve-gold); }
  .cve-wrap .deck { color: var(--cve-text-muted); margin: 8px 0 0; max-width: 720px; font-size: 14px; }
  .cve-wrap .stat-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin: 22px 0 28px; }
  .cve-wrap .stat-card { background: var(--cve-surface); border: 1px solid var(--cve-border); border-radius: 8px; padding: 14px 18px; }
  .cve-wrap .stat-card .num { font-family: 'Fraunces', Georgia, serif; font-style: italic; font-weight: 600; font-size: 28px; color: var(--cve-gold); line-height: 1; }
  .cve-wrap .stat-card .lbl { font-size: 10px; font-weight: 700; letter-spacing: 0.16em; text-transform: uppercase; color: var(--cve-text-muted); margin-top: 6px; }
  .cve-wrap h2 { font-family: 'Fraunces', Georgia, serif; font-style: italic; font-weight: 600; font-size: 22px; margin: 28px 0 8px; color: var(--cve-text); }
  .cve-wrap h2 em { color: var(--cve-gold); }
  .cve-wrap .section-sub { color: var(--cve-text-muted); font-size: 13px; margin: 0 0 12px; }
  .cve-wrap table { width: 100%; border-collapse: collapse; background: var(--cve-surface); border-radius: 8px; overflow: hidden; }
  .cve-wrap th, .cve-wrap td { text-align: left; padding: 10px 12px; border-bottom: 1px solid var(--cve-border); vertical-align: top; font-size: 13px; }
  .cve-wrap th { font-size: 10px; font-weight: 700; letter-spacing: 0.16em; text-transform: uppercase; color: var(--cve-text-muted); background: rgba(255,255,255,0.02); }
  .cve-wrap td.num { font-variant-numeric: tabular-nums; white-space: nowrap; text-align: right; }
  .cve-wrap td.img-cell { width: 52px; }
  .cve-wrap td.img-cell img { width: 44px; height: 44px; object-fit: cover; border-radius: 4px; border: 1px solid var(--cve-border); }
  .cve-wrap td.img-cell .noimg { width: 44px; height: 44px; background: rgba(255,255,255,0.04); border-radius: 4px; display: flex; align-items: center; justify-content: center; color: var(--cve-text-dim); font-size: 10px; }
  .cve-wrap .title-line a { color: var(--cve-text); text-decoration: none; }
  .cve-wrap .title-line a:hover { color: var(--cve-gold); }
  .cve-wrap .sub { color: var(--cve-text-dim); font-size: 11px; margin-top: 3px; font-family: 'SF Mono', ui-monospace, Menlo, monospace; }
  .cve-wrap .hint { color: var(--cve-text-dim); font-size: 11px; margin-top: 3px; font-style: italic; }
  .cve-wrap .drift { font-family: 'SF Mono', ui-monospace, Menlo, monospace; font-size: 11px; font-weight: 600; }
  .cve-wrap .drift-up { color: var(--cve-good); }
  .cve-wrap .drift-down { color: var(--cve-danger); }
  .cve-wrap .drift-flat { color: var(--cve-text-dim); }
  .cve-wrap .src-badge { display: inline-block; font-family: 'SF Mono', ui-monospace, Menlo, monospace; font-size: 10px; font-weight: 700; letter-spacing: 0.06em; text-transform: uppercase; padding: 3px 8px; border-radius: 999px; border: 1px solid var(--cve-border); white-space: nowrap; }
  .cve-wrap .src-linkage { color: var(--cve-good); background: rgba(143,185,95,0.08); border-color: rgba(143,185,95,0.30); }
  .cve-wrap .src-fuzzy   { color: var(--cve-text-dim); background: rgba(255,255,255,0.02); }
  .cve-wrap .linkage-banner { background: var(--cve-surface); border: 1px solid var(--cve-border); border-left: 3px solid var(--cve-gold); border-radius: 6px; padding: 12px 18px; margin: 0 0 18px; display: flex; flex-wrap: wrap; gap: 18px; align-items: baseline; font-size: 13px; color: var(--cve-text-muted); }
  .cve-wrap .linkage-banner b { color: var(--cve-gold); font-family: 'Fraunces', Georgia, serif; font-style: italic; font-weight: 600; font-size: 16px; }
  .cve-wrap .linkage-banner .lb-lbl { font-size: 10px; font-weight: 700; letter-spacing: 0.14em; text-transform: uppercase; color: var(--cve-text-dim); }
  .cve-wrap details { margin-top: 12px; background: var(--cve-surface); border: 1px solid var(--cve-border); border-radius: 8px; }
  .cve-wrap details summary { padding: 12px 16px; cursor: pointer; font-size: 13px; font-weight: 600; color: var(--cve-text); }
  .cve-wrap details summary span { color: var(--cve-text-muted); margin-left: 6px; font-weight: 400; }
  .cve-wrap details > div { padding: 0 0 4px; }
  .cve-wrap details table { border-radius: 0; }
  .cve-wrap .cve-footer { margin-top: 36px; padding-top: 16px; border-top: 1px solid var(--cve-border); color: var(--cve-text-dim); font-size: 11px; font-family: 'SF Mono', ui-monospace, Menlo, monospace; }
  .cve-wrap .cve-footer a { color: var(--cve-gold); }

  /* Push-to-eBay selection bar for the CollX-only bucket */
  .cve-wrap .push-bar { position: sticky; top: 0; z-index: 5; background: var(--cve-surface);
                        border: 1px solid var(--cve-border); border-left: 3px solid var(--cve-gold);
                        border-radius: 8px; padding: 12px 16px; margin: 6px 0 12px;
                        display: flex; flex-wrap: wrap; align-items: center; gap: 14px;
                        box-shadow: 0 4px 18px rgba(0,0,0,0.35); }
  .cve-wrap .push-bar .pb-label { font-size: 10px; font-weight: 800; letter-spacing: 0.22em;
                                  text-transform: uppercase; color: var(--cve-gold); }
  .cve-wrap .push-bar .pb-count { font-family: 'Fraunces', Georgia, serif; font-style: italic;
                                  font-weight: 600; font-size: 18px; color: var(--cve-text); }
  .cve-wrap .push-bar .pb-count .pb-n { color: var(--cve-gold); }
  .cve-wrap .push-bar button, .cve-wrap .push-bar .pb-link {
      background: transparent; border: 1px solid var(--cve-border); color: var(--cve-text);
      font-family: 'Inter', -apple-system, system-ui, sans-serif; font-size: 12px;
      font-weight: 600; letter-spacing: 0.04em; padding: 7px 12px; border-radius: 6px;
      cursor: pointer; transition: all 0.15s ease; }
  .cve-wrap .push-bar button:hover { border-color: var(--cve-gold); color: var(--cve-gold); }
  .cve-wrap .push-bar button.pb-copy { border-color: var(--cve-gold); color: var(--cve-gold);
                                       background: rgba(201,164,74,0.08); }
  .cve-wrap .push-bar button.pb-copy:hover { background: rgba(201,164,74,0.18); }
  .cve-wrap .push-bar button.pb-copy:disabled { opacity: 0.4; cursor: not-allowed; }
  .cve-wrap .push-bar button.pb-copy.pb-flash { background: var(--cve-good); color: #0a0a0a;
                                                border-color: var(--cve-good); }
  .cve-wrap .push-bar .pb-spacer { flex: 1; }
  .cve-wrap .push-bar .pb-hint { font-size: 11px; color: var(--cve-text-muted);
                                 font-family: 'SF Mono', ui-monospace, Menlo, monospace; }
  .cve-wrap td.check-cell { width: 36px; text-align: center; padding-top: 14px; }
  .cve-wrap td.check-cell input[type=checkbox] { width: 16px; height: 16px; cursor: pointer;
                                                 accent-color: var(--cve-gold); }
  .cve-wrap tr.cve-collx-row.is-selected { background: rgba(201,164,74,0.06); }
"""


PAGE_JS = """
<script>
(function() {
  var SECTION_ID = 'cve-collx-only-section';
  function rows() {
    var s = document.getElementById(SECTION_ID);
    if (!s) return [];
    return Array.prototype.slice.call(s.querySelectorAll('tr.cve-collx-row'));
  }
  function checked() {
    return rows().filter(function(r) {
      var cb = r.querySelector('input.cve-collx-check');
      return cb && cb.checked;
    });
  }
  function updateCount() {
    var n = checked().length;
    var el = document.querySelector('#' + SECTION_ID + ' .pb-n');
    if (el) el.textContent = String(n);
    var btn = document.querySelector('#' + SECTION_ID + ' .pb-copy');
    if (btn) btn.disabled = (n === 0);
    rows().forEach(function(r) {
      var cb = r.querySelector('input.cve-collx-check');
      if (!cb) return;
      r.classList.toggle('is-selected', cb.checked);
    });
  }
  function selectAll(val) {
    rows().forEach(function(r) {
      var cb = r.querySelector('input.cve-collx-check');
      if (cb) cb.checked = val;
    });
    updateCount();
  }
  function buildCmd() {
    var ids = checked().map(function(r) {
      return r.getAttribute('data-collx-id');
    }).filter(Boolean);
    if (!ids.length) return '';
    return 'for CID in ' + ids.join(' ') + '; do python3 push_to_ebay.py --collx-id $CID --apply; done';
  }
  function flash(btn, text) {
    var orig = btn.dataset.origLabel || btn.textContent;
    btn.dataset.origLabel = orig;
    btn.textContent = text;
    btn.classList.add('pb-flash');
    setTimeout(function() {
      btn.textContent = orig;
      btn.classList.remove('pb-flash');
    }, 2000);
  }
  function copyCmd(btn) {
    var cmd = buildCmd();
    if (!cmd) return;
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(cmd).then(function() {
        flash(btn, 'Copied \\u2014 paste in terminal');
      }, function() {
        flash(btn, 'Copy failed');
      });
    } else {
      // fallback
      var ta = document.createElement('textarea');
      ta.value = cmd;
      document.body.appendChild(ta);
      ta.select();
      try { document.execCommand('copy'); flash(btn, 'Copied \\u2014 paste in terminal'); }
      catch(e) { flash(btn, 'Copy failed'); }
      document.body.removeChild(ta);
    }
  }
  document.addEventListener('DOMContentLoaded', function() {
    var sec = document.getElementById(SECTION_ID);
    if (!sec) return;
    sec.addEventListener('change', function(ev) {
      if (ev.target && ev.target.classList && ev.target.classList.contains('cve-collx-check')) {
        updateCount();
      }
    });
    var btnAll = sec.querySelector('.pb-select-all');
    var btnClr = sec.querySelector('.pb-clear');
    var btnCpy = sec.querySelector('.pb-copy');
    if (btnAll) btnAll.addEventListener('click', function() { selectAll(true); });
    if (btnClr) btnClr.addEventListener('click', function() { selectAll(false); });
    if (btnCpy) btnCpy.addEventListener('click', function() { copyCmd(btnCpy); });
    updateCount();
  });
})();
</script>
"""


def render_extra_head() -> str:
    return f"<style>{PAGE_CSS}</style>\n{PAGE_JS}"


def render_body(data: dict) -> str:
    m, co, eo = data["matched"], data["collx_only"], data["ebay_only"]
    total_collx_market = sum(r["collx_market"] for r in co)
    total_collx_asking = sum(r["asking"]       for r in co if r["asking"])
    matched_drift_count = sum(1 for r in m if r["collx_market"] and abs(r["ebay_price"] - r["collx_market"]) > max(0.50, 0.10 * r["collx_market"]))

    def row_matched(r: dict) -> str:
        img = f'<img src="{esc(r["image_url"])}" alt="" loading="lazy">' if r["image_url"] else '<div class="noimg">—</div>'
        drift = ""
        if r["collx_market"]:
            delta = r["ebay_price"] - r["collx_market"]
            pct = (delta / r["collx_market"]) * 100 if r["collx_market"] else 0
            arrow = "&uarr;" if delta > 0 else ("&darr;" if delta < 0 else "&middot;")
            cls = "drift-up" if delta > 0.5 else ("drift-down" if delta < -0.5 else "drift-flat")
            drift = f'<span class="drift {cls}">{arrow} ${abs(delta):.2f} ({pct:+.0f}%)</span>'
        source = r.get("match_source") or MATCH_SOURCE_FUZZY
        source_cls = "src-linkage" if source == MATCH_SOURCE_LINKAGE else "src-fuzzy"
        source_badge = f'<span class="src-badge {source_cls}">{esc(source)}</span>'
        return f"""
        <tr>
          <td class="img-cell">{img}</td>
          <td>
            <div class="title-line"><a href="{esc(r["ebay_url"])}" target="_blank" rel="noopener">{esc(r["ebay_title"][:90])}</a></div>
            <div class="sub">eBay {esc(r["ebay_item_id"])} &middot; CollX {esc(r["collx_id"])}</div>
          </td>
          <td class="num">${r["ebay_price"]:.2f}</td>
          <td class="num">${r["collx_market"]:.2f}</td>
          <td>{drift}</td>
          <td>{source_badge}</td>
        </tr>"""

    def row_collx_only(r: dict) -> str:
        img = f'<img src="{esc(r["image_url"])}" alt="" loading="lazy">' if r["image_url"] else '<div class="noimg">—</div>'
        price = f"${r['collx_market']:.2f}" if r["collx_market"] else "—"
        asking = f"${r['asking']:.2f}" if r["asking"] else "—"
        hint = ""
        if r["best_guess"] and r["best_ratio"] > 0.40:
            hint = f'<div class="hint">closest eBay title: "{esc(r["best_guess"])}" ({r["best_ratio"]:.2f})</div>'
        cid = esc(r["collx_id"])
        checkbox = (f'<input type="checkbox" class="cve-collx-check" '
                    f'aria-label="Select {cid} for push to eBay">') if r["collx_id"] else ""
        return f"""
        <tr class="cve-collx-row" data-collx-id="{cid}">
          <td class="check-cell">{checkbox}</td>
          <td class="img-cell">{img}</td>
          <td>
            <div class="title-line">{esc(r["title"][:90])}</div>
            <div class="sub">CollX {cid} &middot; {esc(r["parallel"]) or "&mdash;"}</div>
            {hint}
          </td>
          <td class="num">{price}</td>
          <td class="num">{asking}</td>
        </tr>"""

    def row_ebay_only(r: dict) -> str:
        img = f'<img src="{esc(r["image_url"])}" alt="" loading="lazy">' if r["image_url"] else '<div class="noimg">—</div>'
        return f"""
        <tr>
          <td class="img-cell">{img}</td>
          <td>
            <div class="title-line"><a href="{esc(r["ebay_url"])}" target="_blank" rel="noopener">{esc(r["title"][:90])}</a></div>
            <div class="sub">eBay {esc(r["ebay_item_id"])}</div>
          </td>
          <td class="num">${r["ebay_price"]:.2f}</td>
        </tr>"""

    matched_rows   = "".join(row_matched(r) for r in m)
    collx_rows     = "".join(row_collx_only(r) for r in co)
    ebay_rows      = "".join(row_ebay_only(r) for r in eo)

    push_bar = f"""
<div class="push-bar">
  <span class="pb-label">Push to eBay</span>
  <span class="pb-count"><span class="pb-n">0</span> selected</span>
  <button type="button" class="pb-select-all">Select all visible</button>
  <button type="button" class="pb-clear">Clear</button>
  <button type="button" class="pb-copy" disabled>Copy push command</button>
  <span class="pb-spacer"></span>
  <span class="pb-hint">Paste into terminal &middot; runs <code>push_to_ebay.py --collx-id $CID --apply</code> per card</span>
</div>"""

    asking_html = ''
    if total_collx_asking:
        asking_html = f' &middot; total asking-priced: <b style="color: var(--cve-gold);">${total_collx_asking:,.2f}</b>'

    return f"""<div class="cve-wrap">

<header class="cve-head">
  <div class="eyebrow">Harpua2001 &middot; Inventory comparison</div>
  <h1>CollX <em>vs</em> eBay</h1>
  <p class="deck">Which cards from the CollX collection are already live on eBay, which are still sitting unlisted, and which eBay listings predate CollX or aren't in it yet. Fuzzy-matched by normalized title plus a player + card-number boost.</p>
</header>

{_linkage_banner(data)}

<div class="stat-grid">
  <div class="stat-card"><div class="num">{data['collx_count']}</div><div class="lbl">In CollX</div></div>
  <div class="stat-card"><div class="num">{data['ebay_count']}</div><div class="lbl">Live on eBay</div></div>
  <div class="stat-card"><div class="num">{len(m)}</div><div class="lbl">On both</div></div>
  <div class="stat-card"><div class="num">{len(co)}</div><div class="lbl">CollX-only (unlisted)</div></div>
</div>

<section id="cve-collx-only-section">
<h2>CollX-only &mdash; <em>ready to list on eBay</em></h2>
<p class="section-sub">{len(co)} cards in CollX with no matching live eBay listing. Total CollX market value: <b style="color: var(--cve-gold);">${total_collx_market:,.2f}</b>{asking_html}.</p>
{push_bar}
<table>
  <thead><tr><th></th><th></th><th>Card</th><th class="num">CollX market</th><th class="num">Asking</th></tr></thead>
  <tbody>{collx_rows or '<tr><td colspan="5" style="padding:24px; text-align:center; color: var(--cve-text-dim);">Every CollX card has a live eBay listing.</td></tr>'}</tbody>
</table>
</section>

<details>
<summary>On both &mdash; eBay live + CollX tracked <span>({len(m)} matches: {data['linkage_match_count']} linkage DB exact, {data['fuzzy_match_count']} fuzzy legacy; {matched_drift_count} with price drift over 10% or $0.50)</span></summary>
<div>
<table>
  <thead><tr><th></th><th>Listing</th><th class="num">eBay price</th><th class="num">CollX market</th><th>Drift</th><th>Match source</th></tr></thead>
  <tbody>{matched_rows or '<tr><td colspan="6" style="padding:24px; text-align:center; color: var(--cve-text-dim);">No matches yet — fuzzy threshold may be too strict.</td></tr>'}</tbody>
</table>
</div>
</details>

<details>
<summary>eBay-only &mdash; live on eBay, not in CollX <span>({len(eo)} listings)</span></summary>
<div>
<table>
  <thead><tr><th></th><th>Listing</th><th class="num">eBay price</th></tr></thead>
  <tbody>{ebay_rows or '<tr><td colspan="3" style="padding:24px; text-align:center; color: var(--cve-text-dim);">Every eBay listing has a CollX match.</td></tr>'}</tbody>
</table>
</div>
</details>

<div class="cve-footer">
Generated {esc(data['generated_at'])} &middot; Source: <code>inventory.csv</code> + <code>output/listings_snapshot.json</code> &middot; Fuzzy match threshold {MATCH_THRESHOLD} (SequenceMatcher) with player + card-number boost.
</div>

</div>
"""


def main() -> int:
    data = build_comparison()
    OUT_HTML.parent.mkdir(parents=True, exist_ok=True)
    body = render_body(data)
    page = promote.html_shell(
        title="CollX vs eBay · Harpua2001",
        body=body,
        extra_head=render_extra_head(),
        active_page="collx_vs_ebay.html",
    )
    OUT_HTML.write_text(page, encoding="utf-8")
    print(f"  CollX in inventory:        {data['collx_count']}")
    print(f"  Live eBay listings:        {data['ebay_count']}")
    print(f"  Matched on both:           {len(data['matched'])}")
    print(f"    via linkage DB (exact):  {data['linkage_match_count']}")
    print(f"    via fuzzy (legacy):      {data['fuzzy_match_count']}")
    print(f"  CollX-only:                {len(data['collx_only'])}")
    print(f"  eBay-only:                 {len(data['ebay_only'])}")
    print(f"  Wrote {OUT_HTML}")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
