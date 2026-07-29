"""Build Mike's surprise pages: docs/mikes_card_shop.html (what landed on his
eBay, with a loud read-this-first banner) and docs/coffee_run.html (the coffee
delivery route brief). Data baked in from output/_mike_shop_cards.json and
output/_coffee_routes.json."""
import json
from pathlib import Path

cards = json.load(open("output/_mike_shop_cards.json"))
routes = json.load(open("output/_coffee_routes.json"))
total = sum(float(c["price"]) for c in cards)

FONT = "font-family:'Avenir Next','Segoe UI',system-ui,sans-serif;"

# ---------------------------------------------------------------- coffee page
wawa_rows = ""
for w in sorted(routes["wawas"], key=lambda x: x["detour_min"]):
    d = w["detour_min"]
    verdict = ("literally nothing, Michael" if d < 2 else
               "a rounding error" if d < 3 else
               "ok this one is a hike, skip it")
    wawa_rows += (f"<tr><td>{w['name'].replace('Wawa - ','')}</td>"
                  f"<td>{w['with_coffee_min']} min</td><td>{w['direct_min']} min</td>"
                  f"<td class='detour'>+{d} min</td><td>{verdict}</td></tr>")

legs = routes["legs"]
pts = routes["points"]
gmaps = ("https://www.google.com/maps/dir/203+Chapman+Ave,+Lansdowne,+PA+19050/"
         "Wawa,+8240+West+Chester+Pike,+Upper+Darby,+PA/"
         "236+Crosshill+Rd,+Wynnewood,+PA+19096/"
         "35+Cricket+Ave,+Ardmore,+PA+19003")

coffee = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex">
<title>Operation Coffee Drop — a briefing for Mike</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
<style>
 body{{margin:0;{FONT}background:#fdf8f2;color:#2b2118;line-height:1.55}}
 .wrap{{max-width:860px;margin:0 auto;padding:24px 16px 64px}}
 h1{{font-size:2rem;margin:.2em 0}} h2{{margin-top:2em;border-bottom:3px solid #c96f2e;padding-bottom:4px}}
 .urgent{{background:#7a1f1f;color:#fff;padding:14px 18px;border-radius:10px;font-weight:700;letter-spacing:.02em}}
 .mission{{background:#fff;border:2px dashed #c96f2e;border-radius:12px;padding:18px 20px;margin:18px 0}}
 table{{border-collapse:collapse;width:100%;font-size:.92rem}}
 th,td{{padding:8px 10px;border-bottom:1px solid #e3d5c3;text-align:left}}
 th{{background:#f3e7d7}} .detour{{font-weight:800;color:#7a1f1f}}
 #map{{height:420px;border-radius:12px;border:2px solid #c96f2e;margin:16px 0}}
 .btn{{display:inline-block;background:#c96f2e;color:#fff;text-decoration:none;padding:12px 20px;border-radius:8px;font-weight:700;margin:8px 8px 0 0}}
 .legend span{{display:inline-block;margin-right:18px}}
 .swatch{{display:inline-block;width:26px;height:5px;border-radius:3px;vertical-align:middle;margin-right:6px}}
 .fine{{font-size:.8rem;color:#8a7663}}
</style></head><body><div class="wrap">
<p class="urgent">OFFICIAL BRIEFING — EYES ONLY: MICHAEL, 203 CHAPMAN AVE. SUBJECT: A MAN IS WITHOUT COFFEE.</p>
<h1>Operation Coffee Drop</h1>
<p>Mike. Before you get excited about your fancy new eBay store (and you should — go back and look after this), there is a
humanitarian situation developing at 236 Crosshill Road.</p>
<div class="mission">
<p><strong>The situation:</strong> Jason is trapped in an <strong>8-hour Webex</strong>. He is <strong>out of coffee</strong>.
Both of these things are true at the same time, which scientists agree should not be legal.</p>
<p><strong>The mission:</strong> On your way to work, you stop at Wawa (which, let's be honest, you were doing anyway),
grab <em>one additional coffee</em>, and deliver it to 236 Crosshill Road, Wynnewood.</p>
<p><strong>The screen-door protocol:</strong> Jason may be asleep, on mute, or pretending to take notes. Do NOT knock.
Do NOT ring. Simply open the screen door, place the coffee inside like the gentle hero you are, and walk away.
He will be forever thankful. Possibly emotional.</p>
</div>
<h2>The math (you have no excuse)</h2>
<p>Your normal commute from Chapman Ave to Beyond Hello is about <strong>{routes['baseline_min']} minutes</strong>.
Here is exactly what playing hero costs you, per Wawa, versus going from that same Wawa straight to work like a man
who lets his friends suffer:</p>
<table><tr><th>Wawa</th><th>With coffee drop</th><th>Straight to work</th><th>Out of your way</th><th>Analysis</th></tr>
{wawa_rows}</table>
<p>Recommended play: the <strong>West Chester Pike Wawa</strong>. The coffee drop costs you
<strong>{routes['wawas'][1]['detour_min']} minutes</strong>. You spend longer than that deciding which Sizzli to get.</p>
<h2>The route</h2>
<div class="legend"><span><i class="swatch" style="background:#1d6f42"></i>The Hero Route (home → Wawa → screen door → work)</span>
<span><i class="swatch" style="background:#7a1f1f"></i>The Heartless Route (Wawa → work, no coffee for Jason)</span></div>
<div id="map"></div>
<a class="btn" href="{gmaps}" target="_blank">Open the Hero Route in Google Maps</a>
<a class="btn" style="background:#2b2118" href="mikes_card_shop.html">OK fine — now show me my card shop</a>
<p class="fine">Drive times courtesy of OSRM. Guilt courtesy of Jason. No coffee was harmed in the making of this page — that's the problem.</p>
</div>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script>
const legs = {json.dumps({k: v["geom"] for k, v in legs.items()})};
const pts = {json.dumps(pts)};
const map = L.map('map');
L.tileLayer('https://tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png',{{attribution:'&copy; OpenStreetMap'}}).addTo(map);
const hero = {{color:'#1d6f42',weight:5}};
const cold = {{color:'#7a1f1f',weight:4,dashArray:'8 8'}};
const g = [];
for (const k of ['mike_wawa','wawa_jc','jc_bh']) g.push(L.geoJSON(legs[k],{{style:hero}}).addTo(map));
g.push(L.geoJSON(legs['wawa_bh_direct'],{{style:cold}}).addTo(map));
const mk = (p,label) => L.marker([p[0],p[1]]).addTo(map).bindPopup(label);
mk(pts.mike,"Mike's house — the journey begins");
mk(pts.wawa,"Wawa, 8240 West Chester Pike — buy TWO coffees");
mk(pts.jc,"236 Crosshill Rd — THE SCREEN DOOR. Gently.");
mk(pts.bh,"Beyond Hello, Ardmore — arrive a hero, {legs['wawa_jc']['dur_min']:.0f}-ish min later than the coward's path");
map.fitBounds(L.featureGroup(g).getBounds().pad(0.12));
</script></body></html>"""

# ------------------------------------------------------------------ shop page
card_html = ""
for c in cards:
    pic = c["pic"] or ""
    card_html += f"""<a class="card" href="https://www.ebay.com/itm/{c['mike_id']}" target="_blank">
<img src="{pic}" alt="{c['title']}" loading="lazy">
<div class="cbody"><div class="ctitle">{c['title']}</div>
<div class="cprice">${float(c['price']):.2f}</div>
<div class="cid">Live on your eBay — item {c['mike_id']}</div></div></a>"""

shop = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex">
<title>Mike's Card Shop — grand opening</title>
<style>
 body{{margin:0;{FONT}background:#f6f7fb;color:#1c2330;line-height:1.5}}
 .wrap{{max-width:960px;margin:0 auto;padding:24px 16px 64px}}
 .stop{{display:block;background:#7a1f1f;color:#fff;text-decoration:none;border-radius:14px;
   padding:22px 24px;margin-bottom:28px;box-shadow:0 6px 18px rgba(122,31,31,.35);
   border:3px solid #fff;outline:3px solid #7a1f1f;animation:pulse 1.6s infinite}}
 @keyframes pulse{{0%,100%{{transform:scale(1)}}50%{{transform:scale(1.015)}}}}
 .stop b{{display:block;font-size:1.5rem;letter-spacing:.03em}}
 .stop span{{opacity:.92}}
 h1{{font-size:2.1rem;margin:.2em 0}}
 .lede{{font-size:1.05rem;max-width:46em}}
 .grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(210px,1fr));gap:16px;margin-top:24px}}
 .card{{background:#fff;border-radius:12px;overflow:hidden;text-decoration:none;color:inherit;
   border:1px solid #dfe3ee;transition:transform .15s}} .card:hover{{transform:translateY(-3px)}}
 .card img{{width:100%;aspect-ratio:3/4;object-fit:contain;background:#eef0f6}}
 .cbody{{padding:10px 12px 14px}} .ctitle{{font-size:.85rem;font-weight:600;min-height:3.4em}}
 .cprice{{font-size:1.15rem;font-weight:800;color:#1d6f42;margin-top:6px}}
 .cid{{font-size:.72rem;color:#8b93a7;margin-top:4px}}
 .stats{{display:flex;gap:28px;flex-wrap:wrap;background:#fff;border:1px solid #dfe3ee;border-radius:12px;padding:16px 20px;margin:20px 0}}
 .stats div b{{display:block;font-size:1.5rem}}
 .btn{{display:inline-block;background:#1c2330;color:#fff;text-decoration:none;padding:12px 20px;border-radius:8px;font-weight:700;margin-top:14px}}
 .fine{{font-size:.82rem;color:#8b93a7;margin-top:28px}}
</style></head><body><div class="wrap">
<a class="stop" href="coffee_run.html">
<b>STOP. DO NOT SCROLL. READ THIS FIRST.</b>
<span>Yes, there is a surprise below. No, you may not look at it yet. There is a time-sensitive humanitarian
briefing you must read before you are emotionally ready for this page. Tap here. It takes 90 seconds.
The cards will still be here. Jason's will to live may not.</span></a>
<h1>Welcome to Mike's Card Shop</h1>
<p class="lede">Surprise, buddy. While you were sleeping, your eBay account (<strong>mikeboy-40</strong>) quietly
became a functioning sports card business. Ten football cards from the harpua2001 vault were hand-picked
(read: an algorithm picked them and Jason nodded) and are now <strong>live on your account</strong>. Every card
below links to your actual listing. When something sells, Jason ships it — the cards live at his place, which
is convenient, because so does the screen door you're about to read about.</p>
<div class="stats">
<div><b>10</b>cards live</div>
<div><b>${total:.2f}</b>total list value</div>
<div><b>2</b>Travis Hunter rookies</div>
<div><b>1</b>Jalen Hurts SB MVP (you're welcome)</div>
</div>
<a class="btn" href="https://www.ebay.com/sch/mikeboy-40/m.html" target="_blank">See your whole store on eBay</a>
<div class="grid">{card_html}</div>
<p class="fine">Powered by the same machinery that runs harpua2001. This was a live-fire test of your API token —
it passed. Next stop: the Whatnot empire. Questions, complaints, and coffee-delivery confirmations to Jason.</p>
</div></body></html>"""

Path("docs/coffee_run.html").write_text(coffee)
Path("docs/mikes_card_shop.html").write_text(shop)
print("built docs/coffee_run.html", len(coffee), "bytes")
print("built docs/mikes_card_shop.html", len(shop), "bytes")
