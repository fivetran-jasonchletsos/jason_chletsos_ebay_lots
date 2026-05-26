"""
storefront_agent.py — Buyer-facing landing page (docs/index.html).

Renders a real storefront from output/listings_snapshot.json:
  - Hero strip with brand line + live counts
  - Featured listings grid (top by price, photos required)
  - Browse-by-set / by-player / under-$10 / steals tiles
  - Recently-sold trust strip
  - Seller trust footer

Reuses promote.html_shell() for the chrome (nav, footer, admin gate) and
promote._epn_wrap() for outbound eBay links.
"""
from __future__ import annotations

import html
import json
import random
from collections import Counter
from pathlib import Path

import promote
import browse_index_agent

REPO_ROOT = Path(__file__).parent
SNAPSHOT  = REPO_ROOT / "output" / "listings_snapshot.json"
DOCS_DIR  = REPO_ROOT / "docs"
SOLD_HIST = REPO_ROOT / "data" / "sold_history.json"

FEATURED_COUNT = 24
SOLD_STRIP_COUNT = 8


def _load_listings() -> list[dict]:
    raw = json.loads(SNAPSHOT.read_text())
    listings = raw["listings"] if isinstance(raw, dict) else raw
    return [l for l in listings if l.get("pic") and l.get("url")]


def _load_sold() -> list[dict]:
    if not SOLD_HIST.exists():
        return []
    try:
        return json.loads(SOLD_HIST.read_text())
    except Exception:
        return []


def _price(l: dict) -> float:
    try:
        return float(l.get("price") or 0)
    except (TypeError, ValueError):
        return 0.0


def _render_card(l: dict, idx: int) -> str:
    title = html.escape((l.get("title") or "").strip())
    pic   = html.escape(l.get("pic") or "")
    url   = html.escape(promote._epn_wrap(l.get("url") or ""))
    price = _price(l)
    price_str = f"${price:,.2f}" if price else "—"
    cond = html.escape((l.get("condition") or "").strip())
    delay = min(idx * 30, 720)
    cond_chip = f'<span class="sf-chip">{cond}</span>' if cond else ""
    return f'''
      <a class="sf-card" href="{url}" target="_blank" rel="noopener nofollow" style="animation-delay:{delay}ms">
        <div class="sf-pic">
          <img src="{pic}" alt="{title}" loading="lazy">
          <span class="sf-price">{price_str}</span>
        </div>
        <div class="sf-meta">
          <div class="sf-title">{title}</div>
          <div class="sf-ship" aria-label="Free shipping, combined shipping on 2 or more">Free ship · Combined ship 2+</div>
          <div class="sf-row">{cond_chip}<span class="sf-cta">View on eBay →</span></div>
        </div>
      </a>'''


def _render_set_tile(name: str, count: int) -> str:
    n = html.escape(name)
    slug = browse_index_agent.slugify(name) if hasattr(browse_index_agent, "slugify") else html.escape(name.lower().replace(" ", "-"))
    return f'''<a class="sf-tile" href="by_set.html#{slug}">
        <div class="sf-tile-name">{n}</div>
        <div class="sf-tile-meta">{count} listing{"s" if count != 1 else ""}</div>
      </a>'''


def _render_player_tile(name: str, count: int) -> str:
    n = html.escape(name)
    slug = html.escape(name.lower().replace(" ", "-"))
    return f'''<a class="sf-tile sf-tile-player" href="by_player.html#{slug}">
        <div class="sf-tile-name">{n}</div>
        <div class="sf-tile-meta">{count} card{"s" if count != 1 else ""}</div>
      </a>'''


def _hero(active_count: int, set_count: int, player_count: int, min_price: float) -> str:
    return f'''
    <section class="sf-hero">
      <div class="sf-hero-side">
        <div class="sf-eyebrow">One-person card shop · Selling on eBay since 1998</div>
        <h1 class="sf-headline">
          <span class="sf-headline-serif">Sports &amp; Pokémon</span><br>
          <span class="sf-headline-display">cards, hand-listed since 1998.</span>
        </h1>
        <p class="sf-lede">
          {active_count}+ live listings, real photos, ships next business day from Ohio.
          Combined shipping free on 2+. Checkout happens on eBay with buyer protection
          on every order — tap any card to bid or buy.
        </p>
        <div class="sf-hero-stats">
          <div class="sf-stat"><b>{active_count}</b><span>cards in shop</span></div>
          <div class="sf-stat"><b>{set_count}</b><span>sets</span></div>
          <div class="sf-stat"><b>{player_count}</b><span>players &amp; Pokémon</span></div>
          <div class="sf-stat"><b>from ${min_price:.2f}</b><span>cheapest card</span></div>
        </div>
        <div class="sf-hero-ctas">
          <a class="sf-btn sf-btn-primary" href="#featured">Shop the Cards</a>
          <a class="sf-btn" href="price_drops.html">See Today's Steals →</a>
        </div>
      </div>
      <aside class="sf-hero-trust">
        <div class="sf-trust-row"><span>★★★★★</span><b>100% positive feedback, on eBay since 1998</b></div>
        <div class="sf-trust-row"><span>◆</span><b>Every card photographed front and back before listing</b></div>
        <div class="sf-trust-row"><span>⚡︎</span><b>Ships next business day with tracking</b></div>
        <div class="sf-trust-row"><span>◈</span><b>Buy more than one, pay shipping once</b></div>
      </aside>
    </section>'''


def _featured_section(listings: list[dict]) -> str:
    cards = "\n".join(_render_card(l, i) for i, l in enumerate(listings[:FEATURED_COUNT]))
    return f'''
    <section class="sf-section" id="featured">
      <div class="sf-section-head">
        <h2><span class="sf-num">01</span> Featured Right Now</h2>
        <a class="sf-link" href="browse.html">See the full catalog →</a>
      </div>
      <div class="sf-grid">{cards}</div>
    </section>'''


def _browse_section(top_sets: list[tuple[str,int]], top_players: list[tuple[str,int]]) -> str:
    set_tiles = "\n".join(_render_set_tile(n, c) for n, c in top_sets[:8])
    player_tiles = "\n".join(_render_player_tile(n, c) for n, c in top_players[:8])
    return f'''
    <section class="sf-section">
      <div class="sf-section-head">
        <h2><span class="sf-num">02</span> Browse the Catalog</h2>
        <a class="sf-link" href="browse.html">Every set &amp; player →</a>
      </div>
      <div class="sf-subhead">Popular sets</div>
      <div class="sf-tiles">{set_tiles}</div>
      <div class="sf-subhead">Popular players</div>
      <div class="sf-tiles">{player_tiles}</div>
      <div class="sf-quicklinks">
        <a class="sf-quick" href="under_10.html">
          <div class="sf-quick-name">Under $10</div>
          <div class="sf-quick-sub">Cards for the cost of a sandwich</div>
        </a>
        <a class="sf-quick" href="price_drops.html">
          <div class="sf-quick-name">Today's Steals</div>
          <div class="sf-quick-sub">Prices that dropped overnight</div>
        </a>
        <a class="sf-quick" href="sold.html">
          <div class="sf-quick-name">Recently Sold</div>
          <div class="sf-quick-sub">What other collectors picked up</div>
        </a>
      </div>
    </section>'''


def _sold_strip(sold: list[dict]) -> str:
    if not sold:
        return ""
    items = []
    for s in sold[:SOLD_STRIP_COUNT]:
        title = html.escape((s.get("title") or "")[:60])
        price = s.get("price") or s.get("sold_price") or 0
        try: price_str = f"${float(price):,.2f}"
        except: price_str = "—"
        items.append(f'<li><span class="sf-sold-title">{title}</span><span class="sf-sold-price">{price_str}</span></li>')
    return f'''
    <section class="sf-section sf-section-sold">
      <div class="sf-section-head">
        <h2><span class="sf-num">03</span> Just Sold</h2>
        <a class="sf-link" href="sold.html">See everything that's sold →</a>
      </div>
      <ul class="sf-sold-list">{"".join(items)}</ul>
    </section>'''


def _trust_footer() -> str:
    return '''
    <section class="sf-section sf-trust">
      <div class="sf-trust-grid">
        <div>
          <div class="sf-trust-h">Who you're buying from</div>
          <p>harpua2001 — one person, selling cards on eBay since 1998. Every card is shot in the same lightbox so you can compare condition without guessing. If you ever have a question, message us on eBay and a human answers.</p>
        </div>
        <div>
          <div class="sf-trust-h">How buying works</div>
          <p>Click any card to open its live eBay listing. Bid, hit Buy It Now, or send a Best Offer — eBay handles payment and protects every order. Multi-card orders combine automatically, so you only pay shipping once.</p>
        </div>
        <div>
          <div class="sf-trust-h">Shipping &amp; returns</div>
          <p>Every card ships in a penny sleeve, top-loader, and team-bag, inside a bubble mailer with tracking. Orders out the next business day. Most U.S. addresses see delivery in 2-4 days. If it shows up wrong, send it back within 30 days for a full refund.</p>
        </div>
      </div>
    </section>'''


# --------------------------------------------------------------------------- #
# Storefront CSS — distinctive type pairing + atmospheric background          #
# --------------------------------------------------------------------------- #

STOREFRONT_CSS = r"""
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght,SOFT,WONK@9..144,400..900,0..100,0..1&family=Familjen+Grotesk:wght@400;500;600;700&family=JetBrains+Mono:wght@500;600&display=swap" rel="stylesheet">
<style>
  :root {
    --sf-bg: #0a0a0a;
    --sf-surface: #141414;
    --sf-surface-2: #1c1c1c;
    --sf-ink: #f1efe9;
    --sf-mute: #9a9388;
    --sf-faint: #5d5852;
    --sf-gold: #c9a542;
    --sf-gold-bright: #f0d27a;
    --sf-gold-deep: #8a7521;
    --sf-edge: rgba(201,165,66,0.12);
    --sf-edge-strong: rgba(201,165,66,0.36);
    --sf-shadow: 0 14px 40px -18px rgba(0,0,0,0.85);
  }
  body { font-family: 'Familjen Grotesk', system-ui, sans-serif; background: var(--sf-bg); color: var(--sf-ink); }
  main {
    max-width: 1240px; margin: 0 auto; padding: 1.2rem 1.1rem 4rem;
    position: relative;
  }
  /* atmospheric background */
  main::before {
    content: ""; position: fixed; inset: 0; z-index: -2; pointer-events: none;
    background:
      radial-gradient(ellipse 60% 40% at 12% 8%, rgba(201,165,66,0.10), transparent 70%),
      radial-gradient(ellipse 45% 30% at 90% 18%, rgba(120,80,160,0.07), transparent 70%),
      linear-gradient(180deg, #0a0a0a 0%, #0d0c0a 100%);
  }
  main::after {
    content: ""; position: fixed; inset: 0; z-index: -1; pointer-events: none; opacity: 0.06;
    background-image: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='220' height='220'><filter id='n'><feTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='2' stitchTiles='stitch'/></filter><rect width='100%' height='100%' filter='url(%23n)' opacity='0.7'/></svg>");
  }

  /* ── HERO ── */
  .sf-hero {
    display: grid; grid-template-columns: 1.55fr 1fr; gap: 2.2rem;
    padding: 2rem 0 2.4rem; border-bottom: 1px solid var(--sf-edge);
    margin-bottom: 2.2rem;
    animation: sf-fade-up 0.8s ease both;
  }
  .sf-eyebrow {
    font-family: 'JetBrains Mono', monospace; font-size: 10.5px;
    letter-spacing: 0.22em; text-transform: uppercase;
    color: var(--sf-gold); margin-bottom: 1.1rem;
  }
  .sf-headline {
    font-family: 'Fraunces', Georgia, serif;
    font-weight: 400; font-style: normal;
    font-variation-settings: "opsz" 144, "SOFT" 30, "WONK" 1;
    font-size: clamp(40px, 7.4vw, 92px); line-height: 0.96; letter-spacing: -0.02em;
    margin: 0 0 1.1rem; color: var(--sf-ink);
  }
  .sf-headline-serif { font-style: italic; font-weight: 350; color: var(--sf-mute); display: inline-block; }
  .sf-headline-display { font-weight: 700; color: var(--sf-gold-bright); }
  .sf-lede { font-size: 16.5px; line-height: 1.55; color: var(--sf-mute); max-width: 56ch; margin: 0 0 1.5rem; }
  .sf-hero-stats { display: flex; flex-wrap: wrap; gap: 1.6rem 2.2rem; margin-bottom: 1.6rem; }
  .sf-stat b { display: block; font-family: 'Fraunces', serif; font-weight: 600; font-size: 28px; color: var(--sf-gold-bright); line-height: 1; }
  .sf-stat span { font-family: 'JetBrains Mono', monospace; font-size: 10px; color: var(--sf-faint); text-transform: uppercase; letter-spacing: 0.18em; }
  .sf-hero-ctas { display: flex; gap: 0.7rem; flex-wrap: wrap; }
  .sf-btn {
    display: inline-block; padding: 0.85rem 1.4rem; border-radius: 2px;
    font-family: 'JetBrains Mono', monospace; font-size: 11px; font-weight: 600;
    text-transform: uppercase; letter-spacing: 0.18em;
    background: var(--sf-surface-2); color: var(--sf-ink);
    border: 1px solid var(--sf-edge-strong); transition: all 0.18s;
  }
  .sf-btn:hover { background: var(--sf-surface); border-color: var(--sf-gold); color: var(--sf-gold-bright); transform: translateY(-1px); }
  .sf-btn-primary { background: var(--sf-gold); color: #0a0a0a; border-color: var(--sf-gold-bright); }
  .sf-btn-primary:hover { background: var(--sf-gold-bright); color: #0a0a0a; }
  .sf-hero-trust {
    background: linear-gradient(135deg, rgba(201,165,66,0.07), rgba(201,165,66,0.01));
    border: 1px solid var(--sf-edge); border-radius: 4px;
    padding: 1.4rem 1.3rem; align-self: start; box-shadow: var(--sf-shadow);
  }
  .sf-trust-row { display: flex; align-items: baseline; gap: 0.7rem; padding: 0.55rem 0; border-bottom: 1px dashed var(--sf-edge); }
  .sf-trust-row:last-child { border-bottom: 0; }
  .sf-trust-row span { color: var(--sf-gold); font-size: 14px; min-width: 1.6rem; }
  .sf-trust-row b { font-weight: 500; color: var(--sf-ink); font-size: 13.5px; }

  /* ── SECTIONS ── */
  .sf-section { margin: 2.6rem 0 0; }
  .sf-section-head { display: flex; align-items: baseline; justify-content: space-between; gap: 1rem; margin-bottom: 1.1rem; padding-bottom: 0.55rem; border-bottom: 1px solid var(--sf-edge); }
  .sf-section-head h2 { font-family: 'Fraunces', serif; font-weight: 500; font-style: italic; font-size: 30px; letter-spacing: -0.01em; color: var(--sf-ink); margin: 0; }
  .sf-num { font-family: 'JetBrains Mono', monospace; font-size: 11px; color: var(--sf-gold); margin-right: 0.7rem; font-style: normal; letter-spacing: 0.15em; vertical-align: 0.3em; }
  .sf-link { font-family: 'JetBrains Mono', monospace; font-size: 11px; color: var(--sf-mute); text-transform: uppercase; letter-spacing: 0.14em; }
  .sf-link:hover { color: var(--sf-gold-bright); }
  .sf-subhead { font-family: 'JetBrains Mono', monospace; font-size: 10.5px; color: var(--sf-faint); text-transform: uppercase; letter-spacing: 0.2em; margin: 1.4rem 0 0.7rem; }

  /* ── CARD GRID ── */
  .sf-grid {
    display: grid; gap: 1rem;
    grid-template-columns: repeat(auto-fill, minmax(210px, 1fr));
  }
  @media (min-width: 1400px) {
    .sf-grid { grid-template-columns: repeat(auto-fill, minmax(230px, 1fr)); gap: 1.1rem; }
  }
  .sf-card {
    background: var(--sf-surface); border: 1px solid var(--sf-edge); border-radius: 4px;
    overflow: hidden; display: flex; flex-direction: column;
    transition: transform 0.22s ease, border-color 0.22s ease, box-shadow 0.22s ease;
    opacity: 0; transform: translateY(8px);
    animation: sf-fade-up 0.6s ease forwards;
    position: relative;
  }
  /* Gold accent sweep on hover (top edge) */
  .sf-card::after {
    content: ""; position: absolute; top: 0; left: 0; right: 0; height: 1px;
    background: linear-gradient(90deg, transparent, var(--sf-gold-bright), transparent);
    transform: scaleX(0); transform-origin: left center;
    transition: transform 0.45s cubic-bezier(.4,0,.2,1);
    pointer-events: none;
  }
  .sf-card:hover { transform: translateY(-3px); border-color: var(--sf-edge-strong); box-shadow: var(--sf-shadow); }
  .sf-card:hover::after { transform: scaleX(1); }
  /* Trading card aspect (~2.5:3.5) — fills the slot like the real object */
  .sf-pic { position: relative; aspect-ratio: 5/7; background: #08080a; overflow: hidden; }
  /* shimmer while the image decodes */
  .sf-pic::before {
    content: ""; position: absolute; inset: 0;
    background: linear-gradient(110deg, transparent 30%, rgba(201,165,66,0.045) 50%, transparent 70%);
    background-size: 220% 100%;
    animation: sf-shimmer 1.6s ease-in-out infinite;
    pointer-events: none; z-index: 0;
  }
  .sf-pic img { position: relative; z-index: 1; width: 100%; height: 100%; object-fit: cover; transition: transform 0.55s ease; }
  .sf-pic img[src] { background: #08080a; }
  .sf-card:hover .sf-pic img { transform: scale(1.035); }
  @keyframes sf-shimmer { 0% { background-position: 200% 0; } 100% { background-position: -200% 0; } }
  .sf-price {
    position: absolute; bottom: 8px; right: 8px;
    background: rgba(10,10,10,0.85); color: var(--sf-gold-bright);
    font-family: 'JetBrains Mono', monospace; font-size: 13px; font-weight: 600;
    padding: 0.3rem 0.55rem; border-radius: 2px; border: 1px solid var(--sf-edge-strong);
    backdrop-filter: blur(4px);
  }
  .sf-meta { padding: 0.75rem 0.85rem 0.9rem; display: flex; flex-direction: column; gap: 0.45rem; }
  .sf-title { font-size: 13px; line-height: 1.35; color: var(--sf-ink); display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; min-height: 2.7em; word-break: break-word; overflow-wrap: anywhere; }
  .sf-row { display: flex; align-items: center; justify-content: space-between; gap: 0.5rem; flex-wrap: wrap; }
  .sf-chip { font-family: 'JetBrains Mono', monospace; font-size: 9.5px; color: var(--sf-faint); text-transform: uppercase; letter-spacing: 0.12em; padding: 0.15rem 0.4rem; border: 1px solid var(--sf-edge); border-radius: 2px; }
  .sf-cta { font-family: 'JetBrains Mono', monospace; font-size: 10px; color: var(--sf-gold); letter-spacing: 0.1em; text-transform: uppercase; margin-left: auto; }
  .sf-ship { font-family: 'JetBrains Mono', monospace; font-size: 9.5px; color: var(--sf-gold); letter-spacing: 0.08em; text-transform: uppercase; opacity: 0.85; }

  /* ── BROWSE TILES ── */
  .sf-tiles { display: grid; gap: 0.55rem; grid-template-columns: repeat(auto-fill, minmax(180px, 1fr)); margin-bottom: 0.5rem; }
  .sf-tile {
    background: var(--sf-surface-2); border: 1px solid var(--sf-edge);
    padding: 0.85rem 0.95rem; border-radius: 3px; display: block;
    transition: border-color 0.18s, transform 0.12s;
  }
  .sf-tile:hover { border-color: var(--sf-gold); transform: translateY(-1px); }
  .sf-tile-name { font-family: 'Fraunces', serif; font-weight: 500; font-size: 16px; color: var(--sf-ink); margin-bottom: 0.18rem; line-height: 1.2; }
  .sf-tile-meta { font-family: 'JetBrains Mono', monospace; font-size: 9.5px; color: var(--sf-mute); letter-spacing: 0.1em; text-transform: uppercase; }
  .sf-tile-player .sf-tile-name { font-style: italic; color: var(--sf-gold-bright); }

  .sf-quicklinks { display: grid; gap: 0.6rem; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); margin-top: 1.4rem; }
  .sf-quick {
    background: linear-gradient(135deg, rgba(201,165,66,0.08), var(--sf-surface));
    border: 1px solid var(--sf-edge-strong); border-radius: 4px; padding: 1.1rem 1.2rem;
    transition: all 0.18s;
  }
  .sf-quick:hover { transform: translateY(-2px); border-color: var(--sf-gold); }
  .sf-quick-name { font-family: 'Fraunces', serif; font-style: italic; font-weight: 600; font-size: 22px; color: var(--sf-gold-bright); margin-bottom: 0.25rem; }
  .sf-quick-sub { font-size: 12.5px; color: var(--sf-mute); line-height: 1.4; }

  /* ── SOLD STRIP ── */
  .sf-section-sold { background: var(--sf-surface); border: 1px solid var(--sf-edge); border-radius: 4px; padding: 1.4rem 1.4rem 1.2rem; }
  .sf-section-sold .sf-section-head { border-bottom-color: var(--sf-edge); }
  .sf-sold-list { list-style: none; margin: 0; padding: 0; }
  .sf-sold-list li { display: flex; justify-content: space-between; align-items: baseline; gap: 1rem; padding: 0.55rem 0; border-bottom: 1px dashed var(--sf-edge); }
  .sf-sold-list li:last-child { border-bottom: 0; }
  .sf-sold-title { font-size: 13.5px; color: var(--sf-ink); flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .sf-sold-price { font-family: 'JetBrains Mono', monospace; font-size: 12.5px; color: var(--sf-gold-bright); font-weight: 600; }

  /* ── TRUST FOOTER ── */
  .sf-trust-grid { display: grid; gap: 1.6rem; grid-template-columns: repeat(auto-fit, minmax(230px, 1fr)); }
  .sf-trust-h { font-family: 'JetBrains Mono', monospace; font-size: 10.5px; color: var(--sf-gold); text-transform: uppercase; letter-spacing: 0.18em; margin-bottom: 0.55rem; }
  .sf-trust p { font-size: 13.5px; line-height: 1.55; color: var(--sf-mute); margin: 0; }

  /* ── MOTION ── */
  @keyframes sf-fade-up {
    from { opacity: 0; transform: translateY(10px); }
    to   { opacity: 1; transform: translateY(0); }
  }
  @media (prefers-reduced-motion: reduce) {
    .sf-hero, .sf-card { animation: none; opacity: 1; transform: none; }
    .sf-pic::before { animation: none; }
    .sf-card:hover { transform: none; }
    .sf-card:hover .sf-pic img { transform: none; }
  }

  /* ── MOBILE POLISH ── */
  @media (max-width: 760px) {
    main { padding: 0.9rem 0.8rem 3rem; }
    .sf-hero { grid-template-columns: 1fr; gap: 1.4rem; padding: 1.2rem 0 1.6rem; margin-bottom: 1.4rem; }
    .sf-headline { font-size: clamp(36px, 11vw, 60px); }
    .sf-lede { font-size: 15px; }
    .sf-hero-stats { gap: 1rem 1.4rem; }
    .sf-stat b { font-size: 22px; }
    .sf-section-head h2 { font-size: 22px; }
    .sf-grid { grid-template-columns: repeat(2, 1fr); gap: 0.6rem; }
    .sf-meta { padding: 0.55rem 0.6rem 0.7rem; }
    .sf-title { font-size: 12px; }
    .sf-tiles { grid-template-columns: 1fr 1fr; }
    .sf-tile-name { font-size: 14px; }
    .sf-quick-name { font-size: 18px; }
    .sf-section-sold { padding: 1rem; }
    .sf-sold-list li { flex-direction: column; align-items: flex-start; gap: 0.15rem; }
    .sf-sold-title { white-space: normal; }
  }

  /* Tighter phones (sub-iPhone-SE) */
  @media (max-width: 480px) {
    main { padding: 0.7rem 0.6rem 2.4rem; }
    .sf-hero { padding: 0.8rem 0 1.2rem; gap: 1rem; }
    .sf-headline { font-size: clamp(32px, 12vw, 48px); margin-bottom: 0.7rem; }
    .sf-eyebrow { margin-bottom: 0.6rem; }
    .sf-lede { font-size: 14px; }
    .sf-hero-trust { padding: 1rem; }
    .sf-grid { gap: 0.5rem; }
    .sf-meta { padding: 0.5rem 0.55rem 0.6rem; gap: 0.3rem; }
    .sf-title { font-size: 11.5px; min-height: 2.5em; }
    .sf-price { font-size: 12px; padding: 0.25rem 0.45rem; }
    .sf-section-head h2 { font-size: 19px; }
    .sf-section { margin-top: 1.8rem; }
    .sf-tiles { gap: 0.4rem; }
    .sf-tile { padding: 0.7rem 0.8rem; }
  }

  /* Print: clean sold history if buyers ever save the page */
  @media print {
    main::before, main::after { display: none; }
    body { background: #fff; color: #000; }
    .sf-card, .sf-hero-trust, .sf-section-sold { box-shadow: none; border-color: #ccc; break-inside: avoid; }
    .sf-headline, .sf-section-head h2, .sf-stat b, .sf-quick-name { color: #000; }
    .sf-pic { display: none; }
  }
</style>
"""


def build_index() -> Path:
    listings = _load_listings()
    sold = _load_sold()

    # Featured: a mix of higher-priced flagships + random taste so the page changes day-to-day
    by_price = sorted(listings, key=_price, reverse=True)
    flagships = by_price[:14]
    rest = [l for l in listings if l not in flagships]
    random.seed(len(listings))  # stable per snapshot
    random.shuffle(rest)
    featured = flagships + rest[: max(0, FEATURED_COUNT - len(flagships))]

    # Browse taxonomy via existing browse_index_agent helpers
    set_counts: Counter = Counter()
    player_counts: Counter = Counter()
    for l in listings:
        t = l.get("title") or ""
        s = browse_index_agent.extract_set(t)
        if s:
            set_counts[s] += 1
        for p in browse_index_agent.extract_players(t):
            player_counts[p] += 1
    top_sets = set_counts.most_common(8)
    top_players = player_counts.most_common(8)
    min_price = min((_price(l) for l in listings if _price(l) > 0), default=0.0)

    body = (
        _hero(len(listings), len(set_counts), len(player_counts), min_price)
        + _featured_section(featured)
        + _browse_section(top_sets, top_players)
        + _sold_strip(sold)
        + _trust_footer()
    )

    # html_shell already includes <header>, <nav>, drawer, and footer.
    # Wrap body in a <main> so our atmospheric ::before/::after sit behind it.
    full = promote.html_shell(
        title="Harpua2001 · Sports & Pokémon Cards, Hand-Picked on eBay",
        body=f'<main>{body}</main>',
        extra_head=STOREFRONT_CSS,
        active_page="index.html",
    )

    out = DOCS_DIR / "index.html"
    out.write_text(full)
    return out


def main() -> None:
    path = build_index()
    print(f"  Storefront built: {path}")
    listings = _load_listings()
    print(f"  Featured listings: {min(len(listings), FEATURED_COUNT)} / {len(listings)} total")


if __name__ == "__main__":
    main()
