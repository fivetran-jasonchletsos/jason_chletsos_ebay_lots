"""Mike (mikeboy-40) eBay store review -- 5-expert-agent findings synthesized
into a printable report, corrected against source data before printing.
Output -> output/mike_store_review.pdf, copied to ~/Downloads."""
import shutil
from pathlib import Path
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_LEFT
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Table,
                                 TableStyle, HRFlowable)

OUT = Path("output/mike_store_review.pdf")
NAVY = colors.HexColor("#0b1b3a")
ACCENT = colors.HexColor("#0076B6")
GREY = colors.HexColor("#556")
LIGHT = colors.HexColor("#f2f4f8")

styles = getSampleStyleSheet()
H1 = ParagraphStyle("H1", parent=styles["Heading1"], textColor=NAVY, fontSize=20, spaceAfter=4)
H2 = ParagraphStyle("H2", parent=styles["Heading2"], textColor=NAVY, fontSize=14,
                     spaceBefore=16, spaceAfter=6, borderPadding=0)
SUB = ParagraphStyle("Sub", parent=styles["Normal"], textColor=GREY, fontSize=10, spaceAfter=10)
BODY = ParagraphStyle("Body", parent=styles["Normal"], fontSize=10.3, leading=15,
                       spaceAfter=8, alignment=TA_LEFT)
BULLET = ParagraphStyle("Bullet", parent=BODY, leftIndent=14, bulletIndent=2, spaceAfter=6)
CAPTION = ParagraphStyle("Caption", parent=styles["Normal"], fontSize=8.3, textColor=GREY,
                          leading=11, spaceAfter=4)
STAT_LABEL = ParagraphStyle("StatLabel", parent=styles["Normal"], fontSize=8.5, textColor=GREY)
STAT_VALUE = ParagraphStyle("StatValue", parent=styles["Normal"], fontSize=16, textColor=NAVY,
                             fontName="Helvetica-Bold")


def stat_block(pairs):
    cells = []
    for label, value in pairs:
        cells.append([Paragraph(value, STAT_VALUE), Paragraph(label, STAT_LABEL)])
    row = [c for pair in cells for c in [pair]]
    t = Table([[Table([[c[0]], [c[1]]], colWidths=[1.55 * inch]) for c in row]],
               colWidths=[1.6 * inch] * len(row))
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

    story.append(Paragraph("mikeboy-40 -- eBay Store Review", H1))
    story.append(Paragraph(
        "Prepared by Jason using a 5-agent review of live account data "
        "(GetMyeBaySelling, GetAccount, GetItemTransactions) &mdash; account opened "
        "2026-06-25, about 5.5 weeks old as of this review.", SUB))
    story.append(HRFlowable(width="100%", color=colors.HexColor("#dde"), thickness=1))
    story.append(Spacer(1, 10))

    story.append(Paragraph("At a glance", H2))
    story.append(stat_block([
        ("71 active listings", "$524.47 total value"),
        ("10 sales / 60 days", "$202.08 revenue"),
        ("$34.70 fees paid", "17.2% effective rate"),
        ("$4.90 ad spend", "3/3 promoted items sold"),
    ]))
    story.append(Spacer(1, 8))
    story.append(Paragraph(
        "Overall: a healthy first five weeks. Sales are real and fees are being paid "
        "on schedule -- this is a working store, not a stalled one. The biggest "
        "opportunity is inventory mix, not anything broken.", BODY))

    story.append(Paragraph("Sales performance", H2))
    story.append(Paragraph(
        "10 sales in 60 days totaling $202.08 (avg sale $20.21) against 71 active "
        "listings averaging $7.39 -- sales are skewing well above the typical listing "
        "price, which is a good sign for pricing and photo quality.", BODY))
    story.append(Paragraph(
        "Revenue is top-heavy: 3 sales (James Cook Signature Class auto /5 at $99, "
        "Donruss Optic Jackson Hawes at $30, Max Crosby Signature Class at $16.99) "
        "account for 72% of the 60-day total. That's not a problem by itself -- "
        "low-serial autos and inserts are supposed to carry the average -- but it "
        "means the other 7 sales (mostly $2.59-$12.08) are closer to break-even once "
        "fees and shipping labels ($5.11 total) are counted. The store's health "
        "depends more on landing a few more cards like the Cook auto than on moving "
        "volume in the $2-5 bin.", BODY))

    story.append(Paragraph("Promoted Listings", H2))
    story.append(Paragraph(
        "$4.90 spent across 3 promoted items (Max Crosby $1.95, Bears rookie lot "
        "$0.26, Donruss Optic Hawes $2.69) -- all 3 sold, combining for $58.99, an "
        "8.3% ad-cost-to-revenue ratio. That's inside (better than) the 10-15% "
        "range generally considered healthy for Promoted Listings, so the money "
        "being spent is working efficiently. The sample is small (3 items), so it's "
        "not certain the ad spend caused these sales rather than just coinciding "
        "with cards that would have sold anyway -- but there's no downside signal "
        "here. Only 3 of 71 listings are promoted at all; a reasonable next step is "
        "adding promotion to 8-10 more of the higher-priced or most distinctive "
        "zero-watcher listings (see Inventory Health) rather than promoting "
        "everything at once.", BODY))

    story.append(Paragraph("Fees and margins", H2))
    story.append(Paragraph(
        "$34.70 in total fees against $202.08 revenue is a 17.2% effective take "
        "rate. Final Value Fee runs a flat $0.40 per order plus a percentage of "
        "item price + shipping -- that flat component falls hardest on the sub-$5 "
        "sales, where it can eat 8-15% of the sale on its own before the percentage "
        "fee is even applied. Worth a 5-minute check in Seller Hub: whether an eBay "
        "Store subscription is active, since Store tiers typically lower the "
        "per-category FVF percentage and that gap would close on its own with "
        "volume. Practical fix either way: bundling the sub-$5 singles into 3-5 "
        "card lots (see Inventory Health) means one flat fee shared across several "
        "cards instead of paid per card.", BODY))
    story.append(Paragraph(
        "One housekeeping item, not urgent: the account payout method reads "
        "&ldquo;NothingOnFile&rdquo; in the legacy API field, but FeeNettingStatus is "
        "Enabled and there's no past-due balance ($0.00, PastDue: false) -- fees are "
        "netting normally against payouts. Worth a quick glance in Seller Hub to "
        "confirm the payout bank account shows verified, but nothing indicates a "
        "problem today.", CAPTION))

    story.append(Paragraph("Inventory health", H2))
    story.extend(bullets([
        "Price mix: ~40% of the 71 listings sit under $5, another third in the "
        "$5-10 band, and only 7 crest $15 (top two are $24.50 and $24.26 lots). "
        "There's very little above $25 to anchor the average the way the Cook "
        "auto did in sales.",
        "2025 Topps Resurgence is over-represented and under-performing: 27 of 71 "
        "listings (38%) are Resurgence parallels of mid-tier rookies (Nabers, "
        "Milroe, Graham, Penix), but only 4 of those 27 carry a watcher, against "
        "34% engagement account-wide. It's a lower-recognition product line and "
        "it's the majority of the dead weight.",
        "By contrast, the Panini Select/Prizm/Donruss Optic football singles "
        "watcher at a noticeably higher rate -- worth noting that roughly 10 of "
        "those are cards Jason transferred over as a starter batch, not cards "
        "Mike sourced independently. The lesson (source more $8-11 Select/Prizm-"
        "caliber singles) is proven, but replicating it means finding more "
        "inventory at that tier, not just reordering more Resurgence.",
        "One live duplicate: &ldquo;2026 Topps Chrome Denzer Guzman Rookie Red White "
        "And Blue Refractor&rdquo; is listed twice, at $7.49 and $1.50 -- these are "
        "competing with each other in search. End the $1.50 copy.",
        "Title quality is mixed. Strong titles front-load year/brand/set/player/"
        "serial (the Gavin Stone auto listing is a good template). Weaker ones use "
        "all-lowercase, emoji, or all-caps player names, and at least one omits "
        "year/brand/set entirely (a $1.00 listing titled just &ldquo;sports trading "
        "card singles- Patrick Mahomes&rdquo;) -- that one is losing all its search "
        "traffic to missing keywords.",
    ]))

    story.append(Paragraph("Recommendations, in order", H2))
    story.extend(bullets([
        "Bundle the sub-$5 Resurgence singles into 3-5 card lots -- cuts the "
        "per-card flat-fee drag and clears the zero-watcher pile faster than "
        "individual sales will.",
        "End the duplicate Denzer Guzman listing and clean up the handful of "
        "all-caps / emoji / missing-keyword titles.",
        "Expand Promoted Listings from 3 to roughly 10 items, prioritizing the "
        "highest-priced zero-watcher listings first -- the current 8.3% ad-cost "
        "ratio has room to scale before it stops being efficient.",
        "Keep sourcing $8-11 Select/Prizm/Donruss singles in the style of the "
        "starter batch -- that tier is watchering and selling well above the "
        "Resurgence product.",
        "Quick Seller Hub check on Store subscription status and payout account "
        "verification -- neither is a fire, both are worth 5 minutes.",
    ]))

    story.append(Spacer(1, 14))
    story.append(HRFlowable(width="100%", color=colors.HexColor("#dde"), thickness=1))
    story.append(Paragraph(
        "Five weeks in, this is a store that's selling, paying its fees on time, "
        "and getting real engagement on the right kind of card. The path from here "
        "is mix, not repair.", CAPTION))

    doc.build(story)
    print(f"wrote {OUT}")
    dl = Path.home() / "Downloads" / "mike_store_review.pdf"
    shutil.copy(OUT, dl)
    print(f"copied to {dl}")


if __name__ == "__main__":
    build()
