"""
promote.py - Free listing promotion tools for Harpua2001 / jason_chletsos_ebay

Generates a GitHub Pages site with:
  - Mobile-first listing dashboard (searchable, filterable)
  - Listing quality report (fixable issues ranked by impact)
  - Google Merchant Center RSS feed (free Google Shopping placement)
  - Craigslist post generator (ready-to-paste ads per listing)
  - Analysis SQL views for Fivetran/Databricks schema

Run:
  python3 promote.py

Output goes to ./docs/ (GitHub Pages root).
Push to GitHub and enable Pages at:
  github.com/fivetran-jasonchletsos/jason_chletsos_ebay_lots
  Settings -> Pages -> Branch: main, Folder: /docs
"""

import base64
import json
import os
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote
from xml.dom import minidom

import requests

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

CONFIG_FILE  = Path(__file__).parent / "configuration.json"
LOCKS_FILE   = Path(__file__).parent / "locks.json"
ADMIN_FILE   = Path(__file__).parent / "admin.json"
OUTPUT_DIR   = Path(__file__).parent / "docs"
OUTPUT_DIR.mkdir(exist_ok=True)

# Stable per-installation salt for admin password hashes. Stored alongside
# the passwords in admin.json (gitignored) so it survives across rebuilds
# without invalidating the user's stored login token on every deploy.
# Old tokens still auto-expire when the password itself rotates because the
# hash changes; the salt no longer needs to rotate just to achieve that.
import hashlib as _hashlib, secrets as _secrets


def _ensure_admin_salt() -> str:
    """Read or generate a stable salt persisted in admin.json."""
    if not ADMIN_FILE.exists():
        return _secrets.token_hex(16)
    try:
        data = json.loads(ADMIN_FILE.read_text())
        if isinstance(data, dict) and isinstance(data.get("salt"), str) and len(data["salt"]) >= 16:
            return data["salt"]
        # No salt yet — generate one and persist it
        if isinstance(data, dict):
            data["salt"] = _secrets.token_hex(16)
            ADMIN_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
            return data["salt"]
    except Exception:
        pass
    return _secrets.token_hex(16)


_ADMIN_SALT = _ensure_admin_salt()


def load_admin_hashes() -> list[str]:
    """Read admin.json (gitignored), return SHA-256(salt+pw) hashes."""
    if not ADMIN_FILE.exists():
        return []
    try:
        data = json.loads(ADMIN_FILE.read_text())
        pwds = data.get("passwords", []) if isinstance(data, dict) else []
        return [
            _hashlib.sha256((_ADMIN_SALT + str(p)).encode()).hexdigest()
            for p in pwds
            if p and not str(p).startswith("set-your-")
        ]
    except Exception:
        return []


def load_locks() -> dict:
    """Load known-locked items: {item_id: {code, reason, since}}."""
    if not LOCKS_FILE.exists():
        return {}
    try:
        data = json.loads(LOCKS_FILE.read_text())
        return data.get("items", {}) if isinstance(data, dict) else {}
    except Exception:
        return {}

SELLER_NAME  = "Harpua2001"
STORE_URL    = "https://www.ebay.com/usr/harpua2001"
SITE_URL     = "https://fivetran-jasonchletsos.github.io/jason_chletsos_ebay_lots"
CURRENCY     = "USD"

# ---------------------------------------------------------------------------
# eBay auth
# ---------------------------------------------------------------------------

def get_access_token(cfg: dict) -> str:
    credentials = base64.b64encode(
        f"{cfg['client_id']}:{cfg['client_secret']}".encode()
    ).decode()
    resp = requests.post(
        "https://api.ebay.com/identity/v1/oauth2/token",
        headers={
            "Authorization": f"Basic {credentials}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        data={
            "grant_type":   "refresh_token",
            "refresh_token": cfg["refresh_token"],
            "scope": " ".join([
                "https://api.ebay.com/oauth/api_scope",
                "https://api.ebay.com/oauth/api_scope/sell.inventory.readonly",
                "https://api.ebay.com/oauth/api_scope/sell.fulfillment.readonly",
            ]),
        },
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def get_app_token(cfg: dict) -> str:
    """Client-credentials token for Browse API (no user context needed)."""
    credentials = base64.b64encode(
        f"{cfg['client_id']}:{cfg['client_secret']}".encode()
    ).decode()
    resp = requests.post(
        "https://api.ebay.com/identity/v1/oauth2/token",
        headers={
            "Authorization": f"Basic {credentials}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        data={
            "grant_type": "client_credentials",
            "scope":      "https://api.ebay.com/oauth/api_scope",
        },
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


# ---------------------------------------------------------------------------
# Fetch sold listings (Trading API GetOrders) + persistent history accumulator
# ---------------------------------------------------------------------------
SOLD_HISTORY_FILE = Path(__file__).parent / "sold_history.json"


def _load_sold_history() -> list[dict]:
    if not SOLD_HISTORY_FILE.exists():
        return []
    try:
        return json.load(open(SOLD_HISTORY_FILE))
    except Exception:
        return []


def _save_sold_history(items: list[dict]) -> None:
    SOLD_HISTORY_FILE.write_text(json.dumps(items, indent=2, default=str), encoding="utf-8")


def _redact_buyer(uid: str) -> str:
    """Redact buyer username for the public site — keep first 1 char + length hint."""
    if not uid:
        return ""
    if len(uid) <= 2:
        return uid[0] + "*"
    return uid[0] + "*" * (len(uid) - 1)


def fetch_sold_listings(token: str, cfg: dict, days_back: int = 90) -> list[dict]:
    """
    Fetch completed orders via Trading API GetOrders (90-day max window).
    Merges with persisted history at sold_history.json so the page shows
    all-time sales regardless of eBay's 90-day API limit.
    """
    from datetime import datetime as _dt, timedelta as _td

    days_back = min(max(int(days_back), 1), 90)
    now = _dt.now(timezone.utc)
    start = now - _td(days=days_back)

    NS = "{urn:ebay:apis:eBLBaseComponents}"
    headers = {
        "X-EBAY-API-SITEID":              "0",
        "X-EBAY-API-COMPATIBILITY-LEVEL": "967",
        "X-EBAY-API-CALL-NAME":           "GetOrders",
        "X-EBAY-API-APP-NAME":            cfg.get("client_id", ""),
        "X-EBAY-API-DEV-NAME":            cfg.get("dev_id", ""),
        "X-EBAY-API-CERT-NAME":           cfg.get("client_secret", ""),
        "Content-Type":                   "text/xml",
    }

    # Paginate through all pages
    fresh: list[dict] = []
    page = 1
    while True:
        xml_body = f"""<?xml version="1.0" encoding="utf-8"?>
<GetOrdersRequest xmlns="urn:ebay:apis:eBLBaseComponents">
  <RequesterCredentials><eBayAuthToken>{token}</eBayAuthToken></RequesterCredentials>
  <CreateTimeFrom>{start.strftime('%Y-%m-%dT%H:%M:%S.000Z')}</CreateTimeFrom>
  <CreateTimeTo>{now.strftime('%Y-%m-%dT%H:%M:%S.000Z')}</CreateTimeTo>
  <OrderRole>Seller</OrderRole>
  <OrderStatus>All</OrderStatus>
  <Pagination><EntriesPerPage>100</EntriesPerPage><PageNumber>{page}</PageNumber></Pagination>
  <DetailLevel>ReturnAll</DetailLevel>
</GetOrdersRequest>"""
        try:
            resp = requests.post("https://api.ebay.com/ws/api.dll", data=xml_body, headers=headers, timeout=30)
            resp.raise_for_status()
        except Exception as exc:
            print(f"  GetOrders fetch failed (page {page}): {exc}")
            break
        root = ET.fromstring(resp.text)
        if root.findtext(f"{NS}Ack") not in ("Success", "Warning"):
            err = root.find(f".//{NS}Errors")
            if err is not None:
                print(f"  GetOrders error: [{err.findtext(f'{NS}ErrorCode')}] {err.findtext(f'{NS}LongMessage', '')[:120]}")
            break

        for order in root.findall(f".//{NS}Order"):
            order_id   = order.findtext(f"{NS}OrderID", "")
            created    = order.findtext(f"{NS}CreatedTime", "") or order.findtext(f"{NS}PaidTime", "")
            paid       = order.findtext(f"{NS}PaidTime", "")
            status     = order.findtext(f"{NS}OrderStatus", "")
            buyer      = order.findtext(f"{NS}BuyerUserID", "")
            ship_cost  = order.findtext(f"{NS}ShippingServiceSelected/{NS}ShippingServiceCost", "") \
                       or order.findtext(f"{NS}ShippingDetails/{NS}ShippingServiceOptions/{NS}ShippingServiceCost", "")
            order_total = order.findtext(f"{NS}Total", "0")

            # An Order can have multiple Transactions (line items) — flatten each as a row
            for trans in order.findall(f".//{NS}Transaction"):
                item       = trans.find(f"{NS}Item")
                if item is None:
                    continue
                item_id    = item.findtext(f"{NS}ItemID", "")
                title      = item.findtext(f"{NS}Title", "")
                category   = item.findtext(f"{NS}PrimaryCategory/{NS}CategoryName", "")
                condition  = item.findtext(f"{NS}ConditionDisplayName", "")
                listing_url = item.findtext(f"{NS}ListingDetails/{NS}ViewItemURL", "") or f"https://www.ebay.com/itm/{item_id}"
                qty        = trans.findtext(f"{NS}QuantityPurchased", "1")
                sale_price = trans.findtext(f"{NS}TransactionPrice", "0") or trans.findtext(f"{NS}TransactionPrice/{NS}value", "0")
                sold_date  = trans.findtext(f"{NS}CreatedDate", "") or paid or created
                feedback_left = trans.findtext(f"{NS}FeedbackLeft/{NS}CommentType", "")
                trans_id   = trans.findtext(f"{NS}TransactionID", "")
                try:
                    price_f = float(sale_price)
                except (TypeError, ValueError):
                    price_f = 0.0

                # Composite unique key — order can have multiple line items
                uniq = f"{order_id}:{trans_id}" if trans_id else f"{order_id}:{item_id}"
                fresh.append({
                    "uniq":        uniq,
                    "order_id":    order_id,
                    "item_id":     item_id,
                    "title":       title,
                    "pic":         "",
                    "url":         listing_url,
                    "category":    category,
                    "condition":   condition,
                    "quantity":    qty,
                    "sale_price":  price_f,
                    "sold_date":   sold_date,
                    "buyer":       _redact_buyer(buyer),
                    "ship_cost":   ship_cost,
                    "order_total": order_total,
                    "status":      status,
                    "feedback":    feedback_left,
                })

        pr = root.find(f".//{NS}PaginationResult")
        total_pages = int(pr.findtext(f"{NS}TotalNumberOfPages", "1")) if pr is not None else 1
        if page >= total_pages:
            break
        page += 1

    print(f"  Fetched {len(fresh)} sales from eBay (last {days_back} days)")

    # Merge with persistent history (dedupe by uniq key)
    history = _load_sold_history()
    by_uniq = {h.get("uniq", ""): h for h in history if h.get("uniq")}
    new_count = 0
    for s in fresh:
        if s["uniq"] not in by_uniq:
            new_count += 1
        by_uniq[s["uniq"]] = s  # always overwrite with latest data
    merged = sorted(by_uniq.values(), key=lambda x: x.get("sold_date") or "", reverse=True)

    # Image enrichment for items missing pics (Browse API per-item)
    missing_pics = [m for m in merged if not m.get("pic") and m.get("item_id")]
    if missing_pics:
        try:
            _enrich_sold_with_images(missing_pics, cfg)
        except Exception as exc:
            print(f"  Image enrichment skipped: {exc}")

    _save_sold_history(merged)
    print(f"  Sold history: {len(merged)} total ({new_count} new this run, persisted to {SOLD_HISTORY_FILE.name})")
    return merged


def _enrich_sold_with_images(sold: list[dict], cfg: dict) -> None:
    """Attach a pic URL per sold item via the Browse API (uses user OAuth)."""
    token = get_access_token(cfg)
    base = "https://api.ebay.com/buy/browse/v1/item/get_item_by_legacy_id"
    headers = {"Authorization": f"Bearer {token}", "X-EBAY-C-MARKETPLACE-ID": "EBAY_US"}
    fetched = 0
    for s in sold:
        if s.get("pic") or not s.get("item_id"):
            continue
        try:
            r = requests.get(base, params={"legacy_item_id": s["item_id"]}, headers=headers, timeout=10)
            if r.status_code == 200:
                d = r.json()
                pic = (d.get("image") or {}).get("imageUrl") or ""
                if not pic:
                    addl = d.get("additionalImages") or []
                    if addl:
                        pic = addl[0].get("imageUrl", "")
                if pic:
                    s["pic"] = pic
                    fetched += 1
        except Exception:
            continue
    if fetched:
        print(f"  Image enrichment: pulled {fetched} thumbnails from Browse API")


# ---------------------------------------------------------------------------
# Fetch seller profile (Trading API GetUser) — for trust panel
# ---------------------------------------------------------------------------

def fetch_seller_profile(token: str) -> dict:
    xml_body = f"""<?xml version="1.0" encoding="utf-8"?>
<GetUserRequest xmlns="urn:ebay:apis:eBLBaseComponents">
  <RequesterCredentials><eBayAuthToken>{token}</eBayAuthToken></RequesterCredentials>
  <DetailLevel>ReturnAll</DetailLevel>
</GetUserRequest>"""
    headers = {
        "X-EBAY-API-SITEID":              "0",
        "X-EBAY-API-COMPATIBILITY-LEVEL": "967",
        "X-EBAY-API-CALL-NAME":           "GetUser",
        "Content-Type":                   "text/xml",
    }
    try:
        resp = requests.post("https://api.ebay.com/ws/api.dll", data=xml_body, headers=headers, timeout=15)
        resp.raise_for_status()
    except Exception as exc:
        print(f"  Seller profile fetch failed: {exc}")
        return {}

    import xml.etree.ElementTree as _ET
    root = _ET.fromstring(resp.text)
    NS = "{urn:ebay:apis:eBLBaseComponents}"

    def t(path):
        n = root.find(f".//{NS}{path}".replace(NS + "/", NS))
        return n.text if n is not None and n.text else ""

    profile = {
        "user_id":             root.findtext(f".//{NS}UserID", ""),
        "feedback_score":      root.findtext(f".//{NS}FeedbackScore", "0"),
        "positive_pct":        root.findtext(f".//{NS}PositiveFeedbackPercent", "0"),
        "registration_date":   root.findtext(f".//{NS}RegistrationDate", ""),
        "feedback_unique":     root.findtext(f".//{NS}UniqueNegativeFeedbackCount", "0"),
        "site":                root.findtext(f".//{NS}Site", "US"),
        "seller_business_type": root.findtext(f".//{NS}SellerBusinessType", ""),
        "store_url":           root.findtext(f".//{NS}SellerInfo/{NS}StoreURL", ""),
        "store_name":          root.findtext(f".//{NS}SellerInfo/{NS}StoreName", ""),
    }

    # Compute member_since like "Jan 2018"
    try:
        from datetime import datetime as _dt
        reg = _dt.fromisoformat(profile["registration_date"].replace("Z", "+00:00"))
        profile["member_since"] = reg.strftime("%b %Y")
        profile["member_years"] = max(0, (datetime.now(timezone.utc) - reg).days // 365)
    except Exception:
        profile["member_since"] = ""
        profile["member_years"] = 0

    return profile


# ---------------------------------------------------------------------------
# Deal hunter — find listings priced well below the median for a given query
# ---------------------------------------------------------------------------
DEAL_QUERIES_FILE = Path(__file__).parent / "deal_queries.json"


def _required_grade_from_query(q: str):
    """If the query implies a grade (e.g. 'psa 10'), return (label, must_match_re, exclude_re).
    Otherwise None. Used to reject results that don't actually meet the grade requirement."""
    ql = q.lower()
    if _re.search(r"\bpsa\s*10\b", ql):
        # Must literally say PSA 10 AND not contain another PSA grade like PSA 9, 8, 7…
        return ("PSA 10", r"\bPSA\s*10\b", r"\bPSA\s*[1-9](?!\d)\b")
    if _re.search(r"\bpsa\s*9\b", ql):
        return ("PSA 9", r"\bPSA\s*9\b(?!\.)", None)
    if _re.search(r"\bbgs\s*9\.?5\b", ql):
        return ("BGS 9.5", r"\bBGS\s*9\.5\b", None)
    if _re.search(r"\bbgs\s*10\b", ql):
        return ("BGS 10", r"\bBGS\s*10\b", None)
    if _re.search(r"\bsgc\s*10\b", ql):
        return ("SGC 10", r"\bSGC\s*10\b", None)
    return None


def _title_meets_grade(title: str, grade_req) -> bool:
    """Apply the grade requirement to a candidate title."""
    if not grade_req:
        return True
    label, must_re, exclude_re = grade_req
    if not _re.search(must_re, title, _re.IGNORECASE):
        return False
    if exclude_re and _re.search(exclude_re, title, _re.IGNORECASE):
        return False
    return True


def fetch_deals(cfg: dict) -> dict:
    """Scan watchlist queries on eBay Browse API. Flag items priced significantly
    below median asking price. Returns {threshold, queries: [{q, comps, median, ...,
    deals: [{title, price, discount_pct, url, ...}]}]}."""
    if not DEAL_QUERIES_FILE.exists():
        return {"queries": [], "threshold": 30, "total_deals": 0}
    try:
        cfg_deals = json.load(open(DEAL_QUERIES_FILE))
    except Exception as exc:
        print(f"  deal_queries.json invalid: {exc}")
        return {"queries": [], "threshold": 30, "total_deals": 0}

    queries = cfg_deals.get("queries", [])
    threshold_pct = float(cfg_deals.get("discount_threshold_pct", 30))
    min_comps = int(cfg_deals.get("min_comps", 5))

    # Use app token (client_credentials) — no user OAuth scopes needed for Browse search
    app_token = get_app_token(cfg)
    own_seller = cfg.get("seller_username", "") or "harpua2001"

    out_queries = []
    total_deals = 0
    for q_cfg in queries:
        q = q_cfg.get("q", "").strip()
        if not q:
            continue
        max_price = q_cfg.get("max_price")
        category  = q_cfg.get("category", "")
        url = "https://api.ebay.com/buy/browse/v1/item_summary/search"
        min_price = q_cfg.get("min_price")
        # Default min: $5 for queries that didn't set one (avoids the $0.99 penny-flip floor)
        if min_price is None:
            min_price = 5
        # Build price filter
        if max_price:
            price_range = f"{min_price}..{max_price}"
        else:
            price_range = f"{min_price}.."
        params = {
            "q":      q,
            "limit":  "100",
            # Include both auctions and Buy It Now — we'll badge each in the UI.
            "filter": f"buyingOptions:{{FIXED_PRICE|AUCTION}},itemLocationCountry:US,price:[{price_range}],priceCurrency:USD",
            # No sort — default best-match returns a representative price spread.
        }
        headers = {
            "Authorization": f"Bearer {app_token}",
            "X-EBAY-C-MARKETPLACE-ID": "EBAY_US",
        }
        try:
            r = requests.get(url, params=params, headers=headers, timeout=15)
            r.raise_for_status()
            data = r.json()
        except Exception as exc:
            print(f"  Browse API failed for '{q}': {exc}")
            continue

        items = data.get("itemSummaries", []) or []
        # If the query specifies a grade (e.g. "psa 10"), require the title to literally
        # contain that grade. eBay's keyword search is fuzzy — without this filter,
        # "wolverine psa 10" returns PSA 9, ungraded, etc. wherever "10" appears.
        grade_req = _required_grade_from_query(q)
        # Filter: drop our own listings, items without an image, and obvious noise
        clean = []
        rejected_for_grade = 0
        for it in items:
            seller_name = (it.get("seller") or {}).get("username", "").lower()
            if seller_name == own_seller.lower():
                continue
            price = ((it.get("price") or {}).get("value") or "0")
            try:
                price_f = float(price)
            except (TypeError, ValueError):
                continue
            if price_f <= 0:
                continue
            title_text = it.get("title", "") or ""
            if grade_req and not _title_meets_grade(title_text, grade_req):
                rejected_for_grade += 1
                continue
            img = (it.get("image") or {}).get("imageUrl", "")
            options = it.get("buyingOptions") or []
            if "AUCTION" in options and "FIXED_PRICE" not in options:
                listing_type = "Auction"
            elif "FIXED_PRICE" in options and "AUCTION" in options:
                listing_type = "BIN + Auction"
            elif "BEST_OFFER" in options or any("OFFER" in o for o in options):
                listing_type = "BIN + Offer"
            elif "FIXED_PRICE" in options:
                listing_type = "BIN"
            else:
                listing_type = "BIN"
            # For auctions, end time is informative
            end_time = it.get("itemEndDate", "")
            clean.append({
                "item_id":      it.get("itemId", "") or it.get("legacyItemId", ""),
                "legacy_id":    it.get("legacyItemId", "") or "",
                "title":        it.get("title", ""),
                "price":        price_f,
                "image":        img,
                "condition":    it.get("condition", "") or "Used",
                "seller":       seller_name,
                "feedback":     ((it.get("seller") or {}).get("feedbackPercentage") or "") + "%",
                "url":          it.get("itemWebUrl", ""),
                "listing_type": listing_type,
                "end_time":     end_time,
            })

        if len(clean) < min_comps:
            out_queries.append({"q": q, "category": category, "comps": len(clean), "median": 0, "min": 0, "max": 0, "deals": [], "skipped_reason": f"insufficient comps ({len(clean)}<{min_comps})"})
            continue

        prices = sorted([c["price"] for c in clean])
        median = prices[len(prices) // 2]
        threshold_price = median * (1 - threshold_pct / 100.0)
        deals = []
        for c in clean:
            if c["price"] <= threshold_price:
                discount_pct = round((1 - c["price"] / median) * 100, 1)
                deals.append({**c, "median": median, "discount_pct": discount_pct})
        # Sort deals by discount_pct desc (best deals first)
        deals.sort(key=lambda d: -d["discount_pct"])
        out_queries.append({
            "q":       q,
            "category": category,
            "comps":   len(clean),
            "median":  round(median, 2),
            "min":     round(prices[0], 2),
            "max":     round(prices[-1], 2),
            "deals":   deals,
        })
        total_deals += len(deals)

    print(f"  Found {total_deals} deals across {len(out_queries)} queries")
    return {
        "queries":      out_queries,
        "threshold":    threshold_pct,
        "min_comps":    min_comps,
        "total_deals":  total_deals,
    }


def build_deals_page(deals_data: dict) -> Path:
    """Render the deal hunter page from fetch_deals output."""
    queries     = deals_data.get("queries", [])
    threshold   = deals_data.get("threshold", 30)
    total_deals = deals_data.get("total_deals", 0)

    # Flatten all deals across queries, sort by discount %
    all_deals = []
    for q in queries:
        for d in q.get("deals", []):
            all_deals.append({**d, "from_query": q["q"], "from_category": q.get("category", "")})
    all_deals.sort(key=lambda d: -d["discount_pct"])

    best_deal_pct = all_deals[0]["discount_pct"] if all_deals else 0
    cheapest = min((d["price"] for d in all_deals), default=0)
    total_savings = sum(d["median"] - d["price"] for d in all_deals)

    # Compute filter ranges from full deal set (before slicing)
    if all_deals:
        prices_all   = [d["price"] for d in all_deals]
        discounts    = [d["discount_pct"] for d in all_deals]
        savings_all  = [d["median"] - d["price"] for d in all_deals]
        f_price_min  = int(min(prices_all) // 1)
        f_price_max  = int(max(prices_all) + 1)
        f_disc_min   = int(min(discounts) // 1)
        f_disc_max   = int(max(discounts) + 1)
    else:
        f_price_min = f_price_max = f_disc_min = f_disc_max = 0

    # Derive categories present in deals for the dropdown
    deal_cats = sorted({d.get("from_category", "") for d in all_deals if d.get("from_category")})
    cat_options = '<option value="All">All categories</option>' + "".join(f'<option value="{c}">{c}</option>' for c in deal_cats)

    # Cards
    cards = []
    for d in all_deals[:200]:  # cap at 200 so the page stays fast
        img = (
            f'<img src="{d["image"]}" alt="" loading="lazy">' if d["image"]
            else '<div style="display:flex;align-items:center;justify-content:center;height:100%;color:var(--text-dim);font-size:11px;">No image</div>'
        )
        # Bigger discount → hotter color
        if d["discount_pct"] >= 50:
            tier = '<span class="badge badge-danger">🔥 HOT</span>'
        elif d["discount_pct"] >= 40:
            tier = '<span class="badge badge-warning">DEAL</span>'
        else:
            tier = '<span class="badge badge-success">VALUE</span>'

        cat_tag = f'<span class="tag tag-gold">{d["from_category"]}</span>' if d.get("from_category") else ""
        # Listing-type badge — colored differently for Auction (time-sensitive)
        ltype = d.get("listing_type", "BIN")
        if "Auction" in ltype:
            type_badge = f'<span class="tag tag-warn">⏱ {ltype}</span>'
        elif "Offer" in ltype:
            type_badge = f'<span class="tag tag-gold">{ltype}</span>'
        else:
            type_badge = f'<span class="tag">{ltype}</span>'
        # Auction end time hint
        end_hint = ""
        if d.get("end_time") and "Auction" in ltype:
            try:
                from datetime import datetime as _dt
                end_dt = _dt.fromisoformat(d["end_time"].replace("Z", "+00:00"))
                end_hint = f' <span class="deal-end">ends {end_dt.strftime("%b %-d %-I:%M%p UTC")}</span>'
            except Exception:
                pass
        # Sale price label: "current bid" for auctions, "asking" for BIN
        price_label = "current bid" if "Auction" in ltype and "BIN" not in ltype else "asking"
        # Simplified listing-type token for filter dropdown
        if "Auction" in ltype and "BIN" not in ltype:
            type_token = "Auction"
        elif "Offer" in ltype:
            type_token = "Best Offer"
        else:
            type_token = "BIN"
        savings = d["median"] - d["price"]
        cards.append(f'''
      <article class="deal-card"
        data-price="{d['price']:.2f}"
        data-discount="{d['discount_pct']:.1f}"
        data-savings="{savings:.2f}"
        data-cat="{d.get('from_category','')}"
        data-type="{type_token}"
        data-title="{(d.get('title','') or '').lower().replace(chr(34),'')}">
        <div class="deal-thumb">{img}<div class="deal-discount">-{d['discount_pct']:.0f}%</div></div>
        <div class="deal-body">
          <div class="deal-meta-row">
            {tier}
            {type_badge}
            {cat_tag}
            <span class="tag">{d['condition']}</span>
          </div>
          <a href="{d['url']}" target="_blank" rel="noopener" class="deal-title">{d['title'][:120]}</a>
          <div class="deal-meta-row" style="margin-top:6px;">
            <span class="deal-from">Seen via <em>“{d['from_query']}”</em>{end_hint}</span>
            <span class="deal-feedback" title="Seller">{d['seller']} {d['feedback']}</span>
          </div>
        </div>
        <div class="deal-price-block">
          <div class="deal-price">${d['price']:.2f}</div>
          <div class="deal-median">{price_label} · median ${d['median']:.2f}</div>
          <a href="{d['url']}" target="_blank" rel="noopener" class="btn btn-gold" style="padding:8px 14px;font-size:11px;margin-top:8px;">Check on eBay →</a>
        </div>
      </article>''')

    if not cards:
        cards_html = '<div class="panel" style="text-align:center;padding:48px;color:var(--text-muted);">No deals matched the threshold today. Lower the bar in <code>deal_queries.json</code> (increase <code>discount_threshold_pct</code>) or add new queries.</div>'
    else:
        cards_html = "\n".join(cards)

    # Query summary table
    summary_rows = []
    for q in queries:
        d_count = len(q.get("deals", []))
        if q.get("skipped_reason"):
            summary_rows.append(f'<tr><td>{q["q"]}</td><td colspan="4" style="color:var(--text-muted);font-style:italic;">{q["skipped_reason"]}</td></tr>')
        else:
            d_marker = f'<b style="color:var(--gold);">{d_count}</b>' if d_count else '0'
            summary_rows.append(f'<tr><td>{q["q"]}</td><td>{q["comps"]}</td><td>${q["min"]:.2f}</td><td>${q["median"]:.2f}</td><td>${q["max"]:.2f}</td><td>{d_marker}</td></tr>')
    summary_html = "\n".join(summary_rows) or '<tr><td colspan="6" style="text-align:center;color:var(--text-muted);">Add queries to <code>deal_queries.json</code>.</td></tr>'

    extra_css = """
    .deal-grid { display: grid; gap: 12px; margin-bottom: 28px; }
    .deal-card {
      display: grid;
      grid-template-columns: 108px 1fr auto;
      gap: 16px; align-items: stretch;
      background: var(--surface);
      border: 1px solid var(--border);
      border-left: 3px solid var(--gold);
      border-radius: var(--r-lg);
      padding: 14px 18px;
      transition: all var(--t-fast);
    }
    .deal-card:hover { transform: translateY(-1px); border-color: var(--border-mid); }
    .deal-thumb {
      position: relative;
      width: 108px; height: 108px;
      border-radius: var(--r-sm); overflow: hidden; background: var(--surface-3);
    }
    .deal-thumb img { width: 100%; height: 100%; object-fit: cover; }
    .deal-discount {
      position: absolute; top: 6px; right: 6px;
      background: linear-gradient(135deg, var(--gold), var(--gold-dim));
      color: var(--brand-fg);
      font-family: 'Bebas Neue', sans-serif;
      font-size: 16px; letter-spacing: .02em;
      padding: 3px 8px;
      border-radius: var(--r-sm);
      line-height: 1;
    }
    .deal-body { min-width: 0; }
    .deal-meta-row { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
    .deal-title { display: block; font-size: 14.5px; font-weight: 600; color: var(--text); line-height: 1.35; text-decoration: none; margin-top: 8px; }
    .deal-title:hover { color: var(--gold); }
    .deal-from { font-size: 11px; color: var(--text-muted); }
    .deal-from em { color: var(--gold); font-style: normal; font-weight: 600; }
    .deal-feedback { font-size: 11px; color: var(--text-dim); margin-left: auto; }
    .deal-price-block { text-align: right; flex-shrink: 0; align-self: center; }
    .deal-price {
      font-family: 'Bebas Neue', sans-serif;
      font-size: 30px; line-height: 1;
      color: var(--gold);
      letter-spacing: .02em;
    }
    .deal-median { font-size: 11px; color: var(--text-muted); text-decoration: line-through; margin-top: 4px; }
    .summary-table { width: 100%; }
    .summary-table th, .summary-table td { font-size: 12px; padding: 8px 10px; text-align: left; }
    .summary-table th:not(:first-child), .summary-table td:not(:first-child) { text-align: right; }
    @media (max-width: 580px) {
      .deal-card { grid-template-columns: 80px 1fr; padding: 12px; gap: 12px; }
      .deal-thumb { width: 80px; height: 80px; }
      .deal-price-block { grid-column: 1 / -1; text-align: left; }
      .deal-feedback { margin-left: 0; }
    }
    """

    body = f"""
    <div class="section-head">
      <div>
        <div class="eyebrow">Underpriced listings · &gt;{threshold:g}% below median</div>
        <h1 class="section-title">Deal <span class="accent">Hunter</span></h1>
        <div class="section-sub">Live scans of eBay watchlist queries from <code>deal_queries.json</code>. Flagged when current asking price is at least {threshold:g}% below the median price for the same query.</div>
      </div>
    </div>

    <div class="stat-grid">
      <div class="stat-card"><div class="num">{total_deals}</div><div class="lbl">Deals Right Now</div></div>
      <div class="stat-card"><div class="num">{best_deal_pct:.0f}<span style="font-size:24px;">%</span></div><div class="lbl">Best Discount</div></div>
      <div class="stat-card"><div class="num">${cheapest:,.0f}</div><div class="lbl">Cheapest Find</div></div>
      <div class="stat-card"><div class="num">${total_savings:,.0f}</div><div class="lbl">Potential Savings</div></div>
    </div>

    <div class="filter-bar">
      <div class="filter-row">
        <input type="search" id="deal-search" class="search-input" placeholder="Filter by keyword (player, set, brand)…" oninput="dealApply()" autocomplete="off">
        <select id="deal-cat" onchange="dealApply()" style="max-width:220px;">
          {cat_options}
        </select>
        <select id="deal-type" onchange="dealApply()" style="max-width:180px;">
          <option value="All">All listing types</option>
          <option value="BIN">Buy It Now</option>
          <option value="Auction">Auction</option>
          <option value="Best Offer">Best Offer</option>
        </select>
        <select id="deal-sort" onchange="dealApply()" style="max-width:200px;">
          <option value="discount-desc">Sort: Biggest % off</option>
          <option value="savings-desc">Sort: Biggest $ saved</option>
          <option value="price-asc">Sort: Price low→high</option>
          <option value="price-desc">Sort: Price high→low</option>
        </select>
      </div>
      <div class="filter-row">
        <div class="slider-wrap">
          <div class="slider-labels">
            <span>Price</span>
            <span><span class="slider-values" id="dp-lo">${f_price_min}</span> – <span class="slider-values" id="dp-hi">${f_price_max}</span></span>
          </div>
          <div id="deal-price-slider"></div>
        </div>
      </div>
      <div class="filter-row">
        <div class="slider-wrap">
          <div class="slider-labels">
            <span>Minimum discount</span>
            <span class="slider-values" id="dd-lo">{f_disc_min}%</span>
          </div>
          <div id="deal-disc-slider"></div>
        </div>
      </div>
    </div>

    <div id="deal-results-meta" style="font-size:12px;color:var(--text-muted);margin-bottom:14px;letter-spacing:.08em;text-transform:uppercase;font-weight:600;">
      Showing <span id="deal-visible-count">{len(cards)}</span> of {len(cards)} deals
    </div>

    <div class="deal-grid" id="deal-grid">
      {cards_html}
    </div>

    <div class="panel">
      <div class="panel-head">
        <div class="panel-title">Query coverage</div>
        <div class="panel-sub">{len(queries)} watch queries · min {deals_data.get("min_comps", 5)} comps required</div>
      </div>
      <table class="summary-table">
        <thead><tr><th>Query</th><th>Comps</th><th>Min</th><th>Median</th><th>Max</th><th>Deals</th></tr></thead>
        <tbody>{summary_html}</tbody>
      </table>
    </div>
    """
    # Filter JS — uses noUiSlider (already loaded in head)
    body += f"""
    <script>
      const DP_MIN = {f_price_min}, DP_MAX = {f_price_max};
      const DD_MIN = {f_disc_min}, DD_MAX = {f_disc_max};
      let dealPriceRange = [DP_MIN, DP_MAX];
      let dealDiscMin    = DD_MIN;
      // dealApply MUST be defined before slider creation — noUiSlider fires
      // an initial 'update' event during create() and we call dealApply from it.
      window.dealApply = function() {{
        const q    = (document.getElementById('deal-search').value || '').toLowerCase().trim();
        const cat  = document.getElementById('deal-cat').value;
        const type = document.getElementById('deal-type').value;
        const sort = document.getElementById('deal-sort').value;
        const grid = document.getElementById('deal-grid');
        const cards = Array.from(grid.querySelectorAll('.deal-card'));
        const [plo, phi] = dealPriceRange;
        let vis = 0;
        cards.forEach(c => {{
          const price = parseFloat(c.dataset.price);
          const disc  = parseFloat(c.dataset.discount);
          let ok = true;
          if (q && !(c.dataset.title || '').includes(q)) ok = false;
          if (ok && cat !== 'All' && c.dataset.cat !== cat) ok = false;
          if (ok && type !== 'All' && c.dataset.type !== type) ok = false;
          if (ok && (price < plo || price > phi)) ok = false;
          if (ok && disc < dealDiscMin) ok = false;
          c.style.display = ok ? '' : 'none';
          if (ok) vis++;
        }});
        document.getElementById('deal-visible-count').textContent = vis;
        // Sort visible
        const visCards = cards.filter(c => c.style.display !== 'none');
        const keyMap = {{
          'discount-desc': c => -parseFloat(c.dataset.discount),
          'savings-desc':  c => -parseFloat(c.dataset.savings),
          'price-asc':     c =>  parseFloat(c.dataset.price),
          'price-desc':    c => -parseFloat(c.dataset.price),
        }};
        const keyFn = keyMap[sort] || keyMap['discount-desc'];
        visCards.sort((a, b) => keyFn(a) - keyFn(b));
        visCards.forEach(c => grid.appendChild(c));
      }};

      // Now create the sliders — dealApply is already defined so initial update event works.
      if (typeof noUiSlider !== 'undefined' && DP_MAX > DP_MIN) {{
        const ps = document.getElementById('deal-price-slider');
        if (ps) {{
          noUiSlider.create(ps, {{
            start: [DP_MIN, DP_MAX], connect: true, step: 1,
            range: {{ min: DP_MIN, max: DP_MAX }},
          }});
          ps.noUiSlider.on('update', (vals) => {{
            const [lo, hi] = vals.map(v => Math.round(parseFloat(v)));
            dealPriceRange = [lo, hi];
            document.getElementById('dp-lo').textContent = '$' + lo;
            document.getElementById('dp-hi').textContent = '$' + hi;
            dealApply();
          }});
        }}
      }}
      if (typeof noUiSlider !== 'undefined' && DD_MAX > DD_MIN) {{
        const ds = document.getElementById('deal-disc-slider');
        if (ds) {{
          noUiSlider.create(ds, {{
            start: DD_MIN, step: 1,
            range: {{ min: DD_MIN, max: DD_MAX }},
          }});
          ds.noUiSlider.on('update', (v) => {{
            dealDiscMin = Math.round(parseFloat(Array.isArray(v) ? v[0] : v));
            document.getElementById('dd-lo').textContent = dealDiscMin + '%';
            dealApply();
          }});
        }}
      }}
    </script>"""
    out = OUTPUT_DIR / "deals.html"
    out.write_text(html_shell(f"Deal Hunter · {SELLER_NAME}", body, extra_head=f"<style>{extra_css}</style>", active_page="deals.html"), encoding="utf-8")
    print(f"  Deals page: {out}")
    return out


# ---------------------------------------------------------------------------
# Fetch listings via Trading API (works for legacy listings)
# ---------------------------------------------------------------------------

def fetch_listings(token: str, cfg: dict) -> list[dict]:
    xml_body = """<?xml version="1.0" encoding="utf-8"?>
<GetMyeBaySellingRequest xmlns="urn:ebay:apis:eBLBaseComponents">
  <RequesterCredentials><eBayAuthToken>{token}</eBayAuthToken></RequesterCredentials>
  <ActiveList>
    <Include>true</Include>
    <Pagination><EntriesPerPage>200</EntriesPerPage><PageNumber>1</PageNumber></Pagination>
  </ActiveList>
  <ErrorLanguage>en_US</ErrorLanguage>
  <WarningLevel>High</WarningLevel>
</GetMyeBaySellingRequest>""".format(token=token)

    headers = {
        "X-EBAY-API-SITEID":               "0",
        "X-EBAY-API-COMPATIBILITY-LEVEL":  "967",
        "X-EBAY-API-CALL-NAME":            "GetMyeBaySelling",
        "X-EBAY-API-APP-NAME":             cfg["client_id"],
        "X-EBAY-API-DEV-NAME":             cfg["dev_id"],
        "X-EBAY-API-CERT-NAME":            cfg["client_secret"],
        "Content-Type":                    "text/xml",
    }
    r = requests.post("https://api.ebay.com/ws/api.dll", headers=headers, data=xml_body.encode())
    if r.status_code != 200:
        print(f"  Trading API error: {r.status_code}")
        return []

    ns = {"e": "urn:ebay:apis:eBLBaseComponents"}
    root = ET.fromstring(r.text)
    items = []
    for item in root.findall(".//e:ActiveList/e:ItemArray/e:Item", ns):
        def t(tag):
            el = item.find(f"e:{tag}", ns)
            return (el.text or "").strip() if el is not None else ""

        pic = item.find("e:PictureDetails/e:GalleryURL", ns)
        price_el = item.find("e:SellingStatus/e:CurrentPrice", ns)
        view_url = item.find("e:ListingDetails/e:ViewItemURL", ns)

        item_id = t("ItemID")
        # Upgrade eBay thumbnail URL from s-l140 to s-l500 for sharp images
        raw_pic = pic.text.strip() if pic is not None else ""
        import re as _re
        sharp_pic = _re.sub(r's-l\d+\.jpg', 's-l500.jpg', raw_pic) if raw_pic else ""
        listing_type_raw = t("ListingType")
        # eBay ListingType values: FixedPriceItem, StoresFixedPrice → BIN
        # Chinese, Dutch → Auction. AdType → not a real listing.
        if listing_type_raw in ("FixedPriceItem", "StoresFixedPrice"):
            ltype = "BIN"
        elif listing_type_raw in ("Chinese", "Dutch"):
            ltype = "Auction"
        else:
            ltype = "BIN"  # default
        items.append({
            "item_id":      item_id,
            "title":        t("Title"),
            "price":        price_el.text.strip() if price_el is not None else "0",
            "pic":          sharp_pic,
            "url":          view_url.text.strip() if view_url is not None else f"https://www.ebay.com/itm/{item_id}",
            "category":     t("PrimaryCategory/CategoryName"),
            "condition":    t("ConditionDisplayName"),
            "quantity":     t("QuantityAvailable") or t("Quantity") or "1",
            "desc":         t("Description"),
            "listing_type": ltype,
        })

    print(f"  Fetched {len(items)} listings")
    return items


# ---------------------------------------------------------------------------
# Market price research via eBay Browse API
# ---------------------------------------------------------------------------

import statistics as _stats
import time as _time

def fetch_market_prices(listings: list[dict], cfg: dict) -> dict:
    """
    For each listing, search eBay Browse API for active comps and return a
    dict keyed by item_id with:
      { "market_median": float, "market_min": float, "market_max": float,
        "comp_count": int, "gap_pct": float, "flag": "OK"|"UNDERPRICED"|"OVERPRICED"|"NO_COMPS" }

    Uses the listing title (trimmed to key terms) as the search query.
    Rate-limited to ~1 req/sec to stay within eBay's limits.
    """
    app_token = get_app_token(cfg)
    results   = {}

    print(f"  Fetching market comps for {len(listings)} listings...")
    for i, l in enumerate(listings):
        item_id   = l["item_id"]
        our_price = float(l["price"]) if l["price"] else 0.0
        query     = _market_query(l["title"])

        try:
            r = requests.get(
                "https://api.ebay.com/buy/browse/v1/item_summary/search",
                headers={
                    "Authorization":          f"Bearer {app_token}",
                    "X-EBAY-C-MARKETPLACE-ID": "EBAY_US",
                },
                params={
                    "q":      query,
                    "limit":  10,
                    "sort":   "price",
                    "filter": "buyingOptions:{FIXED_PRICE}",
                },
                timeout=10,
            )
            if r.status_code == 401:
                # Token expired mid-run — refresh once
                app_token = get_app_token(cfg)
                r = requests.get(
                    "https://api.ebay.com/buy/browse/v1/item_summary/search",
                    headers={"Authorization": f"Bearer {app_token}",
                             "X-EBAY-C-MARKETPLACE-ID": "EBAY_US"},
                    params={"q": query, "limit": 10, "sort": "price",
                            "filter": "buyingOptions:{FIXED_PRICE}"},
                    timeout=10,
                )

            prices = []
            for it in r.json().get("itemSummaries", []):
                try:
                    p = float(it["price"]["value"])
                    if p > 0:
                        prices.append(p)
                except (KeyError, ValueError):
                    pass

            if not prices:
                results[item_id] = {"flag": "NO_COMPS", "comp_count": 0,
                                    "market_median": None, "market_min": None,
                                    "market_max": None, "gap_pct": None}
            else:
                med = _stats.median(prices)
                gap = ((our_price - med) / med * 100) if med else 0
                if gap < -15:
                    flag = "UNDERPRICED"
                elif gap > 20:
                    flag = "OVERPRICED"
                else:
                    flag = "OK"
                results[item_id] = {
                    "flag":          flag,
                    "comp_count":    len(prices),
                    "market_median": round(med, 2),
                    "market_min":    round(min(prices), 2),
                    "market_max":    round(max(prices), 2),
                    "gap_pct":       round(gap, 1),
                }

        except Exception as exc:
            results[item_id] = {"flag": "NO_COMPS", "comp_count": 0,
                                "market_median": None, "market_min": None,
                                "market_max": None, "gap_pct": None,
                                "error": str(exc)}

        # Polite rate limit — Browse API allows ~5k calls/day, no hard per-second limit
        # but a short sleep avoids bursting
        if i % 10 == 9:
            _time.sleep(1)

    underpriced = sum(1 for v in results.values() if v["flag"] == "UNDERPRICED")
    overpriced  = sum(1 for v in results.values() if v["flag"] == "OVERPRICED")
    print(f"  Market comps done — {underpriced} underpriced, {overpriced} overpriced")
    return results


def _market_query(title: str) -> str:
    """
    Trim a listing title down to the most distinctive search terms.
    Removes filler words that hurt precision (lot, cards, including, etc.)
    """
    import re as _re
    # Drop common filler that hurts search precision
    stop = r"\b(lot|cards?|including|rookie|card|x different|no duplicates|"  \
           r"graded|raw|nm|mint|psa|bgs|sgc|authenticated|certified|"         \
           r"free shipping|combined shipping)\b"
    q = _re.sub(stop, " ", title, flags=_re.IGNORECASE)
    q = _re.sub(r"\s{2,}", " ", q).strip()
    # Cap at 100 chars for the API
    return q[:100]


# ---------------------------------------------------------------------------
# Shared HTML shell — Dark sports-card luxe design system
# ---------------------------------------------------------------------------

LAMBDA_BASE = "https://jw0hur2091.execute-api.us-east-1.amazonaws.com/ebay"

_BASE_CSS = """
:root {
  /* Default: Dark Luxe (gold on black) */
  --bg:          #0a0a0a;
  --surface:     #141414;
  --surface-2:   #1a1a1a;
  --surface-3:   #232323;
  --border:      rgba(212,175,55,0.10);
  --border-mid:  rgba(212,175,55,0.22);
  --border-hi:   rgba(212,175,55,0.45);
  --gold:        #d4af37;
  --gold-bright: #f4ce5d;
  --gold-dim:    #8a7521;
  --text:        #f1efe9;
  --text-muted:  #9a9388;
  --text-dim:    #5d574c;
  --success:     #7fc77a;
  --warning:     #e0b54a;
  --danger:      #e07b6f;
  --link:        #6cb0ff;
  --shadow-lg:   0 24px 60px -12px rgba(0,0,0,.85);
  --shadow-card: 0 2px 8px rgba(0,0,0,.45), 0 0 0 1px var(--border) inset;
  --glow-gold:   0 0 0 1px var(--border-hi) inset, 0 8px 32px -8px rgba(212,175,55,.25);
  --bg-radial-1: rgba(212,175,55,.08);
  --bg-radial-2: rgba(212,175,55,.05);
  --hero-tag-fg: #0a0a0a;       /* tag text on gold gradient */
  --brand-fg:    #0a0a0a;       /* brand mark "H" on gold */
  --r-sm: 6px;
  --r-md: 10px;
  --r-lg: 16px;
  --r-xl: 22px;
  --t-fast: 160ms cubic-bezier(.4,0,.2,1);
  --t-base: 280ms cubic-bezier(.4,0,.2,1);
}

/* ============ ALT THEME: CREAM & NAVY ============ */
[data-theme="cream"] {
  --bg:          #f5f0e8;       /* warm cream */
  --surface:     #e8e0d0;       /* light tan card */
  --surface-2:   #ede5d6;       /* slightly lighter raised */
  --surface-3:   #d8ccba;       /* darker for inputs / chips */
  --border:      rgba(13,31,60,0.10);
  --border-mid:  rgba(13,31,60,0.22);
  --border-hi:   rgba(13,31,60,0.45);
  --gold:        #c05a1a;       /* burnt orange (price/accent) */
  --gold-bright: #e57228;
  --gold-dim:    #8a3e10;
  --text:        #0d1f3c;       /* deep navy */
  --text-muted:  #5a6a7a;       /* steel gray */
  --text-dim:    #8a98a8;
  --success:     #2f7d4a;
  --warning:     #b8860b;
  --danger:      #b54a3e;
  --link:        #0d1f3c;
  --shadow-lg:   0 18px 48px -12px rgba(13,31,60,.18);
  --shadow-card: 0 2px 10px rgba(13,31,60,.08), 0 0 0 1px var(--border) inset;
  --glow-gold:   0 0 0 1px var(--border-hi) inset, 0 6px 22px -8px rgba(192,90,26,.22);
  --bg-radial-1: rgba(192,90,26,.10);
  --bg-radial-2: rgba(13,31,60,.06);
  --hero-tag-fg: #f5f0e8;       /* cream text on orange tag */
  --brand-fg:    #f5f0e8;       /* cream "H" on orange brand mark */
}

/* Cream-theme button overrides — primary becomes navy/cream, ghost+outline use navy */
[data-theme="cream"] .btn-gold,
[data-theme="cream"] .btn-refresh {
  background: var(--text);
  color: var(--bg);
}
[data-theme="cream"] .btn-gold:hover,
[data-theme="cream"] .btn-refresh:hover {
  filter: brightness(1.15);
  color: var(--bg);
}
[data-theme="cream"] .btn-ghost,
[data-theme="cream"] .btn-outline {
  background: transparent;
  color: var(--text);
  border: 1px solid var(--text);
}
[data-theme="cream"] .btn-ghost:hover,
[data-theme="cream"] .btn-outline:hover {
  background: var(--text);
  color: var(--bg);
  border-color: var(--text);
}
[data-theme="cream"] .btn-install {
  border-color: var(--text);
  color: var(--text);
}
[data-theme="cream"] .btn-install:hover {
  background: var(--text);
  color: var(--bg);
}

/* Cream-theme tag/badge — matches user spec exactly */
[data-theme="cream"] .tag {
  background: #e8d8c0;
  color: #8a3e10;
  border: 1px solid #c05a1a;
}
[data-theme="cream"] .tag-gold {
  background: #c05a1a;
  color: #f5f0e8;
  border-color: #8a3e10;
}
[data-theme="cream"] .tag-danger,
[data-theme="cream"] .badge-danger {
  background: rgba(181,74,62,.14); color: #8a2c20; border-color: rgba(181,74,62,.4);
}
[data-theme="cream"] .tag-warn,
[data-theme="cream"] .badge-warning {
  background: rgba(184,134,11,.14); color: #7a5a07; border-color: rgba(184,134,11,.4);
}
[data-theme="cream"] .tag-success,
[data-theme="cream"] .badge-success {
  background: rgba(47,125,74,.14); color: #1f5230; border-color: rgba(47,125,74,.4);
}
[data-theme="cream"] .badge-gold {
  background: rgba(192,90,26,.14); color: #8a3e10; border-color: rgba(192,90,26,.45);
}

/* Header glass effect needs different alpha on light */
[data-theme="cream"] .app-header {
  background: linear-gradient(180deg, rgba(245,240,232,.95), rgba(245,240,232,.85));
}
[data-theme="cream"] .nav-links a.active {
  background: rgba(192,90,26,.10);
  color: var(--gold);
}

/* Brand mark uses orange gradient w/ cream H letter */
[data-theme="cream"] .brand-mark { color: var(--brand-fg); }

/* Stat / hero glow tints — orange instead of gold halo */
[data-theme="cream"] .stat-card .num,
[data-theme="cream"] .hero-price,
[data-theme="cream"] .product-price {
  text-shadow: 0 0 22px rgba(192,90,26,.18);
}

/* Drawer + selection in cream */
[data-theme="cream"] ::selection { background: var(--gold); color: var(--bg); }
[data-theme="cream"] .drawer { background: var(--surface); }
[data-theme="cream"] .drawer a { color: var(--text); }
[data-theme="cream"] .drawer a:hover, [data-theme="cream"] .drawer a.active {
  background: var(--surface-2); color: var(--gold); border-color: var(--border-mid);
}

/* Filter chip "active" state */
[data-theme="cream"] .chip.active {
  background: var(--text);
  color: var(--bg);
  border-color: var(--text);
}

/* Hero tag (Featured #1) keeps orange-gradient look but with cream text */
[data-theme="cream"] .hero-tag { color: var(--hero-tag-fg); }

/* Search-input magnifier icon needs darker stroke for cream bg */
[data-theme="cream"] .search-input {
  background: var(--surface-2) url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' fill='none' stroke='%235a6a7a' stroke-width='2' viewBox='0 0 24 24'><circle cx='11' cy='11' r='7'/><path d='m20 20-3-3'/></svg>") no-repeat 14px center;
  background-size: 18px;
}

/* Charts: Chart.js uses a hardcoded gray for grids/labels — re-tint via CSS for cream */
[data-theme="cream"] .chart-panel { color: var(--text); }

/* ============ MIDNIGHT LUXURY (Dark Black & Gold, refined) ============ */
[data-theme="midnight"] {
  --bg:          #0f0f0f;
  --surface:     #1c1c1c;
  --surface-2:   #232323;
  --surface-3:   #2a2a2a;
  --border:      rgba(212,168,50,0.10);
  --border-mid:  rgba(212,168,50,0.22);
  --border-hi:   rgba(212,168,50,0.45);
  --gold:        #d4a832;
  --gold-bright: #e5c050;
  --gold-dim:    #b8922a;
  --text:        #f0ead8;
  --text-muted:  #6a5e3a;
  --text-dim:    #4a4028;
  --link:        #d4a832;
  --shadow-lg:   0 24px 60px -12px rgba(0,0,0,.85);
  --shadow-card: 0 2px 8px rgba(0,0,0,.45), 0 0 0 1px var(--border) inset;
  --glow-gold:   0 0 0 1px var(--border-hi) inset, 0 8px 32px -8px rgba(212,168,50,.25);
  --bg-radial-1: rgba(212,168,50,.08);
  --bg-radial-2: rgba(212,168,50,.05);
  --hero-tag-fg: #0f0f0f;
  --brand-fg:    #0f0f0f;
}
[data-theme="midnight"] .tag { background: #1e1a0e; color: #b8922a; border: 1px solid #b8922a; }

/* ============ CLEAN WHITE & COBALT ============ */
[data-theme="cobalt"] {
  --bg:          #ffffff;
  --surface:     #f2f5fc;
  --surface-2:   #f7f9fd;
  --surface-3:   #e3eafa;
  --border:      rgba(13,26,46,0.08);
  --border-mid:  rgba(13,26,46,0.18);
  --border-hi:   rgba(26,79,214,0.45);
  --gold:        #1a4fd6;
  --gold-bright: #3a6fef;
  --gold-dim:    #1238a0;
  --text:        #0d1a2e;
  --text-muted:  #7a8fab;
  --text-dim:    #a8b6cb;
  --link:        #1a4fd6;
  --shadow-lg:   0 18px 48px -12px rgba(13,26,46,.15);
  --shadow-card: 0 2px 10px rgba(13,26,46,.06), 0 0 0 1px var(--border) inset;
  --glow-gold:   0 0 0 1px var(--border-hi) inset, 0 6px 22px -8px rgba(26,79,214,.22);
  --bg-radial-1: rgba(26,79,214,.06);
  --bg-radial-2: rgba(26,79,214,.04);
  --hero-tag-fg: #ffffff;
  --brand-fg:    #ffffff;
}
[data-theme="cobalt"] .tag { background: #eaf0fd; color: #1238a0; border: 1px solid #1a4fd6; }
[data-theme="cobalt"] ::selection { background: var(--gold); color: var(--bg); }
[data-theme="cobalt"] .app-header { background: linear-gradient(180deg, rgba(255,255,255,.95), rgba(255,255,255,.85)); }
[data-theme="cobalt"] .search-input {
  background: var(--surface-2) url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' fill='none' stroke='%237a8fab' stroke-width='2' viewBox='0 0 24 24'><circle cx='11' cy='11' r='7'/><path d='m20 20-3-3'/></svg>") no-repeat 14px center;
  background-size: 18px;
}

/* ============ FOREST & PARCHMENT ============ */
[data-theme="forest"] {
  --bg:          #f4f0e6;
  --surface:     #e8e2d0;
  --surface-2:   #ede8d8;
  --surface-3:   #d8cfb8;
  --border:      rgba(26,46,26,0.10);
  --border-mid:  rgba(26,46,26,0.22);
  --border-hi:   rgba(26,46,26,0.45);
  --gold:        #3a6b2a;
  --gold-bright: #4f8a3a;
  --gold-dim:    #234018;
  --text:        #1a2e1a;
  --text-muted:  #6a7a5a;
  --text-dim:    #8a9778;
  --link:        #3a6b2a;
  --shadow-lg:   0 18px 48px -12px rgba(26,46,26,.18);
  --shadow-card: 0 2px 10px rgba(26,46,26,.08), 0 0 0 1px var(--border) inset;
  --glow-gold:   0 0 0 1px var(--border-hi) inset, 0 6px 22px -8px rgba(58,107,42,.22);
  --bg-radial-1: rgba(58,107,42,.08);
  --bg-radial-2: rgba(26,46,26,.05);
  --hero-tag-fg: #f4f0e6;
  --brand-fg:    #f4f0e6;
}
[data-theme="forest"] .tag { background: #dde8d5; color: #234018; border: 1px solid #3a6b2a; }
[data-theme="forest"] .btn-gold,
[data-theme="forest"] .btn-refresh { background: var(--text); color: var(--bg); }
[data-theme="forest"] .btn-gold:hover,
[data-theme="forest"] .btn-refresh:hover { filter: brightness(1.15); color: var(--bg); }
[data-theme="forest"] .btn-ghost,
[data-theme="forest"] .btn-outline { background: transparent; color: var(--gold); border: 1px solid var(--gold); }
[data-theme="forest"] .btn-ghost:hover,
[data-theme="forest"] .btn-outline:hover { background: var(--gold); color: var(--bg); }
[data-theme="forest"] ::selection { background: var(--gold); color: var(--bg); }
[data-theme="forest"] .app-header { background: linear-gradient(180deg, rgba(244,240,230,.95), rgba(244,240,230,.85)); }
[data-theme="forest"] .search-input {
  background: var(--surface-2) url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' fill='none' stroke='%236a7a5a' stroke-width='2' viewBox='0 0 24 24'><circle cx='11' cy='11' r='7'/><path d='m20 20-3-3'/></svg>") no-repeat 14px center;
  background-size: 18px;
}

/* ============ CRIMSON & CHARCOAL ============ */
[data-theme="crimson"] {
  --bg:          #1c1c1e;
  --surface:     #2a2a2c;
  --surface-2:   #313134;
  --surface-3:   #383838;
  --border:      rgba(192,40,42,0.10);
  --border-mid:  rgba(192,40,42,0.25);
  --border-hi:   rgba(192,40,42,0.55);
  --gold:        #c0282a;
  --gold-bright: #e05050;
  --gold-dim:    #8a1a1c;
  --text:        #f5f5f5;
  --text-muted:  #8a8a8a;
  --text-dim:    #5a5a5a;
  --link:        #e05050;
  --shadow-lg:   0 24px 60px -12px rgba(0,0,0,.85);
  --shadow-card: 0 2px 8px rgba(0,0,0,.5), 0 0 0 1px var(--border) inset;
  --glow-gold:   0 0 0 1px var(--border-hi) inset, 0 8px 32px -8px rgba(192,40,42,.30);
  --bg-radial-1: rgba(192,40,42,.10);
  --bg-radial-2: rgba(192,40,42,.05);
  --hero-tag-fg: #ffffff;
  --brand-fg:    #ffffff;
}
[data-theme="crimson"] .tag { background: #2e1515; color: #e05050; border: 1px solid #c0282a; }

/* ============ SOFT LAVENDER & PLUM ============ */
[data-theme="lavender"] {
  --bg:          #f5f3fb;
  --surface:     #ede9f7;
  --surface-2:   #f0ecf8;
  --surface-3:   #ddd5ee;
  --border:      rgba(42,26,74,0.10);
  --border-mid:  rgba(42,26,74,0.22);
  --border-hi:   rgba(107,63,160,0.45);
  --gold:        #6b3fa0;
  --gold-bright: #8a5cc0;
  --gold-dim:    #4a1f80;
  --text:        #2a1a4a;
  --text-muted:  #7a6a9a;
  --text-dim:    #a59ab8;
  --link:        #6b3fa0;
  --shadow-lg:   0 18px 48px -12px rgba(42,26,74,.18);
  --shadow-card: 0 2px 10px rgba(42,26,74,.08), 0 0 0 1px var(--border) inset;
  --glow-gold:   0 0 0 1px var(--border-hi) inset, 0 6px 22px -8px rgba(107,63,160,.22);
  --bg-radial-1: rgba(107,63,160,.08);
  --bg-radial-2: rgba(42,26,74,.05);
  --hero-tag-fg: #f5f3fb;
  --brand-fg:    #f5f3fb;
}
[data-theme="lavender"] .tag { background: #e2d8f5; color: #4a1f80; border: 1px solid #6b3fa0; }
[data-theme="lavender"] .btn-gold,
[data-theme="lavender"] .btn-refresh { background: var(--text); color: var(--bg); }
[data-theme="lavender"] .btn-gold:hover,
[data-theme="lavender"] .btn-refresh:hover { filter: brightness(1.15); color: var(--bg); }
[data-theme="lavender"] .btn-ghost,
[data-theme="lavender"] .btn-outline { background: transparent; color: var(--gold); border: 1px solid var(--gold); }
[data-theme="lavender"] .btn-ghost:hover,
[data-theme="lavender"] .btn-outline:hover { background: var(--gold); color: var(--bg); }
[data-theme="lavender"] ::selection { background: var(--gold); color: var(--bg); }
[data-theme="lavender"] .app-header { background: linear-gradient(180deg, rgba(245,243,251,.95), rgba(245,243,251,.85)); }
[data-theme="lavender"] .search-input {
  background: var(--surface-2) url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' fill='none' stroke='%237a6a9a' stroke-width='2' viewBox='0 0 24 24'><circle cx='11' cy='11' r='7'/><path d='m20 20-3-3'/></svg>") no-repeat 14px center;
  background-size: 18px;
}

/* ============ WARM SAND & TERRACOTTA ============ */
[data-theme="terracotta"] {
  --bg:          #faf6ef;
  --surface:     #f0e8d8;
  --surface-2:   #f4ede0;
  --surface-3:   #e3d6bc;
  --border:      rgba(46,30,14,0.10);
  --border-mid:  rgba(46,30,14,0.22);
  --border-hi:   rgba(184,76,26,0.45);
  --gold:        #b84c1a;
  --gold-bright: #d76a3a;
  --gold-dim:    #7a2e0a;
  --text:        #2e1e0e;
  --text-muted:  #8a6a4a;
  --text-dim:    #b8a085;
  --link:        #b84c1a;
  --shadow-lg:   0 18px 48px -12px rgba(46,30,14,.18);
  --shadow-card: 0 2px 10px rgba(46,30,14,.08), 0 0 0 1px var(--border) inset;
  --glow-gold:   0 0 0 1px var(--border-hi) inset, 0 6px 22px -8px rgba(184,76,26,.22);
  --bg-radial-1: rgba(184,76,26,.08);
  --bg-radial-2: rgba(46,30,14,.05);
  --hero-tag-fg: #faf6ef;
  --brand-fg:    #faf6ef;
}
[data-theme="terracotta"] .tag { background: #f0d8c8; color: #7a2e0a; border: 1px solid #b84c1a; }
[data-theme="terracotta"] .btn-gold,
[data-theme="terracotta"] .btn-refresh { background: var(--text); color: var(--bg); }
[data-theme="terracotta"] .btn-gold:hover,
[data-theme="terracotta"] .btn-refresh:hover { filter: brightness(1.15); color: var(--bg); }
[data-theme="terracotta"] .btn-ghost,
[data-theme="terracotta"] .btn-outline { background: transparent; color: var(--gold); border: 1px solid var(--gold); }
[data-theme="terracotta"] .btn-ghost:hover,
[data-theme="terracotta"] .btn-outline:hover { background: var(--gold); color: var(--bg); }
[data-theme="terracotta"] ::selection { background: var(--gold); color: var(--bg); }
[data-theme="terracotta"] .app-header { background: linear-gradient(180deg, rgba(250,246,239,.95), rgba(250,246,239,.85)); }
[data-theme="terracotta"] .search-input {
  background: var(--surface-2) url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' fill='none' stroke='%238a6a4a' stroke-width='2' viewBox='0 0 24 24'><circle cx='11' cy='11' r='7'/><path d='m20 20-3-3'/></svg>") no-repeat 14px center;
  background-size: 18px;
}

/* ============ THEME PICKER POPOVER ============ */
.theme-popover {
  position: absolute;
  top: calc(100% + 8px);
  right: 0;
  background: var(--surface);
  border: 1px solid var(--border-mid);
  border-radius: var(--r-md);
  box-shadow: var(--shadow-lg);
  padding: 6px;
  display: none;
  z-index: 200;
  width: 230px;
}
.theme-popover.open { display: block; }
.theme-option {
  display: grid;
  grid-template-columns: 28px 1fr 16px;
  align-items: center;
  gap: 10px;
  padding: 8px 10px;
  border-radius: var(--r-sm);
  cursor: pointer;
  border: none;
  background: transparent;
  width: 100%;
  font: inherit;
  color: var(--text);
  text-align: left;
  transition: background var(--t-fast);
}
.theme-option:hover { background: var(--surface-2); }
.theme-option.active { background: var(--surface-3); }
.theme-swatch {
  width: 28px; height: 28px;
  border-radius: 50%;
  display: grid;
  grid-template-columns: 1fr 1fr;
  overflow: hidden;
  border: 1px solid var(--border-mid);
  position: relative;
}
.theme-swatch span:first-child { background: var(--sw-bg); }
.theme-swatch span:last-child  { background: var(--sw-acc); }
.theme-name { font-size: 13px; font-weight: 600; }
.theme-check { color: var(--gold); font-size: 14px; opacity: 0; }
.theme-option.active .theme-check { opacity: 1; }

*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
html { scroll-behavior: smooth; }
body {
  font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
  background: var(--bg);
  color: var(--text);
  font-size: 15px;
  line-height: 1.55;
  font-feature-settings: 'cv11','ss01','cv02';
  -webkit-font-smoothing: antialiased;
  -webkit-tap-highlight-color: transparent;
  min-height: 100vh;
  background-image:
    radial-gradient(1200px 600px at 80% -10%, var(--bg-radial-1), transparent 60%),
    radial-gradient(900px 500px at -10% 110%, var(--bg-radial-2), transparent 60%);
  background-attachment: fixed;
}
::selection { background: var(--gold); color: #000; }
a { color: var(--link); text-decoration: none; transition: color var(--t-fast); }
a:hover { color: var(--gold-bright); }
.font-display { font-family: 'Bebas Neue', 'Inter', sans-serif; letter-spacing: .02em; font-weight: 400; }
.font-mono { font-family: 'JetBrains Mono', ui-monospace, SFMono-Regular, Menlo, monospace; }

/* ============ HEADER + NAV ============ */
.app-header {
  position: sticky; top: 0; z-index: 100;
  background: linear-gradient(180deg, rgba(10,10,10,.96), rgba(10,10,10,.86));
  backdrop-filter: blur(20px) saturate(140%);
  -webkit-backdrop-filter: blur(20px) saturate(140%);
  border-bottom: 1px solid var(--border);
}
.app-header-inner {
  max-width: 1280px; margin: 0 auto;
  display: flex; align-items: center; gap: 16px;
  padding: 14px 18px;
}
.brand {
  display: flex; align-items: center; gap: 12px;
  text-decoration: none;
  flex: 1; min-width: 0;
}
.brand-mark {
  width: 38px; height: 38px;
  border-radius: var(--r-md);
  background: linear-gradient(135deg, var(--gold), var(--gold-dim));
  display: grid; place-items: center;
  font-family: 'Bebas Neue', sans-serif;
  font-size: 22px; color: var(--brand-fg); font-weight: 700;
  box-shadow: var(--glow-gold);
  flex-shrink: 0;
}
.brand-text { display: flex; flex-direction: column; min-width: 0; }
.brand-name {
  font-family: 'Bebas Neue', sans-serif;
  font-size: 22px; line-height: 1; letter-spacing: .04em;
  color: var(--text);
}
.brand-tag {
  font-size: 10px; letter-spacing: .22em; text-transform: uppercase;
  color: var(--gold); margin-top: 4px; font-weight: 600;
}
.nav-links { display: flex; align-items: center; gap: 2px; }
.nav-links a,
.nav-links .nav-dropdown-trigger {
  color: var(--text-muted);
  font-size: 13px; font-weight: 500;
  padding: 10px 14px; border-radius: var(--r-sm);
  transition: all var(--t-fast);
  white-space: nowrap;
  background: transparent; border: none; font-family: inherit;
  cursor: pointer;
  display: inline-flex; align-items: center; gap: 6px;
}
.nav-links a:hover,
.nav-links .nav-dropdown-trigger:hover { color: var(--text); background: var(--surface-2); }
.nav-links a.active,
.nav-links .nav-dropdown-trigger.active { color: var(--gold); background: rgba(212,175,55,.08); }

.nav-dropdown { position: relative; }
.nav-dropdown-trigger svg { transition: transform var(--t-fast); opacity: .65; }
.nav-dropdown[aria-expanded="true"] .nav-dropdown-trigger svg,
.nav-dropdown.open .nav-dropdown-trigger svg { transform: rotate(180deg); opacity: 1; }
.nav-dropdown-menu {
  position: absolute;
  top: calc(100% + 6px);
  left: 0;
  min-width: 180px;
  background: var(--surface);
  border: 1px solid var(--border-mid);
  border-radius: var(--r-md);
  box-shadow: var(--shadow-lg);
  padding: 6px;
  display: none;
  z-index: 150;
}
.nav-dropdown.open .nav-dropdown-menu,
.nav-dropdown:hover .nav-dropdown-menu { display: block; }
.nav-dropdown-menu a {
  display: block;
  padding: 9px 14px;
  font-size: 13px;
  color: var(--text);
  border-radius: var(--r-sm);
  text-decoration: none;
  white-space: nowrap;
}
.nav-dropdown-menu a:hover { background: var(--surface-2); color: var(--gold); }
.nav-dropdown-menu a.active { background: rgba(212,175,55,.12); color: var(--gold); }

/* Drawer grouping headers (mobile) */
.drawer-group {
  font-size: 10px; letter-spacing: .22em; text-transform: uppercase;
  color: var(--gold); font-weight: 700;
  padding: 16px 14px 6px;
  margin-top: 8px;
  border-top: 1px solid var(--border);
}
.drawer-group:first-of-type { margin-top: 0; border-top: none; padding-top: 8px; }
.btn-refresh {
  background: linear-gradient(135deg, var(--gold), var(--gold-dim));
  color: var(--brand-fg);
  border: none;
  padding: 10px 18px;
  border-radius: var(--r-sm);
  font-size: 12px; font-weight: 700;
  letter-spacing: .08em; text-transform: uppercase;
  cursor: pointer;
  transition: all var(--t-fast);
  box-shadow: var(--glow-gold);
}
.btn-refresh:hover { transform: translateY(-1px); filter: brightness(1.08); }
.btn-refresh:disabled { opacity: .55; cursor: not-allowed; }
.btn-install {
  display: inline-flex; align-items: center; gap: 6px;
  background: transparent;
  color: var(--gold);
  border: 1px solid var(--border-mid);
  padding: 9px 14px;
  border-radius: var(--r-sm);
  font-size: 12px; font-weight: 700;
  letter-spacing: .08em; text-transform: uppercase;
  cursor: pointer;
  transition: all var(--t-fast);
  font-family: inherit;
}
.btn-install:hover { border-color: var(--gold); background: rgba(212,175,55,.06); }

/* ============ ADMIN GATE ============ */
/* Admin nav links + Refresh button hidden unless html.pre-is-admin (set in head before body renders) */
html:not(.pre-is-admin) [data-admin="1"],
html:not(.pre-is-admin) .nav-links a.admin-only,
html:not(.pre-is-admin) .drawer a.admin-only,
html:not(.pre-is-admin) #install-app-btn,
html:not(.pre-is-admin) #nav-refresh-btn,
html:not(.pre-is-admin) .drawer .btn-refresh,
html:not(.pre-is-admin) .btn-logout,
html:not(.pre-is-admin) .drawer-signout { display: none !important; }
html.pre-is-admin .btn-login,
html.pre-is-admin .drawer-signin,
html.pre-is-admin .gate-overlay { display: none !important; }
.btn-login, .btn-logout {
  display: inline-flex; align-items: center; gap: 6px;
  padding: 9px 14px;
  background: transparent;
  color: var(--text-muted);
  border: 1px solid var(--border-mid);
  border-radius: var(--r-sm);
  font-size: 12px; font-weight: 700;
  letter-spacing: .08em; text-transform: uppercase;
  cursor: pointer;
  font-family: inherit;
  transition: all var(--t-fast);
}
.btn-login:hover, .btn-logout:hover { color: var(--gold); border-color: var(--gold); }
.gate-overlay {
  position: fixed; inset: 0; z-index: 500;
  background: rgba(0,0,0,.85);
  backdrop-filter: blur(10px);
  display: none; align-items: center; justify-content: center;
}
.gate-overlay.open { display: flex; }
.gate-card {
  background: var(--surface);
  border: 1px solid var(--border-mid);
  border-radius: var(--r-lg);
  padding: 32px 32px 26px;
  max-width: 380px;
  width: calc(100vw - 32px);
  box-shadow: var(--shadow-lg);
  text-align: center;
}
.gate-card h2 {
  font-family: 'Bebas Neue', sans-serif;
  font-size: 28px; letter-spacing: .04em;
  color: var(--text);
  margin-bottom: 8px;
}
.gate-card .gate-sub {
  font-size: 13px; color: var(--text-muted);
  margin-bottom: 20px;
}
.gate-card input[type="password"] {
  width: 100%;
  margin-bottom: 12px;
  text-align: center;
  letter-spacing: .2em;
  font-size: 16px;
}
.gate-card .gate-actions { display: flex; gap: 10px; }
.gate-card .gate-actions button { flex: 1; }
.gate-error {
  font-size: 12px; color: var(--danger);
  min-height: 18px; margin-bottom: 8px;
}
.gate-storefront-msg {
  font-size: 11px; color: var(--text-dim);
  letter-spacing: .12em; text-transform: uppercase; font-weight: 600;
  margin-top: 14px;
}
.btn-theme {
  width: 38px; height: 38px;
  display: inline-flex; align-items: center; justify-content: center;
  background: transparent;
  color: var(--text-muted);
  border: 1px solid var(--border-mid);
  border-radius: var(--r-sm);
  cursor: pointer;
  transition: all var(--t-fast);
}
.btn-theme:hover { color: var(--gold); border-color: var(--gold); }
.btn-theme .ic-moon { display: none; }
.btn-theme .ic-sun  { display: block; }
[data-theme="cream"] .btn-theme .ic-sun  { display: none; }
[data-theme="cream"] .btn-theme .ic-moon { display: block; }
[data-theme="cream"] .btn-theme {
  color: var(--text);
  border-color: var(--text);
}
[data-theme="cream"] .btn-theme:hover {
  background: var(--text);
  color: var(--bg);
}
.menu-toggle {
  display: none;
  width: 42px; height: 42px;
  border: 1px solid var(--border-mid);
  background: var(--surface);
  color: var(--text);
  border-radius: var(--r-sm);
  cursor: pointer;
  align-items: center; justify-content: center;
}
.menu-toggle svg { width: 22px; height: 22px; }

/* Mobile drawer */
.drawer-backdrop {
  position: fixed; inset: 0;
  background: rgba(0,0,0,.7);
  backdrop-filter: blur(4px);
  z-index: 200;
  opacity: 0; pointer-events: none;
  transition: opacity var(--t-base);
}
.drawer-backdrop.open { opacity: 1; pointer-events: auto; }
.drawer {
  position: fixed;
  top: 0; right: 0; bottom: 0;
  width: min(86vw, 340px);
  background: var(--surface);
  border-left: 1px solid var(--border-mid);
  z-index: 201;
  transform: translateX(100%);
  transition: transform var(--t-base);
  display: flex; flex-direction: column;
  padding: 24px 20px;
  overflow-y: auto;
}
.drawer.open { transform: translateX(0); }
.drawer-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 28px; }
.drawer-close {
  width: 38px; height: 38px;
  border-radius: var(--r-sm);
  background: var(--surface-3);
  border: 1px solid var(--border);
  color: var(--text);
  cursor: pointer;
  display: grid; place-items: center;
}
.drawer a {
  display: flex; align-items: center; justify-content: space-between;
  color: var(--text);
  padding: 16px 14px;
  border-radius: var(--r-md);
  font-size: 15px; font-weight: 500;
  margin-bottom: 4px;
  border: 1px solid transparent;
}
.drawer a:hover, .drawer a.active {
  background: var(--surface-2);
  border-color: var(--border);
  color: var(--gold);
}
.drawer a::after {
  content: '\\2192'; color: var(--text-dim); font-size: 18px;
}
.drawer-foot { margin-top: auto; padding-top: 20px; border-top: 1px solid var(--border); }
.drawer .btn-refresh { width: 100%; padding: 14px; font-size: 13px; }

/* ============ LAYOUT ============ */
main {
  max-width: 1280px;
  margin: 0 auto;
  padding: 32px 20px 80px;
}
.section-head {
  display: flex; align-items: flex-end; justify-content: space-between;
  gap: 16px; margin-bottom: 20px; flex-wrap: wrap;
}
.section-title {
  font-family: 'Bebas Neue', sans-serif;
  font-size: clamp(28px, 4vw, 40px);
  letter-spacing: .03em; line-height: 1;
  color: var(--text);
}
.section-title .accent { color: var(--gold); }
.section-sub { color: var(--text-muted); font-size: 14px; }
.eyebrow {
  font-size: 11px; letter-spacing: .25em; text-transform: uppercase;
  color: var(--gold); font-weight: 700; margin-bottom: 8px;
}

/* ============ STATS ============ */
.stat-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 14px;
  margin-bottom: 28px;
}
.stat-card {
  position: relative;
  background: linear-gradient(180deg, var(--surface), var(--surface-2));
  border: 1px solid var(--border);
  border-radius: var(--r-lg);
  padding: 22px 20px;
  overflow: hidden;
  transition: all var(--t-base);
}
.stat-card::before {
  content: ''; position: absolute; inset: 0;
  background: radial-gradient(400px 200px at 100% 0%, rgba(212,175,55,.08), transparent 60%);
  pointer-events: none;
}
.stat-card:hover { transform: translateY(-2px); border-color: var(--border-mid); }
.stat-card .num {
  font-family: 'Bebas Neue', sans-serif;
  font-size: 44px; line-height: 1;
  color: var(--gold);
  letter-spacing: .02em;
  text-shadow: 0 0 28px rgba(212,175,55,.25);
}
.stat-card .num.danger  { color: var(--danger); text-shadow: 0 0 28px rgba(224,123,111,.25); }
.stat-card .num.warning { color: var(--warning); text-shadow: 0 0 28px rgba(224,181,74,.25); }
.stat-card .num.success { color: var(--success); text-shadow: 0 0 28px rgba(127,199,122,.25); }
.stat-card .lbl {
  font-size: 11px; letter-spacing: .18em; text-transform: uppercase;
  color: var(--text-muted); font-weight: 600;
  margin-top: 8px;
}
.stat-card.linked { cursor: pointer; }
.stat-card.linked:hover { border-color: var(--border-hi); box-shadow: var(--glow-gold); }
.stat-card.linked a { color: inherit; }
button.stat-card {
  font-family: inherit; color: inherit; text-align: center; width: 100%;
  appearance: none; -webkit-appearance: none;
}
button.stat-card.active {
  border-color: var(--gold);
  box-shadow: var(--glow-gold);
}
button.stat-card.active .num { filter: brightness(1.15); }

/* ============ CARDS / SURFACES ============ */
.panel {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--r-lg);
  padding: 22px;
  margin-bottom: 16px;
}
.panel-head {
  display: flex; align-items: center; justify-content: space-between;
  margin-bottom: 18px;
  padding-bottom: 14px;
  border-bottom: 1px solid var(--border);
}
.panel-title {
  font-family: 'Bebas Neue', sans-serif;
  font-size: 22px; letter-spacing: .03em;
  color: var(--text);
}
.panel-sub { color: var(--text-muted); font-size: 13px; }

/* ============ BUTTONS / CHIPS ============ */
.btn {
  display: inline-flex; align-items: center; justify-content: center; gap: 6px;
  padding: 10px 18px;
  border-radius: var(--r-sm);
  font-size: 13px; font-weight: 600;
  cursor: pointer;
  text-decoration: none;
  border: 1px solid transparent;
  transition: all var(--t-fast);
  font-family: inherit;
  white-space: nowrap;
}
.btn-gold {
  background: linear-gradient(135deg, var(--gold), var(--gold-dim));
  color: var(--brand-fg);
  letter-spacing: .04em;
}
.btn-gold:hover { color: #000; transform: translateY(-1px); filter: brightness(1.08); }
.btn-ghost {
  background: var(--surface-2);
  color: var(--text);
  border-color: var(--border);
}
.btn-ghost:hover { background: var(--surface-3); border-color: var(--border-mid); color: var(--gold); }
.btn-outline {
  background: transparent;
  color: var(--gold);
  border: 1px solid var(--border-mid);
}
.btn-outline:hover { border-color: var(--gold); background: rgba(212,175,55,.06); color: var(--gold-bright); }
.btn-block { width: 100%; padding: 14px; }
.btn:disabled { opacity: .5; cursor: not-allowed; }

.chip {
  display: inline-flex; align-items: center; gap: 6px;
  padding: 7px 14px;
  border-radius: 999px;
  background: var(--surface-2);
  border: 1px solid var(--border);
  color: var(--text-muted);
  font-size: 12px; font-weight: 600;
  cursor: pointer;
  transition: all var(--t-fast);
  letter-spacing: .02em;
  user-select: none;
}
.chip:hover { color: var(--text); border-color: var(--border-mid); }
.chip.active {
  background: linear-gradient(135deg, var(--gold), var(--gold-dim));
  color: var(--brand-fg);
  border-color: var(--gold);
}
.chip .count { color: inherit; opacity: .7; }

/* ============ FORM CONTROLS ============ */
input, select, textarea {
  width: 100%;
  padding: 12px 14px;
  background: var(--surface-2);
  color: var(--text);
  border: 1px solid var(--border);
  border-radius: var(--r-sm);
  font-size: 14px;
  font-family: inherit;
  transition: all var(--t-fast);
}
input:focus, select:focus, textarea:focus {
  outline: none;
  border-color: var(--gold);
  background: var(--surface-3);
  box-shadow: 0 0 0 3px rgba(212,175,55,.15);
}
input::placeholder, textarea::placeholder { color: var(--text-dim); }
.search-input {
  background: var(--surface-2) url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' fill='none' stroke='%239a9388' stroke-width='2' viewBox='0 0 24 24'><circle cx='11' cy='11' r='7'/><path d='m20 20-3-3'/></svg>") no-repeat 14px center;
  background-size: 18px;
  padding-left: 44px;
}

input[type="checkbox"] {
  width: auto;
  appearance: none;
  -webkit-appearance: none;
  width: 20px; height: 20px;
  border: 1.5px solid var(--border-mid);
  border-radius: 4px;
  background: var(--surface-2);
  cursor: pointer;
  position: relative;
  transition: all var(--t-fast);
  margin: 0;
  padding: 0;
  vertical-align: middle;
}
input[type="checkbox"]:checked {
  background: var(--gold);
  border-color: var(--gold);
}
input[type="checkbox"]:checked::after {
  content: ''; position: absolute;
  left: 5px; top: 2px;
  width: 6px; height: 11px;
  border: solid #0a0a0a;
  border-width: 0 2px 2px 0;
  transform: rotate(45deg);
}

/* ============ LISTING GRID ============ */
.filter-bar {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--r-lg);
  padding: 20px;
  margin-bottom: 22px;
}
.filter-row { display: flex; gap: 10px; flex-wrap: wrap; align-items: center; margin-bottom: 14px; }
.filter-row:last-child { margin-bottom: 0; }
.filter-chips { display: flex; gap: 8px; flex-wrap: wrap; flex: 1 1 100%; }
.slider-wrap { flex: 1 1 100%; padding: 4px 8px 0; }
.slider-labels { display: flex; justify-content: space-between; font-size: 11px; color: var(--text-muted); margin-bottom: 6px; letter-spacing: .12em; text-transform: uppercase; }
.slider-values { color: var(--gold); font-weight: 700; font-family: 'JetBrains Mono', monospace; }

.grid {
  display: grid;
  gap: 14px;
}
.grid[data-size="large"]  { grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); }
.grid[data-size="medium"] { grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); }
.grid[data-size="small"]  { grid-template-columns: repeat(auto-fill, minmax(140px, 1fr)); }
.grid[data-size="list"]   { grid-template-columns: 1fr; }

.listing-card {
  position: relative;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--r-lg);
  overflow: hidden;
  display: flex;
  flex-direction: column;
  transition: all var(--t-base);
  isolation: isolate;
}
.listing-card::after {
  content: ''; position: absolute; inset: 0;
  border-radius: var(--r-lg); pointer-events: none;
  box-shadow: 0 0 0 1px transparent inset;
  transition: box-shadow var(--t-base);
}
.listing-card:hover { transform: translateY(-3px); border-color: var(--border-mid); }
.listing-card:hover::after { box-shadow: 0 0 0 1px var(--border-hi) inset, 0 24px 50px -10px rgba(0,0,0,.7); }

.thumb-wrap {
  position: relative;
  width: 100%;
  background: linear-gradient(135deg, #0e0e0e, #1a1a1a);
  overflow: hidden;
}
.thumb-wrap::before {
  content: ''; position: absolute; inset: 0;
  background:
    linear-gradient(180deg, transparent 60%, rgba(0,0,0,.7)),
    radial-gradient(circle at 30% 30%, rgba(212,175,55,.06), transparent 50%);
  pointer-events: none; z-index: 1;
}
.grid[data-size="large"]  .thumb-wrap { aspect-ratio: 4/3; }
.grid[data-size="medium"] .thumb-wrap { aspect-ratio: 1/1; }
.grid[data-size="small"]  .thumb-wrap { aspect-ratio: 1/1; }
.listing-card img {
  width: 100%; height: 100%;
  object-fit: cover;
  display: block;
  transition: transform var(--t-base);
}
.listing-card:hover img { transform: scale(1.04); }

.fav-btn {
  position: absolute; top: 10px; right: 10px;
  width: 36px; height: 36px;
  border-radius: 50%;
  background: rgba(0,0,0,.55);
  backdrop-filter: blur(8px);
  border: 1px solid rgba(255,255,255,.08);
  color: var(--text);
  cursor: pointer;
  display: grid; place-items: center;
  z-index: 5;
  transition: all var(--t-fast);
}
.fav-btn svg { width: 18px; height: 18px; fill: none; stroke: currentColor; stroke-width: 2; }
.fav-btn:hover { color: var(--gold); transform: scale(1.08); }
.fav-btn.on { color: var(--gold); }
.fav-btn.on svg { fill: var(--gold); stroke: var(--gold); }

.zoom-btn {
  position: absolute; top: 10px; left: 10px;
  width: 36px; height: 36px;
  border-radius: 50%;
  background: rgba(0,0,0,.55);
  backdrop-filter: blur(8px);
  border: 1px solid rgba(255,255,255,.08);
  color: var(--text);
  cursor: pointer;
  display: grid; place-items: center;
  z-index: 5;
  transition: all var(--t-fast);
  opacity: 0;
}
.listing-card:hover .zoom-btn { opacity: 1; }
.zoom-btn:hover { color: var(--gold); }

.listing-card .info { padding: 14px 16px; flex: 1; min-width: 0; }
.listing-card .info h3 {
  font-size: 13px; font-weight: 600;
  margin-bottom: 8px;
  line-height: 1.4;
  color: var(--text);
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.listing-card .info h3 a { color: inherit; }
.listing-card .info h3 a:hover { color: var(--gold); }
.listing-card .price {
  font-family: 'Bebas Neue', sans-serif;
  font-size: 26px; line-height: 1;
  color: var(--gold);
  letter-spacing: .02em;
  display: inline-flex; align-items: center; gap: 6px;
  cursor: pointer;
  outline: none;
}
.listing-card .price-info-ic {
  font-size: 12px; color: var(--text-muted);
  font-family: 'Inter', sans-serif;
  transition: color var(--t-fast);
}
.listing-card .price:hover .price-info-ic,
.listing-card .price:focus .price-info-ic { color: var(--gold); }
.listing-card .price-wrap { position: relative; display: inline-block; }
.listing-card .price-pop {
  display: none;
  position: fixed;            /* fixed so it escapes the card's overflow clipping */
  min-width: 260px;
  max-width: 300px;
  background: var(--surface-2);
  border: 1px solid var(--border-hi);
  border-radius: var(--r-md);
  box-shadow: var(--shadow-lg);
  padding: 12px 14px;
  z-index: 200;
  font-family: 'Inter', sans-serif;
  text-align: left;
}
.listing-card .price-pop.open { display: block; }
.listing-card .price-pop .pp-row {
  display: grid;
  grid-template-columns: 1fr auto;
  grid-template-rows: auto auto;
  gap: 2px 12px;
  padding: 6px 0;
  border-bottom: 1px solid var(--border);
}
.listing-card .price-pop .pp-row:last-child { border-bottom: none; }
.listing-card .price-pop .pp-lbl {
  font-size: 10px; letter-spacing: .14em; text-transform: uppercase;
  color: var(--text-muted); font-weight: 700;
  grid-column: 1;
}
.listing-card .price-pop .pp-val {
  font-size: 13px; font-weight: 700; color: var(--text);
  text-align: right; grid-column: 2; grid-row: 1;
}
.listing-card .price-pop .pp-note {
  font-size: 11px; color: var(--text-dim);
  grid-column: 1 / -1; grid-row: 2;
}
.grid[data-size="small"] .listing-card .price { font-size: 20px; }
.listing-card .meta {
  font-size: 11px; color: var(--text-muted);
  margin-top: 6px;
  display: flex; gap: 6px; flex-wrap: wrap;
}
.tag {
  display: inline-block;
  padding: 2px 8px;
  background: var(--surface-3);
  border-radius: 999px;
  font-size: 10px; letter-spacing: .12em;
  text-transform: uppercase;
  color: var(--text-muted);
  font-weight: 600;
}
.tag-gold { background: rgba(212,175,55,.12); color: var(--gold); }
.tag-danger { background: rgba(224,123,111,.12); color: var(--danger); }
.tag-warn { background: rgba(224,181,74,.14); color: var(--warning); }
.tag-success { background: rgba(127,199,122,.14); color: var(--success); }

.listing-card .actions {
  padding: 12px 14px;
  border-top: 1px solid var(--border);
  display: flex; gap: 8px;
}
.grid[data-size="small"] .listing-card .info h3 { font-size: 11px; -webkit-line-clamp: 1; }
.grid[data-size="small"] .listing-card .meta { display: none; }
.grid[data-size="small"] .listing-card .actions { padding: 8px; }
.grid[data-size="list"] .listing-card { flex-direction: row; align-items: stretch; }
.grid[data-size="list"] .listing-card .thumb-wrap { width: 120px; flex: 0 0 120px; aspect-ratio: 1/1; }
.grid[data-size="list"] .listing-card .info { padding: 14px 18px; }
.grid[data-size="list"] .listing-card .actions { border-top: none; border-left: 1px solid var(--border); flex-direction: column; min-width: 130px; }

.size-toggle { display: flex; gap: 6px; align-items: center; }
.size-toggle .lbl-txt { font-size: 11px; color: var(--text-muted); letter-spacing: .14em; text-transform: uppercase; margin-right: 6px; font-weight: 600; }
.size-btn {
  padding: 7px 14px;
  border: 1px solid var(--border);
  border-radius: var(--r-sm);
  background: var(--surface-2);
  font-size: 12px; font-weight: 600;
  cursor: pointer;
  color: var(--text-muted);
  transition: all var(--t-fast);
  letter-spacing: .04em;
}
.size-btn:hover { color: var(--text); border-color: var(--border-mid); }
.size-btn.active {
  background: linear-gradient(135deg, var(--gold), var(--gold-dim));
  color: var(--brand-fg);
  border-color: var(--gold);
}

/* ============ TABLES ============ */
.table-wrap { overflow-x: auto; margin: 0 -22px; }
.table-wrap table { min-width: 600px; }
table { width: 100%; border-collapse: collapse; }
th {
  text-align: left;
  padding: 14px 18px;
  font-size: 11px; letter-spacing: .14em; text-transform: uppercase;
  color: var(--text-muted); font-weight: 700;
  background: var(--surface-2);
  border-bottom: 1px solid var(--border);
}
td {
  padding: 14px 18px;
  border-bottom: 1px solid var(--border);
  font-size: 13.5px;
  vertical-align: top;
  color: var(--text);
}
tr:last-child td { border-bottom: none; }
tr:hover td { background: rgba(212,175,55,.03); }

/* ============ BADGES ============ */
.badge {
  display: inline-block;
  padding: 4px 10px;
  border-radius: 999px;
  font-size: 11px; font-weight: 700;
  letter-spacing: .08em; text-transform: uppercase;
  border: 1px solid transparent;
}
.badge-success { background: rgba(127,199,122,.12); color: var(--success); border-color: rgba(127,199,122,.25); }
.badge-warning { background: rgba(224,181,74,.12); color: var(--warning); border-color: rgba(224,181,74,.25); }
.badge-danger  { background: rgba(224,123,111,.12); color: var(--danger);  border-color: rgba(224,123,111,.25); }
.badge-gold    { background: rgba(212,175,55,.12);  color: var(--gold);    border-color: rgba(212,175,55,.30); }

/* ============ STATUS BAR / TOAST ============ */
#status-bar {
  display: none;
  padding: 14px 18px; border-radius: var(--r-md);
  margin-bottom: 16px; font-size: 14px;
  border: 1px solid;
}
.status-info    { background: rgba(108,176,255,.08); color: var(--link);    border-color: rgba(108,176,255,.3); }
.status-success { background: rgba(127,199,122,.08); color: var(--success); border-color: rgba(127,199,122,.3); }
.status-warning { background: rgba(224,181,74,.08);  color: var(--warning); border-color: rgba(224,181,74,.3); }
.status-danger  { background: rgba(224,123,111,.08); color: var(--danger);  border-color: rgba(224,123,111,.3); }

.toast {
  position: fixed; bottom: 24px; left: 50%;
  transform: translateX(-50%) translateY(100px);
  background: var(--surface-2);
  color: var(--text);
  padding: 14px 22px;
  border-radius: var(--r-md);
  font-size: 13px; font-weight: 500;
  z-index: 9999;
  box-shadow: var(--shadow-lg);
  border: 1px solid var(--border-mid);
  opacity: 0;
  transition: all var(--t-base);
  max-width: calc(100vw - 32px);
}
.toast.show { opacity: 1; transform: translateX(-50%) translateY(0); }

/* ============ FOOTER ============ */
.app-footer {
  border-top: 1px solid var(--border);
  padding: 32px 20px;
  text-align: center;
  color: var(--text-dim);
  font-size: 12px;
  letter-spacing: .08em;
}
.app-footer .seller-link { color: var(--gold); }

/* ============ NO RESULTS ============ */
#no-results {
  display: none;
  padding: 60px 20px; text-align: center;
  color: var(--text-muted);
  background: var(--surface);
  border: 1px dashed var(--border-mid);
  border-radius: var(--r-lg);
}
#no-results .big {
  font-family: 'Bebas Neue', sans-serif;
  font-size: 36px; color: var(--gold); margin-bottom: 6px;
}

/* ============ POLISH LAYER — round 2 (design director feedback) ============ */

/* Price treatment — gold gradient text fill with subtle glow + tabular nums.
   Cream/light themes lose the gradient (text-fill-color: transparent + light background
   becomes invisible) so we scope this to dark themes only. */
.listing-card .price, .hero-price, .deal-price, .product-price, .sold-price, .pr-current, .pr-new {
  font-feature-settings: 'tnum' 1, 'ss01' 1;
  font-variant-numeric: tabular-nums;
}
html:not([data-theme]) .listing-card .price,
html:not([data-theme]) .hero-price,
html:not([data-theme]) .deal-price,
html:not([data-theme]) .product-price,
html[data-theme="midnight"] .listing-card .price,
html[data-theme="midnight"] .hero-price,
html[data-theme="midnight"] .deal-price,
html[data-theme="midnight"] .product-price,
html[data-theme="crimson"] .listing-card .price,
html[data-theme="crimson"] .hero-price,
html[data-theme="crimson"] .deal-price,
html[data-theme="crimson"] .product-price {
  background: linear-gradient(180deg, var(--gold-bright) 0%, var(--gold) 55%, var(--gold-dim) 100%);
  -webkit-background-clip: text; background-clip: text;
  -webkit-text-fill-color: transparent; color: transparent;
  text-shadow: 0 0 20px rgba(212,175,55,.18);
}

/* Card hover — single, expensive-feeling move (no jittery translateY) */
.listing-card { transition: border-color .35s ease, box-shadow .35s ease; }
.listing-card:hover {
  transform: none;
  border-color: rgba(212,175,55,.35);
  box-shadow: 0 1px 0 rgba(212,175,55,.12) inset, 0 28px 56px -22px rgba(0,0,0,.85), 0 0 0 1px rgba(212,175,55,.08);
}
.listing-card:hover img { transform: scale(1.06); transition: transform 900ms cubic-bezier(.2,.7,.2,1); }

/* Drop the harsh dark-bottom gradient on thumbs — it kills foil/holo color */
.thumb-wrap::before {
  background: radial-gradient(circle at 30% 25%, rgba(212,175,55,.07), transparent 55%);
  opacity: .9;
  transition: opacity .4s;
}
.listing-card:hover .thumb-wrap::before { opacity: 0; }

/* Section header rhythm — looser sub leading, hairline rule with gold accent */
.section-title { margin-bottom: 6px; }
.section-sub   { line-height: 1.7; max-width: 60ch; color: var(--text-muted); }
.section-head  {
  padding-bottom: 18px; margin-bottom: 28px;
  border-bottom: 1px solid var(--border);
  position: relative;
}
.section-head::after {
  content: ''; display: block;
  width: 48px; height: 2px;
  background: linear-gradient(90deg, var(--gold), transparent);
  position: absolute; left: 0; bottom: -1px;
}

/* Chip active — real "press" feel */
.chip { transition: color .15s, background .15s, box-shadow .25s; }
.chip.active {
  box-shadow: inset 0 1px 0 rgba(255,255,255,.12),
              inset 0 -2px 0 var(--gold),
              0 4px 12px -4px rgba(212,175,55,.4);
}

/* Item detail hero — perspective tilt + shimmer on hover. Signature collector move. */
.product-gallery {
  perspective: 1200px;
  position: relative;
  isolation: isolate;
}
.product-gallery a { display: block; width: 100%; height: 100%; }
.product-gallery img {
  transition: transform .8s cubic-bezier(.2,.7,.2,1);
  will-change: transform;
}
.product-gallery:hover img { transform: rotateY(-4deg) rotateX(2deg) scale(1.02); }
.product-gallery::after {
  content: ''; position: absolute; inset: 24px; pointer-events: none;
  background: linear-gradient(115deg, transparent 30%, rgba(255,255,255,.14) 50%, transparent 70%);
  transform: translateX(-110%);
  transition: transform 1.2s ease;
  mix-blend-mode: overlay;
  border-radius: var(--r-xl);
  z-index: 3;
}
.product-gallery:hover::after { transform: translateX(110%); }

/* Hide buyer-leaking analytics from public visitors (anything tagged data-admin="1") */
html:not(.pre-is-admin) .price-pop-wrap,
html:not(.pre-is-admin) .price-info-ic { display: none !important; }

/* ============ POLISH LAYER ============ */

/* Reading-flow scroll progress indicator at top of page */
.scroll-progress {
  position: fixed; top: 0; left: 0; right: 0;
  height: 3px; z-index: 999;
  background: linear-gradient(90deg, var(--gold), var(--gold-bright));
  transform-origin: 0 50%;
  transform: scaleX(0);
  transition: transform 80ms linear;
  pointer-events: none;
}

/* View Transitions — smooth cross-page navigation */
@view-transition { navigation: auto; }
::view-transition-old(root), ::view-transition-new(root) {
  animation-duration: 220ms;
  animation-timing-function: cubic-bezier(.4,0,.2,1);
}

/* Card entrance stagger — fade up from below */
@keyframes h2k-fade-up {
  from { opacity: 0; transform: translateY(14px); }
  to   { opacity: 1; transform: translateY(0); }
}
.listing-card, .deal-card, .sold-card, .q-card, .pr-card, .tr-card, .cl-card, .topick-tile, .recent-card, .a-panel {
  animation: h2k-fade-up 480ms cubic-bezier(.4,0,.2,1) both;
  animation-delay: calc(var(--enter-idx, 0) * 28ms);
}

/* Keyboard focus rings — gold glow, never harsh blue */
*:focus { outline: none; }
a:focus-visible, button:focus-visible, input:focus-visible, select:focus-visible,
textarea:focus-visible, [contenteditable]:focus-visible, [role="button"]:focus-visible {
  outline: 2px solid var(--gold);
  outline-offset: 3px;
  border-radius: var(--r-sm);
  box-shadow: 0 0 0 4px rgba(212,175,55,.18);
}

/* Empty-state illustrations */
.empty-state {
  display: flex; flex-direction: column; align-items: center; justify-content: center;
  padding: 60px 20px; text-align: center; gap: 14px;
  background: var(--surface);
  border: 1px dashed var(--border-mid);
  border-radius: var(--r-lg);
}
.empty-state-icon {
  width: 64px; height: 64px;
  color: var(--gold);
  opacity: .7;
  animation: h2k-fade-up 600ms both;
}
.empty-state-title {
  font-family: 'Bebas Neue', sans-serif;
  font-size: 28px; letter-spacing: .03em;
  color: var(--text);
}
.empty-state-sub { color: var(--text-muted); font-size: 14px; max-width: 380px; }

/* Confetti container — DOM-injected on success */
.h2k-confetti-host {
  position: fixed; inset: 0;
  pointer-events: none; z-index: 9998;
  overflow: hidden;
}
.h2k-confetti {
  position: absolute; top: -10px;
  width: 10px; height: 14px;
  border-radius: 2px;
  opacity: 0;
  animation: h2k-confetti-fall 1600ms ease-out forwards;
}
@keyframes h2k-confetti-fall {
  0% { opacity: 1; transform: translate3d(0, -10vh, 0) rotate(0deg); }
  100% { opacity: 0; transform: translate3d(var(--cx, 0), 110vh, 0) rotate(var(--cr, 540deg)); }
}

/* Ripple on .btn-gold click */
.btn-gold { position: relative; overflow: hidden; }
.btn-gold::after {
  content: ''; position: absolute; inset: 0;
  background: radial-gradient(circle at var(--rx, 50%) var(--ry, 50%), rgba(255,255,255,.45), transparent 50%);
  opacity: 0;
  transition: opacity 400ms;
  pointer-events: none;
}
.btn-gold:active::after { opacity: 1; transition: opacity 60ms; }

/* Subtle tab indicator slide — handled via .active background */
.tab-bar { position: relative; }

/* Gentle pulse on price element while popover is open */
.price-pop.open + .price,
.listing-card .price-wrap:hover .price { animation: h2k-price-pulse 1.6s ease-in-out infinite; }
@keyframes h2k-price-pulse {
  0%, 100% { text-shadow: 0 0 0 transparent; }
  50%      { text-shadow: 0 0 18px rgba(212,175,55,.4); }
}

/* Skeleton state for charts that haven't drawn yet */
@keyframes h2k-shimmer {
  0% { background-position: -300px 0; }
  100% { background-position: calc(300px + 100%) 0; }
}
.skeleton {
  background: linear-gradient(90deg, var(--surface-2) 0%, var(--surface-3) 50%, var(--surface-2) 100%);
  background-size: 300px 100%;
  animation: h2k-shimmer 1.6s linear infinite;
  border-radius: var(--r-sm);
}

/* Reduced motion respect — disable all animations */
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    animation-duration: 0.01ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: 0.01ms !important;
    scroll-behavior: auto !important;
  }
  .listing-card, .deal-card, .sold-card, .q-card, .pr-card, .tr-card, .cl-card, .topick-tile, .recent-card, .a-panel {
    animation: none !important;
    opacity: 1 !important;
    transform: none !important;
  }
}

/* ============ NOUISLIDER OVERRIDES ============ */
.noUi-target {
  background: var(--surface-3);
  border: 1px solid var(--border);
  box-shadow: none;
  height: 6px;
}
.noUi-connect { background: linear-gradient(90deg, var(--gold-dim), var(--gold)); }
.noUi-handle {
  background: var(--gold);
  border: 2px solid #0a0a0a;
  border-radius: 50%;
  box-shadow: 0 0 0 1px var(--gold), 0 8px 16px rgba(0,0,0,.6);
  width: 22px !important; height: 22px !important;
  right: -11px !important; top: -9px !important;
  cursor: grab;
}
.noUi-handle::before, .noUi-handle::after { display: none; }

/* ============ GLIGHTBOX OVERRIDES ============ */
.glightbox-clean .gslide-description { background: var(--surface) !important; }
.glightbox-clean .gdesc-inner { color: var(--text); }
.glightbox-clean .gslide-title { color: var(--gold) !important; font-family: 'Bebas Neue', sans-serif; font-size: 22px; }
.gbtn { background: var(--surface-2) !important; }

/* ============ RESPONSIVE ============ */
@media (max-width: 880px) {
  .nav-links { display: none; }
  .menu-toggle { display: inline-flex; }
  /* Header auxiliary buttons get tucked into the drawer at narrow widths so
     the brand block + hamburger don't collide. The drawer-foot below renders
     the same actions. */
  .btn-install,
  .btn-login,
  .btn-logout,
  .btn-refresh { display: none !important; }
  /* Tighten header padding so the brand text gets max horizontal room. */
  .app-header-inner { padding: 10px 12px; gap: 10px; }
  /* Force the brand tag onto a single line, ellipsized — the forced <br>
     breaks rendered "SPORTS & POKEMON CARDS" as a cramped stack on phones. */
  .brand-tag {
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    font-size: 9px;
    letter-spacing: .18em;
  }
  .brand-tag br { display: none; }
  /* Slim the brand mark a hair on mobile so the title gets more room. */
  .brand-mark { width: 32px; height: 32px; font-size: 18px; }
  .brand-name { font-size: 20px; }
}
@media (max-width: 640px) {
  main { padding: 22px 14px 70px; }
  .panel { padding: 16px; }
  .stat-card { padding: 18px 16px; }
  .stat-card .num { font-size: 36px; }
  .filter-row { gap: 8px; }
  .grid[data-size="large"]  { grid-template-columns: 1fr 1fr; gap: 12px; }
  .grid[data-size="medium"] { grid-template-columns: 1fr 1fr; gap: 10px; }
  .grid[data-size="small"]  { grid-template-columns: repeat(3, 1fr); gap: 8px; }
  .listing-card .info { padding: 12px; }
  .listing-card .price { font-size: 22px; }
  .table-wrap { margin: 0 -16px; }
  th, td { padding: 12px 14px; font-size: 12.5px; }
}
@media (max-width: 420px) {
  .grid[data-size="medium"] { grid-template-columns: 1fr; }
  .grid[data-size="list"] .listing-card .thumb-wrap { width: 96px; flex: 0 0 96px; }
}
"""

_CDN_HEAD = """
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="preconnect" href="https://cdn.jsdelivr.net">
<link href="https://fonts.googleapis.com/css2?family=Bebas+Neue&family=Inter:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500;700&display=swap" rel="stylesheet">
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/glightbox/dist/css/glightbox.min.css">
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/nouislider@15.7.1/dist/nouislider.min.css">
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/nouislider@15.7.1/dist/nouislider.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/glightbox/dist/js/glightbox.min.js"></script>
"""

_CDN_FOOT = ""  # libs now load synchronously in <head> so body inline scripts can use them

# nav items: (href, label, public?, group?)
# - group=None  → top-level direct link
# - group="X"   → tucked under the "X ▾" dropdown
# Groups are admin-only if every item inside them is admin-only.
_NAV_ITEMS = [
    ("index.html",         "Listings",      True,  None),
    ("steals.html",        "Steals",        True,  None),
    ("sold.html",          "Sold",          True,  None),
    ("analytics.html",     "Analytics",     False, "Insights"),
    ("market_intel.html",  "Market Intel",  False, "Insights"),
    ("deals.html",         "Deals",         False, "Insights"),
    ("quality.html",       "Quality",       False, "Insights"),
    ("price_review.html",  "Pricing",       False, "Insights"),
    ("repricing.html",     "Repricing Agent", False, "Insights"),
    ("title_review.html",  "Titles",        False, "Insights"),
    ("scan.html",          "Scanner",       False, "Tools"),
    ("reddit.html",        "Reddit",        False, "Cross-post"),
    ("craigslist.html",    "Craigslist",    False, "Cross-post"),
    ("google_feed.xml",    "Google Feed",   False, "Cross-post"),
]
_ADMIN_PAGES = {p for p, _, public, _ in _NAV_ITEMS if not public}


def _nav_link_html(active_page: str, mobile: bool = False) -> str:
    """Render the nav.
    Desktop: flat links for top-level + dropdown menus for grouped items.
    Mobile (drawer): everything as a flat list (drawer scrolls).
    """
    if mobile:
        # Drawer: flat list, group items get a small section header
        out = []
        last_group = None
        for href, label, public, group in _NAV_ITEMS:
            is_external = href.endswith(".xml")
            is_active   = (href == active_page)
            cls_parts   = []
            if is_active: cls_parts.append("active")
            if not public: cls_parts.append("admin-only")
            cls = f' class="{" ".join(cls_parts)}"' if cls_parts else ""
            attrs = ' target="_blank" rel="noopener"' if is_external else ""
            if not public: attrs += ' data-admin="1"'
            if group and group != last_group:
                out.append(f'<div class="drawer-group" data-admin="1">{group}</div>')
                last_group = group
            out.append(f'<a href="{href}"{cls}{attrs}>{label}</a>')
        return "\n".join(out)

    # Desktop: build top-level links + grouped dropdowns, preserving order of first appearance
    rendered_groups: set[str] = set()
    out = []
    for href, label, public, group in _NAV_ITEMS:
        is_external = href.endswith(".xml")
        is_active   = (href == active_page)
        if group is None:
            cls_parts = ["nav-link"]
            if is_active: cls_parts.append("active")
            if not public: cls_parts.append("admin-only")
            cls = ' class="' + " ".join(cls_parts) + '"'
            attrs = ' target="_blank" rel="noopener"' if is_external else ""
            if not public: attrs += ' data-admin="1"'
            out.append(f'<a href="{href}"{cls}{attrs}>{label}</a>')
            continue
        if group in rendered_groups:
            continue
        rendered_groups.add(group)
        # Build the dropdown for this group
        items = [it for it in _NAV_ITEMS if it[3] == group]
        group_is_admin = all(not it[2] for it in items)
        any_active     = any(it[0] == active_page for it in items)
        btn_cls = "nav-dropdown-trigger" + (" active" if any_active else "")
        admin_attr = ' data-admin="1"' if group_is_admin else ''
        items_html = []
        for h2, lbl2, public2, _ in items:
            ext  = ' target="_blank" rel="noopener"' if h2.endswith(".xml") else ""
            adm  = ' data-admin="1"' if not public2 else ''
            a_active = ' class="active"' if h2 == active_page else ''
            items_html.append(f'<a href="{h2}"{a_active}{adm}{ext}>{lbl2}</a>')
        out.append(f'''
        <div class="nav-dropdown"{admin_attr}>
          <button class="{btn_cls}" type="button" aria-haspopup="menu" aria-expanded="false" onclick="toggleNavDropdown(this, event)">
            {group}
            <svg width="10" height="10" viewBox="0 0 12 8" fill="none" aria-hidden="true"><path d="M1 1l5 5 5-5" stroke="currentColor" stroke-width="1.8"/></svg>
          </button>
          <div class="nav-dropdown-menu" role="menu">{''.join(items_html)}</div>
        </div>''')
    return "\n".join(out)


def html_shell(title: str, body: str, extra_head: str = "", active_page: str = "index.html") -> str:
    nav_html_desktop = _nav_link_html(active_page, mobile=False)
    nav_html_mobile  = _nav_link_html(active_page, mobile=True)
    updated = datetime.now(timezone.utc).strftime('%b %d, %Y · %H:%M UTC')

    # Admin gate values
    admin_hashes_json = json.dumps(load_admin_hashes())
    admin_salt = _ADMIN_SALT
    is_admin_page = "true" if active_page in _ADMIN_PAGES else "false"
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
  <meta name="theme-color" content="#0a0a0a">
  <meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate">
  <meta http-equiv="Pragma" content="no-cache">
  <meta http-equiv="Expires" content="0">
  <meta name="google-site-verification" content="_qz1v8JzZrRv8CPXWv1al3nMP4oyoWRnG-Pc-guRl5Q" />
  <link rel="manifest" href="manifest.webmanifest">
  <link rel="apple-touch-icon" href="data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 180 180'><rect width='180' height='180' rx='28' fill='%230a0a0a'/><text x='90' y='124' font-family='Bebas Neue, sans-serif' font-size='120' font-weight='700' fill='%23d4af37' text-anchor='middle'>H</text></svg>">
  <meta name="apple-mobile-web-app-capable" content="yes">
  <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
  <meta name="apple-mobile-web-app-title" content="Harpua2001">
  <script>
    // Apply saved theme synchronously to avoid flash-of-wrong-theme.
    (function() {{
      try {{
        var t = localStorage.getItem('h2k_theme');
        if (t && t !== 'dark') document.documentElement.setAttribute('data-theme', t);
      }} catch(e) {{}}
    }})();
    // Admin gate constants (populated at build time)
    window.__ADMIN_HASHES = {admin_hashes_json};
    window.__ADMIN_SALT   = '{admin_salt}';
    window.__IS_ADMIN_PAGE = {is_admin_page};
    // Early body class: if a stored token matches any embedded hash, mark body admin
    (function() {{
      try {{
        var stored = localStorage.getItem('h2k_admin_token');
        var ok = stored && window.__ADMIN_HASHES.indexOf(stored) !== -1;
        document.documentElement.classList.toggle('pre-is-admin', !!ok);
      }} catch(e) {{}}
    }})();
  </script>
  <style>
    /* Use html.pre-is-admin → body.is-admin (we mirror in the body-load script).
       Until then, on admin pages, show the gate over content immediately. */
    html:not(.pre-is-admin) body.admin-page main {{ filter: blur(14px); pointer-events: none; user-select: none; }}
  </style>
  <title>{title}</title>
  {_CDN_HEAD}
  <style>{_BASE_CSS}</style>
  {extra_head}
</head>
<body class="{'admin-page' if active_page in _ADMIN_PAGES else ''}">
  <header class="app-header">
    <div class="app-header-inner">
      <a href="index.html" class="brand">
        <div class="brand-mark">H</div>
        <div class="brand-text">
          <div class="brand-name">{SELLER_NAME}</div>
          <div class="brand-tag">Sports &amp;<br>Pokemon<br>Cards</div>
        </div>
      </a>
      <nav class="nav-links">{nav_html_desktop}</nav>
      <div style="position:relative;">
        <button class="btn-theme" id="theme-picker-btn" onclick="toggleThemePicker(event)" title="Pick a theme" aria-label="Pick a theme" aria-haspopup="menu" aria-expanded="false">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="13.5" cy="6.5" r="1.5" fill="currentColor"/><circle cx="17.5" cy="10.5" r="1.5" fill="currentColor"/><circle cx="8.5" cy="7.5" r="1.5" fill="currentColor"/><circle cx="6.5" cy="12.5" r="1.5" fill="currentColor"/><path d="M12 2C6.49 2 2 6.49 2 12s4.49 10 10 10c1 0 1.5-.5 1.5-1.5 0-.39-.13-.74-.36-1.05-.23-.31-.36-.66-.36-1.05 0-1 .5-1.5 1.5-1.5h1.79c2.69 0 4.97-2.04 4.97-4.94 0-5.51-4.48-9.96-10.04-9.96z"/></svg>
        </button>
        <div class="theme-popover" id="theme-popover" role="menu"></div>
      </div>
      <button class="btn-install" id="install-app-btn" onclick="installApp()" style="display:none;" title="Install as app">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><path d="M12 3v12m-5-5 5 5 5-5M5 21h14"/></svg>
        Install
      </button>
      <button class="btn-login"  onclick="openGate()" title="Sign in to manage listings">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="11" width="18" height="11" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg>
        Sign in
      </button>
      <button class="btn-logout" onclick="adminLogout()" title="Sign out">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4M16 17l5-5-5-5M21 12H9"/></svg>
        Sign out
      </button>
      <button class="btn-refresh" id="nav-refresh-btn" onclick="navRebuild()">Refresh</button>
      <button class="menu-toggle" onclick="openDrawer()" aria-label="Open menu">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="4" y1="7" x2="20" y2="7"/><line x1="4" y1="12" x2="20" y2="12"/><line x1="4" y1="17" x2="20" y2="17"/></svg>
      </button>
    </div>
  </header>

  <div class="drawer-backdrop" id="drawer-backdrop" onclick="closeDrawer()"></div>
  <aside class="drawer" id="drawer" aria-label="Mobile navigation">
    <div class="drawer-head">
      <div>
        <div class="brand-name" style="font-family:'Bebas Neue',sans-serif;font-size:24px;letter-spacing:.04em;">{SELLER_NAME}</div>
        <div class="brand-tag" style="font-size:10px;letter-spacing:.22em;text-transform:uppercase;color:var(--gold);font-weight:600;margin-top:4px;">eBay Storefront</div>
      </div>
      <button class="drawer-close" onclick="closeDrawer()" aria-label="Close menu">
        <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2"><line x1="6" y1="6" x2="18" y2="18"/><line x1="6" y1="18" x2="18" y2="6"/></svg>
      </button>
    </div>
    {nav_html_mobile}
    <div class="drawer-foot">
      <button class="btn-refresh" id="drawer-install-btn" onclick="installApp()" style="display:none;width:100%;padding:14px;font-size:13px;background:transparent;color:var(--text);border:1px solid var(--border-mid);margin-bottom:8px;">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" style="vertical-align:middle;margin-right:6px;"><path d="M12 3v12m-5-5 5 5 5-5M5 21h14"/></svg>
        Install as app
      </button>
      <button class="btn-refresh drawer-signin"  onclick="openGate()"     style="width:100%;padding:14px;font-size:13px;background:transparent;color:var(--text);border:1px solid var(--border-mid);margin-bottom:8px;">
        Sign in
      </button>
      <button class="btn-refresh drawer-signout" onclick="adminLogout()"  style="width:100%;padding:14px;font-size:13px;background:transparent;color:var(--text);border:1px solid var(--border-mid);margin-bottom:8px;display:none;">
        Sign out
      </button>
      <button class="btn-refresh" onclick="navRebuild()">Refresh Site</button>
    </div>
  </aside>

  <div id="nav-toast" class="toast"></div>

  <div class="gate-overlay" id="gate-overlay" role="dialog" aria-modal="true" aria-labelledby="gate-title">
    <div class="gate-card">
      <h2 id="gate-title">Owner Access</h2>
      <div class="gate-sub">Enter the passcode to view management tools (Quality, Pricing, Titles, Reddit, Craigslist).</div>
      <form onsubmit="event.preventDefault(); adminAttempt();">
        <input type="password" id="gate-input" autocomplete="current-password" placeholder="••••••••" autofocus>
        <div class="gate-error" id="gate-error">&nbsp;</div>
        <div class="gate-actions">
          <button type="button" class="btn btn-ghost" onclick="closeGate()">Cancel</button>
          <button type="submit" class="btn btn-gold">Unlock</button>
        </div>
      </form>
      <div class="gate-storefront-msg">Browsing? Listings + Sold are public — no passcode needed.</div>
    </div>
  </div>

  <main>
    {body}
  </main>

  <footer class="app-footer">
    Updated {updated} · <a href="{STORE_URL}" class="seller-link" target="_blank" rel="noopener">{SELLER_NAME} on eBay</a>
  </footer>

  {_CDN_FOOT}
  <script>
    // ---- ADMIN GATE ----
    (function bootstrapAdmin() {{
      // Mirror html class onto body so CSS selectors targeting body.is-admin work
      if (document.documentElement.classList.contains('pre-is-admin')) {{
        document.body.classList.add('is-admin');
      }}
      if (window.__IS_ADMIN_PAGE) {{
        document.body.classList.add('admin-page');
        if (!document.body.classList.contains('is-admin')) {{
          // No valid token → force the gate open and block content
          openGate();
        }}
      }}
    }})();

    async function _sha256Hex(s) {{
      const buf = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(s));
      return Array.from(new Uint8Array(buf)).map(b => b.toString(16).padStart(2, '0')).join('');
    }}
    window.openGate = function() {{
      const o = document.getElementById('gate-overlay');
      if (o) o.classList.add('open');
      setTimeout(() => document.getElementById('gate-input')?.focus(), 50);
    }};
    window.closeGate = function() {{
      // On admin pages, can't close without authing — bounce to home instead
      if (window.__IS_ADMIN_PAGE && !document.body.classList.contains('is-admin')) {{
        const home = location.pathname.includes('/items/') ? '../index.html' : 'index.html';
        location.href = home;
        return;
      }}
      document.getElementById('gate-overlay')?.classList.remove('open');
      const err = document.getElementById('gate-error'); if (err) err.textContent = ' ';
      const inp = document.getElementById('gate-input'); if (inp) inp.value = '';
    }};
    window.adminAttempt = async function() {{
      const inp = document.getElementById('gate-input');
      const err = document.getElementById('gate-error');
      const v = (inp.value || '').trim();
      if (!v) return;
      const hash = await _sha256Hex(window.__ADMIN_SALT + v);
      if (window.__ADMIN_HASHES.indexOf(hash) !== -1) {{
        try {{ localStorage.setItem('h2k_admin_token', hash); }} catch(e) {{}}
        document.body.classList.add('is-admin');
        document.documentElement.classList.add('pre-is-admin');
        document.getElementById('gate-overlay').classList.remove('open');
        showToast('Welcome back. Management tools unlocked.');

        // Fire-and-forget alert ping (server decides if email is sent)
        try {{
          let did = localStorage.getItem('h2k_device_id');
          if (!did) {{
            did = (crypto.randomUUID && crypto.randomUUID()) ||
                  (Date.now() + '-' + Math.random().toString(36).slice(2));
            localStorage.setItem('h2k_device_id', did);
          }}
          fetch('{LAMBDA_BASE}/admin-login', {{
            method: 'POST',
            headers: {{ 'Content-Type': 'application/json' }},
            body: JSON.stringify({{ device_id: did, user_agent: navigator.userAgent }})
          }}).catch(() => {{}});
        }} catch(e) {{}}
      }} else {{
        err.textContent = 'Wrong passcode. Try again.';
        inp.value = '';
        inp.focus();
      }}
    }};
    window.adminLogout = function() {{
      try {{ localStorage.removeItem('h2k_admin_token'); }} catch(e) {{}}
      document.body.classList.remove('is-admin');
      document.documentElement.classList.remove('pre-is-admin');
      if (window.__IS_ADMIN_PAGE) location.href = 'index.html';
      else showToast('Signed out.');
    }};

    // Nav dropdown toggle (touch-friendly; desktop hover also works via CSS)
    window.toggleNavDropdown = function(btn, ev) {{
      ev.stopPropagation();
      const dd = btn.closest('.nav-dropdown');
      const opening = !dd.classList.contains('open');
      // Close any other open dropdowns
      document.querySelectorAll('.nav-dropdown.open').forEach(d => {{
        if (d !== dd) d.classList.remove('open');
      }});
      dd.classList.toggle('open', opening);
      btn.setAttribute('aria-expanded', opening);
    }};
    document.addEventListener('click', (e) => {{
      if (!e.target.closest('.nav-dropdown')) {{
        document.querySelectorAll('.nav-dropdown.open').forEach(d => {{
          d.classList.remove('open');
          d.querySelector('.nav-dropdown-trigger')?.setAttribute('aria-expanded', 'false');
        }});
      }}
    }});

    function openDrawer() {{
      document.getElementById('drawer').classList.add('open');
      document.getElementById('drawer-backdrop').classList.add('open');
      document.body.style.overflow = 'hidden';
    }}
    function closeDrawer() {{
      document.getElementById('drawer').classList.remove('open');
      document.getElementById('drawer-backdrop').classList.remove('open');
      document.body.style.overflow = '';
    }}
    document.querySelectorAll('.drawer a').forEach(a => a.addEventListener('click', closeDrawer));
    document.addEventListener('keydown', e => {{ if (e.key === 'Escape') closeDrawer(); }});

    function showToast(msg) {{
      const t = document.getElementById('nav-toast');
      t.textContent = msg;
      t.classList.add('show');
      clearTimeout(window.__toastTimer);
      window.__toastTimer = setTimeout(() => t.classList.remove('show'), 4000);
    }}

    async function navRebuild() {{
      const btn = document.getElementById('nav-refresh-btn');
      const original = btn.textContent;
      btn.textContent = 'Refreshing…'; btn.disabled = true;
      showToast('Refreshing inventory, prices, sold history, and deals from eBay…');
      try {{
        const resp = await fetch('{LAMBDA_BASE}/rebuild', {{
          method: 'POST', headers: {{ 'Content-Type': 'application/json' }}, body: '{{}}'
        }});
        const data = await resp.json();
        if (data.success) {{
          // Use Lambda's detailed message if present
          const detail = data.message || 'Refresh started';
          showToast(detail + ' · pull-to-refresh in ~2-3 min to see new prices');
        }} else {{
          showToast('Refresh failed: ' + (data.error || 'Unknown'));
        }}
      }} catch (e) {{
        showToast('Refresh request failed: ' + e.message);
      }}
      btn.textContent = original; btn.disabled = false;
    }}

    // Init GLightbox if present anywhere on page
    if (typeof GLightbox !== 'undefined') {{
      window.__lightbox = GLightbox({{ selector: '.glightbox', touchNavigation: true, loop: false }});
    }}

    // ---- eBay revise/reprice lock learning (cross-page) ----
    // When Apply returns errors with codes 240 (content-policy lock) or 291
    // (ended listing), remember them so subsequent visits flag those listings
    // before the user wastes another click.
    window.LockTracker = {{
      KEY: 'h2k_locked_items',
      get() {{
        try {{ return JSON.parse(localStorage.getItem(this.KEY) || '{{}}'); }} catch(e) {{ return {{}}; }}
      }},
      set(map) {{ localStorage.setItem(this.KEY, JSON.stringify(map)); }},
      record(itemId, code, reason) {{
        const m = this.get();
        m[itemId] = {{ code: String(code), reason: String(reason || ''), ts: Date.now() }};
        this.set(m);
      }},
      // Parse Lambda error string like "[240] short :: long"
      parseError(errStr) {{
        const m = String(errStr || '').match(/^\\[(\\d+)\\]/);
        return m ? m[1] : null;
      }},
      // Apply lock badges + uncheck to any cards on the current page
      applyToCards() {{
        const m = this.get();
        document.querySelectorAll('[data-id]').forEach(card => {{
          const id = card.dataset.id;
          if (m[id] && !card.dataset.locked) {{
            card.dataset.locked = m[id].code;
            const cb = card.querySelector('.row-check');
            if (cb) {{ cb.checked = false; cb.disabled = true; cb.title = 'eBay refuses to revise this listing'; }}
            // Add a visual hint if the card has space (no-op if absent)
            if (!card.querySelector('.lock-learned-hint')) {{
              const hint = document.createElement('div');
              hint.className = 'lock-learned-hint';
              hint.style.cssText = 'margin-top:8px;padding:8px 12px;background:rgba(224,123,111,0.08);border:1px dashed rgba(224,123,111,0.35);border-radius:6px;font-size:11px;color:var(--danger);font-weight:600;letter-spacing:.04em;';
              hint.textContent = '🔒 eBay refused a previous revise (code ' + m[id].code + '). Skipped automatically.';
              const target = card.querySelector('.q-body, .pr-info, .info, .tr-bodies') || card;
              target.appendChild(hint);
            }}
          }}
        }});
      }},
      // Hook for Apply functions to call after fetch returns
      consumeErrors(errors) {{
        if (!Array.isArray(errors)) return;
        errors.forEach(e => {{
          const code = this.parseError(e.error || e.msg || e);
          if (code === '240' || code === '291') {{
            const id = e.item_id || e.id;
            if (id) this.record(id, code, e.error || '');
          }}
        }});
        this.applyToCards();
      }}
    }};
    // Apply on every page load
    window.addEventListener('DOMContentLoaded', () => LockTracker.applyToCards());

    // ============ POLISH LAYER ============
    // Skip motion for users who request it
    const __reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

    // Scroll progress bar
    (function () {{
      const bar = document.createElement('div');
      bar.className = 'scroll-progress';
      document.body.appendChild(bar);
      function update() {{
        const h = document.documentElement;
        const top = h.scrollTop || document.body.scrollTop;
        const max = h.scrollHeight - h.clientHeight;
        const pct = max > 0 ? top / max : 0;
        bar.style.transform = 'scaleX(' + pct + ')';
      }}
      window.addEventListener('scroll', update, {{ passive: true }});
      update();
    }})();

    // Staggered card entrance — set --enter-idx so CSS calc() spaces the delays
    (function () {{
      if (__reducedMotion) return;
      const selectors = ['.listing-card','.deal-card','.sold-card','.q-card','.pr-card','.tr-card','.cl-card','.topick-tile','.recent-card','.a-panel'];
      selectors.forEach(sel => {{
        const cards = document.querySelectorAll(sel);
        cards.forEach((c, i) => {{
          if (i < 24) c.style.setProperty('--enter-idx', i);
        }});
      }});
    }})();

    // Count-up animation on stat-card numbers — runs once when each card scrolls into view
    (function () {{
      if (__reducedMotion) return;
      const nums = document.querySelectorAll('.stat-card .num');
      const io = new IntersectionObserver((entries) => {{
        entries.forEach(e => {{
          if (!e.isIntersecting) return;
          const el = e.target;
          const raw = el.textContent || '';
          // Skip anything containing letters (e.g. "5+ yrs", "100%", "★★★★★")
          if (/[a-z%★]/i.test(raw)) {{ io.unobserve(el); return; }}
          const hasDollar = raw.includes('$');
          const target = parseFloat(raw.replace(/[^0-9.\\-]/g, '')) || 0;
          if (target === 0) {{ io.unobserve(el); return; }}
          const isInt = !raw.includes('.');
          const start = performance.now();
          const dur = 900;
          function step(now) {{
            const t = Math.min(1, (now - start) / dur);
            const eased = 1 - Math.pow(1 - t, 3);
            const cur = target * eased;
            const fmt = isInt ? Math.round(cur).toLocaleString() : cur.toFixed(2);
            el.textContent = (hasDollar ? '$' : '') + fmt;
            if (t < 1) requestAnimationFrame(step);
          }}
          requestAnimationFrame(step);
          io.unobserve(el);
        }});
      }}, {{ threshold: 0.4 }});
      nums.forEach(n => io.observe(n));
    }})();

    // Button ripple — track click coordinates as CSS custom properties
    document.addEventListener('click', (e) => {{
      const btn = e.target.closest('.btn-gold');
      if (!btn) return;
      const rect = btn.getBoundingClientRect();
      btn.style.setProperty('--rx', ((e.clientX - rect.left) / rect.width * 100) + '%');
      btn.style.setProperty('--ry', ((e.clientY - rect.top)  / rect.height * 100) + '%');
    }}, {{ passive: true }});

    // Confetti — celebratory micro-interaction on successful Apply
    window.h2kConfetti = function (count = 36) {{
      if (__reducedMotion) return;
      const host = document.createElement('div');
      host.className = 'h2k-confetti-host';
      const colors = ['#d4af37','#f4ce5d','#7fc77a','#6cb0ff','#e07b6f','#b388e0'];
      for (let i = 0; i < count; i++) {{
        const p = document.createElement('div');
        p.className = 'h2k-confetti';
        p.style.left = (Math.random() * 100) + 'vw';
        p.style.background = colors[i % colors.length];
        p.style.setProperty('--cx', (Math.random() * 200 - 100) + 'px');
        p.style.setProperty('--cr', (Math.random() * 720 - 360) + 'deg');
        p.style.animationDelay = (Math.random() * 200) + 'ms';
        host.appendChild(p);
      }}
      document.body.appendChild(host);
      setTimeout(() => host.remove(), 2200);
    }};

    // ---- PWA: register service worker + handle install prompt ----
    if ('serviceWorker' in navigator) {{
      window.addEventListener('load', () => {{
        navigator.serviceWorker.register('sw.js').catch(() => {{}});
      }});
    }}

    let __deferredInstall = null;
    function __toggleInstallBtns(visible) {{
      const headerBtn = document.getElementById('install-app-btn');
      const drawerBtn = document.getElementById('drawer-install-btn');
      if (headerBtn) headerBtn.style.display = visible ? 'inline-flex' : 'none';
      if (drawerBtn) drawerBtn.style.display = visible ? 'inline-flex' : 'none';
    }}
    window.addEventListener('beforeinstallprompt', (e) => {{
      e.preventDefault();
      __deferredInstall = e;
      __toggleInstallBtns(true);
    }});
    window.addEventListener('appinstalled', () => {{
      __deferredInstall = null;
      __toggleInstallBtns(false);
      showToast('Installed. Find Harpua2001 on your home screen.');
    }});
    window.installApp = async function() {{
      if (!__deferredInstall) return;
      __deferredInstall.prompt();
      const choice = await __deferredInstall.userChoice;
      if (choice.outcome === 'accepted') {{
        __deferredInstall = null;
        __toggleInstallBtns(false);
      }}
    }};

    // ---- Theme picker (8 themes) ----
    const THEMES = [
      {{ id: 'dark',       name: 'Dark Luxe',         bg: '#0a0a0a', acc: '#d4af37', meta: '#0a0a0a' }},
      {{ id: 'midnight',   name: 'Midnight Luxury',   bg: '#0f0f0f', acc: '#d4a832', meta: '#0f0f0f' }},
      {{ id: 'crimson',    name: 'Crimson & Charcoal',bg: '#1c1c1e', acc: '#c0282a', meta: '#1c1c1e' }},
      {{ id: 'cream',      name: 'Cream & Navy',      bg: '#f5f0e8', acc: '#c05a1a', meta: '#f5f0e8' }},
      {{ id: 'cobalt',     name: 'White & Cobalt',    bg: '#ffffff', acc: '#1a4fd6', meta: '#ffffff' }},
      {{ id: 'forest',     name: 'Forest & Parchment',bg: '#f4f0e6', acc: '#3a6b2a', meta: '#f4f0e6' }},
      {{ id: 'lavender',   name: 'Lavender & Plum',   bg: '#f5f3fb', acc: '#6b3fa0', meta: '#f5f3fb' }},
      {{ id: 'terracotta', name: 'Sand & Terracotta', bg: '#faf6ef', acc: '#b84c1a', meta: '#faf6ef' }},
    ];
    function applyTheme(id, persist) {{
      const t = THEMES.find(x => x.id === id) || THEMES[0];
      if (t.id === 'dark') document.documentElement.removeAttribute('data-theme');
      else                 document.documentElement.setAttribute('data-theme', t.id);
      if (persist) {{ try {{ localStorage.setItem('h2k_theme', t.id); }} catch(e) {{}} }}
      const meta = document.querySelector('meta[name="theme-color"]');
      if (meta) meta.setAttribute('content', t.meta);
      // Refresh charts to pick up new CSS-var-driven colors
      if (typeof Chart !== 'undefined') {{
        const styles = getComputedStyle(document.documentElement);
        Chart.defaults.color = styles.getPropertyValue('--text-muted').trim() || '#9a9388';
        Chart.defaults.borderColor = styles.getPropertyValue('--border').trim();
        Object.values(Chart.instances || {{}}).forEach(c => {{ try {{ c.update(); }} catch(e) {{}} }});
      }}
      // Update active state in popover
      document.querySelectorAll('.theme-option').forEach(o => o.classList.toggle('active', o.dataset.theme === t.id));
    }}
    function buildThemePicker() {{
      const pop = document.getElementById('theme-popover');
      if (!pop) return;
      const cur = (localStorage.getItem('h2k_theme') || 'dark');
      pop.innerHTML = THEMES.map(t => `
        <button class="theme-option${{t.id === cur ? ' active' : ''}}" data-theme="${{t.id}}" onclick="applyTheme('${{t.id}}', true)">
          <span class="theme-swatch" style="--sw-bg:${{t.bg}}; --sw-acc:${{t.acc}};"><span></span><span></span></span>
          <span class="theme-name">${{t.name}}</span>
          <span class="theme-check">✓</span>
        </button>`).join('');
    }}
    window.toggleThemePicker = function(ev) {{
      ev?.stopPropagation?.();
      const pop = document.getElementById('theme-popover');
      const btn = document.getElementById('theme-picker-btn');
      const open = pop.classList.toggle('open');
      btn.setAttribute('aria-expanded', open);
    }};
    window.applyTheme = applyTheme;
    document.addEventListener('click', (e) => {{
      const pop = document.getElementById('theme-popover');
      if (pop && pop.classList.contains('open') && !pop.contains(e.target) && !e.target.closest('#theme-picker-btn')) {{
        pop.classList.remove('open');
        document.getElementById('theme-picker-btn')?.setAttribute('aria-expanded', false);
      }}
    }});
    buildThemePicker();
    // Sync chart defaults with whatever theme is active right now
    if (typeof Chart !== 'undefined') {{
      const s = getComputedStyle(document.documentElement);
      Chart.defaults.color = s.getPropertyValue('--text-muted').trim() || '#9a9388';
      Chart.defaults.borderColor = s.getPropertyValue('--border').trim();
    }}
  </script>
</body>
</html>"""


# ---------------------------------------------------------------------------
# 1. Listing dashboard (index.html)
# ---------------------------------------------------------------------------

_BASKETBALL_TEAMS = ["lakers", "celtics", "warriors", "bulls", "heat", "knicks", "nets", "76ers", "raptors", "bucks", "cavaliers", "pistons", "pacers", "hawks", "magic", "wizards", "spurs", "rockets", "mavericks", "grizzlies", "pelicans", "thunder", "nuggets", "jazz", "timberwolves", "trail blazers", "kings", "suns", "clippers"]
_BASEBALL_TEAMS   = ["yankees", "red sox", "dodgers", "giants", "cubs", "white sox", "mets", "phillies", "braves", "marlins", "nationals", "orioles", "blue jays", "rays", "guardians", "indians", "twins", "tigers", "royals", "astros", "rangers", "athletics", "angels", "mariners", "cardinals", "brewers", "reds", "pirates", "padres", "rockies", "diamondbacks"]
_FOOTBALL_TEAMS   = ["raiders", "broncos", "cowboys", "49ers", "bears", "packers", "bengals", "chargers", "steelers", "vikings", "rams", "browns", "falcons", "giants", "jets", "patriots", "saints", "seahawks", "buccaneers", "titans", "chiefs", "colts", "eagles", "lions", "ravens", "bills", "dolphins", "texans", "cardinals", "panthers", "redskins", "commanders"]


_GRADE_PATTERNS = [
    (r"\bPSA\s*10\b",          ("PSA 10",  "tag-gold")),
    (r"\bPSA\s*9(?!\.)\b",     ("PSA 9",   "tag-success")),
    (r"\bPSA\s*8(?!\.)\b",     ("PSA 8",   "tag-success")),
    (r"\bBGS\s*9\.5\b",        ("BGS 9.5", "tag-gold")),
    (r"\bBGS\s*10\b",          ("BGS 10",  "tag-gold")),
    (r"\bBGS\s*9(?!\.\d)\b",   ("BGS 9",   "tag-success")),
    (r"\bSGC\s*10\b",          ("SGC 10",  "tag-gold")),
    (r"\bRC\b|\bRookie\b",     ("Rookie",  "tag-gold")),
    (r"\bAuto(graph)?\b",      ("Auto",    "tag-gold")),
    (r"#?(\d+)/(\d+)",         None),       # numbered serial — special handling
    (r"\bPatch\b",             ("Patch",   "tag-success")),
    (r"\bHolo\b",              ("Holo",    "tag-success")),
    (r"\bRefractor\b",         ("Refractor", "tag-success")),
    (r"\bPrizm\b",             ("Prizm",   "tag-success")),
]


def _extract_grade_tags(title: str) -> str:
    """Surface PSA/RC/Auto/etc from titles as visible chips on each card."""
    if not title:
        return ""
    tags = []
    seen = set()
    for pat, value in _GRADE_PATTERNS:
        m = _re.search(pat, title, _re.IGNORECASE)
        if not m:
            continue
        if value is None:  # serial number /XX
            try:
                n, d = m.group(1), m.group(2)
                if int(d) <= 999 and int(d) > 0:
                    label = f"/{d}"
                    if label not in seen:
                        tags.append(f'<span class="tag tag-gold">{label}</span>')
                        seen.add(label)
            except Exception:
                pass
            continue
        label, cls = value
        if label not in seen:
            tags.append(f'<span class="tag {cls}">{label}</span>')
            seen.add(label)
    return "".join(tags[:3])  # cap at 3 to avoid clutter


def _categorize(listing: dict) -> str:
    """Lightweight category derivation from the listing title for filter chips."""
    t = listing["title"].lower()
    if any(w in t for w in ["pokemon", "pikachu", "charizard", "charcadet", "eevee", "holo promo", "mega evolution"]):
        return "Pokemon"
    is_lot = any(w in t for w in [" lot", "lot ", "cards "])
    if any(w in t for w in _BASKETBALL_TEAMS) or "nba" in t or "basketball" in t:
        return "Basketball Lots" if is_lot else "Basketball Singles"
    if any(w in t for w in _BASEBALL_TEAMS) or "mlb" in t or "baseball" in t:
        return "Baseball Lots" if is_lot else "Baseball Singles"
    if any(w in t for w in _FOOTBALL_TEAMS) or "nfl" in t or "football" in t:
        return "Football Lots" if is_lot else "Football Singles"
    if any(w in t for w in ["prizm", "optic", "donruss", "panini", "rookie", "rc "]):
        return "Football Singles"
    return "Other"


# ---------------------------------------------------------------------------
# Multi-source pricing layer — eBay + PriceCharting + PokemonTCG.io
# Cached in pricing_cache.json with a 24h TTL so we don't hammer free-tier APIs.
# ---------------------------------------------------------------------------
PRICING_CACHE_FILE = Path(__file__).parent / "pricing_cache.json"
PRICING_CACHE_TTL  = 24 * 3600

# SportsCardsPro / PriceCharting limits API to 1 call/sec.
_PRICECHARTING_MIN_INTERVAL = 1.05
_pricecharting_last_call_ts = 0.0


def _pricecharting_throttle() -> None:
    """Block until at least 1s has passed since the last PriceCharting API call."""
    global _pricecharting_last_call_ts
    elapsed = _time.time() - _pricecharting_last_call_ts
    if elapsed < _PRICECHARTING_MIN_INTERVAL:
        _time.sleep(_PRICECHARTING_MIN_INTERVAL - elapsed)
    _pricecharting_last_call_ts = _time.time()


# SportsCardsPro card-grade → API field. Higher in list = higher grade priority.
_PRICECHARTING_GRADE_FIELDS = [
    ("psa10",  "manual-only-price"),
    ("bgs10",  "bgs-10-price"),
    ("cgc10",  "condition-17-price"),
    ("sgc10",  "condition-18-price"),
    ("bgs95",  "box-only-price"),
    ("psa9",   "graded-price"),
    ("psa8",   "new-price"),
    ("psa7",   "cib-price"),
    ("raw",    "loose-price"),
]


def _detect_card_grade(title: str) -> str | None:
    """Return one of psa10/psa9/psa8/psa7/bgs10/bgs95/cgc10/sgc10 if title clearly states a grade."""
    t = title.upper()
    if _re.search(r"\bPSA\s*10\b|\bGEM\s*MINT\s*10\b", t):           return "psa10"
    if _re.search(r"\bPSA\s*9\b", t):                                return "psa9"
    if _re.search(r"\bPSA\s*8(\.5)?\b", t):                          return "psa8"
    if _re.search(r"\bPSA\s*7(\.5)?\b", t):                          return "psa7"
    if _re.search(r"\bBGS\s*10\b|\bBLACK\s*LABEL\b", t):             return "bgs10"
    if _re.search(r"\bBGS\s*9\.5\b", t):                             return "bgs95"
    if _re.search(r"\bCGC\s*10\b|\bCGC\s*PRISTINE\b", t):            return "cgc10"
    if _re.search(r"\bSGC\s*10\b", t):                               return "sgc10"
    return None


def _pricing_cache_load() -> dict:
    if not PRICING_CACHE_FILE.exists():
        return {}
    try:
        return json.load(open(PRICING_CACHE_FILE))
    except Exception:
        return {}


def _pricing_cache_save(cache: dict) -> None:
    try:
        PRICING_CACHE_FILE.write_text(json.dumps(cache, indent=2), encoding="utf-8")
    except Exception:
        pass


def fetch_pricecharting(title: str, api_key: str, cache: dict) -> dict | None:
    """SportsCardsPro / PriceCharting API — sports cards, video games, Pokemon.
    Paid subscription required; rate-limited to 1 call/sec by the provider.
    Returns {median, low, high, count, url, matched_title, grade, grades:{...}} or None.
    `grade` is the grade detected from the title (psa10/psa9/.../raw); `median` is
    the price for that grade. `grades` exposes all available grade prices in USD."""
    if not api_key:
        return None
    key = f"pricecharting::{title[:80].lower()}"
    cached = cache.get(key)
    if cached and (_time.time() - cached.get("ts", 0)) < PRICING_CACHE_TTL:
        return cached.get("data")
    try:
        q = _market_query(title)
        _pricecharting_throttle()
        r = requests.get(
            "https://www.pricecharting.com/api/product",
            params={"t": api_key, "q": q},
            timeout=10,
        )
        if r.status_code != 200:
            return None
        d = r.json()
        if d.get("status") != "success":
            cache[key] = {"data": None, "ts": _time.time()}
            return None
        # Extract every grade price returned, in dollars.
        grades: dict[str, float] = {}
        for grade_key, field in _PRICECHARTING_GRADE_FIELDS:
            v = d.get(field)
            if isinstance(v, (int, float)) and v > 0:
                grades[grade_key] = round(v / 100.0, 2)
        if not grades:
            cache[key] = {"data": None, "ts": _time.time()}
            return None
        detected = _detect_card_grade(title)
        # If we detected a grade and have a price for it, use that; otherwise
        # fall back to raw (loose), then to the cheapest known grade price.
        if detected and detected in grades:
            median = grades[detected]
            grade  = detected
        elif "raw" in grades:
            median = grades["raw"]
            grade  = "raw"
        else:
            grade  = min(grades, key=lambda k: grades[k])
            median = grades[grade]
        prices = list(grades.values())
        prod_id = d.get("id", "")
        result = {
            "median":        median,
            "low":           round(min(prices), 2),
            "high":          round(max(prices), 2),
            "count":         len(prices),
            "url":           f"https://www.pricecharting.com/game/{prod_id}" if prod_id else "https://www.pricecharting.com",
            "matched_title": d.get("product-name", ""),
            "grade":         grade,
            "grades":        grades,
        }
        cache[key] = {"data": result, "ts": _time.time()}
        return result
    except Exception:
        return None


def fetch_pokemontcg(title: str, cache: dict, api_key: str = "") -> dict | None:
    """pokemontcg.io API — Pokemon cards. No auth needed (1000/day public);
    free key bumps to 20000/day. Includes TCGplayer + Cardmarket prices.
    Returns {median, low, high, count, url, matched_title} or None."""
    if not any(w in title.lower() for w in ["pokemon", "pikachu", "charizard", "charcadet", "eevee", "mewtwo", "promo", "holo"]):
        return None
    key = f"pokemontcg::{title[:80].lower()}"
    cached = cache.get(key)
    if cached and (_time.time() - cached.get("ts", 0)) < PRICING_CACHE_TTL:
        return cached.get("data")
    try:
        # Extract candidate Pokemon name — first proper-noun-looking words from title
        tokens = [w for w in _re.findall(r"\b[A-Z][a-zA-Z]+\b", title) if w.lower() not in {"pokemon", "card", "holo", "promo", "mega", "evolution", "set", "near", "mint"}]
        name = (tokens[0] if tokens else _market_query(title).split()[0]).strip()
        if not name:
            return None
        headers = {"X-Api-Key": api_key} if api_key else {}
        r = requests.get(
            "https://api.pokemontcg.io/v2/cards",
            params={"q": f'name:"{name}"', "pageSize": 5, "orderBy": "-set.releaseDate"},
            headers=headers,
            timeout=12,
        )
        if r.status_code != 200:
            cache[key] = {"data": None, "ts": _time.time()}
            return None
        data = r.json().get("data", [])
        if not data:
            cache[key] = {"data": None, "ts": _time.time()}
            return None
        # Use the first match; collect TCGplayer market prices across variants
        c = data[0]
        prices = []
        tcg = c.get("tcgplayer", {}).get("prices", {})
        for variant in ("holofoil", "reverseHolofoil", "normal", "1stEditionHolofoil", "1stEditionNormal"):
            v = tcg.get(variant) or {}
            if v.get("market"): prices.append(float(v["market"]))
            elif v.get("mid"):  prices.append(float(v["mid"]))
        # Cardmarket EUR (rough USD conversion not done — show as-is, label EUR)
        cm = c.get("cardmarket", {}).get("prices", {})
        cm_avg = cm.get("averageSellPrice")
        if cm_avg: prices.append(float(cm_avg))
        if not prices:
            cache[key] = {"data": None, "ts": _time.time()}
            return None
        result = {
            "median":        round(sorted(prices)[len(prices) // 2], 2),
            "low":           round(min(prices), 2),
            "high":          round(max(prices), 2),
            "count":         len(prices),
            "url":           (c.get("tcgplayer", {}).get("url") or c.get("cardmarket", {}).get("url") or ""),
            "matched_title": f'{c.get("name", "")} · {c.get("set", {}).get("name", "")}',
        }
        cache[key] = {"data": result, "ts": _time.time()}
        return result
    except Exception:
        return None


def gather_pricing_sources(title: str, cfg: dict, sold_history: list[dict],
                           ebay_market: dict | None, cache: dict) -> dict:
    """Aggregate pricing from every available source for one item.
    Returns dict keyed by source name with {median, low, high, count, url, label, freshness}."""
    out = {}
    # 1. eBay active median (already in fetch_market_prices output)
    if ebay_market and ebay_market.get("market_median") is not None:
        out["ebay_active"] = {
            "median":  ebay_market["market_median"],
            "low":     ebay_market.get("market_min"),
            "high":    ebay_market.get("market_max"),
            "count":   ebay_market.get("comp_count", 0),
            "url":     "",
            "label":   "eBay Active",
            "subnote": f"{ebay_market.get('comp_count', 0)} live asking prices",
        }
    # 2. Your sold history match
    sm = _sold_history_match(title, sold_history or [])
    if sm.get("count", 0) > 0:
        out["sold_history"] = {
            "median":  sm["median"],
            "low":     sm.get("min"),
            "high":    sm.get("max"),
            "count":   sm["count"],
            "url":     "sold.html",
            "label":   "Your past sales",
            "subnote": f"{sm['count']} similar items sold (median)",
        }
    # 3. PriceCharting (if API key)
    pc_key = cfg.get("pricecharting_api_key") or os.environ.get("PRICECHARTING_API_KEY", "")
    if pc_key:
        pc = fetch_pricecharting(title, pc_key, cache)
        if pc:
            out["pricecharting"] = {
                "median":  pc["median"],
                "low":     pc.get("low"),
                "high":    pc.get("high"),
                "count":   pc.get("count", 0),
                "url":     pc.get("url", ""),
                "label":   "PriceCharting",
                "subnote": f"loose · {pc.get('matched_title', '')[:50]}",
            }
    # 4. PokemonTCG.io (free, Pokemon only)
    ptcg_key = cfg.get("pokemontcg_api_key") or os.environ.get("POKEMONTCG_API_KEY", "")
    ptcg = fetch_pokemontcg(title, cache, ptcg_key)
    if ptcg:
        out["pokemontcg"] = {
            "median":  ptcg["median"],
            "low":     ptcg.get("low"),
            "high":    ptcg.get("high"),
            "count":   ptcg.get("count", 0),
            "url":     ptcg.get("url", ""),
            "label":   "PokemonTCG.io",
            "subnote": f"TCGplayer · {ptcg.get('matched_title', '')[:50]}",
        }
    return out


def _suggest_price_multi(your_price: float, sources: dict) -> dict:
    """Recommend a list price using all available sources, ranked by reliability.
    Priority: sold_history > pricecharting > pokemontcg > ebay_active*0.95."""
    if "sold_history" in sources and sources["sold_history"]["count"] >= 3:
        ref = sources["sold_history"]["median"]
        basis = "Your past sales"
    elif "pricecharting" in sources:
        ref = sources["pricecharting"]["median"]
        basis = "PriceCharting"
    elif "pokemontcg" in sources:
        ref = sources["pokemontcg"]["median"]
        basis = "PokemonTCG.io"
    elif "ebay_active" in sources and sources["ebay_active"]["count"] >= 3:
        ref = sources["ebay_active"]["median"] * 0.95
        basis = "eBay active (−5%)"
    else:
        return {"price": None, "basis": "no comps"}
    # Round to .99 ending, min $0.99
    if ref >= 1:
        floor_d = int(ref)
        price = floor_d - 0.01 if ref - floor_d < 0.50 else floor_d + 0.99
    else:
        price = 0.99
    price = max(0.99, round(price, 2))
    return {"price": price, "basis": basis, "reference": round(ref, 2)}


def _sold_history_match(listing_title: str, sold_history: list[dict]) -> dict:
    """Find similar items in sold_history.json by token overlap."""
    if not sold_history:
        return {"count": 0}
    # Tokenize, keep meaningful words (len >=4), skip common stopwords
    stop = {"card", "cards", "lot", "pack", "set", "near", "mint", "psa",
            "from", "with", "rookie", "rookies", "card", "draft", "picks"}
    tokens = {w for w in listing_title.lower().split()
              if len(w) >= 4 and w not in stop}
    if not tokens:
        return {"count": 0}
    prices = []
    for s in sold_history:
        s_tokens = {w for w in (s.get("title") or "").lower().split() if len(w) >= 4}
        if len(tokens & s_tokens) >= 2:
            try:
                p = float(s.get("sale_price") or 0)
                if p > 0:
                    prices.append(p)
            except (TypeError, ValueError):
                continue
    if not prices:
        return {"count": 0}
    prices.sort()
    return {
        "count":  len(prices),
        "median": round(prices[len(prices) // 2], 2),
        "min":    round(prices[0], 2),
        "max":    round(prices[-1], 2),
        "avg":    round(sum(prices) / len(prices), 2),
    }


def build_dashboard(listings: list[dict], market: dict | None = None,
                    seller: dict | None = None, pricing: dict | None = None) -> Path:
    import re as _re

    locks = load_locks()
    seller = seller or {}
    # Load full sold history for cross-listing price intelligence
    sold_history = _load_sold_history()

    # Compute stats
    total_value = sum(float(l['price']) for l in listings if l['price'])
    underpriced_count = sum(
        1 for l in listings
        if market and market.get(l["item_id"], {}).get("flag") == "UNDERPRICED"
    )
    overpriced_count = sum(
        1 for l in listings
        if market and market.get(l["item_id"], {}).get("flag") == "OVERPRICED"
    )

    # Annotate + sort by price desc for hero feature
    enriched = []
    for l in listings:
        try:
            price_f = float(l["price"])
        except (ValueError, TypeError):
            price_f = 0.0
        cat = _categorize(l)
        big_pic = _re.sub(r's-l\d+\.jpg', 's-l1600.jpg', l["pic"]) if l["pic"] else ""
        m = market.get(l["item_id"], {}) if market else {}
        enriched.append({**l, "price_f": price_f, "category": cat, "big_pic": big_pic, "market": m})

    # Top Picks strip: top 6 by price with images (compact horizontal scroller)
    hero_pool = [e for e in enriched if e["pic"]]
    hero_pool.sort(key=lambda e: e["price_f"], reverse=True)
    top_picks = hero_pool[:6]
    # "Hot" tier threshold — top 20% by price
    prices_sorted = sorted([e["price_f"] for e in enriched if e["price_f"] > 0], reverse=True)
    hot_threshold = prices_sorted[max(0, int(len(prices_sorted) * 0.2) - 1)] if prices_sorted else 0

    # Build category chip counts
    cat_counts = {}
    for e in enriched:
        cat_counts[e["category"]] = cat_counts.get(e["category"], 0) + 1
    # Order chips: All first, then by count desc
    chip_order = ["All"] + sorted(cat_counts.keys(), key=lambda k: -cat_counts[k])
    chips_html_parts = []
    for cat in chip_order:
        cnt = len(enriched) if cat == "All" else cat_counts.get(cat, 0)
        if cnt == 0 and cat != "All":
            continue
        active = " active" if cat == "All" else ""
        chips_html_parts.append(
            f'<button type="button" class="chip{active}" data-cat="{cat}" onclick="setCategory(this)">{cat} <span class="count">{cnt}</span></button>'
        )
    # Watchlist chip
    chips_html_parts.append(
        '<button type="button" class="chip" data-cat="__watch" onclick="setCategory(this)">'
        '<svg width="13" height="13" viewBox="0 0 24 24" fill="currentColor" style="margin-right:2px;"><path d="M12 21s-7-4.5-9.5-9C.86 8.4 2.7 4 6.5 4c2 0 3.5 1 5.5 3 2-2 3.5-3 5.5-3 3.8 0 5.64 4.4 4 8-2.5 4.5-9.5 9-9.5 9z"/></svg>'
        'Watchlist <span class="count" id="watch-count">0</span></button>'
    )

    # Price range
    prices = [e["price_f"] for e in enriched if e["price_f"] > 0]
    p_min = int((min(prices) if prices else 0) // 1)
    p_max = int(((max(prices) if prices else 100)) + 1)

    # Build cards
    card_html = []
    for e in enriched:
        flag = e["market"].get("flag") if e["market"] else None
        # Pricing-flag badges leak internal analytics to buyers — admin-only
        flag_tag = ""
        if flag == "UNDERPRICED":
            flag_tag = '<span class="tag tag-danger" data-admin="1">Underpriced</span>'
        elif flag == "OVERPRICED":
            flag_tag = '<span class="tag tag-warn" data-admin="1">Overpriced</span>'
        cond_tag = f'<span class="tag">{e["condition"]}</span>' if e["condition"] else ""
        cat_tag  = f'<span class="tag tag-gold">{e["category"]}</span>'
        grade_tags = _extract_grade_tags(e["title"])

        # Build multi-source pricing popover from the aggregated sources dict
        srcs = (pricing or {}).get(e["item_id"], {})
        rows = [("Your price", f"${e['price_f']:.2f}", "currently listed", "")]
        for sk in ("ebay_active", "sold_history", "pricecharting", "pokemontcg"):
            if sk not in srcs:
                continue
            s = srcs[sk]
            val = f"${s['median']:.2f}"
            if s.get("low") is not None and s.get("high") is not None and s["low"] != s["high"]:
                val += f' <span style="color:var(--text-muted);font-weight:400;font-size:11px;">(${s["low"]:.0f}–${s["high"]:.0f})</span>'
            rows.append((s["label"], val, s.get("subnote", ""), s.get("url", "")))
        # Gap vs eBay active
        if "ebay_active" in srcs:
            gap = (e["price_f"] - srcs["ebay_active"]["median"]) / srcs["ebay_active"]["median"] * 100 if srcs["ebay_active"]["median"] else 0
            tone = "var(--success)" if -15 <= gap <= 20 else ("var(--danger)" if gap < -15 else "var(--warning)")
            rows.append(("Gap vs eBay", f'<span style="color:{tone};font-weight:700;">{gap:+.1f}%</span>', "your price vs eBay median", ""))
        # Suggested via multi-source algorithm
        sug = _suggest_price_multi(e["price_f"], srcs)
        if sug.get("price"):
            rows.append(("Suggested list", f'<b style="color:var(--gold);">${sug["price"]:.2f}</b>', f"based on {sug['basis']}", ""))
        rows_html = "".join(
            f'<div class="pp-row"><div class="pp-lbl">{lbl}</div><div class="pp-val">{val}</div><div class="pp-note">{note}{(" · <a href=\"" + url + "\" target=\"_blank\" rel=\"noopener\" style=\"color:var(--gold);\">↗</a>") if url else ""}</div></div>'
            for lbl, val, note, url in rows
        )
        price_pop_html = f'<div class="price-pop" role="dialog" aria-label="Pricing details">{rows_html}</div>'

        # eBay restriction tag (admin-only — buyers don't need to see lock state)
        lock_info = locks.get(e["item_id"])
        lock_tag = ""
        if lock_info:
            code = lock_info.get("code", "")
            label = "Title locked" if code == "240" else ("Ended" if code == "291" else "Locked")
            reason = lock_info.get("reason", "")
            lock_tag = f'<span class="tag tag-danger" data-admin="1" title="{reason}">🔒 {label}</span>'

        # eBay listing URL drives item-page link instead — we want lightbox to open the image, not the page
        item_page = f"items/{e['item_id']}.html"
        ebay_url  = e["url"]
        title_esc = e["title"].replace('"', "&quot;")

        if e["pic"]:
            thumb = (
                f'<a href="{e["big_pic"]}" class="glightbox" data-gallery="store" '
                f'data-title="{title_esc}" data-description="${e["price_f"]:.2f} · {e["condition"] or e["category"]}">'
                f'<img src="{e["pic"]}" alt="{title_esc}" loading="lazy"></a>'
            )
        else:
            thumb = '<div style="height:100%;display:flex;align-items:center;justify-content:center;color:var(--text-dim);font-size:11px;">No image</div>'

        is_hot = "1" if (hot_threshold and e["price_f"] >= hot_threshold) else "0"
        ltype  = e.get("listing_type", "BIN")
        card_html.append(f'''
      <article class="listing-card"
        data-id="{e['item_id']}"
        data-title="{e['title'].lower()}"
        data-price="{e['price_f']:.2f}"
        data-cat="{e['category']}"
        data-flag="{flag or 'NONE'}"
        data-type="{ltype}"
        data-hot="{is_hot}"
        {f'data-locked="{lock_info["code"]}"' if lock_info else ''}>
        <div class="thumb-wrap">
          {thumb}
          <button class="zoom-btn" type="button"
            onclick="event.preventDefault();document.querySelector('article[data-id=&quot;{e['item_id']}&quot;] .glightbox').click();"
            aria-label="Zoom image">
            <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="7"/><path d="m20 20-3-3M9 11h4M11 9v4"/></svg>
          </button>
          <button class="fav-btn" type="button" data-id="{e['item_id']}" onclick="toggleFav(this, event)" aria-label="Favorite">
            <svg viewBox="0 0 24 24"><path d="M12 21s-7-4.5-9.5-9C.86 8.4 2.7 4 6.5 4c2 0 3.5 1 5.5 3 2-2 3.5-3 5.5-3 3.8 0 5.64 4.4 4 8-2.5 4.5-9.5 9-9.5 9z"/></svg>
          </button>
        </div>
        <div class="info">
          <h3><a href="{item_page}">{e['title']}</a></h3>
          <div class="price-wrap">
            <div class="price" tabindex="0" onclick="togglePricePop(this, event)">${e['price_f']:.2f}<span class="price-info-ic" data-admin="1" aria-hidden="true">ⓘ</span></div>
            <div data-admin="1" class="price-pop-wrap">{price_pop_html}</div>
          </div>
          <div class="meta">{grade_tags}{cat_tag}{cond_tag}{flag_tag}{lock_tag}</div>
        </div>
        <div class="actions">
          <a href="{ebay_url}" target="_blank" rel="noopener" class="btn btn-gold">View on eBay</a>
          <a href="{item_page}" class="btn btn-ghost">Details</a>
        </div>
      </article>''')

    # Compact "Top Picks" horizontal scroller — replaces the heavy hero carousel
    hero_html = ""
    if top_picks:
        tiles = []
        for tp in top_picks:
            tiles.append(f'''
            <a href="items/{tp['item_id']}.html" class="topick-tile" title="{tp['title']}">
              <div class="topick-img"><img src="{tp['pic']}" alt="" loading="lazy"></div>
              <div class="topick-price">${tp['price_f']:.2f}</div>
            </a>''')
        hero_html = f'''
    <section class="topicks">
      <div class="topicks-head">
        <div class="eyebrow">Top of the showcase</div>
        <a href="#listing-grid" class="topicks-more" onclick="setTab('hot')">See all hot cards →</a>
      </div>
      <div class="topicks-scroll">{''.join(tiles)}</div>
    </section>
    '''

    extra_css = """
    /* ============ COMPACT TOP-PICKS STRIP ============ */
    .topicks { margin-bottom: 22px; }
    .topicks-head {
      display: flex; justify-content: space-between; align-items: baseline;
      margin-bottom: 10px;
    }
    .topicks-more {
      font-size: 12px; letter-spacing: .08em; text-transform: uppercase;
      color: var(--gold); font-weight: 700; text-decoration: none;
    }
    .topicks-more:hover { color: var(--gold-bright); }
    .topicks-scroll {
      display: flex; gap: 10px; overflow-x: auto;
      padding-bottom: 4px;
      scrollbar-width: thin;
    }
    .topick-tile {
      flex: 0 0 130px;
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: var(--r-md);
      overflow: hidden;
      text-decoration: none; color: inherit;
      transition: transform var(--t-fast), border-color var(--t-fast);
    }
    .topick-tile:hover { transform: translateY(-2px); border-color: var(--border-mid); }
    .topick-img { aspect-ratio: 1/1; background: #111; }
    .topick-img img { width: 100%; height: 100%; object-fit: cover; }
    .topick-price {
      font-family: 'Bebas Neue', sans-serif;
      font-size: 20px; color: var(--gold);
      padding: 6px 10px;
      letter-spacing: .02em;
    }

    /* ============ TAB BAR (Gallery / Hot / BIN / Auctions) ============ */
    .tab-bar {
      display: flex;
      gap: 4px;
      margin-bottom: 14px;
      padding: 4px;
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: var(--r-md);
      overflow-x: auto;
    }
    .tab-btn {
      flex: 1;
      padding: 10px 14px;
      background: transparent;
      color: var(--text-muted);
      border: none;
      border-radius: var(--r-sm);
      font-size: 13px; font-weight: 700;
      letter-spacing: .06em; text-transform: uppercase;
      cursor: pointer;
      transition: all var(--t-fast);
      font-family: inherit;
      white-space: nowrap;
    }
    .tab-btn:hover { color: var(--text); background: var(--surface-2); }
    .tab-btn.active {
      background: linear-gradient(135deg, var(--gold), var(--gold-dim));
      color: var(--brand-fg);
    }
    .tab-btn .tab-count {
      font-family: 'Bebas Neue', sans-serif;
      font-size: 15px;
      opacity: .8;
      margin-left: 4px;
    }

    .hero {
      display: grid;
      grid-template-columns: minmax(0, 2fr) minmax(0, 1fr);
      gap: 18px;
      margin-bottom: 32px;
    }
    .hero-feature {
      position: relative;
      background: linear-gradient(135deg, var(--surface), var(--surface-2));
      border: 1px solid var(--border-mid);
      border-radius: var(--r-xl);
      overflow: hidden;
      display: grid;
      grid-template-columns: 1fr 1fr;
      min-height: 380px;
      box-shadow: var(--shadow-lg), 0 0 0 1px var(--border-hi) inset;
    }
    .hero-feature::before {
      content: ''; position: absolute; inset: 0;
      background: radial-gradient(600px 400px at 100% 0%, rgba(212,175,55,.16), transparent 60%);
      pointer-events: none;
    }
    .hero-image-wrap {
      position: relative;
      background: #000;
      overflow: hidden;
      min-height: 360px;
    }
    .hero-image-wrap img {
      width: 100%; height: 100%;
      object-fit: cover;
      transition: transform 600ms cubic-bezier(.4,0,.2,1);
    }
    .hero-feature:hover .hero-image-wrap img { transform: scale(1.05); }
    .hero-tag {
      position: absolute; top: 16px; left: 16px;
      padding: 6px 12px;
      background: linear-gradient(135deg, var(--gold), var(--gold-dim));
      color: var(--hero-tag-fg);
      font-size: 11px; font-weight: 800; letter-spacing: .2em;
      text-transform: uppercase;
      border-radius: var(--r-sm);
      z-index: 2;
    }
    .hero-body {
      padding: 32px 36px;
      display: flex; flex-direction: column; justify-content: center;
      position: relative; z-index: 1;
    }
    .hero-title {
      font-family: 'Bebas Neue', sans-serif;
      font-size: clamp(28px, 3.5vw, 44px);
      line-height: 1.05; letter-spacing: .015em;
      color: var(--text);
      margin: 8px 0 14px;
    }
    .hero-price {
      font-family: 'Bebas Neue', sans-serif;
      font-size: clamp(36px, 5vw, 56px);
      color: var(--gold);
      line-height: 1;
      margin-bottom: 14px;
      text-shadow: 0 0 32px rgba(212,175,55,.3);
    }
    .hero-meta { display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 22px; }
    .hero-actions { display: flex; gap: 10px; flex-wrap: wrap; }
    .hero-actions .btn { padding: 12px 24px; font-size: 13px; }

    .hero-runners {
      display: flex; flex-direction: column; gap: 12px;
    }
    .hero-runner {
      display: flex; gap: 14px; align-items: stretch;
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: var(--r-lg);
      padding: 12px;
      transition: all var(--t-fast);
    }
    .hero-runner:hover {
      border-color: var(--border-mid);
      transform: translateX(-2px);
    }
    .hero-runner img {
      width: 76px; height: 76px;
      object-fit: cover;
      border-radius: var(--r-sm);
      flex-shrink: 0;
    }
    .hero-runner-meta { display: flex; flex-direction: column; justify-content: center; min-width: 0; }
    .hero-runner-title {
      font-size: 13px; font-weight: 600; color: var(--text);
      line-height: 1.3;
      display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical;
      overflow: hidden;
    }
    .hero-runner-price {
      font-family: 'Bebas Neue', sans-serif;
      font-size: 22px; color: var(--gold);
      margin-top: 4px;
      letter-spacing: .02em;
    }
    @media (max-width: 980px) {
      .hero { grid-template-columns: 1fr; }
      .hero-feature { grid-template-columns: 1fr; min-height: auto; }
      .hero-image-wrap { aspect-ratio: 16/10; min-height: 0; }
      .hero-runners { flex-direction: row; overflow-x: auto; padding-bottom: 4px; }
      .hero-runner { flex: 0 0 260px; }
    }
    @media (max-width: 540px) {
      .hero-body { padding: 22px; }
      .hero-feature { border-radius: var(--r-lg); }
    }

    /* ============ TRUST PANEL ============ */
    .trust-panel {
      display: grid;
      grid-template-columns: repeat(4, 1fr);
      gap: 0;
      margin-bottom: 28px;
      background: linear-gradient(135deg, var(--surface), var(--surface-2));
      border: 1px solid var(--border-mid);
      border-radius: var(--r-lg);
      overflow: hidden;
      position: relative;
    }
    .trust-panel::before {
      content: ''; position: absolute; inset: 0; pointer-events: none;
      background: radial-gradient(600px 200px at 50% 0%, rgba(212,175,55,.08), transparent 60%);
    }
    .trust-block {
      padding: 18px 16px;
      text-align: center;
      border-right: 1px solid var(--border);
      text-decoration: none; color: inherit;
      transition: background var(--t-fast);
      position: relative; z-index: 1;
    }
    .trust-block:last-child { border-right: none; }
    .trust-block:hover { background: rgba(212,175,55,.05); }
    .trust-num {
      font-family: 'Bebas Neue', sans-serif;
      font-size: 36px; line-height: 1;
      color: var(--gold);
      letter-spacing: .02em;
    }
    .trust-num-sub { font-size: 18px; color: var(--text-muted); margin-left: 2px; }
    .trust-stars {
      font-size: 22px;
      color: var(--gold);
      letter-spacing: .05em;
      line-height: 1;
    }
    .trust-lbl {
      font-size: 10px; letter-spacing: .18em; text-transform: uppercase;
      color: var(--text-muted); font-weight: 600;
      margin-top: 6px;
    }
    .trust-cta .trust-num { font-size: 24px; }
    .trust-cta:hover .trust-lbl { color: var(--gold); }
    @media (max-width: 640px) {
      .trust-panel { grid-template-columns: repeat(2, 1fr); }
      .trust-block:nth-child(2) { border-right: none; }
      .trust-block:nth-child(1), .trust-block:nth-child(2) { border-bottom: 1px solid var(--border); }
      .trust-num { font-size: 28px; }
    }

    /* ============ HERO CAROUSEL ============ */
    .hero-carousel { position: relative; }
    .hero-slide { display: none; }
    .hero-slide.active { display: grid; }
    .hero-slide.fade-in { animation: heroFade 600ms cubic-bezier(.4,0,.2,1); }
    @keyframes heroFade { from { opacity: 0; transform: scale(0.99); } to { opacity: 1; transform: scale(1); } }
    .hero-dots {
      position: absolute; bottom: 14px; left: 50%; transform: translateX(-50%);
      display: flex; gap: 8px; z-index: 5;
    }
    .hero-dot {
      width: 8px; height: 8px;
      border-radius: 50%;
      background: rgba(255,255,255,.25);
      border: none;
      cursor: pointer;
      transition: all var(--t-fast);
      padding: 0;
    }
    .hero-dot.active { background: var(--gold); width: 24px; border-radius: 4px; }

    /* ============ RECENTLY VIEWED ============ */
    .recent-strip {
      display: none;
      margin-bottom: 28px;
    }
    .recent-strip.show { display: block; }
    .recent-head {
      display: flex; justify-content: space-between; align-items: baseline;
      margin-bottom: 12px;
    }
    .recent-head h3 {
      font-family: 'Bebas Neue', sans-serif;
      font-size: 22px; letter-spacing: .03em;
      color: var(--text);
    }
    .recent-clear {
      font-size: 11px; letter-spacing: .12em; text-transform: uppercase;
      color: var(--text-muted); cursor: pointer;
      background: none; border: none; font-family: inherit; font-weight: 600;
    }
    .recent-clear:hover { color: var(--gold); }
    .recent-scroll {
      display: flex; gap: 12px;
      overflow-x: auto;
      padding-bottom: 4px;
      scrollbar-width: thin;
    }
    .recent-card {
      flex: 0 0 200px;
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: var(--r-md);
      overflow: hidden;
      text-decoration: none; color: inherit;
      transition: all var(--t-fast);
    }
    .recent-card:hover { border-color: var(--border-mid); transform: translateY(-2px); }
    .recent-card-img {
      width: 100%; height: 140px;
      object-fit: cover;
      background: #111;
      display: block;
    }
    .recent-card-body { padding: 10px 12px; }
    .recent-card-title {
      font-size: 12px; line-height: 1.3; color: var(--text);
      display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden;
      margin-bottom: 4px;
    }
    .recent-card-price {
      font-family: 'Bebas Neue', sans-serif;
      font-size: 18px; color: var(--gold); letter-spacing: .02em;
    }

    /* ============ SHARE BUTTON ============ */
    .share-btn {
      display: inline-flex; align-items: center; gap: 6px;
      padding: 7px 12px;
      background: transparent;
      border: 1px solid var(--border);
      color: var(--text-muted);
      border-radius: var(--r-sm);
      font-size: 11px; letter-spacing: .14em; text-transform: uppercase; font-weight: 700;
      cursor: pointer;
      font-family: inherit;
    }
    .share-btn:hover { color: var(--gold); border-color: var(--border-mid); }
    """

    # Trust panel
    trust_html = ""
    if seller and seller.get("feedback_score"):
        try:
            fb_score = int(seller["feedback_score"])
            pos_pct  = float(seller.get("positive_pct", "0"))
        except (ValueError, TypeError):
            fb_score, pos_pct = 0, 0.0
        years = seller.get("member_years", 0)
        member_since = seller.get("member_since", "")
        # Star rating: ★ ★ ★ ★ ★ scaled to positive_pct
        stars_full = int(round(pos_pct / 20))
        stars_html = "★" * stars_full + "☆" * (5 - stars_full)
        trust_html = f'''
    <section class="trust-panel">
      <a href="{STORE_URL}" target="_blank" rel="noopener" class="trust-block">
        <div class="trust-num">{fb_score:,}</div>
        <div class="trust-lbl">Feedback Score</div>
      </a>
      <div class="trust-block">
        <div class="trust-stars">{stars_html}</div>
        <div class="trust-lbl">{pos_pct:g}% Positive</div>
      </div>
      <div class="trust-block">
        <div class="trust-num">{years}<span class="trust-num-sub">+ yrs</span></div>
        <div class="trust-lbl">Since {member_since}</div>
      </div>
      <a href="{STORE_URL}" target="_blank" rel="noopener" class="trust-block trust-cta">
        <div class="trust-num">eBay</div>
        <div class="trust-lbl">View Verified Profile →</div>
      </a>
    </section>'''

    body = f"""
    {hero_html}

    <div class="stat-grid">
      <!-- Public-facing buyer-trust signals (hidden when admin signed in — admin sees their own KPIs below) -->
      <button class="stat-card linked" data-public="1" type="button" onclick="filterByKPI('all', this)">
        <div class="num">{len(listings)}</div>
        <div class="lbl">Cards in Stock</div>
      </button>
      <div class="stat-card" data-public="1">
        <div class="num">1<span style="font-size:18px;color:var(--text-muted);">d</span></div>
        <div class="lbl">Ship Time</div>
      </div>
      <div class="stat-card" data-public="1">
        <div class="num">Free</div>
        <div class="lbl">Combined Shipping (2+)</div>
      </div>
      <!-- Admin-only inventory KPIs (hidden from public — they're internal strategy data) -->
      <button class="stat-card linked" type="button" data-admin="1" onclick="filterByKPI('all', this)">
        <div class="num">{len(listings)}</div>
        <div class="lbl">Active Listings</div>
      </button>
      <button class="stat-card linked" type="button" data-admin="1" onclick="filterByKPI('value', this)">
        <div class="num">${total_value:,.0f}</div>
        <div class="lbl">Inventory Value</div>
      </button>
      <button class="stat-card linked" type="button" data-admin="1" onclick="filterByKPI('underpriced', this)">
        <div class="num {'danger' if underpriced_count else ''}">{underpriced_count}</div>
        <div class="lbl">Underpriced</div>
      </button>
      <button class="stat-card linked" type="button" data-admin="1" onclick="filterByKPI('overpriced', this)">
        <div class="num {'warning' if overpriced_count else ''}">{overpriced_count}</div>
        <div class="lbl">Overpriced</div>
      </button>
    </div>

    {trust_html}

    <section class="section-head">
      <div>
        <div class="eyebrow">Browse the inventory</div>
        <h2 class="section-title">The <span class="accent">Showcase</span></h2>
      </div>
      <div class="size-toggle">
        <span class="lbl-txt">View</span>
        <button class="size-btn" data-size="small" onclick="setSize('small', this)">S</button>
        <button class="size-btn active" data-size="medium" onclick="setSize('medium', this)">M</button>
        <button class="size-btn" data-size="large" onclick="setSize('large', this)">L</button>
        <button class="size-btn" data-size="list" onclick="setSize('list', this)">List</button>
      </div>
    </section>

    <div class="filter-bar">
      <div class="filter-row">
        <input type="text" id="search" class="search-input" placeholder="Search players, sets, years…" oninput="applyFilters()" autocomplete="off">
        <select id="category-select" onchange="setCategoryFromSelect()" style="max-width:200px;">
          {''.join(f'<option value="{c}">{c}</option>' for c in chip_order)}
        </select>
        <select id="sort-filter" onchange="applyFilters()" style="max-width:200px;">
          <option value="default">Sort: Featured</option>
          <option value="price-desc">Price: High → Low</option>
          <option value="price-asc">Price: Low → High</option>
          <option value="title">Title A → Z</option>
        </select>
      </div>
      <div class="filter-row">
        <div class="filter-chips">{''.join(chips_html_parts)}</div>
      </div>
      <div class="filter-row">
        <div class="slider-wrap">
          <div class="slider-labels">
            <span>Price Range</span>
            <span><span class="slider-values" id="price-min-lbl">${p_min}</span> – <span class="slider-values" id="price-max-lbl">${p_max}</span></span>
          </div>
          <div id="price-slider"></div>
        </div>
      </div>
    </div>

    <section class="recent-strip" id="recent-strip">
      <div class="recent-head">
        <h3>Recently Viewed</h3>
        <button class="recent-clear" onclick="clearRecent()">Clear</button>
      </div>
      <div class="recent-scroll" id="recent-scroll"></div>
    </section>

    <div class="tab-bar" role="tablist">
      <button class="tab-btn active" data-tab="gallery" onclick="setTab('gallery')" role="tab">Gallery <span class="tab-count" id="cnt-gallery">{len(enriched)}</span></button>
      <button class="tab-btn"        data-tab="hot"     onclick="setTab('hot')"     role="tab">🔥 Hot <span class="tab-count" id="cnt-hot">0</span></button>
      <button class="tab-btn"        data-tab="bin"     onclick="setTab('bin')"     role="tab">Buy It Now <span class="tab-count" id="cnt-bin">0</span></button>
      <button class="tab-btn"        data-tab="auction" onclick="setTab('auction')" role="tab">Auctions <span class="tab-count" id="cnt-auction">0</span></button>
    </div>

    <div id="results-meta" style="display:flex;align-items:center;justify-content:space-between;gap:12px;font-size:12px;color:var(--text-muted);margin-bottom:14px;letter-spacing:.08em;text-transform:uppercase;font-weight:600;flex-wrap:wrap;">
      <div>Showing <span id="visible-count">{len(enriched)}</span> of {len(enriched)} listings</div>
      <button class="share-btn" onclick="shareFilters()" title="Copy a link with these filters applied">
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 12v8a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-8M16 6l-4-4-4 4M12 2v13"/></svg>
        Share filters
      </button>
    </div>

    <div id="no-results" class="empty-state">
      <svg class="empty-state-icon" viewBox="0 0 64 64" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
        <rect x="10" y="14" width="44" height="36" rx="4"/>
        <circle cx="20" cy="24" r="3" fill="currentColor"/>
        <path d="M10 42l12-12 8 8 8-8 16 16"/>
        <line x1="48" y1="56" x2="58" y2="58" stroke-width="3" stroke-linecap="round" opacity=".4"/>
        <line x1="6" y1="58" x2="20" y2="56"  stroke-width="3" stroke-linecap="round" opacity=".4"/>
      </svg>
      <div class="empty-state-title">No matches</div>
      <div class="empty-state-sub">Try widening the price range, switching tabs, or clearing the search box. The card catalog updates every 4 hours automatically.</div>
    </div>

    <div class="grid" id="listing-grid" data-size="medium">
      {''.join(card_html)}
    </div>

    <script>
      const PRICE_MIN_INIT = {p_min};
      const PRICE_MAX_INIT = {p_max};
      let activeCat = 'All';
      let activeFlag = null;     // null | 'UNDERPRICED' | 'OVERPRICED'
      let activeTab  = 'gallery';// 'gallery' | 'hot' | 'bin' | 'auction'
      let priceRange = [PRICE_MIN_INIT, PRICE_MAX_INIT];

      // Tab switcher — sets activeTab + re-applies filters
      window.setTab = function(tab) {{
        activeTab = tab;
        document.querySelectorAll('.tab-btn').forEach(b => b.classList.toggle('active', b.dataset.tab === tab));
        applyFilters();
        document.getElementById('listing-grid').scrollIntoView({{ behavior: 'smooth', block: 'start' }});
      }};

      // Watchlist (localStorage)
      function getFavs() {{
        try {{ return JSON.parse(localStorage.getItem('h2k_favs') || '[]'); }} catch(e) {{ return []; }}
      }}
      function setFavs(list) {{ localStorage.setItem('h2k_favs', JSON.stringify(list)); }}
      function refreshFavUI() {{
        const favs = getFavs();
        document.querySelectorAll('.fav-btn').forEach(b => {{
          b.classList.toggle('on', favs.includes(b.dataset.id));
        }});
        const wc = document.getElementById('watch-count');
        if (wc) wc.textContent = favs.length;
      }}
      function toggleFav(btn, ev) {{
        ev.preventDefault(); ev.stopPropagation();
        const id = btn.dataset.id;
        let favs = getFavs();
        if (favs.includes(id)) favs = favs.filter(x => x !== id);
        else favs.push(id);
        setFavs(favs);
        refreshFavUI();
        if (activeCat === '__watch') applyFilters();
      }}

      // Size toggle
      function setSize(size, btn) {{
        document.getElementById('listing-grid').dataset.size = size;
        document.querySelectorAll('.size-btn').forEach(b => b.classList.toggle('active', b === btn));
        localStorage.setItem('h2k_size', size);
      }}
      const savedSize = localStorage.getItem('h2k_size');
      if (savedSize) {{
        document.getElementById('listing-grid').dataset.size = savedSize;
        document.querySelectorAll('.size-btn').forEach(b => b.classList.toggle('active', b.dataset.size === savedSize));
      }}

      // Category chips
      function setCategory(btn) {{
        activeCat = btn.dataset.cat;
        document.querySelectorAll('.chip').forEach(c => c.classList.toggle('active', c === btn));
        // Sync the dropdown
        const sel = document.getElementById('category-select');
        if (sel) sel.value = activeCat;
        applyFilters();
      }}
      // Category dropdown
      window.setCategoryFromSelect = function() {{
        const sel = document.getElementById('category-select');
        activeCat = sel.value;
        document.querySelectorAll('.chip').forEach(c => c.classList.toggle('active', c.dataset.cat === activeCat));
        applyFilters();
      }};
      // KPI stat-card click → filter the grid
      window.filterByKPI = function(kind, btn) {{
        document.querySelectorAll('.stat-card.linked').forEach(c => c.classList.toggle('active', c === btn));
        // Reset other filters when clicking a KPI
        activeCat = 'All';
        document.querySelectorAll('.chip').forEach(c => c.classList.toggle('active', c.dataset.cat === 'All'));
        const sel = document.getElementById('category-select');
        if (sel) sel.value = 'All';
        document.getElementById('search').value = '';
        slider.noUiSlider.set([PRICE_MIN_INIT, PRICE_MAX_INIT]);
        const sortSel = document.getElementById('sort-filter');
        if (kind === 'value') {{
          sortSel.value = 'price-desc';
          activeFlag = null;
        }} else if (kind === 'underpriced') {{
          sortSel.value = 'default';
          activeFlag = 'UNDERPRICED';
        }} else if (kind === 'overpriced') {{
          sortSel.value = 'default';
          activeFlag = 'OVERPRICED';
        }} else {{
          sortSel.value = 'default';
          activeFlag = null;
        }}
        applyFilters();
        // Scroll the grid into view after the filter applies
        document.getElementById('listing-grid').scrollIntoView({{ behavior: 'smooth', block: 'start' }});
      }};

      // Price slider
      const slider = document.getElementById('price-slider');
      noUiSlider.create(slider, {{
        start: [PRICE_MIN_INIT, PRICE_MAX_INIT],
        connect: true,
        range: {{ min: PRICE_MIN_INIT, max: PRICE_MAX_INIT }},
        step: 1,
      }});
      slider.noUiSlider.on('update', (values) => {{
        const [lo, hi] = values.map(v => Math.round(parseFloat(v)));
        priceRange = [lo, hi];
        document.getElementById('price-min-lbl').textContent = '$' + lo;
        document.getElementById('price-max-lbl').textContent = '$' + hi;
        applyFilters();
      }});

      // Combined filter logic
      function applyFilters() {{
        const q = document.getElementById('search').value.toLowerCase().trim();
        const sort = document.getElementById('sort-filter').value;
        const grid = document.getElementById('listing-grid');
        const cards = Array.from(grid.querySelectorAll('.listing-card'));
        const favs = getFavs();
        const [lo, hi] = priceRange;

        let visible = 0;
        cards.forEach(c => {{
          const price = parseFloat(c.dataset.price);
          let ok = c.dataset.title.includes(q);
          if (ok && activeCat === '__watch') ok = favs.includes(c.dataset.id);
          else if (ok && activeCat !== 'All')  ok = c.dataset.cat === activeCat;
          if (ok && activeFlag) ok = c.dataset.flag === activeFlag;
          if (ok && activeTab === 'hot')      ok = c.dataset.hot === '1';
          else if (ok && activeTab === 'bin')     ok = c.dataset.type === 'BIN';
          else if (ok && activeTab === 'auction') ok = c.dataset.type === 'Auction';
          if (ok) ok = price >= lo && price <= hi;
          c.style.display = ok ? '' : 'none';
          if (ok) visible++;
        }});

        document.getElementById('visible-count').textContent = visible;
        document.getElementById('no-results').style.display = visible === 0 ? 'block' : 'none';

        const visCards = cards.filter(c => c.style.display !== 'none');
        if (sort === 'price-desc') visCards.sort((a,b) => parseFloat(b.dataset.price) - parseFloat(a.dataset.price));
        else if (sort === 'price-asc')  visCards.sort((a,b) => parseFloat(a.dataset.price) - parseFloat(b.dataset.price));
        else if (sort === 'title')      visCards.sort((a,b) => a.dataset.title.localeCompare(b.dataset.title));
        visCards.forEach(c => grid.appendChild(c));
      }}

      refreshFavUI();

      // ============ TAB COUNTS (initial) ============
      (function initTabCounts() {{
        const cards = document.querySelectorAll('.listing-card');
        const setCnt = (id, n) => {{ const el = document.getElementById(id); if (el) el.textContent = n; }};
        setCnt('cnt-gallery', cards.length);
        setCnt('cnt-hot',     Array.from(cards).filter(c => c.dataset.hot === '1').length);
        setCnt('cnt-bin',     Array.from(cards).filter(c => c.dataset.type === 'BIN').length);
        setCnt('cnt-auction', Array.from(cards).filter(c => c.dataset.type === 'Auction').length);
      }})();

      // ============ PRICE POPOVER ============
      function _openPricePop(priceEl) {{
        const pop = priceEl.parentElement.querySelector('.price-pop');
        if (!pop || pop.classList.contains('open')) return;
        document.querySelectorAll('.price-pop.open').forEach(p => p.classList.remove('open'));
        const rect = priceEl.getBoundingClientRect();
        const POP_W = 280;
        let left = rect.left;
        if (left + POP_W + 12 > window.innerWidth) left = Math.max(8, window.innerWidth - POP_W - 12);
        let top = rect.bottom + 8;
        const POP_EST_H = 260;
        if (top + POP_EST_H > window.innerHeight - 8) top = Math.max(8, rect.top - POP_EST_H - 8);
        pop.style.left = left + 'px';
        pop.style.top  = top  + 'px';
        pop.classList.add('open');
      }}
      window.togglePricePop = function(priceEl, ev) {{
        ev.stopPropagation();
        const pop = priceEl.parentElement.querySelector('.price-pop');
        if (!pop) return;
        if (pop.classList.contains('open')) {{
          pop.classList.remove('open');
        }} else {{
          _openPricePop(priceEl);
        }}
      }};
      // Hover-to-open with a short intent delay (avoids flicker when scanning past)
      (function () {{
        let hoverTimer = null;
        document.querySelectorAll('.price-wrap').forEach(wrap => {{
          const priceEl = wrap.querySelector('.price');
          if (!priceEl) return;
          wrap.addEventListener('mouseenter', () => {{
            clearTimeout(hoverTimer);
            hoverTimer = setTimeout(() => _openPricePop(priceEl), 200);
          }});
          wrap.addEventListener('mouseleave', () => {{ clearTimeout(hoverTimer); }});
        }});
      }})();
      document.addEventListener('click', (e) => {{
        if (!e.target.closest('.price-wrap') && !e.target.closest('.price-pop')) {{
          document.querySelectorAll('.price-pop.open').forEach(p => p.classList.remove('open'));
        }}
      }});
      // Close on scroll/resize so the popover doesn't desync from its anchor
      ['scroll','resize'].forEach(evt => window.addEventListener(evt, () => {{
        document.querySelectorAll('.price-pop.open').forEach(p => p.classList.remove('open'));
      }}, {{ passive: true }}));
      document.addEventListener('keydown', (e) => {{
        if (e.key === 'Escape') {{
          document.querySelectorAll('.price-pop.open').forEach(p => p.classList.remove('open'));
        }}
      }});

      // ============ HERO AUTO-ROTATION ============
      const heroSlides = document.querySelectorAll('.hero-slide');
      const heroDots   = document.querySelectorAll('.hero-dot');
      let heroIdx = 0;
      let heroTimer = null;
      function goToSlide(i) {{
        heroSlides.forEach((s, idx) => {{
          s.classList.toggle('active', idx === i);
          if (idx === i) {{
            s.classList.remove('fade-in'); void s.offsetWidth; s.classList.add('fade-in');
          }}
        }});
        heroDots.forEach((d, idx) => d.classList.toggle('active', idx === i));
        heroIdx = i;
      }}
      function nextSlide() {{ goToSlide((heroIdx + 1) % heroSlides.length); }}
      function pauseHero() {{ if (heroTimer) {{ clearInterval(heroTimer); heroTimer = null; }} }}
      function resumeHero() {{ if (heroSlides.length > 1 && !heroTimer) heroTimer = setInterval(nextSlide, 7000); }}
      window.goToSlide = goToSlide;
      window.pauseHero = pauseHero;
      window.resumeHero = resumeHero;
      resumeHero();

      // ============ RECENTLY VIEWED ============
      function getRecent() {{
        try {{ return JSON.parse(localStorage.getItem('h2k_recent') || '[]'); }} catch(e) {{ return []; }}
      }}
      function clearRecent() {{
        localStorage.removeItem('h2k_recent');
        document.getElementById('recent-strip').classList.remove('show');
      }}
      window.clearRecent = clearRecent;
      function renderRecent() {{
        const recent = getRecent();
        if (!recent.length) return;
        const scroll = document.getElementById('recent-scroll');
        const valid = [];
        recent.forEach(r => {{
          const card = document.querySelector('.listing-card[data-id="' + r.id + '"]');
          if (card) {{
            const img = card.querySelector('img')?.src || '';
            const title = card.querySelector('h3 a')?.textContent || r.title || '';
            const price = card.dataset.price || '0';
            valid.push({{ id: r.id, img, title, price }});
          }}
        }});
        if (!valid.length) return;
        scroll.innerHTML = valid.slice(0, 8).map(v => `
          <a href="items/${{v.id}}.html" class="recent-card">
            <img class="recent-card-img" src="${{v.img}}" alt="${{v.title.replace(/"/g, '&quot;')}}" loading="lazy">
            <div class="recent-card-body">
              <div class="recent-card-title">${{v.title}}</div>
              <div class="recent-card-price">$${{parseFloat(v.price).toFixed(2)}}</div>
            </div>
          </a>`).join('');
        document.getElementById('recent-strip').classList.add('show');
      }}
      renderRecent();

      // ============ URL HASH STATE ============
      function readHash() {{
        const params = new URLSearchParams((location.hash || '').replace(/^#/, ''));
        return {{
          q:    params.get('q')    || '',
          cat:  params.get('cat')  || 'All',
          min:  parseFloat(params.get('min')) || PRICE_MIN_INIT,
          max:  parseFloat(params.get('max')) || PRICE_MAX_INIT,
          sort: params.get('sort') || 'default',
          size: params.get('size') || (localStorage.getItem('h2k_size') || 'medium'),
        }};
      }}
      function writeHash() {{
        const p = new URLSearchParams();
        const q = document.getElementById('search').value.trim();
        if (q) p.set('q', q);
        if (activeCat && activeCat !== 'All') p.set('cat', activeCat);
        if (priceRange[0] !== PRICE_MIN_INIT) p.set('min', priceRange[0]);
        if (priceRange[1] !== PRICE_MAX_INIT) p.set('max', priceRange[1]);
        const sort = document.getElementById('sort-filter').value;
        if (sort !== 'default') p.set('sort', sort);
        const size = document.getElementById('listing-grid').dataset.size;
        if (size && size !== 'medium') p.set('size', size);
        const newHash = p.toString();
        if (newHash !== (location.hash || '').replace(/^#/, '')) {{
          history.replaceState(null, '', newHash ? '#' + newHash : location.pathname);
        }}
      }}
      // Apply hash on load
      (function applyHashOnLoad() {{
        const s = readHash();
        if (s.q) document.getElementById('search').value = s.q;
        if (s.sort) document.getElementById('sort-filter').value = s.sort;
        if (s.size) {{
          document.getElementById('listing-grid').dataset.size = s.size;
          document.querySelectorAll('.size-btn').forEach(b => b.classList.toggle('active', b.dataset.size === s.size));
        }}
        if (s.cat && s.cat !== 'All') {{
          const chip = document.querySelector('.chip[data-cat="' + s.cat + '"]');
          if (chip) {{ document.querySelectorAll('.chip').forEach(c => c.classList.remove('active')); chip.classList.add('active'); activeCat = s.cat; }}
        }}
        if (s.min !== PRICE_MIN_INIT || s.max !== PRICE_MAX_INIT) {{
          slider.noUiSlider.set([s.min, s.max]);
        }}
        applyFilters();
      }})();
      // Hook into existing applyFilters to also write hash
      const origApplyFilters = applyFilters;
      applyFilters = function() {{ origApplyFilters(); writeHash(); }};
      window.applyFilters = applyFilters;

      // ============ SHARE FILTERS ============
      window.shareFilters = async function() {{
        writeHash();
        try {{
          await navigator.clipboard.writeText(location.href);
          showToast('Link copied — paste anywhere to share this exact filtered view.');
        }} catch(e) {{
          showToast('Copy failed. URL: ' + location.href);
        }}
      }};
    </script>"""

    out = OUTPUT_DIR / "index.html"
    out.write_text(html_shell(f"{SELLER_NAME} · Sports & Pokemon Cards", body, extra_head=f"<style>{extra_css}</style>", active_page="index.html"), encoding="utf-8")
    print(f"  Dashboard: {out}")
    return out


# ---------------------------------------------------------------------------
# Steals page (steals.html) — PUBLIC. The user's own listings priced below
# the eBay market median, framed positively for buyers.
# ---------------------------------------------------------------------------

def build_steals_page(listings: list[dict], market: dict) -> Path:
    """Surface UNDERPRICED listings to buyers with a 'Save X% vs market' frame."""
    import re as _re

    steals = []
    for l in listings:
        m = market.get(l["item_id"], {}) if market else {}
        if m.get("flag") != "UNDERPRICED":
            continue
        med = m.get("market_median")
        if not med:
            continue
        try:
            our = float(l["price"])
        except (TypeError, ValueError):
            continue
        if our <= 0 or our >= med:
            continue
        save_pct = round((1 - our / med) * 100, 1)
        save_dollars = round(med - our, 2)
        if save_pct < 15:
            continue   # threshold — only items >=15% below market qualify
        try:
            price_f = float(l["price"])
        except (TypeError, ValueError):
            price_f = 0.0
        big_pic = _re.sub(r's-l\d+\.jpg', 's-l500.jpg', l["pic"]) if l["pic"] else ""
        steals.append({
            **l,
            "price_f":      price_f,
            "big_pic":      big_pic,
            "market_median": med,
            "save_pct":     save_pct,
            "save_dollars": save_dollars,
            "category":     _categorize(l),
            "grade_tags":   _extract_grade_tags(l["title"]),
        })

    steals.sort(key=lambda s: -s["save_pct"])

    total_potential_savings = sum(s["save_dollars"] for s in steals)
    biggest_save_pct = max((s["save_pct"] for s in steals), default=0)

    cards = []
    for s in steals:
        save_pct = s["save_pct"]
        if save_pct >= 35:
            tier = '<span class="badge badge-danger">🔥 STEAL</span>'
        elif save_pct >= 25:
            tier = '<span class="badge badge-warning">DEAL</span>'
        else:
            tier = '<span class="badge badge-success">BARGAIN</span>'

        thumb_html = (
            f'<img src="{s["big_pic"] or s["pic"]}" alt="" loading="lazy">' if s["pic"]
            else '<div style="display:flex;align-items:center;justify-content:center;height:100%;color:var(--text-dim);font-size:11px;">No image</div>'
        )

        cards.append(f'''
      <article class="steal-card">
        <div class="steal-thumb">
          {thumb_html}
          <div class="steal-discount">-{save_pct:.0f}%</div>
        </div>
        <div class="steal-body">
          <div class="steal-meta-row">
            {tier}
            <span class="tag tag-gold">{s["category"]}</span>
            {s["grade_tags"]}
            {f'<span class="tag">{s["condition"]}</span>' if s["condition"] else ''}
          </div>
          <a href="items/{s['item_id']}.html" class="steal-title">{s['title']}</a>
          <div class="steal-sub">Save <b style="color:var(--success);">${s["save_dollars"]:.2f}</b> vs. eBay market median ({s["save_pct"]:.0f}% off)</div>
        </div>
        <div class="steal-price-block">
          <div class="steal-price">${s["price_f"]:.2f}</div>
          <div class="steal-median">market ${s["market_median"]:.2f}</div>
          <a href="{s["url"]}" target="_blank" rel="noopener" class="btn btn-gold" style="padding:9px 16px;font-size:12px;margin-top:8px;">Grab it on eBay →</a>
        </div>
      </article>''')

    if not cards:
        cards_html = '''<div class="empty-state">
          <svg class="empty-state-icon" viewBox="0 0 64 64" fill="none" stroke="currentColor" stroke-width="2"><circle cx="32" cy="32" r="20"/><path d="M22 30l8 8 12-16"/></svg>
          <div class="empty-state-title">Fully priced</div>
          <div class="empty-state-sub">Everything in the store is currently priced at or above market median. Check back — new listings drop here when they're listed below market.</div>
        </div>'''
    else:
        cards_html = "\n".join(cards)

    extra_css = """
    .steal-grid { display: grid; gap: 14px; margin-bottom: 28px; }
    .steal-card {
      display: grid;
      grid-template-columns: 112px 1fr auto;
      gap: 16px;
      background: var(--surface);
      border: 1px solid var(--border);
      border-left: 3px solid var(--success);
      border-radius: var(--r-lg);
      padding: 16px 20px;
      transition: all var(--t-fast);
      align-items: center;
    }
    .steal-card:hover {
      border-color: var(--success);
      box-shadow: 0 12px 28px -10px rgba(127,199,122,.2);
      transform: translateY(-1px);
    }
    .steal-thumb {
      position: relative;
      width: 112px; height: 112px;
      border-radius: var(--r-md);
      overflow: hidden;
      background: var(--surface-3);
    }
    .steal-thumb img { width: 100%; height: 100%; object-fit: cover; }
    .steal-discount {
      position: absolute; top: 8px; right: 8px;
      background: linear-gradient(135deg, #e07b6f, #b54a3e);
      color: #fff;
      font-family: 'Bebas Neue', sans-serif;
      font-size: 17px; letter-spacing: .02em;
      padding: 4px 9px;
      border-radius: var(--r-sm);
      line-height: 1;
      box-shadow: 0 4px 12px -4px rgba(224,123,111,.6);
    }
    .steal-body { min-width: 0; }
    .steal-meta-row { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin-bottom: 8px; }
    .steal-title {
      display: block;
      font-size: 15px; font-weight: 600; color: var(--text);
      line-height: 1.4;
      text-decoration: none;
      margin-bottom: 6px;
    }
    .steal-title:hover { color: var(--gold); }
    .steal-sub { font-size: 13px; color: var(--text-muted); }
    .steal-price-block { text-align: right; flex-shrink: 0; }
    .steal-price {
      font-family: 'Bebas Neue', sans-serif;
      font-size: 34px; line-height: 1;
      color: var(--gold);
      letter-spacing: .02em;
    }
    .steal-median {
      font-size: 12px; color: var(--text-muted);
      text-decoration: line-through;
      margin-top: 4px;
    }
    @media (max-width: 580px) {
      .steal-card { grid-template-columns: 80px 1fr; padding: 14px; gap: 14px; }
      .steal-thumb { width: 80px; height: 80px; }
      .steal-price-block { grid-column: 1 / -1; text-align: left; display: flex; align-items: baseline; gap: 12px; flex-wrap: wrap; }
      .steal-price { font-size: 28px; }
    }
    """

    body = f"""
    <div class="section-head">
      <div>
        <div class="eyebrow">Priced below market</div>
        <h1 class="section-title">Steals &amp; <span class="accent">Bargains</span></h1>
        <div class="section-sub">My own listings priced below the current eBay market median — straight from the live API. Auto-updated every 4 hours. The bigger the % off, the bigger the steal.</div>
      </div>
    </div>

    <div class="stat-grid">
      <div class="stat-card">
        <div class="num">{len(steals)}</div>
        <div class="lbl">Cards Below Market</div>
      </div>
      <div class="stat-card">
        <div class="num">${total_potential_savings:,.0f}</div>
        <div class="lbl">Total Savings on Offer</div>
      </div>
      <div class="stat-card">
        <div class="num">{biggest_save_pct:.0f}<span style="font-size:24px;">%</span></div>
        <div class="lbl">Biggest Discount Today</div>
      </div>
    </div>

    <div class="steal-grid">
      {cards_html}
    </div>
    """

    out = OUTPUT_DIR / "steals.html"
    out.write_text(html_shell(f"Steals · {SELLER_NAME}", body, extra_head=f"<style>{extra_css}</style>", active_page="steals.html"), encoding="utf-8")
    print(f"  Steals page: {out}  ({len(steals)} cards below market)")
    return out


# ---------------------------------------------------------------------------
# Market Intelligence page (market_intel.html) — forward-looking
# ---------------------------------------------------------------------------
MARKET_HISTORY_FILE = Path(__file__).parent / "market_history.json"


def _market_history_load() -> list[dict]:
    if not MARKET_HISTORY_FILE.exists():
        return []
    try:
        return json.load(open(MARKET_HISTORY_FILE))
    except Exception:
        return []


def _market_history_append(entry: dict) -> None:
    history = _market_history_load()
    history.append(entry)
    # Keep last 365 snapshots (~1 year of daily builds)
    history = history[-365:]
    MARKET_HISTORY_FILE.write_text(json.dumps(history, indent=2, default=str), encoding="utf-8")


def build_market_intel_page(listings: list[dict], market: dict, sold: list[dict],
                            deals_data: dict) -> Path:
    """Forward-looking market intelligence:
       - aggregate Deal Hunter query data into segments
       - compare against inventory mix
       - recommend underweighted categories with high market median
       - track market metrics over time via market_history.json
    """
    from datetime import datetime as _dt
    import re as _re

    queries = deals_data.get("queries", [])

    # --- Per-category segment aggregation from deal hunter results ---
    segments: dict[str, dict] = {}
    deals_by_cat: dict[str, list] = {}    # actual deal listings, grouped by category
    queries_by_cat: dict[str, list] = {}  # the search queries that defined this category
    for q in queries:
        cat = q.get("category", "Other")
        seg = segments.setdefault(cat, {"comps": 0, "deals": 0, "prices": [], "queries": 0})
        seg["queries"] += 1
        seg["comps"]   += q.get("comps", 0)
        seg["deals"]   += len(q.get("deals", []))
        if q.get("median"):
            seg["prices"].extend([q["median"]] * max(1, q.get("comps", 1) // 5))
        deals_by_cat.setdefault(cat, []).extend(q.get("deals", []))
        if q.get("q"):
            queries_by_cat.setdefault(cat, []).append(q["q"])
    for cat, seg in segments.items():
        prices = sorted(seg["prices"])
        seg["median"] = round(prices[len(prices) // 2], 2) if prices else 0
        seg["min"]    = round(min(prices), 2) if prices else 0
        seg["max"]    = round(max(prices), 2) if prices else 0
    # Sort deals within each category by discount % desc
    for cat in deals_by_cat:
        deals_by_cat[cat].sort(key=lambda d: -d.get("discount_pct", 0))

    # --- Inventory mix (your current listings) ---
    inventory: dict[str, dict] = {}
    for l in listings:
        cat = _categorize(l)
        inv = inventory.setdefault(cat, {"count": 0, "value": 0.0, "avg": 0.0})
        try:
            p = float(l["price"])
        except (TypeError, ValueError):
            p = 0.0
        inv["count"] += 1
        inv["value"] += p
    for cat, inv in inventory.items():
        inv["avg"] = round(inv["value"] / inv["count"], 2) if inv["count"] else 0

    # --- Sold mix (your historical sales by category) ---
    sold_by_cat: dict[str, dict] = {}
    for s in sold:
        cat = _categorize({"title": s.get("title", "")})
        sb = sold_by_cat.setdefault(cat, {"count": 0, "revenue": 0.0})
        sb["count"]   += 1
        sb["revenue"] += float(s.get("sale_price", 0) or 0)

    # --- Recommendation engine ---
    # Score each category by: market_median × log(buyer_demand) × inventory_gap_factor.
    # High score = high-value market segment where you have low or no presence.
    import math
    recommendations = []
    all_cats = sorted(set(segments.keys()) | set(inventory.keys()) | set(sold_by_cat.keys()))
    for cat in all_cats:
        m_seg = segments.get(cat, {})
        inv   = inventory.get(cat, {"count": 0, "value": 0.0, "avg": 0.0})
        sold_seg = sold_by_cat.get(cat, {"count": 0, "revenue": 0.0})
        median = m_seg.get("median", 0)
        comps  = m_seg.get("comps", 0)
        if median < 1 or comps < 5:
            continue  # not enough signal
        # Inventory gap: 1.5 if no inventory, 1.0 if matches, 0.4 if heavy
        if inv["count"] == 0:
            gap_factor = 2.0
        elif inv["count"] < 3:
            gap_factor = 1.4
        elif inv["count"] < 8:
            gap_factor = 1.0
        else:
            gap_factor = 0.6
        # Demand signal — comps = active buyer interest (more listings = more sellers chasing buyers)
        demand = math.log(comps + 1)
        # Track-record bonus if we've sold in this category before
        track_bonus = 1.0 + min(0.5, sold_seg["count"] * 0.05)
        score = median * demand * gap_factor * track_bonus
        # Plain-English recommendation
        if inv["count"] == 0:
            verdict = f"You don't carry this — market median is ${median:.0f} across {comps} active listings"
            action  = "Consider sourcing"
        elif inv["count"] < 3:
            verdict = f"Light inventory ({inv['count']}) vs market depth ({comps} comps at ${median:.0f} median)"
            action  = "Add inventory"
        elif inv["count"] < 8:
            verdict = f"Balanced — you have {inv['count']} listings, median ${median:.0f}"
            action  = "Maintain"
        else:
            verdict = f"Heavy ({inv['count']}) — wait for market to absorb before sourcing more"
            action  = "Hold"
        recommendations.append({
            "category":  cat,
            "score":     round(score, 1),
            "median":    median,
            "comps":     comps,
            "inv_count": inv["count"],
            "inv_value": inv["value"],
            "sold_count": sold_seg["count"],
            "verdict":   verdict,
            "action":    action,
        })
    recommendations.sort(key=lambda r: -r["score"])

    # --- Trending players / sets (from deal hunter results) ---
    name_counts: dict[str, dict] = {}
    for q in queries:
        for d in q.get("deals", []):
            t = (d.get("title") or "")
            # Extract proper-noun-looking tokens; player names typically 2 capitalized words
            tokens = _re.findall(r"\b[A-Z][a-zA-Z\-']{2,}\b", t)
            # Skip pure brands / common words
            skip = {"PSA", "BGS", "SGC", "Mint", "Near", "Card", "Cards", "Rookie",
                    "Holo", "Refractor", "Auto", "Prizm", "Bowman", "Topps", "Panini",
                    "Select", "Optic", "Donruss", "Chrome", "Marvel", "Pokemon"}
            tokens = [t for t in tokens if t not in skip]
            for i in range(len(tokens) - 1):
                bigram = f"{tokens[i]} {tokens[i+1]}"
                # Filter: must look like a name (no digits, length 6-30)
                if 6 <= len(bigram) <= 30 and not any(c.isdigit() for c in bigram):
                    nc = name_counts.setdefault(bigram, {"count": 0, "total_price": 0.0})
                    nc["count"] += 1
                    nc["total_price"] += d.get("price", 0)
    trending = sorted(
        [(n, d["count"], d["total_price"] / d["count"] if d["count"] else 0) for n, d in name_counts.items()],
        key=lambda x: -x[1],
    )[:20]

    # --- Save today's market snapshot to history ---
    today_snapshot = {
        "ts":   _dt.now(timezone.utc).isoformat(),
        "segments": {c: {"median": s.get("median", 0), "comps": s.get("comps", 0)} for c, s in segments.items()},
        "inventory": {c: {"count": i.get("count", 0), "value": round(i.get("value", 0), 2)} for c, i in inventory.items()},
    }
    _market_history_append(today_snapshot)
    history = _market_history_load()

    # --- Time series for inventory + median chart (last 30 snapshots) ---
    recent_history = history[-30:]
    history_labels = [h.get("ts", "")[:10] for h in recent_history]
    # Plot median price per top category over time
    top_cats = [r["category"] for r in recommendations[:4]]
    history_series = {}
    for cat in top_cats:
        history_series[cat] = [
            h.get("segments", {}).get(cat, {}).get("median", 0) for h in recent_history
        ]

    # --- HTML ---
    extra_css = """
    .mi-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-bottom: 24px; }
    .mi-grid.cols-1 { grid-template-columns: 1fr; }
    .mi-panel { background: var(--surface); border: 1px solid var(--border); border-radius: var(--r-lg); padding: 20px; }
    .mi-panel h3 { font-family: 'Bebas Neue', sans-serif; font-size: 20px; letter-spacing: .03em; color: var(--text); margin-bottom: 4px; }
    .mi-panel .mi-sub { font-size: 12px; color: var(--text-muted); margin-bottom: 14px; }
    .mi-chart-wrap { position: relative; height: 280px; }
    .mi-rec-table { width: 100%; }
    .mi-rec-table th, .mi-rec-table td { font-size: 12.5px; padding: 10px 12px; text-align: left; }
    .mi-rec-table th:not(:first-child), .mi-rec-table td:not(:first-child) { text-align: right; }
    .mi-action {
      display: inline-block; padding: 3px 10px; border-radius: 999px;
      font-size: 10px; letter-spacing: .14em; text-transform: uppercase; font-weight: 700;
    }
    .mi-action.consider-sourcing { background: rgba(127,199,122,.16); color: var(--success); }
    .mi-action.add-inventory     { background: rgba(212,175,55,.16); color: var(--gold); }
    .mi-action.maintain          { background: rgba(108,176,255,.16); color: var(--link); }
    .mi-action.hold              { background: rgba(150,150,150,.18); color: var(--text-muted); }
    .mi-score {
      font-family: 'Bebas Neue', sans-serif;
      font-size: 22px; color: var(--gold); letter-spacing: .02em;
    }
    .mi-verdict { font-size: 11px; color: var(--text-muted); display: block; margin-top: 2px; }
    .trending-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(190px, 1fr)); gap: 10px; }
    .trending-tile {
      background: var(--surface-2);
      border: 1px solid var(--border);
      border-radius: var(--r-sm);
      padding: 10px 12px;
      text-decoration: none; color: inherit;
      transition: all var(--t-fast);
    }
    .trending-tile:hover { border-color: var(--gold); background: var(--surface-3); transform: translateY(-1px); }
    .trending-name { font-size: 13px; font-weight: 700; color: var(--text); }
    .trending-meta { font-size: 11px; color: var(--text-muted); margin-top: 4px; font-variant-numeric: tabular-nums; }

    /* Clickable rec rows with expandable detail */
    .mi-rec-table .mi-row { cursor: pointer; transition: background var(--t-fast); }
    .mi-rec-table .mi-row:hover { background: rgba(212,175,55,.04); }
    .mi-rec-table .mi-row.open  { background: rgba(212,175,55,.06); }
    .mi-row-chevron {
      display: inline-block; margin-left: 6px;
      color: var(--text-muted); transition: transform var(--t-fast);
      font-size: 10px;
    }
    .mi-row.open .mi-row-chevron { transform: rotate(180deg); color: var(--gold); }

    .mi-row-detail { display: none; }
    .mi-row-detail.open { display: table-row; }
    .mi-detail-inner {
      padding: 18px 14px 22px;
      background: var(--surface-2);
      border-top: 1px solid var(--border);
      border-bottom: 1px solid var(--border);
    }
    .mi-detail-head {
      display: flex; justify-content: space-between; align-items: flex-start;
      gap: 16px; flex-wrap: wrap;
      margin-bottom: 14px;
    }
    .mi-detail-title {
      font-family: 'Bebas Neue', sans-serif;
      font-size: 22px; letter-spacing: .03em; color: var(--text);
    }
    .mi-detail-sub { font-size: 12px; color: var(--text-muted); margin-top: 4px; }
    .mi-detail-actions { display: flex; gap: 8px; flex-wrap: wrap; }
    .mi-deal-grid {
      display: grid; grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
      gap: 10px;
      margin-bottom: 14px;
    }
    .mi-deal-tile {
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: var(--r-sm);
      overflow: hidden;
      text-decoration: none; color: inherit;
      transition: all var(--t-fast);
    }
    .mi-deal-tile:hover { border-color: var(--gold); transform: translateY(-2px); box-shadow: 0 6px 16px -8px rgba(212,175,55,.3); }
    .mi-deal-img { position: relative; aspect-ratio: 1/1; background: #111; overflow: hidden; }
    .mi-deal-img img { width: 100%; height: 100%; object-fit: cover; }
    .mi-deal-discount {
      position: absolute; top: 6px; right: 6px;
      background: linear-gradient(135deg, var(--gold), var(--gold-dim));
      color: var(--brand-fg);
      font-family: 'Bebas Neue', sans-serif;
      font-size: 14px; padding: 2px 7px;
      border-radius: var(--r-sm); line-height: 1;
    }
    .mi-deal-meta { padding: 8px 10px; }
    .mi-deal-title { font-size: 12px; color: var(--text); line-height: 1.35; display:-webkit-box; -webkit-line-clamp:2; -webkit-box-orient:vertical; overflow:hidden; margin-bottom: 4px; }
    .mi-deal-price { font-family: 'Bebas Neue', sans-serif; font-size: 18px; color: var(--gold); letter-spacing: .02em; }

    .mi-query-row {
      font-size: 11px; color: var(--text-muted);
      padding-top: 10px; border-top: 1px dashed var(--border);
    }
    .mi-query-lbl { letter-spacing: .14em; text-transform: uppercase; font-weight: 700; margin-right: 6px; }
    .mi-query-chip {
      display: inline-block;
      padding: 3px 10px; margin: 2px 4px 2px 0;
      background: var(--surface-3); border: 1px solid var(--border);
      border-radius: 999px;
      text-decoration: none; color: var(--text-muted);
      font-size: 11px; transition: all var(--t-fast);
    }
    .mi-query-chip:hover { color: var(--gold); border-color: var(--gold); }

    /* Greenfield row click target */
    .mi-greenfield {
      display: flex; justify-content: space-between; align-items: center;
      padding: 10px 0; border-bottom: 1px solid var(--border);
      text-decoration: none; color: inherit;
      transition: padding var(--t-fast);
    }
    .mi-greenfield:hover { padding-left: 8px; }
    .mi-greenfield-go { color: var(--gold); font-size: 18px; opacity: 0; transition: opacity var(--t-fast); }
    .mi-greenfield:hover .mi-greenfield-go { opacity: 1; }

    @media (max-width: 760px) { .mi-grid { grid-template-columns: 1fr; } }
    """

    import urllib.parse as _up
    def _ebay_search_url(q: str) -> str:
        return f'https://www.ebay.com/sch/i.html?_nkw={_up.quote_plus(q)}&_sop=15'

    rec_rows = []
    for idx, r in enumerate(recommendations[:25]):
        action_class = r["action"].lower().replace(" ", "-")
        cat = r["category"]
        cat_deals = deals_by_cat.get(cat, [])[:5]
        cat_queries = queries_by_cat.get(cat, [])
        primary_query = cat_queries[0] if cat_queries else cat.lower()
        ebay_url = _ebay_search_url(primary_query)
        deals_filter_url = f'deals.html#cat={_up.quote(cat)}'

        # Build the expandable detail panel
        deals_html_parts = []
        for d in cat_deals:
            img = f'<img src="{d.get("image","")}" alt="" loading="lazy">' if d.get("image") else '<div style="width:100%;height:100%;background:var(--surface-3);"></div>'
            deals_html_parts.append(f'''
              <a href="{d.get("url","#")}" target="_blank" rel="noopener" class="mi-deal-tile">
                <div class="mi-deal-img">{img}<div class="mi-deal-discount">-{d.get("discount_pct", 0):.0f}%</div></div>
                <div class="mi-deal-meta">
                  <div class="mi-deal-title">{(d.get("title","") or "")[:64]}</div>
                  <div class="mi-deal-price">${d.get("price", 0):.2f} <span style="color:var(--text-muted);text-decoration:line-through;font-size:11px;">${d.get("median", 0):.2f}</span></div>
                </div>
              </a>''')
        if not deals_html_parts:
            deals_html_parts = ['<div style="color:var(--text-muted);font-size:13px;padding:12px;">No active deals in this category right now — but the segment is hot. Hit eBay directly to scout.</div>']

        queries_chip = "".join(
            f'<a href="{_ebay_search_url(q)}" target="_blank" rel="noopener" class="mi-query-chip">{q}</a>'
            for q in cat_queries[:6]
        )

        rec_rows.append(f'''
        <tr class="mi-row" data-idx="{idx}" onclick="toggleMiRow(this)">
          <td>
            <b>{cat}</b>
            <span class="mi-verdict">{r["verdict"]}</span>
          </td>
          <td><span class="mi-score">{r["score"]}</span></td>
          <td>${r["median"]:.0f}</td>
          <td>{r["comps"]}</td>
          <td>{r["inv_count"]}</td>
          <td>
            <span class="mi-action {action_class}">{r["action"]}</span>
            <span class="mi-row-chevron" aria-hidden="true">▾</span>
          </td>
        </tr>
        <tr class="mi-row-detail" data-idx="{idx}">
          <td colspan="6">
            <div class="mi-detail-inner">
              <div class="mi-detail-head">
                <div class="mi-detail-info">
                  <div class="mi-detail-title">What's actually selling in <b>{cat}</b></div>
                  <div class="mi-detail-sub">{r["inv_count"]} of yours · {r["sold_count"]} sold in the past · {r["comps"]} active competitor listings · median ${r["median"]:.0f}</div>
                </div>
                <div class="mi-detail-actions">
                  <a href="{ebay_url}" target="_blank" rel="noopener" class="btn btn-gold" style="padding:9px 14px;font-size:11px;">Search on eBay ↗</a>
                  <a href="{deals_filter_url}" class="btn btn-ghost" style="padding:9px 14px;font-size:11px;">Open in Deal Hunter</a>
                </div>
              </div>
              <div class="mi-deal-grid">{''.join(deals_html_parts)}</div>
              <div class="mi-query-row">
                <span class="mi-query-lbl">Source queries:</span> {queries_chip}
              </div>
            </div>
          </td>
        </tr>''')
    trending_html = "".join(
        f'<a href="{_ebay_search_url(n)}" target="_blank" rel="noopener" class="trending-tile" title="Search eBay for &quot;{n}&quot;">'
        f'<div class="trending-name">{n}</div>'
        f'<div class="trending-meta">{c} appearances · avg ${avg:.0f}</div></a>'
        for n, c, avg in trending
    ) or '<div style="color:var(--text-muted);font-size:13px;">Run a few build cycles to populate trending data.</div>'

    # --- Top opportunities (categories not in inventory but with strong market) ---
    new_opps = [r for r in recommendations if r["inv_count"] == 0][:5]

    body = f"""
    <div class="section-head">
      <div>
        <div class="eyebrow">Forward-looking · sourcing recommendations</div>
        <h1 class="section-title">Market <span class="accent">Intelligence</span></h1>
        <div class="section-sub">Statistical analysis of the broader market from your Deal Hunter watchlist data, compared against your current inventory mix. Tells you <em>where to look next</em>, not just what you've done.</div>
      </div>
    </div>

    <div class="stat-grid">
      <div class="stat-card"><div class="num">{len(segments)}</div><div class="lbl">Market Segments Tracked</div></div>
      <div class="stat-card"><div class="num">{sum(s["comps"] for s in segments.values())}</div><div class="lbl">Active Comps Across Market</div></div>
      <div class="stat-card"><div class="num">{len(recommendations)}</div><div class="lbl">Categories Scored</div></div>
      <div class="stat-card"><div class="num">{len(new_opps)}</div><div class="lbl">Greenfield Opportunities</div></div>
    </div>

    <div class="mi-grid cols-1">
      <div class="mi-panel">
        <h3>Sourcing recommendations · ranked by opportunity score</h3>
        <div class="mi-sub">Score = market median × log(comp count) × inventory-gap factor × your-track-record bonus. Higher = better target.</div>
        <table class="mi-rec-table">
          <thead><tr><th>Category</th><th>Score</th><th>Median</th><th>Comps</th><th>You have</th><th>Action</th></tr></thead>
          <tbody>{''.join(rec_rows) or '<tr><td colspan="6" style="text-align:center;color:var(--text-muted);padding:24px;">Add queries to deal_queries.json to start scoring.</td></tr>'}</tbody>
        </table>
      </div>
    </div>

    <div class="mi-grid">
      <div class="mi-panel">
        <h3>Greenfield opportunities</h3>
        <div class="mi-sub">High-market-value segments you don't have any inventory in yet</div>
        {''.join(f'<a href="{_ebay_search_url(queries_by_cat.get(o["category"], [o["category"].lower()])[0])}" target="_blank" rel="noopener" class="mi-greenfield" title="Search eBay for this category"><div><b style="color:var(--text);">{o["category"]}</b> · ${o["median"]:.0f} median · {o["comps"]} comps<br><span style="font-size:11px;color:var(--text-muted);">{o["verdict"]}</span></div><span class="mi-greenfield-go">→</span></a>' for o in new_opps) or '<div style="color:var(--text-muted);font-size:13px;">No greenfield gaps — you have inventory across all tracked segments.</div>'}
      </div>
      <div class="mi-panel">
        <h3>Top 20 trending names</h3>
        <div class="mi-sub">Players/characters appearing most often in current Deal Hunter results</div>
        <div class="trending-grid">{trending_html}</div>
      </div>
    </div>

    {f'''<div class="mi-grid cols-1">
      <div class="mi-panel">
        <h3>Category median price · last {len(recent_history)} builds</h3>
        <div class="mi-sub">Trend line for your top opportunity categories. Useful once a few weeks of builds accumulate.</div>
        <div class="mi-chart-wrap"><canvas id="mi-trend"></canvas></div>
      </div>
    </div>''' if len(recent_history) >= 2 else ''}

    <script>
      // Expandable recommendation rows
      window.toggleMiRow = function (rowEl) {{
        const idx = rowEl.dataset.idx;
        const detail = document.querySelector('.mi-row-detail[data-idx="' + idx + '"]');
        const wasOpen = rowEl.classList.contains('open');
        // Close any other open rows first
        document.querySelectorAll('.mi-row.open').forEach(r => {{
          r.classList.remove('open');
          document.querySelector('.mi-row-detail[data-idx="' + r.dataset.idx + '"]')?.classList.remove('open');
        }});
        if (!wasOpen) {{
          rowEl.classList.add('open');
          detail?.classList.add('open');
        }}
      }};

      Chart.defaults.color = getComputedStyle(document.documentElement).getPropertyValue('--text-muted').trim() || '#9a9388';
      Chart.defaults.font.family = "'Inter', sans-serif";
      const histLabels = {history_labels!r};
      const histSeries = {history_series!r};
      const PALETTE = ['#d4af37','#7fc77a','#6cb0ff','#e0b54a','#e07b6f','#b388e0'];
      if (histLabels.length >= 2 && document.getElementById('mi-trend')) {{
        const datasets = Object.entries(histSeries).map(([cat, vals], i) => ({{
          label: cat, data: vals,
          borderColor: PALETTE[i % PALETTE.length],
          backgroundColor: PALETTE[i % PALETTE.length] + '22',
          borderWidth: 2, tension: 0.35, pointRadius: 3,
        }}));
        new Chart(document.getElementById('mi-trend'), {{
          type: 'line',
          data: {{ labels: histLabels, datasets }},
          options: {{
            plugins: {{ legend: {{ position: 'bottom' }} }},
            scales: {{
              x: {{ grid: {{ display: false }} }},
              y: {{ grid: {{ color: 'rgba(212,175,55,0.06)' }}, ticks: {{ callback: v => '$' + v }} }}
            }}
          }}
        }});
      }}
    </script>
    """

    out = OUTPUT_DIR / "market_intel.html"
    out.write_text(html_shell(f"Market Intelligence · {SELLER_NAME}", body, extra_head=f"<style>{extra_css}</style>", active_page="market_intel.html"), encoding="utf-8")
    print(f"  Market intel page: {out} ({len(recommendations)} categories scored, {len(new_opps)} greenfield)")
    return out


# ---------------------------------------------------------------------------
# Sold items page (sold.html)
# ---------------------------------------------------------------------------

def build_sold_page(sold: list[dict]) -> Path:
    """Renders all completed sales (last 90 days) in a dark-luxe card grid."""
    import re as _re
    from datetime import datetime as _dt

    # Sort newest-first
    sold_sorted = sorted(sold, key=lambda s: s.get("sold_date") or "", reverse=True)

    # Aggregate stats
    total_revenue = sum(s["sale_price"] for s in sold)
    avg_price     = (total_revenue / len(sold)) if sold else 0.0
    unique_buyers = len({s["buyer"] for s in sold if s["buyer"]})

    # Bucket by month for the chart
    monthly = {}
    for s in sold:
        if s.get("sold_date"):
            try:
                d = _dt.fromisoformat(s["sold_date"].replace("Z", "+00:00"))
                k = d.strftime("%Y-%m")
                monthly.setdefault(k, {"count": 0, "revenue": 0.0})
                monthly[k]["count"] += 1
                monthly[k]["revenue"] += s["sale_price"]
            except Exception:
                pass
    months_sorted = sorted(monthly.keys())
    chart_labels  = months_sorted
    chart_revenue = [round(monthly[m]["revenue"], 2) for m in months_sorted]
    chart_count   = [monthly[m]["count"] for m in months_sorted]

    # Build cards
    cards = []
    for s in sold_sorted:
        big_pic = _re.sub(r's-l\d+\.jpg', 's-l500.jpg', s["pic"]) if s["pic"] else ""
        thumb = (
            f'<img src="{big_pic}" alt="" loading="lazy">' if big_pic
            else '<div style="display:flex;align-items:center;justify-content:center;height:100%;color:var(--text-dim);font-size:11px;">No image</div>'
        )
        date_short = ""
        if s.get("sold_date"):
            try:
                d = _dt.fromisoformat(s["sold_date"].replace("Z", "+00:00"))
                date_short = d.strftime("%b %-d, %Y")
            except Exception:
                date_short = s["sold_date"][:10]
        buyer_html = f'<span class="tag">{s["buyer"]}</span>' if s["buyer"] else ""
        feedback_badge = ""
        if s.get("feedback"):
            cls = "badge-success" if "positive" in (s["feedback"] or "").lower() else ("badge-warning" if "neutral" in (s["feedback"] or "").lower() else "badge-danger")
            feedback_badge = f'<span class="badge {cls}">FB: {s["feedback"]}</span>'

        cards.append(f'''
      <article class="sold-card" data-id="{s['item_id']}">
        <div class="sold-thumb">{thumb}</div>
        <div class="sold-body">
          <div class="sold-meta-row">
            <span class="tag tag-success">SOLD</span>
            <span class="sold-date">{date_short}</span>
            {f'<span class="sold-qty">×{s["quantity"]}</span>' if s["quantity"] not in ("", "1") else ""}
          </div>
          <a href="{s['url']}" target="_blank" rel="noopener" class="sold-title">{s['title']}</a>
          <div class="sold-meta-row" style="margin-top:6px;">
            {buyer_html}
            {feedback_badge}
            {f'<span class="tag">{s["condition"]}</span>' if s["condition"] else ""}
          </div>
        </div>
        <div class="sold-price-block">
          <div class="sold-price">${s["sale_price"]:,.2f}</div>
          {f'<div class="sold-ship">+ ${float(s["ship_cost"]):,.2f} ship</div>' if s["ship_cost"] else ""}
        </div>
      </article>''')

    if not cards:
        cards_html = '<div class="panel" style="text-align:center;padding:48px;color:var(--text-muted);">No sales found in the last 90 days. Check back after your next sale.</div>'
    else:
        cards_html = "\n".join(cards)

    extra_css = """
    .sold-grid { display: grid; gap: 12px; }
    .sold-card {
      display: grid;
      grid-template-columns: 88px 1fr auto;
      gap: 16px; align-items: center;
      background: var(--surface);
      border: 1px solid var(--border);
      border-left: 3px solid var(--success);
      border-radius: var(--r-lg);
      padding: 14px 18px;
      transition: all var(--t-fast);
    }
    .sold-card:hover { border-color: var(--border-mid); border-left-color: var(--success); transform: translateX(2px); }
    .sold-thumb {
      width: 88px; height: 88px;
      border-radius: var(--r-sm); overflow: hidden;
      background: var(--surface-3);
    }
    .sold-thumb img { width: 100%; height: 100%; object-fit: cover; }
    .sold-body { min-width: 0; }
    .sold-meta-row { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
    .sold-date { font-size: 11px; color: var(--text-muted); letter-spacing: .12em; text-transform: uppercase; font-weight: 600; }
    .sold-qty { font-size: 11px; color: var(--text-dim); font-weight: 600; }
    .sold-title { display: block; font-size: 14px; font-weight: 600; line-height: 1.35; color: var(--text); margin-top: 6px; text-decoration: none; }
    .sold-title:hover { color: var(--gold); }
    .sold-price-block { text-align: right; flex-shrink: 0; }
    .sold-price {
      font-family: 'Bebas Neue', sans-serif;
      font-size: 28px; line-height: 1;
      color: var(--gold);
      letter-spacing: .02em;
    }
    .sold-ship { font-size: 11px; color: var(--text-muted); margin-top: 4px; }
    .charts-row { display: grid; grid-template-columns: 1fr; gap: 16px; margin-bottom: 24px; }
    .chart-panel { background: var(--surface); border: 1px solid var(--border); border-radius: var(--r-lg); padding: 20px; }
    .chart-panel h3 { font-family: 'Bebas Neue', sans-serif; font-size: 18px; letter-spacing: .03em; color: var(--text); margin-bottom: 14px; }
    .chart-wrap { position: relative; height: 240px; }
    @media (max-width: 540px) {
      .sold-card { grid-template-columns: 56px 1fr; padding: 14px; }
      .sold-thumb { width: 56px; height: 56px; }
      .sold-price-block { grid-column: 1 / -1; text-align: left; }
    }
    """

    # Earliest + latest date range for the eyebrow
    dates = [s.get("sold_date") for s in sold if s.get("sold_date")]
    range_label = "All-time history"
    if dates:
        try:
            d_min = _dt.fromisoformat(min(dates).replace("Z","+00:00")).strftime("%b %Y")
            d_max = _dt.fromisoformat(max(dates).replace("Z","+00:00")).strftime("%b %Y")
            range_label = f"{d_min} → {d_max}" if d_min != d_max else f"Sales from {d_max}"
        except Exception:
            pass
    body = f"""
    <div class="section-head">
      <div>
        <div class="eyebrow">{range_label}</div>
        <h1 class="section-title">Sold <span class="accent">Items</span></h1>
        <div class="section-sub">Completed sales accumulated from eBay (Trading API caps live queries at 90 days; full history persists to <code>sold_history.json</code> on every build, so the catalog grows over time).</div>
      </div>
    </div>

    <div class="stat-grid">
      <div class="stat-card"><div class="num">{len(sold)}</div><div class="lbl">Items Sold</div></div>
      <div class="stat-card"><div class="num">${total_revenue:,.0f}</div><div class="lbl">Gross Revenue</div></div>
      <div class="stat-card"><div class="num">${avg_price:,.2f}</div><div class="lbl">Avg Sale Price</div></div>
      <div class="stat-card"><div class="num">{unique_buyers}</div><div class="lbl">Unique Buyers</div></div>
    </div>

    {'<div class="charts-row"><div class="chart-panel"><h3>Monthly Sales</h3><div class="chart-wrap"><canvas id="chart-sold"></canvas></div></div></div>' if chart_labels else ''}

    <div class="sold-grid">
      {cards_html}
    </div>

    <script>
      Chart.defaults.color = '#9a9388';
      Chart.defaults.font.family = "'Inter', sans-serif";
      const lbls = {chart_labels!r};
      if (lbls.length && document.getElementById('chart-sold')) {{
        new Chart(document.getElementById('chart-sold'), {{
          type: 'bar',
          data: {{
            labels: lbls,
            datasets: [
              {{ label: 'Revenue ($)', data: {chart_revenue}, backgroundColor: 'rgba(212,175,55,.55)', borderColor: '#d4af37', borderWidth: 1.5, borderRadius: 6, yAxisID: 'y' }},
              {{ label: 'Items',        data: {chart_count},   type: 'line',  backgroundColor: 'rgba(127,199,122,.2)', borderColor: '#7fc77a', borderWidth: 2, tension: 0.35, yAxisID: 'y1' }}
            ]
          }},
          options: {{
            plugins: {{ legend: {{ position: 'bottom', labels: {{ padding: 12, usePointStyle: true }} }} }},
            scales: {{
              y:  {{ beginAtZero: true, position: 'left',  grid: {{ color: 'rgba(212,175,55,0.05)' }}, ticks: {{ callback: v => '$' + v }} }},
              y1: {{ beginAtZero: true, position: 'right', grid: {{ display: false }}, ticks: {{ precision: 0 }} }},
              x:  {{ grid: {{ display: false }} }}
            }}
          }}
        }});
      }}
    </script>"""

    out = OUTPUT_DIR / "sold.html"
    out.write_text(html_shell(f"Sold Items · {SELLER_NAME}", body, extra_head=f"<style>{extra_css}</style>", active_page="sold.html"), encoding="utf-8")
    print(f"  Sold items page: {out}")
    return out


# ---------------------------------------------------------------------------
# Analytics page (analytics.html)
# ---------------------------------------------------------------------------

def build_analytics_page(listings: list[dict], market: dict, sold: list[dict]) -> Path:
    """Cross-cut analytics: active inventory vs sold history vs market position."""
    from datetime import datetime as _dt
    import re as _re

    # ---- Active inventory ----
    active_by_cat: dict[str, dict] = {}
    for l in listings:
        cat = _categorize(l)
        try:
            p = float(l["price"])
        except (TypeError, ValueError):
            p = 0.0
        b = active_by_cat.setdefault(cat, {"count": 0, "value": 0.0})
        b["count"] += 1
        b["value"] += p

    # ---- Sold history ----
    sold_by_cat: dict[str, dict] = {}
    monthly: dict[str, dict] = {}
    velocity_by_cat: dict[str, list] = {}
    for s in sold:
        cat = _categorize({"title": s.get("title", "")})
        sp = float(s.get("sale_price", 0) or 0)
        bc = sold_by_cat.setdefault(cat, {"count": 0, "revenue": 0.0})
        bc["count"]   += 1
        bc["revenue"] += sp
        velocity_by_cat.setdefault(cat, []).append(sp)
        sd = s.get("sold_date") or ""
        if sd:
            try:
                d = _dt.fromisoformat(sd.replace("Z", "+00:00"))
                k = d.strftime("%Y-%m")
                bm = monthly.setdefault(k, {"units": 0, "revenue": 0.0})
                bm["units"]   += 1
                bm["revenue"] += sp
            except Exception:
                pass

    months = sorted(monthly.keys())
    months_revenue = [round(monthly[m]["revenue"], 2) for m in months]
    months_units   = [monthly[m]["units"] for m in months]

    # ---- Market position: are you priced above / at / below the market median? ----
    pos_buckets = {"Below market (UNDERPRICED)": 0, "On market (OK)": 0, "Above market (OVERPRICED)": 0, "No comps": 0}
    pos_money_left = 0.0
    scatter_pts = []  # (your_price, market_median, item_id, title, flag)
    for l in listings:
        m = market.get(l["item_id"], {}) if market else {}
        flag = m.get("flag", "NO_COMPS")
        med  = m.get("market_median")
        try:
            our = float(l["price"])
        except (TypeError, ValueError):
            our = 0.0
        if flag == "UNDERPRICED":
            pos_buckets["Below market (UNDERPRICED)"] += 1
            if med:
                pos_money_left += max(0, med - our)
        elif flag == "OVERPRICED":
            pos_buckets["Above market (OVERPRICED)"] += 1
        elif flag == "OK":
            pos_buckets["On market (OK)"] += 1
        else:
            pos_buckets["No comps"] += 1
        if med and our > 0:
            scatter_pts.append({
                "x": round(med, 2),
                "y": round(our, 2),
                "id": l["item_id"],
                "title": l["title"][:60],
                "flag": flag,
            })

    # ---- Sold-vs-asking accuracy: of items sold, were you at/above/below your asking? ----
    # (We don't track historical asking prices reliably — skip this for now)

    # ---- Top-grossing items (sold) ----
    top_sold = sorted(sold, key=lambda s: float(s.get("sale_price", 0) or 0), reverse=True)[:10]

    # ---- Inventory/sales ratio (turnover proxy) ----
    total_inventory_value = sum(b["value"] for b in active_by_cat.values())
    total_sold_revenue    = sum(b["revenue"] for b in sold_by_cat.values())
    turnover_ratio = round(total_sold_revenue / total_inventory_value, 2) if total_inventory_value else 0
    # Avg sale price per category (for sold)
    avg_sale_by_cat = {c: (round(b["revenue"] / b["count"], 2) if b["count"] else 0) for c, b in sold_by_cat.items()}

    # All categories that appear anywhere
    all_cats = sorted(set(active_by_cat.keys()) | set(sold_by_cat.keys()))

    extra_css = """
    .a-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-bottom: 22px; }
    .a-grid.cols-1 { grid-template-columns: 1fr; }
    .a-panel { background: var(--surface); border: 1px solid var(--border); border-radius: var(--r-lg); padding: 20px; }
    .a-panel h3 { font-family: 'Bebas Neue', sans-serif; font-size: 20px; letter-spacing: .03em; color: var(--text); margin-bottom: 4px; }
    .a-panel .a-sub { font-size: 12px; color: var(--text-muted); margin-bottom: 14px; letter-spacing: .02em; }
    .a-chart-wrap { position: relative; height: 280px; }
    .a-chart-wrap.tall { height: 340px; }
    .a-table { width: 100%; }
    .a-table th, .a-table td { font-size: 12.5px; padding: 8px 10px; text-align: left; }
    .a-table th:not(:first-child), .a-table td:not(:first-child) { text-align: right; }
    .a-table tr:hover td { background: rgba(212,175,55,0.04); }
    .a-pct { font-family: 'JetBrains Mono', monospace; font-weight: 700; }
    @media (max-width: 760px) { .a-grid { grid-template-columns: 1fr; } }
    """

    # Top-sold rows
    top_rows = []
    for s in top_sold:
        sp = float(s.get("sale_price", 0) or 0)
        sd = (s.get("sold_date") or "")[:10]
        top_rows.append(f'<tr><td>{s.get("title","")[:75]}</td><td>${sp:,.2f}</td><td>{sd}</td></tr>')
    top_rows_html = "\n".join(top_rows) or '<tr><td colspan="3" style="color:var(--text-muted);text-align:center;padding:24px;">No sales yet.</td></tr>'

    # Category comparison table
    cat_rows = []
    for c in all_cats:
        a = active_by_cat.get(c, {"count": 0, "value": 0.0})
        s = sold_by_cat.get(c, {"count": 0, "revenue": 0.0})
        avg = avg_sale_by_cat.get(c, 0)
        cat_rows.append(
            f'<tr><td><b>{c}</b></td><td>{a["count"]}</td><td>${a["value"]:,.0f}</td>'
            f'<td>{s["count"]}</td><td>${s["revenue"]:,.0f}</td><td>${avg:,.2f}</td></tr>'
        )

    body = f"""
    <div class="section-head">
      <div>
        <div class="eyebrow">Cross-cut intelligence</div>
        <h1 class="section-title">Analytics</h1>
        <div class="section-sub">What you're selling, what you've sold, where the market is. Built from active listings, sold history, and live eBay comps.</div>
      </div>
    </div>

    <div class="stat-grid">
      <div class="stat-card"><div class="num">{len(listings)}</div><div class="lbl">Active Listings</div></div>
      <div class="stat-card"><div class="num">${total_inventory_value:,.0f}</div><div class="lbl">Inventory Value</div></div>
      <div class="stat-card"><div class="num">{sum(b["count"] for b in sold_by_cat.values())}</div><div class="lbl">Items Sold</div></div>
      <div class="stat-card"><div class="num">${total_sold_revenue:,.0f}</div><div class="lbl">Sold Revenue</div></div>
      <div class="stat-card"><div class="num">{turnover_ratio:.2f}<span style="font-size:18px;color:var(--text-muted)">×</span></div><div class="lbl">Turnover Ratio</div></div>
      <div class="stat-card"><div class="num danger">${pos_money_left:,.0f}</div><div class="lbl">$ Left on Table (Underpriced)</div></div>
    </div>

    <div class="a-grid">
      <div class="a-panel">
        <h3>Inventory by category</h3>
        <div class="a-sub">Active listings — what's on the shelf right now</div>
        <div class="a-chart-wrap"><canvas id="ch-inv-cat"></canvas></div>
      </div>
      <div class="a-panel">
        <h3>Sold revenue by category</h3>
        <div class="a-sub">All-time accumulated from eBay sales history</div>
        <div class="a-chart-wrap"><canvas id="ch-sold-cat"></canvas></div>
      </div>
    </div>

    <div class="a-grid cols-1">
      <div class="a-panel">
        <h3>Sales velocity over time</h3>
        <div class="a-sub">Monthly units (line) + revenue (bars)</div>
        <div class="a-chart-wrap tall"><canvas id="ch-sales-time"></canvas></div>
      </div>
    </div>

    <div class="a-grid">
      <div class="a-panel">
        <h3>Market position</h3>
        <div class="a-sub">Each dot is one of your active listings: market median (x) vs your asking price (y). On-line = match, above = overpriced, below = underpriced.</div>
        <div class="a-chart-wrap tall"><canvas id="ch-market-pos"></canvas></div>
      </div>
      <div class="a-panel">
        <h3>Pricing position breakdown</h3>
        <div class="a-sub">How many of your active listings are above/at/below the market median</div>
        <div class="a-chart-wrap"><canvas id="ch-pos-bars"></canvas></div>
      </div>
    </div>

    <div class="a-grid cols-1">
      <div class="a-panel">
        <h3>Category comparison</h3>
        <div class="a-sub">Selling vs sold, side by side</div>
        <table class="a-table">
          <thead><tr><th>Category</th><th>Active</th><th>Listed $</th><th>Sold</th><th>Sold $</th><th>Avg Sale</th></tr></thead>
          <tbody>{''.join(cat_rows)}</tbody>
        </table>
      </div>
      <div class="a-panel">
        <h3>Top 10 sales</h3>
        <div class="a-sub">Biggest sold items in accumulated history</div>
        <table class="a-table">
          <thead><tr><th>Item</th><th>Price</th><th>Date</th></tr></thead>
          <tbody>{top_rows_html}</tbody>
        </table>
      </div>
    </div>

    <script>
      Chart.defaults.color = getComputedStyle(document.documentElement).getPropertyValue('--text-muted').trim() || '#9a9388';
      Chart.defaults.font.family = "'Inter', sans-serif";
      const GOLD = '#d4af37';
      const PALETTE = ['#d4af37','#7fc77a','#6cb0ff','#e0b54a','#e07b6f','#b388e0','#5fc7c7','#f4ce5d','#8a7521'];

      // Inventory by category (donut)
      new Chart(document.getElementById('ch-inv-cat'), {{
        type: 'doughnut',
        data: {{
          labels: {list(active_by_cat.keys())!r},
          datasets: [{{
            data: {[b['count'] for b in active_by_cat.values()]},
            backgroundColor: PALETTE,
            borderColor: '#0a0a0a', borderWidth: 3, hoverOffset: 8,
          }}]
        }},
        options: {{ cutout: '60%', plugins: {{ legend: {{ position: 'bottom', labels: {{ usePointStyle: true, padding: 12 }} }} }} }}
      }});

      // Sold revenue by category (donut)
      new Chart(document.getElementById('ch-sold-cat'), {{
        type: 'doughnut',
        data: {{
          labels: {list(sold_by_cat.keys())!r},
          datasets: [{{
            data: {[round(b['revenue'], 2) for b in sold_by_cat.values()]},
            backgroundColor: PALETTE,
            borderColor: '#0a0a0a', borderWidth: 3, hoverOffset: 8,
          }}]
        }},
        options: {{
          cutout: '60%',
          plugins: {{
            legend: {{ position: 'bottom', labels: {{ usePointStyle: true, padding: 12 }} }},
            tooltip: {{ callbacks: {{ label: (ctx) => ctx.label + ': $' + ctx.parsed.toFixed(2) }} }}
          }}
        }}
      }});

      // Sales velocity over time (line + bar dual axis)
      new Chart(document.getElementById('ch-sales-time'), {{
        type: 'bar',
        data: {{
          labels: {months!r},
          datasets: [
            {{ label: 'Revenue ($)', data: {months_revenue}, backgroundColor: 'rgba(212,175,55,.55)', borderColor: GOLD, borderWidth: 1.5, borderRadius: 6, yAxisID: 'y' }},
            {{ label: 'Items sold', data: {months_units}, type: 'line', backgroundColor: 'rgba(127,199,122,.2)', borderColor: '#7fc77a', borderWidth: 2, tension: 0.35, yAxisID: 'y1' }}
          ]
        }},
        options: {{
          plugins: {{ legend: {{ position: 'bottom' }} }},
          scales: {{
            y:  {{ beginAtZero: true, position: 'left',  grid: {{ color: 'rgba(212,175,55,0.06)' }}, ticks: {{ callback: v => '$' + v }} }},
            y1: {{ beginAtZero: true, position: 'right', grid: {{ display: false }}, ticks: {{ precision: 0 }} }},
          }}
        }}
      }});

      // Market position scatter
      const scatterPts = {scatter_pts!r};
      new Chart(document.getElementById('ch-market-pos'), {{
        type: 'scatter',
        data: {{
          datasets: [{{
            label: 'Listings',
            data: scatterPts.map(p => ({{ x: p.x, y: p.y, _info: p }})),
            backgroundColor: scatterPts.map(p => p.flag === 'UNDERPRICED' ? '#e07b6f' : p.flag === 'OVERPRICED' ? '#e0b54a' : '#7fc77a'),
            pointRadius: 5, pointHoverRadius: 8,
          }}]
        }},
        options: {{
          plugins: {{
            legend: {{ display: false }},
            tooltip: {{ callbacks: {{ label: (ctx) => {{ const p = ctx.raw._info; return [p.title, 'Yours: $' + p.y, 'Market: $' + p.x]; }} }} }}
          }},
          scales: {{
            x: {{ title: {{ display: true, text: 'Market median ($)' }}, grid: {{ color: 'rgba(212,175,55,0.06)' }} }},
            y: {{ title: {{ display: true, text: 'Your price ($)' }}, grid: {{ color: 'rgba(212,175,55,0.06)' }} }}
          }}
        }}
      }});

      // Pricing position breakdown
      new Chart(document.getElementById('ch-pos-bars'), {{
        type: 'bar',
        data: {{
          labels: {list(pos_buckets.keys())!r},
          datasets: [{{
            data: {list(pos_buckets.values())},
            backgroundColor: ['rgba(224,123,111,.7)','rgba(127,199,122,.7)','rgba(224,181,74,.7)','rgba(150,150,150,.4)'],
            borderColor: ['#e07b6f','#7fc77a','#e0b54a','#888'],
            borderWidth: 1.5, borderRadius: 6,
          }}]
        }},
        options: {{
          indexAxis: 'y',
          plugins: {{ legend: {{ display: false }} }},
          scales: {{ x: {{ beginAtZero: true, ticks: {{ precision: 0 }}, grid: {{ color: 'rgba(212,175,55,0.06)' }} }}, y: {{ grid: {{ display: false }} }} }}
        }}
      }});
    </script>
    """

    out = OUTPUT_DIR / "analytics.html"
    out.write_text(html_shell(f"Analytics · {SELLER_NAME}", body, extra_head=f"<style>{extra_css}</style>", active_page="analytics.html"), encoding="utf-8")
    print(f"  Analytics page: {out}")
    return out


# ---------------------------------------------------------------------------
# 2. Quality report (quality.html)
# ---------------------------------------------------------------------------

def build_quality_report(listings: list[dict]) -> Path:
    locks = load_locks()
    prices = []
    for l in listings:
        try:
            prices.append(float(l["price"]))
        except ValueError:
            pass
    avg_price = sum(prices) / len(prices) if prices else 0

    issue_counts = {
        "Short title": 0, "No image": 0, "Weak description": 0, "Pricing outlier": 0,
        "Hype/fluff words": 0, "ALL CAPS section": 0, "Contact info in desc": 0,
        "Placeholder values": 0,
    }
    items = []  # (score, listing, issues)
    # Compile detection patterns once
    fluff_re = _re.compile(
        r"\b(L@@K|LOOK|Wow|Amazing|Must Have|Must-Have|Rare Find|Sweet|Stunning|"
        r"Beautiful|Gorgeous|Awesome|Buy Now|Don't Miss|Steal|GORGEOUS|AMAZING)\b",
        _re.IGNORECASE,
    )
    allcaps_re   = _re.compile(r"\b[A-Z]{4,}\b")
    email_re     = _re.compile(r"\b[\w\.-]+@[\w\.-]+\.\w+\b")
    phone_re     = _re.compile(r"\b\d{3}[\s.-]\d{3}[\s.-]\d{4}\b|\b\(\d{3}\)\s*\d{3}[\s.-]?\d{4}\b")
    placeholder_re = _re.compile(r"\b(does not apply|n/a|unbranded|unknown)\b", _re.IGNORECASE)

    for l in listings:
        issues = []
        score  = 100

        title = l["title"] or ""
        desc  = l["desc"]  or ""
        tlen  = len(title)

        if tlen < 40:
            issues.append(f"Title too short ({tlen}/80 chars)")
            issue_counts["Short title"] += 1
            score -= 25
        elif tlen < 60:
            issues.append(f"Title could be longer ({tlen}/80 chars)")
            issue_counts["Short title"] += 1
            score -= 10

        # Fluff/hype words in title (search-killer + violates eBay seller guidance)
        fluff_hits = [m.group(0) for m in fluff_re.finditer(title)]
        if fluff_hits:
            issues.append(f"Title has fluff word(s): {', '.join(set(fluff_hits))}")
            issue_counts["Hype/fluff words"] += 1
            score -= 10

        # ALL CAPS sections in title (also flagged in description)
        caps_in_title = [m.group(0) for m in allcaps_re.finditer(title) if m.group(0) not in _KEEP_CAPS]
        if caps_in_title:
            issues.append(f"Title has ALL-CAPS section: {', '.join(sorted(set(caps_in_title))[:3])}")
            issue_counts["ALL CAPS section"] += 1
            score -= 8

        if "!" in title or "***" in title:
            issues.append("Title has spammy punctuation (! or ***)")
            score -= 5

        if not l["pic"]:
            issues.append("No image — critical for search rank")
            issue_counts["No image"] += 1
            score -= 40

        if not desc or len(desc) < 50:
            issues.append("Description missing or very short")
            issue_counts["Weak description"] += 1
            score -= 15
        else:
            # Hype/fluff in description
            if fluff_re.search(desc):
                issues.append("Description has hype/fluff words")
                issue_counts["Hype/fluff words"] += 1
                score -= 8
            # Contact info — violates eBay policy
            if email_re.search(desc) or phone_re.search(desc):
                issues.append("Description has email/phone — eBay will suppress")
                issue_counts["Contact info in desc"] += 1
                score -= 20
            # Placeholder values
            if placeholder_re.search(desc):
                issues.append("Description has placeholder values (Does not apply / N/A)")
                issue_counts["Placeholder values"] += 1
                score -= 8

        try:
            p = float(l["price"])
            if avg_price > 0 and p > avg_price * 3:
                issues.append(f"${p:.2f} is 3× your average (${avg_price:.2f})")
                issue_counts["Pricing outlier"] += 1
            elif avg_price > 0 and p < avg_price * 0.1:
                issues.append(f"${p:.2f} is very low vs avg (${avg_price:.2f})")
                issue_counts["Pricing outlier"] += 1
        except ValueError:
            pass

        score = max(0, score)
        items.append((score, l, issues))

    items.sort(key=lambda x: x[0])
    avg_score = sum(s for s, _, _ in items) / len(items) if items else 0
    good = sum(1 for s, _, _ in items if s >= 80)
    fair = sum(1 for s, _, _ in items if 50 <= s < 80)
    bad  = sum(1 for s, _, _ in items if s < 50)

    cards = []
    for score, l, issues in items:
        if score >= 80:
            badge = '<span class="badge badge-success">Good</span>'
            stripe = "var(--success)"
        elif score >= 50:
            badge = '<span class="badge badge-warning">Fair</span>'
            stripe = "var(--warning)"
        else:
            badge = '<span class="badge badge-danger">Needs work</span>'
            stripe = "var(--danger)"

        issue_html = "".join(f'<li>{i}</li>' for i in issues) if issues else '<li style="color:var(--success);">No issues — looks great</li>'
        try:
            price_f = float(l['price'])
        except ValueError:
            price_f = 0.0

        thumb_html = f'<img src="{l["pic"]}" alt="" loading="lazy">' if l["pic"] else '<div style="background:var(--surface-3);width:100%;height:100%;"></div>'

        # Compute suggested title — only fixable if it differs from current
        suggested = _suggest_title(l)
        original  = l["title"].strip()
        title_fixable = suggested.lower() != _re.sub(r' {2,}', ' ', original).lower()

        # Lock check — listings eBay refuses to revise are read-only
        lock_info = locks.get(l["item_id"])
        is_locked = bool(lock_info)

        # Default-check listings with a fixable title AND score < 80 AND not locked
        default_checked = "checked" if (title_fixable and score < 80 and not is_locked) else ""

        lock_badge = ""
        if is_locked:
            code = lock_info.get("code", "")
            label = "Title locked by eBay" if code == "240" else ("Listing ended" if code == "291" else "Locked by eBay")
            tip = lock_info.get("reason", "eBay rejects revisions on this listing")
            lock_badge = f'<span class="badge badge-danger" title="{tip}" style="margin-left:8px;">🔒 {label}</span>'

        action_block = ""
        if is_locked:
            action_block = f'''<div class="q-fix-none" style="border-color:rgba(224,123,111,0.35);background:rgba(224,123,111,0.05);">
              🔒 <b>{lock_info.get("code", "")} — {lock_info.get("reason", "Locked by eBay")}.</b>
              {"Title cannot be changed — to fix, end this listing on eBay and create a new one with a clean title." if lock_info.get("code") == "240" else "Refresh the site to remove ended listings."}
            </div>'''
        elif title_fixable:
            action_block = f'''
              <div class="q-fix">
                <input type="checkbox" class="row-check" value="{l['item_id']}" data-suggested="{suggested.replace('"', '&quot;')}" {default_checked} aria-label="Select for fix">
                <div class="q-fix-text">
                  <div class="q-fix-lbl">Suggested title (will replace on eBay)</div>
                  <div class="q-fix-suggest">{suggested}</div>
                </div>
              </div>'''
        else:
            action_block = '<div class="q-fix-none">Title already optimized · use Price Review for pricing fixes</div>'

        cards.append(f'''
      <article class="q-card" data-id="{l['item_id']}" style="--stripe:{stripe}" {'data-locked="' + lock_info.get("code", "") + '"' if is_locked else ''}>
        <div class="q-thumb">{thumb_html}</div>
        <div class="q-body">
          <div class="q-head">
            <div class="q-title-wrap">
              <div class="q-score-wrap">
                <span class="q-score">{score}</span><span class="q-score-of">/100</span>
                {badge}
                {lock_badge}
              </div>
              <a href="{l['url']}" target="_blank" rel="noopener" class="q-title">{l['title']}</a>
            </div>
            <div class="q-price">${price_f:.2f}</div>
          </div>
          <ul class="q-issues">{issue_html}</ul>
          {action_block}
        </div>
      </article>''')

    extra_css = """
    .charts-row {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
      gap: 16px;
      margin-bottom: 28px;
    }
    .chart-panel {
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: var(--r-lg);
      padding: 20px;
      min-height: 280px;
    }
    .chart-panel h3 {
      font-family: 'Bebas Neue', sans-serif;
      font-size: 18px; letter-spacing: .03em;
      color: var(--text); margin-bottom: 14px;
    }
    .chart-wrap { position: relative; height: 230px; }
    .q-grid { display: grid; gap: 12px; }
    .q-card {
      display: grid;
      grid-template-columns: 88px 1fr;
      gap: 14px;
      background: var(--surface);
      border: 1px solid var(--border);
      border-left: 3px solid var(--stripe);
      border-radius: var(--r-lg);
      padding: 14px;
      transition: all var(--t-fast);
    }
    .q-card:hover { border-color: var(--border-mid); border-left-color: var(--stripe); transform: translateX(2px); }
    .q-thumb { width: 88px; height: 88px; border-radius: var(--r-sm); overflow: hidden; background: var(--surface-3); }
    .q-thumb img { width: 100%; height: 100%; object-fit: cover; }
    .q-body { min-width: 0; }
    .q-head { display: flex; justify-content: space-between; gap: 12px; margin-bottom: 8px; }
    .q-title-wrap { min-width: 0; flex: 1; }
    .q-score-wrap { display: flex; align-items: center; gap: 8px; margin-bottom: 6px; }
    .q-score { font-family: 'Bebas Neue', sans-serif; font-size: 24px; color: var(--stripe); line-height: 1; letter-spacing: .02em; }
    .q-score-of { font-size: 11px; color: var(--text-dim); margin-right: 4px; }
    .q-title { display: block; font-size: 13.5px; font-weight: 600; color: var(--text); line-height: 1.35; text-decoration: none; }
    .q-title:hover { color: var(--gold); }
    .q-price { font-family: 'Bebas Neue', sans-serif; font-size: 22px; color: var(--gold); line-height: 1; letter-spacing: .02em; flex-shrink: 0; }
    .q-issues { list-style: none; padding: 0; margin: 6px 0 0; font-size: 12.5px; color: var(--text-muted); }
    .q-issues li { padding: 3px 0; padding-left: 14px; position: relative; }
    .q-issues li::before { content: '⚑'; position: absolute; left: 0; color: var(--stripe); font-size: 10px; }
    .q-fix {
      display: grid; grid-template-columns: auto 1fr; gap: 12px;
      align-items: start;
      margin-top: 12px; padding: 12px;
      background: var(--surface-2);
      border: 1px dashed var(--border-mid);
      border-radius: var(--r-sm);
    }
    .q-fix-lbl { font-size: 10px; color: var(--text-muted); letter-spacing: .14em; text-transform: uppercase; font-weight: 700; margin-bottom: 4px; }
    .q-fix-suggest { font-size: 13px; color: var(--gold); font-weight: 600; line-height: 1.4; }
    .q-fix-none { margin-top: 12px; font-size: 12px; color: var(--text-dim); padding: 8px 0; border-top: 1px dashed var(--border); }
    .action-bar {
      position: sticky; top: 76px; z-index: 50;
      display: flex; gap: 10px; align-items: center; flex-wrap: wrap;
      padding: 14px 18px; margin-bottom: 16px;
      background: rgba(20,20,20,.92); backdrop-filter: blur(10px);
      border: 1px solid var(--border-mid);
      border-radius: var(--r-md);
    }
    #count-label { font-size: 12px; color: var(--text-muted); letter-spacing: .14em; text-transform: uppercase; font-weight: 700; }
    @media (max-width: 540px) {
      .q-card { grid-template-columns: 64px 1fr; padding: 12px; }
      .q-thumb { width: 64px; height: 64px; }
      .q-head { flex-direction: column; gap: 4px; }
      .action-bar { top: 70px; }
    }
    """

    chart_data_quality = [good, fair, bad]
    chart_data_issues = list(issue_counts.values())
    chart_labels_issues = list(issue_counts.keys())

    body = f"""
    <div class="section-head">
      <div>
        <div class="eyebrow">Health audit</div>
        <h1 class="section-title">Quality <span class="accent">Report</span></h1>
        <div class="section-sub">Listings ranked worst-first — fix the red ones to climb in eBay's search rankings.</div>
      </div>
    </div>

    <div class="stat-grid">
      <div class="stat-card"><div class="num">{len(items)}</div><div class="lbl">Total Listings</div></div>
      <div class="stat-card"><div class="num">{avg_score:.0f}</div><div class="lbl">Avg Score</div></div>
      <div class="stat-card"><div class="num success">{good}</div><div class="lbl">Good (80+)</div></div>
      <div class="stat-card"><div class="num warning">{fair}</div><div class="lbl">Fair (50-79)</div></div>
      <div class="stat-card"><div class="num danger">{bad}</div><div class="lbl">Needs Work</div></div>
    </div>

    <div class="charts-row">
      <div class="chart-panel">
        <h3>Score Distribution</h3>
        <div class="chart-wrap"><canvas id="chart-quality"></canvas></div>
      </div>
      <div class="chart-panel">
        <h3>Issues Found</h3>
        <div class="chart-wrap"><canvas id="chart-issues"></canvas></div>
      </div>
    </div>

    <div class="section-head">
      <h2 class="section-title" style="font-size:24px;">Listings to <span class="accent">improve</span></h2>
    </div>

    <div class="action-bar">
      <button onclick="qSelectAll(true)"  class="btn btn-ghost">Select All Fixable</button>
      <button onclick="qSelectAll(false)" class="btn btn-ghost">Deselect</button>
      <span id="count-label"></span>
      <button onclick="qApplyFixes()" class="btn btn-gold" style="margin-left:auto;">Apply Title Fixes to eBay →</button>
    </div>

    <div id="status-bar"></div>
    <div style="margin-bottom:16px;">
      <button id="rebuild-btn" onclick="qRebuild()" class="btn btn-outline" style="display:none;">Trigger Rebuild</button>
    </div>

    <div class="q-grid">{''.join(cards)}</div>

    <script>
      const REVISE_URL  = '{LAMBDA_BASE}/revise';
      const REBUILD_URL = '{LAMBDA_BASE}/rebuild';

      function qUpdateCount() {{
        const total   = document.querySelectorAll('.row-check').length;
        const checked = document.querySelectorAll('.row-check:checked').length;
        const lbl = document.getElementById('count-label');
        if (lbl) lbl.textContent = checked + ' of ' + total + ' selected';
      }}
      document.querySelectorAll('.row-check').forEach(cb => cb.addEventListener('change', qUpdateCount));
      qUpdateCount();

      function qSelectAll(val) {{
        document.querySelectorAll('.row-check').forEach(cb => cb.checked = val);
        qUpdateCount();
      }}

      function qStatus(msg, kind) {{
        const bar = document.getElementById('status-bar');
        bar.className = 'status-' + kind;
        bar.style.display = 'block';
        bar.textContent = msg;
        bar.scrollIntoView({{ behavior: 'smooth', block: 'nearest' }});
      }}

      async function qApplyFixes() {{
        const items = [];
        document.querySelectorAll('.row-check:checked').forEach(cb => {{
          items.push({{ item_id: cb.value, title: cb.dataset.suggested }});
        }});
        if (!items.length) {{ qStatus('No items selected.', 'warning'); return; }}
        qStatus('Applying ' + items.length + ' title fix(es) to eBay…', 'info');

        try {{
          const resp = await fetch(REVISE_URL, {{
            method: 'POST',
            headers: {{ 'Content-Type': 'application/json' }},
            body: JSON.stringify({{ items }})
          }});
          const data = await resp.json();
          if (data.success) {{
            // Mark successful items as applied
            const failedIds = new Set((data.errors || []).map(e => e.item_id));
            items.forEach(it => {{
              const card = document.querySelector('.q-card[data-id="' + it.item_id + '"]');
              if (card && !failedIds.has(it.item_id)) {{
                card.querySelector('.row-check').checked = false;
                card.style.opacity = '0.45';
              }}
            }});
            // Learn locks for next time
            LockTracker.consumeErrors(data.errors || []);
            const errs = data.errors && data.errors.length ? ' · ' + data.errors.length + ' failed (eBay-locked, now flagged 🔒)' : '';
            if ((data.updated || 0) > 0 && window.h2kConfetti) window.h2kConfetti();
            qStatus('Done. ' + (data.updated || 0) + ' listing(s) updated on eBay' + errs, 'success');
            document.getElementById('rebuild-btn').style.display = 'inline-flex';
          }} else {{
            qStatus('Error: ' + (data.error || 'Unknown'), 'danger');
          }}
        }} catch(e) {{ qStatus('Request failed: ' + e.message, 'danger'); }}
      }}

      async function qRebuild() {{
        const btn = document.getElementById('rebuild-btn');
        btn.disabled = true; btn.textContent = 'Rebuilding…';
        try {{
          const resp = await fetch(REBUILD_URL, {{ method:'POST', headers:{{ 'Content-Type':'application/json' }}, body:'{{}}' }});
          const data = await resp.json();
          if (data.success) qStatus('Site rebuild triggered. Live in ~2 minutes.', 'success');
          else {{ qStatus('Rebuild failed: ' + (data.error || 'Unknown'), 'danger'); btn.disabled = false; btn.textContent = 'Trigger Rebuild'; }}
        }} catch(e) {{ qStatus('Rebuild request failed: ' + e.message, 'danger'); btn.disabled = false; btn.textContent = 'Trigger Rebuild'; }}
      }}

      Chart.defaults.color = '#9a9388';
      Chart.defaults.font.family = "'Inter', sans-serif";
      Chart.defaults.borderColor = 'rgba(212,175,55,0.10)';

      new Chart(document.getElementById('chart-quality'), {{
        type: 'doughnut',
        data: {{
          labels: ['Good (80+)','Fair (50-79)','Needs work'],
          datasets: [{{
            data: {chart_data_quality},
            backgroundColor: ['#7fc77a', '#e0b54a', '#e07b6f'],
            borderColor: '#0a0a0a',
            borderWidth: 3,
            hoverOffset: 8,
          }}],
        }},
        options: {{
          cutout: '68%',
          plugins: {{ legend: {{ position: 'bottom', labels: {{ padding: 14, usePointStyle: true, pointStyle: 'rectRounded' }} }} }},
        }}
      }});

      new Chart(document.getElementById('chart-issues'), {{
        type: 'bar',
        data: {{
          labels: {chart_labels_issues!r},
          datasets: [{{
            data: {chart_data_issues},
            backgroundColor: ['rgba(224,123,111,.6)','rgba(224,181,74,.6)','rgba(108,176,255,.6)','rgba(212,175,55,.6)'],
            borderColor: ['#e07b6f','#e0b54a','#6cb0ff','#d4af37'],
            borderWidth: 1.5,
            borderRadius: 6,
          }}],
        }},
        options: {{
          indexAxis: 'y',
          plugins: {{ legend: {{ display: false }} }},
          scales: {{
            x: {{ grid: {{ color: 'rgba(212,175,55,0.05)' }}, ticks: {{ color: '#9a9388', precision: 0 }} }},
            y: {{ grid: {{ display: false }}, ticks: {{ color: '#f1efe9' }} }},
          }}
        }}
      }});
    </script>"""

    out = OUTPUT_DIR / "quality.html"
    out.write_text(html_shell(f"Quality Report · {SELLER_NAME}", body, extra_head=f"<style>{extra_css}</style>", active_page="quality.html"), encoding="utf-8")
    print(f"  Quality report: {out}")
    return out


# ---------------------------------------------------------------------------
# 3. Craigslist post generator (craigslist.html)
# ---------------------------------------------------------------------------

_CRAIGSLIST_CITIES = [
    ("newyork",      "New York"),
    ("losangeles",   "Los Angeles"),
    ("chicago",      "Chicago"),
    ("sfbay",        "SF Bay Area"),
    ("boston",       "Boston"),
    ("houston",      "Houston"),
    ("atlanta",      "Atlanta"),
    ("philadelphia", "Philadelphia"),
    ("phoenix",      "Phoenix"),
    ("dallas",       "Dallas / Fort Worth"),
    ("seattle",      "Seattle"),
    ("miami",        "Miami / South Florida"),
    ("denver",       "Denver"),
    ("portland",     "Portland"),
    ("sandiego",     "San Diego"),
    ("washingtondc", "Washington DC"),
    ("austin",       "Austin"),
    ("minneapolis",  "Minneapolis"),
    ("detroit",      "Detroit"),
    ("orangecounty", "Orange County"),
    ("vegas",        "Las Vegas"),
    ("nashville",    "Nashville"),
]


def build_craigslist(listings: list[dict]) -> Path:
    """
    Premium Craigslist post generator.
    Highest-priced items featured first, with one-click copy-to-clipboard.
    """
    sorted_l = sorted(listings, key=lambda x: float(x["price"]) if x["price"] else 0, reverse=True)
    cards = []
    for l in sorted_l:
        try:
            price_f = float(l["price"])
        except ValueError:
            price_f = 0.0

        ad_lines = [
            l["title"],
            "",
            f"Price: ${price_f:.2f}",
            f"Condition: {l['condition']}" if l["condition"] else "",
            "",
            l["desc"][:800].strip() if l["desc"] else "See eBay listing for full details.",
            "",
            f"View on eBay: {l['url']}",
            "",
            "Payment: PayPal, Venmo, or cash on local pickup.",
            "Shipping available.",
        ]
        ad_text = "\n".join(line for line in ad_lines if line is not None)
        ad_escaped = ad_text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

        # Premium tier indicator
        if price_f >= 50:
            tier = '<span class="badge badge-gold">Top Tier</span>'
        elif price_f >= 10:
            tier = '<span class="badge badge-success">Mid</span>'
        else:
            tier = '<span class="badge badge-warning">Quick Sale</span>'

        thumb_html = f'<img src="{l["pic"]}" alt="" loading="lazy">' if l["pic"] else ''

        cards.append(f'''
      <article class="cl-card">
        <div class="cl-head">
          <div class="cl-thumb">{thumb_html}</div>
          <div class="cl-info">
            <div style="display:flex;align-items:center;gap:8px;margin-bottom:6px;">
              {tier}
              <span style="font-size:11px;color:var(--text-muted);">{l['category'] or 'Collectibles'}</span>
            </div>
            <h3 class="cl-title">{l['title'][:90]}</h3>
            <div class="cl-price">${price_f:.2f}</div>
          </div>
          <a href="{l['url']}" target="_blank" rel="noopener" class="btn btn-ghost cl-view">View on eBay</a>
        </div>
        <div class="cl-ad-wrap">
          <div class="cl-ad-head">
            <span class="cl-ad-label">Craigslist Ad</span>
            <div style="display:flex;gap:8px;flex-wrap:wrap;">
              <button class="btn btn-ghost cl-copy" type="button" onclick="copyAd(this)">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15V5a2 2 0 0 1 2-2h10"/></svg>
                Copy
              </button>
              <a class="btn btn-gold cl-post" target="_blank" rel="noopener" data-cl-post>
                Post on Craigslist →
              </a>
            </div>
          </div>
          <textarea onclick="this.select()" readonly class="cl-ad">{ad_escaped}</textarea>
        </div>
      </article>''')

    extra_css = """
    .cl-grid { display: grid; gap: 14px; }
    .cl-card {
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: var(--r-lg);
      overflow: hidden;
      transition: all var(--t-fast);
    }
    .cl-card:hover { border-color: var(--border-mid); }
    .cl-head {
      display: grid;
      grid-template-columns: 76px 1fr auto;
      gap: 14px; align-items: center;
      padding: 14px 18px;
      background: var(--surface-2);
      border-bottom: 1px solid var(--border);
    }
    .cl-thumb { width: 76px; height: 76px; border-radius: var(--r-sm); overflow: hidden; background: var(--surface-3); }
    .cl-thumb img { width: 100%; height: 100%; object-fit: cover; }
    .cl-info { min-width: 0; }
    .cl-title { font-size: 14px; font-weight: 600; line-height: 1.4; color: var(--text); margin-bottom: 6px; }
    .cl-price { font-family: 'Bebas Neue', sans-serif; font-size: 24px; color: var(--gold); line-height: 1; letter-spacing: .02em; }
    .cl-view { padding: 8px 14px; font-size: 12px; }
    .cl-ad-wrap { padding: 14px 18px; }
    .cl-ad-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px; }
    .cl-ad-label { font-size: 10px; color: var(--text-muted); letter-spacing: .18em; text-transform: uppercase; font-weight: 700; }
    .cl-copy { padding: 6px 14px; font-size: 11px; }
    .cl-ad {
      width: 100%; height: 180px;
      font-family: 'JetBrains Mono', monospace; font-size: 12px; line-height: 1.55;
      background: #0c0c0c; color: var(--text-muted);
      border: 1px solid var(--border);
      border-radius: var(--r-sm);
      padding: 12px 14px;
      resize: vertical;
    }
    .cl-ad:focus { background: #050505; border-color: var(--border-hi); color: var(--text); }
    @media (max-width: 540px) {
      .cl-head { grid-template-columns: 56px 1fr; gap: 12px; padding: 14px; }
      .cl-thumb { width: 56px; height: 56px; }
      .cl-view { grid-column: 1 / -1; }
    }
    """

    city_options = "".join(
        f'<option value="{slug}">{name}</option>'
        for slug, name in _CRAIGSLIST_CITIES
    )

    body = f"""
    <div class="section-head">
      <div>
        <div class="eyebrow">Free traffic, real buyers</div>
        <h1 class="section-title">Craigslist <span class="accent">Ads</span></h1>
        <div class="section-sub">Pick your city below. Then for any listing: Copy the ad text, click Post on Craigslist → opens that city's submit page → choose <b>For Sale → Collectibles</b> → paste.</div>
      </div>
    </div>

    <div class="panel" style="display:flex;gap:14px;align-items:end;flex-wrap:wrap;margin-bottom:22px;">
      <div style="flex:1;min-width:240px;">
        <label style="display:block;font-size:10px;letter-spacing:.18em;text-transform:uppercase;color:var(--text-muted);font-weight:700;margin-bottom:6px;">Your Craigslist city</label>
        <select id="cl-city" onchange="clCityChange()">
          <option value="">— Pick a city —</option>
          {city_options}
          <option value="__other">Other / find my city ↗</option>
        </select>
      </div>
      <a id="cl-browse-link" target="_blank" rel="noopener" class="btn btn-ghost" style="display:none;">Browse local collectibles ↗</a>
      <a id="cl-post-link" target="_blank" rel="noopener" class="btn btn-outline" style="display:none;">Post New Ad ↗</a>
    </div>

    <div class="cl-grid">
      {''.join(cards)}
    </div>

    <script>
      function clBuildPostUrl(city) {{
        // Craigslist post path: https://[city].craigslist.org/post — opens picker for category
        return 'https://' + city + '.craigslist.org/post';
      }}
      function clBuildBrowseUrl(city) {{
        // For Sale > Collectibles - by owner
        return 'https://' + city + '.craigslist.org/d/collectibles/search/cba';
      }}
      function clRefreshLinks() {{
        const city = localStorage.getItem('cl_city') || '';
        const postLink   = document.getElementById('cl-post-link');
        const browseLink = document.getElementById('cl-browse-link');
        const cards = document.querySelectorAll('[data-cl-post]');

        if (city && city !== '__other') {{
          postLink.href   = clBuildPostUrl(city);
          browseLink.href = clBuildBrowseUrl(city);
          postLink.style.display   = 'inline-flex';
          browseLink.style.display = 'inline-flex';
          cards.forEach(a => {{
            a.href = clBuildPostUrl(city);
            a.style.pointerEvents = '';
            a.style.opacity = '';
            a.title = 'Opens ' + city + '.craigslist.org/post — choose For Sale → Collectibles - by owner';
          }});
        }} else {{
          postLink.style.display   = 'none';
          browseLink.style.display = 'none';
          cards.forEach(a => {{
            a.href = '#';
            a.style.opacity = '0.55';
            a.title = 'Pick your city above first';
          }});
        }}
      }}

      function clCityChange() {{
        const sel = document.getElementById('cl-city');
        const v = sel.value;
        if (v === '__other') {{
          window.open('https://www.craigslist.org/about/sites', '_blank', 'noopener');
          sel.value = localStorage.getItem('cl_city') || '';
          return;
        }}
        if (v) localStorage.setItem('cl_city', v);
        else   localStorage.removeItem('cl_city');
        clRefreshLinks();
      }}

      // Restore selection
      const savedCity = localStorage.getItem('cl_city');
      if (savedCity) {{
        document.getElementById('cl-city').value = savedCity;
      }}
      clRefreshLinks();

      async function copyAd(btn) {{
        const card = btn.closest('.cl-card');
        const text = card.querySelector('.cl-ad').value;
        try {{
          await navigator.clipboard.writeText(text);
          const original = btn.innerHTML;
          btn.innerHTML = '✓ Copied';
          btn.style.borderColor = 'var(--success)';
          btn.style.color = 'var(--success)';
          setTimeout(() => {{ btn.innerHTML = original; btn.style.borderColor = ''; btn.style.color = ''; }}, 1500);
        }} catch (e) {{
          card.querySelector('.cl-ad').select();
          showToast('Press Cmd/Ctrl+C to copy');
        }}
      }}
    </script>"""

    out = OUTPUT_DIR / "craigslist.html"
    out.write_text(html_shell(f"Craigslist Ads · {SELLER_NAME}", body, extra_head=f"<style>{extra_css}</style>", active_page="craigslist.html"), encoding="utf-8")
    print(f"  Craigslist generator: {out}")
    return out


# ---------------------------------------------------------------------------
# 4. Google Merchant Center feed (google_feed.xml)
# ---------------------------------------------------------------------------

# Google product category IDs for our inventory types
# https://www.google.com/basepages/producttype/taxonomy-with-ids.en-US.txt
_GOOGLE_CATEGORY_MAP = {
    "pokemon":    "Toys & Games > Collectible Card Games > Collectible Card Game Cards",
    "football":   "Sporting Goods > Sport Collectibles > Football Collectibles > Football Trading Cards",
    "basketball": "Sporting Goods > Sport Collectibles > Basketball Collectibles > Basketball Trading Cards",
    "baseball":   "Sporting Goods > Sport Collectibles > Baseball Collectibles > Baseball Trading Cards",
    "default":    "Sporting Goods > Sport Collectibles > Football Collectibles > Football Trading Cards",
}

def _google_category(listing: dict) -> str:
    t = listing["title"].lower()
    if any(w in t for w in ["pokemon", "pikachu", "charizard", "charcadet", "eevee", "holo", "promo"]):
        return _GOOGLE_CATEGORY_MAP["pokemon"]
    if any(w in t for w in _BASKETBALL_TEAMS) or "nba" in t or "basketball" in t:
        return _GOOGLE_CATEGORY_MAP["basketball"]
    if any(w in t for w in _BASEBALL_TEAMS) or "mlb" in t or "baseball" in t:
        return _GOOGLE_CATEGORY_MAP["baseball"]
    return _GOOGLE_CATEGORY_MAP["default"]

def _shipping_weight(listing: dict) -> str:
    """Nominal shipping weight for trading-card lots vs singles."""
    t = listing["title"].lower()
    if "lot" in t or any(c.isdigit() and t[t.index(c)-1:t.index(c)] == " " for c in t[:20]):
        return "0.5 oz"
    return "0.1 oz"

def build_google_feed(listings: list[dict], market: dict | None = None,
                      sold_history: list[dict] | None = None, pricing: dict | None = None) -> Path:
    # Module-level refs so the inner per-item page call has them in scope
    _item_page_market  = market
    _item_page_sold    = sold_history
    _item_page_pricing = pricing
    # Also generate individual item pages so g:link points to our verified domain
    items_dir = OUTPUT_DIR / "items"
    items_dir.mkdir(exist_ok=True)

    rss     = ET.Element("rss", {"version": "2.0", "xmlns:g": "http://base.google.com/ns/1.0"})
    channel = ET.SubElement(rss, "channel")
    ET.SubElement(channel, "title").text       = f"{SELLER_NAME} eBay Store"
    ET.SubElement(channel, "link").text        = SITE_URL
    ET.SubElement(channel, "description").text = f"Active listings from {SELLER_NAME}"

    skipped = 0
    for l in listings:
        if not l["title"] or not l["pic"]:
            skipped += 1
            continue
        try:
            price_f = float(l["price"])
        except ValueError:
            skipped += 1
            continue

        # --- Individual item page (fixes domain mismatch) ---
        item_page_url = f"{SITE_URL}/items/{l['item_id']}.html"
        _build_item_page(l, items_dir, all_listings=listings,
                         market=_item_page_market, sold_history=_item_page_sold,
                         pricing=_item_page_pricing)

        # --- Image: upgrade to s-l1600 (800px+ satisfies Google minimum) ---
        import re as _re
        big_pic = _re.sub(r's-l\d+\.jpg', 's-l1600.jpg', l["pic"])

        # --- Condition ---
        cond_lower  = l["condition"].lower()
        if "new" in cond_lower:
            g_condition = "new"
        elif "refurb" in cond_lower:
            g_condition = "refurbished"
        else:
            g_condition = "used"

        # --- Google product category ---
        g_cat = _google_category(l)

        entry = ET.SubElement(channel, "item")
        ET.SubElement(entry, "g:id").text                      = l["item_id"]
        ET.SubElement(entry, "g:title").text                   = l["title"][:150]
        ET.SubElement(entry, "g:description").text             = (l["desc"] or l["title"])[:5000]
        ET.SubElement(entry, "g:link").text                    = item_page_url        # verified domain
        ET.SubElement(entry, "g:image_link").text              = big_pic              # s-l1600
        ET.SubElement(entry, "g:price").text                   = f"{price_f:.2f} {CURRENCY}"
        ET.SubElement(entry, "g:availability").text            = "in_stock"
        ET.SubElement(entry, "g:condition").text               = g_condition
        ET.SubElement(entry, "g:brand").text                   = SELLER_NAME
        ET.SubElement(entry, "g:identifier_exists").text       = "no"
        ET.SubElement(entry, "g:google_product_category").text = g_cat
        ET.SubElement(entry, "g:shipping_weight").text         = _shipping_weight(l)

    out = OUTPUT_DIR / "google_feed.xml"
    xmlstr = minidom.parseString(ET.tostring(rss, encoding="unicode")).toprettyxml(indent="  ")
    out.write_text(xmlstr, encoding="utf-8")
    print(f"  Google feed: {out}  ({len(listings) - skipped} items, {skipped} skipped)")
    return out


def _build_item_page(l: dict, items_dir: Path, all_listings: list[dict] | None = None,
                     market: dict | None = None, sold_history: list[dict] | None = None,
                     pricing: dict | None = None) -> None:
    """
    Premium product page at docs/items/{item_id}.html.
    Verified GitHub Pages domain (satisfies Google Merchant Center).
    Includes OG tags, Schema.org Product JSON-LD, gallery zoom, related items.
    """
    import re as _re
    import json as _json
    price_f = float(l["price"]) if l["price"] else 0.0
    big_pic = _re.sub(r's-l\d+\.jpg', 's-l1600.jpg', l["pic"]) if l["pic"] else ""
    desc_raw = (l["desc"] or l["title"])
    desc_short = desc_raw[:160].replace('"', "'")
    desc_html = desc_raw.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")[:2000]
    title_esc = l['title'].replace('"', "&quot;")
    category = _categorize(l)

    # Pricing intelligence — admin-only panel with every available source
    srcs = (pricing or {}).get(l["item_id"], {})
    pricing_rows = [("Your price", f"${price_f:.2f}", "currently listed on eBay", "")]
    for sk in ("ebay_active", "sold_history", "pricecharting", "pokemontcg"):
        if sk not in srcs:
            continue
        s = srcs[sk]
        val = f"${s['median']:.2f}"
        if s.get("low") is not None and s.get("high") is not None and s["low"] != s["high"]:
            val += f' <span style="color:var(--text-muted);font-weight:400;font-size:13px;">(${s["low"]:.2f}–${s["high"]:.2f})</span>'
        pricing_rows.append((s["label"], val, s.get("subnote", ""), s.get("url", "")))
    if "ebay_active" in srcs:
        med = srcs["ebay_active"]["median"]
        gap = (price_f - med) / med * 100 if med else 0
        tone = "var(--success)" if -15 <= gap <= 20 else ("var(--danger)" if gap < -15 else "var(--warning)")
        pricing_rows.append(("Gap vs eBay", f'<span style="color:{tone};font-weight:700;">{gap:+.1f}%</span>', "your price vs eBay active median", ""))
    sug = _suggest_price_multi(price_f, srcs)
    if sug.get("price"):
        pricing_rows.append(("Suggested list", f'<b style="color:var(--gold);">${sug["price"]:.2f}</b>', f"based on {sug['basis']}", ""))
    pricing_rows_html = "".join(
        f'<div class="ip-row"><div class="ip-lbl">{lbl}</div><div class="ip-val">{val}</div><div class="ip-note">{note}{(" · <a href=\"" + url + "\" target=\"_blank\" rel=\"noopener\" style=\"color:var(--gold);\">view ↗</a>") if url and url.startswith("http") else ""}</div></div>'
        for lbl, val, note, url in pricing_rows
    )
    pricing_panel_html = f'''
        <section class="item-pricing-panel" data-admin="1">
          <div class="ip-head">
            <div class="ip-eyebrow">Pricing intelligence · admin only</div>
            <h3>Where this price sits</h3>
          </div>
          {pricing_rows_html}
        </section>'''

    # Schema.org Product JSON-LD
    product_ld = {
        "@context": "https://schema.org/",
        "@type": "Product",
        "name": l["title"],
        "image": big_pic or None,
        "description": desc_raw[:500],
        "sku": l["item_id"],
        "brand": {"@type": "Brand", "name": SELLER_NAME},
        "offers": {
            "@type": "Offer",
            "url": l["url"],
            "priceCurrency": CURRENCY,
            "price": f"{price_f:.2f}",
            "availability": "https://schema.org/InStock",
            "itemCondition": "https://schema.org/UsedCondition" if "new" not in (l["condition"] or "").lower() else "https://schema.org/NewCondition",
            "seller": {"@type": "Organization", "name": SELLER_NAME, "url": STORE_URL},
        },
    }

    # Related items: same category, exclude self, top by price
    related_html = ""
    if all_listings:
        same_cat = [x for x in all_listings if x["item_id"] != l["item_id"] and _categorize(x) == category and x["pic"]]
        same_cat.sort(key=lambda x: float(x["price"]) if x["price"] else 0, reverse=True)
        rel = same_cat[:4]
        if rel:
            cards = []
            for r in rel:
                rp = float(r["price"]) if r["price"] else 0.0
                cards.append(f'''
            <a href="{r['item_id']}.html" class="rel-card">
              <div class="rel-img"><img src="{r['pic']}" alt="{r['title']}" loading="lazy"></div>
              <div class="rel-meta">
                <div class="rel-title">{r['title'][:60]}{'…' if len(r['title']) > 60 else ''}</div>
                <div class="rel-price">${rp:.2f}</div>
              </div>
            </a>''')
            related_html = f'''
        <section class="related">
          <div class="eyebrow">More from {category}</div>
          <h2 class="section-title" style="margin-bottom:16px;">You might also like</h2>
          <div class="rel-grid">{''.join(cards)}</div>
        </section>'''

    img_block = ""
    if big_pic:
        img_block = f'''
          <a href="{big_pic}" class="glightbox" data-gallery="item" data-title="{title_esc}">
            <img src="{big_pic}" alt="{title_esc}" loading="eager" width="800" height="800">
            <div class="zoom-hint">
              <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="7"/><path d="m20 20-3-3M9 11h4M11 9v4"/></svg>
              Tap to zoom
            </div>
          </a>'''

    extra_head = f"""<meta name="description" content="{title_esc} — ${price_f:.2f}. {desc_short}">
  <meta property="og:title" content="{title_esc}">
  <meta property="og:description" content="{desc_short}">
  <meta property="og:image" content="{big_pic}">
  <meta property="og:url" content="{SITE_URL}/items/{l['item_id']}.html">
  <meta property="og:price:amount" content="{price_f:.2f}">
  <meta property="og:price:currency" content="USD">
  <meta property="og:availability" content="instock">
  <meta property="og:type" content="product">
  <meta name="twitter:card" content="summary_large_image">
  <link rel="canonical" href="{SITE_URL}/items/{l['item_id']}.html">
  <script type="application/ld+json">{_json.dumps(product_ld)}</script>
  <style>
    .product {{
      display: grid;
      grid-template-columns: minmax(0, 1.2fr) minmax(0, 1fr);
      gap: 32px;
      margin-bottom: 40px;
    }}
    .product-gallery {{
      position: relative;
      background: linear-gradient(135deg, #0e0e0e, #1a1a1a);
      border: 1px solid var(--border-mid);
      border-radius: var(--r-xl);
      overflow: hidden;
      aspect-ratio: 1/1;
      box-shadow: var(--shadow-lg);
    }}
    .product-gallery::before {{
      content: ''; position: absolute; inset: 0; pointer-events: none;
      background: radial-gradient(700px 400px at 50% -10%, rgba(212,175,55,.10), transparent 60%);
      z-index: 1;
    }}
    .product-gallery a {{ display: block; width: 100%; height: 100%; }}
    .product-gallery img {{ width: 100%; height: 100%; object-fit: contain; padding: 24px; }}
    .zoom-hint {{
      position: absolute; bottom: 14px; right: 14px; z-index: 2;
      display: inline-flex; align-items: center; gap: 6px;
      padding: 8px 14px;
      background: rgba(0,0,0,.7); backdrop-filter: blur(8px);
      border: 1px solid var(--border);
      border-radius: 999px;
      color: var(--text-muted);
      font-size: 11px; letter-spacing: .14em; text-transform: uppercase; font-weight: 600;
    }}
    .product-detail {{ display: flex; flex-direction: column; }}
    .product-detail .eyebrow {{ margin-bottom: 12px; }}
    .product-title {{
      font-family: 'Bebas Neue', sans-serif;
      font-size: clamp(28px, 3vw, 40px);
      line-height: 1.1; letter-spacing: .015em;
      color: var(--text);
      margin-bottom: 14px;
    }}
    .product-price {{
      font-family: 'Bebas Neue', sans-serif;
      font-size: clamp(46px, 5.5vw, 68px);
      color: var(--gold);
      line-height: 1;
      margin-bottom: 18px;
      text-shadow: 0 0 32px rgba(212,175,55,.3);
    }}
    .product-tags {{ display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 22px; }}
    .product-actions {{ display: flex; gap: 10px; flex-wrap: wrap; margin-bottom: 28px; }}
    .product-actions .btn {{ flex: 1; min-width: 160px; padding: 14px 22px; font-size: 13px; }}
    .product-meta-grid {{
      display: grid;
      grid-template-columns: repeat(2, 1fr);
      gap: 12px;
      padding: 18px;
      background: var(--surface-2);
      border: 1px solid var(--border);
      border-radius: var(--r-lg);
      margin-bottom: 22px;
    }}
    .meta-cell .meta-lbl {{ font-size: 10px; color: var(--text-muted); letter-spacing: .18em; text-transform: uppercase; font-weight: 600; }}
    .meta-cell .meta-val {{ font-size: 14px; color: var(--text); margin-top: 4px; font-weight: 500; }}
    .product-desc {{
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: var(--r-lg);
      padding: 22px;
    }}
    .product-desc h3 {{ font-family: 'Bebas Neue', sans-serif; font-size: 22px; color: var(--text); margin-bottom: 12px; letter-spacing: .03em; }}
    .product-desc p {{ color: var(--text-muted); line-height: 1.7; font-size: 14px; }}
    .item-pricing-panel {{
      background: linear-gradient(180deg, var(--surface), var(--surface-2));
      border: 1px solid var(--border-mid);
      border-radius: var(--r-lg);
      padding: 20px 22px;
      margin-top: 16px;
    }}
    .item-pricing-panel .ip-head {{ margin-bottom: 12px; }}
    .item-pricing-panel .ip-eyebrow {{
      font-size: 10px; letter-spacing: .22em; text-transform: uppercase;
      color: var(--gold); font-weight: 700; margin-bottom: 4px;
    }}
    .item-pricing-panel h3 {{
      font-family: 'Bebas Neue', sans-serif;
      font-size: 22px; letter-spacing: .03em; color: var(--text);
    }}
    .item-pricing-panel .ip-row {{
      display: grid;
      grid-template-columns: 1fr auto;
      grid-template-rows: auto auto;
      gap: 2px 14px;
      padding: 10px 0;
      border-bottom: 1px solid var(--border);
    }}
    .item-pricing-panel .ip-row:last-child {{ border-bottom: none; }}
    .item-pricing-panel .ip-lbl {{
      font-size: 10px; letter-spacing: .16em; text-transform: uppercase;
      color: var(--text-muted); font-weight: 700; grid-column: 1;
    }}
    .item-pricing-panel .ip-val {{
      font-size: 16px; font-weight: 700; color: var(--text);
      text-align: right; grid-column: 2; grid-row: 1;
      font-variant-numeric: tabular-nums;
    }}
    .item-pricing-panel .ip-note {{
      font-size: 11px; color: var(--text-dim);
      grid-column: 1 / -1; grid-row: 2;
    }}
    .related .rel-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
      gap: 14px;
      margin-top: 14px;
    }}
    .rel-card {{
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: var(--r-lg);
      overflow: hidden;
      display: block;
      transition: all var(--t-fast);
    }}
    .rel-card:hover {{ border-color: var(--border-mid); transform: translateY(-2px); }}
    .rel-img {{ aspect-ratio: 1/1; background: #111; }}
    .rel-img img {{ width: 100%; height: 100%; object-fit: cover; }}
    .rel-meta {{ padding: 12px; }}
    .rel-title {{ font-size: 12px; line-height: 1.35; color: var(--text); display:-webkit-box; -webkit-line-clamp:2; -webkit-box-orient:vertical; overflow:hidden; }}
    .rel-price {{ font-family: 'Bebas Neue', sans-serif; color: var(--gold); font-size: 20px; margin-top: 6px; }}
    @media (max-width: 880px) {{
      .product {{ grid-template-columns: 1fr; gap: 22px; }}
    }}
  </style>"""

    body = f"""
    <a href="../index.html" style="display:inline-flex;align-items:center;gap:6px;color:var(--text-muted);font-size:13px;margin-bottom:18px;letter-spacing:.06em;text-transform:uppercase;font-weight:600;">
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M19 12H5M12 19l-7-7 7-7"/></svg>
      Back to listings
    </a>

    <article class="product">
      <div class="product-gallery">{img_block}</div>
      <div class="product-detail">
        <div class="eyebrow">{category} · #{l['item_id']}</div>
        <h1 class="product-title">{l['title']}</h1>
        <div class="product-price">${price_f:.2f}</div>
        <div class="product-tags">
          <span class="tag tag-gold">{category}</span>
          {f'<span class="tag">{l["condition"]}</span>' if l["condition"] else ''}
        </div>
        <div class="product-actions">
          <a href="{l['url']}" target="_blank" rel="noopener" class="btn btn-gold">See full details &amp; buy on eBay →</a>
          <a href="{STORE_URL}" target="_blank" rel="noopener" class="btn btn-outline">More from {SELLER_NAME}</a>
        </div>
        <div style="font-size:12px;color:var(--text-muted);margin:-10px 0 18px;line-height:1.6;">
          🛡 Secure checkout via eBay · Buyer protection included · Combined shipping on 2+ items<br>
          💬 Questions? Message {SELLER_NAME} on eBay — replies usually within a few hours.
        </div>
        <div class="product-meta-grid">
          <div class="meta-cell">
            <div class="meta-lbl">Condition</div>
            <div class="meta-val">{l["condition"] or '—'}</div>
          </div>
          <div class="meta-cell">
            <div class="meta-lbl">Category</div>
            <div class="meta-val">{category}</div>
          </div>
          <div class="meta-cell">
            <div class="meta-lbl">Item ID</div>
            <div class="meta-val font-mono">{l['item_id']}</div>
          </div>
          <div class="meta-cell">
            <div class="meta-lbl">Seller</div>
            <div class="meta-val">{SELLER_NAME}</div>
          </div>
        </div>
        <div class="product-desc">
          <h3>Item Details</h3>
          <p>{desc_html}</p>
        </div>
        {pricing_panel_html}
      </div>
    </article>

    {related_html}"""

    # Track visit in localStorage so the storefront "Recently Viewed" works
    safe_title = _json.dumps(l["title"][:120])  # JSON-encoded string is also valid JS
    visit_script = f"""<script>
      (function() {{
        const id = '{l['item_id']}';
        const title = {safe_title};
        let recent = [];
        try {{ recent = JSON.parse(localStorage.getItem('h2k_recent') || '[]'); }} catch(e) {{}}
        recent = recent.filter(r => r.id !== id);
        recent.unshift({{ id, title, ts: Date.now() }});
        recent = recent.slice(0, 12);
        localStorage.setItem('h2k_recent', JSON.stringify(recent));
      }})();
    </script>"""
    body = body + visit_script

    # Item pages live in /items/ — adjust nav links to relative
    html_doc = html_shell(l['title'], body, extra_head=extra_head, active_page="../index.html")
    # Patch nav hrefs to point one directory up
    html_doc = html_doc.replace('href="index.html"', 'href="../index.html"')
    html_doc = html_doc.replace('href="quality.html"', 'href="../quality.html"')
    html_doc = html_doc.replace('href="price_review.html"', 'href="../price_review.html"')
    html_doc = html_doc.replace('href="title_review.html"', 'href="../title_review.html"')
    html_doc = html_doc.replace('href="craigslist.html"', 'href="../craigslist.html"')
    html_doc = html_doc.replace('href="google_feed.xml"', 'href="../google_feed.xml"')

    (items_dir / f"{l['item_id']}.html").write_text(html_doc, encoding="utf-8")


# ---------------------------------------------------------------------------
# 5. Analysis views SQL for Fivetran/Databricks schema
# ---------------------------------------------------------------------------

ANALYSIS_SQL = """-- Analysis views for Fivetran managed eBay connector
-- Destination: jason_chletsos_databricks / jason_chletsos_ebay
-- Run these after the first sync completes

-- 1. Order revenue summary
CREATE OR REPLACE VIEW jason_chletsos_ebay.v_order_summary AS
SELECT
    o.order_id,
    o.creation_date,
    o.order_fulfillment_status,
    o.order_payment_status,
    o.buyer_username,
    COUNT(DISTINCT li.line_item_id)                              AS line_item_count,
    SUM(li.quantity)                                             AS total_units,
    SUM(li.line_item_cost_value)                                 AS gross_revenue,
    SUM(li.delivery_cost_value)                                  AS shipping_charged,
    SUM(li.line_item_cost_value) + SUM(li.delivery_cost_value)   AS total_order_value,
    SUM(COALESCE(r.amount_value, 0))                             AS total_refunded,
    SUM(li.line_item_cost_value) - SUM(COALESCE(r.amount_value, 0)) AS net_revenue
FROM jason_chletsos_ebay.order_history o
LEFT JOIN jason_chletsos_ebay.orders_line_item li ON o.order_id = li.order_id
LEFT JOIN jason_chletsos_ebay.orders_line_item_refund r ON li.line_item_id = r.line_item_id
GROUP BY o.order_id, o.creation_date, o.order_fulfillment_status,
         o.order_payment_status, o.buyer_username;

-- 2. Sales by item
CREATE OR REPLACE VIEW jason_chletsos_ebay.v_sales_by_item AS
SELECT
    li.legacy_item_id                                            AS listing_id,
    li.title,
    COUNT(DISTINCT li.order_id)                                  AS orders_count,
    SUM(li.quantity)                                             AS units_sold,
    AVG(li.line_item_cost_value)                                 AS avg_sale_price,
    SUM(li.line_item_cost_value)                                 AS gross_revenue,
    SUM(COALESCE(r.amount_value, 0))                             AS total_refunded,
    SUM(li.line_item_cost_value) - SUM(COALESCE(r.amount_value, 0)) AS net_revenue,
    MIN(o.creation_date)                                         AS first_sale_date,
    MAX(o.creation_date)                                         AS last_sale_date
FROM jason_chletsos_ebay.orders_line_item li
JOIN jason_chletsos_ebay.order_history o ON li.order_id = o.order_id
LEFT JOIN jason_chletsos_ebay.orders_line_item_refund r ON li.line_item_id = r.line_item_id
GROUP BY li.legacy_item_id, li.title
ORDER BY gross_revenue DESC;

-- 3. Monthly revenue trend
CREATE OR REPLACE VIEW jason_chletsos_ebay.v_monthly_revenue AS
SELECT
    DATE_TRUNC('month', o.creation_date)                         AS month,
    COUNT(DISTINCT o.order_id)                                   AS orders,
    SUM(li.quantity)                                             AS units_sold,
    SUM(li.line_item_cost_value)                                 AS gross_revenue,
    SUM(COALESCE(r.amount_value, 0))                             AS refunds,
    SUM(li.line_item_cost_value) - SUM(COALESCE(r.amount_value, 0)) AS net_revenue,
    COUNT(DISTINCT o.buyer_username)                             AS unique_buyers
FROM jason_chletsos_ebay.order_history o
LEFT JOIN jason_chletsos_ebay.orders_line_item li ON o.order_id = li.order_id
LEFT JOIN jason_chletsos_ebay.orders_line_item_refund r ON li.line_item_id = r.line_item_id
GROUP BY DATE_TRUNC('month', o.creation_date)
ORDER BY month DESC;

-- 4. Fulfillment performance
CREATE OR REPLACE VIEW jason_chletsos_ebay.v_fulfillment_performance AS
SELECT
    o.order_id,
    o.creation_date                                              AS order_date,
    o.order_fulfillment_status,
    sf.shipping_carrier_code,
    sf.shipped_date,
    DATEDIFF('day', o.creation_date, sf.shipped_date)            AS days_to_ship,
    CASE
        WHEN DATEDIFF('day', o.creation_date, sf.shipped_date) <= 1 THEN 'Same or next day'
        WHEN DATEDIFF('day', o.creation_date, sf.shipped_date) <= 3 THEN 'Fast 2 to 3 days'
        WHEN DATEDIFF('day', o.creation_date, sf.shipped_date) <= 7 THEN 'Standard 4 to 7 days'
        ELSE 'Slow 7 plus days'
    END                                                          AS shipping_speed_tier
FROM jason_chletsos_ebay.order_history o
LEFT JOIN jason_chletsos_ebay.shipping_fulfillment sf ON o.order_id = sf.order_id;

-- 5. Buyer analysis
CREATE OR REPLACE VIEW jason_chletsos_ebay.v_buyer_analysis AS
SELECT
    o.buyer_username,
    COUNT(DISTINCT o.order_id)                                   AS total_orders,
    SUM(li.line_item_cost_value)                                 AS lifetime_value,
    AVG(li.line_item_cost_value)                                 AS avg_order_value,
    MIN(o.creation_date)                                         AS first_order_date,
    MAX(o.creation_date)                                         AS last_order_date,
    CASE
        WHEN COUNT(DISTINCT o.order_id) = 1  THEN 'One-time'
        WHEN COUNT(DISTINCT o.order_id) <= 3 THEN 'Repeat'
        ELSE 'Loyal'
    END                                                          AS buyer_segment
FROM jason_chletsos_ebay.order_history o
JOIN jason_chletsos_ebay.orders_line_item li ON o.order_id = li.order_id
GROUP BY o.buyer_username
ORDER BY lifetime_value DESC;
"""

def build_sitemap_and_robots(listings: list[dict]) -> None:
    """Generate sitemap.xml + robots.txt for SEO."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    urls = [
        ("",                    "1.0", "hourly"),
        ("quality.html",        "0.6", "daily"),
        ("price_review.html",   "0.6", "daily"),
        ("title_review.html",   "0.5", "daily"),
        ("reddit.html",         "0.4", "weekly"),
        ("craigslist.html",     "0.4", "weekly"),
        ("return-policy.html",  "0.3", "monthly"),
    ]
    entries = []
    for path, prio, freq in urls:
        loc = f"{SITE_URL}/{path}".rstrip("/")
        entries.append(f"  <url><loc>{loc}</loc><lastmod>{today}</lastmod><changefreq>{freq}</changefreq><priority>{prio}</priority></url>")
    for l in listings:
        if l.get("item_id"):
            entries.append(f"  <url><loc>{SITE_URL}/items/{l['item_id']}.html</loc><lastmod>{today}</lastmod><changefreq>weekly</changefreq><priority>0.7</priority></url>")

    sitemap = ("<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n"
               "<urlset xmlns=\"http://www.sitemaps.org/schemas/sitemap/0.9\">\n"
               + "\n".join(entries) + "\n</urlset>\n")
    (OUTPUT_DIR / "sitemap.xml").write_text(sitemap, encoding="utf-8")

    robots = (
        "User-agent: *\n"
        "Allow: /\n"
        "Disallow: /price_review.html\n"
        "Disallow: /title_review.html\n"
        "Disallow: /quality.html\n"
        f"Sitemap: {SITE_URL}/sitemap.xml\n"
    )
    (OUTPUT_DIR / "robots.txt").write_text(robots, encoding="utf-8")
    print(f"  Sitemap + robots.txt: {OUTPUT_DIR}/sitemap.xml")


def write_analysis_views():
    out = OUTPUT_DIR / "analysis_views.sql"
    out.write_text(ANALYSIS_SQL, encoding="utf-8")
    print(f"  Analysis views SQL: {out}")
    return out


# ---------------------------------------------------------------------------
# Price review page — market comps vs our prices
# ---------------------------------------------------------------------------

# eBay fee assumptions (used in price suggestion math)
EBAY_FINAL_VALUE_FEE_PCT = 0.1325  # ~13.25% on collectibles category
EBAY_PER_ORDER_FIXED_FEE = 0.40    # $0.40 per order fixed
DEFAULT_SHIP_COST_LOW    = 1.30    # PWE for singles
DEFAULT_SHIP_COST_HIGH   = 5.00    # BMWT for lots


def _ebay_net(sale_price: float, ship_cost: float = DEFAULT_SHIP_COST_LOW) -> dict:
    """Estimate net proceeds after eBay fees + shipping. Returns dict with breakdown."""
    fvf = round(sale_price * EBAY_FINAL_VALUE_FEE_PCT, 2)
    fee = fvf + EBAY_PER_ORDER_FIXED_FEE
    net = round(sale_price - fee - ship_cost, 2)
    return {
        "sale":  round(sale_price, 2),
        "fvf":   fvf,
        "fixed": EBAY_PER_ORDER_FIXED_FEE,
        "ship":  ship_cost,
        "net":   net,
    }


def _suggest_list_price(market_median: float, sold_match: dict | None = None) -> dict:
    """
    Recommend a list price following eBay best practices:
      - Prefer sold-history median (real sale data) when available + N>=3
      - Else use active median × 0.95 (slight below market to move faster)
      - Round to .99 ending (psychological pricing)
      - Pick a strategy label

    Returns: {price, basis, strategy, basis_count, math}
    """
    if sold_match and sold_match.get("count", 0) >= 3:
        basis      = "sold_history"
        basis_p    = sold_match["median"]
        basis_n    = sold_match["count"]
        strategy   = "Match market (your sold median)"
        ref_price  = basis_p
    elif market_median and market_median > 0:
        basis      = "active_median"
        basis_p    = market_median
        basis_n    = 0
        strategy   = "Price to move (5% below active median)"
        ref_price  = market_median * 0.95
    else:
        return {"price": None, "basis": "none", "strategy": "no comps", "basis_count": 0}

    # Round to .99 ending
    floor_dollar = int(ref_price)
    if ref_price - floor_dollar >= 0.50:
        price = floor_dollar + 0.99
    elif floor_dollar >= 1:
        price = floor_dollar - 0.01
    else:
        price = 0.99
    price = max(0.99, round(price, 2))

    return {
        "price":       price,
        "basis":       basis,
        "basis_value": round(basis_p, 2),
        "basis_count": basis_n,
        "strategy":    strategy,
        "math":        _ebay_net(price),
    }


def _load_sportscardspro_prices() -> dict:
    """Load SCP 'actual' prices written by card_price_agent.py."""
    p = Path(__file__).parent / "sportscardspro_prices.json"
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text())
    except Exception:
        return {}


def build_price_review(listings: list[dict], market: dict, pricing: dict | None = None) -> Path:
    """
    Premium price review: cards with current vs suggested side-by-side,
    market gap visualization, gap distribution chart.

    Two pricing bases are shown side-by-side per card:
      - Market   = eBay live comps median (what people *are* selling for)
      - Actual   = SportsCardsPro guide value (what the card *is worth*)
    A toggle at the top swaps which basis drives the row's color/sort.
    """
    locks = load_locks()
    sold_history = _load_sold_history()
    actual_prices = _load_sportscardspro_prices()
    lambda_url  = f"{LAMBDA_BASE}/reprice"
    rebuild_url = f"{LAMBDA_BASE}/rebuild"

    FLAG_ORDER = {"UNDERPRICED": 0, "OVERPRICED": 1, "OK": 2, "NO_COMPS": 3}
    sorted_listings = sorted(
        listings,
        key=lambda l: (
            FLAG_ORDER.get(market.get(l["item_id"], {}).get("flag", "NO_COMPS"), 3),
            abs(market.get(l["item_id"], {}).get("gap_pct") or 0) * -1,
        )
    )

    cards = []
    gap_buckets = {"<-25%": 0, "-25 to -10%": 0, "-10 to +10%": 0, "+10 to +25%": 0, ">+25%": 0}
    for l in sorted_listings:
        item_id   = l["item_id"]
        our_price = float(l["price"]) if l["price"] else 0.0
        m         = market.get(item_id, {})
        flag      = m.get("flag", "NO_COMPS")
        med       = m.get("market_median")
        mn        = m.get("market_min")
        mx        = m.get("market_max")
        gap       = m.get("gap_pct")
        comps     = m.get("comp_count", 0)

        if flag == "NO_COMPS" or med is None:
            continue

        # Bucket the gap for the chart
        if gap is not None:
            if gap < -25: gap_buckets["<-25%"] += 1
            elif gap < -10: gap_buckets["-25 to -10%"] += 1
            elif gap < 10: gap_buckets["-10 to +10%"] += 1
            elif gap < 25: gap_buckets["+10 to +25%"] += 1
            else: gap_buckets[">+25%"] += 1

        # Multi-source pricing: blend eBay active, sold history, PriceCharting, PokemonTCG.io
        item_srcs = (pricing or {}).get(item_id, {})
        if not item_srcs:
            sm = _sold_history_match(l["title"], sold_history)
            suggestion = _suggest_list_price(med, sm)
        else:
            mr = _suggest_price_multi(our_price, item_srcs)
            suggestion = {
                "price":    mr.get("price"),
                "basis":    mr.get("basis", "no data"),
                "math":     _ebay_net(mr["price"], DEFAULT_SHIP_COST_HIGH if "lot" in l["title"].lower() else DEFAULT_SHIP_COST_LOW) if mr.get("price") else None,
                "strategy": f"Multi-source · {mr.get('basis', '?')}",
            }
        suggested = suggestion["price"] if suggestion.get("price") else max(0.99, round(med) - 0.01)
        ship_est = DEFAULT_SHIP_COST_HIGH if "lot" in l["title"].lower() else DEFAULT_SHIP_COST_LOW
        net_math = _ebay_net(suggested, ship_est)

        # Build a tiny sources-comparison sublist for the card body
        sources_html_parts = []
        for sk in ("ebay_active", "sold_history", "pricecharting", "pokemontcg"):
            if sk not in item_srcs:
                continue
            s = item_srcs[sk]
            url_a = f' · <a href="{s["url"]}" target="_blank" rel="noopener" style="color:var(--gold);">↗</a>' if s.get("url", "").startswith("http") else ""
            sources_html_parts.append(
                f'<span class="pr-src"><b>{s["label"]}</b> ${s["median"]:.2f}{url_a}</span>'
            )
        sources_html = ' · '.join(sources_html_parts) if sources_html_parts else '<span style="color:var(--text-dim);">no external comps</span>'

        if flag == "UNDERPRICED":
            badge = '<span class="badge badge-danger">Underpriced</span>'
            stripe = "var(--danger)"
            checked = "checked"
        elif flag == "OVERPRICED":
            badge = '<span class="badge badge-warning">Overpriced</span>'
            stripe = "var(--warning)"
            checked = "checked"
        else:
            badge = '<span class="badge badge-success">On Market</span>'
            stripe = "var(--success)"
            checked = ""

        # Lock — eBay refuses to revise this listing (price OR title)
        lock_info = locks.get(item_id)
        lock_attr = ""
        if lock_info:
            checked = ""  # never default-check a locked item
            lock_label = "Title locked" if lock_info.get("code") == "240" else ("Ended" if lock_info.get("code") == "291" else "Locked")
            lock_reason = lock_info.get("reason", "")
            badge += f' <span class="badge badge-danger" title="{lock_reason}">🔒 {lock_label}</span>'
            stripe = "var(--danger)"
            lock_attr = f'data-locked="{lock_info["code"]}"'

        gap_label = f"{gap:+.1f}% vs market" if gap is not None else ""
        thumb_html = f'<img src="{l["pic"]}" alt="" loading="lazy">' if l["pic"] else ''
        title_short = l['title'][:80] + ('…' if len(l['title']) > 80 else '')

        # SportsCardsPro "actual" price for this listing (set by card_price_agent.py).
        actual_rec    = actual_prices.get(item_id) or {}
        actual_price  = actual_rec.get("actual_price")
        actual_grade  = actual_rec.get("used_grade")
        actual_url    = actual_rec.get("scp_url", "")
        actual_match  = actual_rec.get("matched_product", "")
        actual_conf   = actual_rec.get("confidence") or 0
        is_lot_rec    = actual_rec.get("is_lot", False)
        if actual_price and our_price:
            actual_gap = (our_price - actual_price) / actual_price * 100.0
        else:
            actual_gap = None
        actual_gap_attr = f' data-actual-gap="{actual_gap:.2f}"' if actual_gap is not None else ' data-actual-gap=""'
        market_gap_attr = f' data-market-gap="{gap:.2f}"' if gap is not None else ' data-market-gap=""'

        if actual_price is not None:
            conf_color = "var(--success)" if actual_conf >= 0.7 else ("var(--gold)" if actual_conf >= 0.5 else "var(--warning)")
            conf_pip   = f'<span title="Match confidence {actual_conf:.0%}" style="display:inline-block;width:6px;height:6px;border-radius:50%;background:{conf_color};margin-right:6px;vertical-align:middle;"></span>'
            grade_lbl  = actual_grade.upper().replace("PSA", "PSA ") if actual_grade else ""
            actual_gap_html = f'<span class="pr-gap-actual" style="margin-left:8px;color:{"var(--danger)" if actual_gap and actual_gap < -10 else ("var(--warning)" if actual_gap and actual_gap > 10 else "var(--success)")};">{actual_gap:+.0f}% vs actual</span>' if actual_gap is not None else ""
            actual_url_html = f' · <a href="{actual_url}" target="_blank" rel="noopener" style="color:var(--gold);">↗</a>' if actual_url else ""
            actual_line = (
                f'<div class="pr-actual">'
                f'{conf_pip}<b>Actual</b> <span class="pr-actual-price">${actual_price:.2f}</span>'
                f' <span class="pr-actual-grade">· {grade_lbl}</span>'
                f' <span class="pr-actual-match">· {actual_match[:48]}</span>'
                f'{actual_url_html}'
                f'{actual_gap_html}'
                f'</div>'
            )
        elif is_lot_rec:
            actual_line = '<div class="pr-actual pr-actual-na"><span style="color:var(--text-dim);">Actual N/A — multi-card lot</span></div>'
        elif actual_rec.get("matched_product"):
            actual_line = f'<div class="pr-actual pr-actual-na"><span style="color:var(--text-dim);">Actual: low-confidence match ({actual_rec.get("confidence",0):.0%}) — review manually</span></div>'
        else:
            actual_line = '<div class="pr-actual pr-actual-na"><span style="color:var(--text-dim);">Actual N/A — no SCP match</span></div>'

        check_disabled = "disabled" if lock_info else ""
        cards.append(f'''
      <article class="pr-card review-row" data-id="{item_id}"{market_gap_attr}{actual_gap_attr} {lock_attr} style="--stripe:{stripe}">
        <div class="pr-check">
          <input type="checkbox" class="row-check" value="{item_id}" {checked} {check_disabled} aria-label="Select for repricing"{' title="eBay refuses to revise this listing"' if lock_info else ''}>
        </div>
        <div class="pr-thumb">{thumb_html}</div>
        <div class="pr-info">
          <div class="pr-meta-row">
            {badge}
            <span class="font-mono" style="font-size:11px;color:var(--text-dim);">#{item_id}</span>
          </div>
          <a href="{l['url']}" target="_blank" rel="noopener" class="pr-title">{title_short}</a>
          <div class="pr-market">
            <b>Market</b> <b>${med:.2f}</b> · Range ${mn:.2f}–${mx:.2f} · {comps} comps
          </div>
          {actual_line}
          <div class="pr-sources">
            <div class="pr-sources-lbl">All sources</div>
            <div class="pr-sources-list">{sources_html}</div>
          </div>
        </div>
        <div class="pr-prices">
          <div class="pr-price-cell">
            <div class="pr-cell-lbl">Current</div>
            <div class="current-price pr-current">${our_price:.2f}</div>
            <div class="pr-gap">{gap_label}</div>
          </div>
          <div class="pr-arrow">→</div>
          <div class="pr-price-cell">
            <div class="pr-cell-lbl">New price</div>
            <div class="pr-new">
              <span class="pr-dollar">$</span>
              <span class="price-after" contenteditable="true" data-id="{item_id}" inputmode="decimal">{suggested:.2f}</span>
            </div>
            <div class="pr-strategy" title="Basis: {suggestion.get('basis','')}{', ' + str(suggestion.get('basis_count',0)) + ' sold' if suggestion.get('basis_count',0) else ''}">{suggestion.get('strategy', '')}</div>
            <div class="pr-math">
              -${net_math['fvf']:.2f} fee · -${net_math['ship']:.2f} ship · <b style="color:var(--success);">${net_math['net']:.2f} net</b>
            </div>
            <a href="{l['url']}" target="_blank" rel="noopener" class="pr-view-link">View on eBay →</a>
          </div>
        </div>
      </article>''')

    if not cards:
        cards_html = '<div class="panel" style="text-align:center;padding:40px;color:var(--text-muted);">No actionable price data found.</div>'
    else:
        cards_html = "\n".join(cards)

    underpriced = sum(1 for v in market.values() if v.get("flag") == "UNDERPRICED")
    overpriced  = sum(1 for v in market.values() if v.get("flag") == "OVERPRICED")
    money_left  = sum(
        (market[l["item_id"]]["market_median"] - float(l["price"]))
        for l in listings
        if market.get(l["item_id"], {}).get("flag") == "UNDERPRICED"
        and market[l["item_id"]].get("market_median") is not None
    )

    extra_css = """
    .pr-grid { display: grid; gap: 12px; }
    .pr-card {
      display: grid;
      grid-template-columns: 36px 88px 1fr auto;
      gap: 14px; align-items: center;
      background: var(--surface);
      border: 1px solid var(--border);
      border-left: 3px solid var(--stripe);
      border-radius: var(--r-lg);
      padding: 14px 18px;
      transition: all var(--t-fast);
    }
    .pr-card:hover { border-color: var(--border-mid); border-left-color: var(--stripe); }
    .pr-check { display: flex; justify-content: center; align-items: center; }
    .pr-thumb {
      width: 88px; height: 88px;
      border-radius: var(--r-sm); overflow: hidden;
      background: var(--surface-3);
      flex-shrink: 0;
    }
    .pr-thumb img { width: 100%; height: 100%; object-fit: cover; }
    .pr-info { min-width: 0; }
    .pr-meta-row { display: flex; align-items: center; gap: 8px; margin-bottom: 6px; }
    .pr-title {
      display: block; font-size: 14px; font-weight: 600; color: var(--text);
      line-height: 1.35; margin-bottom: 6px; text-decoration: none;
    }
    .pr-title:hover { color: var(--gold); }
    .pr-market { font-size: 12px; color: var(--text-muted); }
    .pr-market b { color: var(--text); font-weight: 700; }
    .pr-actual {
      font-size: 12px; color: var(--text-muted); margin-top: 4px;
      font-variant-numeric: tabular-nums;
    }
    .pr-actual b { color: var(--gold); font-weight: 700; letter-spacing: .06em; }
    .pr-actual-price { color: var(--text); font-weight: 700; }
    .pr-actual-grade { color: var(--gold-dim); font-size: 11px; letter-spacing: .08em; text-transform: uppercase; }
    .pr-actual-match { color: var(--text-dim); font-size: 11px; }
    .pr-actual-na { font-style: italic; }
    .pr-gap-actual { font-weight: 700; font-size: 11px; }
    .basis-toggle {
      display: inline-flex; align-items: center; gap: 4px;
      margin-left: 12px;
      padding: 4px;
      background: var(--surface-3);
      border: 1px solid var(--border);
      border-radius: var(--r-md);
    }
    .basis-toggle-lbl {
      font-size: 10px; letter-spacing: .18em; text-transform: uppercase;
      color: var(--text-muted); font-weight: 700; padding: 0 8px 0 4px;
    }
    .basis-btn {
      background: transparent; border: none; cursor: pointer;
      padding: 6px 12px;
      font-size: 12px; font-weight: 700; letter-spacing: .08em;
      color: var(--text-muted);
      border-radius: var(--r-sm);
      transition: all var(--t-fast);
    }
    .basis-btn .basis-sub {
      font-size: 9px; opacity: .65; margin-left: 4px;
      font-weight: 500; letter-spacing: .14em;
    }
    .basis-btn:hover { color: var(--text); }
    .basis-btn.active {
      background: var(--gold);
      color: var(--brand-fg);
      box-shadow: 0 2px 8px -2px rgba(212,175,55,.5);
    }
    /* When basis=actual, gray out the market gap and highlight the actual gap; vice-versa. */
    body[data-basis="actual"] .pr-gap            { opacity: .35; }
    body[data-basis="actual"] .pr-gap-actual     { font-size: 13px; }
    body[data-basis="market"] .pr-gap-actual     { opacity: .55; }
    .pr-sources { margin-top: 8px; padding-top: 8px; border-top: 1px dashed var(--border); }
    .pr-sources-lbl {
      font-size: 9px; letter-spacing: .2em; text-transform: uppercase;
      color: var(--text-muted); font-weight: 700; margin-bottom: 4px;
    }
    .pr-sources-list { display: flex; flex-wrap: wrap; gap: 8px 12px; font-size: 12px; color: var(--text-muted); }
    .pr-src { font-variant-numeric: tabular-nums; }
    .pr-src b { color: var(--text); font-weight: 700; }
    .pr-prices {
      display: flex; align-items: center; gap: 14px;
      padding: 10px 14px;
      background: var(--surface-2);
      border: 1px solid var(--border);
      border-radius: var(--r-md);
      flex-shrink: 0;
    }
    .pr-cell-lbl { font-size: 10px; color: var(--text-muted); letter-spacing: .14em; text-transform: uppercase; font-weight: 700; margin-bottom: 2px; }
    .pr-current {
      font-family: 'Bebas Neue', sans-serif;
      font-size: 26px; line-height: 1; color: var(--text);
      letter-spacing: .02em;
    }
    .pr-gap { font-size: 11px; color: var(--stripe); margin-top: 2px; font-weight: 600; }
    .pr-arrow { color: var(--gold); font-size: 24px; line-height: 1; }
    .pr-new {
      display: flex; align-items: baseline; gap: 2px;
      font-family: 'Bebas Neue', sans-serif;
      font-size: 26px; line-height: 1; color: var(--gold);
      letter-spacing: .02em;
    }
    .pr-dollar { font-size: 18px; }
    .pr-new .price-after {
      min-width: 70px;
      border-bottom: 2px dashed var(--gold-dim);
      outline: none;
      cursor: text;
      caret-color: var(--gold);
    }
    .pr-new .price-after:focus { border-bottom-style: solid; border-bottom-color: var(--gold); }
    .pr-strategy { font-size: 10px; letter-spacing: .08em; text-transform: uppercase; color: var(--gold); margin-top: 6px; font-weight: 700; }
    .pr-math { font-size: 11px; color: var(--text-muted); margin-top: 4px; font-family: 'JetBrains Mono', monospace; line-height: 1.4; }
    .pr-view-link { font-size: 11px; color: var(--text-muted); display: block; margin-top: 4px; }
    .pr-view-link:hover { color: var(--gold); }
    .action-bar {
      position: sticky; top: 76px; z-index: 50;
      display: flex; gap: 10px; align-items: center; flex-wrap: wrap;
      padding: 14px 18px; margin-bottom: 16px;
      background: rgba(20,20,20,.92); backdrop-filter: blur(10px);
      border: 1px solid var(--border-mid);
      border-radius: var(--r-md);
    }
    #count-label { font-size: 12px; color: var(--text-muted); letter-spacing: .14em; text-transform: uppercase; font-weight: 700; }
    .charts-row {
      display: grid; grid-template-columns: 1fr; gap: 16px;
      margin-bottom: 24px;
    }
    .chart-panel { background: var(--surface); border: 1px solid var(--border); border-radius: var(--r-lg); padding: 20px; }
    .chart-panel h3 { font-family: 'Bebas Neue', sans-serif; font-size: 18px; letter-spacing: .03em; color: var(--text); margin-bottom: 14px; }
    .chart-wrap { position: relative; height: 220px; }
    @media (max-width: 880px) {
      .pr-card { grid-template-columns: 32px 64px 1fr; gap: 12px; padding: 14px; }
      .pr-thumb { width: 64px; height: 64px; }
      .pr-prices { grid-column: 1 / -1; padding: 12px; justify-content: space-between; }
      .action-bar { top: 70px; }
    }
    @media (max-width: 480px) {
      .pr-card { grid-template-columns: 32px 1fr; }
      .pr-thumb { display: none; }
    }
    """

    body = f"""
    <div class="section-head">
      <div>
        <div class="eyebrow">Market intelligence</div>
        <h1 class="section-title">Price <span class="accent">Review</span></h1>
        <div class="section-sub">Live eBay comps vs your prices. Underpriced = leaving money on the table.</div>
      </div>
    </div>

    <div class="stat-grid">
      <div class="stat-card"><div class="num danger">{underpriced}</div><div class="lbl">Underpriced</div></div>
      <div class="stat-card"><div class="num warning">{overpriced}</div><div class="lbl">Overpriced</div></div>
      <div class="stat-card"><div class="num danger">${money_left:,.0f}</div><div class="lbl">Revenue Gap</div></div>
    </div>

    <div class="charts-row">
      <div class="chart-panel">
        <h3>Market Gap Distribution</h3>
        <div class="chart-wrap"><canvas id="chart-gap"></canvas></div>
      </div>
    </div>

    <div class="action-bar">
      <button onclick="selectAll(true)"  class="btn btn-ghost">Select All</button>
      <button onclick="selectAll(false)" class="btn btn-ghost">Deselect</button>
      <span id="count-label"></span>
      <div class="basis-toggle" role="tablist" aria-label="Compare against">
        <span class="basis-toggle-lbl">Compare vs:</span>
        <button class="basis-btn active" data-basis="market" onclick="setBasis('market')">Market <span class="basis-sub">eBay</span></button>
        <button class="basis-btn"        data-basis="actual" onclick="setBasis('actual')">Actual <span class="basis-sub">SCP</span></button>
      </div>
      <button onclick="applySelected()" class="btn btn-gold" style="margin-left:auto;">Apply to eBay →</button>
    </div>

    <div id="status-bar"></div>
    <div style="margin-bottom:16px;">
      <button id="rebuild-btn" onclick="rebuildSite()" class="btn btn-outline" style="display:none;">Trigger Rebuild</button>
    </div>

    <div class="pr-grid" id="review-body">
      {cards_html}
    </div>

    <script>
      const REPRICE_URL = '{lambda_url}';
      const REBUILD_URL = '{rebuild_url}';

      Chart.defaults.color = '#9a9388';
      Chart.defaults.font.family = "'Inter', sans-serif";
      new Chart(document.getElementById('chart-gap'), {{
        type: 'bar',
        data: {{
          labels: {list(gap_buckets.keys())!r},
          datasets: [{{
            label: 'Listings',
            data: {list(gap_buckets.values())},
            backgroundColor: ['rgba(224,123,111,.7)','rgba(224,181,74,.6)','rgba(127,199,122,.6)','rgba(224,181,74,.5)','rgba(212,175,55,.6)'],
            borderColor:    ['#e07b6f','#e0b54a','#7fc77a','#e0b54a','#d4af37'],
            borderWidth: 1.5,
            borderRadius: 6,
          }}]
        }},
        options: {{
          plugins: {{ legend: {{ display: false }} }},
          scales: {{
            y: {{ grid: {{ color: 'rgba(212,175,55,0.05)' }}, ticks: {{ color: '#9a9388', precision: 0 }} }},
            x: {{ grid: {{ display: false }}, ticks: {{ color: '#f1efe9' }} }}
          }}
        }}
      }});

      function updateCount() {{
        const total   = document.querySelectorAll('.row-check').length;
        const checked = document.querySelectorAll('.row-check:checked').length;
        document.getElementById('count-label').textContent = checked + ' of ' + total + ' selected';
      }}
      document.querySelectorAll('.row-check').forEach(cb => cb.addEventListener('change', updateCount));
      updateCount();

      // Market ↔ Actual basis toggle. Re-sorts the review list by the chosen
      // basis (worst gap first), persists choice in localStorage.
      function setBasis(basis) {{
        document.body.setAttribute('data-basis', basis);
        document.querySelectorAll('.basis-btn').forEach(b => {{
          b.classList.toggle('active', b.dataset.basis === basis);
        }});
        try {{ localStorage.setItem('priceReviewBasis', basis); }} catch (e) {{}}
        const body = document.getElementById('review-body');
        const cards = Array.from(body.querySelectorAll('.pr-card'));
        const attr = basis === 'actual' ? 'data-actual-gap' : 'data-market-gap';
        cards.sort((a, b) => {{
          const av = parseFloat(a.getAttribute(attr));
          const bv = parseFloat(b.getAttribute(attr));
          const aValid = !isNaN(av), bValid = !isNaN(bv);
          if (!aValid && !bValid) return 0;
          if (!aValid) return 1;
          if (!bValid) return -1;
          return Math.abs(bv) - Math.abs(av);
        }});
        cards.forEach(c => body.appendChild(c));
      }}
      (function() {{
        let basis = 'market';
        try {{ basis = localStorage.getItem('priceReviewBasis') || 'market'; }} catch (e) {{}}
        setBasis(basis);
      }})();

      function selectAll(val) {{
        document.querySelectorAll('.row-check').forEach(cb => cb.checked = val);
        updateCount();
      }}

      function showStatus(msg, kind) {{
        const bar = document.getElementById('status-bar');
        bar.className = 'status-' + kind;
        bar.style.display = 'block';
        bar.textContent = msg;
        bar.scrollIntoView({{ behavior: 'smooth', block: 'nearest' }});
      }}

      async function applySelected() {{
        const items = [];
        document.querySelectorAll('.row-check:checked').forEach(cb => {{
          const id    = cb.value;
          const field = document.querySelector('.price-after[data-id="' + id + '"]');
          const price = parseFloat((field ? field.innerText.trim() : '0').replace(/[^0-9.]/g, ''));
          if (id && !isNaN(price) && price > 0) items.push({{ item_id: id, price }});
        }});

        if (!items.length) {{ showStatus('No items selected.', 'warning'); return; }}
        showStatus('Applying ' + items.length + ' price(s) to eBay…', 'info');

        let updated = 0;
        const errors = [];  // {{item_id, error}} — shape compatible with LockTracker
        for (const item of items) {{
          try {{
            const resp = await fetch(REPRICE_URL, {{
              method: 'POST',
              headers: {{ 'Content-Type': 'application/json' }},
              body: JSON.stringify(item)
            }});
            const data = await resp.json();
            if (data.success) {{
              updated++;
              const card = document.querySelector('.row-check[value="' + item.item_id + '"]')?.closest('.pr-card');
              if (card) {{
                const cur = card.querySelector('.current-price');
                if (cur) cur.textContent = '$' + item.price.toFixed(2);
                card.querySelector('.row-check').checked = false;
                card.style.opacity = '0.45';
              }}
            }} else {{
              errors.push({{ item_id: item.item_id, error: data.error || 'failed' }});
            }}
          }} catch(e) {{
            errors.push({{ item_id: item.item_id, error: e.message }});
          }}
        }}

        LockTracker.consumeErrors(errors);
        if (updated > 0 && window.h2kConfetti) window.h2kConfetti();
        const errMsg = errors.length ? ' · ' + errors.length + ' failed (eBay-locked, now flagged 🔒)' : '';
        showStatus('Done. ' + updated + ' price(s) updated on eBay' + errMsg,
          updated > 0 ? 'success' : 'danger');
        if (updated > 0) document.getElementById('rebuild-btn').style.display = 'inline-flex';
      }}

      async function rebuildSite() {{
        const btn = document.getElementById('rebuild-btn');
        btn.disabled = true; btn.textContent = 'Rebuilding…';
        try {{
          const resp = await fetch(REBUILD_URL, {{ method: 'POST', headers: {{ 'Content-Type': 'application/json' }}, body: '{{}}' }});
          const data = await resp.json();
          if (data.success) showStatus('Site rebuild triggered. Live in ~2 minutes.', 'success');
          else {{ showStatus('Rebuild failed: ' + (data.error || 'Unknown'), 'danger'); btn.disabled = false; btn.textContent = 'Trigger Rebuild'; }}
        }} catch(e) {{ showStatus('Rebuild request failed: ' + e.message, 'danger'); btn.disabled = false; btn.textContent = 'Trigger Rebuild'; }}
      }}
    </script>"""

    out = OUTPUT_DIR / "price_review.html"
    out.write_text(html_shell(f"Price Review · {SELLER_NAME}", body, extra_head=f"<style>{extra_css}</style>", active_page="price_review.html"), encoding="utf-8")
    print(f"  Price review: {out}")
    return out


# ---------------------------------------------------------------------------
# Reddit cross-post page (reddit.html)
# ---------------------------------------------------------------------------

# Curated subreddit list — researched from active selling subs.
# r/SportsCardSales is the dedicated marketplace sub (strict format, high traffic).
# Others are collector subs that allow some selling activity.
_REDDIT_SUBS = [
    {"id": "SportsCardSales", "name": "r/SportsCardSales",   "tag": "[WTS]", "kind": "self",
     "note": "Dedicated marketplace · strict format · highest traffic for all sports cards"},
    {"id": "footballcards",   "name": "r/footballcards",     "tag": "[WTS]", "kind": "self",
     "note": "Football-specific community · selling allowed in flair-tagged posts"},
    {"id": "basketballcards", "name": "r/basketballcards",   "tag": "[WTS]", "kind": "self",
     "note": "Basketball-specific community"},
    {"id": "baseballcards",   "name": "r/baseballcards",     "tag": "[WTS]", "kind": "self",
     "note": "Baseball-specific community"},
    {"id": "Pokemoncardsales","name": "r/Pokemoncardsales",  "tag": "[WTS]", "kind": "self",
     "note": "Pokemon-specific marketplace"},
    {"id": "sportscards",     "name": "r/sportscards",       "tag": "[FS]",  "kind": "self",
     "note": "General community · selling in dedicated threads"},
]


def _suggest_subreddit(category: str) -> str:
    return {
        "Pokemon":            "Pokemoncardsales",
        "Football Lots":      "SportsCardSales",
        "Football Singles":   "SportsCardSales",
        "Basketball Lots":    "basketballcards",
        "Basketball Singles": "basketballcards",
        "Baseball Lots":      "baseballcards",
        "Baseball Singles":   "baseballcards",
    }.get(category, "SportsCardSales")


def _reddit_default_post(l: dict) -> tuple[str, str]:
    """Generate (title, body) defaults that conform to r/SportsCardSales rules."""
    try:
        price_f = float(l["price"])
    except (ValueError, TypeError):
        price_f = 0.0
    cat = _categorize(l)
    title = f"[WTS] {l['title'][:200]} — ${price_f:.2f}"
    body_lines = [
        f"**{l['title']}**",
        "",
        f"**Price: ${price_f:.2f}** — coined, firm.",
        f"**Condition:** {l['condition'] or 'See photos in album'}",
        f"**Category:** {cat}",
        "",
        "*(Replace the line below with an Imgur album URL showing photos + a paper with your Reddit username + today's date — required by most sales subs.)*",
        "**Photos:** [imgur.com/a/REPLACE_ME]",
        "",
        "**Shipping:** PWE for singles · BMWT for lots and higher-value items · Insurance available on request.",
        "",
        "**Payment:** eBay-managed checkout only — PayPal, Visa, Mastercard, AmEx, Discover, Apple Pay, Google Pay. All transactions covered by eBay's Money Back Guarantee. **No DM sales, no Venmo / Zelle / Cash App / crypto.**",
        "",
        f"**Buy It Now (one eBay link per post — sub rule):** {l['url']}",
    ]
    body = "\n".join(body_lines)
    return title, body


def build_reddit(listings: list[dict]) -> Path:
    """
    Reddit cross-post page. Pick a listing → composer pre-fills title + body
    in the proper r/SportsCardSales format → click Post to send via Lambda.
    """
    sorted_l = sorted(listings, key=lambda x: float(x["price"]) if x["price"] else 0, reverse=True)

    # Build per-listing JSON payload to drive the composer client-side
    import json as _json
    payloads = {}
    for l in sorted_l:
        cat = _categorize(l)
        title, body = _reddit_default_post(l)
        payloads[l["item_id"]] = {
            "id":       l["item_id"],
            "title":    title,
            "body":     body,
            "subreddit": _suggest_subreddit(cat),
            "ebay_url": l["url"],
            "img":      l["pic"],
            "category": cat,
            "price":    float(l["price"]) if l["price"] else 0,
        }
    payload_json = _json.dumps(payloads)
    subs_json = _json.dumps(_REDDIT_SUBS)

    # Build picker tiles
    tiles = []
    for l in sorted_l:
        try: price_f = float(l["price"])
        except: price_f = 0.0
        cat = _categorize(l)
        thumb = f'<img src="{l["pic"]}" alt="" loading="lazy">' if l["pic"] else ''
        tiles.append(f'''
        <button type="button" class="rd-tile" data-id="{l['item_id']}" onclick="rdSelect('{l['item_id']}')">
          <div class="rd-tile-img">{thumb}</div>
          <div class="rd-tile-info">
            <div class="rd-tile-cat">{cat}</div>
            <div class="rd-tile-title">{l['title'][:64]}</div>
            <div class="rd-tile-price">${price_f:.2f}</div>
          </div>
        </button>''')

    extra_css = """
    .rd-layout {
      display: grid;
      grid-template-columns: minmax(0, 320px) minmax(0, 1fr);
      gap: 22px;
      align-items: start;
    }
    .rd-picker {
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: var(--r-lg);
      padding: 16px;
      max-height: calc(100vh - 140px);
      overflow-y: auto;
      position: sticky; top: 90px;
    }
    .rd-picker h3 { font-family: 'Bebas Neue', sans-serif; font-size: 18px; letter-spacing: .03em; color: var(--text); margin-bottom: 12px; }
    .rd-search { margin-bottom: 12px; }
    .rd-tiles { display: grid; gap: 8px; }
    .rd-tile {
      display: grid; grid-template-columns: 56px 1fr; gap: 10px;
      padding: 8px; border: 1px solid var(--border); border-radius: var(--r-sm);
      background: var(--surface-2); cursor: pointer;
      text-align: left; align-items: center;
      transition: all var(--t-fast); width: 100%;
      font-family: inherit; color: inherit;
    }
    .rd-tile:hover { border-color: var(--border-mid); background: var(--surface-3); }
    .rd-tile.active { border-color: var(--gold); background: rgba(212,175,55,.06); }
    .rd-tile-img { width: 56px; height: 56px; border-radius: var(--r-sm); overflow: hidden; background: #111; }
    .rd-tile-img img { width: 100%; height: 100%; object-fit: cover; }
    .rd-tile-info { min-width: 0; }
    .rd-tile-cat { font-size: 9px; letter-spacing: .15em; text-transform: uppercase; color: var(--gold); font-weight: 700; margin-bottom: 2px; }
    .rd-tile-title {
      font-size: 12px; color: var(--text); line-height: 1.3;
      display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden;
      margin-bottom: 2px;
    }
    .rd-tile-price { font-family: 'Bebas Neue', sans-serif; font-size: 16px; color: var(--gold); }

    .rd-composer {
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: var(--r-lg);
      padding: 22px;
    }
    .rd-empty {
      padding: 60px 20px; text-align: center;
      color: var(--text-muted);
      border: 1px dashed var(--border-mid);
      border-radius: var(--r-md);
    }
    .rd-empty .big { font-family: 'Bebas Neue', sans-serif; font-size: 32px; color: var(--gold); margin-bottom: 6px; }
    .rd-form { display: none; }
    .rd-form.show { display: block; }
    .rd-form-row { margin-bottom: 14px; }
    .rd-form-row label { display: block; font-size: 10px; letter-spacing: .18em; text-transform: uppercase; color: var(--text-muted); font-weight: 700; margin-bottom: 6px; }
    .rd-sub-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(180px, 1fr)); gap: 8px; }
    .rd-sub {
      padding: 10px 12px;
      background: var(--surface-2);
      border: 1px solid var(--border);
      border-radius: var(--r-sm);
      cursor: pointer;
      transition: all var(--t-fast);
    }
    .rd-sub:hover { border-color: var(--border-mid); }
    .rd-sub.active { border-color: var(--gold); background: rgba(212,175,55,.08); }
    .rd-sub-name { font-weight: 700; color: var(--gold); font-size: 13px; margin-bottom: 2px; }
    .rd-sub-note { font-size: 11px; color: var(--text-muted); line-height: 1.35; }
    .rd-form textarea { font-family: 'JetBrains Mono', monospace; font-size: 13px; min-height: 220px; resize: vertical; }
    .rd-form .rd-title-input { font-weight: 600; }
    .rd-actions { display: flex; gap: 10px; flex-wrap: wrap; align-items: center; margin-top: 12px; }
    .rd-preview {
      margin-top: 18px;
      padding: 16px;
      background: #0d0d0d;
      border: 1px solid var(--border);
      border-radius: var(--r-md);
      font-family: 'JetBrains Mono', monospace; font-size: 12px;
      color: var(--text-muted);
      white-space: pre-wrap;
      max-height: 320px;
      overflow-y: auto;
    }
    .rd-preview .pv-title { color: var(--gold); font-weight: 700; font-family: inherit; font-size: 13px; padding-bottom: 8px; margin-bottom: 8px; border-bottom: 1px dashed var(--border); }
    @media (max-width: 880px) {
      .rd-layout { grid-template-columns: 1fr; }
      .rd-picker { max-height: 320px; position: relative; top: 0; }
    }
    """

    body = f"""
    <div class="section-head">
      <div>
        <div class="eyebrow">Cross-post to Reddit</div>
        <h1 class="section-title">Reddit <span class="accent">Cross-Post</span></h1>
        <div class="section-sub">Pick a listing on the left, refine the post, choose a subreddit, send. r/SportsCardSales pre-selected — biggest dedicated sales sub.</div>
      </div>
    </div>

    <div class="rd-layout">
      <aside class="rd-picker">
        <h3>Pick a listing</h3>
        <input type="search" class="rd-search search-input" id="rd-search" placeholder="Filter…" oninput="rdFilter()">
        <div class="rd-tiles">{''.join(tiles)}</div>
      </aside>

      <section class="rd-composer">
        <div id="rd-empty" class="rd-empty">
          <div class="big">No listing selected</div>
          <div>Pick a listing from the panel to begin composing.</div>
        </div>

        <form id="rd-form" class="rd-form" onsubmit="event.preventDefault(); rdSubmit();">
          <div class="rd-form-row">
            <label>Subreddit</label>
            <div class="rd-sub-grid" id="rd-sub-grid"></div>
          </div>
          <div class="rd-form-row">
            <label>Post title (300 char max — keep [WTS] tag)</label>
            <input type="text" id="rd-title" class="rd-title-input" maxlength="300">
          </div>
          <div class="rd-form-row">
            <label>Post body (Markdown supported)</label>
            <textarea id="rd-body"></textarea>
          </div>

          <div id="status-bar"></div>
          <div class="rd-actions">
            <button type="button" class="btn btn-ghost" onclick="rdCopy()">Copy text</button>
            <a id="rd-eitr" target="_blank" rel="noopener" class="btn btn-ghost">View eBay</a>
            <a id="rd-open-reddit" href="#" target="_blank" rel="noopener" class="btn btn-outline" onclick="rdOpenReddit(event)">
              Open Reddit Submit Page →
            </a>
            <button type="submit" class="btn btn-gold" style="margin-left:auto;">Post via API →</button>
          </div>
          <div style="margin-top:8px;font-size:11px;color:var(--text-dim);letter-spacing:.04em;">
            Tip: <strong style="color:var(--text-muted);">Open Reddit Submit Page</strong> opens reddit.com with title + body pre-filled — no API needed. <strong style="color:var(--text-muted);">Post via API</strong> sends directly (requires deployed Lambda + Reddit credentials).
          </div>

          <div class="rd-preview" id="rd-preview"></div>
        </form>
      </section>
    </div>

    <script>
      const REDDIT_URL = '{LAMBDA_BASE}/reddit-post';
      const PAYLOADS = {payload_json};
      const SUBS = {subs_json};
      let activeId = null;
      let activeSub = null;

      // Render subreddit chips
      function rdRenderSubs(selected) {{
        const grid = document.getElementById('rd-sub-grid');
        grid.innerHTML = SUBS.map(s => `
          <button type="button" class="rd-sub${{s.id === selected ? ' active' : ''}}" data-sub="${{s.id}}" onclick="rdPickSub('${{s.id}}')">
            <div class="rd-sub-name">${{s.name}}</div>
            <div class="rd-sub-note">${{s.note}}</div>
          </button>`).join('');
        activeSub = selected;
      }}
      function rdPickSub(id) {{
        activeSub = id;
        document.querySelectorAll('.rd-sub').forEach(b => b.classList.toggle('active', b.dataset.sub === id));
        rdUpdatePreview();
      }}

      function rdSelect(id) {{
        activeId = id;
        const p = PAYLOADS[id];
        document.querySelectorAll('.rd-tile').forEach(t => t.classList.toggle('active', t.dataset.id === id));
        document.getElementById('rd-empty').style.display = 'none';
        document.getElementById('rd-form').classList.add('show');
        document.getElementById('rd-title').value = p.title;
        document.getElementById('rd-body').value  = p.body;
        document.getElementById('rd-eitr').href   = p.ebay_url;
        rdRenderSubs(p.subreddit);
        rdUpdatePreview();
      }}

      function rdUpdatePreview() {{
        const t = document.getElementById('rd-title').value;
        const b = document.getElementById('rd-body').value;
        document.getElementById('rd-preview').innerHTML =
          '<div class="pv-title">' + (t || '(untitled)') + '</div>' +
          (b || '(empty body)').replace(/[<>]/g, c => c === '<' ? '&lt;' : '&gt;');
        if (activeId) {{
          document.getElementById('rd-open-reddit').href = rdSubmitUrl();
        }}
      }}
      document.getElementById('rd-title').addEventListener('input', rdUpdatePreview);
      document.getElementById('rd-body').addEventListener('input', rdUpdatePreview);

      function rdFilter() {{
        const q = document.getElementById('rd-search').value.toLowerCase();
        document.querySelectorAll('.rd-tile').forEach(t => {{
          const hit = t.textContent.toLowerCase().includes(q);
          t.style.display = hit ? '' : 'none';
        }});
      }}

      async function rdCopy() {{
        const t = document.getElementById('rd-title').value;
        const b = document.getElementById('rd-body').value;
        try {{
          await navigator.clipboard.writeText(t + '\\n\\n' + b);
          showToast('Copied. Now click "Open Reddit Submit Page" to paste.');
        }} catch(e) {{ showToast('Copy failed: ' + e.message); }}
      }}

      function rdSubmitUrl() {{
        const sub = activeSub || 'SportsCardSales';
        const t   = document.getElementById('rd-title').value;
        const b   = document.getElementById('rd-body').value;
        // Reddit's submit URL accepts title + text query params and pre-fills the form
        return 'https://www.reddit.com/r/' + encodeURIComponent(sub) + '/submit?'
             + 'title=' + encodeURIComponent(t)
             + '&text=' + encodeURIComponent(b)
             + '&type=TEXT';
      }}

      function rdOpenReddit(ev) {{
        if (!activeId) {{
          ev.preventDefault();
          rdStatus('Select a listing first.', 'warning');
          return;
        }}
        // Update href just-in-time to capture latest title/body edits
        document.getElementById('rd-open-reddit').href = rdSubmitUrl();
      }}

      function rdStatus(msg, kind) {{
        const bar = document.getElementById('status-bar');
        bar.className = 'status-' + kind;
        bar.style.display = 'block';
        bar.textContent = msg;
        bar.scrollIntoView({{ behavior:'smooth', block:'nearest' }});
      }}

      async function rdSubmit() {{
        if (!activeId || !activeSub) {{ rdStatus('Select a listing and subreddit first.', 'warning'); return; }}
        const payload = {{
          item_id:   activeId,
          subreddit: activeSub,
          title:     document.getElementById('rd-title').value,
          body:      document.getElementById('rd-body').value,
        }};
        rdStatus('Posting to r/' + activeSub + '…', 'info');
        try {{
          const resp = await fetch(REDDIT_URL, {{
            method:  'POST',
            headers: {{ 'Content-Type': 'application/json' }},
            body:    JSON.stringify(payload),
          }});
          const data = await resp.json();
          if (data.success) {{
            rdStatus('Posted! ' + (data.url ? 'View: ' + data.url : ''), 'success');
            if (data.url) window.open(data.url, '_blank');
          }} else if (data.error && data.error.includes('not deployed')) {{
            rdStatus('Reddit Lambda not deployed yet. Use Copy → paste at reddit.com/r/' + activeSub + '/submit (see README setup steps).', 'warning');
          }} else {{
            rdStatus('Failed: ' + (data.error || 'Unknown'), 'danger');
          }}
        }} catch(e) {{
          rdStatus('Reddit endpoint unreachable. Use Copy → paste manually. (' + e.message + ')', 'warning');
        }}
      }}
    </script>
    """

    out = OUTPUT_DIR / "reddit.html"
    out.write_text(html_shell(f"Reddit Cross-Post · {SELLER_NAME}", body, extra_head=f"<style>{extra_css}</style>", active_page="reddit.html"), encoding="utf-8")
    print(f"  Reddit cross-post: {out}")
    return out


def build_return_policy() -> Path:
    extra_css = """
    .policy { max-width: 760px; margin: 0 auto; }
    .policy-section {
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: var(--r-lg);
      padding: 24px 28px;
      margin-bottom: 14px;
    }
    .policy-section h2 {
      font-family: 'Bebas Neue', sans-serif;
      font-size: 22px;
      letter-spacing: .03em;
      color: var(--gold);
      margin-bottom: 10px;
    }
    .policy-section p { color: var(--text); line-height: 1.7; font-size: 14.5px; margin-bottom: 10px; }
    .policy-section p:last-child { margin-bottom: 0; }
    """
    body = f"""
    <div class="policy">
      <div class="section-head">
        <div>
          <div class="eyebrow">Buyer Protection</div>
          <h1 class="section-title">Return <span class="accent">Policy</span></h1>
          <div class="section-sub">Seller: {SELLER_NAME} · eBay store: <a href="{STORE_URL}" target="_blank" rel="noopener" class="seller-link">{STORE_URL}</a></div>
        </div>
      </div>

      <div class="policy-section">
        <h2>Returns</h2>
        <p>This seller does not accept returns. All sales are final. Please review all photos, descriptions, and ask any questions before purchasing.</p>
        <p>If an item arrives damaged or is significantly not as described, contact us through eBay messages and we will work to resolve the issue.</p>
      </div>

      <div class="policy-section">
        <h2>Non-defective Returns</h2>
        <p>Returns are not accepted for buyer remorse, changed mind, or items ordered by mistake.</p>
      </div>

      <div class="policy-section">
        <h2>Refunds</h2>
        <p>Refunds are only issued in cases where an item arrives damaged or is significantly not as described. Contact us through eBay messages before opening a case.</p>
      </div>

      <div class="policy-section">
        <h2>Exchanges</h2>
        <p>We do not offer exchanges.</p>
      </div>

      <div class="policy-section">
        <h2>How to Report a Problem</h2>
        <p>If there is a problem with your order, send a message through eBay: <a href="{STORE_URL}" target="_blank" rel="noopener">{STORE_URL}</a></p>
      </div>

      <div style="text-align:center;color:var(--text-dim);font-size:11px;letter-spacing:.16em;text-transform:uppercase;margin-top:24px;">
        Last updated: {datetime.now(timezone.utc).strftime('%B %d, %Y')}
      </div>
    </div>
    """
    out = OUTPUT_DIR / "return-policy.html"
    out.write_text(html_shell(f"Return Policy · {SELLER_NAME}", body, extra_head=f"<style>{extra_css}</style>", active_page="return-policy.html"), encoding="utf-8")
    print(f"  Return policy: {out}")
    return out



# ---------------------------------------------------------------------------
# 6. Title review page (title_review.html) + local apply server
# ---------------------------------------------------------------------------

def build_title_review(listings: list[dict]) -> Path:
    """
    Premium title review: side-by-side diff cards with character counter.
    Apply pushes to Lambda /ebay/revise.
    """
    locks = load_locks()
    lambda_url  = f"{LAMBDA_BASE}/revise"
    rebuild_url = f"{LAMBDA_BASE}/rebuild"

    cards = []
    total_gain = 0
    for l in listings:
        suggested = _suggest_title(l)
        original  = l["title"].strip()
        if suggested.lower() == _re.sub(r' {2,}', ' ', original).lower():
            continue

        char_gain = len(suggested) - len(original.strip())
        total_gain += char_gain
        gain_color = "var(--success)" if char_gain > 0 else "var(--warning)"
        gain_label = f"+{char_gain}" if char_gain > 0 else f"{char_gain}"
        pct = round(min(100, len(suggested) / 80 * 100))
        bar_color = "var(--success)" if len(suggested) <= 80 else "var(--danger)"

        thumb_html = f'<img src="{l["pic"]}" alt="" loading="lazy">' if l["pic"] else ''

        lock_info = locks.get(l["item_id"])
        is_locked = bool(lock_info)
        lock_attr = f'data-locked="{lock_info["code"]}"' if is_locked else ""
        check_attrs = "disabled" if is_locked else "checked"
        lock_inline = ""
        if is_locked:
            label = "Title locked by eBay" if lock_info.get("code") == "240" else ("Listing ended" if lock_info.get("code") == "291" else "Locked")
            lock_reason = lock_info.get("reason", "")
            lock_inline = f'<span class="badge badge-danger" style="margin-left:8px;" title="{lock_reason}">🔒 {label}</span>'

        cards.append(f'''
      <article class="tr-card review-row" data-id="{l['item_id']}" {lock_attr}>
        <header class="tr-head">
          <input type="checkbox" class="row-check" value="{l['item_id']}" {check_attrs} aria-label="Select for revision"{' title="eBay refuses to revise this title"' if is_locked else ''}>
          <div class="tr-thumb">{thumb_html}</div>
          <div class="tr-id">
            <a href="{l['url']}" target="_blank" rel="noopener" class="font-mono" style="font-size:11px;color:var(--text-muted);">#{l['item_id']}</a>
            {lock_inline}
            <a href="{l['url']}" target="_blank" rel="noopener" class="btn btn-ghost" style="padding:6px 12px;font-size:11px;">View on eBay</a>
          </div>
        </header>
        <div class="tr-bodies">
          <div class="tr-version tr-before">
            <div class="tr-lbl">Current</div>
            <div class="title-before">{original}</div>
            <div class="tr-charcount">{len(original)} chars</div>
          </div>
          <div class="tr-arrow"><span>→</span></div>
          <div class="tr-version tr-after">
            <div class="tr-lbl">Optimized · tap to edit</div>
            <div class="title-after" contenteditable="true" data-id="{l['item_id']}" spellcheck="false">{suggested}</div>
            <div class="tr-charcount">
              <span style="color:{bar_color};">{len(suggested)} chars</span>
              <span style="color:{gain_color};font-weight:700;">({gain_label})</span>
              <span class="tr-progress"><span class="tr-progress-fill" style="width:{pct}%;background:{bar_color};"></span></span>
            </div>
          </div>
        </div>
      </article>''')

    if not cards:
        cards_html = '<div class="panel" style="text-align:center;padding:40px;color:var(--text-muted);">All titles are already optimized.</div>'
    else:
        cards_html = "\n".join(cards)

    extra_css = """
    .tr-grid { display: grid; gap: 14px; }
    .tr-card {
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: var(--r-lg);
      overflow: hidden;
      transition: all var(--t-fast);
    }
    .tr-card:hover { border-color: var(--border-mid); }
    .tr-head {
      display: flex; align-items: center; gap: 14px;
      padding: 12px 18px;
      background: var(--surface-2);
      border-bottom: 1px solid var(--border);
    }
    .tr-thumb { width: 44px; height: 44px; border-radius: var(--r-sm); overflow: hidden; background: var(--surface-3); flex-shrink: 0; }
    .tr-thumb img { width: 100%; height: 100%; object-fit: cover; }
    .tr-id { flex: 1; display: flex; align-items: center; justify-content: space-between; gap: 12px; }
    .tr-bodies {
      display: grid;
      grid-template-columns: 1fr 40px 1fr;
      gap: 0;
    }
    .tr-version { padding: 18px 22px; min-width: 0; }
    .tr-after { background: rgba(212,175,55,0.04); border-left: 1px solid var(--border); }
    .tr-lbl { font-size: 10px; color: var(--text-muted); letter-spacing: .18em; text-transform: uppercase; font-weight: 700; margin-bottom: 8px; }
    .title-before {
      color: var(--text-muted); font-size: 13.5px; line-height: 1.45;
      padding: 8px 0; border-bottom: 1px dashed var(--border);
      margin-bottom: 8px;
      text-decoration: line-through; text-decoration-color: rgba(224,123,111,0.4);
      text-decoration-thickness: 1px;
    }
    .title-after {
      color: var(--text); font-size: 14px; font-weight: 600; line-height: 1.45;
      padding: 8px 12px; margin-bottom: 8px;
      background: var(--surface-3);
      border: 1px dashed var(--gold-dim);
      border-radius: var(--r-sm);
      outline: none;
      cursor: text;
      caret-color: var(--gold);
      transition: all var(--t-fast);
      word-break: break-word;
    }
    .title-after:focus { border-style: solid; border-color: var(--gold); background: rgba(212,175,55,.06); }
    .tr-charcount { display: flex; align-items: center; gap: 8px; font-size: 11px; color: var(--text-muted); font-weight: 600; }
    .tr-progress { flex: 1; height: 4px; background: var(--surface-3); border-radius: 999px; overflow: hidden; max-width: 120px; margin-left: auto; }
    .tr-progress-fill { display: block; height: 100%; transition: width var(--t-base); }
    .tr-arrow {
      display: flex; align-items: center; justify-content: center;
      color: var(--gold);
      font-size: 22px;
      background: linear-gradient(180deg, transparent, rgba(212,175,55,.04), transparent);
    }
    .action-bar {
      position: sticky; top: 76px; z-index: 50;
      display: flex; gap: 10px; align-items: center; flex-wrap: wrap;
      padding: 14px 18px; margin-bottom: 16px;
      background: rgba(20,20,20,.92); backdrop-filter: blur(10px);
      border: 1px solid var(--border-mid);
      border-radius: var(--r-md);
    }
    #count-label { font-size: 12px; color: var(--text-muted); letter-spacing: .14em; text-transform: uppercase; font-weight: 700; }
    @media (max-width: 720px) {
      .tr-bodies { grid-template-columns: 1fr; }
      .tr-after { border-left: none; border-top: 1px solid var(--border); }
      .tr-arrow { display: none; }
      .action-bar { top: 70px; }
    }
    """

    body = f"""
    <div class="section-head">
      <div>
        <div class="eyebrow">SEO optimization</div>
        <h1 class="section-title">Title <span class="accent">Review</span></h1>
        <div class="section-sub">{len(cards)} listings have suggested SEO improvements. Total +{total_gain} chars of search keywords.</div>
      </div>
    </div>

    <div class="action-bar">
      <button onclick="selectAll(true)"  class="btn btn-ghost">Select All</button>
      <button onclick="selectAll(false)" class="btn btn-ghost">Deselect</button>
      <span id="count-label"></span>
      <button onclick="applySelected()" class="btn btn-gold" style="margin-left:auto;">Apply to eBay →</button>
    </div>

    <div id="status-bar"></div>
    <div style="margin-bottom:16px;">
      <button id="rebuild-btn" onclick="rebuildSite()" class="btn btn-outline" style="display:none;">Trigger Rebuild</button>
    </div>

    <div class="tr-grid" id="review-body">
      {cards_html}
    </div>

    <script>
      const LAMBDA_URL  = '{lambda_url}';
      const REBUILD_URL = '{rebuild_url}';

      function updateCount() {{
        const total   = document.querySelectorAll('.row-check').length;
        const checked = document.querySelectorAll('.row-check:checked').length;
        document.getElementById('count-label').textContent = checked + ' of ' + total + ' selected';
      }}
      document.querySelectorAll('.row-check').forEach(cb => cb.addEventListener('change', updateCount));
      updateCount();

      function selectAll(val) {{
        document.querySelectorAll('.row-check').forEach(cb => cb.checked = val);
        updateCount();
      }}

      function showStatus(msg, kind) {{
        const bar = document.getElementById('status-bar');
        bar.className = 'status-' + kind;
        bar.style.display = 'block';
        bar.textContent = msg;
        bar.scrollIntoView({{ behavior: 'smooth', block: 'nearest' }});
      }}

      async function applySelected() {{
        const items = [];
        document.querySelectorAll('.row-check:checked').forEach(cb => {{
          const id = cb.value;
          const after = document.querySelector('.title-after[data-id="' + id + '"]');
          items.push({{ item_id: id, title: after ? after.innerText.trim() : '' }});
        }});

        if (!items.length) {{ showStatus('No items selected.', 'warning'); return; }}
        showStatus('Applying ' + items.length + ' title(s) to eBay…', 'info');

        try {{
          const resp = await fetch(LAMBDA_URL, {{
            method: 'POST',
            headers: {{ 'Content-Type': 'application/json' }},
            body: JSON.stringify({{ items }})
          }});
          const data = await resp.json();
          if (data.success) {{
            const updated = data.updated;
            const failedIds = new Set((data.errors || []).map(e => e.item_id));
            items.forEach(it => {{
              if (failedIds.has(it.item_id)) return; // don't dim eBay-rejected rows
              const card = document.querySelector('.row-check[value="' + it.item_id + '"]')?.closest('.tr-card');
              if (card) {{
                const before = card.querySelector('.title-before');
                const after  = card.querySelector('.title-after[data-id="' + it.item_id + '"]');
                if (before && after) before.textContent = after.innerText.trim();
                card.querySelector('.row-check').checked = false;
                card.style.opacity = '0.45';
              }}
            }});
            LockTracker.consumeErrors(data.errors || []);
            if (updated > 0 && window.h2kConfetti) window.h2kConfetti();
            const errs = data.errors && data.errors.length ? ' · ' + data.errors.length + ' failed (eBay-locked, now flagged 🔒)' : '';
            showStatus('Done. ' + updated + ' listing(s) updated on eBay' + errs, 'success');
            document.getElementById('rebuild-btn').style.display = 'inline-flex';
          }} else {{
            showStatus('Error: ' + (data.error || 'Unknown error'), 'danger');
          }}
        }} catch(e) {{ showStatus('Request failed: ' + e.message, 'danger'); }}
      }}

      async function rebuildSite() {{
        const btn = document.getElementById('rebuild-btn');
        btn.disabled = true; btn.textContent = 'Rebuilding…';
        try {{
          const resp = await fetch(REBUILD_URL, {{ method: 'POST', headers: {{ 'Content-Type': 'application/json' }}, body: '{{}}' }});
          const data = await resp.json();
          if (data.success) showStatus('Site rebuild triggered. Live in ~2 minutes.', 'success');
          else {{ showStatus('Rebuild failed: ' + (data.error || 'Unknown'), 'danger'); btn.disabled = false; btn.textContent = 'Trigger Rebuild'; }}
        }} catch(e) {{ showStatus('Rebuild request failed: ' + e.message, 'danger'); btn.disabled = false; btn.textContent = 'Trigger Rebuild'; }}
      }}
    </script>"""

    out = OUTPUT_DIR / "title_review.html"
    out.write_text(html_shell(f"Title Review · {SELLER_NAME}", body, extra_head=f"<style>{extra_css}</style>", active_page="title_review.html"), encoding="utf-8")
    print(f"  Title review: {out}")
    return out


# ---------------------------------------------------------------------------
# Auto-fix: push quality improvements back to eBay via ReviseItem
# ---------------------------------------------------------------------------

import re as _re

# ---------------------------------------------------------------------------
# Per-listing hand-crafted SEO titles
# Keys are eBay item IDs. Values are the optimized title strings.
# Rules:
#   - Max 80 characters (eBay hard limit)
#   - Front-load the most searched keywords (player name, year, set, parallel)
#   - Include: player name, year, brand/set, card number, parallel/color, RC if rookie
#   - For lots: player name, HOF if applicable, number of cards, key brands, era
#   - Never keyword stuff — every word must be a real search term buyers use
#   - No ALL CAPS, no punctuation spam, no filler words
# ---------------------------------------------------------------------------

_SEO_TITLES = {
    # --- Wild Card 5 Card Draw (2026) ---
    "306927028439": "2026 Wild Card 5 Card Draw Justin Jefferson Stacked Deck Black Tie Aces #2/2",
    "306927035291": "2026 Wild Card 5 Card Draw Baker Mayfield Stacked Deck Black Tie King #1/1",
    "306927040476": "2026 Wild Card 5 Card Draw Germie Bernard Black Tie Kings #4/4 Steelers RC",

    # --- HOF Lot listings (90s cards) ---
    "306784122664": "Deion Sanders Atlanta Falcons Football Card Lot (6) NFL HOF Prime Time",
    "306785163679": "Junior Seau San Diego Chargers Football Card Lot (13) Includes Rookie Cards RC",
    "306785270903": "Marshall Faulk San Diego Chargers Indianapolis Colts Football Card Lot (3) HOF",
    "306903933988": "Roger Craig San Francisco 49ers Minnesota Vikings Football Card Lot (8) HOF",
    "306903937710": "Jerome Bettis Los Angeles Rams Notre Dame Football Card Lot (10) HOF The Bus",
    "306903941543": "Tim Brown Los Angeles Raiders Football Card Lot (14) HOF Wide Receiver",
    "306903947932": "Carl Banks New York Giants Football Card Lot (8) Super Bowl LB",
    "306904068997": "Marcus Allen Los Angeles Raiders Kansas City Chiefs Football Card Lot (11) HOF",
    "306904078786": "Steve Atwater Denver Broncos Football Card Lot (7) Includes Rookie Cards RC HOF",
    "306904174454": "Boomer Esiason Cincinnati Bengals New York Jets Football Card Lot (7)",
    "306904178257": "John Elway Denver Broncos Football Card Lot (10) HOF Super Bowl QB",
    "306783987628": "Emmitt Smith Dallas Cowboys Football Card Lot (15) HOF No Duplicates",
    "306844574522": "Jerry Rice San Francisco 49ers Football Card Lot (15) HOF Topps Fleer Score 90s",
    "306844558345": "Steve Young San Francisco 49ers Football Card Lot (18) HOF Topps Fleer Score 90s",
    "306844611599": "Sterling Sharpe Green Bay Packers Football Card Lot (21) 1989-1994 Topps Fleer",

    # --- 2025 Panini Prizm Draft Picks singles ---
    "306903423536": "2025 Panini Prizm Draft Picks Joe Burrow On Campus #OC-14 NFL SP",
    "306926059250": "2025 Panini Prizm Draft Picks Joe Burrow On Campus #OC-14 NFL Football",
    "306914214448": "2025 Panini Donruss Optic Shedeur Sanders Rated Rookie RC #203 Stars Prizm",
    "306914172219": "2025 Panini Prizm Draft Picks Caleb Downs RC #159 Green Prizm Football",
    "306914195022": "2025 Panini Prizm Draft Picks Drew Allar RC Fearless #F-DAR Gold Ice Prizm",
    "306914175824": "2025 Panini Prizm Draft Picks Cam Ward Instant Impact #II-CWD Gold Ice Prizm",
    "306914248275": "2025 Panini Prizm Draft Picks Carnell Tate RC #68 Gold Ice Prizm Football",
    "306914908485": "2025 Panini Prizm Draft Picks Ashton Jeanty RC #13 Gold Ice Prizm Football",
    "306914915295": "2025 Panini Prizm Draft Picks Travis Hunter RC #20 Silver Prizm Football",

    # --- Rule-based fallback lot listings that need hand-crafted titles ---
    "306914500757": "Eric Metcalf Cleveland Browns Football Card Lot (10) NFL Wide Receiver",
    "306914547105": "Andre Rison Indianapolis Colts Atlanta Falcons Football Card Lot (12) RC NFL",

    # --- Pokemon ---
    "306758076966": "Charcadet 022 Mega Evolution Promo Holo Pokemon Card NM",
}

# For listings not in the hand-crafted dict, apply rule-based improvements
def _rule_based_title(listing: dict) -> str:
    title = listing["title"].strip()
    title = _re.sub(r' {2,}', ' ', title)  # collapse double spaces

    t_lower = title.lower()

    # Detect listing type
    is_lot     = any(w in t_lower for w in ["lot", "cards", "x different", "no duplicates"])
    is_prizm   = any(w in t_lower for w in ["prizm", "optic", "donruss", "panini"])
    is_pokemon = any(w in t_lower for w in ["pokemon", "pikachu", "charizard", "charcadet",
                                             "promo", "mega evolution", "holo", "trainer"])
    is_basketball = any(w in t_lower for w in _BASKETBALL_TEAMS) or "nba" in t_lower or "basketball" in t_lower
    is_baseball   = any(w in t_lower for w in _BASEBALL_TEAMS)   or "mlb" in t_lower or "baseball" in t_lower

    # Pokemon, basketball, baseball: keep their own keywords; don't bolt on football/NFL terms
    if is_pokemon or is_basketball or is_baseball:
        return title[:80].strip()

    # Add "Football Card Lot" to lot listings missing it
    if is_lot and "football" not in t_lower:
        suffix = " Football Card Lot"
        if len(title) + len(suffix) <= 80:
            title += suffix
            t_lower = title.lower()

    # Add "NFL" to short football titles missing it
    if "nfl" not in t_lower and len(title) < 65:
        if len(title) + len(" NFL") <= 80:
            title += " NFL"
            t_lower = title.lower()

    # Add "Football" to Prizm/Panini titles missing it
    if is_prizm and "football" not in t_lower:
        if len(title) + len(" Football") <= 80:
            title += " Football"

    return title[:80].strip()


# ---------------------------------------------------------------------------
# Best-practice text helpers — applied to AI-generated titles
# ---------------------------------------------------------------------------
# Fluff/hype words that hurt eBay search rank + buyer trust. Stripped from
# suggested titles. Source: official eBay seller guidelines + best-practice
# prompt published by Claude (see commit message "Align AI to eBay best...").
_FLUFF_WORDS = [
    r"\bL@@K\b", r"\bLOOK\b", r"\bWow\b", r"\bWOW\b", r"\bAmazing\b", r"\bAMAZING\b",
    r"\bMust Have\b", r"\bMust-Have\b", r"\bRare Find\b", r"\bSweet\b",
    r"\bStunning\b", r"\bBeautiful\b", r"\bGorgeous\b", r"\bAwesome\b",
    r"\bBuy Now\b", r"\bDon't Miss\b", r"\bSteal\b", r"\bDeal\b",
    r"\bHOT\b(?! Wheels)",  # "HOT Wheels" is a real brand, "HOT" alone is hype
]
# Acronyms / brand words that should stay all-caps despite the Title-Case rule
_KEEP_CAPS = {
    "NFL", "NBA", "MLB", "NHL", "MLS", "RC", "PSA", "BGS", "SGC", "MVP", "HOF",
    "USA", "DC", "TCG", "OBO", "BIN", "PWE", "BMWT", "WTS", "FS", "BIN+BO",
    "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X", "XI", "XII",
    "NM", "MT", "EX", "VG", "GOAT", "VS", "AKA", "FT", "OZ", "LB",
}


def _clean_title_per_best_practices(title: str) -> str:
    """Apply eBay best practices to a title:
    - Strip exclamation marks + filler punctuation
    - Remove fluff/hype words
    - Convert ALL-CAPS words (4+ chars) to Title Case unless in _KEEP_CAPS
    - Collapse runs of whitespace
    - Trim to 80 chars
    """
    t = title or ""
    # Drop trailing/exclamation marks, dollar signs as filler, asterisks
    t = t.replace("!", "").replace("***", "").replace("**", "")
    # Strip hype words
    for pat in _FLUFF_WORDS:
        t = _re.sub(pat, "", t, flags=_re.IGNORECASE)
    # Title-case fully uppercase words ≥4 chars unless in keep-caps allowlist
    def _fix_caps(m):
        w = m.group(0)
        if w in _KEEP_CAPS or len(w) < 4:
            return w
        return w[0].upper() + w[1:].lower()
    t = _re.sub(r"\b[A-Z]{4,}\b", _fix_caps, t)
    # Collapse whitespace, strip
    t = _re.sub(r"\s+", " ", t).strip()
    # 80-char cap
    return t[:80].strip()


def _suggest_title(listing: dict) -> str:
    """
    Return the best SEO title for a listing.
    Hand-crafted titles take priority. Falls back to rule-based improvements.
    Always runs the cleaner so even hand-crafted titles inherit best practices.
    """
    item_id = listing.get("item_id", "")

    # Use hand-crafted title if available
    if item_id in _SEO_TITLES:
        t = _SEO_TITLES[item_id].strip()
    else:
        # Fall back to rule-based
        t = _rule_based_title(listing)
    return _clean_title_per_best_practices(t)


def revise_listings(cfg: dict, listings: list[dict], dry_run: bool = True):
    """
    Push title and description improvements back to eBay for every listing
    where the suggested title differs from the current title.

    Pass dry_run=True (default) to preview changes without sending to eBay.
    Pass dry_run=False to actually update.
    """
    token = get_access_token(cfg)
    ns_uri = "urn:ebay:apis:eBLBaseComponents"

    improved = []
    for l in listings:
        suggested = _suggest_title(l)
        if suggested.strip().lower() != l["title"].strip().lower():
            improved.append((l, suggested))

    if not improved:
        print("  All titles are already optimized. Nothing to update.")
        return

    print(f"  {'DRY RUN - ' if dry_run else ''}{len(improved)} listings with improvable titles:")
    for l, new_title in improved:
        print(f"    [{l['item_id']}]")
        print(f"      Before: {l['title']}")
        print(f"      After:  {new_title}")

    if dry_run:
        print("\n  Run with --fix to apply these changes to eBay.")
        return

    print("\n  Applying changes to eBay...")
    success = 0
    for l, new_title in improved:
        xml_body = f"""<?xml version="1.0" encoding="utf-8"?>
<ReviseItemRequest xmlns="{ns_uri}">
  <RequesterCredentials><eBayAuthToken>{token}</eBayAuthToken></RequesterCredentials>
  <Item>
    <ItemID>{l['item_id']}</ItemID>
    <Title>{new_title}</Title>
  </Item>
</ReviseItemRequest>"""
        headers = {
            "X-EBAY-API-SITEID":              "0",
            "X-EBAY-API-COMPATIBILITY-LEVEL": "967",
            "X-EBAY-API-CALL-NAME":           "ReviseItem",
            "X-EBAY-API-APP-NAME":            cfg["client_id"],
            "X-EBAY-API-DEV-NAME":            cfg["dev_id"],
            "X-EBAY-API-CERT-NAME":           cfg["client_secret"],
            "Content-Type":                   "text/xml",
        }
        r = requests.post("https://api.ebay.com/ws/api.dll",
                          headers=headers, data=xml_body.encode())
        root = ET.fromstring(r.text)
        ack = root.findtext(f"{{{ns_uri}}}Ack", "")
        if ack in ("Success", "Warning"):
            print(f"    Updated {l['item_id']}: {new_title}")
            success += 1
        else:
            errs = root.findall(f".//{{{ns_uri}}}ShortMessage""")
            msg = errs[0].text if errs else r.text[:100]
            print(f"    FAILED {l['item_id']}: {msg}")

    print(f"\n  Done. {success}/{len(improved)} listings updated on eBay.")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def _verify_build_integrity(listings: list[dict]) -> list[str]:
    """Sanity-check every expected output file exists, is non-empty, and (for
    HTML) carries the canonical admin hash. Returns a list of issue strings;
    empty list = passing."""
    issues: list[str] = []
    expected = [
        "index.html", "steals.html", "sold.html", "analytics.html",
        "market_intel.html", "deals.html", "quality.html", "price_review.html",
        "repricing.html",
        "scan.html",
        "title_review.html", "reddit.html", "craigslist.html", "return-policy.html",
        "sitemap.xml", "robots.txt", "google_feed.xml", "manifest.webmanifest",
    ]
    expected_hashes = set(load_admin_hashes())
    for f in expected:
        p = OUTPUT_DIR / f
        if not p.exists():
            issues.append(f"missing: docs/{f}")
            continue
        # robots.txt is naturally small (~200B), HTML pages should be much larger
        min_size = 100 if f.endswith((".txt", ".webmanifest")) else 1000
        if p.stat().st_size < min_size:
            issues.append(f"suspiciously small (<{min_size}B): docs/{f}")
            continue
        if f.endswith(".html") and expected_hashes:
            content = p.read_text()
            if "__ADMIN_HASHES" in content:
                import re as _r
                m = _r.search(r'__ADMIN_HASHES\s*=\s*\[(.*?)\]', content)
                if m:
                    page_hashes = set(_r.findall(r'"([a-f0-9]+)"', m.group(1)))
                    if page_hashes != expected_hashes:
                        issues.append(f"stale admin hash in docs/{f} (likely built before recent salt/password change)")
    # Verify item pages — count should match active listings with item_ids
    expected_item_ids = {l["item_id"] for l in listings if l.get("item_id")}
    items_dir = OUTPUT_DIR / "items"
    actual_item_files = {p.stem for p in items_dir.glob("*.html")} if items_dir.exists() else set()
    missing_items = expected_item_ids - actual_item_files
    if missing_items:
        issues.append(f"missing {len(missing_items)} item pages (e.g. {sorted(missing_items)[:3]})")
    return issues


def _git_deploy():
    """Commit docs/ changes and push to GitHub Pages (main branch)."""
    import subprocess
    repo  = Path(__file__).parent
    token = os.environ.get("GITHUB_TOKEN", "")

    if token:
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            cwd=repo, capture_output=True, text=True
        )
        remote_url = result.stdout.strip()
        if "github.com" in remote_url and "@" not in remote_url:
            authed_url = remote_url.replace("https://", f"https://{token}@")
            subprocess.run(["git", "remote", "set-url", "origin", authed_url],
                           cwd=repo, check=True)

    subprocess.run(["git", "config", "user.email", "jchletsos@gmail.com"],
                   cwd=repo, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Jason Chletsos"],
                   cwd=repo, capture_output=True)

    subprocess.run(["git", "add", "docs/", "sold_history.json", "market_history.json"], cwd=repo, check=False)
    diff = subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=repo)
    if diff.returncode == 0:
        print("  No changes to deploy.")
        return

    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    subprocess.run(["git", "commit", "-m", f"Site refresh {ts}"],
                   cwd=repo, check=True)
    subprocess.run(["git", "push", "--force", "origin", "main"], cwd=repo, check=True)
    print("  Pushed to GitHub. Pages will rebuild in ~60s.")


def main():
    import sys
    fix_mode    = "--fix"       in sys.argv
    dry_fix     = "--dry-fix"   in sys.argv
    no_deploy   = "--no-deploy" in sys.argv
    reprice_dry   = "--reprice-dry"   in sys.argv
    reprice_apply = "--reprice-apply" in sys.argv
    print("Loading config...")
    cfg = json.loads(CONFIG_FILE.read_text())

    print("Getting eBay access token...")
    token = get_access_token(cfg)

    print("Fetching active listings...")
    listings = fetch_listings(token, cfg)

    if not listings:
        print("No listings found.")
        return

    if fix_mode or dry_fix:
        print(f"\n{'Previewing' if dry_fix else 'Applying'} title improvements...")
        revise_listings(cfg, listings, dry_run=not fix_mode)
        if not fix_mode:
            return

    print("\nGenerating site files:")
    print("  Fetching seller profile...")
    seller = fetch_seller_profile(token)
    if seller:
        (OUTPUT_DIR / "_seller.json").write_text(json.dumps(seller, indent=2), encoding="utf-8")
        print(f"  Seller: {seller.get('user_id')} · feedback {seller.get('feedback_score')} ({seller.get('positive_pct')}% positive) · since {seller.get('member_since')}")
    print("  Fetching sold listings (last 90 days; merged into all-time history)...")
    sold = fetch_sold_listings(token, cfg, days_back=90)
    build_sold_page(sold)
    print("  Scanning Deals watchlist...")
    deals = fetch_deals(cfg)
    build_deals_page(deals)
    print("  Fetching market price comps (this takes ~1 min)...")
    market = fetch_market_prices(listings, cfg)
    print("  Aggregating multi-source pricing (cached 24h)...")
    pricing_cache = _pricing_cache_load()
    pricing_by_id: dict[str, dict] = {}
    pc_count = ptcg_count = 0
    for l in listings:
        srcs = gather_pricing_sources(l["title"], cfg, sold, market.get(l["item_id"]), pricing_cache)
        pricing_by_id[l["item_id"]] = srcs
        if "pricecharting" in srcs: pc_count += 1
        if "pokemontcg"    in srcs: ptcg_count += 1
    _pricing_cache_save(pricing_cache)
    print(f"  Pricing sources: eBay active on all · PriceCharting matched {pc_count}/{len(listings)} · PokemonTCG.io matched {ptcg_count}/{len(listings)}")

    # Run the SportsCardsPro "actual" price agent for any stale/new listings.
    # Rate-limited 1 req/sec by the provider; cached 7d in sportscardspro_prices.json.
    if cfg.get("pricecharting_api_key") or os.environ.get("PRICECHARTING_API_KEY"):
        try:
            import subprocess, sys as _sys
            # Snapshot the current listings for the agent to consume — promote
            # works in-memory but the agent reads from disk.
            snap_path = OUTPUT_DIR / "listings_snapshot.json"
            snap_path.write_text(json.dumps(listings, indent=2, default=str), encoding="utf-8")
            print("  Refreshing SportsCardsPro 'actual' prices (rate-limited, may take a few min)...")
            subprocess.run([_sys.executable, str(Path(__file__).parent / "card_price_agent.py")],
                           check=False, timeout=900)
        except Exception as e:
            print(f"  SCP price agent skipped: {e}")
    build_dashboard(listings, market, seller=seller, pricing=pricing_by_id)
    build_analytics_page(listings, market, sold)
    build_steals_page(listings, market)
    build_market_intel_page(listings, market, sold, deals)
    build_quality_report(listings)
    build_craigslist(listings)
    build_reddit(listings)
    build_google_feed(listings, market=market, sold_history=sold, pricing=pricing_by_id)
    write_analysis_views()
    build_return_policy()
    build_price_review(listings, market, pricing=pricing_by_id)
    build_title_review(listings)

    # ------------------------------------------------------------------
    # Repricing agent — plans (and optionally applies) price changes,
    # writes docs/repricing.html. Imported lazily to keep this module
    # importable even if the agent file is missing in older checkouts.
    # ------------------------------------------------------------------
    try:
        import repricing_agent
        rcfg = repricing_agent.load_config()
        plan = repricing_agent.plan_all(listings, pricing_by_id, rcfg)
        repricing_agent.PLAN_PATH.parent.mkdir(exist_ok=True)
        repricing_agent.PLAN_PATH.write_text(json.dumps({
            "generated_at":  datetime.now(timezone.utc).isoformat(),
            "config":        rcfg,
            "decisions":     plan,
        }, indent=2))
        repricing_agent.summarize(plan)
        applied = []
        if reprice_apply:
            print("\n  Applying repricing changes to eBay...")
            applied = repricing_agent.apply_plan(plan, cfg, rcfg)
            repricing_agent.append_history(applied)
        elif reprice_dry:
            print("  (dry preview — re-run with --reprice-apply to push to eBay)")
        repricing_agent.build_report(plan, repricing_agent.load_history(), rcfg)
    except Exception as e:
        print(f"  ⚠ Repricing agent skipped: {e}")
        # Write a minimal placeholder so the integrity check passes
        (OUTPUT_DIR / "repricing.html").write_text(
            html_shell("Repricing Agent · Harpua2001",
                       f"<section><h1>Repricing Agent</h1><p>Not run this cycle: {e}</p></section>",
                       active_page="repricing.html"),
            encoding="utf-8",
        )

    build_sitemap_and_robots(listings)

    # ------------------------------------------------------------------
    # Build integrity check — refuse to deploy if any expected page is
    # missing or has a stale admin hash (catches silent build failures).
    # ------------------------------------------------------------------
    print("\nVerifying build integrity...")
    issues = _verify_build_integrity(listings)
    if issues:
        print("\n❌ BUILD INTEGRITY FAILED — NOT DEPLOYING")
        for i in issues:
            print(f"  · {i}")
        import sys as _sys
        _sys.exit(1)
    print("  ✓ All expected pages present, admin hashes consistent")

    print("\nDeploying to GitHub Pages...")
    if no_deploy:
        print("  Skipping deploy (--no-deploy flag set).")
    else:
        _git_deploy()

    print(f"""
Done.
---------------------------------------------------------
Site URL (after ~60s build):
  https://fivetran-jasonchletsos.github.io/jason_chletsos_ebay_lots/

Pages:
  /             - Searchable listing dashboard (mobile-friendly)
  /quality.html - Quality report, worst listings first
  /craigslist.html - Ready-to-paste Craigslist ads
  /google_feed.xml - Submit to merchants.google.com for free Google Shopping

Next steps:
  1. Submit google_feed.xml URL to merchants.google.com (free Google Shopping)
  2. Open quality.html and fix red listings to improve eBay search rank
  3. Use craigslist.html to post high-value items on Craigslist (free, collector buyers)
  4. Run this script again anytime to refresh the site with current listings

To preview title improvements without changing eBay:
  python3 promote.py --dry-fix

To apply title improvements directly to eBay:
  python3 promote.py --fix

To add a banner image to the site header:
  1. Create a 1200x200 JPG in Canva (free at canva.com)
  2. Save it as docs/banner.jpg
  3. Run python3 promote.py to redeploy
---------------------------------------------------------
""")


if __name__ == "__main__":
    main()
