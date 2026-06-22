"""build_engine_carousel.py — LinkedIn carousel PDF of the eBay automation engine.
Square slides, dark theme, factual (no hype). Color (screen/LinkedIn use)."""
from reportlab.lib.units import inch
from reportlab.lib.colors import HexColor
from reportlab.pdfgen import canvas
from pathlib import Path

OUT = Path(__file__).parent / "output/engine_linkedin.pdf"
S = 760  # square slide size in points
BG=HexColor("#0d0f13"); SURF=HexColor("#1b1f28"); BD=HexColor("#2a2f3a")
TX=HexColor("#e8eaee"); MUT=HexColor("#98a2b3"); AC=HexColor("#4a9eff"); OK=HexColor("#2ecc71"); PU=HexColor("#b07cff")
c = canvas.Canvas(str(OUT), pagesize=(S,S))
ML=56

def bgfill():
    c.setFillColor(BG); c.rect(0,0,S,S,fill=1,stroke=0)
def kicker(t,y):
    c.setFillColor(AC); c.setFont("Helvetica-Bold",13); c.drawString(ML,y,t.upper())
def title(t,y,size=34):
    c.setFillColor(TX); c.setFont("Helvetica-Bold",size); c.drawString(ML,y,t)
def foot(n):
    c.setFillColor(MUT); c.setFont("Helvetica",11)
    c.drawString(ML,40,"JC² Cards  ·  eBay automation engine")
    c.drawRightString(S-ML,40,f"{n}/6")
def chip(x,y,w,h,label,val,col=AC):
    c.setFillColor(SURF); c.setStrokeColor(BD); c.roundRect(x,y,w,h,10,fill=1,stroke=1)
    c.setFillColor(col); c.setFont("Helvetica-Bold",30); c.drawString(x+16,y+h-44,val)
    c.setFillColor(MUT); c.setFont("Helvetica",10.5); c.drawString(x+16,y+14,label.upper())

# ---- Slide 1: title + stats ----
bgfill()
c.setFillColor(AC); c.setFont("Helvetica-Bold",16); c.drawString(ML,S-70,"JC² CARDS")
title("An eBay selling engine",S-130,38); title("run by AI agents",S-176,38)
c.setFillColor(MUT); c.setFont("Helvetica",15)
c.drawString(ML,S-220,"Scans physical cards, identifies and prices them,")
c.drawString(ML,S-242,"lists them, and optimizes the catalog daily.")
w=(S-2*ML-3*14)/4
for i,(l,v,col) in enumerate([("Active listings","1,688",AC),("Inventory","$7.9k",AC),("Sold","217",OK),("Posted in a day","307",PU)]):
    chip(ML+i*(w+14),250,w,96,l,v,col)
c.setFillColor(TX); c.setFont("Helvetica",13)
c.drawString(ML,205,"Built and operated by one person, with a multi-agent assistant.")
foot(1); c.showPage()

# ---- Slide 2: pipeline ----
bgfill(); kicker("Core pipeline",S-64); title("Scan to listing,",S-110); title("no manual data entry",S-152)
steps=[("Scan","Nine cards per flatbed scan (a 3×3 grid)."),
 ("Grid split","Auto-cut into 9 images, snapping to the gaps so die-cuts aren't clipped."),
 ("Identify — agents","One agent per scan reads the images, returns year/brand/parallel/player/price as data. 17 scans read in parallel."),
 ("Dedup guard","Checks active + 90-day sold + within-batch. A 1-of-1 can never list twice."),
 ("Price","SportsCardsPro-anchored, confidence-gated; autos & rare parallels get a deep-dive."),
 ("Post","eBay Trading API, image upload, returns-not-accepted, dupe-checked at post time.")]
y=S-205
for i,(h,d) in enumerate(steps):
    c.setFillColor(SURF); c.setStrokeColor(BD); c.roundRect(ML,y-58,S-2*ML,52,9,fill=1,stroke=1)
    c.setFillColor(AC if i!=2 else PU); c.setFont("Helvetica-Bold",15); c.drawString(ML+16,y-26,f"{i+1}.  {h}")
    c.setFillColor(MUT); c.setFont("Helvetica",11.5); c.drawString(ML+16,y-44,d[:96])
    y-=64
foot(2); c.showPage()

# ---- Slide 3: morning routine ----
bgfill(); kicker("Daily automation",S-64); title("The morning routine",S-110)
c.setFillColor(MUT); c.setFont("Helvetica",13.5)
c.drawString(ML,S-145,"~25 agents run each morning. Every one produces a plan and a")
c.drawString(ML,S-165,"dashboard first; live actions are applied only after review.")
items=[("Repricing","Toward market, capped per run — trends down to move stock."),
 ("Markdowns","Age-tiered, floor-protected so nothing sells below its floor."),
 ("Promoted listings","Per-listing ad bids — the visibility lever."),
 ("Offers to watchers","Targeted discounts to the highest-intent buyers."),
 ("Best Offer","Re-clamps thresholds so a price drop never breaks a rule."),
 ("Health & digests","Inventory, photo audit, Cassini scoring, daily digest.")]
cw=(S-2*ML-14)/2; y=S-205
for i,(h,d) in enumerate(items):
    x=ML+(i%2)*(cw+14);
    if i%2==0 and i>0: y-=104
    yy=y-(0 if i%2==0 else 0)
    c.setFillColor(SURF); c.setStrokeColor(BD); c.roundRect(x,yy-92,cw,84,9,fill=1,stroke=1)
    c.setFillColor(TX); c.setFont("Helvetica-Bold",14); c.drawString(x+14,yy-30,h)
    c.setFillColor(MUT); c.setFont("Helvetica",10.5)
    words=d.split(); line=""; ly=yy-50
    for wd in words:
        if c.stringWidth(line+" "+wd,"Helvetica",10.5)>cw-28: c.drawString(x+14,ly,line); line=wd; ly-=14
        else: line=(line+" "+wd).strip()
    c.drawString(x+14,ly,line)
foot(3); c.showPage()

# ---- Slide 4: intelligence ----
bgfill(); kicker("Intelligence layer",S-64); title("More than a script",S-110)
rows=[("Sourcing committee","A panel of agent personas debates which players to buy next."),
 ("3-card lots","An expert committee bundles slow singles into themed lots, priced to move."),
 ("Premium deep-dive","Autos & rare parallels are verified and comp-priced individually."),
 ("Self-auditing review","Code changes reviewed by a 9-angle agent fan-out; each bug verified before fixing."),
 ("QC review page","Every posted card re-checked against its image with a confidence score."),
 ("Analytics","Titles parsed into fields for filterable insight on what's selling.")]
y=S-185
for h,d in rows:
    c.setFillColor(SURF); c.setStrokeColor(BD); c.roundRect(ML,y-58,S-2*ML,52,9,fill=1,stroke=1)
    c.setFillColor(PU); c.setFont("Helvetica-Bold",14); c.drawString(ML+16,y-26,h)
    c.setFillColor(MUT); c.setFont("Helvetica",11.5); c.drawString(ML+16,y-44,d[:94])
    y-=64
foot(4); c.showPage()

# ---- Slide 5: agent architecture ----
bgfill(); kicker("How the agents work",S-64); title("Fan out, verify,",S-110); title("synthesize",S-152)
pts=[("Fan-out","160 cards or 9 review angles run as parallel agents — wall-clock is the slowest one, not the sum."),
 ("Structured output","Agents return validated JSON (titles, prices, verdicts) that drops straight into the pipeline."),
 ("Adversarial verification","Findings and IDs are confirmed by separate agents — how mis-IDs get filtered out."),
 ("Committees","For judgment calls, agents argue distinct positions and a chair synthesizes the decision.")]
y=S-205
for h,d in pts:
    c.setFillColor(SURF); c.setStrokeColor(BD); c.roundRect(ML,y-74,S-2*ML,68,9,fill=1,stroke=1)
    c.setFillColor(AC); c.setFont("Helvetica-Bold",15); c.drawString(ML+16,y-28,h)
    c.setFillColor(MUT); c.setFont("Helvetica",11.5)
    words=d.split(); line=""; ly=y-48
    for wd in words:
        if c.stringWidth(line+" "+wd,"Helvetica",11.5)>S-2*ML-32: c.drawString(ML+16,ly,line); line=wd; ly-=15
        else: line=(line+" "+wd).strip()
    c.drawString(ML+16,ly,line)
    y-=86
foot(5); c.showPage()

# ---- Slide 6: stack / close ----
bgfill(); kicker("Built on",S-64); title("One repo, one operator",S-110)
c.setFillColor(MUT); c.setFont("Helvetica",13.5)
c.drawString(ML,S-150,"The only manual steps are scanning cards and approving")
c.drawString(ML,S-170,"the actions that touch live listings. Everything else is agents.")
chips=["Python","eBay Trading API","eBay Browse API","eBay Marketing API","SportsCardsPro",
 "PriceCharting","Multi-agent orchestration","OpenCV grid split","GitHub Pages"]
x=ML; y=S-220
for ch in chips:
    wsp=c.stringWidth(ch,"Helvetica",12)+28
    if x+wsp>S-ML: x=ML; y-=42
    c.setFillColor(SURF); c.setStrokeColor(BD); c.roundRect(x,y-26,wsp,30,15,fill=1,stroke=1)
    c.setFillColor(TX); c.setFont("Helvetica",12); c.drawString(x+14,y-17,ch)
    x+=wsp+10
c.setFillColor(TX); c.setFont("Helvetica-Bold",17); c.drawString(ML,150,"Jason Chletsos")
c.setFillColor(MUT); c.setFont("Helvetica",13); c.drawString(ML,126,"JC² Cards · built with a multi-agent assistant")
foot(6); c.showPage()
c.save()
print(f"wrote {OUT}")
