"""
site_health_agent.py — Site health monitor for Harpua2001 / jason_chletsos_ebay_lots.

Checks:
  1. GitHub Pages index.html responds 200
  2. Key pages (daily.html, browse.html, deals.html) load without error
  3. listings_snapshot.json freshness — warn if older than 24 h
  4. docs/daily.html freshness — warn if not regenerated today
  5. Lambda /health endpoint responds 200
  6. eBay OAuth token validity — lightweight sell/account call, check for 401
  7. output/ plan files freshness — warn if any core plan older than 48 h
  8. Active listing count — warn if dropped >10% from previous run
  9. sold_history.json — warn if last entry older than 3 days

Outputs:
  output/site_health_report.json
  docs/health.html

Exit code 0 if all green, 1 if any red.

Run standalone:
  python3 site_health_agent.py

Or imported and called as:
  import site_health_agent; site_health_agent.main()
"""

from __future__ import annotations

AGENT_NAME = "Luc Robitaille"
AGENT_ROLE = "Site Health"

import base64
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from html import escape
from pathlib import Path
from typing import Any

import requests

import promote

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
REPO_ROOT    = Path(__file__).parent
OUTPUT_DIR   = REPO_ROOT / "output"
DOCS_DIR     = REPO_ROOT / "docs"
CFG_PATH     = REPO_ROOT / "configuration.json"
SNAP_PATH    = OUTPUT_DIR / "listings_snapshot.json"
SOLD_PATH    = REPO_ROOT / "sold_history.json"
DAILY_PATH   = DOCS_DIR  / "daily.html"
REPORT_JSON  = OUTPUT_DIR / "site_health_report.json"
REPORT_HTML  = DOCS_DIR   / "health.html"
PREV_SNAP    = OUTPUT_DIR / "site_health_listing_count.json"

SITE_BASE    = promote.SITE_URL   # "https://fivetran-jasonchletsos.github.io/jason_chletsos_ebay_lots"
LAMBDA_BASE  = promote.LAMBDA_BASE

# Core plans that must be refreshed within 48 hours.
CORE_PLANS = [
    "listings_snapshot.json",
    "repricing_plan.json",
    "relist_plan.json",
    "photo_audit.json",
    "cassini_score_plan.json",
    "price_drops_plan.json",
    "price_consistency_report.json",
    "browse_index_plan.json",
]

TIMEOUT = 12  # seconds per HTTP request

# ---------------------------------------------------------------------------
# Result helpers
# ---------------------------------------------------------------------------

def _ok(name: str, detail: str) -> dict:
    return {"check": name, "status": "green", "detail": detail}


def _warn(name: str, detail: str) -> dict:
    return {"check": name, "status": "yellow", "detail": detail}


def _fail(name: str, detail: str) -> dict:
    return {"check": name, "status": "red", "detail": detail}


def _load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return default


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------

def check_site_index() -> dict:
    url = f"{SITE_BASE}/index.html"
    try:
        r = requests.get(url, timeout=TIMEOUT)
        if r.status_code == 200:
            return _ok("GitHub Pages index", f"HTTP {r.status_code} — {url}")
        return _fail("GitHub Pages index", f"HTTP {r.status_code} — {url}")
    except requests.RequestException as e:
        return _fail("GitHub Pages index", str(e)[:120])


def check_key_pages() -> dict:
    pages = ["daily.html", "browse.html", "deals.html"]
    bad = []
    for page in pages:
        url = f"{SITE_BASE}/{page}"
        try:
            r = requests.get(url, timeout=TIMEOUT)
            if r.status_code != 200:
                bad.append(f"{page} HTTP {r.status_code}")
        except requests.RequestException as e:
            bad.append(f"{page} error: {str(e)[:60]}")
    if not bad:
        return _ok("Key pages", f"daily, browse, deals — all 200")
    return _fail("Key pages", "; ".join(bad))


def check_snapshot_freshness() -> dict:
    if not SNAP_PATH.exists():
        return _fail("Snapshot freshness", "listings_snapshot.json not found")
    mtime = datetime.fromtimestamp(SNAP_PATH.stat().st_mtime, tz=timezone.utc)
    age   = datetime.now(timezone.utc) - mtime
    age_h = age.total_seconds() / 3600
    label = f"{age_h:.1f}h old"
    if age_h <= 24:
        return _ok("Snapshot freshness", label)
    if age_h <= 48:
        return _warn("Snapshot freshness", f"{label} — run promote.py to refresh")
    return _fail("Snapshot freshness", f"{label} — stale, run promote.py")


def check_daily_freshness() -> dict:
    if not DAILY_PATH.exists():
        return _warn("Daily digest freshness", "docs/daily.html not found")
    mtime   = datetime.fromtimestamp(DAILY_PATH.stat().st_mtime, tz=timezone.utc)
    today   = datetime.now(timezone.utc).date()
    if mtime.date() >= today:
        return _ok("Daily digest freshness", f"regenerated today at {mtime.strftime('%H:%M UTC')}")
    age_h = (datetime.now(timezone.utc) - mtime).total_seconds() / 3600
    return _warn("Daily digest freshness", f"{age_h:.1f}h old — run daily_digest_agent.py")


def check_lambda_health() -> dict:
    # /health is at the API Gateway root stage, not under the /ebay prefix
    url = LAMBDA_BASE.rstrip("/ebay").rstrip("/") + "/health"
    try:
        r = requests.get(url, timeout=TIMEOUT)
        if r.status_code == 200:
            return _ok("Lambda /health", f"HTTP 200 — {url}")
        return _fail("Lambda /health", f"HTTP {r.status_code}")
    except requests.RequestException as e:
        return _fail("Lambda /health", str(e)[:120])


def check_ebay_token() -> dict:
    """Validate eBay OAuth by exchanging refresh_token for an access token and
    making a cheap GET to sell/account/v1/privilege (returns 200 even for
    read-only; returns 401 only when the token is expired/revoked)."""
    try:
        cfg = json.loads(CFG_PATH.read_text(encoding="utf-8"))
    except Exception as e:
        return _fail("eBay OAuth token", f"config unreadable: {e}")

    try:
        creds = base64.b64encode(f"{cfg['client_id']}:{cfg['client_secret']}".encode()).decode()
        resp = requests.post(
            "https://api.ebay.com/identity/v1/oauth2/token",
            headers={
                "Authorization": f"Basic {creds}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data={
                "grant_type":   "refresh_token",
                "refresh_token": cfg["refresh_token"],
                "scope": " ".join([
                    "https://api.ebay.com/oauth/api_scope",
                    "https://api.ebay.com/oauth/api_scope/sell.account.readonly",
                ]),
            },
            timeout=TIMEOUT,
        )
    except requests.RequestException as e:
        return _fail("eBay OAuth token", f"token request failed: {e}")

    if resp.status_code == 401:
        return _fail("eBay OAuth token", "401 — refresh_token expired; re-authenticate")
    if not resp.ok:
        return _fail("eBay OAuth token", f"HTTP {resp.status_code}: {resp.text[:120]}")

    token = resp.json().get("access_token", "")
    # Lightweight call: GET /sell/account/v1/return_policy (1 result page, fast)
    try:
        ping = requests.get(
            "https://api.ebay.com/sell/account/v1/return_policy?marketplace_id=EBAY_US",
            headers={"Authorization": f"Bearer {token}"},
            timeout=TIMEOUT,
        )
    except requests.RequestException as e:
        return _warn("eBay OAuth token", f"token OK but ping failed: {e}")

    if ping.status_code == 401:
        return _fail("eBay OAuth token", "access_token rejected by eBay API (401)")
    return _ok("eBay OAuth token", f"valid — sell/account ping HTTP {ping.status_code}")


def check_plan_freshness() -> dict:
    """Warn if any core plan file hasn't been refreshed in the last 48 hours."""
    stale: list[str] = []
    missing: list[str] = []
    now = datetime.now(timezone.utc)
    for fname in CORE_PLANS:
        p = OUTPUT_DIR / fname
        if not p.exists():
            missing.append(fname)
            continue
        age_h = (now - datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc)).total_seconds() / 3600
        if age_h > 48:
            stale.append(f"{fname} ({age_h:.0f}h)")
    issues = [f"missing: {f}" for f in missing] + [f"stale: {s}" for s in stale]
    if not issues:
        return _ok("Plan file freshness", f"all {len(CORE_PLANS)} core plans < 48h old")
    level = _fail if missing else _warn
    return level("Plan file freshness", "; ".join(issues))


def check_listing_count() -> dict:
    """Load snapshot, count actives, compare to previous run (10% drop = red)."""
    raw = _load_json(SNAP_PATH, None)
    if raw is None:
        return _fail("Active listing count", "listings_snapshot.json missing")
    if isinstance(raw, dict):
        listings = raw.get("listings", [])
    else:
        listings = raw if isinstance(raw, list) else []
    current = len(listings)

    prev_data = _load_json(PREV_SNAP, {})
    prev_count = prev_data.get("count") if isinstance(prev_data, dict) else None

    # Persist current count for next run.
    PREV_SNAP.parent.mkdir(exist_ok=True)
    PREV_SNAP.write_text(json.dumps({
        "count":        current,
        "recorded_at":  datetime.now(timezone.utc).isoformat(),
    }, indent=2))

    if prev_count is None:
        return _ok("Active listing count", f"{current} listings (baseline established)")
    drop_pct = (prev_count - current) / max(prev_count, 1) * 100
    if drop_pct > 10:
        return _fail(
            "Active listing count",
            f"{current} now vs {prev_count} prev — {drop_pct:.1f}% drop",
        )
    if drop_pct > 0:
        return _warn(
            "Active listing count",
            f"{current} now vs {prev_count} prev — {drop_pct:.1f}% drop",
        )
    return _ok("Active listing count", f"{current} listings ({abs(drop_pct):.1f}% change from {prev_count})")


def check_sold_history() -> dict:
    raw = _load_json(SOLD_PATH, None)
    if raw is None:
        return _warn("Sold history", "sold_history.json not found")
    if not isinstance(raw, list) or not raw:
        return _warn("Sold history", "sold_history.json is empty")
    # Find the most recent sold_date across all entries.
    now = datetime.now(timezone.utc)
    latest: datetime | None = None
    for row in raw:
        s = row.get("sold_date") or row.get("date") or ""
        try:
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            if latest is None or dt > latest:
                latest = dt
        except (ValueError, TypeError):
            continue
    if latest is None:
        return _warn("Sold history", f"{len(raw)} entries, no parseable dates")
    age_h = (now - latest).total_seconds() / 3600
    age_d = age_h / 24
    label = f"last sale {age_d:.1f}d ago ({latest.strftime('%Y-%m-%d')})"
    if age_d <= 3:
        return _ok("Sold history", label)
    if age_d <= 7:
        return _warn("Sold history", f"{label} — no sales in 3+ days")
    return _fail("Sold history", f"{label} — no sales in 7+ days; check pricing")


# ---------------------------------------------------------------------------
# Run all checks
# ---------------------------------------------------------------------------

def run_checks() -> list[dict]:
    checks = [
        check_site_index,
        check_key_pages,
        check_snapshot_freshness,
        check_daily_freshness,
        check_lambda_health,
        check_ebay_token,
        check_plan_freshness,
        check_listing_count,
        check_sold_history,
    ]
    results = []
    for fn in checks:
        label = fn.__name__.replace("check_", "").replace("_", " ").title()
        print(f"  Checking {label}...", end=" ", flush=True)
        try:
            r = fn()
        except Exception as exc:
            r = _fail(label, f"unexpected error: {exc}")
        status_char = {"green": "OK", "yellow": "WARN", "red": "FAIL"}.get(r["status"], "?")
        print(status_char)
        results.append(r)
    return results


# ---------------------------------------------------------------------------
# Table output
# ---------------------------------------------------------------------------

def print_table(results: list[dict]) -> None:
    col_check  = max(len(r["check"])  for r in results)
    col_status = 6  # "yellow" is longest
    print()
    header = f"  {'CHECK':<{col_check}}  {'STATUS':<{col_status}}  DETAIL"
    print(header)
    print("  " + "-" * (len(header) - 2))
    for r in results:
        s = r["status"].upper()
        print(f"  {r['check']:<{col_check}}  {s:<{col_status}}  {r['detail']}")
    print()


# ---------------------------------------------------------------------------
# HTML dashboard
# ---------------------------------------------------------------------------

_CSS = """<style>
.sh-hero{padding:28px 0 12px;border-bottom:1px solid var(--border);margin-bottom:24px}
.sh-hero h1{margin:0 0 4px;font-family:'Fraunces',Georgia,serif;font-style:italic;font-weight:500;font-variation-settings:'opsz' 144,'SOFT' 30,'WONK' 1;letter-spacing:-0.005em;font-size:52px;letter-spacing:.02em;color:var(--text)}
.sh-hero .sub{color:var(--text-muted);font-size:14px;margin:6px 0 0}
.sh-summary{display:flex;gap:14px;flex-wrap:wrap;margin:20px 0 28px}
.sh-pill{padding:8px 18px;border-radius:20px;font-family:'JetBrains Mono',monospace;font-size:13px;font-weight:700;border:1px solid transparent}
.sh-pill-green{background:rgba(60,180,90,.15);color:var(--success);border-color:rgba(60,180,90,.3)}
.sh-pill-yellow{background:rgba(220,170,60,.12);color:var(--warning);border-color:rgba(220,170,60,.3)}
.sh-pill-red{background:rgba(220,60,60,.12);color:var(--danger);border-color:rgba(220,60,60,.3)}
.sh-tbl-wrap{overflow-x:auto;border-radius:var(--r-md);border:1px solid var(--border);margin-bottom:32px}
.sh-tbl{width:100%;border-collapse:collapse;font-size:13px;background:var(--surface)}
.sh-tbl th{background:var(--surface-2);color:var(--text-muted);font-size:10px;text-transform:uppercase;letter-spacing:.1em;padding:10px 16px;text-align:left;border-bottom:1px solid var(--border)}
.sh-tbl td{padding:11px 16px;border-bottom:1px solid var(--border);vertical-align:middle}
.sh-tbl tr:last-child td{border-bottom:none}
.sh-tbl tr:hover td{background:var(--surface-2)}
.sh-badge{display:inline-block;padding:3px 10px;border-radius:3px;font-family:'JetBrains Mono',monospace;font-size:11px;font-weight:700;min-width:48px;text-align:center}
.sh-badge-green{background:var(--success);color:#fff}
.sh-badge-yellow{background:var(--warning);color:#1a1a1a}
.sh-badge-red{background:var(--danger);color:#fff}
.sh-detail{color:var(--text-muted);font-size:12px;font-family:'JetBrains Mono',monospace}
.sh-foot{margin:24px 0 8px;padding:14px;background:var(--surface-2);border:1px solid var(--border);border-radius:var(--r-md);font-family:'JetBrains Mono',monospace;font-size:11px;color:var(--text-muted);text-align:center;letter-spacing:.06em}
.sh-foot code{color:var(--gold);background:var(--surface);padding:2px 6px;border-radius:3px}
</style>"""


def build_html(results: list[dict], ts: str) -> str:
    counts = {"green": 0, "yellow": 0, "red": 0}
    for r in results:
        counts[r["status"]] = counts.get(r["status"], 0) + 1

    overall = "All systems nominal" if counts["red"] == 0 and counts["yellow"] == 0 \
        else ("Issues detected" if counts["red"] > 0 else "Warnings")

    pills = (
        f"<span class='sh-pill sh-pill-green'>{counts['green']} green</span>"
        f"<span class='sh-pill sh-pill-yellow'>{counts['yellow']} warning{'s' if counts['yellow'] != 1 else ''}</span>"
        f"<span class='sh-pill sh-pill-red'>{counts['red']} red</span>"
    )

    def _row(r: dict) -> str:
        st = r["status"]
        return (
            f"<tr>"
            f"<td>{escape(r['check'])}</td>"
            f"<td><span class='sh-badge sh-badge-{st}'>{st.upper()}</span></td>"
            f"<td class='sh-detail'>{escape(r['detail'])}</td>"
            f"</tr>"
        )
    rows_html = "".join(_row(r) for r in results)

    body = (
        f"<section class='sh-hero'>"
        f"<h1>Site Health</h1>"
        f"<p class='sub'>{escape(overall)} &middot; last checked {escape(ts)}</p>"
        f"</section>"
        f"<div class='sh-summary'>{pills}</div>"
        f"<div class='sh-tbl-wrap'><table class='sh-tbl'>"
        f"<thead><tr><th>Check</th><th>Status</th><th>Detail</th></tr></thead>"
        f"<tbody>{rows_html}</tbody></table></div>"
        f"<div class='sh-foot'>Filed by <strong>{escape(AGENT_NAME)}</strong> "
        f"({escape(AGENT_ROLE)}) &middot; {escape(ts)} &middot; "
        f"run <code>python3 site_health_agent.py</code> to refresh.</div>"
    )

    return promote.html_shell(
        f"Site Health · {promote.SELLER_NAME}",
        body,
        extra_head=_CSS,
        active_page="health.html",
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    print(f"  {AGENT_NAME} ({AGENT_ROLE}) reporting in.")
    now = datetime.now(timezone.utc)
    ts  = now.strftime("%Y-%m-%d %H:%M UTC")
    print(f"  Site health check @ {ts}")
    print()

    results = run_checks()
    print_table(results)

    # Write JSON report.
    OUTPUT_DIR.mkdir(exist_ok=True)
    report = {
        "generated_at": now.isoformat(),
        "summary": {
            s: sum(1 for r in results if r["status"] == s)
            for s in ("green", "yellow", "red")
        },
        "checks": results,
    }
    REPORT_JSON.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"  Report JSON: {REPORT_JSON}")

    # Write HTML dashboard.
    DOCS_DIR.mkdir(exist_ok=True)
    REPORT_HTML.write_text(build_html(results, ts), encoding="utf-8")
    print(f"  Report HTML: {REPORT_HTML}")

    any_red = any(r["status"] == "red" for r in results)
    exit_code = 1 if any_red else 0
    label = "FAIL — one or more checks are red." if any_red else "All checks passed."
    print(f"\n  Overall: {label}")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
