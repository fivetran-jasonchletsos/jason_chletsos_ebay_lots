#!/usr/bin/env python3
"""Generate a single-file comic-themed eBay seller dashboard from warehouse.db.

Reads from tester.* tables in ../jason_chletsos_ebay_lots/files/warehouse.db
and writes output/ebay_dashboard.html with all data embedded.
"""
import duckdb
import json
import os
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "files" / "warehouse.db"
OUT = ROOT / "output" / "dashboard.html"


def fetch_all(con, sql):
    return con.execute(sql).fetchdf().to_dict(orient="records")


def to_native(o):
    """Make pandas/numpy/timestamp values JSON-safe."""
    if o is None:
        return None
    if isinstance(o, (str, int, float, bool)):
        return o
    if isinstance(o, dict):
        return {k: to_native(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [to_native(v) for v in o]
    # pandas Timestamp / numpy types fall through to str
    try:
        import math
        if isinstance(o, float) and math.isnan(o):
            return None
    except Exception:
        pass
    return str(o)


def gather(con):
    listings = fetch_all(
        con,
        """
        SELECT listing_id, title, category_id, condition, price, currency,
               quantity_available, listing_status, listing_format, listing_url,
               image_urls, item_specifics, last_seen_in_ads
        FROM tester.active_listings
        WHERE COALESCE(_fivetran_deleted, false) = false
        ORDER BY price DESC
        """,
    )
    orders = fetch_all(
        con,
        """
        SELECT order_id, listing_id, buyer_username, sale_price, shipping_cost,
               total_amount, order_status, payment_status, created_date,
               shipping_carrier, item_title, quantity
        FROM tester.orders
        WHERE COALESCE(_fivetran_deleted, false) = false
        ORDER BY created_date DESC
        """,
    )
    perf = fetch_all(
        con,
        """
        SELECT listing_id,
               SUM(impressions) AS impressions,
               SUM(clicks)      AS clicks,
               AVG(click_through_rate) AS ctr,
               SUM(page_views)  AS page_views,
               AVG(conversion_rate) AS conv_rate,
               SUM(top_20_search_slot_impressions) AS top20_impressions
        FROM tester.listing_performance
        WHERE COALESCE(_fivetran_deleted, false) = false
        GROUP BY listing_id
        """,
    )
    promoted = fetch_all(
        con,
        """
        SELECT campaign_id, ad_id, campaign_name, campaign_status, listing_id,
               bid_percentage, funding_model, start_date, end_date
        FROM tester.promoted_listings
        WHERE COALESCE(_fivetran_deleted, false) = false
        """,
    )
    standards = fetch_all(
        con,
        """
        SELECT snapshot_date, program, overall_status, evaluation_reason,
               defect_rate, defect_count, defect_denominator, late_shipment_rate,
               cases_closed_without_resolution, transaction_count, gmv,
               eligible_for_top_rated_plus
        FROM tester.seller_standards
        WHERE COALESCE(_fivetran_deleted, false) = false
        ORDER BY snapshot_date DESC
        LIMIT 1
        """,
    )

    perf_by_id = {p["listing_id"]: p for p in perf}
    promo_ids = {p["listing_id"] for p in promoted}
    order_counts = {}
    order_revenue = {}
    for o in orders:
        lid = o["listing_id"]
        order_counts[lid] = order_counts.get(lid, 0) + 1
        order_revenue[lid] = order_revenue.get(lid, 0.0) + float(o.get("total_amount") or 0)

    # Merge per-listing
    for l in listings:
        lid = l["listing_id"]
        p = perf_by_id.get(lid, {})
        l["impressions"] = int(p.get("impressions") or 0)
        l["clicks"] = int(p.get("clicks") or 0)
        l["ctr"] = float(p.get("ctr") or 0)
        l["page_views"] = int(p.get("page_views") or 0)
        l["conv_rate"] = float(p.get("conv_rate") or 0)
        l["promoted"] = lid in promo_ids
        l["orders_count"] = order_counts.get(lid, 0)
        l["revenue"] = round(order_revenue.get(lid, 0.0), 2)
        l["price"] = round(float(l.get("price") or 0), 2)

    return {
        "listings": listings,
        "orders": orders,
        "promoted": promoted,
        "standards": standards[0] if standards else None,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0"/>
<title>The Lot Vault — eBay Seller Dashboard</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Abril+Fatface&family=Playfair+Display:wght@700;900&family=Bebas+Neue&family=JetBrains+Mono:wght@400;700&family=Bangers&display=swap" rel="stylesheet">
<style>
  :root, [data-theme="noir"] {
    --ink:#0a0807; --ink-2:#14100d; --ink-3:#1f1812; --paper:#f4e8c8;
    --aged:#d4b878; --aged-deep:#8a6a2c; --blood:#c8252c; --blood-deep:#7d1419;
    --gold:#e8c463; --green:#4caa55; --blue:#4a8ce0; --yellow:#e6c44a;
  }
  [data-theme="spiderman"] { --ink:#0a0e1e;--ink-2:#111630;--ink-3:#182044;--paper:#f5f7fb;--aged:#9ec5ff;--aged-deep:#1a4ea8;--blood:#d8272d;--blood-deep:#8a0a10;--gold:#4a8cff;--green:#4caa55;--blue:#4a8cff;--yellow:#e6c44a; }
  [data-theme="wolverine"] { --ink:#0d1024;--ink-2:#14182f;--ink-3:#1c2244;--paper:#fff4cc;--aged:#f5cf3a;--aged-deep:#b88a0e;--blood:#1c3fa0;--blood-deep:#0c2470;--gold:#ffd200;--green:#4caa55;--blue:#1c3fa0;--yellow:#ffd200; }
  [data-theme="elektra"] { --ink:#060000;--ink-2:#110404;--ink-3:#1a0808;--paper:#f8e6e0;--aged:#b04040;--aged-deep:#6e1a1a;--blood:#aa0606;--blood-deep:#5c0000;--gold:#d83a3a;--green:#4caa55;--blue:#4a8ce0;--yellow:#d4a020; }
  [data-theme="maxx"] { --ink:#0e0524;--ink-2:#1a0a3a;--ink-3:#281055;--paper:#f5e8ff;--aged:#c4a4f0;--aged-deep:#6a30a8;--blood:#8b1ed6;--blood-deep:#4e0c80;--gold:#f8e635;--green:#5ce0a0;--blue:#6c4ad6;--yellow:#f8e635; }
  [data-theme="gijoe"] { --ink:#0a1208;--ink-2:#16200f;--ink-3:#1f2c14;--paper:#ede4c4;--aged:#a89968;--aged-deep:#4d6b3a;--blood:#c12a1e;--blood-deep:#6e1409;--gold:#c8a838;--green:#6b8b3a;--blue:#2a4060;--yellow:#c8a838; }

  *{box-sizing:border-box;margin:0;padding:0}
  html,body{background:var(--ink);color:var(--paper);font-family:'Playfair Display',Georgia,serif;min-height:100vh;overflow-x:hidden;transition:background .4s,color .4s}
  body,.panel,.card,.stat,.filters,.a-panel,.drawer,.tab,.btn{transition:background .4s,color .4s,border-color .4s,box-shadow .4s}
  body::before{content:"";position:fixed;inset:0;background-image:radial-gradient(circle at 20% 30%,rgba(200,37,44,.06) 0%,transparent 40%),radial-gradient(circle at 80% 70%,rgba(232,196,99,.04) 0%,transparent 45%),radial-gradient(rgba(244,232,200,.04) 1px,transparent 1px);background-size:100% 100%,100% 100%,4px 4px;pointer-events:none;z-index:0}

  header{position:relative;z-index:2;padding:32px 5vw 22px;border-bottom:3px solid var(--blood);background:linear-gradient(180deg,#16100b 0%,#0a0807 100%);box-shadow:0 6px 24px rgba(0,0,0,.6),inset 0 -8px 0 #2a1810}
  .masthead{display:flex;justify-content:space-between;align-items:flex-end;gap:24px;flex-wrap:wrap}
  .brand h1{font-family:'Abril Fatface',serif;font-size:clamp(2.4rem,6vw,4.6rem);line-height:1;letter-spacing:-.02em;color:var(--paper);text-shadow:4px 4px 0 var(--blood),8px 8px 0 rgba(0,0,0,.5)}
  .brand p{margin-top:6px;font-family:'JetBrains Mono',monospace;font-size:.85rem;color:var(--aged);letter-spacing:.15em;text-transform:uppercase}
  .brand .accent{color:var(--blood)}
  .tabs{display:flex;gap:4px;flex-wrap:wrap}
  .tab{background:transparent;color:var(--aged);border:2px solid var(--aged-deep);font-family:'Bebas Neue',sans-serif;letter-spacing:.1em;padding:10px 18px;font-size:1rem;cursor:pointer;text-transform:uppercase}
  .tab:hover{background:var(--aged-deep);color:var(--ink)}
  .tab.active{background:var(--blood);border-color:var(--blood);color:var(--paper);box-shadow:3px 3px 0 var(--ink)}
  .api-pill{background:var(--gold);color:var(--ink);border:2px solid var(--ink);font-family:'Bebas Neue';letter-spacing:.1em;padding:10px 14px;cursor:pointer;box-shadow:3px 3px 0 var(--ink)}

  .theme-row{display:flex;gap:8px;align-items:center;margin-top:18px;flex-wrap:wrap}
  .theme-label{font-family:'Bebas Neue';letter-spacing:.15em;color:var(--aged);font-size:.8rem;text-transform:uppercase;margin-right:4px}
  .theme-chip{cursor:pointer;border:2px solid var(--ink);padding:6px 12px;font-family:'Bangers','Bebas Neue',cursive;letter-spacing:.08em;font-size:.95rem;transition:transform .15s,box-shadow .15s;box-shadow:3px 3px 0 var(--ink);color:#fff;text-shadow:2px 2px 0 rgba(0,0,0,.5)}
  .theme-chip:hover{transform:translate(-2px,-2px);box-shadow:5px 5px 0 var(--ink)}
  .theme-chip.active{outline:3px solid #fff;outline-offset:2px}
  .theme-chip[data-set="noir"]{background:linear-gradient(135deg,#0a0807 0%,#c8252c 100%)}
  .theme-chip[data-set="spiderman"]{background:linear-gradient(135deg,#d8272d 0%,#4a8cff 100%)}
  .theme-chip[data-set="wolverine"]{background:linear-gradient(135deg,#ffd200 0%,#1c3fa0 100%);color:#111;text-shadow:1px 1px 0 #fff}
  .theme-chip[data-set="elektra"]{background:linear-gradient(135deg,#aa0606 0%,#060000 100%)}
  .theme-chip[data-set="maxx"]{background:linear-gradient(135deg,#8b1ed6 0%,#f8e635 100%)}
  .theme-chip[data-set="gijoe"]{background:linear-gradient(135deg,#6b8b3a 0%,#c12a1e 100%)}

  main{position:relative;z-index:1;max-width:1500px;margin:0 auto;padding:32px 5vw 80px}
  .dashboard{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:18px;margin-bottom:32px}
  .stat{background:linear-gradient(160deg,var(--ink-2),var(--ink-3));border:2px solid var(--aged-deep);padding:22px;position:relative;overflow:hidden;box-shadow:5px 5px 0 rgba(0,0,0,.7)}
  .stat::after{content:"";position:absolute;inset:0;background-image:radial-gradient(rgba(212,184,120,.08) 1px,transparent 1px);background-size:6px 6px;pointer-events:none}
  .stat .label{font-family:'Bebas Neue';letter-spacing:.12em;color:var(--aged);font-size:.85rem;text-transform:uppercase}
  .stat .value{font-family:'Abril Fatface',serif;font-size:2.4rem;color:var(--paper);margin-top:6px;line-height:1}
  .stat .value.money{color:var(--gold)}
  .stat .sub{font-family:'JetBrains Mono',monospace;font-size:.72rem;color:var(--aged-deep);margin-top:8px}
  .stat-badge{position:absolute;top:14px;right:14px;font-family:'Bebas Neue';padding:3px 8px;font-size:.72rem;letter-spacing:.1em;border:2px solid}
  .stat-badge.good{color:var(--green);border-color:var(--green);background:rgba(76,170,85,.12)}
  .stat-badge.warn{color:var(--yellow);border-color:var(--yellow);background:rgba(230,196,74,.12)}
  .stat-badge.bad{color:var(--blood);border-color:var(--blood);background:rgba(200,37,44,.12)}

  .filters{display:flex;gap:12px;flex-wrap:wrap;align-items:center;margin-bottom:24px;padding:16px;background:var(--ink-2);border:2px solid var(--aged-deep);box-shadow:5px 5px 0 rgba(0,0,0,.7)}
  .filters input,.filters select{background:var(--ink);color:var(--paper);border:2px solid var(--aged-deep);padding:10px 14px;font-family:'JetBrains Mono',monospace;font-size:.85rem;outline:none}
  .filters input:focus,.filters select:focus{border-color:var(--blood)}
  .filters label{display:inline-flex;align-items:center;gap:8px;cursor:pointer;font-family:'JetBrains Mono',monospace;font-size:.8rem;color:var(--aged);text-transform:uppercase;letter-spacing:.1em}
  .filters input[type="checkbox"]{width:18px;height:18px;accent-color:var(--blood)}
  .filters input[type="text"]{flex:1;min-width:200px}

  .grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(310px,1fr));gap:20px}
  .card{background:linear-gradient(165deg,#1a140e,#0e0a06);border:2px solid var(--aged-deep);box-shadow:6px 6px 0 rgba(0,0,0,.85);padding:18px;position:relative;overflow:hidden;transform:translateY(20px);opacity:0;transition:transform .3s,opacity .4s,box-shadow .25s}
  .card.in{transform:translateY(0);opacity:1}
  .card:hover{box-shadow:10px 10px 0 var(--blood-deep)}
  .card-corner{position:absolute;top:-2px;right:-2px;background:var(--blood);color:var(--paper);padding:4px 10px 6px 22px;font-family:'Bebas Neue';letter-spacing:.1em;font-size:1.1rem;clip-path:polygon(0 0,100% 0,100% 100%,12% 100%)}
  .card-id{font-family:'JetBrains Mono',monospace;font-size:.65rem;color:var(--aged-deep);letter-spacing:.15em}
  .card h3{font-family:'Abril Fatface',serif;font-size:1.25rem;line-height:1.15;margin-top:6px;color:var(--paper);text-shadow:2px 2px 0 rgba(0,0,0,.6);min-height:3em;display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;overflow:hidden}
  .card-badges{display:flex;gap:6px;flex-wrap:wrap;margin-top:12px}
  .badge{font-family:'Bebas Neue';letter-spacing:.1em;padding:4px 10px;font-size:.8rem;border:2px solid}
  .badge.promoted{background:rgba(232,196,99,.15);color:var(--gold);border-color:var(--gold)}
  .badge.active{background:rgba(76,170,85,.15);color:var(--green);border-color:var(--green)}
  .badge.sold{background:rgba(74,140,224,.15);color:var(--blue);border-color:var(--blue)}
  .badge.stale{background:rgba(200,37,44,.15);color:var(--blood);border-color:var(--blood)}
  .card-stats{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin-top:14px;padding-top:12px;border-top:1px dashed var(--aged-deep);font-family:'JetBrains Mono',monospace}
  .card-stat{text-align:center}
  .card-stat .n{font-family:'Abril Fatface',serif;font-size:1.4rem;color:var(--gold);line-height:1}
  .card-stat .l{font-size:.62rem;color:var(--aged-deep);text-transform:uppercase;letter-spacing:.1em;margin-top:4px}
  .card-value{font-family:'Abril Fatface',serif;font-size:2.2rem;color:var(--gold);margin-top:14px;line-height:1;text-shadow:3px 3px 0 var(--ink),6px 6px 0 rgba(125,20,25,.6)}
  .card-value small{font-family:'JetBrains Mono',monospace;font-size:.58rem;display:block;color:var(--aged-deep);letter-spacing:.2em;margin-top:4px}
  .card-actions{display:flex;gap:8px;margin-top:14px}
  .btn{flex:1;padding:10px;background:var(--ink);color:var(--aged);border:2px solid var(--aged-deep);cursor:pointer;font-family:'Bebas Neue';letter-spacing:.1em;font-size:.85rem;text-decoration:none;text-align:center;display:inline-block}
  .btn:hover{background:var(--aged-deep);color:var(--ink)}
  .btn.primary{background:var(--blood);border-color:var(--blood);color:var(--paper)}
  .btn.primary:hover{background:var(--blood-deep)}

  .drawer{position:fixed;top:0;right:0;height:100vh;width:min(520px,100%);background:linear-gradient(165deg,#1a140e,#0a0807);border-left:4px solid var(--blood);transform:translateX(100%);transition:transform .35s cubic-bezier(.6,.2,.3,1);z-index:50;display:flex;flex-direction:column;box-shadow:-12px 0 40px rgba(0,0,0,.7)}
  .drawer.open{transform:translateX(0)}
  .drawer-head{padding:22px;border-bottom:2px solid var(--aged-deep);display:flex;justify-content:space-between;align-items:flex-start;gap:12px}
  .drawer-head h2{font-family:'Abril Fatface',serif;font-size:1.4rem;line-height:1.15}
  .drawer-head p{color:var(--aged);font-family:'JetBrains Mono',monospace;font-size:.72rem;margin-top:4px}
  .drawer-close{background:var(--blood);color:var(--paper);border:0;width:34px;height:34px;font-size:1.2rem;cursor:pointer;font-family:'Bebas Neue'}
  .drawer-body{flex:1;overflow-y:auto;padding:22px;font-family:'Playfair Display',serif;line-height:1.55}
  .thought-bubble{background:var(--paper);color:var(--ink);padding:22px;border-radius:24px;box-shadow:6px 6px 0 var(--blood-deep);position:relative}
  .thought-bubble::after{content:"";position:absolute;bottom:-18px;left:28px;width:28px;height:28px;background:var(--paper);border-radius:50%;box-shadow:38px 16px 0 -8px var(--paper)}
  .thought-bubble h4{font-family:'Abril Fatface',serif;font-size:1.2rem;color:var(--blood);margin-bottom:8px}
  .thought-bubble ul{padding-left:20px}
  .thought-bubble li{margin:8px 0}
  .thought-bubble p{margin:8px 0}
  .thought-bubble strong{color:var(--blood-deep)}
  .copy-btn{margin-top:12px;padding:8px 14px;background:var(--blood);color:var(--paper);border:0;cursor:pointer;font-family:'Bebas Neue';letter-spacing:.1em}
  .loading{display:inline-block;width:22px;height:22px;border:3px solid var(--aged-deep);border-top-color:var(--blood);border-radius:50%;animation:spin .8s linear infinite}
  @keyframes spin{to{transform:rotate(360deg)}}

  .analytics-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(360px,1fr));gap:24px}
  .a-panel{background:linear-gradient(165deg,var(--ink-2),var(--ink-3));border:2px solid var(--aged-deep);padding:24px;box-shadow:6px 6px 0 rgba(0,0,0,.8)}
  .a-panel h3{font-family:'Abril Fatface',serif;font-size:1.4rem;margin-bottom:18px;color:var(--paper);text-shadow:2px 2px 0 var(--blood-deep)}
  .bar-row{display:grid;grid-template-columns:1fr 1fr 90px;align-items:center;gap:12px;margin:10px 0;font-family:'JetBrains Mono',monospace;font-size:.78rem}
  .bar-row .name{color:var(--paper);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
  .bar-row .val{color:var(--gold);text-align:right}
  .bar-track{height:20px;background:var(--ink);border:1px solid var(--aged-deep);position:relative;overflow:hidden}
  .bar-fill{height:100%;background:linear-gradient(90deg,var(--blood-deep),var(--blood),var(--gold));transition:width 1.2s cubic-bezier(.2,.7,.3,1);width:0}
  .standards-table{width:100%;border-collapse:collapse;font-family:'JetBrains Mono',monospace;font-size:.85rem}
  .standards-table td{padding:10px 6px;border-bottom:1px dashed var(--aged-deep)}
  .standards-table td:first-child{color:var(--aged);text-transform:uppercase;letter-spacing:.1em;font-size:.7rem}
  .standards-table td:last-child{text-align:right;color:var(--paper);font-weight:700}
  .status-pill{display:inline-block;padding:6px 14px;font-family:'Bebas Neue';letter-spacing:.1em;border:2px solid}
  .status-pill.above{color:var(--green);border-color:var(--green);background:rgba(76,170,85,.15)}
  .status-pill.std{color:var(--blue);border-color:var(--blue);background:rgba(74,140,224,.15)}
  .status-pill.below{color:var(--blood);border-color:var(--blood);background:rgba(200,37,44,.15)}

  .settings-modal{position:fixed;inset:0;background:rgba(0,0,0,.85);z-index:100;display:none;align-items:center;justify-content:center;padding:20px}
  .settings-modal.open{display:flex}
  .settings-box{background:var(--ink-2);border:3px solid var(--blood);padding:30px;max-width:500px;width:100%;box-shadow:10px 10px 0 var(--ink)}
  .settings-box h2{font-family:'Abril Fatface',serif;margin-bottom:16px}
  .settings-box p{color:var(--aged);margin-bottom:16px;line-height:1.5;font-size:.9rem}
  .settings-box input{width:100%;padding:12px;background:var(--ink);color:var(--paper);border:2px solid var(--aged-deep);font-family:'JetBrains Mono',monospace;margin-bottom:16px;outline:none}
  .settings-actions{display:flex;gap:10px;flex-wrap:wrap}

  .hidden{display:none!important}
  ::-webkit-scrollbar{width:10px;height:10px}
  ::-webkit-scrollbar-track{background:var(--ink)}
  ::-webkit-scrollbar-thumb{background:var(--aged-deep)}
  ::-webkit-scrollbar-thumb:hover{background:var(--blood)}

  @media (max-width:1024px){header{padding:24px 4vw 18px}main{padding:22px 4vw 60px}.grid{grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:16px}.stat .value{font-size:2rem}.drawer{width:min(440px,100%)}.analytics-grid{grid-template-columns:1fr}}
  @media (max-width:720px){header{padding:20px 4vw 16px}main{padding:18px 4vw 60px}.brand h1{font-size:2.1rem}.brand p{font-size:.7rem}.masthead{flex-direction:column;align-items:stretch;gap:12px}.tabs{width:100%;flex-wrap:wrap}.tab{flex:1;padding:10px 6px;font-size:.85rem;min-width:0}.api-pill{flex:0 0 100%;margin-top:6px}.theme-chip{padding:5px 9px;font-size:.8rem}.dashboard{grid-template-columns:repeat(2,1fr);gap:12px}.stat{padding:16px}.stat .value{font-size:1.5rem}.stat .label{font-size:.7rem}.filters{padding:12px;gap:8px}.filters input[type="text"],.filters select{width:100%;min-width:0}.filters label{width:48%;font-size:.7rem}.grid{grid-template-columns:1fr;gap:14px}.card-actions{flex-direction:column}.btn{padding:12px}.drawer{width:100%;border-left:0;border-top:4px solid var(--blood)}.drawer-head{padding:16px}.drawer-body{padding:16px}.bar-row{grid-template-columns:1fr 1fr 70px;font-size:.7rem;gap:8px}}
  @media (max-width:400px){.dashboard{grid-template-columns:1fr}.brand h1{font-size:1.85rem}}
  @media (hover:none){.btn,.tab,.theme-chip,.api-pill{min-height:44px}.card:hover{box-shadow:6px 6px 0 rgba(0,0,0,.85)}.card:active{box-shadow:10px 10px 0 var(--blood-deep)}}
</style>
</head>
<body>

<header>
  <div class="masthead">
    <div class="brand">
      <h1>THE LOT <span class="accent">VAULT</span></h1>
      <p>eBay Seller Dashboard · Generated <span id="gen-at">—</span> · <span id="gen-count">—</span> Active Lots</p>
      <div class="theme-row">
        <span class="theme-label">Theme:</span>
        <button class="theme-chip active" data-set="noir">Noir</button>
        <button class="theme-chip" data-set="spiderman">Spider-Man</button>
        <button class="theme-chip" data-set="wolverine">Wolverine</button>
        <button class="theme-chip" data-set="elektra">Elektra</button>
        <button class="theme-chip" data-set="maxx">The Maxx</button>
        <button class="theme-chip" data-set="gijoe">G.I. Joe</button>
      </div>
    </div>
    <div class="tabs">
      <button class="tab active" data-tab="lots">Lots</button>
      <button class="tab" data-tab="analytics">Analytics</button>
      <button class="tab" data-tab="health">Health</button>
      <button class="tab api-pill" id="open-settings">⚙ API Key</button>
    </div>
  </div>
</header>

<main>
  <section id="view-lots">
    <div class="dashboard" id="dashboard"></div>
    <div class="filters">
      <input type="text" id="search" placeholder="Search title…" />
      <select id="filter-status">
        <option value="">All Statuses</option>
        <option value="ACTIVE">Active</option>
        <option value="ENDED">Ended</option>
      </select>
      <select id="filter-sort">
        <option value="price-desc">Sort: Price ↓</option>
        <option value="price-asc">Sort: Price ↑</option>
        <option value="impressions-desc">Sort: Impressions ↓</option>
        <option value="revenue-desc">Sort: Revenue ↓</option>
      </select>
      <label><input type="checkbox" id="filter-promoted"/> Promoted Only</label>
      <label><input type="checkbox" id="filter-sold"/> Sold Only</label>
    </div>
    <div class="grid" id="grid"></div>
  </section>

  <section id="view-analytics" class="hidden">
    <div class="analytics-grid">
      <div class="a-panel" style="grid-column:1/-1">
        <h3>Top Performers by Revenue</h3>
        <div id="bars-revenue"></div>
      </div>
      <div class="a-panel" style="grid-column:1/-1">
        <h3>Top Performers by Impressions</h3>
        <div id="bars-impressions"></div>
      </div>
      <div class="a-panel">
        <h3>Promoted vs Organic</h3>
        <div id="promoted-split"></div>
      </div>
      <div class="a-panel">
        <h3>Inventory by Price Band</h3>
        <div id="price-bands"></div>
      </div>
    </div>
  </section>

  <section id="view-health" class="hidden">
    <div class="analytics-grid">
      <div class="a-panel">
        <h3>Seller Standards</h3>
        <div id="standards-status"></div>
        <table class="standards-table" id="standards-table"></table>
      </div>
      <div class="a-panel">
        <h3>Recent Orders</h3>
        <div id="recent-orders" style="font-family:'JetBrains Mono',monospace;font-size:.82rem;max-height:540px;overflow-y:auto"></div>
      </div>
    </div>
  </section>
</main>

<aside class="drawer" id="drawer">
  <div class="drawer-head">
    <div>
      <h2 id="drawer-title">—</h2>
      <p id="drawer-sub">—</p>
    </div>
    <button class="drawer-close" id="drawer-close">✕</button>
  </div>
  <div class="drawer-body" id="drawer-body"></div>
</aside>

<div class="settings-modal" id="settings-modal">
  <div class="settings-box">
    <h2>Anthropic API Key</h2>
    <p>Enables AI Listing Optimizer + Title Rewriter. Stored locally only; sent only to api.anthropic.com.</p>
    <input type="password" id="api-key-input" placeholder="sk-ant-..." />
    <div class="settings-actions">
      <button class="btn primary" id="save-key">Save</button>
      <button class="btn" id="clear-key">Clear</button>
      <button class="btn" id="close-settings">Close</button>
    </div>
  </div>
</div>

<script>
const DATA = __DATA__;
const MODEL = "claude-sonnet-4-20250514";

// ---------- THEME ----------
function setTheme(name){
  document.documentElement.setAttribute("data-theme", name);
  localStorage.setItem("lots_theme", name);
  document.querySelectorAll(".theme-chip").forEach(c => c.classList.toggle("active", c.dataset.set === name));
}
document.querySelectorAll(".theme-chip").forEach(chip => chip.addEventListener("click", () => setTheme(chip.dataset.set)));
setTheme(localStorage.getItem("lots_theme") || "noir");

// ---------- DASHBOARD ----------
function renderDashboard(){
  const L = DATA.listings, O = DATA.orders, S = DATA.standards;
  const inventoryValue = L.reduce((s, l) => s + (l.price || 0), 0);
  const totalRevenue = O.reduce((s, o) => s + (parseFloat(o.total_amount) || 0), 0);
  const promotedCount = L.filter(l => l.promoted).length;
  const soldCount = O.length;
  const totalImpressions = L.reduce((s, l) => s + (l.impressions || 0), 0);
  const totalClicks = L.reduce((s, l) => s + (l.clicks || 0), 0);
  const avgCTR = totalImpressions ? (totalClicks / totalImpressions * 100) : 0;
  const status = S ? S.overall_status : "UNKNOWN";
  const statusClass = status === "ABOVE_STANDARD" ? "good" : status === "BELOW_STANDARD" ? "bad" : "warn";

  document.getElementById("gen-at").textContent = DATA.generated_at.slice(0,10);
  document.getElementById("gen-count").textContent = L.length;

  const html = [
    `<div class="stat"><div class="label">Inventory Value</div><div class="value money">$${inventoryValue.toFixed(0)}</div><div class="sub">${L.length} active lots · avg $${(inventoryValue/Math.max(L.length,1)).toFixed(2)}</div></div>`,
    `<div class="stat"><div class="label">Lifetime Revenue</div><div class="value money">$${totalRevenue.toFixed(2)}</div><div class="sub">${soldCount} orders fulfilled</div></div>`,
    `<div class="stat"><div class="label">Total Impressions</div><div class="value">${totalImpressions.toLocaleString()}</div><div class="sub">${totalClicks.toLocaleString()} clicks · ${avgCTR.toFixed(2)}% CTR</div></div>`,
    `<div class="stat"><div class="label">Promoted Lots</div><div class="value">${promotedCount}</div><div class="sub">${(promotedCount/Math.max(L.length,1)*100).toFixed(0)}% of inventory</div></div>`,
    `<div class="stat"><span class="stat-badge ${statusClass}">${status.replace('_',' ')}</span><div class="label">Seller Status</div><div class="value" style="font-size:1.4rem;margin-top:14px">${S ? (S.eligible_for_top_rated_plus ? 'Top Rated Plus Eligible' : 'Standard Account') : '—'}</div><div class="sub">${S ? 'GMV $'+Number(S.gmv).toFixed(2)+' · '+S.transaction_count+' txns' : ''}</div></div>`,
  ].join("");
  document.getElementById("dashboard").innerHTML = html;
}

// ---------- CARDS ----------
function cardHTML(l){
  const isActive = l.listing_status === "ACTIVE";
  const isStale = (l.impressions||0) === 0 && isActive;
  const ctrPct = (l.ctr * 100).toFixed(2);
  return `
    <div class="card" data-id="${l.listing_id}">
      <div class="card-corner">$${(l.price||0).toFixed(2)}</div>
      <div class="card-id">ID ${l.listing_id}</div>
      <h3>${escapeHTML(l.title || 'Untitled Listing')}</h3>
      <div class="card-badges">
        ${isActive ? '<span class="badge active">ACTIVE</span>' : '<span class="badge sold">ENDED</span>'}
        ${l.promoted ? '<span class="badge promoted">⚡ PROMOTED</span>' : ''}
        ${l.orders_count > 0 ? `<span class="badge sold">${l.orders_count} SOLD</span>` : ''}
        ${isStale ? '<span class="badge stale">NO VIEWS</span>' : ''}
      </div>
      <div class="card-stats">
        <div class="card-stat"><div class="n">${(l.impressions||0).toLocaleString()}</div><div class="l">Impressions</div></div>
        <div class="card-stat"><div class="n">${(l.clicks||0)}</div><div class="l">Clicks</div></div>
        <div class="card-stat"><div class="n">${ctrPct}%</div><div class="l">CTR</div></div>
      </div>
      <div class="card-value">$${(l.revenue||0).toFixed(2)}<small>LIFETIME REVENUE</small></div>
      <div class="card-actions">
        <button class="btn primary" data-action="optimize" data-id="${l.listing_id}">AI Optimize</button>
        <a class="btn" href="${l.listing_url}" target="_blank" rel="noopener">View on eBay</a>
      </div>
    </div>`;
}

function escapeHTML(s){return (s||'').replace(/[&<>"']/g, m => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]))}

function renderGrid(list){
  const grid = document.getElementById("grid");
  grid.innerHTML = list.map(cardHTML).join("");
  grid.querySelectorAll(".card").forEach((c, i) => setTimeout(() => c.classList.add("in"), Math.min(i*20, 600)));
  grid.querySelectorAll("[data-action]").forEach(btn => {
    btn.addEventListener("click", () => {
      const l = DATA.listings.find(x => x.listing_id === btn.dataset.id);
      if (btn.dataset.action === "optimize") openOptimizer(l);
    });
  });
}

function applyFilters(){
  const q = document.getElementById("search").value.toLowerCase();
  const status = document.getElementById("filter-status").value;
  const sort = document.getElementById("filter-sort").value;
  const promotedOnly = document.getElementById("filter-promoted").checked;
  const soldOnly = document.getElementById("filter-sold").checked;
  let list = DATA.listings.filter(l => {
    if (q && !(l.title||'').toLowerCase().includes(q)) return false;
    if (status && l.listing_status !== status) return false;
    if (promotedOnly && !l.promoted) return false;
    if (soldOnly && !l.orders_count) return false;
    return true;
  });
  const [field, dir] = sort.split('-');
  list.sort((a,b) => {
    const av = a[field]||0, bv = b[field]||0;
    return dir === 'asc' ? av - bv : bv - av;
  });
  renderGrid(list);
}

// ---------- ANALYTICS ----------
function renderAnalytics(){
  const L = DATA.listings;
  const byRevenue = [...L].filter(l => l.revenue > 0).sort((a,b) => b.revenue - a.revenue).slice(0, 12);
  const byImpressions = [...L].sort((a,b) => (b.impressions||0) - (a.impressions||0)).slice(0, 12);
  renderBars("bars-revenue", byRevenue, l => l.revenue, v => '$'+v.toFixed(2));
  renderBars("bars-impressions", byImpressions, l => l.impressions||0, v => v.toLocaleString());

  // Promoted split
  const promoted = L.filter(l => l.promoted).length;
  const organic = L.length - promoted;
  const promotedRevenue = L.filter(l => l.promoted).reduce((s,l) => s + l.revenue, 0);
  const organicRevenue = L.filter(l => !l.promoted).reduce((s,l) => s + l.revenue, 0);
  document.getElementById("promoted-split").innerHTML = `
    <div class="bar-row"><div class="name">⚡ Promoted (${promoted})</div><div class="bar-track"><div class="bar-fill" style="width:${(promoted/L.length*100).toFixed(1)}%"></div></div><div class="val">$${promotedRevenue.toFixed(0)}</div></div>
    <div class="bar-row"><div class="name">Organic (${organic})</div><div class="bar-track"><div class="bar-fill" style="width:${(organic/L.length*100).toFixed(1)}%"></div></div><div class="val">$${organicRevenue.toFixed(0)}</div></div>`;

  // Price bands
  const bands = [
    {label: "< $5", test: p => p < 5},
    {label: "$5–$15", test: p => p >= 5 && p < 15},
    {label: "$15–$50", test: p => p >= 15 && p < 50},
    {label: "$50–$200", test: p => p >= 50 && p < 200},
    {label: "$200+", test: p => p >= 200},
  ];
  const counts = bands.map(b => ({label: b.label, n: L.filter(l => b.test(l.price||0)).length}));
  const max = Math.max(...counts.map(c => c.n), 1);
  document.getElementById("price-bands").innerHTML = counts.map(c =>
    `<div class="bar-row"><div class="name">${c.label}</div><div class="bar-track"><div class="bar-fill" style="width:${(c.n/max*100).toFixed(1)}%"></div></div><div class="val">${c.n}</div></div>`
  ).join("");
}

function renderBars(containerId, list, valFn, fmtFn){
  const max = Math.max(...list.map(valFn), 1);
  document.getElementById(containerId).innerHTML = list.map(l =>
    `<div class="bar-row"><div class="name" title="${escapeHTML(l.title)}">${escapeHTML((l.title||'').slice(0,50))}</div><div class="bar-track"><div class="bar-fill" data-w="${(valFn(l)/max*100).toFixed(1)}"></div></div><div class="val">${fmtFn(valFn(l))}</div></div>`
  ).join("");
  setTimeout(() => document.querySelectorAll('#'+containerId+' .bar-fill').forEach(b => b.style.width = b.dataset.w + '%'), 50);
}

// ---------- HEALTH ----------
function renderHealth(){
  const S = DATA.standards;
  const statusEl = document.getElementById("standards-status");
  const tbl = document.getElementById("standards-table");
  if (!S) { statusEl.textContent = "No seller standards data."; tbl.innerHTML = ""; return; }
  const cls = S.overall_status === "ABOVE_STANDARD" ? "above" : S.overall_status === "BELOW_STANDARD" ? "below" : "std";
  statusEl.innerHTML = `<div class="status-pill ${cls}">${S.overall_status.replace('_',' ')}</div><p style="margin-top:14px;color:var(--aged);font-family:'JetBrains Mono',monospace;font-size:.75rem">As of ${S.snapshot_date}</p>`;
  const rows = [
    ["Program", S.program],
    ["GMV", "$" + Number(S.gmv).toFixed(2)],
    ["Transactions", S.transaction_count],
    ["Defect Rate", (S.defect_rate*100).toFixed(2) + "%"],
    ["Defect Count", `${S.defect_count} / ${S.defect_denominator}`],
    ["Late Shipments", (S.late_shipment_rate*100).toFixed(2) + "%"],
    ["Cases Unresolved", S.cases_closed_without_resolution],
    ["Top Rated Plus Eligible", S.eligible_for_top_rated_plus ? "YES" : "NO"],
  ];
  tbl.innerHTML = rows.map(([k,v]) => `<tr><td>${k}</td><td>${v}</td></tr>`).join("");

  // Recent orders
  const orders = DATA.orders.slice(0, 30);
  document.getElementById("recent-orders").innerHTML = orders.map(o => `
    <div style="padding:10px 0;border-bottom:1px dashed var(--aged-deep)">
      <div style="display:flex;justify-content:space-between;gap:10px"><strong>$${Number(o.total_amount).toFixed(2)}</strong><span style="color:var(--aged-deep)">${(o.created_date||'').slice(0,10)}</span></div>
      <div style="color:var(--aged);margin-top:4px">${escapeHTML((o.item_title||'').slice(0,60))}</div>
      <div style="color:var(--aged-deep);margin-top:2px;font-size:.7rem">Buyer: ${escapeHTML(o.buyer_username||'?')} · ${o.order_status}</div>
    </div>`).join("");
}

// ---------- TABS ----------
document.querySelectorAll(".tab[data-tab]").forEach(t => {
  t.addEventListener("click", () => {
    document.querySelectorAll(".tab[data-tab]").forEach(x => x.classList.remove("active"));
    t.classList.add("active");
    const tab = t.dataset.tab;
    document.getElementById("view-lots").classList.toggle("hidden", tab !== "lots");
    document.getElementById("view-analytics").classList.toggle("hidden", tab !== "analytics");
    document.getElementById("view-health").classList.toggle("hidden", tab !== "health");
    if (tab === "analytics") renderAnalytics();
    if (tab === "health") renderHealth();
  });
});

// ---------- ANTHROPIC API ----------
function getApiKey(){ return localStorage.getItem("anthropic_api_key") || ""; }
async function callClaude(prompt, onChunk){
  const key = getApiKey();
  if (!key) throw new Error("No API key set. Click ⚙ API Key in the header to add one.");
  const res = await fetch("https://api.anthropic.com/v1/messages", {
    method: "POST",
    headers: { "content-type":"application/json", "x-api-key": key, "anthropic-version":"2023-06-01", "anthropic-dangerous-direct-browser-access":"true" },
    body: JSON.stringify({ model: MODEL, max_tokens: 1200, stream: true, messages: [{ role:"user", content: prompt }] }),
  });
  if (!res.ok) throw new Error(`API ${res.status}: ${await res.text()}`);
  const reader = res.body.getReader();
  const dec = new TextDecoder();
  let buf = "", full = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += dec.decode(value, { stream: true });
    const lines = buf.split("\n"); buf = lines.pop();
    for (const ln of lines) {
      if (ln.startsWith("data: ")) {
        const d = ln.slice(6).trim();
        if (d === "[DONE]") continue;
        try {
          const p = JSON.parse(d);
          if (p.type === "content_block_delta" && p.delta?.text) { full += p.delta.text; onChunk(full); }
        } catch(e) {}
      }
    }
  }
  return full;
}

// ---------- DRAWER ----------
const drawer = document.getElementById("drawer");
document.getElementById("drawer-close").addEventListener("click", () => drawer.classList.remove("open"));
function fmtMD(s){
  let h = s.replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/\*\*(.+?)\*\*/g,"<strong>$1</strong>");
  const lines = h.split("\n"); let out = "", inUl = false;
  for (const ln of lines) {
    const t = ln.trim();
    if (/^[-•]\s+/.test(t)) { if (!inUl) { out += "<ul>"; inUl = true; } out += "<li>" + t.replace(/^[-•]\s+/,"") + "</li>"; }
    else { if (inUl) { out += "</ul>"; inUl = false; } if (t) out += "<p>" + t + "</p>"; }
  }
  if (inUl) out += "</ul>";
  return out;
}

async function openOptimizer(l){
  document.getElementById("drawer-title").textContent = (l.title || 'Listing').slice(0, 60);
  document.getElementById("drawer-sub").textContent = `ID ${l.listing_id} · $${(l.price||0).toFixed(2)} · ${l.impressions||0} imp · ${l.clicks||0} clicks`;
  document.getElementById("drawer-body").innerHTML = `
    <div class="thought-bubble">
      <h4>AI LISTING OPTIMIZER</h4>
      <div id="opt-body"><span class="loading"></span> Calling Claude…</div>
    </div>
    <div id="opt-copy-wrap" style="margin-top:60px"></div>`;
  drawer.classList.add("open");

  const ctr = (l.ctr * 100).toFixed(2);
  const prompt = `You are an expert eBay listing optimizer reviewing a live listing.

LISTING DATA:
- Current title: "${l.title}"
- Price: $${l.price}
- Condition: ${l.condition || '(not set)'}
- Status: ${l.listing_status}
- Listing format: ${l.listing_format}
- Impressions: ${l.impressions || 0}
- Clicks: ${l.clicks || 0}
- CTR: ${ctr}%
- Page views: ${l.page_views || 0}
- Currently promoted: ${l.promoted ? 'YES' : 'NO'}
- Sales so far: ${l.orders_count} order(s), $${l.revenue} revenue

OUTPUT EXACTLY THESE FOUR SECTIONS, separated by blank lines:

DIAGNOSIS:
- 2-3 bullets identifying why this listing is/isn't performing.

OPTIMIZED TITLE:
<a single-line eBay title, max 80 chars, keyword-stuffed but readable. No quotes.>

OPTIMIZED DESCRIPTION:
<3-4 short paragraphs of eBay listing body copy. Plain text, no markdown.>

ACTIONS:
- 3 specific, prioritized next steps (e.g., "Bump promoted bid to 8%", "Add 'vintage' to title", "Photograph reverse side").

Be specific and grounded in the metrics. If impressions are zero, prioritize SEO/discoverability over conversion.`;

  const body = document.getElementById("opt-body");
  try {
    const full = await callClaude(prompt, (text) => { body.innerHTML = fmtMD(text); });
    document.getElementById("opt-copy-wrap").innerHTML = `<button class="copy-btn" id="copy-opt">Copy Optimization</button>`;
    document.getElementById("copy-opt").addEventListener("click", () => {
      navigator.clipboard.writeText(full).then(() => {
        const b = document.getElementById("copy-opt"); b.textContent = "✓ Copied!";
        setTimeout(() => b.textContent = "Copy Optimization", 1800);
      });
    });
  } catch(e) {
    body.innerHTML = `<p style="color:var(--blood-deep)"><strong>Error:</strong> ${e.message}</p>`;
  }
}

// ---------- SETTINGS ----------
const modal = document.getElementById("settings-modal");
document.getElementById("open-settings").addEventListener("click", () => { document.getElementById("api-key-input").value = getApiKey(); modal.classList.add("open"); });
document.getElementById("close-settings").addEventListener("click", () => modal.classList.remove("open"));
document.getElementById("save-key").addEventListener("click", () => { const v = document.getElementById("api-key-input").value.trim(); if (v) localStorage.setItem("anthropic_api_key", v); modal.classList.remove("open"); });
document.getElementById("clear-key").addEventListener("click", () => { localStorage.removeItem("anthropic_api_key"); document.getElementById("api-key-input").value = ""; });

// ---------- WIRE FILTERS ----------
["search","filter-status","filter-sort","filter-promoted","filter-sold"].forEach(id => document.getElementById(id).addEventListener("input", applyFilters));

// ---------- BOOT ----------
renderDashboard();
applyFilters();
</script>
</body>
</html>
"""


def main():
    if not DB.exists():
        raise SystemExit(f"warehouse.db not found at {DB}")
    con = duckdb.connect(str(DB), read_only=True)
    payload = gather(con)
    payload = to_native(payload)
    html = HTML_TEMPLATE.replace("__DATA__", json.dumps(payload, default=str))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(html, encoding="utf-8")
    size_kb = OUT.stat().st_size / 1024
    print(f"Wrote {OUT} ({size_kb:.1f} KB)")
    print(f"Listings: {len(payload['listings'])}  Orders: {len(payload['orders'])}  Promoted: {len(payload['promoted'])}")


if __name__ == "__main__":
    main()
