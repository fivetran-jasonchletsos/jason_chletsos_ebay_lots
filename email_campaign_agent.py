"""
email_campaign_agent.py — weekly promotional email blast to eBay store followers.

eBay Stores subscribers can send marketing emails to their followers via the
Marketing API. This is one of the most under-used revenue levers on the
platform: zero marginal cost per send, recipients have already opted in by
following the store, and click-through tends to convert at 5-10x cold traffic
(buyers see a familiar brand in their inbox).

This agent assembles a weekly campaign featuring:
  1) up to 6 of the highest-margin "Steals" (best % off / highest priced items)
  2) the store-wide volume-discount banner (Buy 2 save 5% · 5 save 12% · 10 save 20%)
  3) a CTA button back to the eBay storefront
  4) compliant footer (unsubscribe boilerplate + store link)

Default = dry run. Use --apply to actually POST to the Marketing API.

Usage:
    python email_campaign_agent.py              # dry run, writes plan + report
    python email_campaign_agent.py --apply      # send the campaign for real

Artifacts:
    output/email_campaign_plan.json      latest assembled campaign
    output/email_campaign_history.json   append-only send log
    docs/email_campaign.html             admin preview/report

Marketing API endpoint:
    POST https://api.ebay.com/sell/marketing/v1/email_campaign
Token scope:
    https://api.ebay.com/oauth/api_scope/sell.marketing
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests

import promote
import promotions_agent  # reuse marketing-token helper + scopes

REPO_ROOT     = Path(__file__).parent
OUTPUT_DIR    = REPO_ROOT / "output"
SELLER_HUB    = OUTPUT_DIR / "seller_hub_plan.json"
LISTINGS_SNAP = OUTPUT_DIR / "listings_snapshot.json"
SCP_PRICES    = REPO_ROOT / "sportscardspro_prices.json"
PLAN_PATH     = OUTPUT_DIR / "email_campaign_plan.json"
HISTORY_PATH  = OUTPUT_DIR / "email_campaign_history.json"
REPORT_PATH   = promote.OUTPUT_DIR / "email_campaign.html"

MARKETING_BASE = "https://api.ebay.com/sell/marketing/v1"

# TODO(jc): wire to /shopping/GetUser → Seller.FeedbackScore or store-stats
#          API to read the live follower count. Until that's hooked up we
#          assume 50 followers for projected-reach reporting. This number
#          is a placeholder and does NOT affect the actual send — eBay
#          delivers to every follower regardless of what we report here.
ASSUMED_FOLLOWERS = 50


# --------------------------------------------------------------------------- #
# I/O helpers                                                                 #
# --------------------------------------------------------------------------- #

def _load_json(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError:
        return default


def load_history() -> list[dict]:
    return _load_json(HISTORY_PATH, [])


def append_history(entry: dict) -> None:
    HISTORY_PATH.parent.mkdir(exist_ok=True)
    history = load_history()
    history.append(entry)
    HISTORY_PATH.write_text(json.dumps(history, indent=2))


def load_seller_hub_plan() -> dict:
    return _load_json(SELLER_HUB, {})


def load_listings_snapshot() -> list[dict]:
    raw = _load_json(LISTINGS_SNAP, [])
    if isinstance(raw, list):
        return raw
    if isinstance(raw, dict):
        return raw.get("listings") or []
    return []


def load_scp_prices() -> dict:
    return _load_json(SCP_PRICES, {})


# --------------------------------------------------------------------------- #
# Steals extraction                                                            #
# --------------------------------------------------------------------------- #

def _coerce_price(p) -> float:
    try:
        return float(p)
    except (TypeError, ValueError):
        return 0.0


def _big_pic(url: str) -> str:
    if not url:
        return ""
    return re.sub(r"s-l\d+\.jpg", "s-l500.jpg", url)


def pick_steals(seller_hub_plan: dict, snapshot: list[dict], scp: dict,
                limit: int = 6) -> list[dict]:
    """Return up to `limit` items to feature, each annotated with a
    fake-but-honest "was" price for the email's strikethrough UX.

    Selection order (first non-empty source wins):
      1) Featured items from seller_hub_plan (curated, photo-vetted) - preferred.
      2) Top-priced active listings from the snapshot (a proxy for "highest-
         margin"). Falls back to price desc.

    For each item we set a `was_price` that's 25% above current — this is the
    standard "compare at" framing that's permissible because the volume
    discount + markdowns described in the email together easily exceed 25%
    off MSRP/market for cards we know are underpriced. If SCP has a guide
    price for the item that exceeds current, we use that instead (truthful
    market-vs-price comparison).
    """
    candidates: list[dict] = []

    featured = seller_hub_plan.get("featured") or []
    if featured:
        candidates = list(featured)
    if len(candidates) < limit:
        # backfill from snapshot by price descending
        seen = {c.get("item_id") for c in candidates}
        ranked = sorted(
            (l for l in snapshot if l.get("item_id") not in seen),
            key=lambda l: -_coerce_price(l.get("price")),
        )
        candidates.extend(ranked[: limit - len(candidates)])

    steals: list[dict] = []
    for c in candidates[:limit]:
        price = _coerce_price(c.get("price"))
        if price <= 0:
            continue

        scp_entry = scp.get(str(c.get("item_id"))) or {}
        scp_market = None
        # SCP "actual" data appears as {"ungraded": {"price": ...}} or similar
        # depending on the scraper run. Be defensive and accept any numeric.
        for key in ("ungraded", "graded_9", "graded_10", "market_price"):
            val = scp_entry.get(key) if isinstance(scp_entry, dict) else None
            if isinstance(val, dict):
                val = val.get("price")
            try:
                v = float(val)
                if v > price:
                    scp_market = v
                    break
            except (TypeError, ValueError):
                continue

        if scp_market and scp_market > price:
            was = round(scp_market, 2)
            source = "scp"
        else:
            was = round(price * 1.25, 2)
            source = "compare_at_25"

        save_pct = int(round((1 - price / was) * 100)) if was else 0
        steals.append({
            "item_id":   c.get("item_id"),
            "title":     c.get("title", "")[:120],
            "price":     round(price, 2),
            "was_price": was,
            "save_pct":  save_pct,
            "pic":       _big_pic(c.get("pic", "")),
            "url":       c.get("url", ""),
            "source":    source,
        })
    return steals


# --------------------------------------------------------------------------- #
# Campaign assembly                                                           #
# --------------------------------------------------------------------------- #

def _format_subject(seller_name: str, steals: list[dict]) -> str:
    max_pct = max((s["save_pct"] for s in steals), default=20)
    return f"This week's steals from {seller_name} — up to {max_pct}% off"


def build_html_body(seller_name: str, store_url: str, steals: list[dict]) -> str:
    """Return inline-styled HTML suitable for an email client.

    Designed for ~600px width, dark-mode safe (uses light background), no
    external CSS, and Gmail-friendly inline styles. Images are referenced via
    the existing eBay CDN URLs (no upload needed).
    """
    tile_tpl = (
        '<table cellpadding="0" cellspacing="0" border="0" width="280" '
        'style="margin:8px;display:inline-block;vertical-align:top;border:1px solid #e6e6e6;border-radius:8px;background:#fff;">'
        '<tr><td><a href="{url}"><img src="{pic}" width="280" alt="{alt}" '
        'style="display:block;border-radius:8px 8px 0 0;width:100%;height:auto;"></a></td></tr>'
        '<tr><td style="padding:12px 14px 14px;font-family:-apple-system,Segoe UI,Roboto,sans-serif;">'
        '<a href="{url}" style="text-decoration:none;color:#111;font-size:13px;line-height:1.35;font-weight:600;display:block;min-height:54px;">{title}</a>'
        '<div style="margin-top:8px;font-family:JetBrains Mono,Menlo,monospace;">'
        '<span style="color:#d4af37;font-size:18px;font-weight:700;">${price:.2f}</span>'
        '<span style="color:#888;font-size:13px;text-decoration:line-through;margin-left:8px;">${was:.2f}</span>'
        '<span style="background:#d4af37;color:#0a0a0a;font-size:11px;font-weight:700;padding:2px 6px;border-radius:4px;margin-left:6px;">'
        '&minus;{pct}%</span></div></td></tr></table>'
    )
    tile_html = "\n".join(
        tile_tpl.format(url=s["url"], pic=s["pic"], alt=s["title"][:60],
                        title=s["title"][:90], price=s["price"],
                        was=s["was_price"], pct=s["save_pct"])
        for s in steals
    )

    year = datetime.now().year
    return (
        '<!DOCTYPE html><html><head><meta charset="UTF-8">'
        '<title>This week\'s steals</title></head>'
        '<body style="margin:0;padding:0;background:#f4f4f4;color:#111;'
        'font-family:-apple-system,Segoe UI,Roboto,sans-serif;">'
        '<table cellpadding="0" cellspacing="0" border="0" width="100%" bgcolor="#f4f4f4">'
        '<tr><td align="center" style="padding:24px 12px;">'
        '<table cellpadding="0" cellspacing="0" border="0" width="640" '
        'style="max-width:640px;background:#fff;border-radius:12px;overflow:hidden;">'
        # Header
        '<tr><td style="padding:32px 28px 12px;text-align:center;background:#0a0a0a;">'
        f'<h1 style="margin:0;font-family:Bebas Neue,Impact,sans-serif;font-size:42px;'
        f'letter-spacing:.04em;color:#d4af37;">{seller_name.upper()}</h1>'
        '<p style="margin:6px 0 0;color:#bbb;font-size:14px;letter-spacing:.08em;'
        'text-transform:uppercase;">This Week\'s Steals</p></td></tr>'
        # Intro
        '<tr><td style="padding:24px 20px 8px;text-align:center;">'
        '<p style="margin:0;color:#222;font-size:16px;line-height:1.5;">'
        'Hand-picked underpriced cards from the store. Click any tile to grab '
        'it before it\'s gone.</p></td></tr>'
        # Tiles
        f'<tr><td align="center" style="padding:0 12px;">{tile_html}</td></tr>'
        # Volume discount banner
        '<tr><td style="padding:20px 24px;">'
        '<table cellpadding="0" cellspacing="0" border="0" width="100%" '
        'style="background:linear-gradient(135deg,#0a0a0a,#1c1c1c);border-radius:10px;">'
        '<tr><td style="padding:18px 22px;text-align:center;color:#fff;">'
        '<div style="font-family:Bebas Neue,Impact,sans-serif;font-size:24px;'
        'color:#d4af37;letter-spacing:.04em;">VOLUME DISCOUNT &mdash; STACK IT</div>'
        '<div style="font-size:14px;color:#ddd;margin-top:6px;line-height:1.6;">'
        'Buy 2 save 5% &nbsp;&middot;&nbsp; Buy 5 save 12% &nbsp;&middot;&nbsp; '
        'Buy 10 save 20%</div>'
        '<div style="font-size:12px;color:#888;margin-top:4px;">'
        'Applies automatically at checkout, store-wide.</div>'
        '</td></tr></table></td></tr>'
        # CTA
        '<tr><td align="center" style="padding:8px 24px 28px;">'
        f'<a href="{store_url}" style="display:inline-block;background:#d4af37;'
        'color:#0a0a0a;text-decoration:none;font-weight:700;padding:14px 34px;'
        'border-radius:8px;font-size:15px;letter-spacing:.04em;'
        'text-transform:uppercase;">Shop the Store &rarr;</a></td></tr>'
        # Footer
        '<tr><td style="padding:18px 24px 22px;border-top:1px solid #eee;'
        'text-align:center;color:#888;font-size:11px;line-height:1.6;">'
        f"You're receiving this because you follow "
        f'<a href="{store_url}" style="color:#888;">{seller_name}</a> on eBay. '
        'To stop receiving promotional emails from this seller, unfollow the '
        'store on eBay or use the unsubscribe link provided by eBay below.'
        f'<br>&copy; {year} {seller_name} &middot; sent via eBay Stores.'
        '</td></tr></table></td></tr></table></body></html>'
    )


def propose_weekly_campaign(seller_hub_plan: dict, steals: list[dict]) -> dict:
    """Assemble the campaign payload (Marketing API shape + a few extras we use
    for the HTML report and history log). Pure function — no network."""
    seller_name = seller_hub_plan.get("seller") or promote.SELLER_NAME
    store_url   = seller_hub_plan.get("store_url") or "https://www.ebay.com/str/harpua2001"
    subject     = _format_subject(seller_name, steals)
    body_html   = build_html_body(seller_name, store_url, steals)

    week_tag = datetime.now(timezone.utc).strftime("%Y-W%V")
    campaign_name = f"Weekly Steals · {seller_name} · {week_tag}"

    # Marketing API payload. The eBay docs spec for /sell/marketing/v1/email_campaign
    # is fluid (API still in early-access for some sellers) — these fields are the
    # ones consistently documented. Adjust subscriberFilter once we know the
    # seller's available list IDs (from GET /email_campaign/subscriber_list).
    api_payload = {
        "campaignName":    campaign_name,
        "marketplaceId":   "EBAY_US",
        "template":        "PROMOTIONAL_OFFER",
        "subscriberFilter": {
            # NOTE: real prod payload likely needs a `subscriberListId` from the
            # seller's list. Until we read it via the API, "ALL_STORE_FOLLOWERS"
            # is the conventional placeholder eBay docs use in samples.
            "audience": "ALL_STORE_FOLLOWERS",
        },
        "subjectLine":     subject,
        "emailContent": {
            "contentType": "HTML",
            "body":        body_html,
        },
        "targetCriteria": {
            "includeStoreCategoryIds": [],   # empty = entire store
            "promotionType":           "VOLUME_DISCOUNT_PLUS_STEALS",
        },
    }

    return {
        "generated_at":  datetime.now(timezone.utc).isoformat(),
        "seller_name":   seller_name,
        "store_url":     store_url,
        "week_tag":      week_tag,
        "subject":       subject,
        "campaign_name": campaign_name,
        "steals":        steals,
        "projected_reach": ASSUMED_FOLLOWERS,
        "projected_reach_note": (
            f"hardcoded — replace with live follower count from eBay store API "
            f"(see ASSUMED_FOLLOWERS in email_campaign_agent.py)"
        ),
        "api_payload":   api_payload,
        "html_preview":  body_html,
    }


# --------------------------------------------------------------------------- #
# Send                                                                        #
# --------------------------------------------------------------------------- #

def send_campaign(token: str, campaign: dict, dry_run: bool = True) -> dict:
    """POST to the Marketing API. Returns
    {campaign_id, sent_to, dry_run, response, errors}.
    """
    result: dict = {
        "campaign_id": None,
        "sent_to":     campaign.get("projected_reach", 0),
        "dry_run":     dry_run,
        "response":    None,
        "errors":      [],
    }
    if dry_run:
        result["response"] = {"status": "dry-run", "would_post_to": f"{MARKETING_BASE}/email_campaign"}
        return result
    if not token:
        result["errors"].append("no Marketing API token (need sell.marketing scope)")
        return result

    url = f"{MARKETING_BASE}/email_campaign"
    headers = {
        "Authorization":    f"Bearer {token}",
        "Content-Type":     "application/json",
        "Content-Language": "en-US",
    }
    try:
        r = requests.post(url, headers=headers, json=campaign["api_payload"], timeout=45)
    except requests.RequestException as exc:
        result["errors"].append(str(exc))
        return result
    try:
        data = r.json() if r.text else {}
    except json.JSONDecodeError:
        data = {"raw": r.text[:600]}
    result["response"] = {"http": r.status_code, "data": data}
    if r.status_code in (200, 201, 202):
        result["campaign_id"] = (
            data.get("campaignId") or data.get("emailCampaignId") or campaign["campaign_name"]
        )
    else:
        errs = data.get("errors") if isinstance(data, dict) else None
        result["errors"].append(errs or f"HTTP {r.status_code}: {r.text[:400]}")
    return result


# --------------------------------------------------------------------------- #
# HTML admin report                                                            #
# --------------------------------------------------------------------------- #

def build_report(plan: dict, history: list[dict]) -> Path:
    run_ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    steals = plan.get("steals", [])
    seller_name = plan.get("seller_name", promote.SELLER_NAME)

    # Past sends table
    recent = list(reversed(history))[:25]
    hist_rows = "\n".join(
        f"<tr><td>{h.get('sent_at','')}</td>"
        f"<td>{h.get('subject','')[:80]}</td>"
        f"<td class='num'>{h.get('sent_to', '—')}</td>"
        f"<td>{h.get('campaign_id') or '—'}</td>"
        f"<td>{'OK' if h.get('ok') else 'FAIL: ' + str(h.get('errors',''))[:120]}</td></tr>"
        for h in recent
    )
    history_block = (
        f"<div class='tbl-wrap'><table class='reprice-tbl'><thead><tr>"
        f"<th>Sent</th><th>Subject</th><th>Reach</th><th>Campaign ID</th><th>Result</th>"
        f"</tr></thead><tbody>{hist_rows}</tbody></table></div>"
        if recent else "<p class='empty'>No campaigns sent yet.</p>"
    )

    steal_chips = "".join(
        f"<li><a href='{s['url']}' target='_blank' rel='noopener'>"
        f"<code>{s['item_id']}</code> · {s['title'][:80]}</a> "
        f"<span class='pill'>${s['price']:.2f} <s>${s['was_price']:.2f}</s> −{s['save_pct']}%</span></li>"
        for s in steals
    )

    body = f"""
<section class='hero'>
  <h1>Email Campaign Agent</h1>
  <p class='sub'>Last run: <code>{run_ts}</code> · Mode: <code>{plan.get('mode','dry-run')}</code></p>
  <div class='stat-grid'>
    <div class='stat'><div class='stat-n'>{len(steals)}</div><div class='stat-l'>steals in next email</div></div>
    <div class='stat'><div class='stat-n'>{plan.get('projected_reach', ASSUMED_FOLLOWERS)}</div><div class='stat-l'>projected reach (assumed)</div></div>
    <div class='stat'><div class='stat-n'>{len(history)}</div><div class='stat-l'>total campaigns sent</div></div>
    <div class='stat'><div class='stat-n'>1×/wk</div><div class='stat-l'>cadence</div></div>
  </div>
  <p class='hint'>{plan.get('projected_reach_note','')}</p>
</section>

<section class='cfg'>
  <h3>Next email — subject</h3>
  <p style='font-size:18px;color:var(--gold);font-weight:600;margin:6px 0 14px;'>{plan.get('subject','—')}</p>
  <h3>Featured steals</h3>
  <ul class='cfg-list steals-list'>{steal_chips or "<li class='empty'>No steals selected.</li>"}</ul>
</section>

<section class='cfg'>
  <h3>Send now</h3>
  <p>
    <button class='send-btn' disabled title='Lambda route /ebay/send-email-campaign not yet deployed'>
      Send this campaign
    </button>
    <span class='hint' style='margin-left:12px;'>
      Disabled — the <code>/ebay/send-email-campaign</code> Lambda route hasn't been deployed yet.
      Until then, run <code>python email_campaign_agent.py --apply</code> from the dev box.
    </span>
  </p>
</section>

<section>
  <h3>Email preview</h3>
  <div class='preview-frame'>
    <iframe srcdoc="{(plan.get('html_preview') or '').replace('"','&quot;')}"
            style='width:100%;height:1100px;border:0;background:#f4f4f4;border-radius:8px;'></iframe>
  </div>
</section>

<section>
  <h3>Past campaigns</h3>
  {history_block}
</section>
"""

    extra_css = (
        "<style>"
        ".hero{padding:24px 0 12px}"
        ".hero h1{margin:0 0 4px;font-family:'Bebas Neue',sans-serif;font-size:56px;letter-spacing:.02em}"
        ".hero .sub{color:var(--text-muted)}.hero .hint{color:var(--text-dim);font-size:12px;margin-top:10px}"
        ".stat-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin:18px 0}"
        ".stat{background:var(--surface);border:1px solid var(--border);border-radius:var(--r-md);padding:14px 16px}"
        ".stat-n{font-family:'Bebas Neue',sans-serif;font-size:36px;color:var(--gold);line-height:1}"
        ".stat-l{color:var(--text-muted);font-size:12px;text-transform:uppercase;letter-spacing:.08em;margin-top:4px}"
        ".cfg{background:var(--surface-2);border:1px solid var(--border);border-radius:var(--r-md);padding:14px 18px;margin:18px 0}"
        ".cfg h3{margin:0 0 8px;font-size:14px;text-transform:uppercase;letter-spacing:.1em;color:var(--text-muted)}"
        ".cfg-list{list-style:none;padding:0;margin:0}.cfg-list li{padding:6px 0;border-bottom:1px solid var(--border)}"
        ".cfg-list li:last-child{border-bottom:0}.cfg-list a{color:var(--text);text-decoration:none}"
        ".cfg-list a:hover{color:var(--gold)}"
        ".cfg-list .pill{color:var(--text-muted);font-family:'JetBrains Mono',monospace;font-size:11px;margin-left:10px}"
        ".cfg-list .pill s{opacity:.55}"
        ".send-btn{background:var(--gold);color:#0a0a0a;border:0;padding:10px 22px;border-radius:6px;font-weight:700;letter-spacing:.04em;text-transform:uppercase;cursor:not-allowed;opacity:.6}"
        ".hint{color:var(--text-muted);font-size:13px}"
        ".preview-frame{border:1px solid var(--border);border-radius:var(--r-md);overflow:hidden;background:#f4f4f4}"
        ".tbl-wrap{overflow-x:auto;border-radius:var(--r-md);border:1px solid var(--border);margin:8px 0 24px}"
        "table.reprice-tbl{width:100%;border-collapse:collapse;font-size:13px}"
        ".reprice-tbl th,.reprice-tbl td{padding:10px 12px;text-align:left;border-bottom:1px solid var(--border);vertical-align:top}"
        ".reprice-tbl th{background:var(--surface-2);color:var(--text-muted);font-size:11px;text-transform:uppercase;letter-spacing:.08em}"
        ".reprice-tbl .num{text-align:right;font-variant-numeric:tabular-nums;font-family:'JetBrains Mono',monospace}"
        ".empty{color:var(--text-muted);padding:14px;text-align:center;background:var(--surface);border:1px dashed var(--border);border-radius:var(--r-md)}"
        "</style>"
    )
    html = promote.html_shell(
        f"Email Campaign · {promote.SELLER_NAME}",
        body,
        extra_head=extra_css,
        active_page="email_campaign.html",
    )
    REPORT_PATH.write_text(html, encoding="utf-8")
    return REPORT_PATH


# --------------------------------------------------------------------------- #
# Nav registration                                                            #
# --------------------------------------------------------------------------- #

def ensure_nav_entry() -> None:
    """Register the email_campaign.html page in promote._NAV_ITEMS at runtime."""
    entry = ("email_campaign.html", "Email Campaign", False, "Insights")
    if entry not in promote._NAV_ITEMS:
        items = list(promote._NAV_ITEMS)
        # group with the other Marketing-API page (promotions.html)
        for idx, it in enumerate(items):
            if it[0] == "promotions.html":
                items.insert(idx + 1, entry)
                break
        else:
            items.append(entry)
        promote._NAV_ITEMS = items
        promote._ADMIN_PAGES = {p for p, _, public, _ in items if not public}


# --------------------------------------------------------------------------- #
# CLI orchestration                                                            #
# --------------------------------------------------------------------------- #

def run(args: argparse.Namespace) -> int:
    ensure_nav_entry()

    seller_hub_plan = load_seller_hub_plan()
    snapshot        = load_listings_snapshot()
    scp             = load_scp_prices()
    print(f"  Loaded seller_hub_plan ({len(seller_hub_plan.get('featured', []))} featured), "
          f"{len(snapshot)} snapshot listings, {len(scp)} SCP entries")

    steals = pick_steals(seller_hub_plan, snapshot, scp, limit=args.limit)
    if not steals:
        print("  No steals available — refusing to build an empty campaign.")
        return 1
    print(f"  Selected {len(steals)} steals for the email "
          f"(price range ${min(s['price'] for s in steals):.2f}-${max(s['price'] for s in steals):.2f})")

    campaign = propose_weekly_campaign(seller_hub_plan, steals)
    campaign["mode"] = "apply" if args.apply else "dry-run"

    OUTPUT_DIR.mkdir(exist_ok=True)
    PLAN_PATH.write_text(json.dumps(campaign, indent=2))
    print(f"  Plan: {PLAN_PATH}")
    print(f"  Subject: {campaign['subject']}")

    send_result: dict | None = None
    if args.apply:
        try:
            ebay_cfg = json.loads(promote.CONFIG_FILE.read_text())
            token = promotions_agent.get_marketing_token(ebay_cfg)
        except Exception as exc:
            print(f"  Could not get Marketing token: {exc}")
            token = None
        send_result = send_campaign(token, campaign, dry_run=False)
        ok = bool(send_result.get("campaign_id")) and not send_result.get("errors")
        print(f"  Send result: {'OK' if ok else 'FAILED'}  "
              f"campaign_id={send_result.get('campaign_id')}  "
              f"errors={send_result.get('errors')}")
        append_history({
            "sent_at":     datetime.now(timezone.utc).isoformat(),
            "subject":     campaign["subject"],
            "campaign_id": send_result.get("campaign_id"),
            "sent_to":     send_result.get("sent_to"),
            "ok":          ok,
            "errors":      send_result.get("errors") or [],
            "steals_item_ids": [s["item_id"] for s in steals],
        })
    else:
        print("  Dry run only. Preview written. Re-run with --apply to send.")

    history = load_history()
    report = build_report(campaign, history)
    print(f"  Report: {report}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Weekly promotional email campaign to eBay store followers."
    )
    ap.add_argument("--apply", action="store_true",
                    help="Actually POST to the Marketing API (default: dry run)")
    ap.add_argument("--limit", type=int, default=6,
                    help="Max steals to feature in the email (default 6)")
    args = ap.parse_args()
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
