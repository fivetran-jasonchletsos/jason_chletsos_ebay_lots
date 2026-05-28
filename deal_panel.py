"""Three-reseller round-table for the Deal Hunter page.

Renders a panel where three reseller archetypes — modeled on common top-seller
strategies on eBay — react to the top deals harvested by fetch_deals(). The
goal: help Jason decide if today's prioritized list is worth pulling the
trigger on or whether to search further.

Personas are deliberately archetypes (strategies, not real handles) so the
panel reads as a strategy lens, not an endorsement:

  Volume Vince — high-velocity modern rookie flipper. Wants liquid modern,
                 BIN, $5-$50, anything that turns in 30 days.
  Grade-It Gina — raw-to-PSA arbitrage. Buys raw, grades, sells PSA 10. Cares
                  about the spread (PSA 10 comp − ask − ~$25 grading − ship).
  Vintage Vic  — pre-2000, HOF, Pokemon WOTC. Skeptical of modern hype,
                 hunts undervalued classics.

Pure rule-based: no LLM calls, deterministic, fast.
"""
from __future__ import annotations

import html as _html
import re
from typing import Any

_HOF_KEYWORDS = (
    "jordan", "mantle", "aaron", "mays", "ruth", "gretzky", "griffey",
    "bonds", "magic ", "bird ", "kobe", "lebron", "jeter", "trout",
    "marino", "montana", "rice", "elway", "favre", "brady", "manning",
    "messi", "ronaldo", "pele",
)
_WOTC_KEYWORDS = (
    "base set", "1st edition", "first edition", "shadowless",
    "wotc", "fossil", "jungle", "team rocket",
)
_GRADED_TOKENS = (" psa ", " bgs ", " sgc ", " cgc ", " hga ", "psa 10", "psa10")
_ROOKIE_TOKENS = (" rc ", " rookie", "(rc)", "/rc", "rookie card")
_FAST_CATS = ("football", "basketball", "baseball")  # liquid sport markets


def _year_in(text: str) -> int:
    m = re.search(r"(19\d{2}|20\d{2})", text)
    return int(m.group()) if m else 0


def _text_for(deal: dict) -> str:
    return (
        (deal.get("title") or "") + " "
        + (deal.get("from_query") or "") + " "
        + (deal.get("from_category") or "")
    ).lower()


# --- Persona scorers --------------------------------------------------------
# Each scorer returns (score 0..5, one-line take).

def _score_vince(d: dict) -> tuple[int, str]:
    text = _text_for(d)
    price = float(d.get("price") or 0)
    median = float(d.get("median") or 0)
    discount = float(d.get("discount_pct") or 0)
    cat = (d.get("from_category") or "").lower()
    ltype = (d.get("listing_type") or "")
    year = _year_in(text)

    score = 0
    notes = []
    if year >= 2020:
        score += 2; notes.append("modern")
    elif year >= 2015:
        score += 1
    if any(k in text for k in _ROOKIE_TOKENS):
        score += 1; notes.append("RC")
    if any(c in cat for c in _FAST_CATS):
        score += 1
    if 5 <= price <= 50:
        score += 1; notes.append(f"${price:.0f} sweet spot")
    if "Auction" in ltype and "BIN" not in ltype:
        score -= 1; notes.append("auction = clock")
    if year and year < 2000:
        score -= 2
    if any(g in text for g in _GRADED_TOKENS):
        score -= 1; notes.append("already graded, less flip room")
    if discount >= 60:
        score += 1
    score = max(0, min(5, score))

    if score >= 4:
        take = f"This one prints. Modern liquid stock, ${price:.0f} in, list Sunday night, gone by Wednesday."
    elif score == 3:
        take = f"Solid flip. {'/'.join(notes) or 'Decent base'}. Not my top of the pile but I'd take it."
    elif score == 2:
        take = "Lukewarm. Margin's there but turn time is the question. Pass unless you're slow this week."
    else:
        take = "Not my lane — too vintage, too slow, or too graded. Skip."
    return score, take


def _score_gina(d: dict) -> tuple[int, str]:
    text = _text_for(d)
    price = float(d.get("price") or 0)
    median = float(d.get("median") or 0)
    query = (d.get("from_query") or "").lower()

    psa_hunt = ("psa 10" in query) or ("psa10" in query)
    already_graded = any(g in text for g in _GRADED_TOKENS)
    is_raw = not already_graded

    # Spread = median (assumed PSA 10 comp when query targets PSA 10)
    # minus ask minus ~$25 PSA Bulk grading minus $1 shipping in.
    spread = median - price - 25 - 1

    if already_graded:
        score = 1
        take = "Already graded. No upside for me — that's Vince or Vic's call."
        return score, take

    if not psa_hunt:
        # raw but query isn't PSA 10 — the median is raw comp; can't assume PSA 10 ceiling
        score = 2
        take = "Raw, but the query isn't a PSA 10 hunt — I can't price the ceiling. Soft skip."
        return score, take

    # Raw + PSA 10 hunt query
    if spread > 80:
        score = 5; take = f"Spread ~${spread:.0f} after grading. Smash buy."
    elif spread > 40:
        score = 4; take = f"~${spread:.0f} spread net of grading + ship. Strong, assuming centering holds up."
    elif spread > 15:
        score = 3; take = f"~${spread:.0f} thin margin. Need the photo to show clean corners — eyes on, then maybe."
    elif spread > 0:
        score = 2; take = f"~${spread:.0f}. Razor thin after fees. Pass unless you love the card."
    else:
        score = 1; take = "Spread doesn't cover grading + ship. Pass."
    return score, take


def _score_vic(d: dict) -> tuple[int, str]:
    text = _text_for(d)
    price = float(d.get("price") or 0)
    year = _year_in(text)

    score = 0
    hits = []
    if year and year < 2000:
        score += 3; hits.append(f"{year}")
    elif year and year < 2010:
        score += 1
    if any(k in text for k in _HOF_KEYWORDS):
        score += 1; hits.append("HOF stock")
    if any(k in text for k in _WOTC_KEYWORDS):
        score += 2; hits.append("WOTC era")
    if year and year >= 2020:
        score -= 2
    score = max(0, min(5, score))

    if score >= 4:
        take = f"This is the lane. {' · '.join(hits) or 'Vintage piece'}. Modern is a casino, this is real."
    elif score == 3:
        take = "Right era or right name. Worth bidding if the comp holds."
    elif score == 2:
        take = "Edge of my radar. Not vintage, but a recognizable name keeps it interesting."
    else:
        take = "Modern. Not what I hunt. Next."
    return score, take


# --- Verdict aggregation ----------------------------------------------------

def _verdict(scored: list[dict]) -> dict:
    if not scored:
        return {"label": "No deals", "summary": "Nothing surfaced today — re-run fetch_deals.", "tone": "neutral"}

    # Strong = at least one persona scoring 4+ on a deal
    strong = sum(1 for s in scored if max(s["v"], s["g"], s["c"]) >= 4)
    consensus = sum(1 for s in scored if min(s["v"], s["g"], s["c"]) >= 3)
    weak = sum(1 for s in scored if max(s["v"], s["g"], s["c"]) <= 2)

    if consensus >= 3:
        return {
            "label": "Strong list — go",
            "summary": (
                f"{consensus} of {len(scored)} top deals have all three personas above neutral. "
                "Solid prioritization — pull the trigger on these before re-querying."
            ),
            "tone": "go",
        }
    if strong >= max(3, len(scored) // 3):
        return {
            "label": "Mixed — act on the strong picks, search further on the rest",
            "summary": (
                f"{strong} deals have at least one persona enthusiastic, but consensus is thin. "
                "Buy the {strong} highlighted picks, then re-query deal_queries.json for the categories "
                "that came up short."
            ).format(strong=strong),
            "tone": "mixed",
        }
    if weak > len(scored) * 0.6:
        return {
            "label": "Search further",
            "summary": (
                f"{weak} of {len(scored)} deals are weak across all three lenses. "
                "Today's list isn't paying — tune deal_queries.json or wait for the next ingest."
            ),
            "tone": "pass",
        }
    return {
        "label": "Mixed list — selective picks only",
        "summary": "No single persona is excited about most of the list. Cherry-pick the rows tagged as strong picks below.",
        "tone": "mixed",
    }


# --- Renderer --------------------------------------------------------------

PERSONAS = [
    {"key": "v", "initials": "VV", "name": "Volume Vince",
     "role": "Modern Rookie Flipper", "tone": "Fast turn. BIN, RC, modern, $5-$50."},
    {"key": "g", "initials": "GG", "name": "Grade-It Gina",
     "role": "Raw-to-PSA-10 Arb",      "tone": "Buys raw if PSA 10 comp − ask − $26 > $30."},
    {"key": "c", "initials": "VV", "name": "Vintage Vic",
     "role": "Pre-2000 + HOF + WOTC",  "tone": "Vintage only. Skeptical of modern hype."},
]


def _pip(score: int) -> str:
    """Render the persona's verdict pip for a deal row."""
    if score >= 4:
        return f'<span class="dp-pip dp-pip--hot" title="Score {score}/5 — strong">+{score}</span>'
    if score == 3:
        return f'<span class="dp-pip dp-pip--ok"  title="Score {score}/5 — neutral">~{score}</span>'
    return f'<span class="dp-pip dp-pip--cold" title="Score {score}/5 — skip">·{score}</span>'


def render_panel(top_deals: list[dict], max_rows: int = 10) -> str:
    """Return the panel HTML block ready to embed in deals.html."""
    deals = (top_deals or [])[:max_rows]
    if not deals:
        return ""

    scored = []
    for d in deals:
        v_s, v_t = _score_vince(d)
        g_s, g_t = _score_gina(d)
        c_s, c_t = _score_vic(d)
        scored.append({
            "deal": d,
            "v": v_s, "v_take": v_t,
            "g": g_s, "g_take": g_t,
            "c": c_s, "c_take": c_t,
            "max": max(v_s, g_s, c_s),
        })

    verdict = _verdict(scored)

    # Per-persona summary line: who's voting strongest, what they liked.
    persona_summary = []
    for p in PERSONAS:
        k = p["key"]
        picks = [s for s in scored if s[k] >= 4]
        if picks:
            best = picks[0]
            line = f'<b>{len(picks)} strong pick{"s" if len(picks) != 1 else ""}.</b> Top: "{_html.escape(best[k+"_take"])}"'
        else:
            line = '<b>Nothing strong today.</b> Recommends re-querying.'
        persona_summary.append((p, line))

    # Build deal-row HTML for the round table
    rows = []
    for i, s in enumerate(scored, 1):
        d = s["deal"]
        title = _html.escape((d.get("title") or "")[:90])
        price = float(d.get("price") or 0)
        median = float(d.get("median") or 0)
        url = d.get("url") or "#"
        # Pick the most enthusiastic take to show alongside the pips
        best_persona = max(PERSONAS, key=lambda p: s[p["key"]])
        best_take = s[best_persona["key"] + "_take"]
        best_score = s[best_persona["key"]]
        # Highlight class for strong picks (any persona >= 4)
        row_cls = "dp-row dp-row--hot" if s["max"] >= 4 else "dp-row"
        rows.append(f"""
        <li class="{row_cls}">
          <span class="dp-rank">{i}</span>
          <span class="dp-pips">{_pip(s["v"])}{_pip(s["g"])}{_pip(s["c"])}</span>
          <a class="dp-title" href="{_html.escape(url)}" target="_blank" rel="noopener">{title}</a>
          <span class="dp-money">
            <b>${price:.2f}</b><span class="dp-median"> · median ${median:.2f}</span>
          </span>
          <span class="dp-take">
            <i class="dp-take-by">{_html.escape(best_persona["name"])} ({best_score}/5):</i>
            {_html.escape(best_take)}
          </span>
        </li>""")

    persona_cards = []
    for p, line in persona_summary:
        persona_cards.append(f"""
        <div class="dp-persona">
          <div class="dp-avatar">{p["initials"]}</div>
          <div class="dp-id">
            <div class="dp-name">{p["name"]}</div>
            <div class="dp-role">{p["role"]}</div>
            <div class="dp-tone">{p["tone"]}</div>
            <div class="dp-line">{line}</div>
          </div>
        </div>""")

    tone_class = {
        "go":      "dp-verdict--go",
        "mixed":   "dp-verdict--mixed",
        "pass":    "dp-verdict--pass",
        "neutral": "",
    }.get(verdict["tone"], "")

    return f"""
    <section class="deal-panel" aria-label="Reseller round table on today's top deals">
      <div class="dp-head">
        <div class="dp-eyebrow">Round Table · Reseller Panel</div>
        <h2 class="dp-title-main">Should you act on today's <em>top {len(scored)} deals</em>?</h2>
        <p class="dp-sub">Three reseller archetypes score the prioritized deal list. Strong picks (any persona giving 4+ out of 5) are highlighted below.</p>
      </div>

      <div class="dp-personas">
        {''.join(persona_cards)}
      </div>

      <div class="dp-verdict {tone_class}">
        <span class="dp-verdict-label">{_html.escape(verdict["label"])}</span>
        <span class="dp-verdict-summary">{_html.escape(verdict["summary"])}</span>
      </div>

      <ol class="dp-rows">
        {''.join(rows)}
      </ol>

      <div class="dp-foot">
        Scoring is rule-based. Pips: <b>+N</b> strong, <b>~N</b> neutral, <b>·N</b> skip. Tune the heuristics in <code>deal_panel.py</code>.
      </div>
    </section>"""


def panel_css() -> str:
    """CSS for the deal panel block — scoped to .deal-panel."""
    return """
    .deal-panel {
      background: var(--surface);
      border: 1px solid var(--border);
      border-left: 3px solid var(--gold);
      border-radius: var(--r-lg);
      padding: 22px 24px 18px;
      margin: 20px 0 28px;
    }
    .deal-panel .dp-eyebrow {
      font-size: 11px; letter-spacing: .18em; text-transform: uppercase;
      color: var(--gold); font-weight: 700;
    }
    .deal-panel .dp-title-main {
      font-family: 'Fraunces', Georgia, serif;
      font-style: italic; font-weight: 500;
      font-size: 26px; line-height: 1.15;
      margin: 6px 0 4px; color: var(--text);
    }
    .deal-panel .dp-title-main em { color: var(--gold); font-style: italic; }
    .deal-panel .dp-sub { color: var(--text-muted); font-size: 13px; margin: 0; }

    .deal-panel .dp-personas {
      display: grid; grid-template-columns: repeat(3, 1fr);
      gap: 12px; margin: 18px 0 14px;
    }
    .deal-panel .dp-persona {
      display: grid; grid-template-columns: 44px 1fr; gap: 12px;
      background: var(--surface-2, rgba(255,255,255,.03));
      border: 1px solid var(--border);
      border-radius: var(--r-md);
      padding: 12px 14px;
    }
    .deal-panel .dp-avatar {
      width: 44px; height: 44px; border-radius: 50%;
      background: linear-gradient(135deg, var(--gold), var(--gold-dim));
      color: var(--brand-fg);
      display: flex; align-items: center; justify-content: center;
      font-family: 'Fraunces', Georgia, serif; font-style: italic;
      font-weight: 600; font-size: 16px; letter-spacing: .02em;
    }
    .deal-panel .dp-name { font-weight: 700; font-size: 13.5px; color: var(--text); }
    .deal-panel .dp-role { font-size: 11px; color: var(--gold); font-weight: 600; letter-spacing: .04em; }
    .deal-panel .dp-tone { font-size: 11px; color: var(--text-muted); margin-top: 2px; }
    .deal-panel .dp-line { font-size: 12px; color: var(--text); margin-top: 6px; line-height: 1.4; }
    .deal-panel .dp-line b { color: var(--gold); }

    .deal-panel .dp-verdict {
      display: flex; flex-direction: column; gap: 4px;
      padding: 12px 14px; margin: 6px 0 14px;
      background: var(--surface-3, rgba(255,255,255,.04));
      border: 1px solid var(--border);
      border-left: 3px solid var(--border-mid, var(--border));
      border-radius: var(--r-md);
    }
    .deal-panel .dp-verdict--go      { border-left-color: #6BC368; }
    .deal-panel .dp-verdict--mixed   { border-left-color: var(--gold); }
    .deal-panel .dp-verdict--pass    { border-left-color: #d77a5a; }
    .deal-panel .dp-verdict-label {
      font-family: 'Fraunces', Georgia, serif;
      font-style: italic; font-weight: 500; font-size: 17px;
      color: var(--text);
    }
    .deal-panel .dp-verdict-summary { font-size: 12.5px; color: var(--text-muted); }

    .deal-panel .dp-rows { list-style: none; padding: 0; margin: 4px 0 0; }
    .deal-panel .dp-row {
      display: grid;
      grid-template-columns: 22px 84px minmax(0,1fr) auto;
      grid-template-rows: auto auto;
      grid-template-areas:
        "rank pips title money"
        ".    .    take  take";
      gap: 4px 12px; align-items: center;
      padding: 10px 6px; border-top: 1px solid var(--border);
    }
    .deal-panel .dp-row--hot { background: rgba(212,175,55,.04); }
    .deal-panel .dp-rank { grid-area: rank; color: var(--text-muted); font-size: 11px; font-weight: 700; }
    .deal-panel .dp-pips { grid-area: pips; display: flex; gap: 3px; }
    .deal-panel .dp-pip {
      display: inline-block; min-width: 22px; padding: 2px 5px;
      border-radius: 4px; font-size: 10px; font-weight: 700; text-align: center;
      font-family: 'SF Mono', ui-monospace, Menlo, monospace;
    }
    .deal-panel .dp-pip--hot  { background: rgba(107,195,104,.18); color: #6BC368; }
    .deal-panel .dp-pip--ok   { background: rgba(212,175,55,.18); color: var(--gold); }
    .deal-panel .dp-pip--cold { background: rgba(215,122,90,.15); color: #d77a5a; }
    .deal-panel .dp-title {
      grid-area: title;
      font-size: 13px; font-weight: 600; color: var(--text);
      text-decoration: none; min-width: 0; overflow: hidden;
      text-overflow: ellipsis; white-space: nowrap;
    }
    .deal-panel .dp-title:hover { color: var(--gold); }
    .deal-panel .dp-money { grid-area: money; font-size: 12px; color: var(--text); white-space: nowrap; }
    .deal-panel .dp-money b { color: var(--gold); font-family: 'Fraunces', Georgia, serif; font-style: italic; font-size: 15px; letter-spacing: .02em; }
    .deal-panel .dp-median { color: var(--text-muted); text-decoration: line-through; font-size: 11px; }
    .deal-panel .dp-take {
      grid-area: take; font-size: 12px; color: var(--text-muted);
      line-height: 1.4; padding-left: 0;
    }
    .deal-panel .dp-take-by { font-style: normal; color: var(--gold); font-weight: 600; margin-right: 4px; }

    .deal-panel .dp-foot {
      font-size: 11px; color: var(--text-dim, var(--text-muted));
      margin-top: 14px; padding-top: 10px; border-top: 1px dashed var(--border);
    }
    .deal-panel .dp-foot code {
      background: var(--surface-3, rgba(255,255,255,.04));
      padding: 1px 5px; border-radius: 3px; font-size: 10.5px;
    }

    @media (max-width: 720px) {
      .deal-panel .dp-personas { grid-template-columns: 1fr; }
      .deal-panel .dp-row {
        grid-template-columns: 22px 84px 1fr;
        grid-template-areas:
          "rank pips title"
          ".    .    money"
          ".    .    take";
      }
      .deal-panel .dp-money { text-align: left; }
    }
    """
