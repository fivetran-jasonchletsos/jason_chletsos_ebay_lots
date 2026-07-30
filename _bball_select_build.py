"""_bball_select_build.py — 2024-25 Select basketball rip: pricing site + pick list.

Renders docs/bball_select.html (public pricing/browse page) and
docs/bball_pull.html (tap-to-check pull list, checklist pattern) from
output/bball_select.json. Re-run after data edits.
"""
import json
from pathlib import Path

DATA = json.load(open("output/bball_select.json"))
cards = DATA["cards"]
tot = DATA["totals"]

KEEP_FLAG = {"LeBron James", "Karl-Anthony Towns", "Jalen Brunson",
             "Pacome Dadiet", "Ariel Hukporti"}


def is_sixers(c):
    t = c["team"].lower()
    return "76" in c["team"] or "phil" in t or "sixer" in t


def par_group(c):
    p = c["parallel"]
    if p.startswith("Blue"):
        return "Blue"
    if "Flash" in p:
        return "Orange Flash"
    if p in ("Tri-Color", "Silver", "Green", "Purple", "Yellow", "Mezzanine"):
        return p
    return "Base"


for c in cards:
    c["grp"] = par_group(c)
    c["keep"] = c["player"] in KEEP_FLAG
    c["sixers"] = is_sixers(c)

# ---------------------------------------------------------------- pricing site
PRICE_HTML = """<!DOCTYPE html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex">
<title>2024-25 Select Basketball Rip — priced card by card</title>
<style>
 :root{--ink:#111;--mut:#667;--grn:#1a7f1a;--red:#a02020}
 body{margin:0;font-family:-apple-system,system-ui,sans-serif;background:#f6f7fa;color:var(--ink)}
 .wrap{max-width:820px;margin:0 auto;padding:18px 14px 40px}
 h1{font-size:24px;margin:8px 0 2px}
 .sub{color:var(--mut);font-size:14px;margin:0 0 14px}
 .hero{background:#0b1b3a;color:#fff;border-radius:16px;padding:18px;margin-bottom:14px}
 .hero .big{font-size:28px;font-weight:800}
 .hero .row{display:flex;gap:18px;flex-wrap:wrap;margin-top:10px}
 .hero .cell b{display:block;font-size:22px}
 .hero .cell span{font-size:12px;opacity:.75}
 .ctrl{display:flex;gap:8px;flex-wrap:wrap;margin:12px 0}
 .ctrl select,.ctrl input{font-size:15px;padding:9px 10px;border:1px solid #ccd;border-radius:10px;background:#fff}
 .ctrl input{flex:1;min-width:160px}
 #stat{color:var(--mut);font-size:13.5px;margin:2px 0 8px}
 .card{display:flex;align-items:center;gap:10px;background:#fff;border:1px solid #dde;border-radius:12px;padding:10px 12px;margin:6px 0}
 .info{flex:1;min-width:0}
 .nm{font-weight:700;font-size:16px}
 .nm .rc{color:var(--red);font-size:11px;font-weight:800;vertical-align:2px}
 .ds{color:var(--mut);font-size:12.5px;margin-top:1px}
 .chip{display:inline-block;font-size:10.5px;font-weight:700;padding:1px 7px;border-radius:8px;margin-right:4px}
 .g-Blue{background:#e3edfd;color:#1a4fa0}.g-Base{background:#eee;color:#555}
 .g-OrangeFlash{background:#ffe8d6;color:#a04a00}.g-TriColor{background:#f3e8fd;color:#7020a0}
 .g-Silver{background:#e8e8ee;color:#445}.g-Green{background:#e2f5e2;color:#186818}
 .g-Purple{background:#efe2f7;color:#6a1b9a}.g-Yellow{background:#fff3c4;color:#8a6d00}
 .g-Mezzanine{background:#e0f2f1;color:#00695c}
 .val{text-align:right;flex:0 0 auto}
 .val b{font-size:17px;color:var(--grn)}
 .val span{display:block;font-size:11px;color:var(--mut)}
 .loc{flex:0 0 auto;text-align:center;background:#123;color:#fff;border-radius:8px;padding:5px 9px;font-size:12px}
 .foot{color:var(--mut);font-size:12.5px;margin-top:20px;line-height:1.5}
</style></head><body><div class="wrap">
<h1>2024-25 Select Basketball Rip</h1>
<p class="sub">__NCARDS__ cards from a retail Select basketball rip, priced honestly card-by-card. Mostly Blue retail parallels.</p>
<div class="hero">
 <div class="big">~$__TYP__ of cards pulled</div>
 <div class="row">
  <div class="cell"><b>__NCARDS__</b><span>cards</span></div>
  <div class="cell"><b>$__LOW__&ndash;$__HIGH__</b><span>value range (typ $__TYP__)</span></div>
  <div class="cell"><b>__NRC__</b><span>rookies</span></div>
  <div class="cell"><b>__NSPEC__</b><span>color/short-print parallels</span></div>
 </div>
</div>
<div class="ctrl">
 <select id="fpar"><option value="">All parallels</option>__PAROPTS__</select>
 <select id="ftier"><option value="">All players</option><option value="star">Stars</option><option value="solid">Solid</option><option value="common">Commons</option></select>
 <select id="frc"><option value="">RC + vets</option><option value="1">Rookies only</option></select>
 <select id="fsort"><option value="v">Sort: value</option><option value="a">Sort: last name A-Z</option><option value="s">Sort: scan order</option></select>
 <input id="q" type="search" placeholder="Search player, team, parallel...">
</div>
<div id="stat"></div>
<div id="list"></div>
<p class="foot"><b>How we priced these:</b> recent eBay sold comps for 2024-25 Select basketball retail parallels. Blue Concourse of a superstar runs single digits raw; Premier Level / Courtside get a small bump; color parallels (Orange Flash, Tri-Color, Silver, Green, Purple, Yellow) get a bigger one. "Typ" is the realistic sale price; low/high bound the range. Fees and shipping not deducted.</p>
</div>
<script>
const CARDS = __DATA__;
const list = document.getElementById("list"), stat = document.getElementById("stat");
function money(x){return "$" + (x % 1 ? x.toFixed(2) : x)}
const lastName = p => {
  const parts = p.replace(/["'.]/g, "").split(/[\\s/-]+/).filter(w => !/^(jr|sr|ii|iii|iv)$/i.test(w));
  return (parts[parts.length - 1] || p).toLowerCase();
};
function render(){
  const pa = document.getElementById("fpar").value;
  const ti = document.getElementById("ftier").value;
  const rc = document.getElementById("frc").value;
  const so = document.getElementById("fsort").value;
  const q = document.getElementById("q").value.toLowerCase();
  let rows = CARDS.filter(c =>
    (!pa || c.grp === pa) && (!ti || c.tier === ti) && (!rc || c.rc) &&
    (!q || (c.player + " " + c.team + " " + c.parallel).toLowerCase().includes(q)));
  if (so === "v") rows.sort((a,b) => b.typ - a.typ || lastName(a.player).localeCompare(lastName(b.player)));
  else if (so === "a") rows.sort((a,b) => lastName(a.player).localeCompare(lastName(b.player)) || a.player.localeCompare(b.player));
  else rows.sort((a,b) => a.scan - b.scan || a.pos - b.pos);
  const t = rows.reduce((s,c) => s + c.typ, 0);
  stat.textContent = rows.length + " cards · est. value ~" + money(Math.round(t*100)/100);
  list.innerHTML = "";
  for (const c of rows){
    const g = "g-" + c.grp.replace(/[^A-Za-z]/g, "");
    const el = document.createElement("div");
    el.className = "card";
    el.innerHTML = `<div class="info"><div class="nm">${c.player}${c.rc ? ' <span class="rc">RC</span>' : ""}</div>` +
      `<div class="ds"><span class="chip ${g}">${c.parallel}</span>${c.team}</div></div>` +
      `<div class="val"><b>${money(c.typ)}</b><span>${money(c.low)}–${money(c.high)}</span></div>` +
      `<div class="loc">${c.scan}/${c.pos}</div>`;
    list.appendChild(el);
  }
}
for (const id of ["fpar","ftier","frc","fsort","q"]) document.getElementById(id).oninput = render;
render();
</script></body></html>"""

groups = sorted({c["grp"] for c in cards},
                key=lambda g: (g == "Blue", g == "Base", g))
par_opts = "".join(f"<option>{g}</option>" for g in
                   sorted({c['grp'] for c in cards}))
n_spec = sum(1 for c in cards if c["grp"] not in ("Blue", "Base"))

price_html = (PRICE_HTML
              .replace("__NCARDS__", str(len(cards)))
              .replace("__TYP__", f"{tot['typ']:,.0f}")
              .replace("__LOW__", f"{tot['low']:,.0f}")
              .replace("__HIGH__", f"{tot['high']:,.0f}")
              .replace("__NRC__", str(sum(1 for c in cards if c["rc"])))
              .replace("__NSPEC__", str(n_spec))
              .replace("__PAROPTS__", par_opts)
              .replace("__DATA__", json.dumps(cards)))
Path("docs/bball_select.html").write_text(price_html)

# ---------------------------------------------------------------- pick list
# 2026-07-29: JC ruled — LeBrons + Knicks are KEEPS (stay home), 76ers to his
# son, and the pull list is now exactly the posting batch: typ >= $2.
pull = [c for c in cards
        if not c["sixers"] and not c["keep"] and c["typ"] >= 2]
pull.sort(key=lambda c: -c["typ"])
pull_typ = round(sum(c["typ"] for c in pull), 2)
sixers = [c for c in cards if c["sixers"]]

PULL_HTML = """<!DOCTYPE html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex">
<title>Select Basketball Pull List</title>
<style>
 body{margin:0;font-family:-apple-system,system-ui,sans-serif;background:#f6f7fa;color:#111}
 .wrap{max-width:760px;margin:0 auto;padding:16px 12px 110px}
 h1{font-size:22px;margin:6px 0 2px}
 .sub{color:#667;font-size:13.5px;margin:0 0 10px}
 .warn{background:#fff8dc;border:1px solid #d4b106;border-radius:10px;padding:10px 12px;font-size:13.5px;margin:0 0 12px;line-height:1.5}
 .chips{display:flex;gap:6px;flex-wrap:wrap;margin:10px 0}
 .chips button{font-size:13px;padding:7px 11px;border:1px solid #ccd;border-radius:16px;background:#fff;cursor:pointer}
 .chips button.on{background:#0b1b3a;color:#fff;border-color:#0b1b3a}
 .ctrl{display:flex;gap:8px;flex-wrap:wrap;margin:8px 0}
 .ctrl select,.ctrl input{font-size:15px;padding:8px 10px;border:1px solid #ccd;border-radius:10px;background:#fff}
 .ctrl input{flex:1;min-width:140px}
 .ghdr{font-weight:800;font-size:14px;color:#334;margin:14px 0 4px}
 .row{display:flex;align-items:center;gap:10px;background:#fff;border:1px solid #dde;border-radius:12px;padding:10px 12px;margin:6px 0;cursor:pointer;-webkit-tap-highlight-color:transparent}
 .row.done{opacity:.55}.row.done .nm{text-decoration:line-through;color:#1a7f1a}
 .cb{flex:0 0 26px;height:26px;border:2px solid #99a;border-radius:7px;display:flex;align-items:center;justify-content:center;font-size:17px;color:#fff}
 .row.done .cb{background:#1a7f1a;border-color:#1a7f1a}
 .info{flex:1;min-width:0}
 .nm{font-weight:700;font-size:16px}
 .nm .rc{color:#a02020;font-size:11px;font-weight:800;vertical-align:2px}
 .nm .keep{background:#a02020;color:#fff;font-size:10px;font-weight:800;padding:1px 6px;border-radius:7px;vertical-align:2px;margin-left:4px}
 .ds{color:#667;font-size:12.5px;margin-top:1px}
 .val{flex:0 0 auto;text-align:right;font-weight:700;color:#1a7f1a;font-size:15px}
 .loc{flex:0 0 auto;text-align:center;background:#123;color:#fff;border-radius:8px;padding:5px 9px;font-size:12px}
 .bar{position:fixed;bottom:0;left:0;right:0;background:#0b1b3a;color:#fff;display:flex;align-items:center;gap:10px;padding:12px 14px;font-size:14px}
 .bar b{font-size:17px}
 .bar button{margin-left:auto;font-size:13px;padding:8px 12px;border:0;border-radius:9px;background:#fff;color:#0b1b3a;font-weight:700;cursor:pointer}
 .bar button.rst{background:transparent;color:#fbb;border:1px solid #a55;margin-left:8px}
</style></head><body><div class="wrap">
<h1>Select Basketball Pull List</h1>
<p class="sub">__NPULL__ cards to pull for posting (of __NCARDS__ ripped) &middot; est. value ~$__PULLTYP__. This IS the posting batch. Scan badge = scan/position (1 = top-left, 9 = bottom-right). Tap a row to check it off &mdash; progress saves on this device.</p>
<div class="warn"><b>Keep at home (not on this list):</b> the 3 LeBrons + the Knicks (Towns, Brunson, Dadiet, Hukporti) &mdash; your call 2026-07-29 &mdash; and __SIXERS__ (76ers go to your son's box).<br>
<b>Also not listed:</b> everything under ~$2 typ (mostly Blue commons) stays in the repository pile for future lots.</div>
<div class="chips" id="chips"></div>
<div class="ctrl">
 <select id="fsort"><option value="v">Sort: value</option><option value="a">Sort: last name A-Z</option><option value="s">Sort: scan order</option></select>
 <input id="q" type="search" placeholder="Search player, team...">
</div>
<div id="list"></div>
</div>
<div class="bar"><span><b id="done">0</b>/__NPULL__ pulled</span>
<button id="copy">Copy report</button><button class="rst" id="reset">Reset</button></div>
<script>
const DATA = __DATA__;
const KEY = "bballpull_done";
let done = new Set(JSON.parse(localStorage.getItem(KEY) || "[]"));
let chip = "";
const groups = [...new Set(DATA.map(c => c.grp))];
const chipbox = document.getElementById("chips");
const lastName = p => {
  const parts = p.replace(/["'.]/g, "").split(/[\\s/-]+/).filter(w => !/^(jr|sr|ii|iii|iv)$/i.test(w));
  return (parts[parts.length - 1] || p).toLowerCase();
};
function id(c){return c.scan + "/" + c.pos}
function money(x){return "$" + (x % 1 ? x.toFixed(2) : x)}
function drawChips(){
  chipbox.innerHTML = "";
  const all = document.createElement("button");
  all.textContent = "All " + done.size + "/" + DATA.length;
  all.className = chip === "" ? "on" : "";
  all.onclick = () => { chip = ""; render(); };
  chipbox.appendChild(all);
  for (const g of groups){
    const rows = DATA.filter(c => c.grp === g);
    const d = rows.filter(c => done.has(id(c))).length;
    const b = document.createElement("button");
    b.textContent = g + " " + d + "/" + rows.length;
    b.className = chip === g ? "on" : "";
    b.onclick = () => { chip = chip === g ? "" : g; render(); };
    chipbox.appendChild(b);
  }
}
function render(){
  drawChips();
  const so = document.getElementById("fsort").value;
  const q = document.getElementById("q").value.toLowerCase();
  let rows = DATA.filter(c => (!chip || c.grp === chip) &&
    (!q || (c.player + " " + c.team + " " + c.parallel).toLowerCase().includes(q)));
  if (so === "v") rows.sort((a,b) => b.typ - a.typ || lastName(a.player).localeCompare(lastName(b.player)));
  else if (so === "a") rows.sort((a,b) => lastName(a.player).localeCompare(lastName(b.player)) || a.player.localeCompare(b.player));
  else rows.sort((a,b) => a.scan - b.scan || a.pos - b.pos);
  const list = document.getElementById("list");
  list.innerHTML = "";
  let hdr = null;
  for (const c of rows){
    if (!chip && so === "v"){
      const band = c.typ >= 5 ? "Headliners ($5+)" : c.typ >= 2.5 ? "Stars ($2.50+)" : "Worth pulling";
      if (band !== hdr){
        hdr = band;
        const h = document.createElement("div");
        h.className = "ghdr"; h.textContent = band;
        list.appendChild(h);
      }
    }
    const el = document.createElement("div");
    el.className = "row" + (done.has(id(c)) ? " done" : "");
    el.innerHTML = `<div class="cb">${done.has(id(c)) ? "&#10003;" : ""}</div>` +
      `<div class="info"><div class="nm">${c.player}${c.rc ? ' <span class="rc">RC</span>' : ""}${c.keep ? ' <span class="keep">KEEP?</span>' : ""}</div>` +
      `<div class="ds">${c.parallel} &middot; ${c.team}</div></div>` +
      `<div class="val">${money(c.typ)}</div>` +
      `<div class="loc">${c.scan}/${c.pos}</div>`;
    el.onclick = () => {
      done.has(id(c)) ? done.delete(id(c)) : done.add(id(c));
      localStorage.setItem(KEY, JSON.stringify([...done]));
      render();
    };
    list.appendChild(el);
  }
  document.getElementById("done").textContent = done.size;
}
document.getElementById("copy").onclick = () => {
  const un = DATA.filter(c => !done.has(id(c)));
  const txt = "BBALL PULL REPORT: " + done.size + "/" + DATA.length + " pulled. " +
    "NOT PULLED (" + un.length + "): " +
    un.map(c => id(c) + " " + c.player + " " + c.parallel).join(" | ");
  navigator.clipboard.writeText(txt).then(() => alert("Report copied — paste it to CC."));
};
document.getElementById("reset").onclick = () => {
  if (confirm("Clear all checkmarks?")){ done.clear(); localStorage.setItem(KEY, "[]"); render(); }
};
document.getElementById("fsort").oninput = render;
document.getElementById("q").oninput = render;
render();
</script></body></html>"""

sixers_txt = ", ".join(f"{c['player']} ({c['parallel']}, scan {c['scan']}/{c['pos']})"
                       for c in sixers) or "none found"
pull_html = (PULL_HTML
             .replace("__NPULL__", str(len(pull)))
             .replace("__NCARDS__", str(len(cards)))
             .replace("__PULLTYP__", f"{pull_typ:,.0f}")
             .replace("__SIXERS__", sixers_txt)
             .replace("__DATA__", json.dumps(pull)))
Path("docs/bball_pull.html").write_text(pull_html)

print(f"pricing page: {len(cards)} cards, typ ${tot['typ']:.2f}")
print(f"pull list: {len(pull)} cards, typ ${pull_typ:.2f}; "
      f"excluded {len(sixers)} 76ers; {sum(1 for c in pull if c['keep'])} KEEP? flags")
