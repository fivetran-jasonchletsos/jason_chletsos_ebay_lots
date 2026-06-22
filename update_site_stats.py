"""update_site_stats.py — refresh the public showcase pages with current numbers.

Recomputes the hero stats from output/listings_snapshot.json + sold_history.json
and rewrites them in-place in docs/engine.html, then regenerates docs/stats.html.
Deterministic (no AI) so it can run on a schedule. Run AFTER refresh_snapshot.py
so the snapshot is current.

    python3 refresh_snapshot.py && python3 update_site_stats.py
"""
from __future__ import annotations
import json, re, subprocess, sys
from datetime import datetime
from pathlib import Path
try:
    from zoneinfo import ZoneInfo
    NOW = datetime.now(ZoneInfo("America/New_York"))
except Exception:
    NOW = datetime.now()

REPO = Path(__file__).parent
SNAP = REPO / "output" / "listings_snapshot.json"
SOLD = REPO / "sold_history.json"
ENGINE = REPO / "docs" / "engine.html"


def _price(it: dict) -> float:
    for k in ("price", "Price", "current_price", "start_price", "StartPrice"):
        v = it.get(k)
        if isinstance(v, dict):
            v = v.get("value") or v.get("#text")
        try:
            return float(v)
        except (TypeError, ValueError):
            continue
    return 0.0


def compute_stats() -> dict:
    snap = json.loads(SNAP.read_text())
    items = snap.get("listings", snap) if isinstance(snap, dict) else snap
    active = len(items)
    value = sum(_price(it) for it in items)
    sold = 0
    if SOLD.is_file():
        sd = json.loads(SOLD.read_text())
        rows = sd if isinstance(sd, list) else (sd.get("orders") or sd.get("sold") or list(sd.values()))
        sold = len(rows) if hasattr(rows, "__len__") else 0
    return {"active": active, "value": value, "sold": sold}


def _sub_stat(html: str, label: str, new_value: str) -> str:
    """Replace the <div class="v">…</div> that precedes a given stat label."""
    pat = re.compile(r'(<div class="v">)[^<]*(</div><div class="l">' + re.escape(label) + r'</div>)')
    new_html, n = pat.subn(lambda m: m.group(1) + new_value + m.group(2), html)
    if n == 0:
        print(f"  WARN: stat label not found, skipped: {label!r}")
    return new_html


def update_engine(stats: dict) -> bool:
    if not ENGINE.is_file():
        print("  engine.html not found, skipping")
        return False
    html = ENGINE.read_text()
    html = _sub_stat(html, "Active listings", f"{stats['active']:,}")
    html = _sub_stat(html, "Inventory value", f"${stats['value']:,.0f}")
    html = _sub_stat(html, "Cards sold", f"{stats['sold']:,}")
    # "Posted in one day" (record) and "Daily agents" are left as-is.
    # Stamp/refresh an "updated" line just below the stat row.
    stamp = f"Stats auto-updated {NOW:%b %-d, %Y %-I:%M %p ET}"
    if "id=\"stats-updated\"" in html:
        html = re.sub(r'(<p id="stats-updated"[^>]*>)[^<]*(</p>)',
                      lambda m: m.group(1) + stamp + m.group(2), html)
    else:
        # inject right after the first </div> that closes the stat row container
        marker = '<div class="l">Daily agents</div></div>'
        if marker in html:
            anchor = html.index(marker) + len(marker)
            end = html.index("</div>", anchor) + len("</div>")
            inject = f'\n    <p id="stats-updated" style="margin:10px 0 0;font-size:12px;color:#98a2b3">{stamp}</p>'
            html = html[:end] + inject + html[end:]
    ENGINE.write_text(html)
    print(f"  engine.html updated: {stats['active']:,} active · ${stats['value']:,.0f} · {stats['sold']:,} sold")
    return True


def regen_stats_page() -> None:
    script = REPO / "build_stats_page.py"
    if script.is_file():
        r = subprocess.run([sys.executable, str(script)], capture_output=True, text=True)
        print("  stats.html regenerated" if r.returncode == 0 else f"  stats.html FAILED: {r.stderr[-300:]}")
    else:
        print("  build_stats_page.py not found, skipping stats.html")


if __name__ == "__main__":
    s = compute_stats()
    update_engine(s)
    regen_stats_page()
    print("Done.")
