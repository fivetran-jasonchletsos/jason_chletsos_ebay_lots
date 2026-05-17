"""
photo_upload_agent.py — Reshoot queue + browser-based photo push workflow.

JC's `photo_quality_audit.py` flagged 128/128 active listings as Cassini-fail
(1 photo each at 500px; Cassini wants 8+ at >=1600x1600). Reshooting the
highest-margin items first is the single largest impressions lever we have
left — sellers who fix this see a 20-40% lift in impressions per listing.

This agent does two things:

  1. Joins `output/photo_quality_plan.json` (which lacks price) with
     `output/listings_snapshot.json` (which has price), then ranks the
     fail-status listings by listing price descending. Output:
     `output/photo_upload_queue.json`.

  2. Renders `docs/photo_upload.html` — a single-page workflow showing
     the top-20 priority listings with drag-and-drop zones, client-side
     image validation (>=8 photos, >=1600x1600), and a "Push to eBay"
     button wired to POST `{LAMBDA_BASE}/upload-photos`. The Lambda
     route is Phase 2 — until it ships, the button reports
     "Lambda route not deployed yet — files staged but not pushed".

CLI:
  python3 photo_upload_agent.py
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import promote


REPO_ROOT          = Path(__file__).parent
PHOTO_QUALITY_PLAN = REPO_ROOT / "output" / "photo_quality_plan.json"
LISTINGS_SNAPSHOT  = REPO_ROOT / "output" / "listings_snapshot.json"
QUEUE_PATH         = REPO_ROOT / "output" / "photo_upload_queue.json"
REPORT_PATH        = promote.OUTPUT_DIR / "photo_upload.html"

# The Lambda route this page POSTs to — implemented in Phase 2.
UPLOAD_ENDPOINT    = f"{promote.LAMBDA_BASE}/upload-photos"

# How many cards to render in the workflow grid. The queue JSON still
# contains the full ranked list so a future tab/page can pick up where
# we leave off.
TOP_N_FOR_PAGE     = 20

# Cassini gates — must match `photo_quality_audit.py` so the UI never
# nags about thresholds the audit doesn't enforce.
PHOTO_COUNT_PASS   = 8
DIM_PASS_PX        = 1600


# === I/O =====================================================================

def _load_json(path: Path) -> Any:
    if not path.exists():
        raise FileNotFoundError(
            f"Missing {path}. Run the upstream agent first."
        )
    return json.loads(path.read_text())


def _price_index(snapshot: list[dict]) -> dict[str, dict]:
    """item_id -> {price_float, price_str, title, url, pic}."""
    out: dict[str, dict] = {}
    for row in snapshot:
        item_id = str(row.get("item_id") or "").strip()
        if not item_id:
            continue
        try:
            price_f = float(row.get("price") or 0)
        except (TypeError, ValueError):
            price_f = 0.0
        out[item_id] = {
            "price_float": price_f,
            "price_str":   row.get("price") or "0.00",
            "title":       row.get("title") or "",
            "url":         row.get("url") or "",
            "pic":         row.get("pic") or "",
        }
    return out


def _build_queue() -> list[dict]:
    """Rank Cassini-fail listings by listing price desc."""
    plan = _load_json(PHOTO_QUALITY_PLAN)
    snapshot = _load_json(LISTINGS_SNAPSHOT)
    prices = _price_index(snapshot)

    rows: list[dict] = []
    for entry in plan.get("listings", []):
        if entry.get("status") != "fail":
            continue
        item_id = str(entry.get("item_id") or "").strip()
        if not item_id:
            continue
        meta = prices.get(item_id, {})
        rows.append({
            "item_id":        item_id,
            "title":          entry.get("title") or meta.get("title", ""),
            "url":            entry.get("url") or meta.get("url", ""),
            "pic":            entry.get("pic") or meta.get("pic", ""),
            "price":          meta.get("price_str", "0.00"),
            "price_float":    meta.get("price_float", 0.0),
            "photo_count":    int(entry.get("photo_count") or 0),
            "max_dimension":  int(entry.get("max_dimension") or 0),
            "recommendation": entry.get("recommendation", ""),
        })

    # Highest-margin items first. Stable secondary sort on item_id so
    # reruns produce identical files even when prices tie.
    rows.sort(key=lambda r: (-r["price_float"], r["item_id"]))
    for i, row in enumerate(rows, start=1):
        row["priority_rank"] = i
    return rows


def _write_queue(rows: list[dict]) -> None:
    payload = {
        "generated_at":      datetime.now(timezone.utc).isoformat(),
        "total_fail":        len(rows),
        "upload_endpoint":   UPLOAD_ENDPOINT,
        "cassini_min_count": PHOTO_COUNT_PASS,
        "cassini_min_dim":   DIM_PASS_PX,
        "listings":          rows,
    }
    QUEUE_PATH.parent.mkdir(parents=True, exist_ok=True)
    QUEUE_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")


# === HTML rendering ==========================================================

def _card_html(row: dict) -> str:
    item_id = row["item_id"]
    title = (row["title"] or "(no title)").replace("<", "&lt;").replace(">", "&gt;")
    url   = row["url"]
    pic   = row["pic"]
    price = row["price"]
    rank  = row["priority_rank"]
    return f"""
<article class="rs-card" data-item-id="{item_id}" id="card-{item_id}">
  <header class="rs-card-head">
    <div class="rs-rank">#{rank}</div>
    <div class="rs-card-meta">
      <a href="{url}" target="_blank" rel="noopener" class="rs-title">{title}</a>
      <div class="rs-sub">
        <span class="rs-price">${price}</span>
        <span class="rs-iid">{item_id}</span>
        <span class="rs-bad">1 pic · 500px</span>
      </div>
    </div>
    <a class="rs-thumb" href="{url}" target="_blank" rel="noopener">
      <img src="{pic}" alt="" loading="lazy" referrerpolicy="no-referrer">
    </a>
  </header>
  <div class="rs-drop" data-drop="{item_id}">
    <input type="file" id="files-{item_id}" multiple accept="image/*" hidden>
    <label for="files-{item_id}" class="rs-drop-label">
      <strong>Drop 8+ photos here</strong>
      <span>or click to choose — JPG/PNG, &ge;1600&times;1600</span>
    </label>
  </div>
  <div class="rs-staged" id="staged-{item_id}"></div>
  <div class="rs-validation" id="valid-{item_id}"></div>
  <div class="rs-actions">
    <button class="rs-btn rs-btn-primary" data-action="push" data-item-id="{item_id}">Push to eBay</button>
    <button class="rs-btn rs-btn-ghost"   data-action="done" data-item-id="{item_id}">Mark complete</button>
  </div>
  <div class="rs-status" id="status-{item_id}"></div>
</article>
""".strip()


def _build_body(rows: list[dict], full_count: int) -> str:
    cards = "\n".join(_card_html(r) for r in rows)
    top_n = len(rows)
    return f"""
<section class="rs-wrap">
  <header class="rs-hero">
    <h1>Reshoot Queue — {full_count} listings <span class="rs-killer">· current rank-killer: 1 pic at 500px</span></h1>
    <p class="rs-lede">
      Cassini de-ranks listings with &lt;8 photos or images smaller than 1600&times;1600.
      Reshoot the highest-margin items first — sellers who fix this see a 20-40% impressions lift per listing.
    </p>
    <div class="rs-strip">
      <div class="rs-stat">
        <div class="rs-stat-n">{full_count}</div>
        <div class="rs-stat-l">Cassini-fail listings</div>
      </div>
      <div class="rs-stat">
        <div class="rs-stat-n">{top_n}</div>
        <div class="rs-stat-l">Shown below (top by price)</div>
      </div>
      <div class="rs-stat">
        <div class="rs-stat-n">{PHOTO_COUNT_PASS}+</div>
        <div class="rs-stat-l">Photos needed each</div>
      </div>
      <div class="rs-stat">
        <div class="rs-stat-n">{DIM_PASS_PX}px</div>
        <div class="rs-stat-l">Min long edge</div>
      </div>
      <a class="rs-stat rs-stat-link" href="photo_quality.html">
        <div class="rs-stat-n">&rarr;</div>
        <div class="rs-stat-l">Full Photo Quality report</div>
      </a>
    </div>
  </header>

  <div id="rs-grid" class="rs-grid">
    {cards}
  </div>

  <section class="rs-done-wrap">
    <h2>Done today</h2>
    <div id="rs-done" class="rs-done">
      <p class="rs-empty">Nothing marked complete yet.</p>
    </div>
  </section>
</section>
""".strip()


_EXTRA_CSS = """
.rs-wrap { max-width: 1200px; margin: 0 auto; padding: 24px 16px 96px; }
.rs-hero h1 { font-family: 'Bebas Neue', sans-serif; font-size: clamp(28px, 4vw, 44px); letter-spacing:.02em; margin:0 0 8px; }
.rs-killer { color: var(--accent, #d4af37); font-weight: 400; }
.rs-lede { color: var(--text-dim, #999); max-width: 760px; margin: 0 0 20px; line-height: 1.5; }
.rs-strip { display:grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 12px; margin-bottom: 28px; }
.rs-stat { background: var(--surface, #141414); border: 1px solid var(--border, #2a2a2a); border-radius: 12px; padding: 14px 16px; }
.rs-stat-n { font-family:'Bebas Neue',sans-serif; font-size: 28px; color: var(--accent, #d4af37); }
.rs-stat-l { font-size: 12px; color: var(--text-dim, #999); text-transform: uppercase; letter-spacing:.06em; }
.rs-stat-link { text-decoration: none; color: inherit; transition: transform .15s; }
.rs-stat-link:hover { transform: translateY(-2px); }
.rs-grid { display: grid; grid-template-columns: 1fr; gap: 16px; }
@media (min-width: 880px) { .rs-grid { grid-template-columns: 1fr 1fr; } }
.rs-card { background: var(--surface, #141414); border: 1px solid var(--border, #2a2a2a); border-radius: 14px; padding: 16px; display: flex; flex-direction: column; gap: 12px; }
.rs-card.is-done { opacity: .45; }
.rs-card-head { display:grid; grid-template-columns: 40px 1fr 88px; gap: 12px; align-items: center; }
.rs-rank { font-family:'Bebas Neue',sans-serif; font-size: 28px; color: var(--accent, #d4af37); text-align:center; }
.rs-title { color: var(--text, #eee); font-weight: 600; text-decoration: none; display:block; line-height: 1.3; }
.rs-title:hover { text-decoration: underline; }
.rs-sub { display:flex; gap: 10px; align-items:center; font-size: 12px; color: var(--text-dim, #999); margin-top: 4px; flex-wrap: wrap; }
.rs-price { color: #4ade80; font-weight: 700; font-size: 14px; }
.rs-iid { font-family: ui-monospace, Menlo, monospace; }
.rs-bad { background: rgba(239,68,68,.12); color: #f87171; padding: 2px 8px; border-radius: 6px; }
.rs-thumb img { width: 88px; height: 88px; object-fit: cover; border-radius: 8px; border: 1px solid var(--border, #2a2a2a); }
.rs-drop { border: 2px dashed var(--border, #2a2a2a); border-radius: 12px; padding: 24px; text-align:center; cursor: pointer; transition: border-color .15s, background .15s; }
.rs-drop.is-hover { border-color: var(--accent, #d4af37); background: rgba(212,175,55,.06); }
.rs-drop-label { display:block; cursor: pointer; }
.rs-drop-label strong { display:block; font-size: 15px; color: var(--text, #eee); margin-bottom: 4px; }
.rs-drop-label span { font-size: 12px; color: var(--text-dim, #999); }
.rs-staged { display: grid; grid-template-columns: repeat(auto-fill, minmax(72px, 1fr)); gap: 8px; }
.rs-staged:empty { display: none; }
.rs-staged figure { margin:0; position: relative; }
.rs-staged img { width: 100%; aspect-ratio: 1/1; object-fit: cover; border-radius: 6px; border: 1px solid var(--border, #2a2a2a); }
.rs-staged figcaption { font-size: 10px; color: var(--text-dim, #999); text-align: center; margin-top: 2px; }
.rs-staged .bad img { border-color: #ef4444; }
.rs-validation { font-size: 13px; }
.rs-validation.is-error { color: #f87171; }
.rs-validation.is-ok    { color: #4ade80; }
.rs-actions { display:flex; gap: 10px; flex-wrap: wrap; }
.rs-btn { padding: 10px 16px; border-radius: 8px; font-weight: 600; cursor: pointer; border: 1px solid transparent; font-size: 14px; }
.rs-btn-primary { background: var(--accent, #d4af37); color: #0a0a0a; }
.rs-btn-primary:disabled { opacity: .4; cursor: not-allowed; }
.rs-btn-ghost { background: transparent; border-color: var(--border, #2a2a2a); color: var(--text, #eee); }
.rs-status { font-size: 13px; color: var(--text-dim, #999); min-height: 1.2em; }
.rs-status.is-warn { color: #fbbf24; }
.rs-status.is-ok   { color: #4ade80; }
.rs-status.is-err  { color: #f87171; }
.rs-done-wrap { margin-top: 36px; }
.rs-done-wrap h2 { font-family:'Bebas Neue',sans-serif; font-size: 24px; letter-spacing:.04em; }
.rs-done { display: flex; flex-direction: column; gap: 6px; }
.rs-done .rs-empty { color: var(--text-dim, #999); font-style: italic; }
.rs-done .rs-done-row { padding: 8px 12px; background: var(--surface, #141414); border: 1px solid var(--border, #2a2a2a); border-radius: 8px; font-size: 13px; }
"""


def _build_script() -> str:
    return """
<script>
(function() {
  const ENDPOINT = """ + json.dumps(UPLOAD_ENDPOINT) + """;
  const MIN_COUNT = """ + str(PHOTO_COUNT_PASS) + """;
  const MIN_DIM   = """ + str(DIM_PASS_PX) + """;
  // Per-listing staged file state — in-memory only so a refresh clears stale files.
  const staged = new Map();

  function fmtKB(n) { return (n / 1024).toFixed(0) + ' KB'; }

  function probeDim(file) {
    return new Promise((resolve) => {
      const url = URL.createObjectURL(file);
      const img = new Image();
      img.onload = () => { resolve({ w: img.naturalWidth, h: img.naturalHeight, url }); };
      img.onerror = () => { resolve({ w: 0, h: 0, url }); };
      img.src = url;
    });
  }

  async function renderStaged(itemId) {
    const files = staged.get(itemId) || [];
    const wrap  = document.getElementById('staged-' + itemId);
    const valid = document.getElementById('valid-' + itemId);
    wrap.innerHTML = '';
    let smallCount = 0;
    for (const file of files) {
      const probe = await probeDim(file);
      const fig = document.createElement('figure');
      const small = probe.w < MIN_DIM || probe.h < MIN_DIM;
      if (small) { fig.classList.add('bad'); smallCount++; }
      fig.innerHTML = '<img src="' + probe.url + '" alt="">' +
                      '<figcaption>' + probe.w + '×' + probe.h + '<br>' + fmtKB(file.size) + '</figcaption>';
      wrap.appendChild(fig);
    }
    // Validate.
    const messages = [];
    if (files.length < MIN_COUNT) {
      messages.push('Need at least ' + MIN_COUNT + ' photos (have ' + files.length + ').');
    }
    if (smallCount > 0) {
      messages.push(smallCount + ' photo(s) below ' + MIN_DIM + '×' + MIN_DIM + '.');
    }
    if (messages.length) {
      valid.className = 'rs-validation is-error';
      valid.textContent = messages.join(' ');
    } else if (files.length === 0) {
      valid.className = 'rs-validation';
      valid.textContent = '';
    } else {
      valid.className = 'rs-validation is-ok';
      valid.textContent = files.length + ' photos ready, all ≥' + MIN_DIM + 'px.';
    }
    const pushBtn = document.querySelector('[data-action="push"][data-item-id="' + itemId + '"]');
    if (pushBtn) pushBtn.disabled = !(files.length >= MIN_COUNT && smallCount === 0);
  }

  function addFiles(itemId, fileList) {
    const cur = staged.get(itemId) || [];
    for (const f of fileList) {
      if (f && f.type && f.type.startsWith('image/')) cur.push(f);
    }
    staged.set(itemId, cur);
    renderStaged(itemId);
  }

  // Wire all drop zones.
  document.querySelectorAll('.rs-drop').forEach(zone => {
    const itemId = zone.getAttribute('data-drop');
    const input  = document.getElementById('files-' + itemId);
    input.addEventListener('change', (e) => addFiles(itemId, e.target.files));
    zone.addEventListener('dragover', (e) => { e.preventDefault(); zone.classList.add('is-hover'); });
    zone.addEventListener('dragleave', () => zone.classList.remove('is-hover'));
    zone.addEventListener('drop', (e) => {
      e.preventDefault();
      zone.classList.remove('is-hover');
      addFiles(itemId, e.dataTransfer.files);
    });
  });

  // Push to eBay — POST multipart to Lambda. Until Phase 2 ships
  // the route returns 404/405 and we surface a friendly notice.
  document.querySelectorAll('[data-action="push"]').forEach(btn => {
    btn.disabled = true;
    btn.addEventListener('click', async () => {
      const itemId = btn.getAttribute('data-item-id');
      const files = staged.get(itemId) || [];
      const status = document.getElementById('status-' + itemId);
      if (files.length < MIN_COUNT) {
        status.className = 'rs-status is-err';
        status.textContent = 'Need at least ' + MIN_COUNT + ' photos.';
        return;
      }
      const fd = new FormData();
      fd.append('item_id', itemId);
      files.forEach((f, i) => fd.append('files', f, f.name || ('photo-' + i + '.jpg')));
      status.className = 'rs-status is-warn';
      status.textContent = 'Uploading ' + files.length + ' photos…';
      try {
        const resp = await fetch(ENDPOINT, { method: 'POST', body: fd });
        if (resp.status === 404 || resp.status === 405 || resp.status === 501) {
          status.className = 'rs-status is-warn';
          status.textContent = 'Lambda route not deployed yet — files staged but not pushed.';
          return;
        }
        if (!resp.ok) {
          const text = await resp.text();
          status.className = 'rs-status is-err';
          status.textContent = 'Upload failed (' + resp.status + '): ' + text.slice(0, 200);
          return;
        }
        const data = await resp.json().catch(() => ({}));
        status.className = 'rs-status is-ok';
        status.textContent = 'Pushed ' + (data.count || files.length) + ' photos to eBay.';
      } catch (err) {
        status.className = 'rs-status is-warn';
        status.textContent = 'Lambda route not deployed yet — files staged but not pushed. (' + err.message + ')';
      }
    });
  });

  // Mark complete — move card into "done today" pile.
  document.querySelectorAll('[data-action="done"]').forEach(btn => {
    btn.addEventListener('click', () => {
      const itemId = btn.getAttribute('data-item-id');
      const card = document.getElementById('card-' + itemId);
      if (!card) return;
      card.classList.add('is-done');
      const title = card.querySelector('.rs-title');
      const done  = document.getElementById('rs-done');
      const empty = done.querySelector('.rs-empty');
      if (empty) empty.remove();
      const row = document.createElement('div');
      row.className = 'rs-done-row';
      row.textContent = '✓ ' + (title ? title.textContent : itemId) + ' · ' + itemId;
      done.appendChild(row);
      setTimeout(() => card.remove(), 250);
    });
  });
})();
</script>
"""


def render_page(rows: list[dict], full_count: int) -> Path:
    top = rows[:TOP_N_FOR_PAGE]
    body = _build_body(top, full_count) + _build_script()
    extra_head = f"<style>{_EXTRA_CSS}</style>"
    html = promote.html_shell(
        f"Photo Upload · {promote.SELLER_NAME}",
        body,
        extra_head=extra_head,
        active_page="photo_upload.html",
    )
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(html, encoding="utf-8")
    return REPORT_PATH


# === CLI =====================================================================

def main() -> int:
    rows = _build_queue()
    _write_queue(rows)
    out = render_page(rows, full_count=len(rows))
    top5 = ", ".join(f"{r['item_id']}(${r['price']})" for r in rows[:5])
    print(f"[photo_upload_agent] queued {len(rows)} fail listings -> {QUEUE_PATH}")
    print(f"[photo_upload_agent] rendered {out}")
    print(f"[photo_upload_agent] top 5 priority: {top5}")
    print(f"[photo_upload_agent] upload endpoint: {UPLOAD_ENDPOINT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
