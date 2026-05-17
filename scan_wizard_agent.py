"""
scan_wizard_agent.py — mobile scan-and-list wizard.

JC opens this on his phone, points camera at a card, captures, types/edits
the title, AI cleans it, price suggests, then "Create draft on eBay" pushes
to the existing Lambda create-listing flow.

Single-card focus, big touch targets, sticky step indicator.

Output:
  docs/scan_wizard.html
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import promote

REPO_ROOT = Path(__file__).parent
REPORT    = REPO_ROOT / "docs" / "scan_wizard.html"

LAMBDA_BASE = promote.LAMBDA_BASE


def build_body() -> str:
    return f"""
<main class="wiz-main">
  <div class="wiz-shell">

    <header class="wiz-header">
      <h1 class="wiz-title">Scan &amp; List</h1>
      <p class="wiz-sub">One card. Six taps. Live on eBay.</p>
    </header>

    <!-- STEP 1 -->
    <section class="wiz-step" data-step="1">
      <div class="step-num">Step 1</div>
      <h2 class="step-title">Snap the card</h2>
      <label class="capture-btn" for="cardPhoto">
        <span class="capture-icon">📷</span>
        <span class="capture-label">Take photo or upload</span>
        <span class="capture-hint">Rear camera launches automatically</span>
      </label>
      <input id="cardPhoto" type="file" accept="image/*" capture="environment" hidden>
      <div id="photoPreviewWrap" class="photo-preview" hidden>
        <img id="photoPreview" alt="Captured card">
        <button type="button" class="ghost-btn" id="retakeBtn">Retake</button>
      </div>
    </section>

    <!-- STEP 2 -->
    <section class="wiz-step" data-step="2">
      <div class="step-num">Step 2</div>
      <h2 class="step-title">What's on this card?</h2>
      <textarea id="rawTitle" class="big-input" rows="3"
        placeholder="e.g. 2018 Topps Chrome Shohei Ohtani RC Refractor #150"></textarea>
      <p class="hint">Type what you see — front of card has most of it.</p>
    </section>

    <!-- STEP 3 -->
    <section class="wiz-step" data-step="3">
      <div class="step-num">Step 3</div>
      <h2 class="step-title">AI-polish the title</h2>
      <button type="button" class="primary-btn" id="improveBtn">✨ Improve title</button>
      <div id="aiResult" class="ai-result" hidden>
        <label class="lbl">Suggested title (≤80 chars)</label>
        <input id="cleanTitle" type="text" class="big-input" maxlength="80">
        <div class="char-count"><span id="charCount">0</span>/80</div>
      </div>
    </section>

    <!-- STEP 4 -->
    <section class="wiz-step" data-step="4">
      <div class="step-num">Step 4</div>
      <h2 class="step-title">Suggested price</h2>
      <button type="button" class="primary-btn" id="priceBtn">💰 Look up price</button>
      <div id="priceResult" class="ai-result" hidden>
        <label class="lbl">Asking price (USD)</label>
        <div class="price-row">
          <span class="dollar">$</span>
          <input id="askPrice" type="number" min="0" step="0.01" class="big-input price-input">
        </div>
        <p class="hint" id="priceNote"></p>
      </div>
    </section>

    <!-- STEP 5 -->
    <section class="wiz-step" data-step="5">
      <div class="step-num">Step 5</div>
      <h2 class="step-title">Category</h2>
      <select id="catSelect" class="big-input">
        <option value="261328">Sports Trading Cards · Baseball</option>
        <option value="261329">Sports Trading Cards · Basketball</option>
        <option value="261330">Sports Trading Cards · Football</option>
        <option value="183454">Hockey Cards</option>
        <option value="183050">Pokémon TCG Individual Cards</option>
        <option value="38292">MTG Individual Cards</option>
        <option value="261324">Non-Sport Trading Cards</option>
        <option value="212">Other Trading Cards</option>
      </select>
      <p class="hint" id="catHint">Auto-guessed from title.</p>
    </section>

    <!-- STEP 6 -->
    <section class="wiz-step" data-step="6">
      <div class="step-num">Step 6</div>
      <h2 class="step-title">Send to eBay</h2>
      <button type="button" class="primary-btn big-cta" id="createBtn">🚀 Create draft on eBay</button>
      <div id="createResult" class="ai-result" hidden></div>
    </section>

  </div>

  <!-- STICKY BOTTOM BAR -->
  <div class="step-bar">
    <div class="step-bar-text">Step <span id="curStep">1</span> / 6</div>
    <div class="step-bar-progress"><div class="step-bar-fill" id="stepFill"></div></div>
  </div>
</main>

<style>
  body {{ background: var(--bg); }}
  .wiz-main {{ padding: 16px 14px 120px; max-width: 480px; margin: 0 auto; }}
  .wiz-shell {{ display: flex; flex-direction: column; gap: 18px; }}
  .wiz-header {{ text-align: center; padding: 12px 0 4px; }}
  .wiz-title {{ font-family: 'Bebas Neue', sans-serif; font-size: 38px; letter-spacing: .04em; color: var(--gold); margin: 0; }}
  .wiz-sub {{ color: var(--text-muted); margin: 4px 0 0; font-size: 14px; }}
  .wiz-step {{ background: var(--surface); border: 1px solid var(--border); border-radius: 14px; padding: 18px 16px; }}
  .step-num {{ font-family: 'JetBrains Mono', monospace; font-size: 11px; color: var(--gold-dim); letter-spacing: .12em; text-transform: uppercase; margin-bottom: 6px; }}
  .step-title {{ margin: 0 0 14px; font-size: 20px; color: var(--text); font-weight: 700; }}
  .capture-btn {{ display: flex; flex-direction: column; align-items: center; gap: 6px; padding: 28px 12px; background: var(--surface-2); border: 2px dashed var(--border-mid); border-radius: 12px; cursor: pointer; }}
  .capture-btn:active {{ background: var(--surface-3); border-color: var(--gold); }}
  .capture-icon {{ font-size: 42px; }}
  .capture-label {{ font-size: 17px; color: var(--text); font-weight: 600; }}
  .capture-hint {{ font-size: 12px; color: var(--text-muted); }}
  .photo-preview {{ margin-top: 12px; text-align: center; }}
  .photo-preview img {{ max-width: 100%; max-height: 360px; border-radius: 10px; border: 1px solid var(--border-mid); }}
  .big-input {{ width: 100%; padding: 14px 12px; font-size: 16px; background: var(--surface-2); color: var(--text); border: 1px solid var(--border-mid); border-radius: 10px; font-family: inherit; -webkit-appearance: none; }}
  .big-input:focus {{ outline: none; border-color: var(--gold); }}
  textarea.big-input {{ resize: vertical; min-height: 84px; }}
  .primary-btn {{ width: 100%; padding: 16px; font-size: 17px; font-weight: 700; background: var(--gold); color: #1a1300; border: none; border-radius: 12px; cursor: pointer; min-height: 54px; }}
  .primary-btn:active {{ background: var(--gold-bright); }}
  .primary-btn:disabled {{ opacity: .55; }}
  .big-cta {{ font-size: 19px; padding: 18px; }}
  .ghost-btn {{ margin-top: 10px; padding: 10px 14px; font-size: 14px; background: transparent; color: var(--text-muted); border: 1px solid var(--border-mid); border-radius: 8px; }}
  .ai-result {{ margin-top: 14px; }}
  .lbl {{ display: block; font-size: 12px; color: var(--text-muted); margin-bottom: 6px; text-transform: uppercase; letter-spacing: .08em; }}
  .char-count {{ text-align: right; font-size: 12px; color: var(--text-muted); margin-top: 4px; font-family: 'JetBrains Mono', monospace; }}
  .hint {{ font-size: 12px; color: var(--text-muted); margin: 8px 0 0; }}
  .price-row {{ display: flex; align-items: center; gap: 8px; }}
  .dollar {{ font-size: 24px; color: var(--gold); font-weight: 700; }}
  .price-input {{ flex: 1; font-size: 22px; font-weight: 700; }}
  .step-bar {{ position: fixed; bottom: 0; left: 0; right: 0; background: rgba(10,10,10,.96); backdrop-filter: blur(8px); border-top: 1px solid var(--border-mid); padding: 12px 16px env(safe-area-inset-bottom, 12px); z-index: 50; }}
  .step-bar-text {{ font-family: 'JetBrains Mono', monospace; font-size: 12px; color: var(--text-muted); text-align: center; margin-bottom: 6px; letter-spacing: .08em; }}
  .step-bar-progress {{ height: 4px; background: var(--surface-3); border-radius: 4px; overflow: hidden; }}
  .step-bar-fill {{ height: 100%; background: var(--gold); width: 16%; transition: width .25s ease; }}
  @media (min-width: 600px) {{ .wiz-main {{ padding: 24px; }} }}
</style>

<script>
  const LAMBDA = '{LAMBDA_BASE}';
  const $ = (id) => document.getElementById(id);

  let currentStep = 1;
  let photoDataUrl = null;

  function setStep(n) {{
    currentStep = Math.max(currentStep, n);
    $('curStep').textContent = currentStep;
    $('stepFill').style.width = (currentStep / 6 * 100) + '%';
  }}

  // STEP 1 — capture
  $('cardPhoto').addEventListener('change', (e) => {{
    const file = e.target.files && e.target.files[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = (ev) => {{
      photoDataUrl = ev.target.result;
      $('photoPreview').src = photoDataUrl;
      $('photoPreviewWrap').hidden = false;
      setStep(2);
      $('rawTitle').focus();
    }};
    reader.readAsDataURL(file);
  }});
  $('retakeBtn').addEventListener('click', () => {{
    $('cardPhoto').value = '';
    $('photoPreviewWrap').hidden = true;
    photoDataUrl = null;
  }});

  // STEP 2 — raw text
  $('rawTitle').addEventListener('input', () => {{
    if ($('rawTitle').value.trim().length > 6) setStep(3);
  }});

  // STEP 3 — AI improve
  $('improveBtn').addEventListener('click', async () => {{
    const raw = $('rawTitle').value.trim();
    if (!raw) {{ alert('Type the card details first.'); return; }}
    $('improveBtn').disabled = true;
    $('improveBtn').textContent = 'Working...';
    try {{
      const r = await fetch(LAMBDA + '/ai-chat', {{
        method: 'POST',
        headers: {{ 'Content-Type': 'application/json' }},
        body: JSON.stringify({{
          prompt: 'Format this card description as an eBay-best-practices title under 80 chars. Return only the title text, no quotes, no explanation: ' + raw
        }})
      }});
      const j = await r.json();
      const suggested = (j.text || j.response || j.message || raw).trim().slice(0, 80);
      $('cleanTitle').value = suggested;
      $('charCount').textContent = suggested.length;
      $('aiResult').hidden = false;
      autoGuessCategory(suggested);
      setStep(4);
    }} catch (err) {{
      $('cleanTitle').value = raw.slice(0, 80);
      $('aiResult').hidden = false;
      alert('AI unavailable — using your text as-is.');
    }} finally {{
      $('improveBtn').disabled = false;
      $('improveBtn').textContent = '✨ Improve title';
    }}
  }});
  $('cleanTitle').addEventListener('input', () => {{
    $('charCount').textContent = $('cleanTitle').value.length;
    autoGuessCategory($('cleanTitle').value);
  }});

  // STEP 4 — price lookup
  $('priceBtn').addEventListener('click', async () => {{
    const title = $('cleanTitle').value.trim() || $('rawTitle').value.trim();
    if (!title) {{ alert('Need a title first.'); return; }}
    $('priceBtn').disabled = true;
    $('priceBtn').textContent = 'Looking up...';
    try {{
      const r = await fetch(LAMBDA + '/price-lookup', {{
        method: 'POST',
        headers: {{ 'Content-Type': 'application/json' }},
        body: JSON.stringify({{ title: title }})
      }});
      const j = await r.json().catch(() => ({{}}));
      const suggested = j.suggested_price || j.price || '';
      $('askPrice').value = suggested || '';
      $('priceNote').textContent = j.note || j.source || 'Stub — confirm with sold comps.';
      $('priceResult').hidden = false;
      setStep(5);
    }} catch (err) {{
      $('priceResult').hidden = false;
      $('priceNote').textContent = 'Price service unreachable — enter manually.';
    }} finally {{
      $('priceBtn').disabled = false;
      $('priceBtn').textContent = '💰 Look up price';
    }}
  }});
  $('askPrice').addEventListener('input', () => {{ if ($('askPrice').value) setStep(6); }});

  // STEP 5 — category guess
  function autoGuessCategory(title) {{
    const t = title.toLowerCase();
    const map = [
      ['183050', /pokemon|pikachu|charizard|tcg/],
      ['38292',  /magic\\b|mtg|planeswalker/],
      ['261330', /football|nfl|qb\\b|quarterback/],
      ['261329', /basketball|nba|lebron|jordan/],
      ['183454', /hockey|nhl/],
      ['261328', /baseball|mlb|topps|ohtani|trout|judge/],
    ];
    for (const [cat, rx] of map) {{
      if (rx.test(t)) {{ $('catSelect').value = cat;
                         $('catHint').textContent = 'Auto-guessed from keywords.'; return; }}
    }}
    $('catHint').textContent = 'Pick the closest match.';
  }}

  // STEP 6 — create draft
  $('createBtn').addEventListener('click', async () => {{
    const title = $('cleanTitle').value.trim();
    const price = parseFloat($('askPrice').value || '0');
    const catId = $('catSelect').value;
    if (!title || !price) {{ alert('Need title and price.'); return; }}
    $('createBtn').disabled = true;
    $('createBtn').textContent = 'Creating...';
    const result = $('createResult');
    result.hidden = false;
    result.innerHTML = '<p class="hint">Uploading photo &amp; building draft...</p>';
    try {{
      let photoUrl = null;
      if (photoDataUrl) {{
        const up = await fetch(LAMBDA + '/upload-photos', {{
          method: 'POST',
          headers: {{ 'Content-Type': 'application/json' }},
          body: JSON.stringify({{ image: photoDataUrl }})
        }}).then(r => r.json()).catch(() => ({{}}));
        photoUrl = up.url || (up.urls && up.urls[0]) || null;
      }}
      const listing = {{
        title: title,
        price: price,
        category_id: catId,
        condition_id: 4000,
        quantity: 1,
        photo_urls: photoUrl ? [photoUrl] : [],
        description: title,
        seller: '{promote.SELLER_NAME}'
      }};
      const r = await fetch(LAMBDA + '/create-listing', {{
        method: 'POST',
        headers: {{ 'Content-Type': 'application/json' }},
        body: JSON.stringify(listing)
      }});
      const j = await r.json();
      if (j.item_id || j.itemId || j.success) {{
        const url = j.view_url || j.url || ('https://www.ebay.com/itm/' + (j.item_id || j.itemId));
        result.innerHTML = '<p style="color:var(--success);font-weight:700;">✓ Draft created!</p>'
                         + '<a href="' + url + '" target="_blank" class="primary-btn" style="display:block;text-align:center;margin-top:10px;text-decoration:none;">View on eBay</a>';
      }} else {{
        result.innerHTML = '<p style="color:var(--danger);">Error: ' + (j.error || JSON.stringify(j)) + '</p>';
      }}
    }} catch (err) {{
      result.innerHTML = '<p style="color:var(--danger);">Failed: ' + err.message + '</p>';
    }} finally {{
      $('createBtn').disabled = false;
      $('createBtn').textContent = '🚀 Create draft on eBay';
    }}
  }});
</script>
"""


def main() -> None:
    body = build_body()
    html_doc = promote.html_shell(
        f"Scan Wizard · {promote.SELLER_NAME}",
        body,
        active_page="scan_wizard.html",
    )
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(html_doc, encoding="utf-8")
    print(f"[scan_wizard] wrote {REPORT}  ({datetime.now(timezone.utc).isoformat()})")


if __name__ == "__main__":
    main()
