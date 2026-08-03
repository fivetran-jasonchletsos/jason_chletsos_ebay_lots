"""Daily-routine revamp report -- 5-agent review synthesis, every fix applied
2026-08-03, real test results, and the full-pipeline smoke test outcome.
Output -> output/daily_routine_revamp.pdf, copied to ~/Downloads."""
import shutil
from pathlib import Path
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_LEFT
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Table,
                                 TableStyle, HRFlowable)

OUT = Path("output/daily_routine_revamp.pdf")
NAVY = colors.HexColor("#0b1b3a")
GREY = colors.HexColor("#556")
LIGHT = colors.HexColor("#f2f4f8")
GOOD = colors.HexColor("#2f8f5b")
BAD = colors.HexColor("#b5473a")

styles = getSampleStyleSheet()
H1 = ParagraphStyle("H1", parent=styles["Heading1"], textColor=NAVY, fontSize=20, spaceAfter=4)
H2 = ParagraphStyle("H2", parent=styles["Heading2"], textColor=NAVY, fontSize=14,
                     spaceBefore=16, spaceAfter=6)
H3 = ParagraphStyle("H3", parent=styles["Heading3"], textColor=NAVY, fontSize=11.5,
                     spaceBefore=10, spaceAfter=4)
SUB = ParagraphStyle("Sub", parent=styles["Normal"], textColor=GREY, fontSize=10, spaceAfter=10)
BODY = ParagraphStyle("Body", parent=styles["Normal"], fontSize=10.2, leading=14.5,
                       spaceAfter=7, alignment=TA_LEFT)
BULLET = ParagraphStyle("Bullet", parent=BODY, leftIndent=14, bulletIndent=2, spaceAfter=5)
CAPTION = ParagraphStyle("Caption", parent=styles["Normal"], fontSize=8.3, textColor=GREY,
                          leading=11, spaceAfter=4)
STAT_LABEL = ParagraphStyle("StatLabel", parent=styles["Normal"], fontSize=8.5, textColor=GREY)
STAT_VALUE = ParagraphStyle("StatValue", parent=styles["Normal"], fontSize=15, textColor=NAVY,
                             fontName="Helvetica-Bold")


def stat_block(pairs):
    cells = [[Paragraph(v, STAT_VALUE), Paragraph(l, STAT_LABEL)] for l, v in pairs]
    t = Table([[Table([[c[0]], [c[1]]], colWidths=[1.55 * inch]) for c in cells]],
               colWidths=[1.6 * inch] * len(cells))
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BACKGROUND", (0, 0), (-1, -1), LIGHT),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#dde")),
        ("TOPPADDING", (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
    ]))
    return t


def bullets(items):
    return [Paragraph(f"&bull;&nbsp;&nbsp;{i}", BULLET) for i in items]


def build():
    doc = SimpleDocTemplate(str(OUT), pagesize=letter,
                             topMargin=0.6 * inch, bottomMargin=0.6 * inch,
                             leftMargin=0.65 * inch, rightMargin=0.65 * inch)
    story = []

    story.append(Paragraph("Harpua2001 Daily Routine -- Revamp Report", H1))
    story.append(Paragraph(
        "5-agent review of the daily automation pipeline, every fix applied and "
        "tested tonight, and the full-pipeline smoke-test result. Compiled 2026-08-03.",
        SUB))
    story.append(HRFlowable(width="100%", color=colors.HexColor("#dde"), thickness=1))
    story.append(Spacer(1, 10))

    story.append(Paragraph("At a glance", H2))
    story.append(stat_block([
        ("4 fixes shipped", "sold_reconciler, sell_inventory_reprice, shipping_audit, listing_performance"),
        ("1025 listings", "audited for shipping cost"),
        ("3 mismatches", "found, 2 fixed live"),
        ("25/26 clean", "full pipeline smoke test"),
    ]))
    story.append(Spacer(1, 8))
    story.append(Paragraph(
        "Five specialist agents reviewed the daily pipeline end to end. Four concrete "
        "fixes shipped tonight, each tested against live data rather than just read "
        "and trusted. One real financial gap was caught (3 more shipping-undercharged "
        "listings, 2 already corrected) and one stale, silently-failing step was found "
        "and removed.", BODY))

    story.append(Paragraph("1. The 5-agent review -- what each lens found", H2))
    story.append(Paragraph(
        "Five independent specialists (ops/sequencing, card-selling strategy, "
        "marketing/customer-ops, promotions/pricing, risk/data-integrity) reviewed the "
        "same pipeline blind to each other's conclusions. Three of five independently "
        "flagged the same gap -- strong signal it was real.", BODY))
    story.extend(bullets([
        "<b>Consensus finding (3/5 agents):</b> CollX has no inbound API, so a card "
        "sold on eBay never tells CollX it sold -- <b>sold_reconciler_agent.py</b> "
        "existed but never ran automatically. This is upstream of the oversell-guard "
        "cleanup work, not a duplicate of it.",
        "<b>Biggest structural gap (pricing lens):</b> repricing_agent.py can't touch "
        "listings posted via the Sell Inventory API (CollX imports) -- only "
        "sell_inventory_reprice.py can. It existed but was never previewed in the "
        "daily dry-run, so the digest's repricing section was blind to part of the "
        "catalog every single day.",
        "<b>Zero-detection risk (risk lens):</b> the 79-listing shipping-undercharge "
        "incident from 2026-08-02 had, and until tonight still had, no automated daily "
        "check of its own class of bug.",
        "<b>Fixed vs. flagged-not-ready:</b> pnl_agent.py and listing_performance_agent.py "
        "were both documented as broken and skipped daily -- worth fixing since they're "
        "the only real margin/search-rank visibility in the system. Separately, "
        "lot_generator_agent.py (the flagship AI Lot Generator) was found to cap lots "
        "at 25 cards in code, violating the standing 5-card rule -- flagged, not "
        "touched tonight.",
        "<b>Not yet actioned</b> (lower priority, no code changed): specifics_agent.py "
        "and feedback_agent.py additions, message_responder_agent.py / "
        "tracking_responder_agent.py for buyer-message visibility, a weekly "
        "email_campaign_agent.py dry-run, promotions_agent.py addition, and resolving "
        "a possible price_drops_agent vs. repricing_agent conflict on the same SKU. "
        "These are queued for a future pass.",
    ]))

    story.append(Paragraph("2. Fixes shipped tonight, with real test results", H2))

    story.append(Paragraph("sold_reconciler_agent.py -- added, pre-authorized", H3))
    story.append(Paragraph(
        "Added to Step 0a, right after the oversell guard. Confirmed safe to "
        "auto-apply by reading the code and running it live: <b>--apply only writes "
        "to the local state/linkage.db sqlite file</b> -- there is no eBay/marketplace "
        "write in either dry-run or --apply mode; both make the identical live "
        "GetMyeBaySelling read. Real run: 80 sold listings in a 30-day window, 1 "
        "matched to CollX linkage, 79 eBay-only/unlinked, no errors.", BODY))

    story.append(Paragraph("sell_inventory_reprice.py -- added to Step 1 dry-run", H3))
    story.append(Paragraph(
        "Added right after repricing_agent.py, since it depends on that run's output. "
        "A same-day test refined the original claim: repricing_agent's fresh dry-run "
        "produced 72 apply-targets, but only <b>9 (12.5%)</b> were actual CollX/"
        "Inventory-API SKUs needing this fallback -- the other 63 were ordinary "
        "Trading listings repricing_agent could already reach directly. The 97%-of-"
        "catalog figure describes overall catalog composition (how many listings were "
        "posted via the newer API path), not what share of any single day's repricing "
        "targets needs the fallback -- both numbers are now documented so the daily "
        "summary doesn't overstate the gap.", BODY))

    story.append(Paragraph("listing_performance_agent.py -- fixed", H3))
    story.append(Paragraph(
        "The skill doc blamed a schema-drift crash. On inspection, that guard had "
        "already been patched separately at some point -- the real, still-live bug "
        "was a Sell Analytics API date-range error: requesting a window ending "
        "\"today\" gets rejected as \"end date in the future\" because Analytics data "
        "lags live eBay by about a day. Fixed by ending the window at yesterday. "
        "Verified with a real run: 85,661 impressions / 718 clicks / 200 listings "
        "analyzed, no errors.", BODY))

    story.append(Paragraph("pnl_agent.py -- confirmed working, no fix needed", H3))
    story.append(Paragraph(
        "Tested directly rather than trusting the skill doc's \"broken\" label -- it "
        "ran clean on the first try, correctly surfacing negative-margin listings "
        "(several Icon Collection Mahomes cards losing $10-12 each after fees). "
        "Whatever schema-drift issue existed previously no longer reproduces.", BODY))

    story.append(Paragraph("shipping_audit_agent.py -- new agent, built and run live", H3))
    story.append(Paragraph(
        "New report-only SRE-style gate: live Trading API GetItem per active listing "
        "(the snapshot doesn't carry shipping fields), cached 7 days so only new/stale "
        "listings get re-checked daily. First cold run against all 1,025 active "
        "listings took 18.9 minutes with an empty cache; subsequent daily runs will "
        "be fast. <b>Found 3 real mismatches</b> -- the original 79-listing fix from "
        "2026-08-02 wasn't fully complete:", BODY))
    story.extend(bullets([
        "Frank Thomas Heavy Lumber Bat Relic Auto ($152.50) -- USPSPriority @ $0.00 "
        "(should be US_eBayStandardEnvelope @ $1.32). <b>Not fixed</b> -- ReviseItem "
        "rejected it for an unclear reason; ruled out Best Offer, an active bid, and "
        "ending-within-12-hours via follow-up GetItem/GetBestOffers checks. Needs a "
        "manual fix in Seller Hub.",
        "Maxx Crosby Signature Class Round 4 Pick 4 ($14.99) -- was USPSFirstClass "
        "@ $0.99. <b>Fixed</b> via ReviseItem, confirmed live at $1.32/standard envelope.",
        "Javonte Williams Select Concourse ($4.49) -- was USPSFirstClass @ $0.99. "
        "<b>Fixed</b> via ReviseItem, confirmed live.",
    ]))

    story.append(Paragraph("Bonus catch: a stale, silently-failing pipeline step", H3))
    story.append(Paragraph(
        "The full pipeline smoke test (below) surfaced one failure: vault_eligibility.py. "
        "Root cause wasn't a regression from tonight's changes -- the script was "
        "<b>deleted from the repo on 2026-05-28</b> (\"Nav cleanup: drop Vault + "
        "Whatnot\") but never removed from the daily skill's agent list. This step has "
        "been failing every single day for over two months without anyone noticing, "
        "since a single agent failure doesn't stop the rest of the pipeline. Removed "
        "from the skill.", BODY))

    story.append(Paragraph("3. Full-pipeline smoke test", H2))
    story.append(Paragraph(
        "Ran all 26 Step 1 agents end to end, in the exact revised order, to catch any "
        "breakage from reordering rather than testing each agent in isolation. "
        "<b>25 of 26 ran clean</b> on the first pass, including the two new sequencing "
        "dependencies (shipping_audit_agent.py running early with a warm cache, "
        "sell_inventory_reprice.py correctly consuming repricing_agent.py's "
        "just-written plan). The one failure (vault_eligibility.py, above) was "
        "diagnosed, fixed by removing the stale reference, and the pipeline is now "
        "clean end to end.", BODY))

    story.append(Paragraph("4. Current state / what's still open", H2))
    story.extend(bullets([
        "<b>Needs your action:</b> the Frank Thomas $152.50 bat relic auto still has "
        "wrong shipping (USPSPriority @ $0.00) -- fix it directly in Seller Hub, since "
        "the automated ReviseItem path rejected it for a reason that wasn't Best "
        "Offer, a bid, or an ending-soon lock.",
        "<b>Daily pipeline is ready to run</b> with tonight's four additions/fixes "
        "plus the vault_eligibility.py removal -- no further setup needed.",
        "<b>Queued for later, not done tonight:</b> specifics_agent.py / "
        "feedback_agent.py additions, message_responder_agent.py / "
        "tracking_responder_agent.py for buyer-message visibility, a weekly "
        "email_campaign_agent.py preview, promotions_agent.py addition, resolving the "
        "price_drops_agent/repricing_agent overlap, and fixing the 5-card cap bug in "
        "lot_generator_agent.py before it's ever added to the daily routine.",
    ]))

    story.append(Spacer(1, 14))
    story.append(HRFlowable(width="100%", color=colors.HexColor("#dde"), thickness=1))
    story.append(Paragraph(
        "Everything above was tested against live data, not just read and assumed -- "
        "every fix has a real run's output behind it, and the smoke test caught a "
        "two-month-old silent failure the original skill doc never mentioned.",
        CAPTION))

    doc.build(story)
    print(f"wrote {OUT}")
    dl = Path.home() / "Downloads" / "daily_routine_revamp.pdf"
    shutil.copy(OUT, dl)
    print(f"copied to {dl}")


if __name__ == "__main__":
    build()
