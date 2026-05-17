"""
photo_quality_audit.py — Cassini photo-quality recommendation report.

eBay's Cassini search algorithm de-ranks listings with fewer than 8 photos
and listings whose images are smaller than 1600x1600. Sellers who reshoot
flagged items see a 20-30% lift in impressions. This script audits every
active listing in `output/listings_snapshot.json` against those two
Cassini-specific factors ONLY — it is intentionally narrower than
`photo_audit_agent.py`, which scores via Pillow + sell-potential.

Factors per listing:
  1. photo_count   pass >=8 · warn 4-7 · fail <4
  2. max_dimension URL `s-l1600` -> pass · `s-l500` or smaller -> fail
  3. has_no_image  GetItem returned zero PictureURLs

Trading API GetItem responses are cached in `output/photo_audit_cache.json`
with a 24h TTL. Outputs `output/photo_quality_plan.json` plus the admin
report `docs/photo_quality.html`. No eBay writes.

CLI:
  python photo_quality_audit.py              # full audit + cache refresh
  python photo_quality_audit.py --no-fetch   # reuse cache only
  python photo_quality_audit.py --report-only
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

import promote


REPO_ROOT          = Path(__file__).parent
LISTINGS_SNAPSHOT  = REPO_ROOT / "output" / "listings_snapshot.json"
CACHE_PATH         = REPO_ROOT / "output" / "photo_audit_cache.json"
PLAN_PATH          = REPO_ROOT / "output" / "photo_quality_plan.json"
REPORT_PATH        = promote.OUTPUT_DIR / "photo_quality.html"

EBAY_NS            = "urn:ebay:apis:eBLBaseComponents"

# Cassini thresholds — codified in one place.
PHOTO_COUNT_PASS   = 8           # >=8 photos passes Cassini's photo-count signal
PHOTO_COUNT_WARN   = 4           # 4-7 is a warning band, <4 is a hard fail
DIM_PASS_PX        = 1600        # 1600px long edge passes Cassini's dimension signal
DIM_FAIL_PX        = 500         # 500px or smaller is a hard fail

CACHE_TTL_SECONDS  = 24 * 60 * 60

# Trading API politeness — eBay throttles aggressive GetItem callers.
TRADING_RPS        = 2.0


# === I/O ===

def _load_listings() -> list[dict]:
    if not LISTINGS_SNAPSHOT.exists():
        raise FileNotFoundError(
            f"Missing {LISTINGS_SNAPSHOT}. Run promote.py first to refresh the snapshot."
        )
    data = json.loads(LISTINGS_SNAPSHOT.read_text())
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and "listings" in data:
        return data["listings"]
    raise ValueError(f"Unrecognized listings_snapshot.json shape: {type(data)}")


def _load_cache() -> dict:
    if not CACHE_PATH.exists():
        return {"entries": {}}
    try:
        return json.loads(CACHE_PATH.read_text())
    except (json.JSONDecodeError, OSError):
        return {"entries": {}}


def _save_cache(cache: dict) -> None:
    CACHE_PATH.parent.mkdir(exist_ok=True)
    CACHE_PATH.write_text(json.dumps(cache, indent=2))


def _cache_fresh(entry: dict) -> bool:
    ts = entry.get("fetched_at")
    if not ts:
        return False
    try:
        fetched = datetime.fromisoformat(ts)
    except ValueError:
        return False
    if fetched.tzinfo is None:
        fetched = fetched.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - fetched).total_seconds() < CACHE_TTL_SECONDS


# === Trading API: GetItem -> PictureURL[] ===

class _RateLimiter:
    def __init__(self, rps: float) -> None:
        self.min_interval = 1.0 / rps if rps > 0 else 0.0
        self._last = 0.0

    def wait(self) -> None:
        if self.min_interval <= 0:
            return
        gap = time.monotonic() - self._last
        if gap < self.min_interval:
            time.sleep(self.min_interval - gap)
        self._last = time.monotonic()


def fetch_pictures(item_id: str, ebay_cfg: dict, token: str) -> dict:
    """Trading API GetItem (DetailLevel=ReturnAll) -> PictureURL list."""
    xml_body = f"""<?xml version="1.0" encoding="utf-8"?>
<GetItemRequest xmlns="{EBAY_NS}">
  <RequesterCredentials><eBayAuthToken>{token}</eBayAuthToken></RequesterCredentials>
  <ItemID>{item_id}</ItemID>
  <DetailLevel>ReturnAll</DetailLevel>
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
        return {"ok": False, "error": str(e), "pictures": []}

    ns = {"e": EBAY_NS}
    pics: list[str] = []
    for p in root.findall(".//e:PictureDetails/e:PictureURL", ns):
        if p.text and p.text.strip():
            pics.append(p.text.strip())
    if not pics:
        g = root.find(".//e:PictureDetails/e:GalleryURL", ns)
        if g is not None and g.text:
            pics.append(g.text.strip())

    ack = root.findtext(f"{{{EBAY_NS}}}Ack", "")
    return {"ok": ack in ("Success", "Warning"), "pictures": pics, "ack": ack}


# === URL-pattern dimension probe ===

_SIZE_RE = re.compile(r"s-l(\d+)\.(?:jpg|jpeg|png|webp)", re.IGNORECASE)


def url_max_dimension(url: str) -> int | None:
    """Parse the `s-l####.jpg` size token in eBay CDN URLs; None if absent."""
    if not url:
        return None
    m = _SIZE_RE.search(url)
    return int(m.group(1)) if m else None


def listing_max_dimension(pictures: list[str], thumb: str | None) -> int | None:
    """Best-known dimension across all PictureURLs plus the thumbnail.
    Sellers who uploaded high-res originals usually surface `s-l1600`; phone
    screenshots cap at `s-l500`. The MAX is the fairest read of source quality.
    """
    sizes = [url_max_dimension(u) for u in (pictures or [])]
    sizes.append(url_max_dimension(thumb) if thumb else None)
    sizes = [s for s in sizes if s is not None]
    return max(sizes) if sizes else None


# === Scoring ===

def classify(photo_count: int, max_dim: int | None, has_no_image: bool) -> tuple[str, str]:
    """Return (status, recommendation). Status: no_image | fail | warn | pass."""
    if has_no_image:
        return ("no_image", "No images on this listing — upload at least 8 photos at 1600x1600 before promoting it.")

    count_status: str
    if photo_count >= PHOTO_COUNT_PASS:
        count_status = "pass"
    elif photo_count >= PHOTO_COUNT_WARN:
        count_status = "warn"
    else:
        count_status = "fail"

    if max_dim is None:
        dim_status = "warn"
    elif max_dim >= DIM_PASS_PX:
        dim_status = "pass"
    elif max_dim <= DIM_FAIL_PX:
        dim_status = "fail"
    else:
        dim_status = "warn"

    # Overall status takes the worst of the two signals.
    order = {"pass": 0, "warn": 1, "fail": 2}
    status = count_status if order[count_status] >= order[dim_status] else dim_status

    parts: list[str] = []
    if count_status == "fail":
        parts.append(f"Reshoot: add at least {PHOTO_COUNT_PASS - photo_count} more photos "
                     f"(currently {photo_count}, Cassini wants {PHOTO_COUNT_PASS}+).")
    elif count_status == "warn":
        parts.append(f"Add {PHOTO_COUNT_PASS - photo_count} more photos to reach the 8-photo Cassini floor.")
    if dim_status == "fail":
        parts.append(f"Upload originals at >= {DIM_PASS_PX}x{DIM_PASS_PX} "
                     f"(current max render is {max_dim}px).")
    elif dim_status == "warn":
        if max_dim is None:
            parts.append("Could not derive image dimensions from CDN URL — verify >= 1600x1600.")
        else:
            parts.append(f"Image render is {max_dim}px — re-upload at >= {DIM_PASS_PX}px for Cassini.")
    if not parts:
        parts.append("Reshoot recommended: none — listing clears the Cassini photo bar.")
    return (status, " ".join(parts))


# === Orchestration ===

def collect_pictures(listings: list[dict], ebay_cfg: dict, token: str,
                     cache: dict, fetch: bool) -> dict:
    """Populate cache['entries'][item_id] with picture lists; returns cache."""
    entries = cache.setdefault("entries", {})
    limiter = _RateLimiter(TRADING_RPS)
    total = len(listings)
    fetched = 0
    reused  = 0
    for i, l in enumerate(listings, 1):
        item_id = l.get("item_id")
        if not item_id:
            continue
        existing = entries.get(item_id)
        if existing and _cache_fresh(existing):
            reused += 1
            continue
        if not fetch:
            # No-fetch mode: leave stale or empty entries as-is; the audit
            # will degrade gracefully by falling back to the snapshot thumb.
            continue
        limiter.wait()
        result = fetch_pictures(item_id, ebay_cfg, token)
        entries[item_id] = {
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "pictures":   result.get("pictures") or [],
            "ok":         result.get("ok", False),
            "ack":        result.get("ack"),
            "error":      result.get("error"),
        }
        fetched += 1
        if i % 10 == 0 or i == total:
            print(f"    [{i}/{total}]  {item_id}  pics={len(entries[item_id]['pictures'])}")
    print(f"  Trading API: fetched={fetched}  reused_cache={reused}  skipped={total - fetched - reused}")
    return cache


def audit(listings: list[dict], cache: dict) -> dict:
    entries = cache.get("entries", {})
    rows: list[dict] = []
    summary = {"pass": 0, "warn": 0, "fail": 0, "no_image": 0}

    for l in listings:
        item_id = l.get("item_id")
        if not item_id:
            continue
        entry = entries.get(item_id) or {}
        pictures = entry.get("pictures") or []
        # Fall back to the snapshot thumbnail if the Trading API returned
        # nothing — better than treating a real (but uncached) listing as
        # zero-photo.
        if not pictures and l.get("pic"):
            pictures = [l["pic"]]
        photo_count = len(pictures)
        has_no_image = photo_count == 0
        max_dim = listing_max_dimension(pictures, l.get("pic"))
        status, recommendation = classify(photo_count, max_dim, has_no_image)
        summary[status] += 1
        rows.append({
            "item_id":        item_id,
            "title":          l.get("title") or "",
            "url":            l.get("url") or "",
            "pic":            l.get("pic") or "",
            "photo_count":    photo_count,
            "max_dimension":  max_dim,
            "status":         status,
            "recommendation": recommendation,
        })

    # Worst-first ordering for downstream consumers.
    sev_order = {"no_image": 0, "fail": 1, "warn": 2, "pass": 3}
    rows.sort(key=lambda r: (sev_order[r["status"]], r["photo_count"], -(r["max_dimension"] or 0)))
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary":      summary,
        "listings":     rows,
    }


# === HTML report ===

def _esc(s: str) -> str:
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _status_chip(status: str) -> str:
    return f'<span class="pq-chip pq-{status}">{status.replace("_", " ")}</span>'


def build_report(plan: dict) -> Path:
    summary = plan["summary"]
    rows = plan["listings"]
    failing = [r for r in rows if r["status"] in ("fail", "no_image")]
    warning = [r for r in rows if r["status"] == "warn"]
    run_ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    def _row(r: dict) -> str:
        title = _esc(r["title"])[:90]
        pic = _esc(r["pic"])
        thumb = (f'<img src="{pic}" alt="" loading="lazy">'
                 if pic else '<div class="pq-thumb-empty"></div>')
        dim_str = f"{r['max_dimension']}px" if r["max_dimension"] else "—"
        return (f'<tr class="pq-row-{r["status"]}">'
                f'<td class="pq-thumb">{thumb}</td>'
                f'<td class="pq-item"><a href="{_esc(r["url"])}" target="_blank" rel="noopener">'
                f'<span class="pq-title">{title}</span>'
                f'<span class="pq-item-id">{r["item_id"]}</span></a></td>'
                f'<td class="num">{r["photo_count"]}</td>'
                f'<td class="num">{dim_str}</td>'
                f'<td>{_status_chip(r["status"])}</td>'
                f'<td class="pq-rec">Reshoot recommended — {_esc(r["recommendation"])}</td></tr>')

    def _section(heading: str, count: int, hint: str, rows_html: str, empty_msg: str) -> str:
        body_rows = rows_html or f'<tr><td colspan="6" class="pq-empty">{empty_msg}</td></tr>'
        return (f'<section class="sh-section">'
                f'<div class="sh-section-head">'
                f'<h2>{heading} <span class="sh-count">({count})</span></h2>'
                f'<span class="sh-hint">{hint}</span></div>'
                f'<div class="pq-tbl-wrap"><table class="sh-tbl pq-tbl">'
                f'<thead><tr><th>Thumb</th><th>Listing</th><th>Photos</th>'
                f'<th>Max dim</th><th>Status</th><th>Recommendation</th></tr></thead>'
                f'<tbody>{body_rows}</tbody></table></div></section>')

    def _kpi(cls: str, n: int, label: str, foot: str) -> str:
        return (f'<div class="sh-kpi pq-kpi-{cls}"><div class="sh-kpi-n">{n}</div>'
                f'<div class="sh-kpi-l">{label}</div>'
                f'<div class="sh-kpi-foot">{foot}</div></div>')

    failing_rows = "\n".join(_row(r) for r in failing)
    warning_rows = "\n".join(_row(r) for r in warning)
    total = sum(summary.values())
    pass_pct = (summary["pass"] / total * 100) if total else 0.0

    kpis = (_kpi("pass", summary['pass'], "Pass",
                 f"&ge;{PHOTO_COUNT_PASS} photos &amp; &ge;{DIM_PASS_PX}px · {pass_pct:.0f}% of book")
            + _kpi("warn", summary['warn'], "Warn", "4-7 photos or sub-1600 render")
            + _kpi("fail", summary['fail'], "Fail",
                   f"&lt;{PHOTO_COUNT_WARN} photos or &le;{DIM_FAIL_PX}px render")
            + _kpi("none", summary['no_image'], "No image",
                   "Trading API returned zero PictureURLs"))

    body = (f'<section class="hero"><h1>Photo Quality (Cassini)</h1>'
            f'<p class="sub">Last run: <code>{run_ts}</code> · auditing '
            f'<strong>{total}</strong> active listings against eBay\'s Cassini '
            f'photo-count (&ge;{PHOTO_COUNT_PASS}) and dimension '
            f'(&ge;{DIM_PASS_PX}px) signals.</p>'
            f'<div class="sh-kpis">{kpis}</div>'
            f'<p class="sh-hint">Sellers who reshoot Cassini-flagged listings see '
            f'a typical <strong>20-30%</strong> lift in impressions. This page is '
            f'a recommendation only — no eBay writes happen.</p></section>'
            + _section("Reshoot now", len(failing),
                       "Listings that fail both Cassini signals or have zero images.",
                       failing_rows,
                       "No failing listings — every active listing clears the 8-photo / 1600px Cassini bar.")
            + _section("Warning band", len(warning),
                       "Cleared the floor but missing the 8-photo Cassini optimum.",
                       warning_rows,
                       "No warning-band listings."))

    extra_css = """<style>
.hero{padding:24px 0 12px}.hero h1{margin:0 0 4px;font-family:'Bebas Neue',sans-serif;font-size:56px;letter-spacing:.02em}.hero .sub{color:var(--text-muted)}
.sh-kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:14px;margin:22px 0 28px}
.sh-kpi{background:var(--surface);border:1px solid var(--border);border-radius:var(--r-md);padding:18px 20px;position:relative;overflow:hidden}
.sh-kpi::before{content:"";position:absolute;inset:0 auto 0 0;width:3px;background:var(--gold);opacity:.7}
.sh-kpi-n{font-family:'Bebas Neue',sans-serif;font-size:44px;color:var(--gold);line-height:1}
.sh-kpi-l{color:var(--text-muted);font-size:12px;text-transform:uppercase;letter-spacing:.08em;margin-top:6px}
.sh-kpi-foot{color:var(--text-dim);font-size:11px;margin-top:8px;border-top:1px dashed var(--border);padding-top:8px}
.pq-kpi-pass::before{background:var(--success)}.pq-kpi-warn::before{background:var(--warning)}
.pq-kpi-fail::before,.pq-kpi-none::before{background:var(--danger)}
.pq-kpi-pass .sh-kpi-n{color:var(--success)}.pq-kpi-warn .sh-kpi-n{color:var(--warning)}
.pq-kpi-fail .sh-kpi-n,.pq-kpi-none .sh-kpi-n{color:var(--danger)}
.sh-section{margin:36px 0}.sh-section-head{display:flex;align-items:baseline;gap:14px;flex-wrap:wrap;margin-bottom:14px}
.sh-section-head h2{margin:0;font-family:'Bebas Neue',sans-serif;font-size:28px;letter-spacing:.02em}
.sh-count{color:var(--text-muted);font-weight:400;font-size:18px;margin-left:6px}.sh-hint{color:var(--text-muted);font-size:13px}
.pq-tbl-wrap{overflow-x:auto;border-radius:var(--r-md);border:1px solid var(--border)}
.sh-tbl{width:100%;border-collapse:collapse;font-size:13px;background:var(--surface)}
.sh-tbl th,.sh-tbl td{padding:10px 14px;text-align:left;border-bottom:1px solid var(--border);vertical-align:middle}
.sh-tbl th{background:var(--surface-2);color:var(--text-muted);font-size:11px;text-transform:uppercase;letter-spacing:.08em}
.sh-tbl tr:last-child td{border-bottom:none}.sh-tbl tr:hover td{background:var(--surface-2)}
.sh-tbl .num{text-align:right;font-variant-numeric:tabular-nums;font-family:'JetBrains Mono',monospace}
.pq-thumb img{width:56px;height:56px;object-fit:cover;border-radius:4px;display:block}
.pq-thumb-empty{width:56px;height:56px;background:var(--surface-2);border-radius:4px}
.pq-item a{text-decoration:none}.pq-item .pq-title{display:block;color:var(--text)}
.pq-item .pq-item-id{display:block;color:var(--text-dim);font-size:11px;font-family:'JetBrains Mono',monospace;margin-top:2px}
.pq-item a:hover .pq-title{color:var(--gold)}.pq-rec{color:var(--text-muted);font-size:12px;max-width:420px}
.pq-chip{display:inline-block;padding:3px 8px;border-radius:4px;font-size:10px;font-weight:700;letter-spacing:.1em;text-transform:uppercase}
.pq-chip.pq-pass{background:var(--success);color:#fff}.pq-chip.pq-warn{background:var(--warning);color:#1a1a1a}
.pq-chip.pq-fail,.pq-chip.pq-no_image{background:var(--danger);color:#fff}
.pq-row-fail td{background:linear-gradient(to right,rgba(220,60,60,.06),transparent)}
.pq-row-no_image td{background:linear-gradient(to right,rgba(220,60,60,.1),transparent)}
.pq-row-warn td{background:linear-gradient(to right,rgba(220,170,60,.05),transparent)}
.pq-empty{color:var(--text-muted);padding:20px;text-align:center}
</style>"""
    html = promote.html_shell("Photo Quality (Cassini) · Harpua2001", body,
                              extra_head=extra_css, active_page="photo_quality.html")
    REPORT_PATH.parent.mkdir(exist_ok=True)
    REPORT_PATH.write_text(html, encoding="utf-8")
    return REPORT_PATH


# === Entry point ===

def main() -> int:
    ap = argparse.ArgumentParser(description="Cassini photo-quality recommendation report.")
    ap.add_argument("--no-fetch", action="store_true",
                    help="Reuse output/photo_audit_cache.json (24h TTL) without calling Trading API.")
    ap.add_argument("--report-only", action="store_true",
                    help="Rebuild docs/photo_quality.html from output/photo_quality_plan.json.")
    args = ap.parse_args()

    if args.report_only:
        if not PLAN_PATH.exists():
            print(f"  No cached plan at {PLAN_PATH} — running a full audit.")
        else:
            plan = json.loads(PLAN_PATH.read_text())
            path = build_report(plan)
            print(f"  Report: {path}")
            return 0

    listings = _load_listings()
    cache = _load_cache()

    if args.no_fetch:
        print(f"  --no-fetch: reusing {CACHE_PATH.name} ({len(cache.get('entries', {}))} cached entries)")
        cache = collect_pictures(listings, ebay_cfg={}, token="",
                                 cache=cache, fetch=False)
    else:
        ebay_cfg = json.loads(promote.CONFIG_FILE.read_text())
        print("  Getting eBay access token...")
        token = promote.get_access_token(ebay_cfg)
        print(f"  Auditing photos for {len(listings)} listings (cache TTL = 24h)...")
        cache = collect_pictures(listings, ebay_cfg, token, cache, fetch=True)
        _save_cache(cache)

    plan = audit(listings, cache)
    PLAN_PATH.parent.mkdir(exist_ok=True)
    PLAN_PATH.write_text(json.dumps(plan, indent=2))

    s = plan["summary"]
    print(f"\n  Cassini tally: pass={s['pass']}  warn={s['warn']}  "
          f"fail={s['fail']}  no_image={s['no_image']}")
    worst = [r for r in plan["listings"] if r["status"] in ("no_image", "fail")][:5]
    if worst:
        print("\n  Top 5 worst (reshoot first):")
        for r in worst:
            dim = f"{r['max_dimension']}px" if r['max_dimension'] else "no-dim"
            print(f"    {r['item_id']}  {r['status']:<8}  "
                  f"{r['photo_count']} pics · {dim}  {r['title'][:60]}")

    path = build_report(plan)
    print(f"\n  Report: {path}")
    print(f"  Plan:   {PLAN_PATH}")
    print(f"  Cache:  {CACHE_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
