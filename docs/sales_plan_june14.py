"""Generate the 5-agent sales plan PDF for Saturday June 14, 2026."""
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
)
from reportlab.lib.enums import TA_LEFT, TA_CENTER

OUT = "docs/sales_plan_june14.pdf"

doc = SimpleDocTemplate(OUT, pagesize=letter,
    leftMargin=0.75*inch, rightMargin=0.75*inch,
    topMargin=0.75*inch, bottomMargin=0.75*inch)

BLACK  = colors.black
DGRAY  = colors.HexColor("#222222")
MGRAY  = colors.HexColor("#555555")
LGRAY  = colors.HexColor("#cccccc")
WHITE  = colors.white

styles = getSampleStyleSheet()

H1  = ParagraphStyle("H1",  fontSize=17, leading=21, textColor=BLACK, spaceAfter=3,  fontName="Helvetica-Bold")
H2  = ParagraphStyle("H2",  fontSize=11, leading=14, textColor=BLACK, spaceBefore=12, spaceAfter=3, fontName="Helvetica-Bold")
H3  = ParagraphStyle("H3",  fontSize=9.5, leading=13, textColor=BLACK, spaceBefore=8, spaceAfter=2, fontName="Helvetica-Bold")
BODY= ParagraphStyle("BODY",fontSize=8.5, leading=12.5, textColor=DGRAY, spaceAfter=4, fontName="Helvetica")
BLET= ParagraphStyle("BLET",parent=BODY, leftIndent=12, firstLineIndent=-10, spaceAfter=2)
SML = ParagraphStyle("SML", fontSize=7.5, leading=11, textColor=MGRAY, spaceAfter=3, fontName="Helvetica")
CAP = ParagraphStyle("CAP", fontSize=7.5, leading=11, textColor=MGRAY, fontName="Helvetica", alignment=TA_CENTER)

def rule(): return HRFlowable(width="100%", thickness=0.5, color=LGRAY, spaceAfter=6)
def sp(n=5): return Spacer(1, n)
def h1(t): return Paragraph(t, H1)
def h2(t): return Paragraph(t, H2)
def h3(t): return Paragraph(t, H3)
def body(t): return Paragraph(t, BODY)
def blet(t): return Paragraph(f"•  {t}", BLET)
def sml(t): return Paragraph(t, SML)

def tbl(data, widths, header=True):
    t = Table(data, colWidths=widths)
    s = [
        ("FONTNAME",(0,0),(-1,-1),"Helvetica"),
        ("FONTSIZE",(0,0),(-1,-1),7.5),
        ("TEXTCOLOR",(0,0),(-1,-1),DGRAY),
        ("ROWBACKGROUNDS",(0,0),(-1,-1),[colors.HexColor("#f4f4f4"), WHITE]),
        ("GRID",(0,0),(-1,-1),0.3,LGRAY),
        ("TOPPADDING",(0,0),(-1,-1),3),
        ("BOTTOMPADDING",(0,0),(-1,-1),3),
        ("LEFTPADDING",(0,0),(-1,-1),5),
        ("VALIGN",(0,0),(-1,-1),"TOP"),
    ]
    if header:
        s += [
            ("FONTNAME",(0,0),(-1,0),"Helvetica-Bold"),
            ("BACKGROUND",(0,0),(-1,0),colors.HexColor("#2a2a2a")),
            ("TEXTCOLOR",(0,0),(-1,0),WHITE),
        ]
    t.setStyle(TableStyle(s))
    return t

story = []

# TITLE
story += [
    h1("JC² Cards — Saturday Sales Plan"),
    sml("5-Agent Advisory Panel  |  June 14, 2026  |  Execute tonight into 9am ET Sunday"),
    rule(), sp(4),
]

# EXECUTIVE SUMMARY
story += [
    h2("Executive Summary"),
    body("The store has 11 orders and $174.87 in revenue today (Saturday). Goal: 5+ more sales before 9am Sunday. "
         "The core problem is a dead zone of base parallels priced $6.99-$14.99 with zero watchers and zero velocity. "
         "The June 7 proof point is clear: $1.99-$2.99 on hot rookie chromes drove 9 sales in one day. "
         "The plan collapses non-numbered base parallels into impulse brackets, fires the 8pm ET watcher offer blast "
         "as the Saturday evening anchor, and runs three sequenced repricing batches with snapshot refreshes between each. "
         "Numbered parallels, autos, and short prints are explicitly protected throughout."),
    sp(),
]

# ACTION PLAN
story += [h2("Action Runbook — Execute in Order")]

actions = [
    ("Step", "Time (ET)", "Command / Action", "Rationale"),
    ("1", "Now", "python3 refresh_snapshot.py",
     "Snapshot is 12+ hrs old. All agent decisions are only as good as this data."),
    ("2", "Now", "Seller Hub: verify ghost listing 306965305227 is ENDED",
     "Ghost Cam Ward at $101.20 splits impressions and will absorb the watcher offer instead of the real card 306939333836."),
    ("3", "Now", "python3 repricing_agent.py (dry-run)",
     "Confirm 25-card queue targets the right cards. Verify no numbered parallels, autos, or SPs in drop queue."),
    ("4", "Now", "python3 repricing_agent.py --apply",
     "First batch: Cam Ward and Caleb Williams mid-tier drops. Cassini freshness boost fires immediately."),
    ("5", "5:00pm", "python3 refresh_snapshot.py + repricing_agent.py (dry-run)",
     "Always refresh before second apply. Confirm second batch contains the $6.99-$10.99 Ward and Hunter base parallels."),
    ("6", "5:05pm", "python3 repricing_agent.py --apply",
     "Second batch: Cam Ward Select $6.99→$2.99, Travis Hunter Thunderbirds/Mosaic $8.99→$4.99. Peak Saturday browse window."),
    ("7", "5:30pm", "python3 best_offer_agent.py --apply",
     "Enable Best Offer on 89 eligible listings. Auto-accept at 90% of market median. Passive sales engine overnight."),
    ("8", "7:00pm", "python3 refresh_snapshot.py + repricing_agent.py --apply",
     "Third batch: Jeanty $10.99-$12.99 base parallels → $6.99-$7.99; Mahomes Icon Collection x6 → $4.99. Fires 60min before watcher blast."),
    ("9", "7:45pm", "python3 promoted_listings_agent.py --dry-run",
     "Verify 8% rate active on all listings $5+. Raise daily budget $10→$25 if needed. Do NOT spike rate above 8%."),
    ("10", "8:00pm", "python3 watchers_offer_agent.py --apply",
     "15 eligible listings at 15% off BIN. Priority: Caleb Williams Shock (10 watchers), Cam Ward real listing (4 watchers). Saturday night Sunday-fear window."),
    ("11", "9:00pm", "Optional: Manual BIN drops in Seller Hub if <3 sales since Step 4",
     "Bryce Underwood Pink Lava $4.99→$1.99, Tate Ratledge /175 $3.99→$1.99. Price-drop notification is a second trigger to the same watchers."),
    ("12", "10pm-11pm", "python3 refresh_snapshot.py",
     "Final snapshot so Best Offer engine runs on today's comp data overnight. No additional repricing. Let it run."),
]
story += [tbl(actions, [0.35*inch, 0.65*inch, 2.3*inch, 3.25*inch]), sp()]

# PRICE DROPS
story += [h2("Specific Price Drops")]

drops = [
    ("Card", "Current", "Target", "Reason"),
    ("Cam Ward Select Premier Silver (306996442389)", "$6.99", "$2.99",
     "Non-numbered. Proven velocity at $2.99. Cassini dead zone above $4."),
    ("Cam Ward Select base (306997193468)", "$6.99", "$2.99",
     "Same logic. Zero watchers. Bracket collapse."),
    ("Cam Ward Select Gold Green x2", "$8.99 ea", "$3.99 ea",
     "Non-numbered color parallel. Two copies create self-competition."),
    ("Cam Ward Phoenix (306996441756)", "$10.99", "$4.99",
     "Phoenix base inserts are commodity tier. No comp support at $10.99."),
    ("Travis Hunter Thunderbirds x2", "$8.99 ea", "$4.99 ea",
     "Base insert. Zero sales in $8-$11 band. Drops below mobile 'under $5' filter."),
    ("Travis Hunter Mosaic", "$8.99", "$4.99",
     "Mosaic base RC parallel. Same dead zone. $4.99 matches May Pink Shock sold."),
    ("Travis Hunter Rookies and Stars", "$8.99", "$4.99",
     "Non-differentiated insert. Saturday impulse buyer at $4.99, not $8.99."),
    ("Travis Hunter Mosaic Elevate", "$11.99", "$5.99",
     "Subset insert justifies slight premium over base. Still below dead zone."),
    ("Ashton Jeanty Select Turbocharged", "$10.99", "$6.99",
     "Named subset but not numbered. Above impulse ceiling for non-numbered Jeanty."),
    ("Ashton Jeanty Phoenix x2", "$12.99 ea", "$7.99 ea",
     "Phoenix base. $7.99 is current impulse ceiling for non-numbered Jeanty parallels."),
    ("Ashton Jeanty Prizm Draft Picks", "$12.99", "$7.99",
     "Not the flagship Prizm set. $12.99 above market position."),
    ("Mahomes Icon Collection x6", "$7.99 ea", "$4.99 ea",
     "Six identical cards = Cassini dilution. $4.99 below mobile under-$5 filter."),
    ("HOLD — Cam Ward Pink X-Fractor 306939333836", "$27.99", "HOLD",
     "4 watchers. Fire watcher offer at 15% off first ($23.79). Reprice only if offer expires unsold."),
    ("HOLD — Caleb Williams Shock Prizm 306990367662", "$12.34", "HOLD",
     "10 watchers. Watcher offer at 15% off ($10.49) preserves more margin than pre-dropping."),
    ("HOLD — All numbered parallels, autos, SPs", "—", "HOLD",
     "Hunter Prizm Teal Black, Ward Select Certified, and all serially-numbered cards stay put."),
]
story += [tbl(drops, [2.4*inch, 0.6*inch, 0.6*inch, 2.95*inch]), sp()]

# PROJECTED SALES
story += [
    h2("Projected Outcome"),
    body("Conservative: 5 additional sales before 9am Sunday. Optimistic: 9 sales."),
    sp(3),
]

proj = [
    ("Mechanism", "Projected Sales", "Key Driver"),
    ("Repricing (3 batches, ~75 drops)", "3-5 impulse closes",
     "Hot-name chromes at $1.99-$4.99. June 7 proof: 9 sales from same approach."),
    ("Watcher offer blast 8pm ET (15 listings at 15% off)", "1-3 conversions",
     "Caleb Williams 10-watcher listing is highest probability. Sunday-fear psychology."),
    ("Best Offer passive engine overnight (89 listings)", "1-2 auto-accepts",
     "Hampton/Sanders at $14.99 vs $1.98 median — any serious offer gets accepted instantly."),
    ("Optional BIN drops at 9pm if <3 sales", "0-1 additional",
     "Price-drop notification acts as second trigger to existing watchers."),
]
story += [tbl(proj, [1.9*inch, 1.2*inch, 3.45*inch]), sp()]

# PANEL DEBATE SUMMARY
story += [h2("Panel Debate — Where They Disagreed")]

debates = [
    ("Debate 1 — Watcher offer timing",
     "Conversion Optimizer argued for immediate afternoon blast. eBay Algo Expert and Ops Manager overruled: "
     "morning and 3pm sends exhausted cooldown slots. 15 clean-cooldown listings remain. Saturday 8pm is the "
     "Sunday-fear window. Firing at 3pm burns those 15 slots at lower-intent moment. 8pm anchor stands."),
    ("Debate 2 — Promoted listing rate spike",
     "eBay Algo Expert argued for 12-15% to punch through Saturday ad auction. Majority said no: risk is "
     "promoting $1.99 cards into losses before price-band filter is verified. Compromise: keep 8% rate, "
     "raise daily budget $10→$25. Same impression share, no downside risk."),
    ("Debate 3 — Jeanty Green /75 at $29.99",
     "Pricing Strategist wanted to cut to $24.99 for velocity. Sports Card Market Analyst correctly held line: "
     "comps support $35-55 on Green /75, store is already cheapest at $29.99. Promoted listing carries "
     "impression load. Hold. Cutting $5 sacrifices anchor position for marginal probability gain."),
    ("Debate 4 — Snapshot refresh discipline",
     "Ops Manager identified critical failure mode: applying repricing twice on the same snapshot re-executes "
     "the same 25-card queue, burning API quota and triggering revision throttle. Rule: always refresh → "
     "dry-run → apply. Never apply twice on the same snapshot."),
    ("Debate 5 — Numbered vs. unnumbered protection",
     "Pricing Strategist enforced the guardrail throughout: do NOT conflate 'zero watchers at above-market "
     "price' with 'droppable.' Numbered parallels, autos, and SPs stay at current price. Travis Hunter Teal "
     "Black ($9.99) and Cam Ward Select Certified ($17.99) explicitly excluded from all drop queues."),
]

for title, content in debates:
    story += [h3(title), body(content), sp(3)]

# FOOTER
story += [
    sp(8), rule(),
    Paragraph("JC² Cards  —  5-Agent Advisory Panel  —  June 14, 2026  —  Execute tonight", CAP),
]

doc.build(story)
print(f"PDF written to {OUT}")
