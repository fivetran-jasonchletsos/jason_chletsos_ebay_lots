"""build_review_page.py — generate docs/review.html, a QC page for posted cards.

Reads:
  output/posted_manifest_22_39.json   (image, item_id, title, price, batch, player)
  output/_verify_results.json         (item_id -> confidence, player_ok, suggested_title, issue)

Static page (GitHub Pages). JC reviews every posted card against its crop,
lowest-confidence first. Click any card for a full detail view (large image +
notes). Filter by player, players sorted by card count. Mark the wrong ones,
export corrections to paste back. Motivated by a Charles-Woodson-listed-as-
Davante-Adams mis-ID.
"""
import json, html
from collections import Counter
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
        "player": c.get("player", "(unknown)"),
        "conf": float(v.get("confidence", 0.5)),
        "player_ok": bool(v.get("player_ok", True)),
        "suggested": v.get("suggested_title", "") or "",
        "issue": v.get("issue", "") or "",
    })

rows.sort(key=lambda r: (r["player_ok"], r["conf"]))
low = sum(1 for r in rows if r["conf"] < 0.7 or not r["player_ok"])
total = len(rows)
total_val = sum(r["price"] for r in rows)
counts = Counter(r["player"] for r in rows)


def conf_class(r):
    if not r["player_ok"] or r["conf"] < 0.4:
        return "bad"
    if r["conf"] < 0.7:
        return "warn"
    return "ok"


def esc(s, q=False):
    return html.escape(str(s), quote=q)


cards_html = []
for r in rows:
    cc = conf_class(r)
    pct = int(round(r["conf"] * 100))
    flag = " · PLAYER?" if not r["player_ok"] else ""
    cards_html.append(
        '<div class="card ' + cc + '" data-id="' + r["item_id"]
        + '" data-conf="' + ("%.2f" % r["conf"]) + '" data-playerok="' + str(r["player_ok"]).lower()
        + '" data-player="' + esc(r["player"], True) + '"'
        + ' data-title="' + esc(r["title"], True) + '"'
        + ' data-price="' + ("%.2f" % r["price"]) + '"'
        + ' data-issue="' + esc(r["issue"], True) + '"'
        + ' data-sugg="' + esc(r["suggested"], True) + '"'
        + ' data-pct="' + str(pct) + '">'
        + '<img loading="lazy" src="review_imgs/' + r["item_id"] + '.jpg" alt="">'
        + '<div class="meta">'
        + '<div class="conf ' + cc + '">' + str(pct) + "%" + flag + "</div>"
        + '<div class="title">' + esc(r["title"]) + "</div>"
        + '<div class="sub">$' + ("%.2f" % r["price"]) + " · " + esc(r["player"]) + "</div>"
        + '<div class="actions"><button class="good">Looks good</button>'
          '<button class="wrong">Wrong</button></div>'
        + '<textarea class="fix" placeholder="Correct title (or note)" rows="2"></textarea>'
        + "</div></div>"
    )

# player filter chips, sorted by count desc then name
chips = ['<button class="chip active" data-player="__all">All <b>' + str(total) + "</b></button>"]
for name, n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])):
    chips.append('<button class="chip" data-player="' + esc(name, True) + '">'
                 + esc(name) + " <b>" + str(n) + "</b></button>")

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
  .bar > button { background:var(--surface2); color:var(--text); border:1px solid var(--border); border-radius:7px; padding:6px 12px; cursor:pointer; font-size:13px; }
  .bar > button.active { border-color:var(--accent); color:var(--accent); }
  .bar .spacer { flex:1; }
  #copy { background:var(--accent); color:#fff; border:none; font-weight:600; }
  #count { color:var(--muted); font-size:13px; }
  .players { display:flex; gap:6px; flex-wrap:wrap; padding:10px 20px 2px; background:var(--surface); border-bottom:1px solid var(--border); }
  .chip { background:var(--surface2); color:var(--text); border:1px solid var(--border); border-radius:14px; padding:3px 11px; cursor:pointer; font-size:12.5px; }
  .chip b { color:var(--accent); margin-left:3px; }
  .chip.active { background:var(--accent); border-color:var(--accent); color:#fff; }
  .chip.active b { color:#fff; }
  .grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(280px,1fr)); gap:14px; padding:18px 20px; }
  .card { background:var(--surface); border:1px solid var(--border); border-radius:11px; overflow:hidden; display:flex; flex-direction:column; }
  .card.bad { border-color:var(--bad); }
  .card.warn { border-color:var(--warn); }
  .card img { width:100%; height:240px; object-fit:contain; background:#000; cursor:zoom-in; }
  .meta { padding:10px 12px; display:flex; flex-direction:column; gap:6px; }
  .conf { font-weight:700; font-size:13px; width:fit-content; padding:2px 8px; border-radius:6px; }
  .conf.ok { background:rgba(46,204,113,.15); color:var(--ok); }
  .conf.warn { background:rgba(241,196,15,.15); color:var(--warn); }
  .conf.bad { background:rgba(231,76,60,.18); color:var(--bad); }
  .title { font-size:13.5px; font-weight:600; }
  .sub { font-size:12px; color:var(--muted); }
  .actions { display:flex; gap:6px; }
  .actions button { flex:1; border:1px solid var(--border); background:var(--surface2); color:var(--text); border-radius:6px; padding:5px; cursor:pointer; font-size:12.5px; }
  .card.mark-good .good { background:var(--ok); color:#04210f; border-color:var(--ok); }
  .card.mark-wrong .wrong { background:var(--bad); color:#fff; border-color:var(--bad); }
  .fix { display:none; width:100%; background:var(--surface2); color:var(--text); border:1px solid var(--border); border-radius:6px; padding:6px; font:13px inherit; resize:vertical; }
  .card.mark-wrong .fix { display:block; }
  footer { padding:24px 20px 60px; color:var(--muted); font-size:12px; text-align:center; }
  /* detail modal */
  #modal { position:fixed; inset:0; z-index:20; background:rgba(0,0,0,.82); display:none; align-items:center; justify-content:center; padding:24px; }
  #modal.open { display:flex; }
  .sheet { background:var(--surface); border:1px solid var(--border); border-radius:14px; max-width:920px; width:100%; max-height:92vh; overflow:auto; display:grid; grid-template-columns:minmax(0,1.1fr) minmax(0,1fr); }
  .sheet img { width:100%; height:100%; max-height:92vh; object-fit:contain; background:#000; border-radius:14px 0 0 14px; }
  .sheet .info { padding:20px 22px; display:flex; flex-direction:column; gap:12px; }
  .sheet h2 { font-size:18px; margin:0; }
  .kv { font-size:13px; color:var(--muted); }
  .kv b { color:var(--text); }
  .sheet .note { background:var(--surface2); border:1px solid var(--border); border-radius:8px; padding:10px 12px; font-size:13px; }
  .sheet .note .lbl { color:var(--muted); font-size:11px; text-transform:uppercase; letter-spacing:.04em; margin-bottom:3px; }
  .sheet a { color:var(--accent); }
  .sheet .mactions { display:flex; gap:8px; margin-top:4px; }
  .sheet .mactions button { flex:1; border:1px solid var(--border); background:var(--surface2); color:var(--text); border-radius:7px; padding:8px; cursor:pointer; font-size:13.5px; }
  .sheet .mactions .mgood.on { background:var(--ok); color:#04210f; border-color:var(--ok); }
  .sheet .mactions .mwrong.on { background:var(--bad); color:#fff; border-color:var(--bad); }
  .sheet textarea { width:100%; background:var(--surface2); color:var(--text); border:1px solid var(--border); border-radius:7px; padding:8px; font:13.5px inherit; resize:vertical; }
  .close { position:absolute; top:16px; right:20px; font-size:28px; color:#fff; cursor:pointer; background:none; border:none; }
  @media (max-width:680px){ .sheet{ grid-template-columns:1fr; } .sheet img{ max-height:50vh; border-radius:14px 14px 0 0; } }
"""

JS = r"""
  const LS = 'jc2_review_22_39';
  let state = JSON.parse(localStorage.getItem(LS) || '{}');
  function save(){ localStorage.setItem(LS, JSON.stringify(state)); }
  function apply(card){
    const id = card.dataset.id, s = state[id] || {};
    card.classList.toggle('mark-good', s.status === 'good');
    card.classList.toggle('mark-wrong', s.status === 'wrong');
    const fix = card.querySelector('.fix');
    if (s.fix != null && fix.value !== s.fix) fix.value = s.fix;
  }
  function setStatus(id, status){ state[id] = Object.assign({}, state[id]||{}, {status}); save(); }
  document.querySelectorAll('.card').forEach(card => {
    const id = card.dataset.id;
    apply(card);
    card.querySelector('.good').onclick = e => { e.stopPropagation(); setStatus(id,'good'); apply(card); refresh(); };
    card.querySelector('.wrong').onclick = e => { e.stopPropagation(); setStatus(id,'wrong'); apply(card); card.querySelector('.fix').focus(); refresh(); };
    card.querySelector('.fix').oninput = e => { state[id] = Object.assign({}, state[id]||{}, {status:'wrong', fix:e.target.value}); save(); };
    card.querySelector('img').onclick = () => openModal(card);
  });

  // ---- detail modal ----
  const modal = document.getElementById('modal');
  let activeCard = null;
  function openModal(card){
    activeCard = card;
    const d = card.dataset;
    modal.querySelector('.mimg').src = 'review_imgs/' + d.id + '.jpg';
    modal.querySelector('.mtitle').textContent = d.title;
    modal.querySelector('.mmeta').innerHTML =
      '$' + d.price + ' &middot; <b>' + d.player + '</b> &middot; confidence <b>' + d.pct + '%</b>'
      + (d.playerok === 'false' ? ' &middot; <span style="color:var(--bad)">PLAYER MISMATCH?</span>' : '');
    modal.querySelector('.mlink').href = 'https://www.ebay.com/itm/' + d.id;
    modal.querySelector('.mlink').textContent = 'View on eBay (' + d.id + ')';
    const noteBox = modal.querySelector('.mnote');
    noteBox.style.display = d.issue ? '' : 'none';
    modal.querySelector('.mnotetext').textContent = d.issue || '';
    const sg = modal.querySelector('.msugg');
    if (d.sugg) { sg.style.display=''; sg.querySelector('.msuggbtn').textContent = d.sugg; }
    else sg.style.display='none';
    const s = state[d.id] || {};
    modal.querySelector('.mgood').classList.toggle('on', s.status==='good');
    modal.querySelector('.mwrong').classList.toggle('on', s.status==='wrong');
    const ta = modal.querySelector('.mfix'); ta.value = s.fix || '';
    modal.classList.add('open');
  }
  function closeModal(){ modal.classList.remove('open'); activeCard=null; }
  modal.querySelector('.close').onclick = closeModal;
  modal.onclick = e => { if (e.target === modal) closeModal(); };
  document.addEventListener('keydown', e => { if (e.key==='Escape') closeModal(); });
  modal.querySelector('.mgood').onclick = () => { if(!activeCard) return; const id=activeCard.dataset.id; setStatus(id,'good'); apply(activeCard); openModal(activeCard); refresh(); };
  modal.querySelector('.mwrong').onclick = () => { if(!activeCard) return; const id=activeCard.dataset.id; setStatus(id,'wrong'); apply(activeCard); openModal(activeCard); refresh(); };
  modal.querySelector('.mfix').oninput = e => { if(!activeCard) return; const id=activeCard.dataset.id; state[id]=Object.assign({},state[id]||{},{status:'wrong',fix:e.target.value}); save(); apply(activeCard); modal.querySelector('.mwrong').classList.add('on'); refresh(); };
  modal.querySelector('.msuggbtn').onclick = () => { if(!activeCard) return; const id=activeCard.dataset.id; const v=activeCard.dataset.sugg; state[id]={status:'wrong',fix:v}; save(); apply(activeCard); modal.querySelector('.mfix').value=v; modal.querySelector('.mwrong').classList.add('on'); refresh(); };

  // ---- filters ----
  let statusFilter = 'all', playerFilter = '__all';
  function refresh(){
    document.querySelectorAll('.card').forEach(card => {
      const conf = parseFloat(card.dataset.conf), pok = card.dataset.playerok === 'true';
      const st = (state[card.dataset.id]||{}).status;
      let vis = true;
      if (statusFilter === 'review') vis = vis && (conf < 0.7 || !pok);
      if (statusFilter === 'wrong')  vis = vis && (st === 'wrong');
      if (playerFilter !== '__all')  vis = vis && (card.dataset.player === playerFilter);
      card.style.display = vis ? '' : 'none';
    });
    const wrong = Object.values(state).filter(s => s.status==='wrong').length;
    document.getElementById('count').textContent = wrong + ' marked wrong';
  }
  document.querySelectorAll('.bar [data-filter]').forEach(b => b.onclick = () => {
    document.querySelectorAll('.bar [data-filter]').forEach(x=>x.classList.remove('active'));
    b.classList.add('active'); statusFilter = b.dataset.filter; refresh();
  });
  document.querySelectorAll('.players .chip').forEach(c => c.onclick = () => {
    document.querySelectorAll('.players .chip').forEach(x=>x.classList.remove('active'));
    c.classList.add('active'); playerFilter = c.dataset.player; refresh();
  });
  document.getElementById('copy').onclick = () => {
    const out = [];
    document.querySelectorAll('.card').forEach(card => {
      const id = card.dataset.id, s = state[id]||{};
      if (s.status === 'wrong')
        out.push(id + ' | WAS: ' + card.dataset.title + ' | FIX: ' + ((s.fix||'').trim() || '(needs correct title)'));
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
    + '<div class="stats"><b>' + str(total) + '</b> cards posted (Scans 22-39) &middot; <b>'
    + str(low) + '</b> need a look &middot; list value <b>$' + ("%0.2f" % total_val)
    + '</b> &middot; click any card for detail</div>'
    + '<div class="bar">'
    + '<button data-filter="all" class="active">All (' + str(total) + ')</button>'
    + '<button data-filter="review">Needs review (' + str(low) + ')</button>'
    + '<button data-filter="wrong">Marked wrong</button>'
    + '<span class="spacer"></span><span id="count"></span>'
    + '<button id="copy">Copy corrections</button></div></header>'
    + '<div class="players">' + "".join(chips) + "</div>"
)

modal_html = (
    '<div id="modal"><button class="close">&times;</button>'
    '<div class="sheet"><img class="mimg" src="" alt="">'
    '<div class="info"><h2 class="mtitle"></h2><div class="kv mmeta"></div>'
    '<div class="kv"><a class="mlink" target="_blank" rel="noopener"></a></div>'
    '<div class="note mnote"><div class="lbl">Reviewer note</div><div class="mnotetext"></div></div>'
    '<div class="note msugg"><div class="lbl">Suggested fix (click to use)</div>'
    '<button class="msuggbtn" style="background:none;border:1px dashed var(--border);color:var(--accent);border-radius:6px;padding:4px 8px;cursor:pointer;text-align:left"></button></div>'
    '<div class="mactions"><button class="mgood">Looks good</button><button class="mwrong">Wrong</button></div>'
    '<textarea class="mfix" rows="3" placeholder="Correct title (or note)"></textarea>'
    '</div></div></div>'
)

page = (
    '<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">'
    '<meta name="viewport" content="width=device-width, initial-scale=1">'
    '<title>JC2 Cards — Listing QC Review</title><style>' + CSS + "</style></head><body>"
    + header
    + '<div class="grid">' + "".join(cards_html) + "</div>"
    + modal_html
    + '<footer>Review saves in your browser. Click a card to inspect it, mark the wrong ones, '
      'then "Copy corrections" and paste the block back to CC.</footer>'
    + "<script>" + JS + "</script></body></html>"
)

outp = REPO / "docs/review.html"
outp.write_text(page)
print("wrote " + str(outp) + " — " + str(total) + " cards, "
      + str(len(counts)) + " players, " + str(low) + " flagged")
