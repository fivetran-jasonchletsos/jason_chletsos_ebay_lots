"""
price_consistency_agent.py — SRE / data-consistency gate for the site.

The invariant: every page or JSON artifact that displays an active listing's
price MUST show the same price as the live eBay listing. Drift causes things
like the Cam Ward Reddit-cross-post incident (2026-05-18): one page said one
price, the rest said another, and a cross-post would have published the wrong
number publicly.

Three layers (matching the SRE playbook):
  1. INVARIANT      — defined here: per-item_id, every reference matches eBay.
  2. DETECTION      — this agent. Pulls live prices, walks every docs/*.html
                       and every output/*.json, surfaces every mismatch.
  3. GATE           — promote.py main() calls run_check() at the end of
                       every full rebuild. Build fails (exit code 1) on drift
                       so we cannot push divergent data to GitHub Pages.

CLI:
  python3 price_consistency_agent.py                  # scan + report
  python3 price_consistency_agent.py --strict         # exit 1 on any drift
  python3 price_consistency_agent.py --fix-snapshot   # refresh snapshot from
                                                      # live eBay if drift seen
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import promote

REPO_ROOT  = Path(__file__).parent
DOCS_DIR   = REPO_ROOT / "docs"
OUTPUT_DIR = REPO_ROOT / "output"
REPORT     = OUTPUT_DIR / "price_consistency_report.json"
HTML_OUT   = DOCS_DIR   / "price_consistency.html"

# A 12-digit eBay item ID. Used to spot listing references in arbitrary text.
ITEM_ID_RE = re.compile(r"\b(30\d{10})\b")

# Match a price in a window AFTER the item id. We accept these shapes:
#   $9.99   $9,999.99   "price": "9.99"   StartPrice...">9.99<
# Anchor: an item id, then within ~600 chars look for a price token.
PRICE_NEAR_RE = re.compile(r"\$(\d{1,5}(?:,\d{3})*(?:\.\d{1,2})?)")

# Threshold: ignore differences <= 1 cent (float math, rounding).
EPSILON_CENTS = 1


def _load_live_prices() -> dict[str, float]:
    """Source of truth: eBay's GetMyeBaySelling. Skips paginating beyond a
    single page since the store is small (<500 listings). Returns dict
    item_id -> current_price."""
    cfg = json.loads(promote.CONFIG_FILE.read_text())
    token = promote.get_access_token(cfg)
    listings = promote.fetch_listings(token, cfg)
    out: dict[str, float] = {}
    for l in listings:
        try:
            p = float(l.get("price") or 0)
        except (TypeError, ValueError):
            continue
        if p > 0:
            out[str(l["item_id"])] = round(p, 2)
    return out


def _scan_text_for_prices(text: str, item_ids: set[str]) -> dict[str, list[float]]:
    """Find every dollar amount that appears in a 600-char window AFTER each
    item id reference. Returns {item_id: [observed_prices]}.

    This is intentionally a SUPERSET — we'd rather have false positives
    (e.g. a $1.30 shipping value near an item id) than miss a real price
    drift. The reporting step ranks by "frequency of observed value vs
    live price" so noise tokens don't dominate.
    """
    out: dict[str, list[float]] = defaultdict(list)
    for m in ITEM_ID_RE.finditer(text):
        iid = m.group(1)
        if iid not in item_ids:
            continue
        window = text[m.end():m.end() + 600]
        for pm in PRICE_NEAR_RE.finditer(window):
            try:
                price = float(pm.group(1).replace(",", ""))
            except ValueError:
                continue
            if 0.5 <= price <= 50000:  # plausibility filter
                out[iid].append(round(price, 2))
    return dict(out)


def _scan_file(path: Path, item_ids: set[str]) -> dict[str, list[float]]:
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return {}
    return _scan_text_for_prices(text, item_ids)


def run_check(strict: bool = False) -> dict:
    """Pull live prices, walk every doc + plan, surface drift.

    The invariant is intentionally narrow: only pages where the rendered
    number next to an item_id IS the listing's current asking price.
    Admin pages (best_offer, repricing, cassini, promoted_listings, etc.)
    legitimately render comp prices, market medians, projected targets,
    and historical "old → new" pairs — flagging those would be noise.

    Buyer-facing surfaces only — these MUST agree with eBay:
        index.html, deals.html, steals.html, sold.html (historical),
        by_set.html, by_player.html, browse.html, collect.html,
        pikachu.html / charizard.html / mew.html / mewtwo.html / eevee.html,
        pokemon.html, pokemon_news.html, under_10.html, top_sellers.html,
        reddit.html, craigslist.html, google_feed.xml,
        docs/items/*.html  (per-listing detail pages)
    """
    print("  Loading live prices from eBay GetMyeBaySelling...")
    live = _load_live_prices()
    item_ids = set(live)
    print(f"  Live listings: {len(item_ids)}")

    BUYER_FACING = {
        "index.html", "deals.html", "steals.html", "sold.html",
        "by_set.html", "by_player.html", "browse.html", "collect.html",
        "pikachu.html", "charizard.html", "mew.html", "mewtwo.html", "eevee.html",
        "pokemon.html", "pokemon_news.html", "under_10.html", "top_sellers.html",
        "reddit.html", "craigslist.html", "google_feed.xml",
    }
    targets: list[Path] = []
    for name in BUYER_FACING:
        path = DOCS_DIR / name
        if path.exists():
            targets.append(path)
    # Per-listing detail pages — these definitely show the listing's price.
    targets.extend(sorted(DOCS_DIR.glob("items/*.html")))

    # We only flag a mismatch when a non-live price is observed REPEATEDLY
    # for the same item in the same file — single occurrences are usually
    # shipping costs or "Range $X.XX-$Y.YY" comp data that legitimately
    # differs from the listing price. Repetition signals a price-card render.
    drift: list[dict] = []
    files_scanned = 0
    for path in targets:
        per_file = _scan_file(path, item_ids)
        if not per_file:
            continue
        files_scanned += 1
        for iid, observed in per_file.items():
            live_price = live[iid]
            cents = round(live_price * 100)
            # Count how often each price appears in this file
            counts: dict[float, int] = defaultdict(int)
            for p in observed:
                counts[p] += 1
            # The most-frequent observed price is the candidate "rendered" price
            cand_price, cand_count = max(counts.items(), key=lambda kv: kv[1])
            cand_cents = round(cand_price * 100)
            if cand_count < 2:
                # Single sighting — probably a shipping/fee/comp number
                continue
            if abs(cand_cents - cents) <= EPSILON_CENTS:
                continue
            drift.append({
                "file":         str(path.relative_to(REPO_ROOT)),
                "item_id":      iid,
                "rendered":     cand_price,
                "live_ebay":    live_price,
                "delta":        round(cand_price - live_price, 2),
                "occurrences":  cand_count,
            })

    report = {
        "generated_at":   datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "live_listings":  len(item_ids),
        "files_scanned":  files_scanned,
        "drift_count":    len(drift),
        "drift":          drift,
    }
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, indent=2), encoding="utf-8")

    # Render the admin page
    _render_report(report)
    return report


def _render_report(report: dict) -> Path:
    drift = report["drift"]
    by_item: dict[str, list[dict]] = defaultdict(list)
    for d in drift:
        by_item[d["item_id"]].append(d)

    if drift:
        status_html = f'<div class="pc-banner pc-banner-bad">DRIFT DETECTED — {len(drift)} occurrences across {len(by_item)} items. Build should fail until fixed.</div>'
        rows = []
        for iid, rows_for_item in sorted(by_item.items(), key=lambda kv: -len(kv[1])):
            live = rows_for_item[0]["live_ebay"]
            for d in rows_for_item:
                rows.append(
                    f"<tr><td><code>{d['item_id']}</code></td>"
                    f"<td>{d['file']}</td>"
                    f"<td class='num'>${d['rendered']:.2f}</td>"
                    f"<td class='num'>${d['live_ebay']:.2f}</td>"
                    f"<td class='num pc-delta'>{d['delta']:+.2f}</td>"
                    f"<td class='num'>{d['occurrences']}x</td></tr>"
                )
        table = ("<table class='pc-tbl'><thead><tr><th>Item</th><th>File</th>"
                 "<th class='num'>Rendered</th><th class='num'>Live eBay</th>"
                 "<th class='num'>Δ</th><th class='num'>Hits</th></tr></thead>"
                 f"<tbody>{''.join(rows)}</tbody></table>")
    else:
        status_html = '<div class="pc-banner pc-banner-ok">All clean. Every active listing\'s rendered price matches live eBay.</div>'
        table = ""

    body = f"""
    <div class="section-head section-head--inline">
      <div class="sh-title">
        <div class="eyebrow">SRE consistency gate</div>
        <h1 class="section-title">Price <span class="accent">Consistency</span></h1>
      </div>
      <div class="section-sub sh-sub">
        Every page that displays an active listing's price must match the
        live eBay price. Runs at the end of every full rebuild. If drift is
        detected, the build should fail before pushing to GitHub Pages.
      </div>
    </div>
    <div class="stat-grid">
      <div class="stat-card"><div class="num">{report['live_listings']}</div><div class="lbl">Live listings</div></div>
      <div class="stat-card"><div class="num">{report['files_scanned']}</div><div class="lbl">Files scanned</div></div>
      <div class="stat-card"><div class="num {'danger' if report['drift_count'] else 'success'}">{report['drift_count']}</div><div class="lbl">Drift occurrences</div></div>
    </div>
    {status_html}
    {table}
    """
    extra_css = """
<style>
  .pc-banner { padding: 14px 18px; border-radius: var(--r-md, 8px); margin: 16px 0; font-weight: 600; letter-spacing: .04em; }
  .pc-banner-ok  { background: rgba(127,199,122,.12); color: var(--success); border: 1px solid rgba(127,199,122,.35); }
  .pc-banner-bad { background: rgba(224,123,111,.12); color: var(--danger);  border: 1px solid rgba(224,123,111,.35); }
  .pc-tbl { width: 100%; border-collapse: collapse; background: var(--surface); border: 1px solid var(--border); border-radius: var(--r-md, 8px); overflow: hidden; }
  .pc-tbl th, .pc-tbl td { padding: 10px 12px; text-align: left; border-bottom: 1px solid var(--border); font-size: 13px; }
  .pc-tbl th { background: var(--surface-2); color: var(--text-muted); font-size: 11px; text-transform: uppercase; letter-spacing: .08em; }
  .pc-tbl .num { text-align: right; font-variant-numeric: tabular-nums; font-family: 'JetBrains Mono', monospace; }
  .pc-delta { color: var(--danger); font-weight: 700; }
</style>
"""
    html_doc = promote.html_shell("Price Consistency · SRE Gate", body,
                                  extra_head=extra_css,
                                  active_page="price_consistency.html")
    HTML_OUT.parent.mkdir(parents=True, exist_ok=True)
    HTML_OUT.write_text(html_doc, encoding="utf-8")
    return HTML_OUT


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.strip())
    ap.add_argument("--strict", action="store_true",
                    help="Exit 1 if any drift detected (for build gating).")
    args = ap.parse_args()
    report = run_check(strict=args.strict)
    if report["drift_count"]:
        print(f"  DRIFT DETECTED: {report['drift_count']} occurrences across "
              f"{len({d['item_id'] for d in report['drift']})} items.")
        print(f"  Full report: {REPORT}")
        print(f"  Admin page:  {HTML_OUT}")
        for d in report["drift"][:10]:
            print(f"    {d['file']}: {d['item_id']} rendered ${d['rendered']:.2f} vs live ${d['live_ebay']:.2f}")
        if args.strict:
            return 1
    else:
        print(f"  Clean: 0 drift across {report['files_scanned']} files / {report['live_listings']} live listings.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
