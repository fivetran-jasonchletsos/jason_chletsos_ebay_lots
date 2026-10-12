"""marketplace_drafts.py — generate ready-to-paste Facebook Marketplace listing
drafts from our live eBay listings.

WHY THIS EXISTS (and why it is NOT a bot):
  Facebook Marketplace has no sanctioned public API for posting individual
  listings of general goods (trading cards). The only way to "auto-post" is a
  browser bot driving a logged-in session, which violates Facebook's ToS /
  Commerce Policies and gets accounts checkpointed or banned. So we do NOT post
  automatically. Instead we automate the *prep*: this emits each card's
  Marketplace-ready Title / Price / Category / Condition / Description + its
  photo, so the seller pastes a listing into Marketplace's Create flow in
  seconds. The posting click stays human = the account stays safe.

  The compliant *automatic* surface already exists separately (meta_feed.py ->
  Facebook/Instagram Shop catalog). This script is the complement for true
  peer-to-peer Marketplace local listings.

SOURCE: output/listings_snapshot.json — every live listing carries a public
  eBay image URL `pic`, an `item_id`, `title`, `price`, `desc`, `quantity`.

OUTPUT:
  * output/marketplace_drafts.json  — structured drafts (for other tooling)
  * docs/marketplace_drafts.html    — a copy-button dashboard the seller works
    through (highest-value cards first), with a "Create listing" deep link.

Holds: screens out NY Giants (NFL) / NY Mets / Philadelphia 76ers titles, same
belt-and-suspenders guard as meta_feed.py. Honors the $4 floor by default.

USAGE:
  python3 marketplace_drafts.py                 # top 100 cards by price -> drafts + html
  python3 marketplace_drafts.py --all           # every eligible listing
  python3 marketplace_drafts.py --limit 250     # top 250 by price
  python3 marketplace_drafts.py --min-price 10  # only $10+ cards
"""
import argparse
import html
import json
from pathlib import Path

SNAP = Path("output/listings_snapshot.json")
OUT_JSON = Path("output/marketplace_drafts.json")
OUT_HTML = Path("docs/marketplace_drafts.html")

# Facebook Marketplace create-listing deep link (opens the item form).
FB_CREATE_URL = "https://www.facebook.com/marketplace/create/item"
# Marketplace category + condition most trading-card singles map to.
DEFAULT_CATEGORY = "Toys & Games"
DEFAULT_CONDITION = "Used - Like New"


def is_held(title: str) -> bool:
    """True if the title belongs to a held team we never list: NY Giants (NFL);
    NY Mets; Philadelphia 76ers / Sixers. (SF Giants baseball is fine.)"""
    t = (title or "").lower()
    if "76ers" in t or "sixers" in t:
        return True
    if "mets" in t:
        return True
    if "giants" in t and "san francisco" not in t and "sf giants" not in t:
        return True
    return False


def make_title(title: str) -> str:
    """Marketplace titles cap at 150 chars; keep it tidy."""
    t = " ".join((title or "").split())
    return t[:150]


def make_description(title: str, price: float, desc: str) -> str:
    """A clean, buyer-friendly Marketplace description. Local-sale framing;
    we do not push buyers to eBay here (this surface is for local/FB buyers)."""
    t = " ".join((title or "").split())
    lines = [
        t,
        "",
        "Raw (ungraded) trading card — the exact card pictured is what you get.",
        "Stored in a penny sleeve + top-loader and shipped protected. Local "
        "pickup / meetup also welcome.",
        f"Asking ${price:.0f}. Bundle deals if you grab a few — just ask!",
    ]
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description="Generate Facebook Marketplace listing drafts.")
    ap.add_argument("--min-price", type=float, default=4.0,
                    help="Only include listings at or above this price (default 4.0 = our floor).")
    ap.add_argument("--limit", type=int, default=100,
                    help="Max drafts to emit, highest price first (default 100).")
    ap.add_argument("--all", action="store_true",
                    help="Emit every eligible listing (overrides --limit).")
    args = ap.parse_args()

    if not SNAP.exists():
        print(f"ERROR: {SNAP} not found — run the listings snapshot refresh first.")
        return 1

    data = json.loads(SNAP.read_text())
    items = data if isinstance(data, list) else data.get("listings", data.get("items", []))

    drafts = []
    skipped_held = skipped_noimg = skipped_cheap = 0
    for it in items:
        title = (it.get("title") or "").strip()
        pic = (it.get("pic") or "").strip()
        iid = str(it.get("item_id") or "").strip()
        try:
            price = float(it.get("price") or 0)
        except (TypeError, ValueError):
            price = 0.0
        if not title:
            continue
        if is_held(title):
            skipped_held += 1
            continue
        if not pic:
            skipped_noimg += 1
            continue
        if price < args.min_price:
            skipped_cheap += 1
            continue
        drafts.append({
            "title": make_title(title),
            "price": round(price, 2),
            "price_label": f"${price:.0f}",
            "category": DEFAULT_CATEGORY,
            "condition": DEFAULT_CONDITION,
            "description": make_description(title, price, it.get("desc", "")),
            "image_url": pic,
            "ebay_url": f"https://www.ebay.com/itm/{iid}" if iid else "",
            "item_id": iid,
        })

    # Highest value first — that's the order worth a human's posting time.
    drafts.sort(key=lambda d: d["price"], reverse=True)
    if not args.all:
        drafts = drafts[: args.limit]

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(drafts, indent=2))

    OUT_HTML.parent.mkdir(parents=True, exist_ok=True)
    OUT_HTML.write_text(render_html(drafts))

    print(f"Marketplace drafts: {len(drafts)} cards")
    print(f"  skipped: {skipped_cheap} under ${args.min_price:.0f}, "
          f"{skipped_held} held (Giants/Mets/76ers), {skipped_noimg} no image")
    print(f"  wrote {OUT_JSON} + {OUT_HTML}")
    return 0


def render_html(drafts) -> str:
    rows = []
    for i, d in enumerate(drafts):
        t = html.escape(d["title"])
        desc = html.escape(d["description"])
        desc_js = json.dumps(d["description"])
        title_js = json.dumps(d["title"])
        price_js = json.dumps(d["price_label"])
        img = html.escape(d["image_url"])
        price = html.escape(d["price_label"])
        cat = html.escape(d["category"])
        cond = html.escape(d["condition"])
        rows.append(f"""
      <article class="card" data-i="{i}">
        <div class="thumb"><img src="{img}" alt="" loading="lazy"></div>
        <div class="body">
          <div class="chips"><span class="chip price">{price}</span><span class="chip">{cat}</span><span class="chip">{cond}</span></div>
          <div class="fl">Title</div>
          <div class="val title">{t}</div>
          <button class="copy" onclick='cp(this,{title_js})'>Copy title</button>
          <div class="fl">Description</div>
          <div class="val desc">{desc}</div>
          <button class="copy" onclick='cp(this,{desc_js})'>Copy description</button>
          <div class="acts">
            <a class="dl" href="{img}" target="_blank" rel="noopener" download>Open / save photo &#8599;</a>
            <button class="copy all" onclick='cpAll(this,{title_js},{price_js},{desc_js})'>Copy all</button>
          </div>
        </div>
      </article>""")
    cards = "".join(rows)
    n = len(drafts)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="theme-color" content="#0b0d12">
<title>Marketplace Drafts — Harpua2001</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
  :root{{--bg:#0b0d12;--surf:#141821;--surf2:#1b202b;--ink:#eef2f8;--mut:#9aa6b8;--dim:#6b7688;
    --accent:#2d7bf6;--accent2:#49d0a0;--line:rgba(255,255,255,.08);--r:12px;}}
  *{{box-sizing:border-box;margin:0;padding:0}}
  body{{background:var(--bg);color:var(--ink);font-family:'Inter',system-ui,sans-serif;line-height:1.55;padding:0 0 60px}}
  header{{position:sticky;top:0;z-index:10;background:rgba(11,13,18,.92);backdrop-filter:blur(10px);
    border-bottom:1px solid var(--line);padding:16px 20px;display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap}}
  header h1{{font-size:18px;font-weight:700;letter-spacing:-.01em}}
  header .sub{{color:var(--mut);font-size:13px}}
  header a.new{{background:var(--accent);color:#fff;text-decoration:none;font-weight:600;font-size:13px;padding:9px 15px;border-radius:999px}}
  header a.new:hover{{filter:brightness(1.1)}}
  .note{{max-width:900px;margin:18px auto 6px;padding:0 20px;color:var(--mut);font-size:13.5px}}
  .grid{{max-width:900px;margin:10px auto;padding:0 20px;display:grid;gap:16px}}
  .card{{display:grid;grid-template-columns:120px 1fr;gap:16px;background:var(--surf);border:1px solid var(--line);border-radius:var(--r);padding:14px}}
  @media(max-width:560px){{.card{{grid-template-columns:1fr}}}}
  .thumb{{aspect-ratio:3/4;background:var(--surf2);border-radius:8px;overflow:hidden}}
  .thumb img{{width:100%;height:100%;object-fit:cover;display:block}}
  .chips{{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:10px}}
  .chip{{font-size:11px;font-weight:600;color:var(--mut);background:var(--surf2);border:1px solid var(--line);border-radius:999px;padding:3px 10px}}
  .chip.price{{color:#0a0f06;background:var(--accent2);border-color:var(--accent2)}}
  .fl{{font-size:10.5px;letter-spacing:.14em;text-transform:uppercase;color:var(--dim);margin:8px 0 3px;font-weight:600}}
  .val{{background:var(--surf2);border:1px solid var(--line);border-radius:8px;padding:9px 11px;font-size:13.5px;white-space:pre-wrap}}
  .val.title{{font-weight:600}}
  .copy{{margin-top:6px;background:var(--surf2);border:1px solid var(--line);color:var(--ink);font-size:12px;font-weight:600;
    padding:6px 12px;border-radius:999px;cursor:pointer;font-family:inherit}}
  .copy:hover{{border-color:var(--accent)}}
  .copy.done{{background:var(--accent2);color:#0a0f06;border-color:var(--accent2)}}
  .acts{{display:flex;align-items:center;gap:10px;margin-top:12px;flex-wrap:wrap}}
  .acts .dl{{color:var(--accent);font-size:12.5px;font-weight:600;text-decoration:none}}
  .acts .dl:hover{{text-decoration:underline}}
  .copy.all{{background:var(--accent);color:#fff;border-color:var(--accent)}}
</style>
</head>
<body>
<header>
  <div><h1>Marketplace Drafts</h1><div class="sub">{n} cards &middot; highest value first &middot; paste into Facebook Marketplace</div></div>
  <a class="new" href="{FB_CREATE_URL}" target="_blank" rel="noopener">+ Create listing on Marketplace &#8599;</a>
</header>
<p class="note">For each card: click <b>+ Create listing</b> (opens Marketplace), then copy the title &amp; description here and open/save the photo to upload. Category <b>{DEFAULT_CATEGORY}</b>, condition <b>{DEFAULT_CONDITION}</b> are pre-filled suggestions. Posting stays manual on purpose — keeps your account safe (no bots).</p>
<div class="grid">{cards}</div>
<script>
  function flash(btn){{var o=btn.textContent;btn.classList.add('done');btn.textContent='Copied';setTimeout(function(){{btn.classList.remove('done');btn.textContent=o;}},1300);}}
  function write(text,btn){{
    if(navigator.clipboard&&navigator.clipboard.writeText){{navigator.clipboard.writeText(text).then(function(){{flash(btn);}});}}
    else{{var ta=document.createElement('textarea');ta.value=text;document.body.appendChild(ta);ta.select();document.execCommand('copy');ta.remove();flash(btn);}}
  }}
  function cp(btn,text){{write(text,btn);}}
  function cpAll(btn,title,price,desc){{write(title+"\\n\\nPrice: "+price+"\\n\\n"+desc,btn);}}
</script>
</body>
</html>"""


if __name__ == "__main__":
    raise SystemExit(main())
