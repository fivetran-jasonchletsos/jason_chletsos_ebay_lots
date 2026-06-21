"""build_stats_page.py — interactive analytics dashboard for JC2 Cards.

Parses every active listing (output/listings_snapshot.json) and sold card
(sold_history.json) title into structured fields (year, brand, player, team,
parallel/insert, RC, numbered), embeds the dataset, and renders a self-contained
filterable page: KPIs + top-10 charts (players by count & value, brand, year,
team, parallel) + a live-filtered table. No external CDN — pure CSS bars.
"""
import json, re, html
from pathlib import Path

REPO = Path(__file__).parent
snap = json.loads((REPO / "output/listings_snapshot.json").read_text())
active = snap.get("listings", snap) if isinstance(snap, dict) else snap
sold = json.loads((REPO / "sold_history.json").read_text())
try:
    KNOWN = json.loads((REPO / "output/known_players.json").read_text())
except Exception:
    KNOWN = []

# Broaden the player roster with common names so parsing has good coverage
KNOWN = list(set(KNOWN + [
    "Travis Hunter","Cam Ward","Ashton Jeanty","Jayden Daniels","Caleb Williams",
    "Patrick Mahomes II","Patrick Mahomes","Josh Allen","Lamar Jackson","Joe Burrow",
    "Justin Jefferson","Ja'Marr Chase","CeeDee Lamb","Puka Nacua","Justin Herbert",
    "Jahmyr Gibbs","Brock Bowers","Sam LaPorta","De'Von Achane","Amon-Ra St. Brown",
    "Ladd McConkey","Jaxon Smith-Njigba","Trey McBride","Nico Collins","Drake Maye",
    "Bo Nix","Tetairoa McMillan","Emeka Egbuka","Matthew Golden","Shedeur Sanders",
    "Tyler Warren","Mykel Williams","Will Johnson","Dillon Gabriel","Bijan Robinson",
    "Saquon Barkley","Derrick Henry","Tyreek Hill","Jaylen Waddle","Brian Thomas Jr.",
    "Brian Thomas","C.J. Stroud","CJ Stroud","Bryce Young","Marvin Harrison Jr.",
    "Marvin Harrison","Jonathan Taylor","Rome Odunze","Brock Purdy","Quinn Ewers",
    "Kyle Williams","Jack Bech","Mason Taylor","George Kittle","Jordan Love",
    "Dak Prescott","Trevor Lawrence","Aaron Rodgers","Tyler Shough","Devin Neal",
    "Omarion Hampton","Patrick Surtain II","Daniel Jones","Aidan Hutchinson",
    "Keon Coleman","Luther Burden III","Tate Ratledge","Will Howard","Jalen Milroe",
    "Khalil Mack","Asante Samuel Jr.","Rashee Rice","Colston Loveland","Isaac TeSlaa",
    "Antwaun Powell-Ryland","Chris Olave","Tyler Warren","Myles Garrett",
]))
KNOWN.sort(key=len, reverse=True)

BRANDS = [  # order matters: most specific first
    ("signature class", "Topps Signature Class"), ("topps chrome", "Topps Chrome"),
    ("topps cosmic", "Topps Cosmic"), ("topps iconic", "Topps Iconic"),
    ("topps finest", "Topps Finest"), ("topps total", "Topps Total"),
    ("totally certified", "Totally Certified"), ("bowman", "Bowman"),
    ("topps", "Topps"), ("prizm draft", "Prizm Draft"), ("prizm", "Prizm"),
    ("donruss optic", "Donruss Optic"), ("optic", "Donruss Optic"),
    ("mosaic", "Mosaic"), ("select", "Select"), ("donruss", "Donruss"),
    ("contenders", "Contenders"), ("absolute", "Absolute"), ("phoenix", "Phoenix"),
    ("revolution", "Revolution"), ("chronicles", "Chronicles"), ("score", "Score"),
    ("prestige", "Prestige"), ("obsidian", "Obsidian"), ("illusions", "Illusions"),
    ("certified", "Certified"), ("rookies & stars", "Rookies & Stars"),
    ("rookies and stars", "Rookies & Stars"), ("panini", "Panini (other)"),
]
TEAMS = ["49ers","Bears","Bengals","Bills","Broncos","Browns","Buccaneers","Cardinals",
    "Chargers","Chiefs","Colts","Commanders","Cowboys","Dolphins","Eagles","Falcons",
    "Giants","Jaguars","Jets","Lions","Packers","Panthers","Patriots","Raiders","Rams",
    "Ravens","Saints","Seahawks","Steelers","Texans","Titans","Vikings"]
PARALLELS = ["silver","gold","orange","pink","green","red","blue","purple","teal","bronze",
    "copper","black","white","aqua","lime","yellow","neon","camo","tie-dye","lava",
    "fluorescent","snakeskin","cracked ice","prizmatic","wave","disco","scope","hyper",
    "velocity","shimmer","mojo","flash","die-cut","refractor","xfractor","x-fractor",
    "checkerboard","tri-color","lazer","pulsar"]
INSERTS = ["turbocharged","numbers","future","thunderbirds","touchdown masters","contours",
    "notoriety","paragon","epic performers","players","celebration","league leaders",
    "round 1 pick","round 2 pick","round pick","class action","class icons","new wave",
    "stargazing","sunday showcase","throwbacks","hidden potential","elevate","play action"]

_STOP = set(w.lower() for w in (
    [t for _,t in BRANDS] + TEAMS + ["Football","Panini","Topps","RC","Rookie","Insert",
    "Parallel","Prizm","Select","Donruss","Optic","Mosaic","Phoenix","Score","Revolution",
    "Chronicles","Absolute","Contenders","Bowman","Chrome","Cosmic","Iconic","Finest","Total",
    "Signature","Class","Certified","Prestige","Obsidian","Draft","Picks","NFL","The","And",
    "Wide","Receiver","Running","Back","Quarterback","Tight","End","QB","WR","RB","TE","CB",
    "Los","Angeles","New","York","San","Francisco","Tampa","Bay","Green","Kansas","City",
    "Las","Vegas","Trojans","Wolverines"] + [p for p in PARALLELS] + [w for i in INSERTS for w in i.split()]))

def _residual_name(t):
    # strip year, serials, card numbers, then keep Capitalized word runs not in stoplist
    s = re.sub(r"\b20\d{2}\b", " ", t)
    s = re.sub(r"\d+\s*/\s*\d+", " ", s); s = re.sub(r"#\s*[\w-]+", " ", s)
    s = re.sub(r"[^A-Za-z'.\- ]", " ", s)
    run = []
    for w in s.split():
        base = w.strip(".'-")
        if base and base[0].isupper() and base.lower() not in _STOP and len(base) > 1:
            run.append(w)
            if len(run) >= 3: break
        elif run:
            break
    name = " ".join(run).strip(" -.'")
    return name if 2 <= len(name) <= 28 and " " in name else ""

def parse(title):
    t = title or ""; tl = t.lower()
    ym = re.search(r"\b(20\d{2})\b", t); year = ym.group(1) if ym else ""
    brand = next((lbl for tok,lbl in BRANDS if tok in tl), "Other")
    player = next((n for n in KNOWN if n.lower() in tl), "")
    player = {"CJ Stroud":"C.J. Stroud","Patrick Mahomes":"Patrick Mahomes II",
              "Brian Thomas":"Brian Thomas Jr.","Marvin Harrison":"Marvin Harrison Jr."}.get(player, player)
    if not player:
        player = _residual_name(t)
    team = next((tm for tm in TEAMS if re.search(rf"\b{tm.lower()}\b", tl)), "")
    par = next((p.title() for p in PARALLELS if p in tl), "")
    ins = next((i.title() for i in INSERTS if i in tl), "")
    rc = bool(re.search(r"\brc\b|\brookie\b", tl))
    numbered = bool(re.search(r"\d+\s*/\s*\d+", t))
    return {"year":year,"brand":brand,"player":player or "(unmatched)","team":team or "(none)",
            "parallel":par or ("Base" if not ins else ""),"insert":ins or "(none)",
            "rc":rc,"numbered":numbered}

rows = []
for l in active:
    p = parse(l.get("title",""))
    rows.append({**p, "src":"active","title":l.get("title",""),"price":float(l.get("price") or 0),
                 "item_id":str(l.get("item_id","")),"date":""})
for s in sold:
    p = parse(s.get("title",""))
    rows.append({**p, "src":"sold","title":s.get("title",""),"price":float(s.get("sale_price") or 0),
                 "item_id":str(s.get("item_id","")),"date":(s.get("sold_date","") or "")[:10]})

DATA = json.dumps(rows)
a_n = sum(1 for r in rows if r["src"]=="active"); a_v = sum(r["price"] for r in rows if r["src"]=="active")
s_n = sum(1 for r in rows if r["src"]=="sold");   s_v = sum(r["price"] for r in rows if r["src"]=="sold")

CSS = """
:root{--bg:#0f1115;--surf:#1a1d24;--surf2:#222630;--bd:#2c313c;--tx:#e6e8ec;--mut:#9aa3b0;--ac:#4a9eff;--ok:#2ecc71;--gd:#f1c40f}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--tx);font:14px/1.45 -apple-system,Segoe UI,Roboto,sans-serif}
header{padding:16px 22px;background:var(--surf);border-bottom:1px solid var(--bd);position:sticky;top:0;z-index:10}
h1{font-size:18px;margin:0 0 3px}.sub{color:var(--mut);font-size:12.5px}
.kpis{display:flex;gap:12px;flex-wrap:wrap;margin-top:12px}
.kpi{background:var(--surf2);border:1px solid var(--bd);border-radius:10px;padding:10px 16px;min-width:120px}
.kpi .v{font-size:22px;font-weight:800}.kpi .l{font-size:11px;color:var(--mut);text-transform:uppercase;letter-spacing:.04em}
.kpi.act .v{color:var(--ac)}.kpi.sold .v{color:var(--ok)}
.bar{display:flex;gap:8px;flex-wrap:wrap;align-items:center;padding:12px 22px;background:var(--surf);border-bottom:1px solid var(--bd)}
.bar select,.bar input{background:var(--surf2);color:var(--tx);border:1px solid var(--bd);border-radius:7px;padding:6px 9px;font-size:13px}
.bar label{font-size:11px;color:var(--mut);display:flex;flex-direction:column;gap:3px}
.bar .chk{flex-direction:row;align-items:center;gap:5px;margin-top:14px}
#reset{background:var(--ac);color:#fff;border:none;border-radius:7px;padding:7px 12px;cursor:pointer;margin-top:14px;font-weight:600}
.wrap{padding:18px 22px 60px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:16px}
.card{background:var(--surf);border:1px solid var(--bd);border-radius:12px;padding:14px 16px}
.card h3{margin:0 0 12px;font-size:13.5px;color:var(--tx)}
.rowb{display:grid;grid-template-columns:120px 1fr 64px;align-items:center;gap:8px;margin-bottom:7px;font-size:12.5px}
.rowb .nm{color:var(--tx);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.rowb .track{background:var(--surf2);border-radius:5px;height:16px;overflow:hidden}
.rowb .fill{height:100%;background:linear-gradient(90deg,var(--ac),#6db3ff);border-radius:5px}
.rowb.val .fill{background:linear-gradient(90deg,var(--ok),#5bdc8a)}
.rowb .amt{text-align:right;color:var(--mut);font-variant-numeric:tabular-nums}
table{width:100%;border-collapse:collapse;font-size:12.5px;margin-top:6px}
th,td{text-align:left;padding:6px 8px;border-bottom:1px solid var(--bd)}
th{color:var(--mut);font-weight:600;cursor:pointer;position:sticky;top:0;background:var(--surf)}
td.num,th.num{text-align:right;font-variant-numeric:tabular-nums}
.tag{font-size:10px;padding:1px 6px;border-radius:4px;background:var(--surf2);color:var(--mut)}
.tag.sold{background:rgba(46,204,113,.15);color:var(--ok)}.tag.active{background:rgba(74,158,255,.15);color:var(--ac)}
#tablewrap{max-height:560px;overflow:auto;margin-top:8px}
#count{color:var(--mut);font-size:12px;margin:10px 0 0}
"""

JS = r"""
const DATA = __DATA__;
const $ = s => document.querySelector(s);
const uniq = (k) => [...new Set(DATA.map(r=>r[k]).filter(v=>v!==''&&v!=null))].sort();
function fill(sel, vals, label){ const e=$(sel); e.innerHTML='<option value="">'+label+'</option>'+vals.map(v=>`<option>${v}</option>`).join(''); }
fill('#fbrand', uniq('brand'),'All brands'); fill('#fyear', uniq('year'),'All years');
fill('#fteam', uniq('team'),'All teams'); fill('#fpar', uniq('parallel'),'All parallels');
fill('#fins', uniq('insert'),'All inserts');

function filtered(){
  const src=$('#fsrc').value, b=$('#fbrand').value, y=$('#fyear').value, tm=$('#fteam').value,
        pa=$('#fpar').value, ins=$('#fins').value, q=$('#fq').value.toLowerCase().trim(),
        rc=$('#frc').checked, num=$('#fnum').checked;
  return DATA.filter(r=>{
    if(src&&r.src!==src)return false; if(b&&r.brand!==b)return false; if(y&&r.year!==y)return false;
    if(tm&&r.team!==tm)return false; if(pa&&r.parallel!==pa)return false; if(ins&&r.insert!==ins)return false;
    if(rc&&!r.rc)return false; if(num&&!r.numbered)return false;
    if(q&&!(r.player.toLowerCase().includes(q)||r.title.toLowerCase().includes(q)))return false;
    return true;
  });
}
function agg(rows,key){ const m={}; rows.forEach(r=>{const k=r[key]||'(none)'; m[k]=m[k]||{n:0,v:0}; m[k].n++; m[k].v+=r.price;}); return m; }
function bars(sel,rows,key,mode,n){
  const m=agg(rows,key); let arr=Object.entries(m).map(([k,o])=>({k,n:o.n,v:o.v}));
  arr.sort((a,b)=> mode==='v'? b.v-a.v : b.n-a.n); arr=arr.slice(0,n||10);
  const max=Math.max(1,...arr.map(x=>mode==='v'?x.v:x.n));
  $(sel).innerHTML=arr.map(x=>{
    const val=mode==='v'?x.v:x.n; const w=(val/max*100).toFixed(1);
    const disp=mode==='v'?('$'+x.v.toFixed(0)):x.n;
    return `<div class="rowb ${mode==='v'?'val':''}"><div class="nm" title="${x.k}">${x.k}</div>
      <div class="track"><div class="fill" style="width:${w}%"></div></div><div class="amt">${disp}</div></div>`;
  }).join('') || '<div class="sub">no data</div>';
}
let sortKey='price', sortDir=-1;
function render(){
  const rows=filtered();
  const av=rows.filter(r=>r.src==='active'), so=rows.filter(r=>r.src==='sold');
  $('#k1').textContent=av.length; $('#k2').textContent='$'+av.reduce((s,r)=>s+r.price,0).toFixed(0);
  $('#k3').textContent=so.length; $('#k4').textContent='$'+so.reduce((s,r)=>s+r.price,0).toFixed(0);
  $('#k5').textContent=rows.length? '$'+(rows.reduce((s,r)=>s+r.price,0)/rows.length).toFixed(2):'$0';
  bars('#bpc',rows,'player','n'); bars('#bpv',rows,'player','v');
  bars('#bbrand',rows,'brand','n'); bars('#byear',rows,'year','n');
  bars('#bteam',rows,'team','n',10); bars('#bpar',rows,'parallel','n');
  const sorted=[...rows].sort((a,b)=>{const x=a[sortKey],y=b[sortKey];return (x>y?1:x<y?-1:0)*sortDir;});
  $('#count').textContent=rows.length+' cards shown';
  $('#tbody').innerHTML=sorted.slice(0,400).map(r=>`<tr>
    <td><span class="tag ${r.src}">${r.src}</span></td><td>${r.player}</td><td>${r.year} ${r.brand}</td>
    <td>${r.parallel||r.insert||''}${r.rc?' RC':''}${r.numbered?' #':''}</td><td>${r.team}</td>
    <td class="num">$${r.price.toFixed(2)}</td><td>${r.date||''}</td></tr>`).join('');
}
document.querySelectorAll('.bar select,.bar input').forEach(e=>e.addEventListener('input',render));
$('#reset').onclick=()=>{document.querySelectorAll('.bar select').forEach(s=>s.value='');
  $('#fq').value='';$('#frc').checked=false;$('#fnum').checked=false;render();};
document.querySelectorAll('th[data-k]').forEach(th=>th.onclick=()=>{
  const k=th.dataset.k; sortDir = sortKey===k? -sortDir : -1; sortKey=k; render();});
render();
"""

page = (
"<!DOCTYPE html><html lang='en'><head><meta charset='utf-8'>"
"<meta name='viewport' content='width=device-width, initial-scale=1'>"
"<title>JC2 Cards — Analytics</title><style>" + CSS + "</style></head><body>"
"<header><h1>JC&sup2; Cards — Inventory & Sales Analytics</h1>"
"<div class='sub'>" + f"{a_n} active (${a_v:,.0f}) · {s_n} sold (${s_v:,.0f}) · parsed from titles · filter anything below" + "</div>"
"<div class='kpis'>"
"<div class='kpi act'><div class='v' id='k1'>–</div><div class='l'>Active cards</div></div>"
"<div class='kpi act'><div class='v' id='k2'>–</div><div class='l'>Active value</div></div>"
"<div class='kpi sold'><div class='v' id='k3'>–</div><div class='l'>Sold cards</div></div>"
"<div class='kpi sold'><div class='v' id='k4'>–</div><div class='l'>Sold value</div></div>"
"<div class='kpi'><div class='v' id='k5'>–</div><div class='l'>Avg price (shown)</div></div>"
"</div></header>"
"<div class='bar'>"
"<label>Source<select id='fsrc'><option value=''>Active + Sold</option><option value='active'>Active only</option><option value='sold'>Sold only</option></select></label>"
"<label>Brand<select id='fbrand'></select></label>"
"<label>Year<select id='fyear'></select></label>"
"<label>Team<select id='fteam'></select></label>"
"<label>Parallel<select id='fpar'></select></label>"
"<label>Insert<select id='fins'></select></label>"
"<label>Player / title<input id='fq' placeholder='search…' size='16'></label>"
"<label class='chk'><input type='checkbox' id='frc'> RC only</label>"
"<label class='chk'><input type='checkbox' id='fnum'> Numbered only</label>"
"<button id='reset'>Reset</button>"
"</div><div class='wrap'><div class='grid'>"
"<div class='card'><h3>Top 10 players — by card count</h3><div id='bpc'></div></div>"
"<div class='card'><h3>Top 10 players — by total value</h3><div id='bpv'></div></div>"
"<div class='card'><h3>By brand</h3><div id='bbrand'></div></div>"
"<div class='card'><h3>By year</h3><div id='byear'></div></div>"
"<div class='card'><h3>Top teams</h3><div id='bteam'></div></div>"
"<div class='card'><h3>By parallel</h3><div id='bpar'></div></div>"
"</div>"
"<div class='card' style='margin-top:16px'><h3>Cards (filtered) — click a header to sort</h3>"
"<div id='count'></div><div id='tablewrap'><table><thead><tr>"
"<th>Src</th><th data-k='player'>Player</th><th>Set</th><th>Variant</th>"
"<th data-k='team'>Team</th><th class='num' data-k='price'>Price</th><th data-k='date'>Sold</th>"
"</tr></thead><tbody id='tbody'></tbody></table></div></div>"
"</div><script>" + JS.replace("__DATA__", DATA) + "</script></body></html>"
)

outp = REPO / "docs/stats.html"
outp.write_text(page)
print(f"wrote {outp} — {len(rows)} cards ({a_n} active, {s_n} sold)")
