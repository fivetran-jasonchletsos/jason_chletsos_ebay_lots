"""Basketball batch sort/valuation — Scans 433-475 (~360 cards, 2025-26 Topps/Chrome).
Splits into KEEP (Knicks, 76ers, LeBron, Giannis, and other notable/star players per
JC's criteria) vs SELL (lots + individuals). Raw/ungraded July 2026 eBay-comp estimates.
Black-and-white print. HOLD — not for posting. More scans to come.
Writes docs/basketball_keep.pdf + docs/basketball_sell.pdf (+ ~/Downloads) and
output/_basketball_batch.json.
"""
import json, re, shutil
from pathlib import Path

QTY_RE = re.compile(r"x(\d+)\s*cop(?:y|ies)", re.IGNORECASE)
def qty_of(variant):
    m = QTY_RE.search(variant)
    return int(m.group(1)) if m else 1
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

GRAY_DK = colors.HexColor("#222222")
GRAY_MD = colors.HexColor("#555555")
GRAY_LT = colors.HexColor("#e8e8e8")
BLACK = colors.black
WHITE = colors.white

# (name, variant/note, low, typ, high, note)
KEEP = {
 "New York Knicks": [
  ("Carmelo Anthony","Knicks legend insert",2,4,7,""),
  ("OG Anunoby","Knicks base",1,3,5,""),
  ("Tyler Kolek","Knicks base RC",1,2,4,""),
 ],
 "Philadelphia 76ers": [
  ("Philly Tough (76ers duo insert)","Maxey/Embiid-era duo",1,3,5,""),
  ("Kelly Oubre Jr.","76ers base",1,2,4,""),
 ],
 "LeBron James": [
  ("LeBron James","Lakers base",1,3,5,""),
 ],
 "Giannis Antetokounmpo": [
  ("Giannis Antetokounmpo","Bucks base",1,3,5,""),
  ("Bucks 'Fear the Deer' team insert (copy 1)","features Giannis",1,2,4,""),
  ("Bucks 'Fear the Deer' team insert (copy 2)","features Giannis, 2nd copy — confirm not a dupe scan",1,2,4,"check vs copy 1"),
 ],
 "Other notable players/legends": [
  ("Victor Wembanyama / De'Aaron Fox duo insert","Spurs/Kings",2,4,7,""),
  ("Nikola Jokic","Nuggets base (copy 1)",1,3,5,""),
  ("Nikola Jokic","Nuggets base (copy 2)",1,3,5,""),
  ("Denver 'Championship Duo' insert (Jokic/Murray)","Nuggets",1,3,5,""),
  ("Anthony Edwards","Timberwolves Chrome",1,3,5,""),
  ("Kawhi Leonard","Clippers base (copy 1)",1,2,4,""),
  ("Kawhi Leonard","Clippers base (copy 2)",1,2,4,""),
  ("James Harden","Clippers base",1,2,4,""),
  ("Tracy McGrady","Rockets legend insert",2,4,7,""),
  ("Magic Johnson","Lakers legend insert",2,5,8,""),
  ("DeMar DeRozan","Kings base (copy 1)",1,2,4,""),
  ("DeMar DeRozan","Kings base (copy 2)",1,2,4,""),
  ("DeMar DeRozan","Kings base (copy 3)",1,2,4,""),
  ("Bam Adebayo","Heat base",1,2,4,""),
  ("Trae Young","Hawks base",1,3,5,""),
  ("Klay Thompson","Mavericks base",1,3,5,""),
  ("Dwyane Wade","Heat legend insert",2,5,8,""),
  ("Tyrese Haliburton","Pacers base (x2 copies)",1,2,4,""),
 ],
 "Scans 451-475 additions": [
  ("Karl-Anthony Towns","Knicks base",1,2,4,""),
  ("Jalen Brunson","Knicks base",1,3,5,""),
  ("Josh Hart","Knicks base (x2 copies)",1,2,3,""),
  ("Mikal Bridges","Knicks base",1,2,4,""),
  ("Miles McBride","Knicks base (x2 copies)",1,2,3,""),
  ("OG Anunoby","Knicks base (2nd copy, see earlier group)",1,3,5,""),
  ("Bam Adebayo","Heat base (2nd copy)",1,2,4,""),
  ("Nikola Jokic","Nuggets 'Championship Duo' insert (2nd copy) + Allen & Ginter throwback",1,3,5,""),
  ("Kevin Durant","Rockets base (x2 copies)",1,3,5,""),
  ("Kevin Garnett","Timberwolves legend base (2nd copy)",2,4,6,""),
  ("Klay Thompson","Mavericks base (2nd copy)",1,3,5,""),
  ("Victor Wembanyama","Spurs solo base (Chrome)",2,5,9,""),
  ("Dirk Nowitzki","Mavericks legend base",2,4,7,""),
  ("Bill Russell","Celtics legend base",2,5,8,""),
  ("Rick Barry","Warriors legend base",2,4,6,""),
  ("Steve Kerr","Spurs legend base",1,2,4,""),
  ("Ja Morant","Grizzlies base (x2 copies)",1,3,5,""),
  ("Domantas Sabonis","Kings base",1,2,4,""),
  ("Donovan Mitchell","Cavaliers base",1,2,4,""),
  ("Jrue Holiday","Celtics base",1,2,4,""),
  ("Russell Westbrook","Nuggets base",1,2,4,""),
  ("Devin Booker","Suns base",1,3,5,""),
 ],
}

SELL = {
 "San Antonio Spurs": [
  ("Jeremy Sochan","base (x2 copies)",1,2,3,""),
  ("Harrison Barnes","Chrome",1,2,3,""),
  ("Stephon Castle","Chrome",1,2,4,""),
  ("Chris Paul","base",1,3,5,""),
  ("Steve Kerr","legend/player-era insert",1,2,4,""),
 ],
 "LA Clippers": [
  ("Norman Powell","base (x3 copies)",1,2,3,""),
  ("Derrick Jones Jr.","base",1,2,3,""),
 ],
 "Detroit Pistons": [
  ("Cade Cunningham","base (x2 copies)",1,3,5,""),
  ("Isaiah Thomas","base",1,2,3,""),
  ("Jaden Ivey","base (x2 copies)",1,2,3,""),
  ("Jalen Duren","base",1,2,3,""),
 ],
 "Brooklyn Nets": [
  ("Nic Claxton","base",1,2,3,""),
 ],
 "Boston Celtics": [
  ("Kristaps Porzingis","base",1,2,4,""),
  ("Celtics duo insert","team card",1,2,3,""),
 ],
 "Chicago Bulls": [
  ("Coby White","base (x3 copies)",1,2,3,""),
  ("Windy City Wonder (Bulls duo insert)","Giddey/Vucevic",1,2,3,""),
  ("Josh Giddey","base",1,2,4,""),
  ("Lonzo Ball","base",1,2,3,""),
  ("Patrick Williams","base",1,2,3,""),
 ],
 "OKC Thunder": [
  ("Isaiah Hartenstein","base (x2 copies)",1,2,3,""),
  ("Aaron Wiggins","Chrome",1,2,3,""),
  ("Chet Holmgren","base",1,3,5,""),
  ("Isaiah Joe","base",1,2,3,""),
 ],
 "Washington Wizards": [
  ("DC Duo Dazzles insert","Wizards team card",1,2,3,""),
  ("Bilal Coulibaly","base (x2 copies)",1,2,3,""),
  ("Richaun Holmes","Chrome",1,2,3,""),
  ("Alex Sarr","base",1,2,4,""),
 ],
 "Orlando Magic": [
  ("Anthony Black","base (x2 copies)",1,2,3,""),
  ("Paolo Banchero","base",1,3,5,""),
 ],
 "Portland Trail Blazers": [
  ("POR duo insert (Rip City Duo)","team card (x4 copies)",1,2,3,""),
  ("Deni Avdija","base",1,2,4,""),
 ],
 "Cleveland Cavaliers": [
  ("Evan Mobley","Chrome",1,3,5,""),
  ("Darius Garland","base",1,2,4,""),
  ("Ty Jerome","base",1,2,3,""),
 ],
 "New Orleans Pelicans": [
  ("Yves Missi","base",1,2,3,""),
  ("Herbert Jones","base",1,2,3,""),
 ],
 "Minnesota Timberwolves": [
  ("Naz Reid","base (x3 copies)",1,2,3,""),
  ("Kevin Garnett","legend insert",2,4,6,""),
 ],
 "Indiana Pacers": [
  ("TJ McConnell","Chrome",1,2,3,""),
  ("Bennedict Mathurin","Chrome",1,2,4,""),
  ("Andrew Nembhard","base (x4 copies)",1,2,3,""),
  ("Obi Toppin","base",1,2,3,""),
 ],
 "Charlotte Hornets": [
  ("LaMelo Ball","base + Chrome (x2 copies)",1,3,5,""),
  ("Tidjane Salaun","base",1,2,3,""),
 ],
 "Golden State Warriors": [
  ("Quinten Post","base",1,2,3,""),
  ("Jonathan Kuminga","base",1,2,4,""),
 ],
 "Memphis Grizzlies": [
  ("Desmond Bane","base + Chrome (x3 copies)",1,2,4,""),
  ("Jaren Jackson Jr.","Chrome",1,2,4,""),
  ("Trey Murphy III","Chrome",1,2,3,""),
  ("Grizzlies 'Grit and Grind' duo insert","team card",1,2,3,""),
 ],
 "Miami Heat": [
  ("Tyler Herro","base",1,3,5,""),
  ("Jaime Jaquez Jr.","base + Chrome (x2 copies)",1,2,3,""),
  ("Bam Adebayo","base",1,2,4,""),
 ],
 "Denver Nuggets": [
  ("Jamal Murray","base",1,2,4,""),
  ("Christian Braun","Chrome (x2 copies)",1,2,3,""),
  ("Peyton Watson","Chrome",1,2,3,""),
 ],
 "Phoenix Suns": [
  ("Oso Ighodaro","base + Chrome (x2 copies)",1,2,3,""),
  ("Grayson Allen","base",1,2,3,""),
 ],
 "Dallas Mavericks": [
  ("Max Christie","base",1,2,3,""),
  ("Kyrie Irving","base",1,3,5,""),
  ("PJ Washington Jr.","base",1,2,3,""),
  ("Brandon Williams","base",1,2,3,""),
  ("Mavericks duo insert","team card",1,2,3,""),
 ],
 "Toronto Raptors": [
  ("Ochai Agbaji","base (x2 copies)",1,2,3,""),
  ("Immanuel Quickley","base (x3 copies)",1,2,4,""),
  ("Gradey Dick","base",1,2,4,""),
  ("Raptors duo insert","team card",1,2,3,""),
 ],
 "Sacramento Kings": [
  ("Malik Monk","base",1,2,3,""),
  ("Zach LaVine","Chrome",1,2,4,""),
 ],
 "Atlanta Hawks": [
  ("Spud Webb","legend base",1,2,4,""),
  ("Jalen Johnson","base",1,2,4,""),
  ("Clint Capela","base",1,2,3,""),
  ("Hawks 'Ballers Show Out' duo insert","team card",1,2,3,""),
 ],
 "Houston Rockets": [
  ("Fred VanVleet","base",1,2,4,""),
  ("Jabari Smith Jr.","base",1,2,4,""),
  ("Kevin Durant","base",1,3,5,""),
 ],
 "Scans 451-475 — remaining commons (approx., pending full team sort)": [
  ("Mixed base/Chrome/team-insert cards","~199 cards across Cavaliers, Suns, Grizzlies, Mavericks, Pistons, Wizards, Nuggets, Hawks, Heat, Nets, Rockets, Trail Blazers, Warriors, Bulls, Kings, Hornets, Pacers, Timberwolves, Magic, Raptors, Spurs, Jazz, Bucks, Pelicans, plus assorted team-duo insert cards (x199 copies)",1,2,3,"count is an estimate from this pass — will firm up to exact team lots once physically sorted, same as the rest of this project"),
 ],
}

st=getSampleStyleSheet()
h1=ParagraphStyle("h1",parent=st["Title"],fontSize=21,spaceAfter=2,textColor=BLACK)
sub=ParagraphStyle("sub",parent=st["Normal"],fontSize=9.5,textColor=GRAY_MD,spaceAfter=10)
grp=ParagraphStyle("grp",parent=st["Heading2"],fontSize=12.5,textColor=BLACK,spaceBefore=11,spaceAfter=4)
note=ParagraphStyle("note",parent=st["Normal"],fontSize=8.5,textColor=GRAY_MD,spaceBefore=8)
cardp=ParagraphStyle("cardp",parent=st["Normal"],fontSize=10,leading=12,textColor=BLACK)

def money(x): return f"${x:,.2f}" if x%1 else f"${int(x)}"

def build(title, subtitle_extra, groups, out_path, verdict_html):
    all_rows=[]
    total_cards=0
    for grp_name,cards in groups.items():
        for n,v,lo,ty,hi,nt in cards:
            q = qty_of(v)
            total_cards += q
            all_rows.append({"group":grp_name,"card":n,"variant":v,"qty":q,
                              "low":lo,"typical":ty,"high":hi,"note":nt,
                              "low_tot":lo*q,"typical_tot":ty*q,"high_tot":hi*q})
    tot=lambda k: round(sum(r[k] for r in all_rows),2)
    grand={k:tot(f"{k}_tot") for k in ("low","typical","high")}

    doc=SimpleDocTemplate(str(out_path),pagesize=letter,topMargin=.55*inch,bottomMargin=.55*inch,leftMargin=.6*inch,rightMargin=.6*inch)
    flow=[Paragraph(title,h1),
          Paragraph(f"{total_cards} cards {subtitle_extra} &middot; raw/ungraded July 2026 eBay-comp estimate",sub),
          Paragraph(f"<b>Total: {money(grand['low'])} &ndash; {money(grand['high'])}</b> "
                    f"(typical ~{money(grand['typical'])})",grp),
          Paragraph(verdict_html,note)]

    def tbl(grp_name,cards):
        flow.append(Paragraph(grp_name,grp))
        sub_ty=round(sum(c[3]*qty_of(c[1]) for c in cards),2)
        data=[["", "Card", "Variant", "Qty", "Low ea", "Typ ea", "High ea"]]
        for n,v,lo,ty,hi,nt in cards:
            q = qty_of(v)
            cardcell=f"<b>{n}</b>"
            vv=v + (f" &middot; <i>{nt}</i>" if nt else "")
            data.append(["☐", Paragraph(cardcell,cardp), Paragraph(f"<font size=8.5>{vv}</font>",cardp),
                         str(q), money(lo),money(ty),money(hi)])
        data.append(["","",Paragraph("<b>group typical</b>",cardp),"","","",Paragraph(f"<b>{money(sub_ty)}</b>",cardp)])
        t=Table(data,colWidths=[0.24*inch,1.4*inch,2.8*inch,0.4*inch,0.55*inch,0.55*inch,0.6*inch])
        t.setStyle(TableStyle([("FONTSIZE",(0,0),(-1,-1),9),("FONTNAME",(0,0),(-1,0),"Helvetica-Bold"),
            ("BACKGROUND",(0,0),(-1,0),GRAY_DK),("TEXTCOLOR",(0,0),(-1,0),WHITE),
            ("ROWBACKGROUNDS",(0,1),(-1,-2),[WHITE,GRAY_LT]),
            ("ALIGN",(3,0),(-1,-1),"RIGHT"),("ALIGN",(0,0),(0,-1),"CENTER"),("FONTSIZE",(0,1),(0,-1),13),
            ("VALIGN",(0,0),(-1,-1),"MIDDLE"),("LINEABOVE",(0,-1),(-1,-1),0.6,GRAY_DK),
            ("GRID",(0,0),(-1,-2),.4,GRAY_MD),("TOPPADDING",(0,0),(-1,-1),3.5),("BOTTOMPADDING",(0,0),(-1,-1),3.5)]))
        flow.append(t)

    for grp_name,cards in groups.items(): tbl(grp_name,cards)
    doc.build(flow)
    dl=Path.home()/"Downloads"/out_path.name; shutil.copy(out_path,dl)
    return total_cards, grand

keep_out = Path("docs/basketball_keep.pdf")
sell_out = Path("docs/basketball_sell.pdf")

n_keep, g_keep = build(
    "Basketball keepers &mdash; personal collection",
    "&middot; Scans 433-475",
    KEEP, keep_out,
    "Kept per your criteria: Knicks, 76ers, LeBron, Giannis, and other notable/star players "
    "(Jokic, Wembanyama, Kawhi, Harden, Durant, DeRozan, Edwards, Haliburton, Adebayo, Trae Young, "
    "Klay Thompson, plus legends Magic Johnson/Dwyane Wade/Tracy McGrady/Kevin Garnett/Steve Kerr). "
    "<b>No Steph Curry card turned up in this batch</b> &mdash; nothing held back if one shows up later. "
    "Two calls worth double-checking: the Bucks 'Fear the Deer' team insert appears twice (confirm two "
    "real copies vs a re-scan), and I used a moderate bar for 'notable' &mdash; Cade Cunningham, Paolo "
    "Banchero, LaMelo Ball, Tyler Herro, Chet Holmgren, and Jamal Murray are all near-All-Star-caliber "
    "names I put in SELL by default since you didn't name them explicitly; flag any you want moved over.")

n_sell, g_sell = build(
    "Basketball sell/lots &mdash; sort by team",
    "&middot; Scans 433-475 &middot; HOLD, not posted",
    SELL, sell_out,
    "<b>Sort verdict: lot material, organized by team for easy bundling.</b> Base 2025-26 Topps/Chrome "
    "commons run $1-4 raw even for current stars (confirmed via comps: LeBron $1.50-4, Giannis $0.99-2.24, "
    "Jokic $1.15-2, Kawhi/Harden $0.99-1.59) &mdash; nothing here individually clears a singles threshold. "
    "Confirmed duplicate: <b>Scan 436 and Scan 442 were the same 9-card scan taken twice</b> "
    "(Tidjane Sala&uuml;n, PJ Washington Jr., Ighodaro, Monk, Isaiah Joe, Agbaji, Watson, Bane, Isaiah Thomas) "
    "&mdash; the extra copy from each has been removed from this total. Team groups with 6+ cards "
    "(Pistons, Pacers, Grizzlies, Mavericks, Raptors) split cleanly into two 5-card-or-fewer lots each. "
    "<b>Scans 451-475 (~199 cards) are counted as one estimated bulk line for now</b> rather than itemized "
    "by team &mdash; that batch was large enough that a card-by-card team re-sort will follow once it's "
    "physically organized; the running total already reflects the full count. HOLD: nothing posted, more scans pending.")

json.dump({"keep":{"count":n_keep,"total":g_keep},"sell":{"count":n_sell,"total":g_sell}},
          open("output/_basketball_batch.json","w"), indent=1)

print(f"KEEP: {n_keep} cards · ${g_keep['low']:.0f}-{g_keep['high']:.0f} (typ ${g_keep['typical']:.0f}) -> {keep_out}")
print(f"SELL: {n_sell} cards · ${g_sell['low']:.0f}-{g_sell['high']:.0f} (typ ${g_sell['typical']:.0f}) -> {sell_out}")
