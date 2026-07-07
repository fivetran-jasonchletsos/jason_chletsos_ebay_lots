"""Visual review sheet for the Mosaic batch (scans 265-267) so JC can approve
from the couch. Groups: Green parallels, Inserts, Base. Plus the 4 held dupes.
Output -> output/mosaic_review.pdf, ~/Downloads, docs/."""
import shutil
from pathlib import Path
from PIL import Image
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.lib.colors import HexColor
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image as RLImage
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

CROP = Path("output/split_cards")
THUMB = Path("output/_thumbs_mosaic"); THUMB.mkdir(exist_ok=True)
OUT = Path("output/mosaic_review.pdf")
def crop(scan, idx):
    src = CROP / f"Scan {scan}" / f"Scan {scan}_{idx:02d}.jpg"
    th = THUMB / f"{scan}_{idx:02d}.jpg"
    if not th.exists():
        im = Image.open(src).convert("RGB"); w=300
        im.resize((w, int(im.height*w/im.width))).save(th, "JPEG", quality=72)
    return str(th)

st = getSampleStyleSheet()
H  = ParagraphStyle("H", parent=st["Heading1"], fontSize=17, spaceAfter=3, textColor=HexColor("#111"))
SUB= ParagraphStyle("SUB", parent=st["Normal"], fontSize=9.5, textColor=HexColor("#666"), spaceAfter=10)
H2 = ParagraphStyle("H2", parent=st["Heading2"], fontSize=12.5, spaceBefore=10, spaceAfter=6, textColor=HexColor("#1a3d6d"))
CAP= ParagraphStyle("CAP", parent=st["Normal"], fontSize=7.8, leading=9.4, alignment=1)
PR = ParagraphStyle("PR", parent=st["Normal"], fontSize=8.6, leading=10, alignment=1, textColor=HexColor("#137333"))
HOLD=ParagraphStyle("HOLD", parent=st["Normal"], fontSize=7.6, leading=9, alignment=1, textColor=HexColor("#b23b00"))

# (scan, idx, player, year, parallel, rc, price)
GREEN = [
 (266,1,"Ray Lewis",2024,"Green",0,4.99),(265,3,"Kyle Williams",2025,"Green",1,3.99),
 (265,5,"Greg Zuerlein",2024,"Green",0,2.99),(265,6,"Will Anderson Jr",2024,"Green",0,3.99),
 (265,8,"Drake London",2024,"Green",0,4.99),(265,9,"J.J. McCarthy",2024,"Green",0,4.99),
]
INSERT = [
 (267,1,"Bijan Robinson",2024,"Epic Performers",0,4.99),(267,7,"Larry Fitzgerald",2024,"Touchdown Masters",0,3.99),
 (266,2,"Peyton Manning",2024,"Epic Performers Fluorescent Pink",0,4.99),(266,8,"Dan Fouts",2024,"Touchdown Masters",0,2.99),
 (267,3,"Kaleb Johnson",2025,"Notoriety",1,2.99),(265,2,"Colston Loveland",2025,"Notoriety",1,3.99),
 (265,1,"Justin Jefferson",2024,"Elevate Fluorescent Pink",0,6.99),
 (266,7,"Puka Nacua",2024,"Epic Performers Green & Gold",0,4.99),
 (265,4,"Puka Nacua",2024,"Touchdown Masters Green & Gold",0,4.99),
]
BASE = [
 (266,4,"Jared Verse",2024,"Mosaic",1,2.99),(266,5,"Bill Cowher",2024,"Mosaic",0,2.99),
 (266,6,"Bobby Wagner",2024,"Mosaic",0,1.99),(266,9,"Greg Rousseau",2024,"Mosaic",0,1.99),
 (265,7,"Trey Benson",2024,"Genesis",0,3.99),
]
# (scan, idx, player, why) — confirmed base = already listed
HELD = [
 (266,3,"Drake Maye","Notoriety (base) — already listed"),
]

IW,IH=0.92*inch,1.26*inch
def cell(scan,idx,lines,price=None,hold=None):
    parts=[RLImage(crop(scan,idx),width=IW,height=IH), Paragraph(lines,CAP)]
    if price: parts.append(Paragraph(f"${price:.2f}",PR))
    if hold: parts.append(Paragraph(hold,HOLD))
    return parts

def grid(cards, kind):
    rows=[cards[i:i+6] for i in range(0,len(cards),6)]
    out=[]
    for chunk in rows:
        cts=[]
        for c in chunk:
            if kind=="new":
                scan,idx,pl,yr,par,rc,price=c
                lbl=f"<b>{pl}</b><br/>{yr} {par}{' RC' if rc else ''}"
                col=cell(scan,idx,lbl,price=price)
            else:
                scan,idx,pl,why=c
                col=cell(scan,idx,f"<b>{pl}</b>",hold=why)
            t=Table([[x] for x in col],colWidths=[1.15*inch])
            t.setStyle(TableStyle([("ALIGN",(0,0),(-1,-1),"CENTER"),("TOPPADDING",(0,0),(-1,-1),1),("BOTTOMPADDING",(0,0),(-1,-1),1)]))
            cts.append(t)
        row=Table([cts],colWidths=[1.2*inch]*len(chunk))
        row.setStyle(TableStyle([("ALIGN",(0,0),(-1,-1),"CENTER"),("VALIGN",(0,0),(-1,-1),"TOP"),("BOTTOMPADDING",(0,0),(-1,-1),8)]))
        out.append(row)
    return out

nnew=len(GREEN)+len(INSERT)+len(BASE)
story=[Paragraph("Mosaic review — scans 265-267 (v3, corrected)", H),
 Paragraph(f"harpua2001 &bull; {nnew} new to post + 1 already-listed. <b>Nothing posted yet.</b> "
   "Per your review: Jefferson &amp; Peyton = Fluorescent Pink, Trey Benson = Genesis, both Nacua = Green &amp; Gold, "
   "Scan 267 crops re-done. Cowher/Verse still plain 'Mosaic'. Prices are Best-Offer starts. Say 'go' to post.", SUB)]
story.append(Paragraph(f"GREEN MOSAIC ({len(GREEN)})", H2)); story += grid(GREEN,"new")
story.append(Paragraph(f"INSERTS ({len(INSERT)})", H2)); story += grid(INSERT,"new")
story.append(Paragraph(f"BASE / PARALLEL ({len(BASE)})", H2)); story += grid(BASE,"new")
story.append(Spacer(1,8))
story.append(Paragraph(f"ALREADY LISTED — HELD ({len(HELD)})", H2)); story += grid(HELD,"held")

SimpleDocTemplate(str(OUT),pagesize=letter,topMargin=0.5*inch,bottomMargin=0.4*inch,leftMargin=0.5*inch,rightMargin=0.5*inch).build(story)
for dest in (Path.home()/"Downloads"/"mosaic_review.pdf", Path("docs/mosaic_review.pdf")):
    shutil.copy(OUT,dest)
print("wrote",OUT,"+ ~/Downloads + docs/")
