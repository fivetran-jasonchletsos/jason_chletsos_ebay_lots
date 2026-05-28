"""
build_ai_overview.py — generate a polished PDF overview of every AI/ML surface
in this project.

Two audiences supported:
  --audience exec      (default) — Head-of-AI-Products / executive lens.
                       Output: docs/harpua_ai_overview.pdf + ~/Downloads copy.
  --audience linkedin  — founder/builder voice for a LinkedIn post.
                       Ends with a CTA link to ebay.com/str/harpua2001.
                       Output: ~/Downloads/harpua_ai_overview_linkedin.pdf only.

Pipeline:
  1. Render HTML with brand styling (Fraunces display + Inter body).
  2. Convert to PDF via headless Chrome (respects @page CSS and Google Fonts).

Run:
    python3 build_ai_overview.py                    # exec version
    python3 build_ai_overview.py --audience linkedin
    python3 build_ai_overview.py --audience both
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from datetime import date
from pathlib import Path

REPO_ROOT  = Path(__file__).parent
DOCS_DIR   = REPO_ROOT / "docs"
DOWNLOADS  = Path.home() / "Downloads"

EBAY_STORE_URL = "https://www.ebay.com/str/harpua2001"

CHROME_CANDIDATES = [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
]


def find_chrome() -> str:
    for p in CHROME_CANDIDATES:
        if Path(p).is_file():
            return p
    raise SystemExit("No Chrome/Chromium/Edge/Brave found. Install one or wire wkhtmltopdf.")


HTML_EXEC = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>harpua2001 — AI Surface Overview</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,400;9..144,600;9..144,800&family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
  @page {
    size: Letter;
    margin: 0.6in 0.55in 0.55in 0.55in;
  }
  html, body {
    margin: 0; padding: 0;
    font-family: 'Inter', -apple-system, system-ui, sans-serif;
    font-size: 10.5pt; line-height: 1.45;
    color: #1a1814;
    background: #faf7f1;
  }
  .wrap { padding: 0 0 24pt 0; }
  header { border-bottom: 2px solid #c9a44a; padding-bottom: 14pt; margin-bottom: 18pt; }
  .eyebrow {
    font-family: 'Inter', sans-serif; font-size: 8.5pt; font-weight: 700;
    letter-spacing: 0.22em; text-transform: uppercase; color: #8a6d2e;
  }
  h1 {
    font-family: 'Fraunces', Georgia, serif;
    font-variation-settings: 'opsz' 144, 'SOFT' 30;
    font-weight: 600; font-style: italic;
    font-size: 28pt; line-height: 1.05; letter-spacing: -0.01em;
    margin: 6pt 0 4pt 0; color: #1a1814;
  }
  h1 em { color: #8a6d2e; font-style: italic; }
  .deck { font-size: 11pt; color: #4a4438; max-width: 520pt; margin: 0; }
  h2 {
    font-family: 'Fraunces', Georgia, serif;
    font-variation-settings: 'opsz' 144;
    font-weight: 700; font-size: 15pt; letter-spacing: -0.005em;
    margin: 22pt 0 8pt 0; color: #1a1814;
    border-top: 1px solid #d8cfb8; padding-top: 12pt;
  }
  h2:first-of-type { border-top: 0; padding-top: 0; margin-top: 4pt; }
  h3 {
    font-family: 'Inter', sans-serif; font-weight: 700;
    font-size: 10.5pt; margin: 10pt 0 4pt 0;
  }
  p { margin: 0 0 8pt 0; }
  ul { margin: 4pt 0 8pt 14pt; padding: 0; }
  li { margin-bottom: 3pt; }
  code, .mono {
    font-family: 'SF Mono', ui-monospace, Menlo, monospace;
    font-size: 9pt; background: #f1ead7; padding: 1pt 4pt; border-radius: 2pt;
    color: #4a3a14;
  }
  .pill {
    display: inline-block;
    font-size: 7.5pt; font-weight: 700; letter-spacing: 0.1em; text-transform: uppercase;
    padding: 2pt 6pt; border-radius: 999pt;
    background: #1a1814; color: #c9a44a;
    vertical-align: 1pt;
  }
  .tldr {
    background: #fff;
    border: 1px solid #d8cfb8;
    border-left: 3pt solid #c9a44a;
    padding: 10pt 14pt;
    margin: 8pt 0 12pt 0;
    border-radius: 2pt;
  }
  .tldr p { margin: 0; }
  table {
    width: 100%; border-collapse: collapse;
    margin: 6pt 0 10pt 0;
    font-size: 9.5pt;
  }
  th, td {
    text-align: left; padding: 5pt 7pt 5pt 0;
    vertical-align: top;
    border-bottom: 1px solid #e6ddc4;
  }
  th {
    font-weight: 700; font-size: 8.5pt; letter-spacing: 0.08em;
    text-transform: uppercase; color: #6c5a2e;
    border-bottom: 1px solid #8a6d2e;
  }
  td.surface { font-weight: 600; color: #1a1814; }
  td.model  { font-family: 'SF Mono', ui-monospace, Menlo, monospace; font-size: 8.5pt; color: #4a3a14; }
  .twocol { display: grid; grid-template-columns: 1fr 1fr; gap: 14pt; }
  .stat-strip {
    display: grid; grid-template-columns: repeat(4, 1fr); gap: 8pt;
    margin: 6pt 0 14pt 0;
  }
  .stat {
    background: #1a1814; color: #faf7f1;
    padding: 10pt 12pt; border-radius: 3pt;
  }
  .stat .n {
    font-family: 'Fraunces', Georgia, serif; font-variation-settings: 'opsz' 144;
    font-weight: 600; font-style: italic; font-size: 22pt; line-height: 1;
    color: #c9a44a;
  }
  .stat .l {
    font-size: 7.5pt; font-weight: 700; letter-spacing: 0.16em;
    text-transform: uppercase; margin-top: 3pt; color: #faf7f1; opacity: 0.85;
  }
  .footnote {
    font-size: 8.5pt; color: #6c5a2e; margin-top: 14pt;
    border-top: 1px solid #d8cfb8; padding-top: 10pt;
  }
  .footnote .meta { color: #8a6d2e; }
  .filepath { font-family: 'SF Mono', ui-monospace, Menlo, monospace; font-size: 8.5pt; color: #4a3a14; }
  .badge-paused { background: #e6ddc4; color: #6c5a2e; }
</style>
</head>
<body>
<div class="wrap">

<header>
  <div class="eyebrow">harpua2001 &middot; eBay Lots project</div>
  <h1>AI on a <em>one-person</em> sports-cards store.</h1>
  <p class="deck">An honest inventory of every LLM call, every rules-based agent, every data source, and the multi-agent Claude Code workflow that runs it all. Built by Jason Chletsos. {DATE_STAMP}.</p>
</header>

<div class="stat-strip">
  <div class="stat"><div class="n">3</div><div class="l">Live Claude surfaces</div></div>
  <div class="stat"><div class="n">21</div><div class="l">Planning agents (rules)</div></div>
  <div class="stat"><div class="n">5</div><div class="l">Fivetran-synced tables</div></div>
  <div class="stat"><div class="n">7</div><div class="l">Pricing sources</div></div>
</div>

<div class="tldr">
<p><b>TL;DR.</b> Three production LLM surfaces (all Anthropic Claude), each with a sharp job — buyer-facing chat assistant, per-listing copy/CTR optimizer, and on-phone card vision. Around the LLMs sits a deterministic agent constellation that does the slow, dollarized work: repricing, promoted-listings bidding, best-offer auto-respond, photo audits, Cassini scoring. Every production write is gated by a dry-run + typed-yes confirm. A custom Fivetran Connector SDK pipes five eBay tables into the warehouse; the buyer-facing site reads from that. Day-to-day development is driven by a multi-agent Claude Code cadence — fan out 4-6 specialist agents in parallel, verify, ship.</p>
</div>

<h2>1. Live LLM surfaces</h2>
<p>Three Anthropic Claude surfaces are in production today. Zero OpenAI, Gemini, or non-Anthropic calls in the codebase.</p>

<table>
<thead><tr><th style="width:23%">Surface</th><th style="width:18%">Model</th><th>What it does</th><th style="width:22%">Cost &amp; safety</th></tr></thead>
<tbody>
<tr>
  <td class="surface">Buyer-site AI assistant <span class="pill">live</span></td>
  <td class="model">claude-opus-4-7</td>
  <td>Lambda route <code>POST /ebay/ai-chat</code> backs <code>docs/assistant.html</code>. System prompt frames Claude as the store's cards assistant, with persona context (favorite Pokemon list, store policies). Multi-turn conversation; serves visitors who want help finding cards or asking buying questions.</td>
  <td>max_tokens 1024; per-turn history truncated to last N, each capped at 8000 chars; token usage logged from response.</td>
</tr>
<tr>
  <td class="surface">AI Listing Optimizer <span class="pill">live</span></td>
  <td class="model">claude-sonnet-4</td>
  <td>Per-listing "AI Optimize" button on the seller dashboard. Sends current title, price, CTR, impressions, and promoted flag. Returns a 4-section diagnosis (DIAGNOSIS, OPTIMIZED TITLE, OPTIMIZED DESCRIPTION, ACTIONS). Streams via SSE so the diagnosis renders as it generates.</td>
  <td>max_tokens 1200; BYO key (stored in browser localStorage); <code>anthropic-dangerous-direct-browser-access: true</code>.</td>
</tr>
<tr>
  <td class="surface">Mobile card scanner (vision) <span class="pill badge-paused">paused</span></td>
  <td class="model">claude-sonnet-4-6 (default) / opus-4-7 / haiku-4-5</td>
  <td>Front + optional back photo, base64-encoded to the Messages API. System prompt forces a strict JSON schema — name, set, number, total, rarity, foil, edition, language, condition_hints, confidence. Output drops into the same <code>inventory.csv</code> schema the Python pipeline consumes, so card-scanner and CSV-import are interchangeable inputs.</td>
  <td>max_tokens 600; API key in iOS Keychain / Android encrypted prefs via <code>expo-secure-store</code>; per-scan cost surfaced in the model picker (~$0.005 Sonnet, ~$0.002 Haiku, ~$0.03 Opus).</td>
</tr>
</tbody>
</table>

<h2>2. Heuristic agent stack (no LLM, by design)</h2>
<p>Around the LLM surfaces sits a deterministic agent constellation. Each agent runs in <b>dry-run mode by default</b>, writes a plan JSON, renders an HTML report for review, and only mutates eBay state when invoked with <code>--apply</code> and an explicit per-agent confirmation. Total: 21 agents.</p>

<div class="twocol">
<div>
<h3>Pricing &amp; offers</h3>
<ul>
  <li><b>repricing_agent</b> — guardrailed raise/lower/hold from sold-history median, multi-source pricing, per-listing locks. Writes via Trading <code>ReviseItem</code>.</li>
  <li><b>best_offer_agent</b> / <b>best_offer_autorespond_agent</b> — auto-accept at market median * 0.95, auto-decline at * 0.75, midpoint counter in the middle band.</li>
  <li><b>watchers_offer_agent</b> — proactive offers to watchers using floor = max(absolute, current * multiplier, sold_median * 0.92).</li>
  <li><b>price_drops_agent</b>, <b>price_consistency_agent</b> — flag listings off-market vs. comps.</li>
  <li><b>card_price_agent</b> — tokenizes titles, scores candidate products against SportsCardsPro <code>/api/products</code>, fetches grade-matched price.</li>
</ul>

<h3>Listing performance &amp; ranking</h3>
<ul>
  <li><b>cassini_score_agent</b> — 0-100 rubric (photos 25, specifics 20, title 15, impressions 15, CTR 10, recent sale 10, offer eligibility 5).</li>
  <li><b>listing_performance_agent</b> — reads eBay Sell Analytics <code>traffic_report</code> joined to local snapshot.</li>
  <li><b>promoted_listings_agent</b> — 5 ad-rate tiers (NO_AD, LOW, STANDARD, AGGRESSIVE, MAX) by rule classification.</li>
  <li><b>photo_audit_agent</b> / <b>photo_quality_audit</b> — Pillow-based scoring on count, long-edge px, file-size proxy, aspect, coverage.</li>
</ul>
</div>
<div>
<h3>Inventory + ops</h3>
<ul>
  <li><b>inventory_agent</b> — reads <code>inventory.csv</code> (now CollX-sourced), suggests title/category/price/specifics, renders ready-to-list HTML.</li>
  <li><b>collx_ingest</b> — adapter from CollX Pro CSV export to the inventory schema (CollX has no public dev API).</li>
  <li><b>push_to_ebay</b> — single-card live <code>AddItem</code> with dry-run + typed-yes confirm gate.</li>
  <li><b>relist_agent</b> — ended/unsold republication queue.</li>
  <li><b>orders_watch_agent</b>, <b>tracking_responder_agent</b> — order lifecycle + automated tracking replies.</li>
  <li><b>combined_shipping</b> — flips <code>ApplyShippingDiscount</code> in bulk via <code>ReviseItem</code>.</li>
</ul>

<h3>Buyer-side &amp; marketing</h3>
<ul>
  <li><b>buyer_watchlist_agent</b> — scoring + outreach signal for watcher cohorts.</li>
  <li><b>repeat_buyers_agent</b> — tier by count + lifetime spend; templated thank-yous.</li>
  <li><b>email_campaign_agent</b> — assembles top-margin "Steals" plus volume-discount banner.</li>
  <li><b>message_responder_agent</b> — FAQ pattern matching for buyer questions.</li>
  <li><b>daily_digest_agent</b>, <b>pnl_agent</b>, <b>pokemon_news_agent</b>, <b>pokemon_deals_agent</b>, <b>top_sellers_agent</b>, <b>under_10_agent</b>, <b>vault_eligibility</b>, <b>hub_pages_agent</b> — reporting / merchandising / catalog.</li>
</ul>
</div>
</div>

<h2>3. Data + ML inputs</h2>
<p>The agents are only as good as the signals they ingest. Five integration paths feed them:</p>
<ul>
  <li><b>Fivetran custom connector</b> (<span class="filepath">connector.py</span>) — written against the Fivetran Connector SDK. Syncs five eBay tables to the warehouse: <code>active_listings</code>, <code>listing_performance</code>, <code>orders</code>, <code>promoted_listings</code>, <code>seller_standards</code>. Encodes hard-won knowledge — Browse API returns 403 for user tokens, so listing data is reconstructed from orders + promoted listings; <code>traffic_report</code> requires <code>marketplace_ids:EBAY_US</code>.</li>
  <li><b>Pricing</b> — SportsCardsPro / PriceCharting (paid, single API key) as "actual price"; eBay Finding API sold history as "market price"; Pokemon TCG API (free) as Pokemon fallback; CollX Pro CSV as live market signal for current inventory.</li>
  <li><b>Cassini ranking model</b> — deterministic 0-100 score derived from observable Cassini inputs. Not a trained model; an opinionated proxy.</li>
  <li><b>Warehouse</b> — DuckDB locally, Fivetran-loaded <code>tester.*</code> tables consumed by the dashboard builder.</li>
  <li><b>Lambda layer</b> — <code>jw0hur2091.execute-api.us-east-1.amazonaws.com</code> hosts the Trading API write surfaces (revise / reprice / ai-chat / oauth callback / account-deletion notification handler).</li>
</ul>

<h2>4. Collaboration workflow with Claude Code</h2>
<p>The most active AI surface on this project is actually the development loop itself — Claude Code as a teammate, not as a generation tool. Three patterns are durable:</p>
<ul>
  <li><b>Multi-agent fan-out for features.</b> When a task is broad ("audit the buyer site for conversion gaps", "build the store-companion mobile flow"), launch 4–6 specialist agents in parallel — reseller persona, mobile-UX designer, eBay API risk reviewer, etc. Aggregate findings, ship. Default cadence.</li>
  <li><b>Dry-run + typed-yes for every production write.</b> No agent ever writes to eBay without printing the full plan, surfacing economics + risks, and prompting for an explicit "yes". Encoded in <code>harpua-daily</code> skill, in <code>push_to_ebay.py</code>, in every <code>--apply</code> flag.</li>
  <li><b>Persistent project memory.</b> Ten memory notes at <span class="filepath">.claude/projects/&hellip;/memory/</span> capture project goal, agent catalog, conversion-audit findings, slang preferences, fan-out cadence. Future sessions start with full context — no "what are we working on again."</li>
</ul>
<p>One concrete skill — <code>harpua-daily</code> — runs all 21 planning agents in dry-run, summarizes each into a single table (Agent &middot; What it would do &middot; $ impact), and refuses to add <code>--apply</code> without explicit per-agent confirmation. The skill also encodes a known schema-drift bug in two agents and the one-line fix.</p>

<h2>5. Paused / experimental</h2>
<ul>
  <li><b>Mobile companion app</b> (Expo / React Native). Card scanner is wired to Claude vision; eBay listing creation is implemented. Paused at commit <code>2fbd691</code> — CollX Pro became the inventory source-of-truth and supplanted the on-phone scanner. Code is preserved, not deleted.</li>
  <li><b>eBay Vault enrollment</b> — flagged by <code>best_offer_agent</code> but eBay has not exposed a Vault-enroll field in <code>ReviseItem</code> as of mid-2026. Will wire when the API surface lands.</li>
  <li><b>Photo upload to live listings</b> — UI built; Lambda route <code>/upload-photos</code> not deployed.</li>
  <li><b>Two known-broken agents</b> — <code>listing_performance_agent</code>, <code>pnl_agent</code> crash on snapshot schema drift. <code>harpua-daily</code> skips them; one-line fix is documented in the skill.</li>
</ul>

<div class="footnote">
<div class="meta">Generated by <code>build_ai_overview.py</code> from the live repo state. Source paths and findings traceable in the audit log.</div>
<div class="meta" style="margin-top:6pt;">harpua2001 store: <a href="https://www.ebay.com/str/harpua2001" style="color:#8a6d2e; text-decoration: none;">ebay.com/str/harpua2001</a> &middot; Public dashboard: index.html &middot; Inventory pipeline: inventory.html</div>
</div>

</div>
</body>
</html>
"""


HTML_LINKEDIN = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>How I run an eBay sports-card store with AI — harpua2001</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,400;9..144,600;9..144,800&family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
  @page { size: Letter; margin: 0.5in 0.5in 0.5in 0.5in; }
  html, body {
    margin: 0; padding: 0;
    font-family: 'Inter', -apple-system, system-ui, sans-serif;
    font-size: 10pt; line-height: 1.45;
    color: #1a1814; background: #faf7f1;
  }
  .wrap { padding: 0 0 20pt 0; }
  header { border-bottom: 2px solid #c9a44a; padding-bottom: 12pt; margin-bottom: 14pt; }
  .eyebrow {
    font-family: 'Inter', sans-serif; font-size: 8pt; font-weight: 700;
    letter-spacing: 0.22em; text-transform: uppercase; color: #8a6d2e;
  }
  h1 {
    font-family: 'Fraunces', Georgia, serif;
    font-variation-settings: 'opsz' 144, 'SOFT' 30;
    font-weight: 600; font-style: italic;
    font-size: 25pt; line-height: 1.05; letter-spacing: -0.01em;
    margin: 5pt 0 5pt 0; color: #1a1814;
  }
  h1 em { color: #8a6d2e; font-style: italic; }
  .deck { font-size: 10.5pt; color: #4a4438; max-width: 540pt; margin: 0; }
  h2 {
    font-family: 'Fraunces', Georgia, serif;
    font-variation-settings: 'opsz' 144;
    font-weight: 700; font-size: 14pt; letter-spacing: -0.005em;
    margin: 14pt 0 6pt 0; color: #1a1814;
    border-top: 1px solid #d8cfb8; padding-top: 10pt;
  }
  h2:first-of-type { border-top: 0; padding-top: 0; margin-top: 2pt; }
  p { margin: 0 0 7pt 0; }
  ul { margin: 4pt 0 6pt 14pt; padding: 0; }
  li { margin-bottom: 3pt; }
  code, .mono {
    font-family: 'SF Mono', ui-monospace, Menlo, monospace;
    font-size: 8.5pt; background: #f1ead7; padding: 1pt 4pt; border-radius: 2pt;
    color: #4a3a14;
  }
  .stat-strip {
    display: grid; grid-template-columns: repeat(4, 1fr); gap: 8pt;
    margin: 8pt 0 12pt 0;
  }
  .stat {
    background: #1a1814; color: #faf7f1;
    padding: 9pt 12pt; border-radius: 3pt;
  }
  .stat .n {
    font-family: 'Fraunces', Georgia, serif; font-variation-settings: 'opsz' 144;
    font-weight: 600; font-style: italic; font-size: 20pt; line-height: 1;
    color: #c9a44a;
  }
  .stat .l {
    font-size: 7pt; font-weight: 700; letter-spacing: 0.16em;
    text-transform: uppercase; margin-top: 3pt; color: #faf7f1; opacity: 0.85;
  }
  /* Architecture grid */
  .arch {
    display: grid; grid-template-columns: repeat(4, 1fr); gap: 8pt;
    margin: 6pt 0 10pt 0;
  }
  .layer {
    background: #fff; border: 1px solid #d8cfb8;
    border-top: 3pt solid #c9a44a;
    padding: 9pt 10pt 10pt 10pt; border-radius: 3pt;
  }
  .layer .layer-name {
    font-family: 'Inter', sans-serif; font-size: 7.5pt;
    font-weight: 800; letter-spacing: 0.18em; text-transform: uppercase;
    color: #8a6d2e; margin-bottom: 3pt;
  }
  .layer .layer-headline {
    font-family: 'Fraunces', Georgia, serif; font-variation-settings: 'opsz' 144;
    font-weight: 700; font-size: 11pt; line-height: 1.15;
    margin-bottom: 6pt; color: #1a1814;
  }
  .layer ul { margin: 0; padding-left: 13pt; }
  .layer li { font-size: 8.5pt; line-height: 1.35; margin-bottom: 2pt; color: #2c2820; }
  .layer li b { color: #1a1814; }
  /* Surface table */
  table.surfaces {
    width: 100%; border-collapse: collapse;
    font-size: 9pt; margin: 4pt 0 8pt 0;
  }
  table.surfaces th, table.surfaces td {
    padding: 4pt 8pt 4pt 0; text-align: left;
    vertical-align: top; border-bottom: 1px solid #e6ddc4;
  }
  table.surfaces th {
    font-size: 7.5pt; font-weight: 700; letter-spacing: 0.1em;
    text-transform: uppercase; color: #6c5a2e;
    border-bottom: 1px solid #8a6d2e;
  }
  table.surfaces td.s { font-weight: 600; color: #1a1814; }
  table.surfaces td.m { font-family: 'SF Mono', ui-monospace, Menlo, monospace; font-size: 8.5pt; color: #4a3a14; white-space: nowrap; }
  /* Morning routine */
  .morning {
    background: #1a1814; color: #ecdfb8;
    border-radius: 4pt; padding: 14pt 16pt;
    margin: 6pt 0 4pt 0;
  }
  .morning .prompt {
    font-family: 'SF Mono', ui-monospace, Menlo, monospace; font-size: 9.5pt;
    color: #c9a44a; margin-bottom: 8pt;
  }
  .morning .prompt .dollar { color: #faf7f1; opacity: 0.5; margin-right: 6pt; }
  .morning .plan-table {
    width: 100%; border-collapse: collapse;
    font-family: 'SF Mono', ui-monospace, Menlo, monospace;
    font-size: 8.5pt; color: #ecdfb8;
  }
  .morning .plan-table th, .morning .plan-table td {
    padding: 3pt 8pt 3pt 0; text-align: left; vertical-align: top;
    border-bottom: 1px solid rgba(201, 164, 74, 0.18);
  }
  .morning .plan-table th {
    font-family: 'Inter', sans-serif; font-size: 7pt; font-weight: 700;
    letter-spacing: 0.16em; text-transform: uppercase;
    color: #c9a44a; border-bottom: 1px solid #c9a44a;
  }
  .morning .plan-table td.agent { color: #faf7f1; font-weight: 500; }
  .morning .plan-table td.dollars { color: #c9a44a; white-space: nowrap; text-align: right; }
  .morning .footer-line {
    margin-top: 10pt;
    font-family: 'SF Mono', ui-monospace, Menlo, monospace; font-size: 9pt;
    color: #c9a44a;
  }
  .morning .footer-line .ask { color: #faf7f1; opacity: 0.7; }
  .morning .footer-line .yes { color: #c9a44a; font-weight: 700; }
  /* Why unique */
  .unique { display: grid; grid-template-columns: 1fr 1fr; gap: 8pt 18pt; margin-top: 4pt; }
  .unique .pt { padding-left: 18pt; position: relative; }
  .unique .pt::before {
    content: ""; position: absolute; left: 0; top: 4pt;
    width: 8pt; height: 8pt; background: #c9a44a; border-radius: 2pt;
  }
  .unique .pt-head {
    font-family: 'Fraunces', Georgia, serif; font-variation-settings: 'opsz' 144;
    font-weight: 700; font-size: 10.5pt; color: #1a1814; margin-bottom: 1pt;
  }
  .unique .pt-body { font-size: 9pt; color: #3a3528; line-height: 1.4; }
  .cta {
    margin-top: 16pt;
    background: #1a1814; color: #faf7f1;
    padding: 16pt 20pt; border-radius: 4pt;
  }
  .cta .cta-eyebrow {
    font-size: 8pt; font-weight: 700; letter-spacing: 0.22em;
    text-transform: uppercase; color: #c9a44a;
  }
  .cta .cta-head {
    font-family: 'Fraunces', Georgia, serif; font-variation-settings: 'opsz' 144;
    font-weight: 600; font-style: italic; font-size: 17pt; line-height: 1.15;
    margin: 2pt 0 6pt 0;
  }
  .cta .cta-head em { color: #c9a44a; font-style: italic; }
  .cta .cta-deck { color: #ecdfb8; font-size: 10pt; margin-bottom: 8pt; }
  .cta .cta-link {
    display: inline-block;
    font-family: 'SF Mono', ui-monospace, Menlo, monospace; font-size: 10.5pt;
    font-weight: 600; color: #c9a44a; text-decoration: none;
    background: rgba(201, 164, 74, 0.12);
    padding: 7pt 12pt; border: 1pt solid #c9a44a; border-radius: 3pt;
  }
  .footnote {
    font-size: 8pt; color: #6c5a2e; margin-top: 10pt;
    border-top: 1px solid #d8cfb8; padding-top: 6pt;
  }
</style>
</head>
<body>
<div class="wrap">

<header>
  <div class="eyebrow">Builder notes &middot; harpua2001</div>
  <h1>How I run an eBay sports-card store like a <em>team of ten</em>.</h1>
  <p class="deck">Solo operator. Real store. AI in the right places, deterministic agents in the rest. Below: the actual architecture, the products in the stack, and why this combination ships things a one-person business shouldn't be able to ship.</p>
</header>

<div class="stat-strip">
  <div class="stat"><div class="n">3</div><div class="l">Live LLM surfaces</div></div>
  <div class="stat"><div class="n">21</div><div class="l">Background agents</div></div>
  <div class="stat"><div class="n">5</div><div class="l">Fivetran-synced tables</div></div>
  <div class="stat"><div class="n">1</div><div class="l">Operator (me)</div></div>
</div>

<h2>The architecture, in four layers</h2>
<div class="arch">
  <div class="layer">
    <div class="layer-name">Source data</div>
    <div class="layer-headline">Inventory + market signal</div>
    <ul>
      <li><b>CollX Pro</b> — system of record for card inventory (CSV export, no public API)</li>
      <li><b>SportsCardsPro / PriceCharting</b> — paid pricing guide, "actual" price</li>
      <li><b>Pokemon TCG API</b> — free fallback for TCG cards</li>
      <li><b>eBay Trading + Finding + Browse APIs</b> — listing CRUD, sold history, market read</li>
    </ul>
  </div>
  <div class="layer">
    <div class="layer-name">Data pipeline</div>
    <div class="layer-headline">Warehouse + transforms</div>
    <ul>
      <li><b>Fivetran Connector SDK</b> — custom connector, syncs 5 eBay tables (listings, performance, orders, promoted, seller standards)</li>
      <li><b>DuckDB</b> — local analytical warehouse the dashboard reads</li>
      <li><b>Python adapters</b> — CollX CSV ingest, multi-source pricing fusion</li>
    </ul>
  </div>
  <div class="layer">
    <div class="layer-name">Intelligence</div>
    <div class="layer-headline">Claude + deterministic agents</div>
    <ul>
      <li><b>Anthropic Claude</b> — Opus 4.7 (buyer chat), Sonnet 4 (listing optimizer), Sonnet 4.6 / Haiku 4.5 (mobile vision scanner)</li>
      <li><b>21 Python agents</b> — repricing, best-offer auto-respond, Cassini scoring, photo audit, promoted-listings tiering, relist, daily digest</li>
      <li><b>Pillow</b> — photo quality checks</li>
    </ul>
  </div>
  <div class="layer">
    <div class="layer-name">Surfaces</div>
    <div class="layer-headline">Where it touches the world</div>
    <ul>
      <li><b>AWS Lambda + API Gateway</b> — backend for AI chat + Trading API writes</li>
      <li><b>GitHub Pages</b> — public buyer-facing storefront (Python static-site generator, ~10K LOC)</li>
      <li><b>Expo / React Native</b> — mobile companion app (Claude vision scanner; paused)</li>
      <li><b>eBay Seller Hub + Store</b> — the actual marketplace</li>
    </ul>
  </div>
</div>

<h2>The three places where Claude actually generates</h2>
<table class="surfaces">
<thead><tr><th style="width:22%">Surface</th><th style="width:16%">Model</th><th>Job</th></tr></thead>
<tbody>
<tr><td class="s">Buyer-site chat</td><td class="m">claude-opus-4-7</td><td>Lambda route serves a chat widget that knows my store, policies, and persona context. Positioned where buyers stall — choosing between similar cards, asking about combined shipping.</td></tr>
<tr><td class="s">Listing optimizer</td><td class="m">claude-sonnet-4</td><td>One button on the dashboard. Takes a title + CTR + impressions, returns diagnosis, rewritten title, rewritten description, action list. Streams via SSE so the diagnosis renders first.</td></tr>
<tr><td class="s">Mobile vision scanner</td><td class="m">sonnet-4-6 / haiku-4-5</td><td>Snap a card, get strict JSON back — name, set, number, rarity, foil, condition hints. Output drops into the same inventory schema the Python pipeline reads.</td></tr>
</tbody>
</table>

<h2>The AI morning routine</h2>
<p>Every morning I run one command. It puts all 21 agents through their paces in <b>dry-run mode</b>, reads my live eBay data, and prints a single table of what each agent <i>would</i> do plus the dollar impact. I review it over coffee, then approve the agents I want to apply. Nothing writes to eBay without an explicit per-agent confirmation.</p>
<div class="morning">
  <div class="prompt"><span class="dollar">$</span>harpua-daily</div>
  <table class="plan-table">
    <thead><tr><th style="width:30%">Agent</th><th>Planned actions</th><th style="width:20%; text-align:right;">$ impact</th></tr></thead>
    <tbody>
      <tr><td class="agent">repricing</td><td>Raise 8, lower 12, hold 87</td><td class="dollars">+$24 / wk</td></tr>
      <tr><td class="agent">best_offer_autorespond</td><td>Accept 3, counter 4, decline 1</td><td class="dollars">+$67 today</td></tr>
      <tr><td class="agent">watchers_offer</td><td>Proactive offers to 14 watchers</td><td class="dollars">+$112 est</td></tr>
      <tr><td class="agent">promoted_listings</td><td>Bump 9 to AGGRESSIVE tier, drop 3 to LOW</td><td class="dollars">ad rate &uarr;</td></tr>
      <tr><td class="agent">cassini_score</td><td>7 below ranking floor (photos, specifics)</td><td class="dollars">+rank</td></tr>
      <tr><td class="agent">relist</td><td>5 ended unsold &mdash; ready to relist</td><td class="dollars">&mdash;</td></tr>
      <tr><td class="agent">photo_audit</td><td>12 listings below resolution gate</td><td class="dollars">+$8 / listing</td></tr>
      <tr><td class="agent">price_drops</td><td>14 cards drifted &gt;15% from sold median</td><td class="dollars">&mdash;</td></tr>
      <tr><td class="agent">email_campaign</td><td>"Steals" newsletter ready (38 cards)</td><td class="dollars">+$200 est</td></tr>
      <tr><td class="agent">repeat_buyers, daily_digest, &hellip;</td><td>(12 more agents, all dry-run)</td><td class="dollars">&mdash;</td></tr>
    </tbody>
  </table>
  <div class="footer-line"><span class="ask">Apply? &nbsp; repricing? </span><span class="yes">yes</span><span class="ask"> &nbsp; best_offer? </span><span class="yes">yes</span><span class="ask"> &nbsp; promoted_listings? </span>no<span class="ask"> &nbsp;&hellip;</span></div>
</div>
<p>What used to be an hour of manual triage in Seller Hub is now a 5-minute table review. The agents don't decide what gets shipped &mdash; I do &mdash; but they do the surveying, scoring, and option generation that would otherwise eat the morning.</p>

<h2>Why this combination is different</h2>
<div class="unique">
  <div class="pt">
    <div class="pt-head">Hybrid intelligence, on purpose</div>
    <div class="pt-body">LLMs run only where judgment beats rules. Everything else is deterministic Python with explicit math. Lower cost, higher predictability, easier debugging — and you don't end up explaining hallucinated prices to angry buyers.</div>
  </div>
  <div class="pt">
    <div class="pt-head">Three safety gates before every write</div>
    <div class="pt-body">Dry-run by default, written plan emitted as JSON + HTML for review, then typed "yes" confirmation per agent. Three layers between an LLM/agent and a real eBay listing or someone's credit card.</div>
  </div>
  <div class="pt">
    <div class="pt-head">Multi-agent fan-out for development</div>
    <div class="pt-body">Building features means launching 4-6 specialist Claude Code agents in parallel — reseller persona, mobile-UX critic, API-risk reviewer — and aggregating their findings into one ship. Velocity without thrash.</div>
  </div>
  <div class="pt">
    <div class="pt-head">Persistent project memory</div>
    <div class="pt-body">Project goal, agent catalog, audit findings, working cadence, slang preferences — all written to a memory layer the AI loads on every session. Never starts from zero. The system retains operator context.</div>
  </div>
  <div class="pt">
    <div class="pt-head">A real data pipeline, not a vibe</div>
    <div class="pt-body">Custom Fivetran connector backing a DuckDB warehouse. Multi-source pricing fusion across four vendors. Cassini-score model built from observable eBay signals. The "AI" sits on top of an actual data foundation.</div>
  </div>
  <div class="pt">
    <div class="pt-head">One-operator scale</div>
    <div class="pt-body">A single human plus this stack ships at the pace of a small team. The system isn't aspirational — it's running daily, gating real writes to a real production store. The infrastructure IS the team.</div>
  </div>
</div>

<div class="cta">
  <div class="cta-eyebrow">See it running</div>
  <div class="cta-head">Shop the store this <em>was built for</em>.</div>
  <div class="cta-deck">Sports cards (mostly football and Pokemon), aggressively priced, free combined shipping. The infrastructure above is what keeps the lights on.</div>
  <a class="cta-link" href="{EBAY_STORE_URL}">{EBAY_STORE_URL}</a>
</div>

<div class="footnote">
Built with Anthropic Claude (Opus 4.7, Sonnet 4, Haiku 4.5) and Claude Code &middot; AWS Lambda &middot; Fivetran Connector SDK &middot; DuckDB &middot; CollX Pro &middot; SportsCardsPro &middot; eBay Developer APIs &middot; GitHub Pages &middot; {DATE_STAMP} &middot; Jason Chletsos
</div>

</div>
</body>
</html>
"""


def render_pdf(html_template: str, html_path: Path, pdf_path: Path) -> None:
    html = (html_template
            .replace("{DATE_STAMP}", date.today().isoformat())
            .replace("{EBAY_STORE_URL}", EBAY_STORE_URL))
    html_path.write_text(html, encoding="utf-8")
    chrome = find_chrome()
    cmd = [
        chrome,
        "--headless=new",
        "--disable-gpu",
        "--no-sandbox",
        "--no-pdf-header-footer",
        "--virtual-time-budget=8000",
        f"--print-to-pdf={pdf_path}",
        f"file://{html_path.resolve()}",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if proc.returncode != 0 or not pdf_path.is_file():
        print("Chrome stdout:", proc.stdout[:400])
        print("Chrome stderr:", proc.stderr[:400])
        raise SystemExit(f"PDF generation failed for {pdf_path}")


def build_exec() -> None:
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    html_path = DOCS_DIR / "harpua_ai_overview.html"
    pdf_path  = DOCS_DIR / "harpua_ai_overview.pdf"
    render_pdf(HTML_EXEC, html_path, pdf_path)
    size_kb = pdf_path.stat().st_size // 1024
    print(f"  exec -> {pdf_path} ({size_kb} KB)")
    down = DOWNLOADS / "harpua_ai_overview.pdf"
    shutil.copy2(pdf_path, down)
    print(f"        + {down}")


def build_linkedin() -> None:
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    # Render HTML inside docs/ (so relative font URLs resolve), but only ship
    # the PDF to ~/Downloads — this variant is not linked from the site.
    html_path = DOCS_DIR / "harpua_ai_overview_linkedin.html"
    pdf_path  = DOWNLOADS / "harpua_ai_overview_linkedin.pdf"
    render_pdf(HTML_LINKEDIN, html_path, pdf_path)
    size_kb = pdf_path.stat().st_size // 1024
    print(f"  linkedin -> {pdf_path} ({size_kb} KB)")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--audience", choices=["exec", "linkedin", "both"], default="exec")
    args = ap.parse_args()

    print(f"Audience: {args.audience}")
    if args.audience in ("exec", "both"):
        build_exec()
    if args.audience in ("linkedin", "both"):
        build_linkedin()
    return 0


if __name__ == "__main__":
    sys.exit(main())
