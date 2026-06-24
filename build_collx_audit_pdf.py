"""build_collx_audit_pdf.py — CollX entry sheet for audit cards the eBay APIs
couldn't reprice (offer not retrievable). Reads output/_collx_locked.json.
Output: ~/Downloads/harpua2001_collx_audit_<date>.pdf
"""
from __future__ import annotations
import json
from datetime import datetime
from pathlib import Path
from reportlab.lib.colors import HexColor, white
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas

OUT = Path.home() / "Downloads" / f"harpua2001_collx_audit_{datetime.now():%Y-%m-%d}.pdf"
INK=HexColor("#1a1a1a"); GOLD=HexColor("#b8860b"); GREEN=HexColor("#1d7a3f")
RED=HexColor("#b03030"); GREY=HexColor("#777777"); LINE=HexColor("#e2e2e2")
CONF={"high":GREEN,"med":HexColor("#b8860b"),"medium":HexColor("#b8860b"),"low":HexColor("#999999")}

def money(x): return f"${float(x):,.2f}"

def main():
    rows=json.loads(Path("output/_collx_locked.json").read_text())
    rows.sort(key=lambda r:float(r["cur"])-float(r["rec"]), reverse=True)
    PW,PH=letter; ML,MR=0.55*inch,0.55*inch
    c=canvas.Canvas(str(OUT),pagesize=letter)
    tot_cur=sum(float(r["cur"]) for r in rows); tot_rec=sum(float(r["rec"]) for r in rows)

    def header():
        HDR=0.92*inch
        c.setFillColor(INK); c.rect(0,PH-HDR,PW,HDR,stroke=0,fill=1)
        c.setFillColor(white); c.setFont("Helvetica-Bold",19)
        c.drawString(ML,PH-0.5*inch,"CollX Audit — Enter These Prices")
        c.setFont("Helvetica",9.5); c.setFillColor(HexColor("#cfcfcf"))
        c.drawString(ML,PH-0.72*inch,f"{len(rows)} cards the eBay API couldn't touch · recommended price-to-move (recent sold comps)")
        c.setFont("Helvetica",9)
        c.drawRightString(PW-MR,PH-0.5*inch,datetime.now().strftime("%b %d, %Y"))
        c.drawRightString(PW-MR,PH-0.72*inch,"harpua2001")
        y=PH-HDR-0.26*inch
        c.setFont("Helvetica-Bold",7.5); c.setFillColor(GREY)
        c.drawString(ML+0.18*inch,y,"CARD"); c.drawRightString(PW-MR-1.35*inch,y,"WAS")
        c.drawRightString(PW-MR-0.55*inch,y,"COLLX"); c.drawRightString(PW-MR,y,"CONF")
        y-=0.08*inch; c.setStrokeColor(INK); c.setLineWidth(1); c.line(ML,y,PW-MR,y)
        return y-0.20*inch

    y=header()
    for r in rows:
        if y<0.7*inch:
            c.showPage(); y=header()
        c.setFillColor(INK); c.setFont("Helvetica",9.5)
        c.drawString(ML,y,r["title"][:58])
        c.setFillColor(RED); c.setFont("Helvetica",8.5)
        c.drawRightString(PW-MR-1.35*inch,y,money(r["cur"]))
        wc=c.stringWidth(money(r["cur"]),"Helvetica",8.5)
        c.setStrokeColor(RED); c.setLineWidth(0.7); c.line(PW-MR-1.35*inch-wc,y+1.5,PW-MR-1.35*inch,y+1.5)
        c.setFillColor(GREEN); c.setFont("Helvetica-Bold",11)
        c.drawRightString(PW-MR-0.55*inch,y-1,money(r["rec"]))
        c.setFillColor(CONF.get(r.get("conf","low"),GREY)); c.setFont("Helvetica-Bold",7)
        c.drawRightString(PW-MR,y,str(r.get("conf","?")).upper()[:4])
        y-=0.165*inch
        c.setFillColor(HexColor("#aaaaaa")); c.setFont("Helvetica-Oblique",6.5)
        c.drawString(ML,y+0.02*inch,(r.get("note","") or "")[:92])
        y-=0.135*inch
        c.setStrokeColor(LINE); c.setLineWidth(0.4); c.line(ML,y+0.06*inch,PW-MR,y+0.06*inch)

    # totals
    if y<0.9*inch: c.showPage(); y=PH-1.4*inch
    y-=0.05*inch; c.setStrokeColor(INK); c.setLineWidth(1.1); c.line(ML,y+0.16*inch,PW-MR,y+0.16*inch)
    c.setFillColor(INK); c.setFont("Helvetica-Bold",11); c.drawString(ML,y,f"TOTAL ({len(rows)} cards)")
    c.setFillColor(RED); c.setFont("Helvetica",10); c.drawRightString(PW-MR-1.35*inch,y,money(tot_cur))
    c.setFillColor(GREEN); c.setFont("Helvetica-Bold",13); c.drawRightString(PW-MR-0.55*inch,y-1,money(tot_rec))
    c.setFillColor(GREY); c.setFont("Helvetica-Oblique",8)
    c.drawString(ML,0.5*inch,"CONF = comp confidence (HIGH solid solds · MED adjacent · LOW thin/estimate — eyeball LOW before entering). New 2025 product, comps thin.")
    c.showPage(); c.save()
    print(f"Wrote {OUT}  ({len(rows)} cards, {money(tot_cur)} -> {money(tot_rec)})")

if __name__=="__main__":
    main()
