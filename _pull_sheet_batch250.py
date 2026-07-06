"""Visual pull sheet for scans 252-261 (~90 cards) — the synthesized 2-expert plan.
Singles + lots (<=4) with images and suggested prices. Cards likely already live
(pending precise de-dup after API reset) are flagged [VERIFY-LIVE].
Output -> output/pull_sheet_batch250.pdf, ~/Downloads, docs/."""
import shutil
from pathlib import Path
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.lib.colors import HexColor
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image as RLImage)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

from PIL import Image
CROP = Path("output/split_cards")
THUMB = Path("output/_thumbs250b"); THUMB.mkdir(exist_ok=True)
OUT = Path("output/pull_sheet_batch250.pdf")
# grid_split assigned scan file numbers in a different order than the sheets were
# read into the catalog. This maps catalog-block number -> real file on disk.
# Verified by reading position-1 of all 10 files (10/10 anchors match) + spot checks
# (254_06 Tyler Baron, 261_02 CeeDee Lamb, 259_05 Bosa). No duplicate files.
REMAP = {252:257, 253:261, 254:253, 255:255, 256:256,
         257:260, 258:258, 259:259, 260:254, 261:252}
def crop(scan, idx):
    f = REMAP.get(scan, scan)
    src = CROP / f"Scan {f}" / f"Scan {f}_{idx:02d}.jpg"
    th = THUMB / f"{f}_{idx:02d}.jpg"
    if not th.exists():
        im = Image.open(src).convert("RGB")
        w = 300; im = im.resize((w, int(im.height*w/im.width)))
        im.save(th, "JPEG", quality=72)
    return str(th)

styles = getSampleStyleSheet()
H  = ParagraphStyle("H", parent=styles["Heading1"], fontSize=17, spaceAfter=3, textColor=HexColor("#111111"))
SUB= ParagraphStyle("SUB", parent=styles["Normal"], fontSize=9.5, textColor=HexColor("#666"), spaceAfter=10)
H2 = ParagraphStyle("H2", parent=styles["Heading2"], fontSize=12.5, spaceBefore=10, spaceAfter=6, textColor=HexColor("#1a3d6d"))
CAP= ParagraphStyle("CAP", parent=styles["Normal"], fontSize=7.6, leading=9, alignment=1)
PR = ParagraphStyle("PR", parent=styles["Normal"], fontSize=8.5, leading=10, alignment=1, textColor=HexColor("#137333"))
LOTP=ParagraphStyle("LOTP", parent=styles["Normal"], fontSize=10, leading=12, textColor=HexColor("#137333"))
LIVE=ParagraphStyle("LIVE", parent=styles["Normal"], fontSize=6.8, leading=8, alignment=1, textColor=HexColor("#b23b00"))

# SINGLES: (scan, idx, player, parallel, price, verify_live)
SINGLES = [
 (255,7,"Ashton Jeanty","Prizmatic RC","$13.99",True),
 (253,1,"Shedeur Sanders","Prizm RC","$10.99",False),
 (261,5,"Cam Ward","Topps Notoriety RC","$8.99",False),
 (255,2,"Omarion Hampton","Prizm Green Crk Ice RC","$10.99",True),
 (260,9,"Michael Penix Jr","Cosmic RC","$5.99",False),
 (256,2,"Quinn Ewers","Cosmic RC","$4.99",False),
 (259,5,"Nick Bosa","Prizm","$4.99",False),
 (259,3,"Puka Nacua","Prizm","$5.99",False),
 (252,3,"Puka Nacua","Select Turbocharged","$6.99",False),
 (259,9,"T.J. Watt","Optic Light It Up","$5.99",False),
 (258,3,"Brock Bowers","Prizm","$7.99",False),
 (253,2,"CeeDee Lamb","Select","$4.99",False),
 (257,3,"Stefon Diggs","Mosaic","$3.99",False),
 (257,1,"Josh Jacobs","Prizm","$3.99",False),
 (261,4,"Jayden Daniels","Mosaic TD Masters","$8.99",False),
 (260,4,"Caleb Williams","Prizm Global Reach","$6.99",True),
 (256,8,"C.J. Stroud","Prizm","$4.99",False),
 (259,1,"Jared Goff","Prizm RWB","$4.99",False),
 (256,5,"Trey McBride","Cosmic","$3.99",False),
 (256,7,"Nico Collins","Cosmic","$3.99",False),
 (255,6,"De'Von Achane","Cosmic","$4.99",False),
 (260,3,"DeAndre Hopkins","Cosmic","$3.99",False),
 (259,2,"Breece Hall","Prizm","$4.99",False),
 (253,3,"Tee Higgins","Mosaic","$3.99",False),
 (253,9,"Derek Stingley Jr","Mosaic Epic Perf","$3.99",False),
 (252,7,"Khalil Mack","Prizm","$3.99",False),
 (254,6,"Mike Evans","Prizm Draft Red Crk Ice","$6.99",False),
 (258,9,"Matthew Stafford","Prizm Black","$6.99",False),
 (255,5,"Kelvin Banks Jr","Prizm Green RC","$4.99",True),
 (255,1,"Mark Andrews","Phoenix Silver","$4.99",True),
 (260,1,"Derwin James Jr","Prizm Green","$4.99",True),
 (260,2,"RJ Harvey","Prizm Emergent RC","$4.99",True),
]

# LOTS: (title, price, [ (scan,idx,label,verify_live) ... up to 4 ])
LOTS = [
 ("Mike Evans Lot A","$10.99",[(254,3,"Prizm",False),(254,4,"Select",False),(254,5,"Mosaic",False),(254,1,"Donruss",False)]),
 ("Mike Evans Lot B","$9.99",[(254,2,"Cosmic",False),(254,9,"Prizm Draft",False),(254,7,"Totally Cert",False),(254,8,"Contenders",False)]),
 ("Matthew Stafford Lot","$9.99",[(258,5,"Prizm",False),(258,4,"Mosaic",False),(258,7,"Mosaic Silver",False),(258,2,"Contenders",False)]),
 ("QB / Vet Depth Lot","$6.99",[(258,6,"Stafford Cont",False),(261,9,"Stafford Select",False),(256,1,"Jordan Addison",False),(260,7,"Mike Vrabel",True)]),
 ("Derwin James / Defense Lot","$6.99",[(261,2,"Derwin Mosaic",False),(261,6,"Derwin Mosaic",False),(259,4,"Tremaine Edmunds",False),(261,1,"Jordan James RC",False)]),
 ("Cosmic Rookie Lot","$7.99",[(253,7,"Tate Ratledge RC",False),(260,5,"Croskey-Merritt RC",False),(255,9,"Mike Evans Cosmic",False),(260,8,"Savaiinaea RC",False)]),
 ("Rookie Skill Fliers Lot","$7.99",[(252,5,"Arian Smith RC",False),(252,6,"Jalen Milroe RC",False),(257,4,"Jaydon Blue RC",False),(257,5,"Pat Bryant RC",True)]),
 ("Rookie WR/RB Lot","$7.99",[(253,5,"Tre Harris RC",False),(253,4,"Tory Horton RC",False),(257,6,"Woody Marks RC",False),(259,6,"DJ Giddens RC",False)]),
 ("Rookie Color Sleepers Lot","$8.99",[(255,4,"Tai Felton Elevate",True),(258,8,"Tai Felton Select",False),(257,9,"Emmanwori Purple",True),(260,6,"Tyler Baron RC",False)]),
 ("NFL Legends Lot A","$8.99",[(257,7,"Tony Dorsett",False),(259,8,"Hines Ward",False),(253,6,"Michael Irvin",False),(261,7,"Eric Allen HOF",False)]),
 ("NFL Legends Lot B","$6.99",[(261,3,"Jamal Anderson",False),(261,8,"Dwight Freeney",False),(256,9,"Keyshawn Johnson",False),(253,8,"Cedric Tillman",False)]),
 ("Vet / Bills Lot","$6.99",[(252,1,"Dalton Kincaid",False),(257,2,"Dawson Knox",False),(252,2,"Evan Engram",False),(252,8,"Jakobi Meyers",False)]),
 ("Role-Player Prizm Lot","$6.99",[(259,7,"Marshon Lattimore",False),(252,4,"L'Jarius Sneed",False),(256,6,"Kwity Paye",False),(256,3,"Braelon Allen",False)]),
 ("WR/TE Grab-Bag Lot","$5.99",[(252,9,"Jake Ferguson",False),(257,8,"Mike Gesicki",False),(256,4,"Jaylen Warren",False),(258,1,"Breece Hall Rev",False)]),
]
# Possible duplicate re-scans to verify physically (fold into a lot if real):
DUPES = [(255,3,"Tate Ratledge (2nd?)"),(255,8,"Tory Horton (2nd?)")]

story=[]
story.append(Paragraph("Pull sheet — scans 252-261 (~90 cards)", H))
story.append(Paragraph("harpua2001 &bull; 2026-07-06 &bull; 2-expert plan. <b>Nothing posted yet &mdash; images now verified.</b> "
    "The scan files were mis-numbered by the splitter; that's fixed, so every crop below is the correct card. "
    "[VERIFY-LIVE] = likely already listed today; set aside until de-dup confirms. Prices are Best-Offer starts.", SUB))

IW,IH=0.92*inch,1.26*inch
def img_cell(scan,idx,label,price=None,live=False):
    parts=[RLImage(crop(scan,idx),width=IW,height=IH), Paragraph(label,CAP)]
    if price: parts.append(Paragraph(price,PR))
    if live: parts.append(Paragraph("[VERIFY-LIVE]",LIVE))
    return parts

# SINGLES grid, 6 per row
story.append(Paragraph(f"SINGLES ({len(SINGLES)})", H2))
percol=6
rows=[SINGLES[i:i+percol] for i in range(0,len(SINGLES),percol)]
for chunk in rows:
    imgs=[]; caps=[]
    for scan,idx,player,par,price,live in chunk:
        c=img_cell(scan,idx,f"<b>{player}</b><br/>{par}",price,live)
        imgs.append(c[0])
        sub=[c[1],c[2]]+([c[3]] if live else [])
        caps.append(sub)
    # build a mini-table per cell to stack caption/price/flag
    celltables=[]
    for j,(scan,idx,player,par,price,live) in enumerate(chunk):
        col=[img_cell(scan,idx,f"<b>{player}</b><br/>{par}",price,live)]
        t=Table([[x] for x in col[0]],colWidths=[1.15*inch])
        t.setStyle(TableStyle([("ALIGN",(0,0),(-1,-1),"CENTER"),("TOPPADDING",(0,0),(-1,-1),1),("BOTTOMPADDING",(0,0),(-1,-1),1)]))
        celltables.append(t)
    row=Table([celltables],colWidths=[1.2*inch]*len(chunk))
    row.setStyle(TableStyle([("ALIGN",(0,0),(-1,-1),"CENTER"),("VALIGN",(0,0),(-1,-1),"TOP"),("BOTTOMPADDING",(0,0),(-1,-1),6)]))
    story.append(row)

# LOTS
story.append(Spacer(1,6))
story.append(Paragraph(f"LOTS ({len(LOTS)}) — 4 cards max each", H2))
for title,price,cards in LOTS:
    story.append(Paragraph(f"<b>{title}</b> &mdash; {price}", LOTP))
    celltables=[]
    for scan,idx,label,live in cards:
        col=img_cell(scan,idx,label,None,live)
        t=Table([[x] for x in col],colWidths=[1.15*inch])
        t.setStyle(TableStyle([("ALIGN",(0,0),(-1,-1),"CENTER"),("TOPPADDING",(0,0),(-1,-1),1),("BOTTOMPADDING",(0,0),(-1,-1),1)]))
        celltables.append(t)
    row=Table([celltables],colWidths=[1.2*inch]*len(cards))
    row.setStyle(TableStyle([("ALIGN",(0,0),(-1,-1),"LEFT"),("VALIGN",(0,0),(-1,-1),"TOP"),("BOTTOMPADDING",(0,0),(-1,-1),8)]))
    story.append(row)

story.append(Spacer(1,6))
story.append(Paragraph("Verify physically (possible re-scan duplicates — fold into nearest Cosmic/rookie lot if real):", H2))
dcells=[]
for scan,idx,label in DUPES:
    col=img_cell(scan,idx,label,None,False)
    t=Table([[x] for x in col],colWidths=[1.15*inch]); t.setStyle(TableStyle([("ALIGN",(0,0),(-1,-1),"CENTER")]))
    dcells.append(t)
story.append(Table([dcells],colWidths=[1.2*inch]*len(dcells)))

doc=SimpleDocTemplate(str(OUT),pagesize=letter,topMargin=0.5*inch,bottomMargin=0.4*inch,leftMargin=0.5*inch,rightMargin=0.5*inch)
doc.build(story)
for dest in (Path.home()/"Downloads"/"pull_sheet_batch250.pdf", Path("docs/pull_sheet_batch250.pdf")):
    shutil.copy(OUT,dest)
print("wrote",OUT,"+ ~/Downloads + docs/")
