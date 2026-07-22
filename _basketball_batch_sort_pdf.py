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

NAME_WORD_RE = re.compile(r"[A-Za-z']+")
SUFFIXES = {"jr","sr","ii","iii","iv","v"}
def last_name_key(name):
    words = NAME_WORD_RE.findall(name)
    while words and words[-1].lower() in SUFFIXES:
        words.pop()
    return (words[-1].lower() if words else name.lower(), name.lower())
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
 "Held back — needs JC to locate the physical card": [
  ("Kevin Durant","Rockets base — sheet listed 1 for sale on top of the 2 KEEP copies, but no 3rd physical "
   "Durant appearance turned up anywhere in scans 433-450 during posting verification 2026-07-22 — dropped "
   "from the Rockets lot pending JC confirming which scan/card this actually is",1,3,5,""),
 ],
 "Scans 451-475 — remaining commons (approx., pending full team sort)": [
  ("Mixed base/Chrome cards","across Cavaliers, Suns, Grizzlies, Mavericks, Pistons, Wizards, Nuggets, Hawks, Heat, Nets, Rockets, Trail Blazers, Warriors, Bulls, Kings, Hornets, Pacers, Timberwolves, Magic, Raptors, Spurs, Jazz, Bucks, Pelicans (x199 copies)",1,2,3,"count is an estimate from this pass — will firm up to exact team lots once physically sorted, same as the rest of this project. NOT yet purged of team-duo/team-insert cards (unlike the itemized teams above) — this pile hasn't been individually sorted, so any team cards mixed in here still count toward the 199 for now."),
 ],
}

st=getSampleStyleSheet()
h1=ParagraphStyle("h1",parent=st["Title"],fontSize=21,spaceAfter=2,textColor=BLACK)
sub=ParagraphStyle("sub",parent=st["Normal"],fontSize=9.5,textColor=GRAY_MD,spaceAfter=10)
grp=ParagraphStyle("grp",parent=st["Heading2"],fontSize=12.5,textColor=BLACK,spaceBefore=11,spaceAfter=4)
note=ParagraphStyle("note",parent=st["Normal"],fontSize=8.5,textColor=GRAY_MD,spaceBefore=8)
cardp=ParagraphStyle("cardp",parent=st["Normal"],fontSize=10,leading=12,textColor=BLACK)

def money(x): return f"${x:,.2f}" if x%1 else f"${int(x)}"

def build(title, subtitle_extra, groups, out_path, verdict_html, alpha=False):
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
        if grp_name: flow.append(Paragraph(grp_name,grp))
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

    if alpha:
        flat = [c for cards in groups.values() for c in cards]
        flat.sort(key=lambda c: last_name_key(c[0]))
        tbl(None, flat)
    else:
        for grp_name,cards in groups.items(): tbl(grp_name,cards)
    doc.build(flow)
    dl=Path.home()/"Downloads"/out_path.name; shutil.copy(out_path,dl)
    return total_cards, grand

keep_out = Path("docs/basketball_keep.pdf")
sell_out = Path("docs/basketball_sell.pdf")

n_keep, g_keep = build(
    "Basketball keepers &mdash; personal collection",
    "&middot; Scans 433-475 &middot; A-Z by last name for easy physical pulling",
    KEEP, keep_out,
    "Kept per your criteria: Knicks, 76ers, LeBron, Giannis, and other notable/star players "
    "(Jokic, Wembanyama, Kawhi, Harden, Durant, DeRozan, Edwards, Haliburton, Adebayo, Trae Young, "
    "Klay Thompson, plus legends Magic Johnson/Dwyane Wade/Tracy McGrady/Kevin Garnett/Steve Kerr). "
    "<b>No Steph Curry card turned up in this batch</b> &mdash; nothing held back if one shows up later. "
    "Two calls worth double-checking: the Bucks 'Fear the Deer' team insert appears twice (confirm two "
    "real copies vs a re-scan), and I used a moderate bar for 'notable' &mdash; Cade Cunningham, Paolo "
    "Banchero, LaMelo Ball, Tyler Herro, Chet Holmgren, and Jamal Murray are all near-All-Star-caliber "
    "names I put in SELL by default since you didn't name them explicitly; flag any you want moved over. "
    "<b>Sorted A-Z by last name</b> below (team groupings dropped) to match a physical pull straight off "
    "an alphabetized stack &mdash; the handful of team-insert/duo cards (no single player name) sort by "
    "whatever word lands last, so double check those land where you'd expect.",
    alpha=True)

n_sell, g_sell = build(
    "Basketball sell/lots &mdash; sort by team",
    "&middot; Scans 433-475 &middot; Spurs&ndash;Rockets now LIVE (29 lots), only the 451-475 bulk pile left on HOLD",
    SELL, sell_out,
    "<b>POSTED 2026-07-22 (round 1):</b> Spurs through Miami Heat (22 lots/singles, 67 cards, $150.37). "
    "During crop verification, Trey Murphy III (a Pelicans player) was found miscategorized under the "
    "Grizzlies lot &mdash; moved into the Pelicans lot before posting. "
    "<b>POSTED 2026-07-22 (round 2):</b> Denver Nuggets through Houston Rockets (7 lots, 25 cards, $49.43) "
    "&mdash; JC physically confirmed Braun is 1 Chrome + 1 base (not 2 Chrome) and Watson is base (not "
    "Chrome), both already corrected below before this round. JC also flagged a Rockets card labeled base "
    "that was actually Chrome &mdash; that was Fred VanVleet (confirmed Topps Chrome by direct re-check of "
    "the scan); while on that same scan, Jalen Johnson (Hawks) was also found to be Chrome despite being "
    "labeled base, so that got corrected too. Immanuel Quickley (Raptors) was listed as 3 copies but only "
    "2 physical appearances could be found across every scan in this itemized batch (433-450) &mdash; posted "
    "as 2, flagged. Kevin Durant's Rockets \"base\" listing was dropped entirely &mdash; no 3rd physical "
    "Durant card turned up anywhere in scans 433-450 beyond the 2 already reserved for KEEP; see the held-back "
    "note at the top of the table below. "
    "<b>Sort verdict: lot material, organized by team for easy bundling.</b> Base 2025-26 Topps/Chrome "
    "commons run $1-4 raw even for current stars (confirmed via comps: LeBron $1.50-4, Giannis $0.99-2.24, "
    "Jokic $1.15-2, Kawhi/Harden $0.99-1.59) &mdash; nothing here individually clears a singles threshold. "
    "<b>Correction 2026-07-22:</b> the earlier note claiming Scan 436 and Scan 442 were a duplicate 9-card scan "
    "was wrong &mdash; re-verified all 15 original scans directly and that Sala&uuml;n/Washington/Ighodaro/Monk/"
    "Isaiah Joe/Agbaji/Watson/Bane/Isaiah Thomas set is really Scan 433, a single unique scan with no duplicate. "
    "Scans 436 and 442 are two other, different real scans (Kyrie/Garnett/Kerr/Durant/Castle and DeRozan/"
    "Haliburton/Kuminga respectively). Quantities have been corrected accordingly (Isaiah Thomas x2, Nembhard x3, "
    "Ighodaro x3, Peyton Watson x2 base &mdash; not Chrome as first labeled). Team groups with 6+ cards "
    "(Pistons, Pacers, Grizzlies, Mavericks, Raptors) split cleanly into two 5-card-or-fewer lots each. "
    "<b>Scans 451-475 (~199 cards) are counted as one estimated bulk line for now</b> rather than itemized "
    "by team &mdash; that batch was large enough that a card-by-card team re-sort will follow once it's "
    "physically organized; the running total already reflects the full count. "
    "<b>Team/multi-player insert cards (duo inserts, team celebration cards) have been pulled OUT of every "
    "lot below</b> per JC's call &mdash; he's setting those aside to decide on separately later, so they no "
    "longer count toward any team's lot total or this sheet's grand total.")

json.dump({"keep":{"count":n_keep,"total":g_keep},"sell":{"count":n_sell,"total":g_sell}},
          open("output/_basketball_batch.json","w"), indent=1)

print(f"KEEP: {n_keep} cards · ${g_keep['low']:.0f}-{g_keep['high']:.0f} (typ ${g_keep['typical']:.0f}) -> {keep_out}")
print(f"SELL: {n_sell} cards · ${g_sell['low']:.0f}-{g_sell['high']:.0f} (typ ${g_sell['typical']:.0f}) -> {sell_out}")
