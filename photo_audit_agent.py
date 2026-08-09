"""
photo_audit_agent.py — read-only photo-quality audit for Harpua2001 listings.

Single-photo listings convert at ~30% the rate of 4+ photo listings; over-
compressed thumbnails lose to competitors in eBay search-result CTR. This agent
walks every active listing, pulls every PictureURL via the Trading API GetItem
call, then scores each photo on:

  1. Photo count           (1 → SEVERE, 2 → POOR, 3 → OK, 4+ → GOOD)
  2. Resolution            (flag photos with long edge < min_long_edge_px)
  3. File-size proxy       (bytes < min_file_bytes_per_megapixel ⇒ over-
                            compressed)
  4. Aspect ratio          (flag panoramic / extreme crops)
  5. Coverage              (front/back/angled/detail heuristic via count tiers)

Each listing is then weighted by a "sell potential" signal:

    sell_potential_score = max(1, sold_history_median * watchers_count)

…so the reshoot queue is sorted by leverage, not just severity. The agent is
strictly advisory — no eBay writes, no --apply flag.

Usage:
    python photo_audit_agent.py              # full audit, fetches all photos
    python photo_audit_agent.py --no-fetch   # reuse output/photo_audit.json
    python photo_audit_agent.py --report-only

Artifacts:
    output/photo_audit.json            full per-listing audit
    docs/photo_audit.html              human-readable, ranked report
    photo_audit_config.json            tunable thresholds (created on 1st run)
"""


from __future__ import annotations

# --- Roster ---
AGENT_NAME = 'Walt "Clyde" Frazier'
AGENT_ROLE = 'Photo Audit'

import argparse
import json
import statistics
import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path

import requests

import promote
import chart_helpers


REPO_ROOT          = Path(__file__).parent
CONFIG_PATH        = REPO_ROOT / "photo_audit_config.json"
LISTINGS_SNAPSHOT  = REPO_ROOT / "output" / "listings_snapshot.json"
SOLD_HISTORY_PATH  = REPO_ROOT / "sold_history.json"
AUDIT_PATH         = REPO_ROOT / "output" / "photo_audit.json"
REPORT_PATH        = promote.OUTPUT_DIR / "photo_audit.html"

EBAY_NS            = "urn:ebay:apis:eBLBaseComponents"

DEFAULT_CONFIG: dict = {
    "min_long_edge_px":              800,
    "min_photos_for_ok":             3,
    "min_photos_for_good":           4,
    "min_file_bytes_per_megapixel":  30000,
    "max_listings_to_audit":         200,
    "rotation_offset":               0,
    "low_priority_below_value_usd":  5.00,
    # Aspect ratio bounds (long edge / short edge). Most sports cards are 3:4
    # ≈ 1.33. Anything > 2.0 is panoramic; anything < 1.05 is square-cropped.
    "aspect_panoramic_above":        2.0,
    "aspect_square_below":           1.05,
    # CDN politeness — eBay throttles aggressive image-CDN scraping.
    "max_image_requests_per_sec":    5.0,
    # Trading API GetItem pacing (separate quota).
    "max_trading_calls_per_sec":     2.0,
    # Conversion-uplift model assumptions for the top-line $/month estimate.
    "assumed_views_per_listing_per_month":  120,
    "assumed_baseline_conversion_pct":      1.2,
    "assumed_uplift_multiplier_severe":     2.5,   # 1-photo → 4-photo: ~2.5x
    "assumed_uplift_multiplier_poor":       1.6,
    "assumed_uplift_multiplier_ok":         1.15,
}


# --------------------------------------------------------------------------- #
# Config + snapshot I/O                                                       #
# --------------------------------------------------------------------------- #

def load_config() -> dict:
    if not CONFIG_PATH.exists():
        CONFIG_PATH.write_text(json.dumps(DEFAULT_CONFIG, indent=2))
        print(f"  Created default config at {CONFIG_PATH.name}")
        return dict(DEFAULT_CONFIG)
    cfg = json.loads(CONFIG_PATH.read_text())
    for k, v in DEFAULT_CONFIG.items():
        cfg.setdefault(k, v)
    return cfg


def _load_listings() -> list[dict]:
    """Tolerate both snapshot shapes used in this repo:
       - flat list (current shape)
       - dict with a 'listings' key (repricing-agent shape)
    """
    if not LISTINGS_SNAPSHOT.exists():
        raise FileNotFoundError(
            f"Missing {LISTINGS_SNAPSHOT}. Run promote.py or repricing_agent.py first."
        )
    data = json.loads(LISTINGS_SNAPSHOT.read_text())
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and "listings" in data:
        return data["listings"]
    raise ValueError(f"Unrecognized listings_snapshot.json shape: {type(data)}")


def _load_sold_history() -> list[dict]:
    if not SOLD_HISTORY_PATH.exists():
        return []
    try:
        return json.loads(SOLD_HISTORY_PATH.read_text())
    except json.JSONDecodeError:
        return []


def _sold_median_for(title: str, sold: list[dict]) -> float:
    """Cheap title-token overlap match against sold_history → median sale price.
    Falls back to 0 if no comp at all. This is intentionally lossy — the audit
    just needs a rough "is this a $1 card or a $50 card" signal."""
    if not title or not sold:
        return 0.0
    toks = {t for t in title.lower().split() if len(t) > 3}
    if not toks:
        return 0.0
    matches: list[float] = []
    for s in sold:
        st = (s.get("title") or "").lower()
        if not st:
            continue
        st_toks = {t for t in st.split() if len(t) > 3}
        if len(toks & st_toks) >= 3:
            try:
                p = float(s.get("sale_price") or 0)
                if p > 0:
                    matches.append(p)
            except (TypeError, ValueError):
                continue
    if not matches:
        return 0.0
    return float(statistics.median(matches))


# --------------------------------------------------------------------------- #
# eBay Trading API: GetItem → PictureURL[] + WatchCount                       #
# --------------------------------------------------------------------------- #

def fetch_item_detail(item_id: str, ebay_cfg: dict, token: str) -> dict:
    """Trading API GetItem — returns picture URLs + watcher count.

    We ask for two output selectors (Pictures, ItemSpecifics) plus the default
    summary so we get WatchCount in one round-trip.
    """
    xml_body = f"""<?xml version="1.0" encoding="utf-8"?>
<GetItemRequest xmlns="{EBAY_NS}">
  <RequesterCredentials><eBayAuthToken>{token}</eBayAuthToken></RequesterCredentials>
  <ItemID>{item_id}</ItemID>
  <DetailLevel>ReturnAll</DetailLevel>
  <IncludeWatchCount>true</IncludeWatchCount>
</GetItemRequest>"""
    headers = {
        "X-EBAY-API-SITEID":              "0",
        "X-EBAY-API-COMPATIBILITY-LEVEL": "967",
        "X-EBAY-API-CALL-NAME":           "GetItem",
        "X-EBAY-API-APP-NAME":            ebay_cfg["client_id"],
        "X-EBAY-API-DEV-NAME":            ebay_cfg["dev_id"],
        "X-EBAY-API-CERT-NAME":           ebay_cfg["client_secret"],
        "Content-Type":                   "text/xml",
    }
    try:
        r = requests.post("https://api.ebay.com/ws/api.dll",
                          headers=headers, data=xml_body.encode(), timeout=30)
        root = ET.fromstring(r.text)
    except (requests.RequestException, ET.ParseError) as e:
        return {"ok": False, "error": str(e), "pictures": [], "watch_count": 0}

    ns = {"e": EBAY_NS}
    pics: list[str] = []
    for p in root.findall(".//e:PictureDetails/e:PictureURL", ns):
        if p.text and p.text.strip():
            pics.append(p.text.strip())
    # Also accept GalleryURL as a fallback if PictureURL is empty.
    if not pics:
        g = root.find(".//e:PictureDetails/e:GalleryURL", ns)
        if g is not None and g.text:
            pics.append(g.text.strip())

    wc_el = root.find(".//e:Item/e:WatchCount", ns)
    try:
        watch_count = int(wc_el.text) if wc_el is not None and wc_el.text else 0
    except ValueError:
        watch_count = 0

    ack = root.findtext(f"{{{EBAY_NS}}}Ack", "")
    return {
        "ok":          ack in ("Success", "Warning"),
        "pictures":    pics,
        "watch_count": watch_count,
        "ack":         ack,
    }


# --------------------------------------------------------------------------- #
# Per-image probing: HEAD → fall back to GET (only enough bytes for dims)     #
# --------------------------------------------------------------------------- #

_PILLOW = None
def _pillow():
    global _PILLOW
    if _PILLOW is None:
        try:
            from PIL import Image
            _PILLOW = Image
        except ImportError:
            _PILLOW = False
    return _PILLOW


def _dims_from_bytes(b: bytes) -> tuple[int, int] | None:
    img_lib = _pillow()
    if not img_lib:
        return None
    try:
        with img_lib.open(BytesIO(b)) as im:
            return im.size  # (w, h)
    except Exception:
        return None


def probe_image(url: str, session: requests.Session) -> dict:
    """Return {url, bytes, width, height, ok, error}.

    Tries HEAD first for byte-size; eBay's CDN does not return dimensions in
    headers, so we always need a partial GET (or full GET fallback) when Pillow
    is available. If Pillow is missing we still report byte-size and skip the
    resolution check.
    """
    out: dict = {"url": url, "bytes": 0, "width": None, "height": None,
                 "ok": False, "error": None}
    try:
        h = session.head(url, timeout=15, allow_redirects=True)
        if h.status_code == 200:
            cl = h.headers.get("Content-Length")
            if cl and cl.isdigit():
                out["bytes"] = int(cl)
    except requests.RequestException as e:
        out["error"] = f"HEAD: {e}"

    img_lib = _pillow()
    if img_lib:
        # Range-GET first 256 KB — enough for any reasonable JPEG header
        # parser to recover dimensions without pulling full file.
        try:
            r = session.get(url, timeout=20, stream=True,
                            headers={"Range": "bytes=0-262143"})
            if r.status_code in (200, 206):
                content = r.content
                if not out["bytes"]:
                    cr = r.headers.get("Content-Range")
                    if cr and "/" in cr:
                        total = cr.rsplit("/", 1)[1]
                        if total.isdigit():
                            out["bytes"] = int(total)
                    if not out["bytes"]:
                        out["bytes"] = len(content)
                dims = _dims_from_bytes(content)
                if dims:
                    out["width"], out["height"] = dims
                    out["ok"] = True
                    return out
            # Fallthrough: try full GET
        except requests.RequestException as e:
            out["error"] = f"GET: {e}"

        try:
            r = session.get(url, timeout=30)
            if r.status_code == 200:
                if not out["bytes"]:
                    out["bytes"] = len(r.content)
                dims = _dims_from_bytes(r.content)
                if dims:
                    out["width"], out["height"] = dims
                    out["ok"] = True
                    return out
        except requests.RequestException as e:
            out["error"] = f"GET-full: {e}"
    else:
        # Pillow unavailable — count this as ok if we at least got a byte size.
        out["ok"] = out["bytes"] > 0

    return out


# --------------------------------------------------------------------------- #
# Throttled batch driver                                                      #
# --------------------------------------------------------------------------- #

class RateLimiter:
    """Token-bucket-ish pacer: ensures no more than `rps` calls per second."""

    def __init__(self, rps: float) -> None:
        self.min_interval = 1.0 / rps if rps > 0 else 0
        self._last = 0.0

    def wait(self) -> None:
        if self.min_interval <= 0:
            return
        now = time.monotonic()
        gap = now - self._last
        if gap < self.min_interval:
            time.sleep(self.min_interval - gap)
        self._last = time.monotonic()


# --------------------------------------------------------------------------- #
# Scoring                                                                     #
# --------------------------------------------------------------------------- #

def severity_for(photo_count: int, cfg: dict) -> str:
    if photo_count <= 1:
        return "SEVERE"
    if photo_count == 2:
        return "POOR"
    if photo_count < cfg["min_photos_for_good"]:
        return "OK"
    return "GOOD"


def audit_listing(listing: dict, pics_meta: list[dict], watch_count: int,
                  sold_median: float, cfg: dict) -> dict:
    """Score one listing. pics_meta is the list of probe_image() results."""
    photo_count = len(pics_meta)
    sev = severity_for(photo_count, cfg)

    # Resolution checks
    res_issues: list[dict] = []
    file_issues: list[dict] = []
    aspect_issues: list[dict] = []
    for idx, p in enumerate(pics_meta):
        w, h, b = p.get("width"), p.get("height"), p.get("bytes") or 0
        if w and h:
            long_edge = max(w, h)
            short_edge = max(1, min(w, h))
            if long_edge < cfg["min_long_edge_px"]:
                res_issues.append({
                    "index": idx, "url": p["url"],
                    "width": w, "height": h, "long_edge": long_edge,
                })
            mp = (w * h) / 1_000_000 if w * h > 0 else 0
            if mp >= 0.36 and b > 0 and b / max(mp, 0.01) < cfg["min_file_bytes_per_megapixel"]:
                file_issues.append({
                    "index": idx, "url": p["url"],
                    "bytes": b, "megapixels": round(mp, 2),
                    "bytes_per_mp": int(b / max(mp, 0.01)),
                })
            ratio = long_edge / short_edge
            if ratio >= cfg["aspect_panoramic_above"]:
                aspect_issues.append({"index": idx, "url": p["url"],
                                      "ratio": round(ratio, 2), "kind": "panoramic"})
            elif ratio <= cfg["aspect_square_below"]:
                aspect_issues.append({"index": idx, "url": p["url"],
                                      "ratio": round(ratio, 2), "kind": "square"})

    try:
        listing_price = float(listing.get("price") or 0)
    except (TypeError, ValueError):
        listing_price = 0.0

    # sell_potential_score — use sold median when we have it, else current price
    # as a weak fallback so we still rank reasonably without comps.
    median_used = sold_median if sold_median > 0 else listing_price
    sell_potential = max(1.0, median_used * max(watch_count, 1))

    return {
        "item_id":             listing.get("item_id"),
        "title":               listing.get("title"),
        "url":                 listing.get("url"),
        "thumb":               listing.get("pic"),
        "price":               listing_price,
        "photo_count":         photo_count,
        "severity":            sev,
        "watch_count":         watch_count,
        "sold_history_median": round(sold_median, 2),
        "sell_potential_score": round(sell_potential, 2),
        "resolution_issues":   res_issues,
        "file_size_issues":    file_issues,
        "aspect_issues":       aspect_issues,
        "photos":              pics_meta,
        "is_low_value":        listing_price < cfg["low_priority_below_value_usd"]
                                and sold_median < cfg["low_priority_below_value_usd"],
    }


def reshoot_priority(a: dict, cfg: dict) -> float:
    """Combined priority: severity tier × sell_potential, with a small kicker
    for resolution/file-size red flags. Higher = reshoot first."""
    sev_weight = {"SEVERE": 4.0, "POOR": 2.5, "OK": 1.2, "GOOD": 0.4}[a["severity"]]
    flag_kicker = 1.0 + 0.15 * len(a["resolution_issues"]) \
                      + 0.10 * len(a["file_size_issues"]) \
                      + 0.05 * len(a["aspect_issues"])
    low_value_dampener = 0.5 if a["is_low_value"] else 1.0
    return round(sev_weight * a["sell_potential_score"] * flag_kicker * low_value_dampener, 2)


def estimate_monthly_uplift(top_audits: list[dict], cfg: dict) -> float:
    """Back-of-envelope $/month uplift if the caller reshoots `top_audits`.

    Per listing:
        extra_sales = views/mo * baseline_conv * (uplift_multiplier - 1)
        $/mo       = extra_sales * price (or sold_history_median)
    """
    views = cfg["assumed_views_per_listing_per_month"]
    base  = cfg["assumed_baseline_conversion_pct"] / 100.0
    mult  = {
        "SEVERE": cfg["assumed_uplift_multiplier_severe"],
        "POOR":   cfg["assumed_uplift_multiplier_poor"],
        "OK":     cfg["assumed_uplift_multiplier_ok"],
        "GOOD":   1.0,
    }
    total = 0.0
    for a in top_audits:
        unit_value = a["sold_history_median"] if a["sold_history_median"] > 0 else a["price"]
        m = mult.get(a["severity"], 1.0)
        extra_sales_per_mo = views * base * max(m - 1.0, 0)
        total += extra_sales_per_mo * unit_value
    return round(total, 2)


# --------------------------------------------------------------------------- #
# Orchestration                                                               #
# --------------------------------------------------------------------------- #

def run_audit(cfg: dict) -> dict:
    listings = _load_listings()
    sold     = _load_sold_history()
    cap      = cfg["max_listings_to_audit"]
    if len(listings) > cap:
        # Rotating slice, not a fixed [:cap] truncation -- otherwise the same
        # first `cap` listings get re-audited every run forever and the rest
        # of the catalog (98%+ of it, once the store grew past ~200 active
        # listings) never gets checked at all. Mirrors repricing_agent.py's
        # rotation_offset pattern. Fixed 2026-08-09.
        off = int(cfg.get("rotation_offset", 0)) % len(listings)
        sliced = listings[off:off + cap]
        if len(sliced) < cap:
            sliced += listings[:cap - len(sliced)]
        print(f"  Auditing {cap} of {len(listings)} listings this run "
              f"(rotating slice from offset {off})")
        try:
            raw = json.loads(CONFIG_PATH.read_text()) if CONFIG_PATH.exists() else {}
            raw["rotation_offset"] = (off + cap) % len(listings)
            CONFIG_PATH.write_text(json.dumps(raw, indent=2))
        except Exception:
            pass
        listings = sliced

    ebay_cfg = json.loads(promote.CONFIG_FILE.read_text())
    print("  Getting eBay access token...")
    token = promote.get_access_token(ebay_cfg)

    trading_limiter = RateLimiter(cfg["max_trading_calls_per_sec"])
    image_limiter   = RateLimiter(cfg["max_image_requests_per_sec"])
    session = requests.Session()
    session.headers.update({"User-Agent": "harpua-photo-audit/1.0"})

    audits: list[dict] = []
    print(f"  Auditing photos for {len(listings)} listings...")
    for i, l in enumerate(listings, 1):
        item_id = l.get("item_id")
        if not item_id:
            continue

        trading_limiter.wait()
        detail = fetch_item_detail(item_id, ebay_cfg, token)
        pics = detail.get("pictures") or []
        # Fall back to snapshot's primary `pic` if Trading API returned nothing
        # (e.g. recently ended listings, gallery-only items).
        if not pics and l.get("pic"):
            pics = [l["pic"]]

        pics_meta: list[dict] = []
        for url in pics:
            image_limiter.wait()
            pics_meta.append(probe_image(url, session))

        sold_median = _sold_median_for(l.get("title", ""), sold)
        audit = audit_listing(l, pics_meta, detail.get("watch_count", 0),
                              sold_median, cfg)
        audit["reshoot_priority"] = reshoot_priority(audit, cfg)
        audits.append(audit)

        if i % 10 == 0 or i == len(listings):
            print(f"    [{i}/{len(listings)}]  {item_id}  {audit['severity']:<6}  "
                  f"{audit['photo_count']} photos  pri={audit['reshoot_priority']}")

    # Sort: highest sell_potential first, then severity tiebreak
    sev_order = {"SEVERE": 0, "POOR": 1, "OK": 2, "GOOD": 3}
    audits.sort(key=lambda a: (-a["sell_potential_score"], sev_order[a["severity"]]))
    # Then assign reshoot-priority rank by the reshoot_priority score itself
    ranked = sorted(audits, key=lambda a: -a["reshoot_priority"])
    for rank, a in enumerate(ranked, 1):
        a["reshoot_rank"] = rank

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "config":       cfg,
        "audits":       ranked,
    }


# --------------------------------------------------------------------------- #
# HTML report                                                                 #
# --------------------------------------------------------------------------- #

def _badge(sev: str) -> str:
    return f'<span class="sev-badge sev-{sev.lower()}">{sev}</span>'


def _red_dots(issues: list[dict], total: int, tip_prefix: str) -> str:
    """One dot per photo slot; red if that slot has an issue, grey otherwise."""
    if total == 0:
        return '<span class="dot-empty">—</span>'
    flagged = {i["index"] for i in issues}
    dots = []
    for idx in range(total):
        cls = "dot-red" if idx in flagged else "dot-ok"
        tip = ""
        if idx in flagged:
            issue = next((x for x in issues if x["index"] == idx), {})
            if "long_edge" in issue:
                tip = f' title="{tip_prefix}: {issue["width"]}x{issue["height"]}"'
            elif "bytes" in issue:
                tip = f' title="{tip_prefix}: {issue["bytes"]} bytes, {issue["megapixels"]} MP"'
            elif "ratio" in issue:
                tip = f' title="{tip_prefix}: ratio {issue["ratio"]} ({issue["kind"]})"'
            else:
                tip = f' title="{tip_prefix}"'
        dots.append(f'<span class="dot {cls}"{tip}></span>')
    return "".join(dots)


# --------------------------------------------------------------------------- #
# Entry point                                                                 #
# --------------------------------------------------------------------------- #

def main() -> int:
    print(f'  {AGENT_NAME} ({AGENT_ROLE}) reporting in.')
    ap = argparse.ArgumentParser(description="Read-only photo-quality audit for Harpua2001.")
    ap.add_argument("--no-fetch", action="store_true",
                    help="Reuse cached output/photo_audit.json instead of re-probing.")
    ap.add_argument("--report-only", action="store_true",
                    help="Rebuild docs/photo_audit.html from the cached audit.")
    args = ap.parse_args()

    cfg = load_config()

    if args.report_only or args.no_fetch:
        if not AUDIT_PATH.exists():
            print(f"  No cached audit at {AUDIT_PATH} — running a full audit.")
            payload = run_audit(cfg)
        else:
            payload = json.loads(AUDIT_PATH.read_text())
            payload["config"] = cfg  # always reflect current thresholds in the report
    else:
        payload = run_audit(cfg)

    AUDIT_PATH.parent.mkdir(exist_ok=True)
    AUDIT_PATH.write_text(json.dumps(payload, indent=2))

    sev_counts = {"SEVERE": 0, "POOR": 0, "OK": 0, "GOOD": 0}
    for a in payload["audits"]:
        sev_counts[a["severity"]] += 1
    print(f"\n  Severity tally: "
          f"{sev_counts['SEVERE']} severe · "
          f"{sev_counts['POOR']} poor · "
          f"{sev_counts['OK']} ok · "
          f"{sev_counts['GOOD']} good")

    top3 = payload["audits"][:3]
    if top3:
        print("\n  Top reshoot priorities:")
        for a in top3:
            print(f"    #{a['reshoot_rank']}  {a['item_id']}  {a['severity']:<6} "
                  f"pri={a['reshoot_priority']:>8.1f}  ${a['price']:>6.2f}  "
                  f"{(a['title'] or '')[:60]}")

    print(f"\n  JSON:   {AUDIT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
