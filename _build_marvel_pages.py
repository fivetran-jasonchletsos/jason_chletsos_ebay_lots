"""Assemble the Marvel sell-off catalog from 5 verification agents + CC's own
manual reads (scans 693-695), apply the year/set corrections that surfaced
during the pass (flagship base set is 2026 Topps Chrome Marvel Comics, not
2024; Deadpool movie tie-ins are 2025 Topps Chrome Deadpool; Marvel Beginnings
is 2022; Women of Marvel is a standalone 2024 Upper Deck product), and build
two pages: docs/marvel_pull.html (singles only, ready to post, no gate) and
docs/marvel_lots_proposal.html (21 lot proposals, needs JC confirm + physical
pull before anything is listed -- house rule)."""
import json, re
from pathlib import Path

OUT = Path("output")


def fix_year(title):
    return (title
            .replace("2024 Topps Chrome Marvel Studios Deadpool & Wolverine", "2025 Topps Chrome Deadpool")
            .replace("2024 Topps Chrome Marvel Studios", "2025 Topps Chrome Deadpool")
            .replace("2024 Topps Chrome Marvel", "2026 Topps Chrome Marvel Comics"))


# ---------------------------------------------------------------- agent 1
a1 = json.load(open(OUT / "_marvel_agent1_numbered_wave.json"))
singles = []
for c in a1:
    c["title"] = fix_year(c["title"])
    c["description"] = fix_year(c["description"])
    singles.append({"scan": c["scan"], "pos": c["pos"], "player": c["character"],
                     "team": "Marvel", "parallel": c["parallel"], "insert": "",
                     "title": c["title"], "price": c["price"], "desc": c["description"],
                     "grp": "Numbered" if c.get("serial") else "Wave/Refractor",
                     "manufacturer": "Topps", "set": "2026 Topps Chrome Marvel Comics",
                     "serial": c.get("serial")})

# ---------------------------------------------------------------- agent 2
a2 = json.load(open(OUT / "_marvel_agent2_vintage_1st.json"))
DEADPOOL_MOVIE = {(696, 4), (696, 5), (697, 6)}
for c in a2:
    title = c["title"]
    desc = c["description"]
    if (c["scan"], c["pos"]) in DEADPOOL_MOVIE:
        title = re.sub(r"^2024 Topps Chrome Marvel(?: Studios)?", "2025 Topps Chrome Deadpool", title)
        setname = "2025 Topps Chrome Deadpool"
    elif title.startswith("2024 Topps Chrome Marvel"):
        title = fix_year(title)
        setname = "2026 Topps Chrome Marvel Comics"
    elif "Upper Deck" in title:
        setname = "Upper Deck Marvel Monumental Covers"
    else:
        setname = c.get("set", "Vintage Marvel")
    grp = "Vintage 1993-94" if "1993" in title or "1994" in title or "Battles Masterpieces" in title else \
          ("Deadpool Movie" if "2025 Topps Chrome Deadpool" in title else "1st Appearance")
    singles.append({"scan": c["scan"], "pos": c["pos"], "player": c["character"],
                     "team": "Marvel", "parallel": "", "insert": c.get("set", ""),
                     "title": title, "price": c["price"], "desc": desc, "grp": grp,
                     "manufacturer": "Topps" if "Topps" in setname else ("Upper Deck" if "Upper Deck" in setname else "SkyBox/Fleer"),
                     "set": setname, "serial": None})

# ---------------------------------------------------------------- agent 3
a3 = json.load(open(OUT / "_marvel_agent3_beginnings_inserts.json"))
for c in a3:
    setname = c["set"]
    grp = ("Beginnings Insert" if "Marvel Beginnings" in setname else
           "Women of Marvel" if "Women of Marvel" in setname else
           "Deadpool Movie" if "Deadpool" in setname else
           "2026 Chrome Insert")
    singles.append({"scan": c["scan"], "pos": c["pos"], "player": c["character"],
                     "team": "Marvel", "parallel": "", "insert": c.get("insert", ""),
                     "title": c["title"], "price": c["price"], "desc": c["description"], "grp": grp,
                     "manufacturer": "Upper Deck" if "Upper Deck" in setname else "Topps",
                     "set": setname, "serial": None})

# ---- gap-fill: 4 Wave Refractor singles drafted early but never sent to
# an agent for verification. CC personally verified all 4 crops directly.
GAP_WAVE = [
 (687, 8, "She-Venom", 4.99),
 (688, 2, "Spider-Man Noir", 5.49),
 (689, 1, "Tombstone", 3.99),
 (689, 2, "Ultimate Wolverine", 5.99),
]
for scan, pos, name, price in GAP_WAVE:
    title = f"2026 Topps Chrome Marvel Comics {name} Wave Refractor Chase Parallel"
    singles.append({"scan": scan, "pos": pos, "player": name, "team": "Marvel",
                     "parallel": "Wave Refractor", "insert": "", "title": title[:80],
                     "price": price, "grp": "Wave/Refractor", "manufacturer": "Topps",
                     "set": "2026 Topps Chrome Marvel Comics", "serial": None,
                     "desc": f"{name} on the shiny rainbow Wave Refractor chase parallel, "
                             f"CC-verified directly against the scan (zigzag wave foil pattern confirmed)."})

for c in singles:
    assert len(c["title"]) <= 80, (len(c["title"]), c["title"])

singles.sort(key=lambda c: -c["price"])
total_singles_value = sum(c["price"] for c in singles)

# ---------------------------------------------------------------- agent 4 + 5 lots
a4 = json.load(open(OUT / "_marvel_agent4_chrome_lots.json"))
a5 = json.load(open(OUT / "_marvel_agent5_beginnings_lots.json"))

# (681,2) Black Panther and (681,3) Colossus are Wave Refractors already
# handled as premium singles by agent 1 -- my skip-list to agent 4 wrongly
# said "681: none to skip", so it double-cataloged them as base commons too.
DOUBLE_COUNTED = {(681, 2), (681, 3)}

lots = []
for l in a4["lots"]:
    title = fix_year(l["title"]) if "2024 Topps Chrome Marvel" in l["title"] else l["title"]
    if not title.startswith("2026 Topps Chrome Marvel Comics"):
        title = "2026 Topps Chrome Marvel Comics " + title
    cards = [c for c in l["cards"] if (c["scan"], c["pos"]) not in DOUBLE_COUNTED]
    price = l["price"] if len(cards) == len(l["cards"]) else round(l["price"] * len(cards) / len(l["cards"]), 2)
    lots.append({"title": title[:80], "price": price, "cards": cards,
                 "theme": l.get("theme_note", ""), "source": "Topps Chrome base commons"})
for l in a5["lots"]:
    title = l["title"]
    if not title.startswith("2022 Upper Deck Marvel Beginnings") and not title.startswith("Upper Deck Marvel Beginnings"):
        title = "2022 Upper Deck Marvel Beginnings " + title
    elif title.startswith("Upper Deck Marvel Beginnings"):
        title = title.replace("Upper Deck Marvel Beginnings", "2022 Upper Deck Marvel Beginnings")
    lots.append({"title": title[:80], "price": l["price"], "cards": l["cards"],
                 "theme": l.get("theme_note", ""), "source": "Marvel Beginnings base commons"})

for l in lots:
    assert len(l["title"]) <= 80, (len(l["title"]), l["title"])
    assert len(l["cards"]) <= 5, l

# ---- gap-fill: 5 Marvel Beginnings base commons on scan 693 that fell
# between agent 3 (insert-only positions) and agent 5 (scans 690-692 only).
# CC personally verified all 5 crops directly.
lots.append({
    "title": "2022 Upper Deck Marvel Beginnings 5-Card Lot: Dazzler, Pepper Potts +3",
    "price": 5.99,
    "cards": [
        {"scan": 693, "pos": 1, "character": "Dazzler"},
        {"scan": 693, "pos": 2, "character": "Johnny Watts"},
        {"scan": 693, "pos": 4, "character": "The Maker"},
        {"scan": 693, "pos": 7, "character": "Eimin"},
        {"scan": 693, "pos": 8, "character": "Pepper Potts"},
    ],
    "theme": "Gap-fill lot (scan 693 base commons, CC-verified) — Pepper Potts and Dazzler carry the name recognition",
    "source": "Marvel Beginnings base commons",
})

total_lot_value = sum(l["price"] for l in lots)
total_lot_cards = sum(len(l["cards"]) for l in lots)

json.dump(singles, open(OUT / "_marvel_singles_final.json", "w"), indent=1)
json.dump(lots, open(OUT / "_marvel_lots_final.json", "w"), indent=1)

print(f"SINGLES: {len(singles)} cards, ${total_singles_value:.2f}")
print(f"LOTS: {len(lots)} lots, {total_lot_cards} cards, ${total_lot_value:.2f}")

FONT = "font-family:-apple-system,system-ui,sans-serif;"

# =================================================================== SINGLES PULL PAGE
groups = sorted({c["grp"] for c in singles})
rows_js = json.dumps([{"scan": c["scan"], "pos": c["pos"], "player": c["player"],
                        "team": c["set"], "parallel": c["parallel"] or c["insert"],
                        "rc": False, "tier": "hit", "low": round(c["price"]*0.5, 2),
                        "typ": c["price"], "high": round(c["price"]*2, 2),
                        "grp": c["grp"], "keep": False, "sixers": False, "ebay": "",
                        "title": c["title"], "desc": c["desc"]} for c in singles])

singles_html = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex">
<title>Marvel Sell-Off — Singles Pull List</title>
<style>
 body{{margin:0;{FONT}background:#f6f7fa;color:#111}}
 .wrap{{max-width:760px;margin:0 auto;padding:16px 12px 110px}}
 h1{{font-size:22px;margin:6px 0 2px}}
 .sub{{color:#667;font-size:13.5px;margin:0 0 10px}}
 .warn{{background:#fff8dc;border:1px solid #d4b106;border-radius:10px;padding:10px 12px;font-size:13.5px;margin:0 0 12px;line-height:1.5}}
 .chips{{display:flex;gap:6px;flex-wrap:wrap;margin:10px 0}}
 .chips button{{font-size:13px;padding:7px 11px;border:1px solid #ccd;border-radius:16px;background:#fff;cursor:pointer}}
 .chips button.on{{background:#7b1fa2;color:#fff;border-color:#7b1fa2}}
 .ctrl{{display:flex;gap:8px;flex-wrap:wrap;margin:8px 0}}
 .ctrl select,.ctrl input{{font-size:15px;padding:8px 10px;border:1px solid #ccd;border-radius:10px;background:#fff}}
 .ctrl input{{flex:1;min-width:140px}}
 .ghdr{{font-weight:800;font-size:14px;color:#334;margin:14px 0 4px}}
 .row{{display:flex;align-items:center;gap:10px;background:#fff;border:1px solid #dde;border-radius:12px;padding:10px 12px;margin:6px 0;cursor:pointer;-webkit-tap-highlight-color:transparent}}
 .row.done{{opacity:.55}}.row.done .nm{{text-decoration:line-through;color:#1a7f1a}}
 .cb{{flex:0 0 26px;height:26px;border:2px solid #99a;border-radius:7px;display:flex;align-items:center;justify-content:center;font-size:17px;color:#fff}}
 .row.done .cb{{background:#1a7f1a;border-color:#1a7f1a}}
 .info{{flex:1;min-width:0}}
 .nm{{font-weight:700;font-size:16px}}
 .ds{{color:#667;font-size:12.5px;margin-top:1px}}
 .val{{flex:0 0 auto;text-align:right;font-weight:700;color:#7b1fa2;font-size:15px}}
 .loc{{flex:0 0 auto;text-align:center;background:#2d1b3d;color:#fff;border-radius:8px;padding:5px 9px;font-size:12px}}
 .bar{{position:fixed;bottom:0;left:0;right:0;background:#2d1b3d;color:#fff;display:flex;align-items:center;gap:10px;padding:12px 14px;font-size:14px}}
 .bar b{{font-size:17px}}
 .bar button{{margin-left:auto;font-size:13px;padding:8px 12px;border:0;border-radius:9px;background:#fff;color:#2d1b3d;font-weight:700;cursor:pointer}}
 .bar button.rst{{background:transparent;color:#fbb;border:1px solid #a55;margin-left:8px}}
</style></head><body><div class="wrap">
<h1>Marvel Sell-Off — Singles Pull List</h1>
<p class="sub">{len(singles)} cards ready to pull &amp; post (of the full ~155-card haul, scans 680-697) &middot; est. value ~${total_singles_value:.2f}.
Scan badge = scan/position (1 = top-left ... 9 = bottom-right). Tap a row to check it off &mdash; progress saves on this device.</p>
<div class="warn"><b>Verified by 3 independent agents + CC's own reads.</b> Year correction: the flagship base set is
<b>2026 Topps Chrome Marvel Comics</b> (not 2024), Deadpool/Wolverine movie inserts are <b>2025 Topps Chrome Deadpool</b>,
Marvel Beginnings is <b>2022</b>, Women of Marvel is a standalone <b>2024 Upper Deck</b> product.
Agents corrected several of my draft calls: Abomination and Silence have no special parallel (repriced as commons),
Hope Summers/Leader are plain Refractors not Wave, and the Deep Lore villain on 694/1 is Nuke, not Warhawk.<br>
<b>21 lot proposals</b> for the ~99 base-common characters are on a separate page (needs your OK + physical pull first, house rule) &mdash; see <a href="marvel_lots_proposal.html">marvel_lots_proposal.html</a>.<br>
<b>4 more boxes incoming today</b> &mdash; this page is built to extend as new scans get catalogued.</div>
<div class="chips" id="chips"></div>
<div class="ctrl">
 <select id="fsort"><option value="v">Sort: value</option><option value="a">Sort: name A-Z</option><option value="s">Sort: scan order</option></select>
 <input id="q" type="search" placeholder="Search character, set...">
</div>
<div id="list"></div>
</div>
<div class="bar"><span><b id="done">0</b>/{len(singles)} pulled</span>
<button id="copy">Copy report</button><button class="rst" id="reset">Reset</button></div>
<script>
const DATA = {rows_js};
const KEY = "marvelpull_done";
let done = new Set(JSON.parse(localStorage.getItem(KEY) || "[]"));
let chip = "";
const groups = [...new Set(DATA.map(c => c.grp))];
const chipbox = document.getElementById("chips");
const lastName = p => {{
  const parts = p.replace(/["'.]/g, "").split(/[\\s/-]+/);
  return (parts[parts.length - 1] || p).toLowerCase();
}};
function id(c){{return c.scan + "/" + c.pos}}
function money(x){{return "$" + (x % 1 ? x.toFixed(2) : x)}}
function drawChips(){{
  chipbox.innerHTML = "";
  const all = document.createElement("button");
  all.textContent = "All " + done.size + "/" + DATA.length;
  all.className = chip === "" ? "on" : "";
  all.onclick = () => {{ chip = ""; render(); }};
  chipbox.appendChild(all);
  for (const g of groups){{
    const rows = DATA.filter(c => c.grp === g);
    const d = rows.filter(c => done.has(id(c))).length;
    const b = document.createElement("button");
    b.textContent = g + " " + d + "/" + rows.length;
    b.className = chip === g ? "on" : "";
    b.onclick = () => {{ chip = chip === g ? "" : g; render(); }};
    chipbox.appendChild(b);
  }}
}}
function render(){{
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
  for (const c of rows){{
    if (!chip && so === "v"){{
      const band = c.typ >= 5 ? "Headliners ($5+)" : c.typ >= 3 ? "Solid ($3+)" : "Worth pulling";
      if (band !== hdr){{
        hdr = band;
        const h = document.createElement("div");
        h.className = "ghdr"; h.textContent = band;
        list.appendChild(h);
      }}
    }}
    const el = document.createElement("div");
    el.className = "row" + (done.has(id(c)) ? " done" : "");
    el.innerHTML = `<div class="cb">${{done.has(id(c)) ? "&#10003;" : ""}}</div>` +
      `<div class="info"><div class="nm">${{c.player}}</div>` +
      `<div class="ds">${{c.team}}${{c.parallel ? " &middot; " + c.parallel : ""}}</div></div>` +
      `<div class="val">${{money(c.typ)}}</div>` +
      `<div class="loc">${{c.scan}}/${{c.pos}}</div>`;
    el.onclick = () => {{
      done.has(id(c)) ? done.delete(id(c)) : done.add(id(c));
      localStorage.setItem(KEY, JSON.stringify([...done]));
      render();
    }};
    list.appendChild(el);
  }}
  document.getElementById("done").textContent = done.size;
}}
document.getElementById("copy").onclick = () => {{
  const un = DATA.filter(c => !done.has(id(c)));
  const txt = "MARVEL SINGLES PULL REPORT: " + done.size + "/" + DATA.length + " pulled. " +
    "NOT PULLED (" + un.length + "): " +
    un.map(c => id(c) + " " + c.player + " " + c.parallel).join(" | ");
  navigator.clipboard.writeText(txt).then(() => alert("Report copied — paste it to CC."));
}};
document.getElementById("reset").onclick = () => {{
  if (confirm("Clear all checkmarks?")){{ done.clear(); localStorage.setItem(KEY, "[]"); render(); }}
}};
document.getElementById("fsort").oninput = render;
document.getElementById("q").oninput = render;
render();
</script></body></html>"""

Path("docs/marvel_pull.html").write_text(singles_html)

# =================================================================== LOTS PROPOSAL PAGE
lot_rows = ""
for i, l in enumerate(lots):
    card_list = ", ".join(f'{c["character"]} ({c["scan"]}/{c["pos"]})' for c in l["cards"])
    lot_rows += f"""<div class="lotcard">
<div class="lothdr"><span class="lotnum">Lot {i+1}</span><span class="lotprice">${l['price']:.2f}</span></div>
<div class="lottitle">{l['title']}</div>
<div class="lotcards">{card_list}</div>
<div class="lotsrc">{l['source']}{' — ' + l['theme'] if l.get('theme') else ''}</div>
<label class="lotchk"><input type="checkbox" data-lot="{i}"> Pulled &amp; ready to post</label>
</div>"""

lots_html = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex">
<title>Marvel Sell-Off — Lot Proposals</title>
<style>
 body{{margin:0;{FONT}background:#f6f7fa;color:#111}}
 .wrap{{max-width:760px;margin:0 auto;padding:16px 12px 40px}}
 h1{{font-size:22px;margin:6px 0 2px}}
 .sub{{color:#667;font-size:13.5px;margin:0 0 10px}}
 .gate{{background:#fde8e8;border:2px solid #c0392b;border-radius:10px;padding:12px 14px;font-size:14px;margin:0 0 14px;line-height:1.5;font-weight:600;color:#7a1f1f}}
 .lotcard{{background:#fff;border:1px solid #dde;border-radius:12px;padding:12px 14px;margin:10px 0}}
 .lothdr{{display:flex;justify-content:space-between;align-items:center;margin-bottom:4px}}
 .lotnum{{font-size:12px;font-weight:800;color:#7b1fa2;background:#f3e5f5;padding:3px 8px;border-radius:6px}}
 .lotprice{{font-weight:800;color:#1a7f1a;font-size:16px}}
 .lottitle{{font-weight:700;font-size:15px;margin:4px 0}}
 .lotcards{{color:#556;font-size:13px;line-height:1.5}}
 .lotsrc{{color:#899;font-size:11.5px;margin-top:4px;font-style:italic}}
 .lotchk{{display:block;margin-top:8px;font-size:13px;color:#334}}
 .stats{{display:flex;gap:20px;background:#fff;border:1px solid #dde;border-radius:10px;padding:10px 14px;margin:0 0 14px;font-size:13px}}
 .stats b{{display:block;font-size:18px;color:#7b1fa2}}
</style></head><body><div class="wrap">
<h1>Marvel Sell-Off — Lot Proposals</h1>
<p class="sub">{len(lots)} proposed 5-card-max thematic lots covering {total_lot_cards} base-common characters &middot; est. value ~${total_lot_value:.2f}.</p>
<div class="gate">HOUSE RULE — nothing here is postable yet. Every lot needs JC's explicit OK + the physical cards pulled and
sleeved together before it goes to eBay. Check a lot below once you've reviewed the grouping and pulled the cards;
that's the signal to CC to post it.</div>
<div class="stats">
<div><b>{len(lots)}</b>lots proposed</div>
<div><b>{total_lot_cards}</b>cards covered</div>
<div><b>${total_lot_value:.2f}</b>est. total value</div>
</div>
{lot_rows}
</div>
<script>
document.querySelectorAll('input[type=checkbox]').forEach(cb => {{
  const key = "marvel_lot_" + cb.dataset.lot;
  cb.checked = localStorage.getItem(key) === "1";
  cb.onchange = () => localStorage.setItem(key, cb.checked ? "1" : "0");
}});
</script></body></html>"""

Path("docs/marvel_lots_proposal.html").write_text(lots_html)

# ---- sanity gate
for f in ("docs/marvel_pull.html", "docs/marvel_lots_proposal.html"):
    t = Path(f).read_text()
    assert t.count("<html") == 1 and t.count("</html>") == 1, f
print("both pages built and pass basic HTML sanity check")
