"""Build a plain-text-style PDF summarizing the scan 221-249 posting session
plus the 2026-07-05 Scan 232 / lot-fix cleanup, for JC's review.
Output -> output/session_report.pdf and ~/Downloads."""
import shutil
from pathlib import Path
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.lib.colors import HexColor
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

OUT = Path("output/session_report.pdf")
styles = getSampleStyleSheet()
H = ParagraphStyle("H", parent=styles["Heading1"], fontSize=17, spaceAfter=4, textColor=HexColor("#111111"))
SUB = ParagraphStyle("SUB", parent=styles["Normal"], fontSize=9.5, textColor=HexColor("#666666"), spaceAfter=12)
H2 = ParagraphStyle("H2", parent=styles["Heading2"], fontSize=12.5, spaceBefore=12, spaceAfter=5, textColor=HexColor("#1a3d6d"))
BODY = ParagraphStyle("BODY", parent=styles["Normal"], fontSize=10, leading=14, spaceAfter=5)
BULLET = ParagraphStyle("BULLET", parent=BODY, leftIndent=14, bulletIndent=2)
FLAG = ParagraphStyle("FLAG", parent=BODY, backColor=HexColor("#fff4e5"), borderColor=HexColor("#e0a44a"),
                      borderWidth=0.7, borderPadding=6, leading=14)

story = []
story.append(Paragraph("Session recap: scans 221-249 + Scan 232 / lot cleanup", H))
story.append(Paragraph("harpua2001 &bull; updated 2026-07-05 &bull; everything Claude did, plus what still needs your eyes", SUB))

def section(title): story.append(Paragraph(title, H2))
def p(txt): story.append(Paragraph(txt, BODY))
def b(txt): story.append(Paragraph("&bull;&nbsp; " + txt, BULLET))
def flag(txt): story.append(Paragraph(txt, FLAG)); story.append(Spacer(1, 4))

# --- Today's lot cleanup (the new work) ---
section("Today's cleanup (Scan 232 + bad lots)")
p("You flagged wrong pictures on Lot 10 and Lot 16. Reading the crops directly turned up a "
  "scan-numbering mess: several lots were showing cards that didn't match their titles. Fixed:")
b("<b>Lot 10</b> (307044329510): the \"Cole Kmet\" was fiction &mdash; that crop was actually a Tyleik "
  "Williams card <i>back</i> plus a Zay Flowers insert fragment. Scan 243 has no Kmet. Rebuilt as a clean "
  "2-card lot: <b>Pat Bryant + Tyleik Williams</b>, $6.99.")
b("<b>Lot 16</b> (307044256082): titled \"Leonard Wingo Alexander Sanders\" but pictured a totally different "
  "Prizm sheet. Rebuilt to match reality: <b>Kelvin Banks Jr RC, RJ Harvey RC, Tai Felton RC</b>, $7.99.")
b("<b>Lot 17</b> (307044256122): same root cause. Rebuilt: <b>Caleb Williams, Jalen Royals RC, Mike Vrabel</b>, $7.99.")
b("Pulled the two standout cards out as their own singles (your call):")
b("&nbsp;&nbsp;&mdash; <b>Ashton Jeanty Prizmatic RC</b> &rarr; new single 307044447834, $17.99, Best Offer.")
b("&nbsp;&nbsp;&mdash; <b>Joe Montana Prizmatic</b> &rarr; was already listed as a single, so no duplicate; just "
  "removed from the lot.")
b("<b>Derwin James Jr</b> (Prizm Green, Chargers) was the one Scan 232 card never listed &mdash; now live: "
  "307044468986, $5.99.")
b("<b>Arch Manning</b> (307044329349) ended per your call; the fictional entries are documented and disabled "
  "in the plan source so they can't regenerate.")

# --- Root cause note ---
section("Why the pictures were wrong")
p("The crop folder \"Scan 232\" held a Panini Prizm base/insert sheet (Kelvin Banks, Joe Montana, RJ Harvey, "
  "Derwin James, Ashton Jeanty, Tai Felton, Mike Vrabel, Caleb Williams, Arch Manning), but the plan had "
  "labeled those same slots as \"Prizm Draft College\" players (Ryan Wingo, Riley Leonard, etc.). The scan "
  "numbers got crossed during re-scanning, and auto-ID never caught it. Every card has now been read by eye "
  "and the listings match the actual cards.")

# --- Original batch (context) ---
section("Earlier in the batch (scans 221-249)")
b("~88 listings posted across scans 221-249, singles + small lots, with a duplicate guard.")
b("Scan 231 fully re-verified by hand (auto-ID had 8 of 9 wrong).")
b("T.J. Watt false \"1/1\" removed; 4 Phoenix Contours relabeled by color, repriced $12.99.")
b("Serials captured: Mason Graham 159/385, Bhayshul Tuten 654/899.")

# --- Problems still needing your call ---
section("Still needs your attention")
flag("<b>Duplicate zebra SALE.</b> The Jameson Williams Zebra (Select) sold, then the old duplicate guard "
     "reposted it (only checked active, not sold listings), and the repost (307044329432) <b>sold again</b>. If "
     "you already shipped the first one, cancel/refund one of the two orders before the second ships.")
flag("<b>Guard fix pending.</b> The batch repost guard should also load SOLD titles so a sold card can't be "
     "relisted. (The daily oversell_guard.py already covers this by SKU; the batch script is the gap.) A "
     "read-only sweep today found 0 other active listings duplicating a sold card, so it's contained.")

# --- Actions table ---
section("eBay actions this session")
data = [["Item / action", "Result"],
        ["~88 new listings (scans 221-249)", "Live"],
        ["Lot 10 307044329510", "Rebuilt 2-card (Bryant + Williams), $6.99"],
        ["Lot 16 307044256082", "Rebuilt 3-card (Banks/Harvey/Felton), $7.99"],
        ["Lot 17 307044256122", "Rebuilt 3-card (Williams/Royals/Vrabel), $7.99"],
        ["Ashton Jeanty Prizmatic RC 307044447834", "New single, $17.99"],
        ["Derwin James Jr Green 307044468986", "New single, $5.99"],
        ["Joe Montana Prizmatic", "Already live; excluded from lot"],
        ["Arch Manning 307044329349", "Ended per your call"],
        ["Jameson Zebra 307044329432", "Reposted + re-sold &mdash; reconcile"],
        ["Sold-repost sweep", "0 others found (read-only)"]]
t = Table(data, colWidths=[3.7*inch, 2.9*inch])
t.setStyle(TableStyle([
    ("BACKGROUND",(0,0),(-1,0),HexColor("#1a3d6d")),
    ("TEXTCOLOR",(0,0),(-1,0),HexColor("#ffffff")),
    ("FONTSIZE",(0,0),(-1,-1),8.5),
    ("FONTNAME",(0,0),(-1,0),"Helvetica-Bold"),
    ("GRID",(0,0),(-1,-1),0.4,HexColor("#cccccc")),
    ("ROWBACKGROUNDS",(0,1),(-1,-1),[HexColor("#ffffff"),HexColor("#f4f6f9")]),
    ("VALIGN",(0,0),(-1,-1),"MIDDLE"),
    ("TOPPADDING",(0,0),(-1,-1),4),("BOTTOMPADDING",(0,0),(-1,-1),4),
    ("LEFTPADDING",(0,0),(-1,-1),6)]))
story.append(t)

section("Suggested next steps")
b("Reconcile the duplicate zebra order (cancel/refund the second sale).")
b("Give me the go-ahead to ship the SOLD-title fix into the batch guard so this can't recur.")
b("If any other older lot looks off, point me at it &mdash; I'll read the crops and fix it the same way.")

doc = SimpleDocTemplate(str(OUT), pagesize=letter, topMargin=0.6*inch, bottomMargin=0.6*inch,
                        leftMargin=0.7*inch, rightMargin=0.7*inch)
doc.build(story)
dl = Path.home()/"Downloads"/"session_report.pdf"
shutil.copy(OUT, dl)
print("wrote", OUT, "and", dl)
