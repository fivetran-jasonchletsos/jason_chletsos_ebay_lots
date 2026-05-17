"""
ai_assistant_agent.py — Renders docs/assistant.html: a chat UI for asking
plain-English questions about the user's trading-card inventory and the
broader card market.

This is a UI-only page. The Send button POSTs to a Lambda route at
/ebay/ai-chat that is not yet provisioned — the page degrades gracefully
to a friendly "AI backend coming soon" message when the endpoint 404s.

The page mirrors the chat-panel pattern used in the sheetz / epic-clarity /
meridian Snowflake demos:

  • Header with eyebrow + serif title
  • KPI strip (live counts pulled from this repo's JSON outputs)
  • Suggested-questions chip row (pre-fills the input on click)
  • Conversation thread with user / assistant bubbles and timestamps
  • Sticky "Ask anything" textarea + Send button at the bottom
  • Violet "AI" badge on every assistant bubble

CLI:
    python3 ai_assistant_agent.py
        → renders docs/assistant.html

No --apply flag, no live LLM call, no Anthropic SDK dependency.
"""
from __future__ import annotations

import html as _html
import json
from datetime import datetime, timezone
from pathlib import Path

import promote

REPO_ROOT  = Path(__file__).parent
OUTPUT_DIR = REPO_ROOT / "output"
DOCS_DIR   = REPO_ROOT / "docs"

# Lambda endpoint the page will POST to once a /ebay/ai-chat route is wired.
# Until then the request 404s and the UI shows a friendly fallback message.
AI_CHAT_ENDPOINT = "https://jw0hur2091.execute-api.us-east-1.amazonaws.com/ebay/ai-chat"

SUGGESTED_QUESTIONS = [
    "What's the market price for a 2024 Topps Chrome Cam Ward rookie PSA 10?",
    "Which of my listings should I reprice today?",
    "Find me Pikachu cards under $10",
    "What Pokemon sets are dropping next month?",
    "How do I value a 1994 Classic Pro Line autograph?",
    "What's my best-performing listing this month?",
]


# --------------------------------------------------------------------------- #
# Data loading                                                                #
# --------------------------------------------------------------------------- #

def _safe_load_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def gather_kpis() -> dict:
    """Pull live counts from the existing JSON outputs.

    Falls back to 0 / '—' if any file is missing so this never crashes.
    """
    kpis = {
        "listings_total": 0,
        "sold_recent":    0,
        "categories":     0,
        "pikachu_deals":  0,
    }

    snap = _safe_load_json(OUTPUT_DIR / "listings_snapshot.json")
    if isinstance(snap, list):
        kpis["listings_total"] = len(snap)
    elif isinstance(snap, dict):
        kpis["listings_total"] = int(snap.get("count") or snap.get("listings_total") or 0)

    sold = _safe_load_json(REPO_ROOT / "sold_history.json")
    if isinstance(sold, list):
        kpis["sold_recent"] = len(sold)
    elif isinstance(sold, dict):
        # try common shapes
        for k in ("items", "sold", "history"):
            v = sold.get(k)
            if isinstance(v, list):
                kpis["sold_recent"] = len(v)
                break

    hub = _safe_load_json(OUTPUT_DIR / "seller_hub_plan.json")
    if isinstance(hub, dict):
        cats = hub.get("categories")
        if isinstance(cats, list):
            kpis["categories"] = len(cats)

    pika = _safe_load_json(OUTPUT_DIR / "pokemon_pikachu_plan.json")
    if isinstance(pika, dict):
        buckets = pika.get("buckets")
        if isinstance(buckets, dict):
            buckets = list(buckets.values())
        if isinstance(buckets, list):
            kpis["pikachu_deals"] = sum(int(b.get("n_deals") or 0) for b in buckets)

    return kpis


# --------------------------------------------------------------------------- #
# HTML rendering                                                              #
# --------------------------------------------------------------------------- #

def _esc(s) -> str:
    return _html.escape("" if s is None else str(s), quote=True)


def render_body(kpis: dict) -> str:
    # KPI tiles — live numbers from JSON outputs.
    kpi_tiles = [
        ("Active listings", f"{kpis['listings_total']:,}",  "from listings_snapshot.json"),
        ("Sold (recent)",   f"{kpis['sold_recent']:,}",     "from sold_history.json"),
        ("Categories",      f"{kpis['categories']:,}",      "from seller_hub_plan.json"),
        ("Pikachu deals",   f"{kpis['pikachu_deals']:,}",   "from pokemon_pikachu_plan.json"),
    ]
    kpi_html = "".join(
        f"""
        <div class="ai-kpi">
          <div class="ai-kpi-num">{_esc(num)}</div>
          <div class="ai-kpi-label">{_esc(label)}</div>
          <div class="ai-kpi-src">{_esc(src)}</div>
        </div>"""
        for label, num, src in kpi_tiles
    )

    # Strip-style summary line ("172 listings · 63 sold · 8 categories")
    strip_line = (
        f"<strong>{kpis['listings_total']:,}</strong> listings &middot; "
        f"<strong>{kpis['sold_recent']:,}</strong> sold last 90 days &middot; "
        f"<strong>{kpis['categories']:,}</strong> categories &middot; "
        f"<strong>{kpis['pikachu_deals']:,}</strong> Pikachu deals scanned"
    )

    chips = "".join(
        f'<button type="button" class="ai-chip" data-q="{_esc(q)}">{_esc(q)}</button>'
        for q in SUGGESTED_QUESTIONS
    )

    # JSON payload of suggested questions for JS access (defensive — also
    # readable from the DOM via data-q).
    suggestions_json = json.dumps(SUGGESTED_QUESTIONS)

    endpoint_js = json.dumps(AI_CHAT_ENDPOINT)
    kpis_json = json.dumps(kpis)

    body = f"""
    <div class="section-head ai-head">
      <div>
        <div class="eyebrow"><span class="ai-badge">AI</span> Card Assistant &middot; ask anything</div>
        <h1 class="section-title">Card <span class="accent">Assistant</span></h1>
        <div class="section-sub">
          Plain-English questions over your live inventory, sold history, and the broader
          card market. Type a question or tap a suggestion below &mdash; answers will route
          through Claude once the Lambda <code>/ebay/ai-chat</code> route is wired.
        </div>
      </div>
    </div>

    <div class="ai-strip">{strip_line}</div>

    <div class="ai-kpi-row">
      {kpi_html}
    </div>

    <div class="ai-chips-wrap">
      <div class="ai-chips-label">Try a suggested question</div>
      <div class="ai-chips">
        {chips}
      </div>
    </div>

    <div class="ai-thread" id="ai-thread" aria-live="polite">
      <div class="ai-thread-empty" id="ai-empty">
        <div class="ai-empty-emoji">&#129518;</div>
        <div class="ai-empty-title">No questions yet</div>
        <div class="ai-empty-sub">
          Ask about market prices, your repricing queue, deal alerts, or anything else
          card-related. Suggested questions above will get you started.
        </div>
      </div>
    </div>

    <form id="ai-form" class="ai-input-bar" autocomplete="off">
      <textarea
        id="ai-input"
        class="ai-input"
        rows="1"
        placeholder="Ask anything about cards, your listings, or the market…"></textarea>
      <button type="submit" id="ai-send" class="ai-send">
        <span class="ai-send-label">Send</span>
        <span class="ai-send-arrow" aria-hidden="true">&#10148;</span>
      </button>
    </form>

    <div class="ai-foot">
      <span class="ai-badge">AI</span>
      Responses route to a Claude-backed Lambda. Until <code>ANTHROPIC_API_KEY</code>
      is configured on the <code>/ebay/ai-chat</code> route this page will surface a
      friendly &ldquo;coming soon&rdquo; message.
    </div>

    <script>
      (function() {{
        const ENDPOINT     = {endpoint_js};
        const SUGGESTIONS  = {suggestions_json};
        const KPIS         = {kpis_json};
        const thread       = document.getElementById('ai-thread');
        const empty        = document.getElementById('ai-empty');
        const form         = document.getElementById('ai-form');
        const input        = document.getElementById('ai-input');
        const sendBtn      = document.getElementById('ai-send');

        function fmtTime(d) {{
          const h = d.getHours(), m = d.getMinutes();
          const ap = h >= 12 ? 'PM' : 'AM';
          const hh = ((h + 11) % 12) + 1;
          return hh + ':' + (m < 10 ? '0' + m : m) + ' ' + ap;
        }}

        function escapeHtml(s) {{
          return (s == null ? '' : String(s))
            .replace(/&/g, '&amp;').replace(/</g, '&lt;')
            .replace(/>/g, '&gt;').replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
        }}

        function addBubble(role, text, opts) {{
          opts = opts || {{}};
          if (empty && empty.parentNode) empty.parentNode.removeChild(empty);
          const wrap = document.createElement('div');
          wrap.className = 'ai-row ' + (role === 'user' ? 'ai-row-user' : 'ai-row-asst');
          const bubble = document.createElement('div');
          bubble.className = 'ai-bubble ' + (role === 'user' ? 'ai-bubble-user' : 'ai-bubble-asst');
          if (opts.pending) bubble.classList.add('ai-bubble-pending');
          if (opts.error)   bubble.classList.add('ai-bubble-error');
          if (role !== 'user') {{
            const tag = document.createElement('span');
            tag.className = 'ai-badge ai-bubble-badge';
            tag.textContent = 'AI';
            bubble.appendChild(tag);
          }}
          const body = document.createElement('div');
          body.className = 'ai-bubble-body';
          body.innerHTML = escapeHtml(text).replace(/\\n/g, '<br>');
          bubble.appendChild(body);
          const ts = document.createElement('div');
          ts.className = 'ai-ts';
          ts.textContent = fmtTime(new Date());
          bubble.appendChild(ts);
          wrap.appendChild(bubble);
          thread.appendChild(wrap);
          thread.scrollTop = thread.scrollHeight;
          return bubble;
        }}

        function setPending(bubble, text) {{
          bubble.classList.remove('ai-bubble-pending');
          const body = bubble.querySelector('.ai-bubble-body');
          if (body) body.innerHTML = escapeHtml(text).replace(/\\n/g, '<br>');
        }}

        function setError(bubble, text) {{
          bubble.classList.remove('ai-bubble-pending');
          bubble.classList.add('ai-bubble-error');
          const body = bubble.querySelector('.ai-bubble-body');
          if (body) body.innerHTML = escapeHtml(text).replace(/\\n/g, '<br>');
        }}

        async function ask(question) {{
          const q = (question || '').trim();
          if (!q) return;
          addBubble('user', q);
          input.value = '';
          autosize();
          sendBtn.disabled = true;
          const pending = addBubble('assistant', 'Thinking…', {{ pending: true }});
          try {{
            const resp = await fetch(ENDPOINT, {{
              method: 'POST',
              headers: {{ 'Content-Type': 'application/json' }},
              body: JSON.stringify({{
                question: q,
                context: {{ kpis: KPIS, source: 'docs/assistant.html' }}
              }})
            }});
            if (!resp.ok) {{
              if (resp.status === 404 || resp.status === 403) {{
                setError(pending,
                  'AI backend coming soon — add ANTHROPIC_API_KEY to the Lambda ' +
                  'and wire the /ebay/ai-chat route, and this will start answering ' +
                  'with live Claude responses grounded in your listings, sold ' +
                  'history, and pricing comps.');
              }} else {{
                setError(pending, 'Backend error (' + resp.status + '). Try again shortly.');
              }}
              return;
            }}
            const data = await resp.json().catch(function() {{ return null; }});
            const answer = (data && (data.answer || data.message || data.text)) ||
                           'No answer returned by the assistant.';
            setPending(pending, answer);
          }} catch (err) {{
            setError(pending,
              'AI backend coming soon — could not reach ' + ENDPOINT + '. ' +
              'Once the /ebay/ai-chat Lambda route is live with ANTHROPIC_API_KEY ' +
              'this question will route to Claude.');
          }} finally {{
            sendBtn.disabled = false;
            input.focus();
          }}
        }}

        function autosize() {{
          input.style.height = 'auto';
          input.style.height = Math.min(input.scrollHeight, 180) + 'px';
        }}

        document.querySelectorAll('.ai-chip').forEach(function(btn) {{
          btn.addEventListener('click', function() {{
            const q = btn.getAttribute('data-q');
            input.value = q;
            autosize();
            input.focus();
          }});
        }});

        input.addEventListener('input', autosize);
        input.addEventListener('keydown', function(e) {{
          if (e.key === 'Enter' && !e.shiftKey) {{
            e.preventDefault();
            ask(input.value);
          }}
        }});

        form.addEventListener('submit', function(e) {{
          e.preventDefault();
          ask(input.value);
        }});
      }})();
    </script>
    """
    return body


_EXTRA_CSS = """
<style>
  .ai-head { margin-bottom: 14px; }
  .ai-badge {
    display: inline-block;
    background: linear-gradient(135deg, #8b5cf6 0%, #6d28d9 100%);
    color: #fff;
    font-family: 'Bebas Neue', sans-serif;
    font-size: 11px;
    letter-spacing: .14em;
    padding: 2px 8px;
    border-radius: 4px;
    vertical-align: middle;
    margin-right: 6px;
    box-shadow: 0 2px 8px rgba(139,92,246,.35);
  }

  .ai-strip {
    background: var(--surface);
    border: 1px solid var(--border);
    border-left: 3px solid #8b5cf6;
    border-radius: var(--r-sm, 6px);
    padding: 10px 14px;
    margin: 8px 0 18px;
    font-size: 13px;
    color: var(--text-muted);
  }
  .ai-strip strong { color: var(--text); font-family: 'Bebas Neue', sans-serif; font-size: 17px; letter-spacing: .03em; }

  .ai-kpi-row {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
    gap: 12px;
    margin: 0 0 22px;
  }
  .ai-kpi {
    background: var(--surface);
    border: 1px solid var(--border);
    border-top: 3px solid #8b5cf6;
    border-radius: var(--r-md, 8px);
    padding: 14px 16px;
  }
  .ai-kpi-num { font-family: 'Bebas Neue', sans-serif; font-size: 34px; color: var(--text); line-height: 1; }
  .ai-kpi-label { font-size: 11px; text-transform: uppercase; letter-spacing: .12em; color: var(--text-muted); margin-top: 6px; }
  .ai-kpi-src { font-size: 10px; color: var(--text-muted); opacity: .6; margin-top: 4px; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }

  .ai-chips-wrap { margin: 0 0 18px; }
  .ai-chips-label {
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: .14em;
    color: var(--text-muted);
    margin-bottom: 8px;
  }
  .ai-chips { display: flex; flex-wrap: wrap; gap: 8px; }
  .ai-chip {
    background: var(--surface);
    border: 1px solid var(--border);
    color: var(--text);
    padding: 7px 12px;
    border-radius: 999px;
    font-size: 12px;
    cursor: pointer;
    transition: all .15s ease;
    line-height: 1.2;
  }
  .ai-chip:hover {
    border-color: #8b5cf6;
    color: #c4b5fd;
    background: rgba(139,92,246,.08);
    transform: translateY(-1px);
  }

  .ai-thread {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--r-md, 8px);
    padding: 18px;
    min-height: 280px;
    max-height: 60vh;
    overflow-y: auto;
    margin-bottom: 16px;
    display: flex;
    flex-direction: column;
    gap: 12px;
    scroll-behavior: smooth;
  }
  .ai-thread-empty {
    margin: auto;
    text-align: center;
    color: var(--text-muted);
    padding: 28px 12px;
  }
  .ai-empty-emoji { font-size: 36px; }
  .ai-empty-title { font-family: 'Bebas Neue', sans-serif; font-size: 22px; color: var(--text); margin-top: 8px; letter-spacing: .04em; }
  .ai-empty-sub { font-size: 13px; margin-top: 6px; max-width: 420px; margin-left: auto; margin-right: auto; line-height: 1.5; }

  .ai-row { display: flex; }
  .ai-row-user { justify-content: flex-end; }
  .ai-row-asst { justify-content: flex-start; }

  .ai-bubble {
    max-width: 78%;
    padding: 11px 14px 8px;
    border-radius: 14px;
    font-size: 14px;
    line-height: 1.5;
    position: relative;
    word-wrap: break-word;
  }
  .ai-bubble-user {
    background: linear-gradient(135deg, #0ea5e9 0%, #2563eb 100%);
    color: #fff;
    border-bottom-right-radius: 4px;
  }
  .ai-bubble-asst {
    background: var(--surface-2, #1a1a1a);
    border: 1px solid var(--border);
    color: var(--text);
    border-bottom-left-radius: 4px;
  }
  .ai-bubble-pending { opacity: .65; }
  .ai-bubble-pending .ai-bubble-body { animation: ai-pulse 1.4s ease-in-out infinite; }
  @keyframes ai-pulse { 0%,100% { opacity: .55; } 50% { opacity: 1; } }
  .ai-bubble-error {
    background: rgba(244, 63, 94, .08);
    border-color: rgba(244, 63, 94, .35);
    color: #fecaca;
  }
  .ai-bubble-badge { margin-bottom: 4px; display: inline-block; }
  .ai-bubble-body { white-space: pre-wrap; }
  .ai-ts {
    font-size: 10px;
    color: rgba(255,255,255,.55);
    margin-top: 4px;
    text-align: right;
    letter-spacing: .04em;
  }
  .ai-bubble-asst .ai-ts { color: var(--text-muted); }

  .ai-input-bar {
    position: sticky;
    bottom: 0;
    z-index: 5;
    background: var(--bg, #0a0a0a);
    border-top: 1px solid var(--border);
    padding: 12px 0 10px;
    display: flex;
    gap: 10px;
    align-items: flex-end;
    margin: 8px -4px 4px;
  }
  .ai-input {
    flex: 1;
    resize: none;
    background: var(--surface);
    border: 1px solid var(--border);
    color: var(--text);
    border-radius: 12px;
    padding: 12px 14px;
    font-size: 14px;
    line-height: 1.45;
    font-family: inherit;
    max-height: 180px;
    transition: border-color .15s ease, box-shadow .15s ease;
  }
  .ai-input:focus {
    outline: none;
    border-color: #8b5cf6;
    box-shadow: 0 0 0 3px rgba(139,92,246,.18);
  }
  .ai-send {
    background: linear-gradient(135deg, #8b5cf6 0%, #6d28d9 100%);
    color: #fff;
    border: none;
    border-radius: 12px;
    padding: 12px 18px;
    font-family: 'Bebas Neue', sans-serif;
    font-size: 15px;
    letter-spacing: .08em;
    cursor: pointer;
    display: inline-flex;
    align-items: center;
    gap: 8px;
    transition: transform .12s ease, box-shadow .12s ease, opacity .12s ease;
    box-shadow: 0 4px 14px rgba(139,92,246,.35);
  }
  .ai-send:hover { transform: translateY(-1px); box-shadow: 0 6px 18px rgba(139,92,246,.5); }
  .ai-send:disabled { opacity: .5; cursor: not-allowed; transform: none; box-shadow: none; }
  .ai-send-arrow { font-size: 14px; }

  .ai-foot {
    font-size: 11px;
    color: var(--text-muted);
    margin: 6px 0 30px;
    line-height: 1.55;
  }
  .ai-foot code {
    background: var(--surface);
    border: 1px solid var(--border);
    padding: 1px 5px;
    border-radius: 3px;
    font-size: 10.5px;
  }

  @media (max-width: 640px) {
    .ai-bubble { max-width: 88%; }
    .ai-thread { padding: 12px; max-height: 55vh; }
    .ai-kpi-num { font-size: 28px; }
  }
</style>
"""


def render(out_path: Path | None = None) -> Path:
    kpis = gather_kpis()
    body = render_body(kpis)
    html_doc = promote.html_shell(
        f"Card Assistant &middot; {promote.SELLER_NAME}",
        body,
        extra_head=_EXTRA_CSS,
        active_page="assistant.html",
    )
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    out = out_path or (DOCS_DIR / "assistant.html")
    out.write_text(html_doc, encoding="utf-8")
    return out


def main() -> int:
    out = render()
    kpis = gather_kpis()
    print(f"Rendered {out}")
    print(
        f"  KPIs: listings={kpis['listings_total']}  "
        f"sold={kpis['sold_recent']}  "
        f"categories={kpis['categories']}  "
        f"pikachu_deals={kpis['pikachu_deals']}"
    )
    print(f"  Endpoint (stubbed): {AI_CHAT_ENDPOINT}")
    print(f"  Generated: {datetime.now(timezone.utc).isoformat()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
