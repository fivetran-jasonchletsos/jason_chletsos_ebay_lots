"""
build_hol_walkthrough_pdfs.py — generate two PDFs for the dbt Wizard HOL
no-typing-pattern showcase:

  1. dbt_wizard_hol_walkthrough_scenario2.pdf
     A panel-by-panel mockup of what a participant sees going through
     scenario-2 with the new "next" advancement pattern. Demonstrates that
     the only thing they type is the skill invocation + the word "next".

  2. dbt_wizard_hol_prompts_overview.pdf
     A printable cheat-sheet listing every canonical prompt across all four
     scenarios so an instructor (or a participant who wants to know what's
     actually being asked) can scan all 20+ prompts at once.

Both drop in ~/Downloads. Matches the brand styling of build_ai_overview.py
and build_hol_script_explainer.py.
"""
from __future__ import annotations

import subprocess
import sys
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).parent
DOCS_DIR  = REPO_ROOT / "docs"
DOWNLOADS = Path.home() / "Downloads"

WALK_HTML = DOCS_DIR / "hol_walkthrough_scenario2.html"
WALK_PDF  = DOWNLOADS / "dbt_wizard_hol_walkthrough_scenario2.pdf"
OVER_HTML = DOCS_DIR / "hol_prompts_overview.html"
OVER_PDF  = DOWNLOADS / "dbt_wizard_hol_prompts_overview.pdf"

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
    raise SystemExit("No Chrome/Chromium/Edge/Brave found.")


# --------------------------------------------------------------------------- #
# Shared CSS                                                                  #
# --------------------------------------------------------------------------- #

CSS = """
  @page { size: Letter; margin: 0.55in 0.5in 0.5in 0.5in; }
  html, body {
    margin: 0; padding: 0;
    font-family: 'Inter', -apple-system, system-ui, sans-serif;
    font-size: 10pt; line-height: 1.45;
    color: #1a1814; background: #faf7f1;
  }
  .wrap { padding: 0 0 22pt 0; }
  header { border-bottom: 2px solid #c9a44a; padding-bottom: 12pt; margin-bottom: 14pt; }
  .eyebrow {
    font-family: 'Inter', sans-serif; font-size: 8pt; font-weight: 700;
    letter-spacing: 0.22em; text-transform: uppercase; color: #8a6d2e;
  }
  h1 {
    font-family: 'Fraunces', Georgia, serif;
    font-variation-settings: 'opsz' 144, 'SOFT' 30;
    font-weight: 600; font-style: italic;
    font-size: 23pt; line-height: 1.1; letter-spacing: -0.01em;
    margin: 5pt 0 5pt 0; color: #1a1814;
  }
  .deck { font-size: 10.5pt; color: #4a4438; max-width: 540pt; margin: 0; }
  h2 {
    font-family: 'Fraunces', Georgia, serif;
    font-variation-settings: 'opsz' 144;
    font-weight: 700; font-size: 14pt; letter-spacing: -0.005em;
    margin: 14pt 0 6pt 0; color: #1a1814;
    border-top: 1px solid #d8cfb8; padding-top: 10pt;
  }
  h2:first-of-type { border-top: 0; padding-top: 0; margin-top: 4pt; }
  p { margin: 0 0 7pt 0; }
  code, .mono {
    font-family: 'SF Mono', ui-monospace, Menlo, monospace;
    font-size: 9pt; background: #f1ead7; padding: 1pt 4pt; border-radius: 2pt;
    color: #4a3a14;
  }
  .key {
    display: inline-block;
    font-family: 'SF Mono', ui-monospace, Menlo, monospace;
    font-size: 10pt; font-weight: 600;
    padding: 2pt 8pt; border-radius: 4pt;
    background: #1a1814; color: #c9a44a;
    border: 1px solid #c9a44a;
  }
  .footnote {
    font-size: 8pt; color: #6c5a2e; margin-top: 12pt;
    border-top: 1px solid #d8cfb8; padding-top: 6pt;
  }
"""

# --------------------------------------------------------------------------- #
# Walkthrough PDF — scenario 2 panels                                         #
# --------------------------------------------------------------------------- #

WALK_CSS_EXTRA = """
  .tldr {
    background: #fff;
    border: 1px solid #d8cfb8;
    border-left: 3pt solid #c9a44a;
    padding: 10pt 14pt;
    margin: 8pt 0 12pt 0;
    border-radius: 2pt;
  }
  .panel {
    margin: 10pt 0;
    page-break-inside: avoid;
  }
  .panel-num {
    font-family: 'Inter', sans-serif;
    font-size: 7.5pt; font-weight: 700; letter-spacing: 0.18em;
    text-transform: uppercase; color: #8a6d2e;
    margin-bottom: 4pt;
  }
  .user-line {
    margin: 4pt 0 6pt 0; padding: 6pt 12pt;
    background: #1a1814; color: #faf7f1; border-radius: 4pt;
    font-family: 'SF Mono', ui-monospace, Menlo, monospace;
    font-size: 9.5pt;
    display: inline-block;
    border-left: 3pt solid #c9a44a;
  }
  .user-line .label { color: #c9a44a; font-weight: 700; margin-right: 6pt; font-size: 8pt; letter-spacing: 0.16em; text-transform: uppercase; }
  .wizard-block {
    background: #fff;
    border: 1px solid #d8cfb8;
    border-left: 3pt solid #1a1814;
    padding: 8pt 12pt;
    margin: 6pt 0;
    border-radius: 2pt;
    font-size: 9.5pt;
  }
  .wizard-block .label {
    font-family: 'Inter', sans-serif;
    font-size: 7.5pt; font-weight: 700; letter-spacing: 0.16em;
    text-transform: uppercase; color: #6c5a2e;
    margin-bottom: 3pt;
  }
  .wizard-block .auto-prompt {
    font-family: 'SF Mono', ui-monospace, Menlo, monospace;
    font-size: 9pt; line-height: 1.45;
    background: #f1ead7; padding: 6pt 8pt; border-radius: 2pt;
    color: #4a3a14;
    margin: 3pt 0 5pt 0;
  }
  .wizard-block .summary {
    color: #2c2820; margin: 4pt 0 4pt 0; font-size: 9.5pt;
  }
  .wizard-block .footer-line {
    margin-top: 6pt; font-size: 8.5pt; color: #6c5a2e;
    font-family: 'SF Mono', ui-monospace, Menlo, monospace;
    background: #f8f1de; padding: 4pt 8pt; border-radius: 2pt;
  }
  .wizard-block .footer-line .b { color: #1a1814; font-weight: 700; }
  .stat-strip {
    display: grid; grid-template-columns: repeat(3, 1fr); gap: 8pt;
    margin: 6pt 0 10pt 0;
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
    font-size: 7.5pt; font-weight: 700; letter-spacing: 0.16em;
    text-transform: uppercase; margin-top: 3pt; color: #faf7f1; opacity: 0.85;
  }
"""

SCENARIO_2_PANELS = [
    {
        "step": 1,
        "title": "Locate the target model",
        "user_typed": "start scenario 2",
        "user_label": "User types (once, to invoke the skill)",
        "auto_prompt": "I need to add support-ticket context to enriched orders without breaking downstream consumers. Find int_orders_enriched in this project. Show me what it currently produces, its grain, and which models depend on it downstream.",
        "summary": "dbt Wizard searches the project, surfaces int_orders_enriched, shows its grain (one row per order) and the downstream models that depend on it.",
        "next_step": 2,
        "next_prompt": "Describe stg_tickets. Show me the columns, their types, the grain, and how order_id joins back to int_orders_enriched.",
    },
    {
        "step": 2,
        "title": "Discover the unused source",
        "user_typed": "[enter]",
        "user_label": "User presses",
        "auto_prompt": "Describe stg_tickets. Show me the columns, their types, the grain, and how order_id joins back to int_orders_enriched.",
        "summary": "Wizard returns the stg_tickets schema and confirms the order_id join key exists. Now the participant knows tickets can be wired in.",
        "next_step": 3,
        "next_prompt": "Run a quick check: count rows in stg_tickets with a non-null order_id, count distinct ticket order_ids, and count how many of those order_ids match an order_id in int_orders_enriched. Tell me whether stg_tickets is one-to-one or one-to-many at the order grain.",
    },
    {
        "step": 3,
        "title": "Validate the join",
        "user_typed": "[enter]",
        "user_label": "User presses",
        "auto_prompt": "Run a quick check: count rows in stg_tickets, count distinct ticket order_ids, count matching order_ids in int_orders_enriched. Tell me whether stg_tickets is one-to-one or one-to-many at the order grain.",
        "summary": "Wizard runs the validation. Participant learns stg_tickets is one-to-many (multiple tickets per order), so aggregation will be required before joining.",
        "next_step": 4,
        "next_prompt": "Update int_orders_enriched to add ticket_count, has_open_ticket_flag, and last_ticket_status from stg_tickets. Aggregate stg_tickets to one row per order_id before joining. Use a LEFT JOIN so orders without tickets still appear.",
    },
    {
        "step": 4,
        "title": "Modify the existing model",
        "user_typed": "[enter]",
        "user_label": "User presses",
        "auto_prompt": "Update int_orders_enriched to add ticket_count, has_open_ticket_flag, and last_ticket_status from stg_tickets. Aggregate to one row per order_id. LEFT JOIN. Preserve every existing column.",
        "summary": "Wizard writes the SQL that extends int_orders_enriched. The participant sees the diff but nothing is materialized yet.",
        "next_step": 5,
        "next_prompt": "Compile int_orders_enriched and every downstream model that depends on it. Then preview 20 rows of int_orders_enriched ordered deterministically by order_id. Do not materialize anything.",
    },
    {
        "step": 5,
        "title": "Compile downstream + safe preview",
        "user_typed": "[enter]",
        "user_label": "User presses",
        "auto_prompt": "Compile int_orders_enriched and every downstream model that depends on it. Then preview 20 rows of int_orders_enriched ordered deterministically by order_id. Do not materialize anything.",
        "summary": "Wizard compiles, runs a dry preview. Downstream is confirmed unbroken. Participant sees the new ticket columns in the preview rows.",
        "next_step": 6,
        "next_prompt": "Materialize int_orders_enriched into my dev schema. Skip the verification pass — the preview and downstream compile already confirmed the output.",
    },
    {
        "step": 6,
        "title": "Materialize",
        "user_typed": "[enter]",
        "user_label": "User presses",
        "auto_prompt": "Materialize int_orders_enriched into my dev schema. Skip the verification pass — the preview and downstream compile already confirmed the output.",
        "summary": "Wizard materializes into the participant's dev schema. The scenario is complete. Total participant typing: one invocation, then five enter keypresses.",
        "next_step": None,
        "next_prompt": None,
    },
]

# Guardrail demo panel — shown after the main flow to demonstrate what happens
# when a participant tries to type something off-script.
GUARDRAIL_PANEL = {
    "step": "Guardrail",
    "title": "What happens if a participant types something else",
    "user_typed": "what is the order table?",
    "user_label": "User types (off-script)",
    "auto_prompt": "(blocked — Wizard does not run an off-script query)",
    "summary": "Wizard responds with a single line: \"This lab runs on a fixed script. Press enter to continue to the next step. The instructor will pause the lab if you have a question.\" — and re-displays the current pending canonical prompt.",
    "next_step": None,
    "next_prompt": None,
}

def render_walkthrough_html() -> str:
    panels_html = []
    for p in SCENARIO_2_PANELS:
        footer_html = ""
        if p["next_step"] and p["next_prompt"]:
            footer_html = f"""
        <div class="footer-line">
          <b>Step {p['step']} complete.</b> Press <b>enter</b> to continue to Step {p['next_step']}.<br><br>
          Step {p['next_step']}: <span style="display:block; margin-top:3pt;">{p['next_prompt']}</span>
        </div>"""
        else:
            footer_html = """
        <div class="footer-line">
          <b>Scenario complete.</b> Final model materialized in your dev schema.
        </div>"""
        panels_html.append(f"""
    <div class="panel">
      <div class="panel-num">Panel {p['step']} &middot; Step {p['step']} &mdash; {p['title']}</div>
      <div class="user-line"><span class="label">{p['user_label']}</span>{p['user_typed']}</div>
      <div class="wizard-block">
        <div class="label">dbt Wizard auto-runs:</div>
        <div class="auto-prompt">{p['auto_prompt']}</div>
        <div class="summary"><i>What participant sees:</i> {p['summary']}</div>{footer_html}
      </div>
    </div>""")

    # Append the guardrail demo panel
    g = GUARDRAIL_PANEL
    panels_html.append(f"""
    <div class="panel">
      <div class="panel-num">Panel {g['step']} &middot; {g['title']}</div>
      <div class="user-line"><span class="label">{g['user_label']}</span>{g['user_typed']}</div>
      <div class="wizard-block">
        <div class="label">dbt Wizard refuses:</div>
        <div class="auto-prompt">{g['auto_prompt']}</div>
        <div class="summary"><i>What participant sees:</i> {g['summary']}</div>
      </div>
    </div>""")

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>dbt Wizard HOL — Scenario 2 walkthrough (no-typing path)</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,400;9..144,600;9..144,800&family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>{CSS}{WALK_CSS_EXTRA}</style>
</head>
<body>
<div class="wrap">

<header>
  <div class="eyebrow">dbt Wizard HOL &middot; Scenario 2 walkthrough</div>
  <h1>What participants see &mdash; <i>locked to the script</i>.</h1>
  <p class="deck">A panel-by-panel mockup of scenario 2 (extending int_orders_enriched with support-ticket context) using the locked-down advancement pattern. Participants invoke the skill once, then press <span class="key">enter</span> between steps. Anything else is refused.</p>
</header>

<div class="stat-strip">
  <div class="stat"><div class="n">1</div><div class="l">Skill invocation</div></div>
  <div class="stat"><div class="n">5</div><div class="l">Enter keypresses</div></div>
  <div class="stat"><div class="n">0</div><div class="l">Off-script questions accepted</div></div>
</div>

<div class="tldr">
<p><b>Before:</b> participants had to triple-click, copy, and paste each multi-sentence canonical prompt, or retype it. Typos and partial pastes caused dbt Wizard to misinterpret intent. <b>After:</b> the skill auto-runs Step 1 on invocation. Pressing <span class="key">enter</span> is the only way to advance. Any other input is refused with a single redirect line — Wizard will not go off-script. The instructor pauses the lab if a participant has a question.</p>
</div>

{''.join(panels_html)}

<div class="footnote">
Pattern applies to all four scenarios + onboarding. The five SKILL.md files have been updated locally. Source paths: <code>skills/onboarding/SKILL.md</code>, <code>skills/scenario-1/SKILL.md</code>, <code>skills/scenario-2/SKILL.md</code>, <code>skills/scenario-3/SKILL.md</code>, <code>skills/scenario-4/SKILL.md</code> &middot; Generated {{DATE_STAMP}}.
</div>

</div>
</body>
</html>"""

# --------------------------------------------------------------------------- #
# Overview PDF — all prompts across scenarios                                 #
# --------------------------------------------------------------------------- #

OVER_CSS_EXTRA = """
  .how {
    background: #fff;
    border: 1px solid #d8cfb8;
    border-left: 3pt solid #c9a44a;
    padding: 10pt 14pt;
    margin: 8pt 0 14pt 0;
    border-radius: 2pt;
  }
  .scenario {
    margin-top: 12pt;
    page-break-inside: avoid;
  }
  .scenario-head {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    border-bottom: 1px solid #c9a44a;
    padding-bottom: 4pt;
    margin-bottom: 8pt;
  }
  .scenario-name {
    font-family: 'Fraunces', Georgia, serif;
    font-variation-settings: 'opsz' 144;
    font-weight: 700; font-style: italic; font-size: 14pt; color: #1a1814;
  }
  .scenario-meta {
    font-family: 'SF Mono', ui-monospace, Menlo, monospace;
    font-size: 8pt; color: #8a6d2e;
  }
  .prompt-row {
    display: grid;
    grid-template-columns: 28pt 1fr;
    gap: 8pt;
    margin-bottom: 6pt;
    padding-bottom: 6pt;
    border-bottom: 1px dashed #e6ddc4;
  }
  .prompt-row:last-child { border-bottom: 0; }
  .prompt-num {
    font-family: 'Fraunces', Georgia, serif; font-variation-settings: 'opsz' 144;
    font-weight: 700; font-style: italic; font-size: 14pt; color: #8a6d2e;
    line-height: 1;
  }
  .prompt-body {
    font-size: 9pt; line-height: 1.45;
  }
  .prompt-head {
    font-family: 'Inter', sans-serif; font-size: 8pt; font-weight: 700;
    letter-spacing: 0.16em; text-transform: uppercase; color: #6c5a2e;
    margin-bottom: 2pt;
  }
  .prompt-text {
    font-family: 'SF Mono', ui-monospace, Menlo, monospace;
    font-size: 8.5pt; color: #2c2820;
    background: #f8f1de; padding: 4pt 8pt; border-radius: 2pt;
  }
"""

SCENARIOS = [
    {
        "name": "Onboarding",
        "summary": "New analytics engineer onboarding — get oriented in the dbt project.",
        "prompts": [
            ("Project summary", "I'm a new analytics engineer onboarding to this project. Give me a one-paragraph summary of what this dbt project does."),
            ("By-domain inventory", "List the staging, intermediate, and mart models broken out by domain so I know what's where."),
            ("Mart lineage and grain", "Show me the lineage, grain, and key columns of the orders mart."),
            ("Sample + distinct values", "Show me a 10-row sample of the orders mart and the distinct values for status and channel."),
            ("Tests and contracts", "What tests and contracts are defined on the orders model? Any currently failing tests?"),
            ("Create new mart", "Create a new mart model called orders_by_week that rolls orders up to weekly grain by store."),
            ("Compile and preview", "Compile and preview orders_by_week. Don't materialize it."),
        ],
    },
    {
        "name": "Scenario 1 — Inventory misallocation",
        "summary": "Investigate why stores received the wrong inventory before a sale.",
        "prompts": [
            ("Discovery", "Operations thinks inventory was misallocated across stores before a sale. Find the models in this project related to inventory, stores, items, and shipments."),
            ("Grain + joins", "For those models, show the grain, key columns, and how they join together."),
            ("Item-specific check", "Check the shipment plan versus on-hand inventory for our top SKUs and surface the stores where actual deviates most from plan."),
            ("Create variance model", "Create a dbt model named inventory_shipment_variance that compares planned versus actual at the store-item grain and labels each row over, under, or on-target."),
            ("Compile + preview", "Compile the model and preview the first 20 rows ordered deterministically by variance magnitude."),
            ("Materialize safely", "Before materializing, confirm the active dbt target is my dev schema. Then materialize inventory_shipment_variance."),
        ],
    },
    {
        "name": "Scenario 2 — Extend orders with tickets",
        "summary": "Wire support tickets into int_orders_enriched without breaking downstream.",
        "prompts": [
            ("Locate target model", "I need to add support-ticket context to enriched orders without breaking downstream consumers. Find int_orders_enriched in this project. Show me what it currently produces, its grain, and which models depend on it downstream."),
            ("Discover unused source", "Find every support-ticket source or model in this project that int_orders_enriched does NOT currently reference."),
            ("Describe stg_tickets", "Describe stg_tickets. Show me the columns, their types, the grain, and how order_id joins back to int_orders_enriched."),
            ("Validate the join", "Run a quick check: count rows in stg_tickets with a non-null order_id, count distinct ticket order_ids, and count how many match int_orders_enriched. One-to-one or one-to-many?"),
            ("Modify the model", "Update int_orders_enriched to add ticket_count, has_open_ticket_flag, last_ticket_status from stg_tickets. Aggregate to one row per order_id first. LEFT JOIN. Preserve every existing column."),
            ("Compile + preview", "Compile int_orders_enriched and every downstream model that depends on it. Then preview 20 rows ordered by order_id. Do not materialize anything."),
            ("Materialize", "Materialize int_orders_enriched into my dev schema."),
        ],
    },
    {
        "name": "Scenario 3 — Schema breakage repair",
        "summary": "Upstream source column renamed; fix the staging model and validate blast radius.",
        "prompts": [
            ("Explain the failure", "My dbt run just failed after a product source schema change. Explain the failure and tell me which column changed."),
            ("Describe current source", "Describe the current schema of retail.RET_PRODUCTS, including column names and types."),
            ("Blast radius", "Show me every model, source definition, test, and YAML file that references the old column name."),
            ("Apply the fix", "Update stg_products to read brand_name (the new column) instead of the old name. Preserve every other column the model emits."),
            ("Compile + preview", "Compile stg_products and every downstream product model. Preview 20 rows of stg_products."),
        ],
    },
    {
        "name": "Scenario 4 — Customer segmentation",
        "summary": "Marketing-driven segmentation model built fresh on top of order activity.",
        "prompts": [
            ("Discovery", "Marketing needs a targeted customer segment based on recent purchase behavior by store. Find the models related to customers, stores, orders, order lines, products, and categories."),
            ("Grain + joins", "Show the grain and joins for those models."),
            ("Data inspection", "Check recent order dates and category values needed for a 180-day segmentation model."),
            ("Activity model", "Create a 180-day customer activity model by store."),
            ("Segment model", "Create a segment model for VIPs, big spenders, and category-loyal customers, built on top of the activity model."),
            ("Compile + preview", "Compile and preview the segment model. Exclude customers with no segment."),
            ("Materialize", "Materialize the segment model into my dev schema. Skip the verification pass — the preview already confirmed the output."),
        ],
    },
]

def render_overview_html() -> str:
    scenarios_html = []
    total_prompts = sum(len(s["prompts"]) for s in SCENARIOS)
    for s in SCENARIOS:
        rows = []
        for i, (head, body) in enumerate(s["prompts"], 1):
            rows.append(f"""
      <div class="prompt-row">
        <div class="prompt-num">{i}</div>
        <div class="prompt-body">
          <div class="prompt-head">{head}</div>
          <div class="prompt-text">{body}</div>
        </div>
      </div>""")
        scenarios_html.append(f"""
    <div class="scenario">
      <div class="scenario-head">
        <div class="scenario-name">{s['name']}</div>
        <div class="scenario-meta">{len(s['prompts'])} prompts</div>
      </div>
      <p style="font-size:9pt; color:#4a4438; margin:0 0 6pt 0;">{s['summary']}</p>{''.join(rows)}
    </div>""")

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>dbt Wizard HOL — Prompts overview</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,400;9..144,600;9..144,800&family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>{CSS}{OVER_CSS_EXTRA}</style>
</head>
<body>
<div class="wrap">

<header>
  <div class="eyebrow">dbt Wizard HOL &middot; Prompts overview</div>
  <h1>Every prompt participants will run &mdash; at a glance.</h1>
  <p class="deck">Five skills, {total_prompts} canonical prompts. Under the new advancement pattern, dbt Wizard runs each one automatically when the participant types <span class="key">next</span>. This sheet is the instructor reference (and a printable cheat sheet) for what's actually being executed under the hood.</p>
</header>

<div class="how">
<p style="margin:0;"><b>How participants advance.</b> They invoke the skill once (e.g., natural-language phrasing that matches the skill description). The skill auto-runs prompt 1. After each step Wizard prints a footer like <span class="mono">Step N complete. Press enter to continue.</span> The only input that advances is pressing <span class="key">enter</span> (sending an empty message). <b>Anything else is refused</b> with a single redirect line — Wizard will not run off-script queries. The instructor pauses the lab if a participant has a real question.</p>
</div>

{''.join(scenarios_html)}

<div class="footnote">
Source: <code>skills/&lt;name&gt;/SKILL.md</code> in <code>fivetran-jacklowery/dbt_wizard_hol</code>. SKILL.md files updated locally with the advancement pattern; not yet pushed. Generated {{DATE_STAMP}}.
</div>

</div>
</body>
</html>"""


def render_pdf(html: str, html_path: Path, pdf_path: Path) -> None:
    html = html.replace("{DATE_STAMP}", date.today().isoformat())
    html_path.write_text(html, encoding="utf-8")
    chrome = find_chrome()
    proc = subprocess.run(
        [
            chrome,
            "--headless=new",
            "--disable-gpu",
            "--no-sandbox",
            "--no-pdf-header-footer",
            "--virtual-time-budget=8000",
            f"--print-to-pdf={pdf_path}",
            f"file://{html_path.resolve()}",
        ],
        capture_output=True, text=True, timeout=60,
    )
    if proc.returncode != 0 or not pdf_path.is_file():
        print(f"Chrome stderr for {pdf_path.name}:", proc.stderr[:400])
        raise SystemExit(f"PDF generation failed: {pdf_path}")


def main() -> int:
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    render_pdf(render_walkthrough_html(), WALK_HTML, WALK_PDF)
    size_kb = WALK_PDF.stat().st_size // 1024
    print(f"  walkthrough -> {WALK_PDF} ({size_kb} KB)")
    render_pdf(render_overview_html(), OVER_HTML, OVER_PDF)
    size_kb = OVER_PDF.stat().st_size // 1024
    print(f"  overview    -> {OVER_PDF} ({size_kb} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
