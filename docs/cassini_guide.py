"""Generate a printable grayscale PDF explaining Cassini as it relates to JC2 Cards."""
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
)
from reportlab.lib.enums import TA_LEFT, TA_CENTER

OUT = "docs/cassini_guide.pdf"

doc = SimpleDocTemplate(
    OUT,
    pagesize=letter,
    leftMargin=0.85*inch,
    rightMargin=0.85*inch,
    topMargin=0.85*inch,
    bottomMargin=0.85*inch,
)

BLACK  = colors.black
DGRAY  = colors.HexColor("#222222")
MGRAY  = colors.HexColor("#555555")
LGRAY  = colors.HexColor("#cccccc")
WHITE  = colors.white

styles = getSampleStyleSheet()

H1 = ParagraphStyle("H1", parent=styles["Normal"],
    fontSize=18, leading=22, textColor=BLACK,
    spaceAfter=4, fontName="Helvetica-Bold")

H2 = ParagraphStyle("H2", parent=styles["Normal"],
    fontSize=12, leading=15, textColor=BLACK,
    spaceBefore=14, spaceAfter=4, fontName="Helvetica-Bold")

BODY = ParagraphStyle("BODY", parent=styles["Normal"],
    fontSize=9.5, leading=14, textColor=DGRAY,
    spaceAfter=6, fontName="Helvetica")

BULLET = ParagraphStyle("BULLET", parent=BODY,
    leftIndent=16, firstLineIndent=-10,
    spaceAfter=3)

SMALL = ParagraphStyle("SMALL", parent=BODY,
    fontSize=8, textColor=MGRAY, spaceAfter=4)

CAPTION = ParagraphStyle("CAPTION", parent=BODY,
    fontSize=8, textColor=MGRAY, alignment=TA_CENTER)

def rule():
    return HRFlowable(width="100%", thickness=0.5, color=LGRAY, spaceAfter=8)

def h1(txt): return Paragraph(txt, H1)
def h2(txt): return Paragraph(txt, H2)
def body(txt): return Paragraph(txt, BODY)
def bullet(txt): return Paragraph(f"•  {txt}", BULLET)
def small(txt): return Paragraph(txt, SMALL)
def sp(n=6): return Spacer(1, n)

def table(data, col_widths, header=True):
    t = Table(data, colWidths=col_widths)
    style = [
        ("FONTNAME",    (0,0), (-1,-1), "Helvetica"),
        ("FONTSIZE",    (0,0), (-1,-1), 8.5),
        ("TEXTCOLOR",   (0,0), (-1,-1), DGRAY),
        ("ROWBACKGROUNDS", (0,0), (-1,-1), [colors.HexColor("#f5f5f5"), WHITE]),
        ("GRID",        (0,0), (-1,-1), 0.3, LGRAY),
        ("TOPPADDING",  (0,0), (-1,-1), 4),
        ("BOTTOMPADDING",(0,0),(-1,-1), 4),
        ("LEFTPADDING", (0,0), (-1,-1), 6),
    ]
    if header:
        style += [
            ("FONTNAME",    (0,0), (-1,0), "Helvetica-Bold"),
            ("BACKGROUND",  (0,0), (-1,0), colors.HexColor("#333333")),
            ("TEXTCOLOR",   (0,0), (-1,0), WHITE),
        ]
    t.setStyle(TableStyle(style))
    return t

story = []

# ── TITLE ──────────────────────────────────────────────────────────────────
story += [
    h1("Cassini: eBay's Search Engine"),
    small("JC² Cards Reference Guide  —  June 2026"),
    rule(),
    sp(4),
]

# ── SECTION 1 ──────────────────────────────────────────────────────────────
story += [
    h2("1. What Is Cassini?"),
    body("Cassini is eBay's internal search-ranking algorithm — named after the Saturn probe. "
         "When a buyer searches for a card, Cassini decides which of the millions of matching "
         "listings appear on page one and which get buried on page twelve. It is the single most "
         "important factor in whether your cards get seen at all."),
    body("Cassini does not rank by newest or cheapest. It ranks by predicted sale probability — "
         "the listings it believes are most likely to result in a completed transaction. "
         "Everything else follows from that one idea."),
    sp(),
]

# ── SECTION 2 ──────────────────────────────────────────────────────────────
story += [
    h2("2. The Core Signals Cassini Measures"),
    body("Cassini scores every listing on a combination of signals. The most important ones for "
         "a single-card store like JC² Cards:"),
    sp(4),
]

signal_data = [
    ["Signal", "What It Means", "Weight"],
    ["Click-through rate",
     "How often buyers click your listing when it appears in search",
     "Very High"],
    ["Sell-through rate",
     "What percentage of your listings actually sell",
     "Very High"],
    ["Price competitiveness",
     "How your price compares to active and recent sold comps",
     "High"],
    ["Item specifics completeness",
     "Player, Set, Year, Brand, Features fields filled in",
     "High"],
    ["Title keyword quality",
     "Year + Brand + Player + Set + Parallel in the right order",
     "High"],
    ["Seller feedback score",
     "Percentage of positive feedback, recency, volume",
     "Medium"],
    ["Listing age / recency",
     "Newer listings get a brief visibility boost on first appearance",
     "Medium"],
    ["Photo quality",
     "Clear front + back images; eBay rewards listings with real photos",
     "Medium"],
    ["Best Offer enabled",
     "Signals buyer-friendliness; Cassini rewards negotiable listings",
     "Low-Med"],
    ["Promoted listing ad rate",
     "Paid boost on top of organic rank; does not replace organic signals",
     "Additive"],
]
story += [
    table(signal_data, [1.6*inch, 3.4*inch, 0.9*inch]),
    sp(),
]

# ── SECTION 3 ──────────────────────────────────────────────────────────────
story += [
    h2("3. Price Is the Lever You Control Most"),
    body("Cassini knows the market. It has access to every completed sale across eBay. "
         "If your Cam Ward RC is priced at $12 and the last 10 sold for $6, "
         "Cassini treats your listing as a likely non-seller and buries it."),
    body("The rule of thumb: price within 15% of the recent sold median and Cassini "
         "treats your listing as competitive. Price more than 25% above median and "
         "your organic rank drops materially. You become invisible."),
    body("This is why the daily repricing agent runs every morning. Cards that drift "
         "above market get pushed back toward competitiveness before the day's search "
         "traffic peaks."),
    sp(4),
]

price_data = [
    ["Your Price vs. Sold Median", "Cassini Behavior"],
    ["Within 10% below",  "Top-tier placement. Maximum impressions."],
    ["At median (0%)",    "Strong placement. Competitive."],
    ["10-25% above",      "Moderate placement. Visible but not featured."],
    ["25-50% above",      "Poor placement. Most buyers never see it."],
    ["50%+ above",        "Effectively invisible in organic search."],
]
story += [
    table(price_data, [2.4*inch, 3.5*inch]),
    sp(),
]

# ── SECTION 4 ──────────────────────────────────────────────────────────────
story += [
    h2("4. The June 7 Lesson — How We Learned This the Hard Way"),
    body("On June 7, 2026, JC² Cards had its best single-day sales volume to date: "
         "9 cards sold. The trigger was a $1.99 price point on hot rookie chrome parallels "
         "(Cam Ward, Travis Hunter, Ashton Jeanty)."),
    body("The repricing agent had a bug: it re-raised winners back above $1.99 the "
         "next morning. Sales stopped. The fix was two-part: set max_step_up_pct to zero "
         "to freeze raises, and lock the 8 best-performing impulse cards in a skip list "
         "so the agent cannot touch them."),
    body("The insight: $1.99 on a hot rookie chrome is not giving it away. At that price, "
         "Cassini ranks it first, buyers click it immediately, and velocity builds. "
         "A $4.99 price on the same card might earn 30% more per unit but sell once a "
         "month instead of three times a week. The math favors $1.99."),
    sp(),
]

# ── SECTION 5 ──────────────────────────────────────────────────────────────
story += [
    h2("5. Item Specifics: The Invisible Work That Matters"),
    body("Item Specifics are the structured fields on your listing: Brand, Player, Year, "
         "Set, Features (RC, Auto, Serial Numbered). Buyers filter by these fields constantly. "
         "Cassini uses them to match your listing to searches like "
         "“2025 Panini Prizm Cam Ward Rookie” even when those exact words are not in your title."),
    body("The store had 354 Panini cards incorrectly labeled as Topps because the posting "
         "script had a hardcoded manufacturer field. Those listings were invisible to buyers "
         "filtering for Panini products. The specifics_agent.py repair job fixes ~23 per pass."),
    body("Every listing posted through post_from_scan.py now auto-infers Brand, Set, Year, "
         "and Features from the title. Never post without a brand token in the title "
         "(Prizm, Select, Donruss, Topps Chrome, etc.)."),
    sp(),
]

# ── SECTION 6 ──────────────────────────────────────────────────────────────
story += [
    h2("6. Listing Velocity and the Fresh-Listing Boost"),
    body("New listings receive a 24-48 hour visibility boost when they first go live. "
         "Cassini surfaces them to test buyer response — essentially an audition. "
         "If buyers click and buy, the listing keeps good placement. If buyers scroll past, "
         "Cassini demotes it."),
    body("This is why scanning and listing regularly beats dumping 100 cards at once every "
         "two weeks. Consistent daily or every-other-day listing keeps the store "
         "cycling through fresh-boost windows and signals to Cassini that the store "
         "is active and maintaining inventory."),
    bullet("Aim for 10-30 new listings per session, multiple sessions per week."),
    bullet("Scan expensive cards first when volume is down — one $50 auto is "
           "worth 25 base cards in Cassini signal value."),
    bullet("Listings that get early views and watchers get ranked higher permanently."),
    sp(),
]

# ── SECTION 7 ──────────────────────────────────────────────────────────────
story += [
    h2("7. Watcher Offers and Cassini"),
    body("When a buyer watches a listing, Cassini interprets it as strong buy-intent. "
         "Sending an Offer to Watchers (through the Negotiation API) converts that intent "
         "into a sale. Cassini then registers the sell-through, which improves the store's "
         "overall rank for similar cards."),
    body("The optimal timing is not 9am or 5pm. Based on June 2026 data:"),
    bullet("Morning blast (8-10am ET): Catches Friday/weekend lookers starting their day."),
    bullet("Evening blast (7-9pm ET): Highest conversion window. People are settled, "
           "not commuting or working."),
    bullet("Avoid 5pm ET: Friday afternoon people are leaving work, picking up kids, "
           "running errands. Not checking eBay."),
    sp(),
]

# ── SECTION 8 ──────────────────────────────────────────────────────────────
story += [
    h2("8. What Kills Your Cassini Rank"),
    sp(4),
]

kill_data = [
    ["Action", "Why It Hurts"],
    ["Pricing 30%+ above comps",
     "Cassini sees low sale probability and buries the listing"],
    ["Missing item specifics",
     "Listing misses filtered searches; lower match rate = lower rank"],
    ["Wrong manufacturer stamped",
     "354 Panini cards labeled Topps — invisible to Panini-filtered searches"],
    ["Duplicate listings",
     "Cassini penalizes duplicate titles; can suppress both listings"],
    ["No returns policy edge case",
     "ReturnsNotAccepted is fine; inconsistent return policies confuse the algo"],
    ["Inactive store periods",
     "No new listings for 2+ weeks signals a dormant store; rank decays"],
    ["Low sell-through rate",
     "If <5% of your listings sell per month, Cassini demotes the whole store"],
]
story += [
    table(kill_data, [2.1*inch, 3.8*inch]),
    sp(),
]

# ── SECTION 9 ──────────────────────────────────────────────────────────────
story += [
    h2("9. Daily Routine Checklist"),
    body("The daily pipeline runs these in order to maintain Cassini health:"),
    sp(4),
]

routine_data = [
    ["Step", "Agent / Action", "Purpose"],
    ["1", "card_price_agent.py", "Refresh SportsCardsPro cache"],
    ["2", "repricing_agent.py --apply", "Push prices back toward market median"],
    ["3", "best_offer_agent.py --apply", "Ensure Best Offer is enabled on all listings"],
    ["4", "watchers_offer_agent.py --apply", "Convert watchers to buyers"],
    ["5", "promoted_listings_agent.py --apply", "Maintain ad rates on key cards"],
    ["6", "Scan + post new cards", "Trigger fresh-listing boosts, add inventory"],
    ["7", "daily_digest_agent.py", "Review what sold, what's stale, what to reprice"],
]
story += [
    table(routine_data, [0.4*inch, 2.2*inch, 3.3*inch]),
    sp(),
]

# ── FOOTER ─────────────────────────────────────────────────────────────────
story += [
    sp(8),
    rule(),
    Paragraph(
        "JC² Cards  —  eBay Store: Harpua2001  —  Generated June 2026",
        CAPTION
    ),
]

doc.build(story)
print(f"PDF written to {OUT}")
