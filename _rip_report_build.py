"""_rip_report_build.py — "The Rip Report": did $250 of packs beat buying singles?

Renders docs/rip_report.html (standalone, public, shareable) from
output/rip_experiment.json. Re-run after appending a new batch + cards to the
JSON; the page recomputes totals, per-batch stats, and the verdict.
"""
import json
from pathlib import Path

DATA = json.load(open("output/rip_experiment.json"))
cards = DATA["cards"]
batches = DATA["batches"]

spent = sum(b["cost"] for b in batches)
tot = {k: round(sum(c[k] for c in cards), 2) for k in ("low", "typ", "high")}
FEE = 0.15  # eBay final value + payment fees, rough
net_typ = round(tot["typ"] * (1 - FEE), 2)
recovery = tot["typ"] / spent * 100
net_recovery = net_typ / spent * 100

if net_recovery >= 110:
    verdict = "Ripping is WINNING so far — the hits carried it."
elif net_recovery >= 90:
    verdict = "Basically break-even — the fun of ripping was nearly free."
else:
    verdict = "Buying singles wins — ripping recovered only part of the spend."

html = """<!DOCTYPE html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>The Rip Report — was $__SPENT__ of packs worth it?</title>
<meta property="og:title" content="The Rip Report — was $__SPENT__ of packs worth it?">
<meta property="og:description" content="__NCARDS__ cards ripped, valued card-by-card. Verdict: __VERDICT__">
<style>
 :root{--ink:#111;--mut:#667;--gold:#b8860b;--grn:#1a7f1a;--red:#a02020}
 body{margin:0;font-family:-apple-system,system-ui,sans-serif;background:#f6f7fa;color:var(--ink)}
 .wrap{max-width:820px;margin:0 auto;padding:18px 14px 90px}
 h1{font-size:26px;margin:8px 0 2px}
 .sub{color:var(--mut);font-size:14px;margin:0 0 14px}
 .hero{background:#111;color:#fff;border-radius:16px;padding:18px;margin-bottom:14px}
 .hero .big{font-size:30px;font-weight:800}
 .hero .row{display:flex;gap:18px;flex-wrap:wrap;margin-top:10px}
 .hero .cell b{display:block;font-size:22px}
 .hero .cell span{font-size:12px;opacity:.75}
 .verdict{margin-top:12px;padding:10px 12px;background:rgba(212,175,55,.15);border:1px solid rgba(212,175,55,.5);border-radius:10px;font-weight:600}
 .bar{height:14px;background:#333;border-radius:7px;overflow:hidden;margin-top:12px;position:relative}
 .bar>div{height:100%;background:linear-gradient(90deg,#b8860b,#ffd700)}
 .bar>i{position:absolute;top:-3px;bottom:-3px;width:2px;background:#fff;left:100%}
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
 .c-Base{background:#eee;color:#555}.c-Rookie{background:#fde8e8;color:#a02020}
 .c-Insert{background:#e8f0fd;color:#1a4fa0}.c-Parallel{background:#f3e8fd;color:#7020a0}
 .c-SerialNo{background:#fff3d6;color:#8a6d00}
 .val{text-align:right;flex:0 0 auto}
 .val b{font-size:17px;color:var(--grn)}
 .val span{display:block;font-size:11px;color:var(--mut)}
 .loc{flex:0 0 auto;text-align:center;background:#123;color:#fff;border-radius:8px;padding:5px 9px;font-size:12px}
 .foot{color:var(--mut);font-size:12.5px;margin-top:20px;line-height:1.5}
</style></head><body><div class="wrap">
<h1>The Rip Report</h1>
<p class="sub">We spent <b>$__SPENT__</b> on packs, ripped them, and priced every card honestly. Is ripping packs a good investment? Follow along.</p>
<div class="hero">
 <div class="big">$__SPENT__ spent &rarr; ~$__TYP__ of cards</div>
 <div class="bar"><div style="width:__PCT__%"></div></div>
 <div class="row">
  <div class="cell"><b>__NCARDS__</b><span>cards pulled</span></div>
  <div class="cell"><b>$__LOW__&ndash;$__HIGH__</b><span>value range (typ $__TYP__)</span></div>
  <div class="cell"><b>__PCT__%</b><span>gross recovery</span></div>
  <div class="cell"><b>__NETPCT__%</b><span>after ~15% selling fees</span></div>
 </div>
 <div class="verdict">Verdict so far: __VERDICT__</div>
</div>
<div class="ctrl">
 <select id="fsport"><option value="">All sports</option><option>Baseball</option><option>Football</option></select>
 <select id="fcat"><option value="">All types</option><option>Rookie</option><option>Insert</option><option>Parallel</option><option>Serial #</option><option>Base</option></select>
 <select id="fsort"><option value="v">Sort: value</option><option value="a">Sort: player A-Z</option><option value="s">Sort: scan order</option></select>
 <input id="q" type="search" placeholder="Search player, team, set...">
</div>
<div id="stat"></div>
<div id="list"></div>
<p class="foot"><b>How we priced these:</b> __METHOD__ Selling costs (eBay fees, shipping supplies, your time) are NOT in the card values &mdash; the "after fees" number knocks off ~15%. New batches get added as we rip them; the verdict updates live.</p>
</div>
<script>
const CARDS = __DATA__;
const list = document.getElementById("list"), stat = document.getElementById("stat");
function money(x){return "$" + (x % 1 ? x.toFixed(2) : x)}
function render(){
  const sp = document.getElementById("fsport").value;
  const ct = document.getElementById("fcat").value;
  const so = document.getElementById("fsort").value;
  const q = document.getElementById("q").value.toLowerCase();
  let rows = CARDS.filter(c =>
    (!sp || c.sport === sp) && (!ct || c.category === ct) &&
    (!q || (c.player + " " + c.team + " " + c.brand + " " + c.insert + " " + c.parallel).toLowerCase().includes(q)));
  if (so === "v") rows.sort((a,b) => b.typ - a.typ || a.player.localeCompare(b.player));
  else if (so === "a") rows.sort((a,b) => a.player.localeCompare(b.player));
  else rows.sort((a,b) => a.scan - b.scan || a.pos - b.pos);
  const t = rows.reduce((s,c) => s + c.typ, 0);
  stat.textContent = rows.length + " cards · est. value ~" + money(Math.round(t*100)/100);
  list.innerHTML = "";
  for (const c of rows){
    const cls = "c-" + c.category.replace(/[^A-Za-z]/g, "");
    const bits = [c.brand, c.insert, c.parallel, c.serial].filter(Boolean).join(" · ");
    const el = document.createElement("div");
    el.className = "card";
    el.innerHTML = `<div class="info"><div class="nm">${c.player}${c.rc ? ' <span class="rc">RC</span>' : ""}</div>` +
      `<div class="ds"><span class="chip ${cls}">${c.category}</span>${bits} — ${c.team || ""} (${c.sport})</div></div>` +
      `<div class="val"><b>${money(c.typ)}</b><span>${money(c.low)}–${money(c.high)}</span></div>` +
      `<div class="loc">${c.scan}/${c.pos}</div>`;
    list.appendChild(el);
  }
}
for (const id of ["fsport","fcat","fsort","q"]) document.getElementById(id).oninput = render;
render();
</script></body></html>"""

html = (html
        .replace("__SPENT__", f"{spent:,.0f}")
        .replace("__TYP__", f"{tot['typ']:,.0f}")
        .replace("__LOW__", f"{tot['low']:,.0f}")
        .replace("__HIGH__", f"{tot['high']:,.0f}")
        .replace("__PCT__", f"{recovery:.0f}")
        .replace("__NETPCT__", f"{net_recovery:.0f}")
        .replace("__NCARDS__", str(len(cards)))
        .replace("__VERDICT__", verdict)
        .replace("__METHOD__", DATA.get("methodology", ""))
        .replace("__DATA__", json.dumps(cards)))

Path("docs/rip_report.html").write_text(html)
print(f"wrote docs/rip_report.html — {len(cards)} cards, ${spent:.0f} spent, "
      f"typ ${tot['typ']:.2f} ({recovery:.0f}% gross, {net_recovery:.0f}% net) — {verdict}")
