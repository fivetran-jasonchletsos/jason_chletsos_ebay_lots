"""build_pdf_library.py — one page linking every pull sheet / lot plan / pricing
PDF the store has ever produced, grouped by category, so nothing sits orphaned
in docs/ only reachable by typing the exact filename.

Usage:
    python3 build_pdf_library.py
"""
from __future__ import annotations

import promote

DOCS_DIR = promote.OUTPUT_DIR  # canonical docs/ path, shared with the site build
HTML_PATH = DOCS_DIR / "pdf_library.html"

# PDFs that live in docs/ but are deliberately NOT in the library
# (they have their own nav entry or aren't worksheet-style documents).
KNOWN_UNLISTED = {"harpua_ai_overview.pdf"}

# Admin-only PDFs (JC decision 2026-07-25: split the library). These carry the
# seller's own low/typ/high price floors, Best-Offer floors, keeper piles, or
# internal strategy — public linking would let buyers anchor Best Offers at
# our own "low" estimates (2,000+ listings have auto-accept). Their cards are
# wrapped in data-admin="1" so only a logged-in admin sees them; checklists,
# sort lists, and plain pull sheets stay public.
GATED = {
    "baseball_batch_pricing.pdf",     # low/typ/high per card
    "basketball_keep.pdf",            # internal keeper pile
    "numbered_review.pdf",            # value estimates + review flags
    "pull_sheet_batch250.pdf",        # includes Best-Offer floor prices
    "scan493_507_candidates.pdf",     # low/typ/high per card
    "pull_list_valuation.pdf",        # low/typ/high per card
    "relics_pricing.pdf",             # low/typ/high per card
    "marvel_valuation.pdf",           # raw value estimates
    "sales_plan_june14.pdf",          # internal pricing strategy
    "session_report.pdf",             # internal ops recap
}

# (filename, title, description, updated)
GROUPS: list[tuple[str, list[tuple[str, str, str, str]]]] = [
    ("Baseball", [
        ("baseball_posting_plan.pdf",
         "Baseball posting plan",
         "3 individual autos + 34 alphabetical team lots (5 cards or fewer) + 1 team-insert lot, matching JC's physical A-Z sort.",
         "2026-07-21"),
        ("baseball_batch_pricing.pdf",
         "Baseball batch pricing worksheet",
         "Scans 391-409, 168 cards priced low/typical/high before deciding singles vs. lots.",
         "2026-07-21"),
        ("baseball_batch2_sort.pdf",
         "Baseball batch 2 sort",
         "Scans 476-486, 98 cards sorted into individuals vs. lots.",
         "2026-07-22"),
        ("baseball_batch2_lots.pdf",
         "Baseball batch 2 — lots only",
         "Pull sheet for the batch-2 team lots (singles already posted separately).",
         "2026-07-23"),
    ]),
    ("Basketball", [
        ("basketball_keep.pdf",
         "Basketball — keep",
         "Keeper pile: Knicks, 76ers, LeBron, Giannis, and other notables held back from selling.",
         "2026-07-22"),
        ("basketball_sell.pdf",
         "Basketball — sell / lots by team",
         "~135 cards sorted into sell singles vs. team lots.",
         "2026-07-22"),
        ("basketball_posted_lots.pdf",
         "Basketball posted lots",
         "7 more basketball lots posted live (Nuggets-Rockets mix, 25 cards).",
         "2026-07-22"),
    ]),
    ("Football pull sheets", [
        ("chrome_pull_all.pdf",
         "Topps Chrome pull sheet (35 cards)",
         "Every Chrome card grouped by value tier with a POSTED flag; numbered hits and inserts called out.",
         "2026-07-10"),
        ("chrome_pull_314_316.pdf",
         "Chrome scan 316 pull sheet (26 cards)",
         "Breece Hall Green /99 confirmed among the hits.",
         "2026-07-10"),
        ("prizm_4plus_pull.pdf",
         "Prizm $4+ pull sheet (17 cards)",
         "The high-value Prizm posted — Lazer parallels, a jersey relic, Prizmatic/Emergent/White Sparkle.",
         "2026-07-09"),
        ("prizm_pull_268_306.pdf",
         "Prizm pull sheet, scans 268-306",
         "254 unique cards to pull, alphabetical by last name; base vs. colored parallels flagged.",
         "2026-07-08"),
        ("prizm_pull_simple.pdf",
         "Prizm pull list (simple)",
         "Clean one-line-per-card print-friendly version of the 268-306 pull sheet.",
         "2026-07-08"),
        ("mosaic_pull_307_311.pdf",
         "Mosaic pull sheet, scans 307-311",
         "41 unique cards to pull, alphabetical, with team and scan position.",
         "2026-07-08"),
        ("mosaic_review.pdf",
         "Mosaic batch review, scans 265-267",
         "17 new to post + 4 already listed, grouped Green / Inserts / Base.",
         "2026-07-07"),
        ("numbered_review.pdf",
         "Numbered cards review",
         "40 serial-numbered cards, rarest-first, with review flags.",
         "2026-06-27"),
        ("pull_sheet_batch250.pdf",
         "Scans 252-261 plan (~90 cards)",
         "32 singles + 14 lots (4 cards max) with images and Best-Offer prices.",
         "2026-07-06"),
        ("pull_sheet.pdf",
         "Pull sheet — 9 leftover cards",
         "4 singles + a 5-card Prizm Draft Rookies lot from scans 250/251.",
         "2026-07-05"),
        ("batch241_plan.pdf",
         "Batch 241 full plan",
         "Every single and lot in scans 221-249, with card images.",
         "2026-07-05"),
    ]),
    ("Pricing & valuation", [
        ("scan493_507_candidates.pdf",
         "Scans 493-507 — individual-posting candidates",
         "33 cards pulled from a 15-scan batch as worth listing individually (Ohtani x2, Acuna Jr, Skenes x2, Betts, Freeman, Posey, Mayer x3, and more) — HOLD, pull and confirm before posting.",
         "2026-07-25"),
        ("pull_list_valuation.pdf",
         "Pull list valuation",
         "Priced pull list with checkboxes for physically pulling + confirming each card.",
         "2026-07-24"),
        ("relics_pricing.pdf",
         "Relics & parallels pricing",
         "Low/typical/high pricing worksheet for relics and named parallels, grouped by set.",
         "2026-07-24"),
        ("marvel_valuation.pdf",
         "Marvel Chrome valuation",
         "63 Marvel Chrome cards, raw price estimate — not for sale, reference only.",
         "2026-07-13"),
    ]),
    ("Older reference sheets", [
        ("pull_list_3_june2026.pdf", "Pull list 3 (June 2026)", "Earlier pull sheet, kept for reference.", "2026-06-18"),
        ("pull_list_june14.pdf", "Pull list (June 14)", "Earlier pull sheet, kept for reference.", "2026-06-18"),
        ("sales_plan_june14.pdf", "Sales plan (June 14)", "Earlier sales/posting plan, kept for reference.", "2026-06-18"),
        ("cassini_guide.pdf", "Cassini score guide", "How the Cassini listing-quality score is calculated and what fixes it.", "2026-06-18"),
        ("session_report.pdf", "Session report", "Recap of a working session: lot fixes, cards pulled as singles, open items.", "2026-07-05"),
    ]),
    ("Auction HQ checklists", [
        ("auction_checklist_before.pdf", "Auction checklist — before", "Setup checklist for a live-auction session, before going live.", "2026-07-13"),
        ("auction_checklist_during.pdf", "Auction checklist — during", "Running checklist for during a live-auction session.", "2026-07-13"),
        ("auction_checklist_after.pdf", "Auction checklist — after", "Wrap-up checklist for after a live-auction session.", "2026-07-13"),
    ]),
]

_CSS = """
.pdf-wrap { max-width: 760px; margin: 0 auto; padding: 24px 20px 60px; }
.pdf-wrap h1 { font-size: 24px; margin: 8px 0 2px; }
.pdf-wrap .sub { color: var(--muted, #8a94a6); font-size: 14px; margin: 0 0 28px; }
.pdf-group { margin-bottom: 34px; }
.pdf-group h2 { font-size: 15px; letter-spacing: .04em; text-transform: uppercase;
                color: var(--accent, #d4af37); margin: 0 0 12px; border-bottom: 1px solid rgba(128,128,128,.25); padding-bottom: 8px; }
a.pdf-card { display: block; background: var(--card-bg, rgba(128,128,128,.06)); border: 1px solid rgba(128,128,128,.2);
             border-radius: 12px; padding: 14px 18px; margin: 10px 0; text-decoration: none; color: inherit; }
a.pdf-card:hover { background: rgba(212,175,55,.08); border-color: rgba(212,175,55,.4); }
a.pdf-card .pdf-title { font-weight: 600; font-size: 15px; margin: 0 0 4px; }
a.pdf-card .pdf-desc { font-size: 13px; color: var(--muted, #8a94a6); line-height: 1.45; margin: 0 0 6px; }
a.pdf-card .pdf-date { font-size: 11px; color: var(--muted, #8a94a6); opacity: .7; }
"""


def build_body() -> str:
    total = sum(len(items) for _, items in GROUPS)
    n_gated = sum(1 for _g, items in GROUPS for (f, _t, _d, _u) in items if f in GATED)
    n_public = total - n_gated
    parts = [
        '<div class="pdf-wrap">',
        "<h1>PDF Library</h1>",
        f'<p class="sub">{n_public} pull sheets, sort lists &amp; checklists'
        f'<span data-admin="1"> &middot; plus {n_gated} internal pricing worksheets (admin)</span>.</p>',
    ]
    for group_name, items in GROUPS:
        # Hide the whole group (header included) from anonymous visitors when
        # every PDF in it is admin-only; otherwise gate card-by-card.
        group_gated = all(f in GATED for (f, _t, _d, _u) in items)
        grp_attr = ' data-admin="1"' if group_gated else ""
        parts.append(f'<div class="pdf-group"{grp_attr}>')
        parts.append(f"<h2>{group_name}</h2>")
        for fname, title, desc, updated in items:
            card_attr = ' data-admin="1"' if (fname in GATED and not group_gated) else ""
            parts.append(
                f'<a class="pdf-card" href="{fname}"{card_attr}>'
                f'<div class="pdf-title">{title}</div>'
                f'<div class="pdf-desc">{desc}</div>'
                f'<div class="pdf-date">Updated {updated}</div>'
                f"</a>"
            )
        parts.append("</div>")
    parts.append("</div>")
    return "\n".join(parts)


def check_orphans() -> None:
    """Warn (never fail — this runs inside the site build) when docs/ holds a
    PDF that isn't registered in GROUPS, so the library's 'every PDF the store
    has ever produced' promise stays self-enforcing instead of hand-enforced."""
    listed = {fname for _g, items in GROUPS for (fname, _t, _d, _u) in items}
    on_disk = {p.name for p in DOCS_DIR.glob("*.pdf")}
    orphans = sorted(on_disk - listed - KNOWN_UNLISTED)
    for name in orphans:
        print(f"  WARNING: docs/{name} is not listed in the PDF Library — "
              f"add it to GROUPS in build_pdf_library.py")
    missing = sorted(listed - on_disk)
    for name in missing:
        print(f"  WARNING: PDF Library links docs/{name}, which does not exist")


def main() -> int:
    body = build_body()
    page = promote.html_shell(
        "PDF Library · Harpua2001",
        body,
        extra_head=f"<style>{_CSS}</style>",
        active_page="pdf_library.html",
    )
    with open(HTML_PATH, "w", encoding="utf-8") as fh:
        fh.write(page)
    print(f"  Wrote {HTML_PATH}")
    check_orphans()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
