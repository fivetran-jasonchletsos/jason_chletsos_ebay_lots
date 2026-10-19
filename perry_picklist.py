#!/usr/bin/env python3
"""perry_picklist.py — price a scanned card batch for a bulk buyer and build a
filterable pick list.

Context: a buyer wants every card worth over $10. JC scans cards into a folder
(default ~/Downloads/Perry) with an fi-8170 (Image Capture), labeled with a
batch prefix (default "PP_001"); the trailing number is the scan sequence.

This script:
  1. Intake: keeps the SEQ stream ("<prefix> N.jpeg"), DISCARDS the dual-named
     duplicates ("<prefix> N k.jpeg") per the fi-8170 rule. Fronts = ODD seq
     numbers, backs = even (validated on the 2026-10-18 giveaway pilot: odd=front,
     even=back globally, seq1 a lone orphan front). This scanner also flips faces
     180, so each front is rotated upright before ID + display.
  2. Identify each card via the live Lambda appraiser (trading-card path).
  3. Price with REAL SportsCardsPro comps via card_price_agent.price_listing
     (raw/ungraded price = the card's value basis). The nova-lite estimate is
     NOT used for the price (the pilot proved it returns flat bucket noise).
  4. Resumable: results keyed by front filename in output/perry_picklist_results.json,
     so re-running after more scans only processes new fronts.
  5. Output: docs/perry_picklist.html — a pick list you filter by min price
     (default $10) and sort by value, with each card's image, title, SCP price,
     confidence, SCP link, and a KEEP/HOLD flag for Giants/Mets/76ers.

NOTE: this PRICES and lists only. It never posts to eBay and never sells — it's a
pick list for JC to work the buyer deal from.

Usage:
  python3 perry_picklist.py                       # full current batch
  python3 perry_picklist.py --limit 5             # quick test on 5 cards
  python3 perry_picklist.py --dir ~/Downloads/Perry --prefix PP_001
  python3 perry_picklist.py --rebuild-html        # just regenerate the page from existing results
"""
import argparse
import base64
import html
import io
import json
import os
import re
import time
import urllib.request
from pathlib import Path

import statistics

import requests
from PIL import Image

import card_price_agent as cpa
import promote

BROWSE_URL = "https://api.ebay.com/buy/browse/v1/item_summary/search"
OWN_SELLER = "harpua2001"
_LOT_RE = re.compile(r"\b(lot|lots|bundle|bulk|you pick|complete set|\d+\s*cards?)\b", re.I)


def ebay_price(token: str, title: str) -> dict:
    """Price a card from eBay ACTIVE listings (Browse API) — asking-price comps.
    Returns {price (median), n, low, high} using the matched active listings,
    excluding our own store and obvious lot/bundle listings. Asking prices skew
    a bit high vs sold, but they're a free, already-authorized ballpark good
    enough to sort >$10 vs under while PriceCharting is down."""
    q = " ".join((title or "").split())[:350]
    if not q:
        return {"price": None, "n": 0}
    params = {
        "q": q,
        "limit": "60",
        "filter": "buyingOptions:{FIXED_PRICE},itemLocationCountry:US,price:[1..],priceCurrency:USD",
    }
    headers = {"Authorization": f"Bearer {token}", "X-EBAY-C-MARKETPLACE-ID": "EBAY_US"}
    try:
        r = requests.get(BROWSE_URL, params=params, headers=headers, timeout=20)
        r.raise_for_status()
    except requests.RequestException:
        return {"price": None, "n": 0}
    prices = []
    for it in (r.json().get("itemSummaries") or []):
        seller = ((it.get("seller") or {}).get("username") or "").lower()
        if seller == OWN_SELLER:
            continue
        if _LOT_RE.search(it.get("title") or ""):
            continue
        try:
            p = float((it.get("price") or {}).get("value") or 0)
        except (TypeError, ValueError):
            continue
        if p > 0:
            prices.append(p)
    if not prices:
        return {"price": None, "n": 0}
    prices.sort()
    return {
        "price": round(statistics.median(prices), 2),
        "n": len(prices),
        "low": prices[0],
        "high": prices[-1],
    }

REPO = Path(__file__).parent
LAMBDA_URL = "https://jw0hur2091.execute-api.us-east-1.amazonaws.com/ebay/upload-photos"
RESULTS = REPO / "output" / "perry_picklist_results.json"
IMG_DIR = REPO / "output" / "perry_picklist_imgs"
HTML_OUT = REPO / "docs" / "perry_picklist.html"


def is_held(title: str) -> str:
    """Return a hold label if the card is on a KEEP team (don't sell) — NY Giants
    (not SF), NY Mets, Philadelphia 76ers/Sixers — else ''."""
    t = (title or "").lower()
    if "76ers" in t or "sixers" in t:
        return "76ers (son)"
    if "mets" in t:
        return "NY Mets (keep)"
    if "giants" in t and "san francisco" not in t and "sf giant" not in t:
        return "NY Giants (keep)"
    return ""


def seq_fronts(folder: Path, prefix: str):
    """Return [(front_num, front_path, back_path_or_None)] for the batch.
    Fronts = odd seq numbers; back of front N is N-1 (even); discards dual files."""
    seq = {}
    pat = re.compile(r"^" + re.escape(prefix) + r" (\d+)\.jpe?g$", re.I)
    for f in folder.iterdir():
        m = pat.match(f.name)
        if m:
            seq[int(m.group(1))] = f
    out = []
    for n in sorted(seq):
        if n % 2 == 1:  # odd = front
            back = seq.get(n - 1) if n > 1 else None
            out.append((n, seq[n], back))
    return out


def to_dataurl(path: Path, rotate180: bool = True, maxdim: int = 1280) -> str:
    im = Image.open(path).convert("RGB")
    if rotate180:
        im = im.rotate(180)
    w, h = im.size
    if max(w, h) > maxdim:
        s = maxdim / max(w, h)
        im = im.resize((round(w * s), round(h * s)))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=82)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def save_thumb(path: Path, out_path: Path, rotate180: bool = True, maxdim: int = 700):
    im = Image.open(path).convert("RGB")
    if rotate180:
        im = im.rotate(180)
    w, h = im.size
    if max(w, h) > maxdim:
        s = maxdim / max(w, h)
        im = im.resize((round(w * s), round(h * s)))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    im.save(out_path, "JPEG", quality=80)


def identify(front_path: Path, back_path):
    body = {"image": to_dataurl(front_path)}
    if back_path:
        try:
            body["back"] = to_dataurl(back_path)
        except Exception:
            pass
    req = urllib.request.Request(
        LAMBDA_URL, data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=str(Path.home() / "Downloads" / "Perry"))
    ap.add_argument("--prefix", default="PP_001")
    ap.add_argument("--min-price", type=float, default=10.0, help="default filter on the page")
    ap.add_argument("--limit", type=int, default=0, help="process at most N new fronts (0 = all)")
    ap.add_argument("--rebuild-html", action="store_true", help="only regenerate the HTML from saved results")
    ap.add_argument("--source", choices=["ebay", "scp"], default="ebay",
                    help="price source: ebay=active-listing comps (free, default); scp=SportsCardsPro (needs valid token)")
    ap.add_argument("--reprice", action="store_true",
                    help="re-price already-identified cards that have no price yet (no re-ID / no vision cost). "
                         "Run this after a price source comes back up.")
    args = ap.parse_args()

    results = json.loads(RESULTS.read_text()) if RESULTS.exists() else {}

    if not args.rebuild_html:
        folder = Path(os.path.expanduser(args.dir))
        if not folder.exists():
            print(f"ERROR: {folder} not found")
            return 1
        if args.source == "scp":
            token = cpa.load_token()
        else:
            cfg = json.loads((REPO / "configuration.json").read_text())
            token = promote.get_app_token(cfg)
        # Reprice pass: fill in prices for already-identified cards that have
        # none yet (price source was down when they were scanned). No vision.
        if args.reprice:
            need = [r for r in results.values()
                    if r.get("title") and not isinstance(r.get("price"), (int, float))]
            print(f"reprice: {len(need)} identified cards missing a price")
            for j, r in enumerate(need, 1):
                title = r["title"]
                if args.source == "scp":
                    pi = cpa.price_listing({"title": title}, token)
                    r["price"] = (pi or {}).get("actual_price")
                    if pi:
                        r["grades"] = pi.get("grades"); r["scp_url"] = pi.get("scp_url")
                        r["scp_confidence"] = pi.get("confidence")
                else:
                    ep = ebay_price(token, title)
                    r["price"] = ep.get("price"); r["comps"] = ep.get("n")
                    r["comp_low"] = ep.get("low"); r["comp_high"] = ep.get("high")
                r["price_source"] = args.source
                if j % 25 == 0 or j == len(need):
                    RESULTS.write_text(json.dumps(results, indent=2))
                    print(f"  repriced {j}/{len(need)}")
                time.sleep(0.2)
            RESULTS.write_text(json.dumps(results, indent=2))
            render_html(results, args.min_price)
            priced = [r for r in results.values() if isinstance(r.get("price"), (int, float))]
            print(f"reprice done. {len(priced)} now priced. Pick list: {HTML_OUT}")
            return 0

        if args.prefix.upper() == "ALL":
            prefixes = sorted({m.group(0) for f in folder.iterdir()
                               if (m := re.match(r"PP_\d+", f.name))})
            fronts = []
            for pre in prefixes:
                fronts.extend(seq_fronts(folder, pre))
            print(f"batches found: {', '.join(prefixes)}")
        else:
            fronts = seq_fronts(folder, args.prefix)
        todo = [(n, fp, bp) for (n, fp, bp) in fronts if fp.name not in results]
        if args.limit:
            todo = todo[: args.limit]
        print(f"batch {args.prefix}: {len(fronts)} cards, {len(results)} already done, processing {len(todo)}")

        for idx, (n, fp, bp) in enumerate(todo, 1):
            rec = {"front_file": fp.name, "seq": n, "back_file": bp.name if bp else None}
            try:
                resp = identify(fp, bp)
                card = resp.get("card") or {}
                title = (card.get("ebay_title") or "").strip()
                rec["title"] = title
                rec["player"] = card.get("player")
                rec["set"] = card.get("set_name")
                rec["year"] = card.get("year")
                rec["identified"] = bool(resp.get("identified"))
                # Price the card
                rec["price_source"] = args.source
                if not title:
                    rec["price"] = None
                elif args.source == "scp":
                    pi = cpa.price_listing({"title": title}, token)
                    if pi:
                        rec["price"] = pi.get("actual_price")
                        rec["grades"] = pi.get("grades")
                        rec["scp_url"] = pi.get("scp_url")
                        rec["scp_confidence"] = pi.get("confidence")
                        rec["matched"] = pi.get("matched_product")
                    else:
                        rec["price"] = None
                else:  # ebay active-comp median
                    ep = ebay_price(token, title)
                    rec["price"] = ep.get("price")
                    rec["comps"] = ep.get("n")
                    rec["comp_low"] = ep.get("low")
                    rec["comp_high"] = ep.get("high")
                rec["hold"] = is_held(title)
                img_rel = f"perry_picklist_imgs/{fp.stem}.jpg"
                save_thumb(fp, REPO / "output" / img_rel)
                rec["image"] = img_rel
                rec["status"] = "ok"
            except Exception as exc:
                rec["status"] = "error"
                rec["error"] = str(exc)[:200]
            results[fp.name] = rec
            if idx % 10 == 0 or idx == len(todo):
                RESULTS.write_text(json.dumps(results, indent=2))
                print(f"  {idx}/{len(todo)} done ({rec.get('title','')[:50]} -> {rec.get('price')})")
            time.sleep(0.2)
        RESULTS.write_text(json.dumps(results, indent=2))

    render_html(results, args.min_price)
    priced = [r for r in results.values() if isinstance(r.get("price"), (int, float))]
    over = [r for r in priced if r["price"] >= args.min_price and not r.get("hold")]
    print(f"\nDONE. {len(results)} cards processed, {len(priced)} priced, "
          f"{len(over)} over ${args.min_price:.0f} (excl. holds).")
    print(f"Pick list: {HTML_OUT}")
    return 0


def render_html(results: dict, default_min: float):
    cards = sorted(
        results.values(),
        key=lambda r: (r.get("price") if isinstance(r.get("price"), (int, float)) else -1),
        reverse=True,
    )
    rows = []
    for r in cards:
        price = r.get("price")
        pnum = price if isinstance(price, (int, float)) else -1
        price_lbl = f"${price:,.2f}" if isinstance(price, (int, float)) else "—"
        hold = r.get("hold") or ""
        conf = r.get("scp_confidence")
        conf_lbl = f"{conf:.2f}" if isinstance(conf, (int, float)) else ""
        img = html.escape("../output/" + r.get("image")) if r.get("image") else ""
        title = html.escape(r.get("title") or "(unidentified)")
        scp = r.get("scp_url") or ""
        rows.append(f"""
      <tr class="card" data-price="{pnum}" data-hold="{1 if hold else 0}">
        <td class="thumbcell">{f'<img src="{img}" loading="lazy">' if img else ''}</td>
        <td class="pricecell">{price_lbl}</td>
        <td class="titlecell">{title}{f'<span class="hold">{html.escape(hold)}</span>' if hold else ''}
            {f'<a class="scp" href="{html.escape(scp)}" target="_blank" rel="noopener">SCP &#8599;</a>' if scp else ''}</td>
        <td class="confcell">{conf_lbl}</td>
      </tr>""")
    body = "".join(rows)
    n = len(cards)
    HTML_OUT.parent.mkdir(parents=True, exist_ok=True)
    HTML_OUT.write_text(f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Perry Buy List — priced cards</title>
<style>
  :root{{--bg:#0c0e13;--surf:#151924;--line:rgba(255,255,255,.09);--ink:#eef2f8;--mut:#9aa6b8;--dim:#6b7688;--gold:#e3b23c;--green:#3fd27e}}
  *{{box-sizing:border-box;margin:0;padding:0}}
  body{{background:var(--bg);color:var(--ink);font-family:Inter,system-ui,-apple-system,sans-serif;padding:0 0 60px}}
  header{{position:sticky;top:0;z-index:5;background:rgba(12,14,19,.95);backdrop-filter:blur(10px);border-bottom:1px solid var(--line);padding:14px 18px}}
  h1{{font-size:18px;font-weight:700}}
  .sub{{color:var(--mut);font-size:13px;margin-top:2px}}
  .controls{{display:flex;gap:16px;align-items:center;flex-wrap:wrap;margin-top:12px}}
  .controls label{{font-size:13px;color:var(--mut);display:flex;align-items:center;gap:8px}}
  .controls input[type=number]{{width:90px;background:var(--surf);border:1px solid var(--line);color:var(--ink);border-radius:8px;padding:7px 10px;font-size:14px;font-weight:600}}
  .controls .count{{color:var(--green);font-weight:700;font-size:14px}}
  .controls .tot{{color:var(--gold);font-weight:700}}
  .controls button{{background:var(--surf);border:1px solid var(--line);color:var(--ink);border-radius:8px;padding:7px 12px;font-size:12.5px;font-weight:600;cursor:pointer}}
  .controls button.on{{background:var(--gold);color:#1a1205;border-color:var(--gold)}}
  table{{width:100%;max-width:1000px;margin:14px auto;border-collapse:collapse;padding:0 12px}}
  td{{border-bottom:1px solid var(--line);padding:9px 10px;vertical-align:middle}}
  .thumbcell{{width:70px}} .thumbcell img{{width:60px;height:80px;object-fit:cover;border-radius:5px;display:block;background:var(--surf)}}
  .pricecell{{font-weight:800;font-size:17px;color:var(--green);white-space:nowrap;width:92px}}
  .titlecell{{font-size:14px;line-height:1.35}}
  .hold{{display:inline-block;margin-left:8px;font-size:10.5px;font-weight:700;color:#ffb3b3;background:rgba(255,80,80,.14);border:1px solid rgba(255,80,80,.35);border-radius:999px;padding:1px 8px;text-transform:uppercase;letter-spacing:.04em}}
  .scp{{margin-left:8px;font-size:11px;color:var(--mut)}}
  .confcell{{color:var(--dim);font-size:12px;width:48px;text-align:right}}
  tr.hidden{{display:none}}
</style></head><body>
<header>
  <h1>Perry Buy List</h1>
  <div class="sub">{n} cards priced via SportsCardsPro (raw/ungraded). Sorted high to low. Holds (Giants/Mets/76ers) flagged.</div>
  <div class="controls">
    <label>Min price $ <input type="number" id="min" value="{default_min:.0f}" min="0" step="1"></label>
    <button id="holdBtn" class="on">Hide holds</button>
    <span class="count" id="count"></span>
    <span>·</span><span>Total value: <span class="tot" id="total"></span></span>
  </div>
</header>
<table><tbody id="rows">{body}</tbody></table>
<script>
  var rows = Array.prototype.slice.call(document.querySelectorAll('tr.card'));
  var minEl=document.getElementById('min'), holdBtn=document.getElementById('holdBtn'),
      countEl=document.getElementById('count'), totalEl=document.getElementById('total');
  var hideHolds=true;
  function apply(){{
    var min=parseFloat(minEl.value)||0, shown=0, total=0;
    rows.forEach(function(r){{
      var p=parseFloat(r.dataset.price), hold=r.dataset.hold==='1';
      var ok = p>=min && !(hideHolds&&hold);
      r.classList.toggle('hidden', !ok);
      if(ok){{ shown++; if(p>0) total+=p; }}
    }});
    countEl.textContent = shown+' cards';
    totalEl.textContent = '$'+total.toLocaleString(undefined,{{minimumFractionDigits:2,maximumFractionDigits:2}});
  }}
  minEl.addEventListener('input', apply);
  holdBtn.addEventListener('click', function(){{ hideHolds=!hideHolds; holdBtn.classList.toggle('on',hideHolds); holdBtn.textContent=hideHolds?'Hide holds':'Show holds'; apply(); }});
  apply();
</script>
</body></html>""")


if __name__ == "__main__":
    raise SystemExit(main())
