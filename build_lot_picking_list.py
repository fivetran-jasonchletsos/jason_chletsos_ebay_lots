"""
build_lot_picking_list.py — printable picking-list PDF for the AI lot
generator's current proposals. One section per lot, thumbnails of every
included card so Jason can walk to his physical collection and pull each
card by sight.

Workflow:
  1. AI lot generator proposes lots from CollX cards not yet on eBay
     (linkage DB status='unlisted').
  2. This script renders a per-lot picking list with checkboxes + photos.
  3. Jason physically gathers the cards, marks each one off.
  4. push_lots_to_ebay.py (next session) takes the approved lots live.

Reads:  output/lot_generator_plan.json
Writes: ~/Downloads/harpua2001_lot_picking_list.pdf
        docs/lot_picking_list.html (for re-print without regen)
"""
from __future__ import annotations

import html
import json
import subprocess
import sys
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).parent
DOCS_DIR  = REPO_ROOT / "docs"
DOWNLOADS = Path.home() / "Downloads"

PLAN_PATH = REPO_ROOT / "output" / "lot_generator_plan.json"
HTML_OUT  = DOCS_DIR / "lot_picking_list.html"
PDF_OUT   = DOWNLOADS / "harpua2001_lot_picking_list.pdf"

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


def esc(s) -> str:
    return html.escape(str(s or ""))


THEME_LABEL = {
    "rookie_class": "Rookie Class Lot",
    "team":         "Team Lot",
    "player":       "Player Lot",
    "set_year":     "Set / Year Lot",
    "parallel":     "Parallel Lot",
}


def render_card(c: dict) -> str:
    img = (c.get("image_url") or "").strip()
    img_html = (f'<img src="{esc(img)}" alt="" loading="lazy">'
                if img else '<div class="noimg">no photo</div>')
    parallel = esc(c.get("parallel") or "")
    parallel_chip = f'<span class="pchip">{parallel}</span>' if parallel else ""
    try:
        mv = float(c.get("collx_market") or 0)
    except (TypeError, ValueError):
        mv = 0.0
    mv_html = f"${mv:.2f}" if mv else "—"
    return f"""
      <div class="card">
        <span class="check"></span>
        <div class="card-img">{img_html}</div>
        <div class="card-meta">
          <div class="card-name">{esc((c.get('name') or '')[:55])}</div>
          <div class="card-sub">{esc(c.get('player') or '')} {parallel_chip}</div>
          <div class="card-foot">
            <span class="card-id">{esc(c.get('collx_id') or '')}</span>
            <span class="card-mv">{mv_html}</span>
          </div>
        </div>
      </div>"""


def render_lot(i: int, lot: dict) -> str:
    cards_html = "".join(render_card(c) for c in (lot.get("cards") or []))
    theme = lot.get("theme") or ""
    theme_label = THEME_LABEL.get(theme, theme.replace("_", " ").title() or "Lot")
    try:
        sug = float(lot.get("suggested_price") or 0)
    except (TypeError, ValueError):
        sug = 0.0
    try:
        floor = float(lot.get("total_collx_market") or 0)
    except (TypeError, ValueError):
        floor = 0.0
    margin = sug - floor
    margin_class = "pos" if margin > 0 else "neg"
    # Strip the leading "N " count from the title — the "LOT NN / N cards" chip
    # above already shows count, and italic Fraunces "3" can read as "5" at heading
    # scale, causing confusion. The raw title with the count stays in the plan JSON
    # for the eBay listing.
    import re
    raw_title = (lot.get('title') or '')
    display_title = re.sub(r'^\d+\s+', '', raw_title)
    return f"""
    <section class="lot">
      <header class="lot-head">
        <div class="lot-num">Lot {i:02d} &middot; {lot.get('card_count', '?')} cards</div>
        <h2>{esc(display_title[:80])}</h2>
        <div class="lot-meta">
          <span class="theme-chip">{esc(theme_label)}</span>
          <span class="price">${sug:.2f}</span>
          <span class="floor">CollX sum ${floor:.2f}</span>
          <span class="margin {margin_class}">margin {('+' if margin >= 0 else '−')}${abs(margin):.2f}</span>
        </div>
        <p class="just">{esc((lot.get('justification') or '')[:200])}</p>
      </header>
      <div class="cards">{cards_html}</div>
    </section>"""


def last_name(player: str) -> str:
    parts = (player or "").strip().split()
    return parts[-1] if parts else ""


def render_az(lots_sorted: list[dict]) -> str:
    """A-Z text checklist — flat (card, lot_idx) pairs grouped by first letter
    of last name. No thumbnails — dense text rows for fast walking-the-binder
    check-off. Designed to fit on ~3-4 printed pages, not 30."""
    flat = []
    for lot_idx, lot in enumerate(lots_sorted, 1):
        for c in (lot.get("cards") or []):
            flat.append({
                "card":      c,
                "lot_idx":   lot_idx,
                "lot_title": lot.get("title", ""),
            })

    def key(item):
        ln = last_name(item["card"].get("player", "")).lower()
        return (ln or "z", (item["card"].get("player", "") or "").lower())

    flat.sort(key=key)

    import re as _re

    rows = []
    last_letter = None
    for item in flat:
        c = item["card"]
        ln = last_name(c.get("player", ""))
        letter = (ln[:1] or "?").upper()
        if letter != last_letter:
            rows.append(f'<tr class="letter-row"><td colspan="4"><span class="letter-mark">{letter}</span></td></tr>')
            last_letter = letter
        parallel = (c.get("parallel") or "").strip()
        parallel_chip = f' <span class="pchip">{esc(parallel)}</span>' if parallel else ""
        card_name = (c.get('name') or '')
        # Trim verbose set prefix to keep the row compact — e.g.
        # "2025 Panini Prizm Draft Picks Antwane Wells Jr. #94" stays full,
        # already concise enough at ~50 chars.
        disp_lot_title = _re.sub(r'^\d+\s+', '', item['lot_title'] or '')
        rows.append(f"""
        <tr>
          <td class="check-col"><span class="check"></span></td>
          <td class="player">{esc(c.get('player') or '')}{parallel_chip}</td>
          <td class="card-line">{esc(card_name[:60])}</td>
          <td class="lot-ref">Lot {item['lot_idx']:02d} &middot; {esc(disp_lot_title[:30])}</td>
        </tr>""")

    return f"""
      <table class="az-text-table">
        <tbody>{''.join(rows)}</tbody>
      </table>"""


def render_html(plan: dict) -> str:
    lots_raw = plan.get("lots") or plan.get("proposals") or []
    # Sort by card count ascending — smallest lots first for momentum
    lots = sorted(lots_raw, key=lambda l: (int(l.get("card_count") or 999),
                                            -float(l.get("suggested_price") or 0)))
    total_value = sum(float(l.get("suggested_price") or 0) for l in lots)
    total_cards = sum(int(l.get("card_count") or 0) for l in lots)
    lots_html = "".join(render_lot(i+1, l) for i, l in enumerate(lots))
    az_html = render_az(lots)
    today = date.today().isoformat()

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>harpua2001 — Lot Picking List</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,400;9..144,600;9..144,800&family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
  @page {{ size: Letter; margin: 0.45in 0.4in 0.45in 0.4in; }}
  html, body {{
    margin: 0; padding: 0;
    font-family: 'Inter', -apple-system, system-ui, sans-serif;
    font-size: 9.5pt; line-height: 1.4;
    color: #1a1814; background: #faf7f1;
  }}
  .wrap {{ padding: 0; }}
  /* Cover header */
  header.cover {{
    border-bottom: 2px solid #c9a44a;
    padding-bottom: 12pt;
    margin-bottom: 14pt;
  }}
  .eyebrow {{
    font-family: 'Inter', sans-serif; font-size: 8pt; font-weight: 700;
    letter-spacing: 0.22em; text-transform: uppercase; color: #8a6d2e;
  }}
  h1 {{
    font-family: 'Fraunces', Georgia, serif;
    font-variation-settings: 'opsz' 144, 'SOFT' 30;
    font-weight: 600; font-style: italic;
    font-size: 24pt; line-height: 1.05; letter-spacing: -0.01em;
    margin: 4pt 0 4pt 0; color: #1a1814;
  }}
  h1 em {{ color: #8a6d2e; font-style: italic; }}
  .deck {{ font-size: 10pt; color: #4a4438; max-width: 540pt; margin: 0; }}
  .stat-strip {{
    display: grid; grid-template-columns: repeat(4, 1fr); gap: 8pt;
    margin: 10pt 0 12pt 0;
  }}
  .stat {{
    background: #1a1814; color: #faf7f1;
    padding: 8pt 10pt; border-radius: 3pt;
  }}
  .stat .n {{
    font-family: 'Fraunces', Georgia, serif; font-variation-settings: 'opsz' 144;
    font-weight: 600; font-style: italic; font-size: 17pt; line-height: 1;
    color: #c9a44a;
  }}
  .stat .l {{
    font-size: 7pt; font-weight: 700; letter-spacing: 0.16em;
    text-transform: uppercase; margin-top: 3pt; opacity: 0.85;
  }}
  .tldr {{
    background: #fff; border: 1px solid #d8cfb8;
    border-left: 3pt solid #c9a44a;
    padding: 9pt 14pt; margin: 4pt 0 4pt 0; border-radius: 2pt;
    font-size: 9.5pt;
  }}
  .tldr p {{ margin: 0; }}

  /* Each lot — page break before so one lot per printed page where possible */
  .lot {{
    page-break-inside: avoid;
    page-break-before: always;
    padding-top: 4pt;
  }}
  .lot:first-of-type {{
    page-break-before: avoid;
    margin-top: 12pt;
  }}
  .lot-head {{
    border-bottom: 1.5pt solid #c9a44a;
    padding-bottom: 7pt; margin-bottom: 10pt;
  }}
  .lot-num {{
    font-size: 8pt; font-weight: 700; letter-spacing: 0.22em;
    text-transform: uppercase; color: #8a6d2e; margin-bottom: 2pt;
  }}
  .lot h2 {{
    font-family: 'Fraunces', Georgia, serif;
    font-variation-settings: 'opsz' 144;
    font-weight: 700; font-style: italic; font-size: 17pt;
    margin: 2pt 0 4pt 0; line-height: 1.15;
    color: #1a1814;
  }}
  .lot-meta {{
    display: flex; gap: 12pt; align-items: baseline; flex-wrap: wrap;
    margin: 4pt 0 4pt 0;
  }}
  .theme-chip {{
    font-size: 8pt; font-weight: 700; letter-spacing: 0.14em;
    text-transform: uppercase; color: #4a3a14;
    background: #f1ead7; padding: 2pt 8pt; border-radius: 999pt;
  }}
  .price {{
    font-family: 'Fraunces', Georgia, serif; font-variation-settings: 'opsz' 144;
    font-weight: 600; font-style: italic; font-size: 16pt; color: #8a6d2e;
    line-height: 1;
  }}
  .floor {{ font-size: 9pt; color: #6c5a2e; font-family: 'SF Mono', ui-monospace, Menlo, monospace; }}
  .margin {{ font-size: 9pt; font-family: 'SF Mono', ui-monospace, Menlo, monospace; font-weight: 700; }}
  .margin.pos {{ color: #5a7b3a; }}
  .margin.neg {{ color: #b85c44; }}
  .just {{
    font-size: 9pt; color: #4a4438; font-style: italic;
    margin: 4pt 0 0; line-height: 1.4;
  }}

  /* Card grid for the picking list */
  .cards {{
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 7pt;
  }}
  .card {{
    background: #fff;
    border: 1px solid #d8cfb8;
    border-radius: 3pt;
    padding: 6pt 7pt 7pt 7pt;
    position: relative;
    page-break-inside: avoid;
  }}
  .card .check {{
    position: absolute; top: 5pt; right: 5pt;
    width: 13pt; height: 13pt;
    border: 1.5pt solid #8a6d2e;
    border-radius: 2pt;
    background: #fff;
  }}
  .card-img {{
    width: 100%; aspect-ratio: 3 / 4;
    background: #f1ead7;
    border-radius: 2pt;
    overflow: hidden;
    display: flex; align-items: center; justify-content: center;
    margin-bottom: 5pt;
  }}
  .card-img img {{ width: 100%; height: 100%; object-fit: cover; }}
  .noimg {{ font-size: 8pt; color: #8a6d2e; }}
  .card-name {{ font-size: 8.5pt; font-weight: 600; color: #1a1814; line-height: 1.3; max-height: 30pt; overflow: hidden; }}
  .card-sub {{ font-size: 8pt; color: #4a4438; margin-top: 1pt; display: flex; align-items: center; gap: 4pt; flex-wrap: wrap; }}
  .pchip {{
    font-size: 7pt; font-weight: 700;
    color: #8a6d2e; background: #f1ead7;
    padding: 0 4pt; border-radius: 999pt; letter-spacing: 0.06em;
  }}
  .card-foot {{
    display: flex; justify-content: space-between; align-items: baseline;
    margin-top: 3pt;
  }}
  .card-id {{ font-family: 'SF Mono', ui-monospace, Menlo, monospace; font-size: 7pt; color: #8a6d2e; }}
  .card-mv {{ font-family: 'SF Mono', ui-monospace, Menlo, monospace; font-size: 8pt; color: #4a3a14; font-weight: 600; }}

  .footnote {{
    font-size: 8pt; color: #6c5a2e; margin-top: 14pt;
    border-top: 1px solid #d8cfb8; padding-top: 6pt;
  }}
  /* A-Z text checklist — dense, no thumbnails, fits ~50 rows per page */
  .az-text-table {{ width: 100%; border-collapse: collapse; font-size: 9pt; }}
  .az-text-table td {{
    padding: 2.5pt 6pt 2.5pt 0; vertical-align: baseline;
    border-bottom: 1px dotted #e6ddc4;
  }}
  .check-col {{ width: 14pt; }}
  .check-col .check {{
    display: inline-block; width: 10pt; height: 10pt;
    border: 1.2pt solid #8a6d2e; border-radius: 2pt; background: #fff;
  }}
  .player {{ font-weight: 700; font-size: 9pt; color: #1a1814; white-space: nowrap; width: 130pt; }}
  .pchip {{
    display: inline-block;
    font-size: 6.5pt; font-weight: 700;
    color: #8a6d2e; background: #f1ead7;
    padding: 0 4pt; border-radius: 999pt; letter-spacing: 0.06em;
    vertical-align: 1pt; margin-left: 3pt;
  }}
  .card-line {{ font-size: 9pt; color: #4a4438; }}
  .lot-ref {{ font-size: 8pt; color: #8a6d2e; font-family: 'SF Mono', ui-monospace, Menlo, monospace; white-space: nowrap; text-align: right; }}
  .letter-row td {{
    border-bottom: 1.5pt solid #c9a44a !important;
    padding-top: 8pt !important; padding-bottom: 2pt !important;
  }}
  .letter-mark {{
    font-family: 'Fraunces', Georgia, serif; font-variation-settings: 'opsz' 144;
    font-style: italic; font-weight: 700;
    font-size: 16pt; color: #8a6d2e;
    display: inline-block; padding: 1pt 0;
  }}
  /* Page break between sections */
  .lot-detail-divider {{
    page-break-before: always;
    border-top: 2pt solid #c9a44a; padding-top: 14pt; margin-top: 18pt;
  }}
  .section-title {{
    font-family: 'Fraunces', Georgia, serif; font-variation-settings: 'opsz' 144;
    font-style: italic; font-weight: 600; font-size: 18pt; color: #1a1814;
    margin: 0 0 4pt 0;
  }}
  .section-title em {{ color: #8a6d2e; font-style: italic; }}
  .section-sub {{ color: #4a4438; font-size: 9.5pt; margin: 0 0 8pt 0; }}
</style>
</head>
<body>
<div class="wrap">

<header class="cover">
  <div class="eyebrow">harpua2001 &middot; Lot Picking List</div>
  <h1>Walk the binders, <em>check the boxes</em>.</h1>
  <p class="deck">Printable picking list for the AI lot generator's current proposals. Every card below is in CollX and is not yet on eBay. Pull each one, check the box, then hand the marked-up list back to me and I'll list each lot.</p>
</header>

<div class="stat-strip">
  <div class="stat"><div class="n">{len(lots)}</div><div class="l">Lots to pull</div></div>
  <div class="stat"><div class="n">{total_cards}</div><div class="l">Cards to find</div></div>
  <div class="stat"><div class="n">${total_value:.0f}</div><div class="l">Combined lot value</div></div>
  <div class="stat"><div class="n">~{(total_cards/max(len(lots),1)):.0f}</div><div class="l">Avg cards per lot</div></div>
</div>

<div class="tldr">
<p><b>How to use this list.</b> Section 1 is the <b>per-lot detail with thumbnails</b> — read through to see what each lot is and what's in it. Sorted by card count ascending so the smallest lots come first. Section 2 (after the divider) is a <b>text-only A-Z checklist</b> — print it, walk your binder front-to-back, tick each card as you find it. If a card is missing, scratch its box and we'll pull it from the lot.</p>
</div>

<h2 class="section-title">Section 1 &mdash; <em>Per-lot detail</em></h2>
<p class="section-sub">Sorted by card count ascending. Start with the 3-card lots and build momentum.</p>

{lots_html}

<div class="lot-detail-divider"></div>
<h2 class="section-title">Section 2 &mdash; <em>A-Z walk-the-binder checklist</em></h2>
<p class="section-sub">{total_cards} cards, text only. Pull every card you find, sort into lots using Section 1 above.</p>

{az_html}

<div class="footnote">
Generated {today} from <code>output/lot_generator_plan.json</code> &middot; Refresh with: <code>python3 lot_generator_agent.py &amp;&amp; python3 build_lot_picking_list.py</code>
</div>

</div>
</body>
</html>"""


def main() -> int:
    if not PLAN_PATH.exists():
        raise SystemExit(f"No plan at {PLAN_PATH}. Run: python3 lot_generator_agent.py")
    plan = json.loads(PLAN_PATH.read_text())
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
            "--virtual-time-budget=20000",
            f"--print-to-pdf={PDF_OUT}",
            f"file://{HTML_OUT.resolve()}",
        ],
        capture_output=True, text=True, timeout=120,
    )
    if proc.returncode != 0 or not PDF_OUT.is_file():
        print("Chrome stderr:", proc.stderr[:400])
        raise SystemExit("PDF generation failed")
    size_kb = PDF_OUT.stat().st_size // 1024
    print(f"Wrote {PDF_OUT} ({size_kb} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
