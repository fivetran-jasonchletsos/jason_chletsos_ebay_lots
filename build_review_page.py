"""build_review_page.py — generate docs/review.html, a QC page for posted cards.

Reads:
  output/posted_manifest_22_39.json   (image, item_id, title, price, batch)
  output/_verify_results.json         (item_id -> confidence, player_ok, suggested_title, issue)

Static page (works on GitHub Pages). JC reviews every posted card against its
crop, lowest-confidence first, marks the wrong ones, and exports corrections as
a paste-back block. Motivated by a Charles-Woodson-listed-as-Davante-Adams
mis-ID that slipped through.
"""
import json, html
from pathlib import Path

REPO = Path(__file__).parent
posted = json.loads((REPO / "output/posted_manifest_22_39.json").read_text())
vpath = REPO / "output/_verify_results.json"
verify = json.loads(vpath.read_text()) if vpath.is_file() else {}

rows = []
for c in posted:
    iid = str(c["item_id"])
    v = verify.get(iid, {})
    rows.append({
        "item_id": iid,
        "title": c["title"],
        "price": float(c["price"]),
        "batch": c["batch"],
        "conf": float(v.get("confidence", 0.5)),
        "player_ok": bool(v.get("player_ok", True)),
        "suggested": v.get("suggested_title", "") or "",
        "issue": v.get("issue", "") or "",
    })

rows.sort(key=lambda r: (r["player_ok"], r["conf"]))
low = sum(1 for r in rows if r["conf"] < 0.7 or not r["player_ok"])
total = len(rows)
total_val = sum(r["price"] for r in rows)


def conf_class(r):
    if not r["player_ok"] or r["conf"] < 0.4:
        return "bad"
    if r["conf"] < 0.7:
        return "warn"
    return "ok"


cards_html = []
for r in rows:
    cc = conf_class(r)
    pct = int(round(r["conf"] * 100))
    sugg = ""
    if r["suggested"]:
        sa = html.escape(r["suggested"], quote=True)
        sugg = ('<div class="sugg">suggested: <button class="usesugg" data-sugg="'
                + sa + '">' + html.escape(r["suggested"]) + "</button></div>")
    issue = ('<div class="issue">' + html.escape(r["issue"]) + "</div>") if r["issue"] else ""
    flag = " · PLAYER?" if not r["player_ok"] else ""
    cards_html.append(
        '<div class="card ' + cc + '" data-id="' + r["item_id"]
        + '" data-conf="' + ("%.2f" % r["conf"]) + '" data-playerok="' + str(r["player_ok"]).lower() + '">'
        + '<img loading="lazy" src="review_imgs/' + r["item_id"] + '.jpg" alt="">'
        + '<div class="meta">'
        + '<div class="conf ' + cc + '">' + str(pct) + "%" + flag + "</div>"
        + '<div class="title" title="' + html.escape(r["title"], quote=True) + '">' + html.escape(r["title"]) + "</div>"
        + '<div class="sub">$' + ("%.2f" % r["price"]) + ' · <a href="https://www.ebay.com/itm/'
        + r["item_id"] + '" target="_blank" rel="noopener">' + r["item_id"] + "</a></div>"
        + issue + sugg
        + '<div class="actions"><button class="good">Looks good</button><button class="wrong">Wrong</button></div>'
        + '<textarea class="fix" placeholder="Correct title (or note)" rows="2"></textarea>'
        + "</div></div>"
    )

CSS = """
  :root { --bg:#0f1115; --surface:#1a1d24; --surface2:#222630; --border:#2c313c;
          --text:#e6e8ec; --muted:#9aa3b0; --ok:#2ecc71; --warn:#f1c40f; --bad:#e74c3c; --accent:#4a9eff; }
  * { box-sizing:border-box; }
  body { margin:0; background:var(--bg); color:var(--text); font:15px/1.45 -apple-system,Segoe UI,Roboto,sans-serif; }
  header { position:sticky; top:0; z-index:5; background:var(--surface); border-bottom:1px solid var(--border); padding:14px 20px; }
  h1 { font-size:18px; margin:0 0 6px; }
  .stats { color:var(--muted); font-size:13px; }
  .stats b { color:var(--text); }
  .bar { display:flex; gap:8px; flex-wrap:wrap; margin-top:10px; align-items:center; }
  .bar button { background:var(--surface2); color:var(--text); border:1px solid var(--border); border-radius:7px; padding:6px 12px; cursor:pointer; font-size:13px; }
  .bar button.active { border-color:var(--accent); color:var(--accent); }
  .bar .spacer { flex:1; }
  #copy { background:var(--accent); color:#fff; border:none; font-weight:600; }
  #count { color:var(--muted); font-size:13px; }
  .grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(280px,1fr)); gap:14px; padding:18px 20px; }
  .card { background:var(--surface); border:1px solid var(--border); border-radius:11px; overflow:hidden; display:flex; flex-direction:column; }
  .card.bad { border-color:var(--bad); }
  .card.warn { border-color:var(--warn); }
  .card img { width:100%; height:240px; object-fit:contain; background:#000; }
  .meta { padding:10px 12px; display:flex; flex-direction:column; gap:6px; }
  .conf { font-weight:700; font-size:13px; width:fit-content; padding:2px 8px; border-radius:6px; }
  .conf.ok { background:rgba(46,204,113,.15); color:var(--ok); }
  .conf.warn { background:rgba(241,196,15,.15); color:var(--warn); }
  .conf.bad { background:rgba(231,76,60,.18); color:var(--bad); }
  .title { font-size:13.5px; font-weight:600; }
  .sub { font-size:12px; color:var(--muted); }
  .sub a { color:var(--accent); text-decoration:none; }
  .issue { font-size:12px; color:var(--warn); }
  .sugg { font-size:12px; color:var(--muted); }
  .sugg .usesugg { background:none; border:1px dashed var(--border); color:var(--accent); border-radius:5px; padding:2px 6px; cursor:pointer; font-size:12px; text-align:left; }
  .actions { display:flex; gap:6px; }
  .actions button { flex:1; border:1px solid var(--border); background:var(--surface2); color:var(--text); border-radius:6px; padding:5px; cursor:pointer; font-size:12.5px; }
  .card.mark-good .good { background:var(--ok); color:#04210f; border-color:var(--ok); }
  .card.mark-wrong .wrong { background:var(--bad); color:#fff; border-color:var(--bad); }
  .fix { display:none; width:100%; background:var(--surface2); color:var(--text); border:1px solid var(--border); border-radius:6px; padding:6px; font:13px inherit; resize:vertical; }
  .card.mark-wrong .fix { display:block; }
  footer { padding:24px 20px 60px; color:var(--muted); font-size:12px; text-align:center; }
"""

JS = r"""
  const LS = 'jc2_review_22_39';
  let state = JSON.parse(localStorage.getItem(LS) || '{}');
  function save() { localStorage.setItem(LS, JSON.stringify(state)); }
  function apply(card) {
    const id = card.dataset.id, s = state[id] || {};
    card.classList.toggle('mark-good', s.status === 'good');
    card.classList.toggle('mark-wrong', s.status === 'wrong');
    const fix = card.querySelector('.fix');
    if (s.fix != null && fix.value !== s.fix) fix.value = s.fix;
  }
  document.querySelectorAll('.card').forEach(card => {
    const id = card.dataset.id;
    apply(card);
    card.querySelector('.good').onclick = () => { state[id] = {status:'good'}; save(); apply(card); refresh(); };
    card.querySelector('.wrong').onclick = () => { state[id] = Object.assign({}, state[id]||{}, {status:'wrong'}); save(); apply(card); card.querySelector('.fix').focus(); refresh(); };
    card.querySelector('.fix').oninput = e => { state[id] = Object.assign({}, state[id]||{}, {status:'wrong', fix:e.target.value}); save(); };
    const us = card.querySelector('.usesugg');
    if (us) us.onclick = () => { const fix = card.querySelector('.fix'); state[id] = {status:'wrong', fix:us.dataset.sugg}; save(); apply(card); fix.value = us.dataset.sugg; refresh(); };
  });
  let filter = 'all';
  function refresh() {
    document.querySelectorAll('.card').forEach(card => {
      const conf = parseFloat(card.dataset.conf), pok = card.dataset.playerok === 'true';
      const st = (state[card.dataset.id]||{}).status;
      let vis = true;
      if (filter === 'review') vis = (conf < 0.7 || !pok);
      if (filter === 'wrong') vis = (st === 'wrong');
      card.style.display = vis ? '' : 'none';
    });
    const wrong = Object.values(state).filter(s => s.status==='wrong').length;
    document.getElementById('count').textContent = wrong + ' marked wrong';
  }
  document.querySelectorAll('.bar [data-filter]').forEach(b => b.onclick = () => {
    document.querySelectorAll('.bar [data-filter]').forEach(x=>x.classList.remove('active'));
    b.classList.add('active'); filter = b.dataset.filter; refresh();
  });
  document.getElementById('copy').onclick = () => {
    const out = [];
    document.querySelectorAll('.card').forEach(card => {
      const id = card.dataset.id, s = state[id]||{};
      if (s.status === 'wrong') {
        const cur = card.querySelector('.title').textContent.trim();
        out.push(id + ' | WAS: ' + cur + ' | FIX: ' + ((s.fix||'').trim() || '(needs correct title)'));
      }
    });
    const text = out.length ? ('CORRECTIONS (' + out.length + '):\n' + out.join('\n')) : 'No cards marked wrong.';
    navigator.clipboard.writeText(text).then(() => {
      const b=document.getElementById('copy'); b.textContent='Copied!'; setTimeout(()=>b.textContent='Copy corrections',1500);
    });
  };
  refresh();
"""

header = (
    '<header><h1>JC&sup2; Cards — Listing QC Review</h1>'
    + '<div class="stats"><b>' + str(total) + '</b> cards posted (Scans 22-39) · <b>'
    + str(low) + '</b> need a look · list value <b>$' + ("%0.2f" % total_val)
    + '</b> · sorted least-confident first</div>'
    + '<div class="bar">'
    + '<button data-filter="all" class="active">All (' + str(total) + ')</button>'
    + '<button data-filter="review">Needs review (' + str(low) + ')</button>'
    + '<button data-filter="wrong">Marked wrong</button>'
    + '<span class="spacer"></span><span id="count"></span>'
    + '<button id="copy">Copy corrections</button></div></header>'
)

page = (
    '<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">'
    '<meta name="viewport" content="width=device-width, initial-scale=1">'
    '<title>JC2 Cards — Listing QC Review</title><style>' + CSS + "</style></head><body>"
    + header
    + '<div class="grid">' + "".join(cards_html) + "</div>"
    + '<footer>Review state saves in your browser. Mark the wrong ones, type the correction, '
      'hit "Copy corrections," and paste the block back to CC.</footer>'
    + "<script>" + JS + "</script></body></html>"
)

outp = REPO / "docs/review.html"
outp.write_text(page)
print("wrote " + str(outp) + " — " + str(total) + " cards, " + str(low) + " flagged for review")
