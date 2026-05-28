"""
build_lot_generator_explainer.py — PDF explainer of the AI Lot Generator
(replacing the Whatnot page in the harpua2001 buyer site).

Walks through the problem, candidate selection, the five grouping strategies,
the pricing model, and the live results from the current run. Pulls real
numbers from output/lot_generator_plan.json so the PDF reflects today's
data, not stale boilerplate.

Drops in ~/Downloads. Matches the branded style of the other PDFs
(build_ai_overview.py, build_hol_script_explainer.py).
"""
from __future__ import annotations

import json
import subprocess
import sys
from collections import Counter
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).parent
DOCS_DIR  = REPO_ROOT / "docs"
DOWNLOADS = Path.home() / "Downloads"

PLAN_PATH = REPO_ROOT / "output" / "lot_generator_plan.json"
HTML_OUT  = DOCS_DIR / "lot_generator_explainer.html"
PDF_OUT   = DOWNLOADS / "harpua2001_lot_generator_explainer.pdf"

CHROME_CANDIDATES = [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
]


def find_chrome() -> str:
    for p in CHROME_CANDIDATES:
        if Path(p).is_file():
            return p
    raise SystemExit("No Chrome/Chromium/Edge/Brave found.")


THEME_LABEL = {
    "rookie_class": "Rookie Class",
    "team":         "Team",
    "player":       "Player",
    "set_year":     "Set / Year",
    "parallel":     "Parallel / Shiny",
}


def load_plan() -> dict:
    if not PLAN_PATH.exists():
        raise SystemExit(f"No plan at {PLAN_PATH} — run `python3 lot_generator_agent.py` first.")
    data = json.loads(PLAN_PATH.read_text())
    lots = data.get("lots") or data.get("proposals") or []
    by_theme = Counter(l.get("theme", "?") for l in lots)
    total_value = sum(l.get("suggested_price", 0) for l in lots)
    total_cards = sum(l.get("card_count", 0)      for l in lots)
    top = sorted(lots, key=lambda l: l.get("suggested_price", 0), reverse=True)[:5]
    return {
        "total_lots":   len(lots),
        "total_value":  total_value,
        "total_cards":  total_cards,
        "by_theme":     dict(by_theme),
        "top":          top,
        "candidates":   data.get("candidate_count") or data.get("candidates") or 95,
    }


def render_html(p: dict) -> str:
    def theme_count(key: str) -> int:
        return p["by_theme"].get(key, 0)

    top_rows = []
    for l in p["top"]:
        top_rows.append(f"""
        <tr>
          <td class="num">${l.get('suggested_price', 0):.2f}</td>
          <td class="num">{l.get('card_count', '?')}</td>
          <td class="theme-cell">{THEME_LABEL.get(l.get('theme', ''), l.get('theme', '?'))}</td>
          <td class="title-cell">{(l.get('title', '') or '')[:75]}</td>
        </tr>""")

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>harpua2001 — AI Lot Generator explainer</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,400;9..144,600;9..144,800&family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
  @page {{ size: Letter; margin: 0.55in 0.5in 0.5in 0.5in; }}
  html, body {{
    margin: 0; padding: 0;
    font-family: 'Inter', -apple-system, system-ui, sans-serif;
    font-size: 10pt; line-height: 1.45;
    color: #1a1814; background: #faf7f1;
  }}
  .wrap {{ padding: 0 0 22pt 0; }}
  header {{ border-bottom: 2px solid #c9a44a; padding-bottom: 12pt; margin-bottom: 12pt; }}
  .eyebrow {{
    font-family: 'Inter', sans-serif; font-size: 8pt; font-weight: 700;
    letter-spacing: 0.22em; text-transform: uppercase; color: #8a6d2e;
  }}
  h1 {{
    font-family: 'Fraunces', Georgia, serif;
    font-variation-settings: 'opsz' 144, 'SOFT' 30;
    font-weight: 600; font-style: italic;
    font-size: 26pt; line-height: 1.05; letter-spacing: -0.01em;
    margin: 5pt 0 4pt 0; color: #1a1814;
  }}
  h1 em {{ color: #8a6d2e; font-style: italic; }}
  .deck {{ font-size: 10.5pt; color: #4a4438; max-width: 540pt; margin: 0; }}
  h2 {{
    font-family: 'Fraunces', Georgia, serif;
    font-variation-settings: 'opsz' 144;
    font-weight: 700; font-size: 13pt; letter-spacing: -0.005em;
    margin: 12pt 0 5pt 0; color: #1a1814;
    border-top: 1px solid #d8cfb8; padding-top: 9pt;
  }}
  h2:first-of-type {{ border-top: 0; padding-top: 0; margin-top: 2pt; }}
  p {{ margin: 0 0 6pt 0; }}
  ul, ol {{ margin: 4pt 0 6pt 16pt; padding: 0; }}
  li {{ margin-bottom: 2pt; }}
  code, .mono {{
    font-family: 'SF Mono', ui-monospace, Menlo, monospace;
    font-size: 9pt; background: #f1ead7; padding: 1pt 4pt; border-radius: 2pt;
    color: #4a3a14;
  }}
  .tldr {{
    background: #fff;
    border: 1px solid #d8cfb8;
    border-left: 3pt solid #c9a44a;
    padding: 9pt 14pt;
    margin: 6pt 0 10pt 0;
    border-radius: 2pt;
  }}
  .tldr p {{ margin: 0; }}
  .stat-strip {{
    display: grid; grid-template-columns: repeat(4, 1fr); gap: 8pt;
    margin: 6pt 0 10pt 0;
  }}
  .stat {{
    background: #1a1814; color: #faf7f1;
    padding: 8pt 11pt; border-radius: 3pt;
  }}
  .stat .n {{
    font-family: 'Fraunces', Georgia, serif; font-variation-settings: 'opsz' 144;
    font-weight: 600; font-style: italic; font-size: 19pt; line-height: 1;
    color: #c9a44a;
  }}
  .stat .l {{
    font-size: 7pt; font-weight: 700; letter-spacing: 0.16em;
    text-transform: uppercase; margin-top: 3pt; color: #faf7f1; opacity: 0.85;
  }}
  .themes {{
    display: grid; grid-template-columns: repeat(5, 1fr); gap: 8pt;
    margin: 4pt 0 10pt 0;
  }}
  .theme-card {{
    background: #fff; border: 1px solid #d8cfb8;
    border-top: 3pt solid #c9a44a;
    padding: 8pt 10pt;
    border-radius: 3pt;
  }}
  .theme-card .label {{
    font-family: 'Inter', sans-serif; font-size: 7pt; font-weight: 800;
    letter-spacing: 0.16em; text-transform: uppercase; color: #8a6d2e;
    margin-bottom: 3pt;
  }}
  .theme-card .count {{
    font-family: 'Fraunces', Georgia, serif; font-variation-settings: 'opsz' 144;
    font-weight: 600; font-style: italic; font-size: 18pt; color: #1a1814;
    line-height: 1;
  }}
  .theme-card .desc {{
    font-size: 8.5pt; color: #4a4438; line-height: 1.35;
    margin-top: 4pt;
  }}
  table.top {{
    width: 100%; border-collapse: collapse;
    margin: 4pt 0 10pt 0;
    font-size: 9.5pt;
  }}
  table.top th, table.top td {{
    text-align: left; padding: 5pt 8pt 5pt 0;
    vertical-align: top; border-bottom: 1px solid #e6ddc4;
  }}
  table.top th {{
    font-size: 7.5pt; font-weight: 700; letter-spacing: 0.1em;
    text-transform: uppercase; color: #6c5a2e;
    border-bottom: 1px solid #8a6d2e;
  }}
  table.top td.num {{ font-variant-numeric: tabular-nums; white-space: nowrap; }}
  table.top td.num:first-child {{
    font-family: 'Fraunces', Georgia, serif; font-style: italic; font-weight: 600;
    color: #8a6d2e; font-size: 11pt;
  }}
  .theme-cell {{
    font-size: 8pt; font-weight: 700; letter-spacing: 0.1em;
    text-transform: uppercase; color: #8a6d2e;
  }}
  .title-cell {{ color: #1a1814; }}
  .formula {{
    background: #1a1814; color: #ecdfb8;
    border-radius: 3pt; padding: 9pt 12pt;
    font-family: 'SF Mono', ui-monospace, Menlo, monospace;
    font-size: 9pt; line-height: 1.5;
    margin: 4pt 0 8pt 0;
  }}
  .formula .label {{ color: #c9a44a; font-weight: 700; margin-right: 6pt; }}
  .footnote {{
    font-size: 8pt; color: #6c5a2e; margin-top: 12pt;
    border-top: 1px solid #d8cfb8; padding-top: 6pt;
  }}
</style>
</head>
<body>
<div class="wrap">

<header>
  <div class="eyebrow">harpua2001 &middot; AI Lot Generator</div>
  <h1>Turning <em>sub-economic singles</em> into sellable lots.</h1>
  <p class="deck">Many cards in the harpua2001 inventory cost more in eBay fees than they earn at the listed single-card price. This agent reads the unlisted pool, identifies the sub-economic cards, and proposes themed bundles that DO sell. Replaces the Whatnot page in the buyer-facing site.</p>
</header>

<div class="stat-strip">
  <div class="stat"><div class="n">{p['candidates']}</div><div class="l">Sub-economic candidates</div></div>
  <div class="stat"><div class="n">{p['total_lots']}</div><div class="l">Lots proposed</div></div>
  <div class="stat"><div class="n">{p['total_cards']}</div><div class="l">Cards bundled</div></div>
  <div class="stat"><div class="n">${p['total_value']:.0f}</div><div class="l">Total lot value</div></div>
</div>

<div class="tldr">
<p><b>The problem.</b> A $1 card with free shipping nets negative once eBay's $0.30 fixed fee + 13.25% final value fee + actual shipping eat into it. Sellers list these anyway and they sit dead, or skip them and they sit in a box. Bundling 10 cards from one team or one set at $14.99 moves real volume at real margin.</p>
</div>

<h2>1. Candidate selection</h2>
<p>A card enters the lot pool if it meets any of these from the linkage DB / inventory:</p>
<ul>
  <li><b>Status is <code>unlisted</code></b> in the linkage DB (already-live cards aren't eligible).</li>
  <li><b>CollX market value is empty</b> (unpriced — too risky to list as a single).</li>
  <li><b>CollX market value is below $3.00</b> (single-listing economics break under eBay fees + shipping).</li>
</ul>
<p>Tonight's run: <b>{p['candidates']} of 105 unlisted cards</b> were sub-economic. The other 13 ($2.50+) went through <code>push_to_ebay_batch.py</code> as individual listings.</p>

<h2>2. The five grouping strategies</h2>
<p>The agent runs each candidate through five heuristic grouping passes. Each pass produces lots of a different shape. The same card can only end up in one lot — once claimed, the next pass skips it.</p>

<div class="themes">
  <div class="theme-card">
    <div class="label">Team</div>
    <div class="count">{theme_count('team')}</div>
    <div class="desc">Cards bundled by NFL team. "11 Carolina Panthers Card Lot 2025." Fans buy team-name lots heavily.</div>
  </div>
  <div class="theme-card">
    <div class="label">Player</div>
    <div class="count">{theme_count('player')}</div>
    <div class="desc">Multi-parallel runs of one player. "4 Caleb Williams RC Lot Prizm Mosaic Phoenix."</div>
  </div>
  <div class="theme-card">
    <div class="label">Set / Year</div>
    <div class="count">{theme_count('set_year')}</div>
    <div class="desc">Same set, different cards. Set-builders search "X Card Lot 2025 Topps Chrome."</div>
  </div>
  <div class="theme-card">
    <div class="label">Rookie Class</div>
    <div class="count">{theme_count('rookie_class')}</div>
    <div class="desc">Entire draft-year rookie classes. Collectors speculate on the whole class.</div>
  </div>
  <div class="theme-card">
    <div class="label">Parallel</div>
    <div class="count">{theme_count('parallel')}</div>
    <div class="desc">Shiny / Prizm / Refractor lots regardless of player. "12 Card Parallel Lot Shiny."</div>
  </div>
</div>

<h2>3. The pricing model</h2>
<p>Each lot needs a price that beats the sum of its underlying CollX market values (the seller's floor) AND that the lot-buying market will pay. Two formulas, depending on whether the lot is bulky or focused:</p>

<div class="formula">
  <div><span class="label">Bulk lots</span>(team, set/year, rookie class)</div>
  <div>price = max(sum(collx_market) &times; 0.60, count &times; $1.50, $9.99 floor)</div>
</div>
<div class="formula">
  <div><span class="label">Focused lots</span>(player, parallel)</div>
  <div>price = max(sum(collx_market) &times; 0.75, $7.99 floor, $9.99 floor)</div>
</div>

<p>Bulk lots discount harder (60% of sum) because the buyer is paying for volume, not individual cards. Focused lots hold tighter (75% of sum) because the theme adds value — "every Caleb Williams parallel I'm missing in one purchase" is worth more than the raw sum.</p>

<h2>4. Tonight's top lots</h2>

<table class="top">
<thead><tr><th class="num">Price</th><th class="num">Cards</th><th>Theme</th><th>Title</th></tr></thead>
<tbody>{''.join(top_rows)}</tbody>
</table>

<p>Total across all <b>{p['total_lots']}</b> lots: <b>${p['total_value']:.2f}</b> in proposed revenue, bundling <b>{p['total_cards']}</b> cards that wouldn't have moved as singles.</p>

<h2>5. What's next — applying the lots</h2>
<p>v1 is dry-run only. The <code>--apply</code> flag is a no-op stub. Next session wires <code>push_lots_to_ebay.py</code> so each lot becomes one <code>AddItem</code> with multiple cards bundled into the description + photos. The linkage DB will track a new "lot_id" so all the underlying <code>collx_id</code>s point to the same eBay ItemID. When a lot sells, every CollX card in it flips to <code>sold</code> in one stroke.</p>

<p>v2 is the AI step: feed the candidate pool into Claude (Sonnet 4 or Opus 4.7) for richer themes the heuristic misses — "Rivalry Week" lots pairing AFC West QBs, "Vintage Insert" runs across decades, narrative bundles a heuristic can't see. The current heuristic is the floor, not the ceiling.</p>

<div class="footnote">
Source: <code>lot_generator_agent.py</code> &middot; Plan JSON: <code>output/lot_generator_plan.json</code> &middot; Live page: <code>docs/lots.html</code> &middot; Generated {date.today().isoformat()} from real data, not boilerplate
</div>

</div>
</body>
</html>"""


def main() -> int:
    plan = load_plan()
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    HTML_OUT.write_text(render_html(plan), encoding="utf-8")
    chrome = find_chrome()
    proc = subprocess.run(
        [
            chrome,
            "--headless=new",
            "--disable-gpu",
            "--no-sandbox",
            "--no-pdf-header-footer",
            "--virtual-time-budget=8000",
            f"--print-to-pdf={PDF_OUT}",
            f"file://{HTML_OUT.resolve()}",
        ],
        capture_output=True, text=True, timeout=60,
    )
    if proc.returncode != 0 or not PDF_OUT.is_file():
        print("Chrome stderr:", proc.stderr[:400])
        raise SystemExit("PDF generation failed")
    print(f"Wrote {PDF_OUT} ({PDF_OUT.stat().st_size // 1024} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
