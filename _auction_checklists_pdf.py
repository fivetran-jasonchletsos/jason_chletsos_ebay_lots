"""Generate the 3 auction stage-checklist PDFs (before/during/after) for the
crew to print/tape up. Writes docs/ + copies to ~/Downloads."""
import shutil
from pathlib import Path
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

STAGES = {
 "before": ("BEFORE — Pre-show prep", "#33c4ff", [
  ("Pick a theme","Team / player / era / product — a reason for niche collectors to show"),
  ("Pull & sort inventory in RUN ORDER","Cheap $1-5 openers first; better cards for the 2nd half"),
  ("Set floors on the good cards","Don't $1-start what you can't lose (use the fee calculator)"),
  ("Stock the table","Penny sleeves, toploaders, team bags, painter's tape within reach"),
  ("Schedule the show 24-48h ahead","In-app + teaser on IG/TikTok so regulars bookmark it"),
  ("Line up a giveaway item","Follow-to-enter in the first 5 min pulls & holds viewers"),
  ("Hard-wire internet + speed test","Ethernet > wifi; test upload at your real show time"),
  ("Assign roles","Host / Runner / Packer-Mod — everyone knows their job"),
  ("Camera + audio + lighting check","Dark mat, 2 lights at 10 & 2 o'clock, mic on, overhead framed"),
 ]),
 "during": ("DURING — Run of show", "#d98a00", [
  ("Go live ON TIME","Consistency is the #1 algorithm lever"),
  ("30-second intro","What's selling tonight + how the room works"),
  ("Giveaway in first 5 min","Follow-to-enter, tied to real inventory"),
  ("Open with cheap $1-start bangers","Warm the room and the discovery algorithm"),
  ("Call every card fully","Year -> product -> parallel -> player; show comp, start below it"),
  ("Keep chat warm","Greet by name, answer questions, never go quiet"),
  ("Pin 3+ Buy-It-Now items","~40% of sales come from BIN"),
  ("LOG every sale to a buyer","This is what makes packing accurate"),
  ("Bring the good cards out mid-show","Once the audience is present and bidding"),
  ("Second giveaway to retain","Space them to hold viewers"),
  ("Hold pace 30-60 cards/hr","Short timers on cheap, longer on premium"),
  ("Honest condition on camera","The recording is your dispute protection"),
 ]),
 "after": ("AFTER — Fulfillment & review", "#1f9c46", [
  ("Ship within 24-48h WITH a drop-off scan","You eat the refund on late unscanned orders (Mar 2026)"),
  ("Let Smart Bundling combine each buyer","One label per buyer protects your margin"),
  ("Message tracking to buyers","Builds repeat buyers"),
  ("Update the cost-basis ledger","From the Show Mode CSV — needed for taxes"),
  ("Pull the Whatnot Seller Statement","Itemizes your deductible fees"),
  ("Review the numbers","Viewers, sell-through, $/hr — what worked?"),
  ("Note what sold / what died","Shapes next show's batch"),
  ("Restock supplies","Sleeves, toploaders, mailers, labels"),
  ("Schedule the next show","Keep the fixed weekly slots"),
 ]),
}
st=getSampleStyleSheet()
h1=ParagraphStyle("h1",parent=st["Title"],fontSize=22,spaceAfter=2)
sub=ParagraphStyle("sub",parent=st["Normal"],fontSize=10,textColor=colors.HexColor("#6b7280"),spaceAfter=14)
item=ParagraphStyle("item",parent=st["Normal"],fontSize=13,leading=15)
note=ParagraphStyle("note",parent=st["Normal"],fontSize=10,textColor=colors.HexColor("#6b7280"))

def build(stage):
    title,color,items=STAGES[stage]
    out=Path(f"docs/auction_checklist_{stage}.pdf")
    doc=SimpleDocTemplate(str(out),pagesize=letter,topMargin=.7*inch,bottomMargin=.7*inch,leftMargin=.8*inch,rightMargin=.8*inch)
    flow=[Paragraph(f"Auction HQ &mdash; {title}",h1),
          Paragraph("Jason &middot; Mike &middot; Moo &middot; print &amp; tape to the wall",sub)]
    rows=[]
    for name,desc in items:
        rows.append(["☐", Paragraph(f"<b>{name}</b><br/><font size=9 color='#6b7280'>{desc}</font>",item)])
    t=Table(rows,colWidths=[0.4*inch,6.0*inch])
    t.setStyle(TableStyle([("FONTSIZE",(0,0),(0,-1),16),("VALIGN",(0,0),(-1,-1),"TOP"),
        ("LINEBELOW",(0,0),(-1,-1),0.5,colors.HexColor("#e5e7eb")),
        ("TEXTCOLOR",(0,0),(0,-1),colors.HexColor(color)),
        ("TOPPADDING",(0,0),(-1,-1),7),("BOTTOMPADDING",(0,0),(-1,-1),7)]))
    flow.append(t)
    flow.append(Spacer(1,10))
    flow.append(Paragraph("Live at: fivetran-jasonchletsos.github.io/jason_chletsos_ebay_lots/auction_hq.html",note))
    doc.build(flow)
    dl=Path.home()/"Downloads"/out.name; shutil.copy(out,dl)
    print("wrote",out,"->",dl)

for s in STAGES: build(s)
print("done — 3 checklist PDFs")
