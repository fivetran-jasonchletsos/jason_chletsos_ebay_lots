"""ODI demo build, planned across three 1-hour sessions (cold start, no prework).

Maps the ~3-hour odi-demo-builder flow onto 3 x 1hr boss sessions:
  S1 Foundation & first data  -> provision AWS lake, MDLS destination, OAuth connector, first sync
  S2 dbt pipeline             -> bronze/silver/gold models into gold Iceberg tables
  S3 Frontend + polish + tour -> React shell, frontend-design pass, Niraj content QA, demo tour

Reality baked in: on the demo machine AWS creds + the Fivetran API key are NOT yet
set, so S1 opens with a 5-minute access check and a no-AWS fallback. Boss is
hands-on; prompts are plain English. Multi-page so nothing is dropped.
Outputs to output/ and is copied to ~/Downloads (JC's standing pref).
"""
from pathlib import Path
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.lib.colors import HexColor
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Table,
                                TableStyle, KeepTogether)

REPO = Path(__file__).parent
OUT = REPO / "output/odi_demo_3session_plan.pdf"

INK = HexColor("#111111"); MID = HexColor("#444444")
ACCENT = HexColor("#1a5fb4"); BOX = HexColor("#eef3fb"); BORD = HexColor("#c7d6ee")
GREEN = HexColor("#1a7f47"); GBOX = HexColor("#e8f5ee"); GBORD = HexColor("#bfe2cd")
AMBER = HexColor("#8a5a00"); ABOX = HexColor("#fbf2dd"); ABORD = HexColor("#ecd9a6")
LINE = HexColor("#cccccc"); GREY = HexColor("#777777")

sesh = ParagraphStyle("sesh", fontName="Helvetica-Bold", fontSize=12.5, textColor=HexColor("#ffffff"),
                      backColor=ACCENT, borderPadding=5, spaceBefore=10, spaceAfter=5, leading=15)
h2   = ParagraphStyle("h2", fontName="Helvetica-Bold", fontSize=11, textColor=ACCENT,
                      spaceBefore=7, spaceAfter=4, leading=13)
body = ParagraphStyle("body", fontName="Helvetica", fontSize=9, textColor=INK, leading=12, spaceAfter=3)
small= ParagraphStyle("small", fontName="Helvetica", fontSize=8.3, textColor=MID, leading=10.5, spaceAfter=2)
plab = ParagraphStyle("plab", fontName="Helvetica-Bold", fontSize=9, textColor=ACCENT,
                      leading=11, spaceBefore=5, spaceAfter=1)
prompt = ParagraphStyle("prompt", fontName="Helvetica", fontSize=8.8, textColor=INK, leading=11.2,
                        backColor=BOX, borderColor=BORD, borderWidth=0.6, borderPadding=5, spaceAfter=2)
note = ParagraphStyle("note", fontName="Helvetica-Oblique", fontSize=8, textColor=MID, leading=10, spaceAfter=4)
done = ParagraphStyle("done", fontName="Helvetica-Bold", fontSize=8.8, textColor=GREEN, leading=11.5,
                      backColor=GBOX, borderColor=GBORD, borderWidth=0.6, borderPadding=5, spaceBefore=2, spaceAfter=4)
warn = ParagraphStyle("warn", fontName="Helvetica", fontSize=8.8, textColor=AMBER, leading=11.5,
                      backColor=ABOX, borderColor=ABORD, borderWidth=0.8, borderPadding=6, spaceBefore=2, spaceAfter=5)

def S(title):   return Paragraph(title, sesh)
def P(label, text, kind="prompt"):
    style = {"prompt": prompt, "done": done, "warn": warn}[kind]
    return KeepTogether([Paragraph(label, plab), Paragraph(text, style)])

flow = []

# ---------- ACCESS GATE ----------
flow.append(Paragraph("Session 1 opens with a 5-minute access check (these aren't set up yet)", h2))
flow.append(Paragraph(
    "<b>Do this first, or the AWS build can't start.</b> Tools (terraform, aws, jq, node, dbt) are already "
    "installed; access is not.<br/>"
    "&bull;&nbsp; <b>Fivetran:</b> log in, generate an API key, then in the terminal "
    "<code>export FIVETRAN_API_KEY=key:secret</code><br/>"
    "&bull;&nbsp; <b>AWS:</b> run <code>aws configure</code> (paste an admin access key + secret, or use SSO), "
    "confirm with <code>aws sts get-caller-identity</code><br/>"
    "&bull;&nbsp; <b>If either isn't available:</b> don't burn the hour fighting it. Pivot to touring a finished "
    "demo (dozens in <code>~/Documents/GitHub/*-ODI-Demo</code>) and locking the vertical/persona, then provision "
    "next session once access is sorted.", warn))

# ---------- CARRY BETWEEN SESSIONS ----------
flow.append(Paragraph("Carry between sessions (no prework assumed — re-establish at the top of each)", h2))
flow.append(Paragraph(
    "&bull;&nbsp; The <b>Fivetran API key</b> — the env var won't survive a new terminal, so re-export it each session "
    "(store it somewhere safe).<br/>"
    "&bull;&nbsp; The <b>demo directory path</b> Claude created, and your <b>AWS creds</b> (re-run aws configure if needed).<br/>"
    "&bull;&nbsp; The <b>group / connector / destination ids</b> — Claude can re-list these from the API if you lose them.", body))

# ---------- SESSION 1 ----------
flow.append(S("Session 1 (today) — Foundation &amp; first data"))
flow.append(Paragraph("Goal: AWS lake provisioned, MDLS destination + OAuth connector created, first sync started. "
                      "Lock the vertical, org name, and persona before you provision.", small))
flow.append(P("Kickoff",
    "Let's build a new ODI demo with the odi-demo-builder skill. Vertical: [VERTICAL]. Org name: [ORG]. Buyer "
    "persona: [PERSONA]. Nothing is provisioned yet — my AWS creds and $FIVETRAN_API_KEY are now set. Scaffold the "
    "Terraform for the S3 bucket, Glue bronze/silver/gold, and the Fivetran IAM role, and walk me through "
    "provisioning step by step."))
flow.append(P("Provision the lake",
    "Start the MDLS destination setup so we get the AWS account id and external id, put them into tfvars, then run "
    "terraform init and apply. Show me the bucket name and IAM role ARN outputs."))
flow.append(Paragraph("This is the handshake: you begin the destination in the Fivetran UI to get the external id, "
                      "paste it into tfvars, then apply the Terraform. Claude does the rest.", note))
flow.append(P("Create the destination",
    "Create the Managed Data Lake destination via the REST API using the terraform outputs (bucket, IAM role ARN, "
    "Glue bronze database) in us-east-1. Confirm the destination id and setup status."))
flow.append(P("OAuth connector",
    "Create the [source] connector in this group via the REST API, then generate a Fivetran Connect Card link and "
    "give me the URL so I can sign in with OAuth."))
flow.append(Paragraph("In the browser: open the Connect Card URL, sign in via OAuth, pick the data, click Save. "
                      "No passwords typed.", note))
flow.append(P("Test + sync",
    "Run the connector setup test (expect CONNECTED), then trigger the first sync and poll sync_state every 30 "
    "seconds until it's SYNCED. Tell me which tables landed."))
flow.append(P("Session 1 done",
    "Lake provisioned + connector authorized + first sync landing in the Iceberg lake. If AWS setup ran long, "
    "stopping after the destination/connector are created and the sync is triggered is a fine session 1 — verify "
    "and pick up at dbt next time.", "done"))

# ---------- SESSION 2 ----------
flow.append(S("Session 2 — dbt pipeline (bronze / silver / gold)"))
flow.append(Paragraph("Resume check: re-export FIVETRAN_API_KEY, confirm aws sts get-caller-identity works, and "
                      "confirm session 1's sync finished.", small))
flow.append(P("Resume",
    "Resume the ODI demo in [demo dir]. Verify the Fivetran sync completed and list the tables that landed in the "
    "Glue bronze database."))
flow.append(P("Scaffold dbt",
    "Scaffold the dbt project to the portfolio standard: bronze sources.yml from the synced tables, silver staging "
    "models, and one gold Iceberg fact/dimension. Apply Niraj's content rules — org name [ORG] everywhere, every "
    "connector gets its Fivetran deep link, no raw table names exposed."))
flow.append(P("dbt build",
    "Run dbt build --select bronze silver gold and confirm the gold Iceberg tables are created in the Glue catalog. "
    "If it fails, diagnose from the error before fixing."))
flow.append(P("Verify",
    "Show me a sample query against the gold tables through Athena so we can see the modeled data."))
flow.append(P("Session 2 done",
    "Working bronze/silver/gold pipeline, gold Iceberg tables queryable in the lake.", "done"))

# ---------- SESSION 3 ----------
flow.append(S("Session 3 — Frontend, polish &amp; demo tour"))
flow.append(Paragraph("Resume check: same env re-establish as session 2.", small))
flow.append(P("Frontend shell",
    "Generate the React frontend shell — a Landing page with the [ORG] hero and a pipeline diagram "
    "(Fivetran -> S3/Iceberg -> dbt -> Athena), and a Pipeline page listing the connector with its Fivetran deep link."))
flow.append(P("Design pass",
    "Run the frontend-design pass for the [VERTICAL] vertical and [PERSONA] buyer — distinctive look, no generic AI "
    "aesthetic, analytical charts instead of dense tables, no emojis."))
flow.append(P("Content QA",
    "Do a Niraj content QA pass: org name [ORG] in every title, H1, and navbar; no raw table names exposed; every "
    "connector shows its Fivetran deep link."))
flow.append(P("Tour",
    "Start the frontend and walk me through the demo end to end — landing, pipeline, the data in the lake."))
flow.append(P("Session 3 done",
    "Demo-ready ODI app: live connector, Iceberg lake, dbt pipeline, and a polished frontend you can present.", "done"))

# ---------- header / footer ----------
def header_footer(c, doc):
    w, h = letter
    c.saveState()
    if doc.page == 1:
        c.setFillColor(INK); c.setFont("Helvetica-Bold", 16)
        c.drawString(0.55*inch, h - 0.55*inch, "ODI Demo Build — 3-Session Plan (3 x 1 hour)")
        c.setFillColor(MID); c.setFont("Helvetica", 9)
        c.drawString(0.55*inch, h - 0.72*inch,
                     "Cold start, no prework. Boss hands-on, you drive the risky parts. Each session is "
                     "self-contained and resumable.")
        c.setStrokeColor(ACCENT); c.setLineWidth(1.2)
        c.line(0.55*inch, h - 0.80*inch, w - 0.55*inch, h - 0.80*inch)
    c.setFillColor(GREY); c.setFont("Helvetica-Oblique", 7.5)
    c.drawString(0.55*inch, 0.4*inch, "Fill in [VERTICAL] [ORG] [PERSONA] [source] before session 1  ·  green = stop here if time's up")
    c.drawRightString(w - 0.55*inch, 0.4*inch, f"page {doc.page}")
    c.restoreState()

doc = SimpleDocTemplate(str(OUT), pagesize=letter,
                        leftMargin=0.55*inch, rightMargin=0.55*inch,
                        topMargin=0.95*inch, bottomMargin=0.6*inch,
                        title="ODI Demo Build - 3-Session Plan")
doc.build(flow, onFirstPage=header_footer, onLaterPages=header_footer)
print(f"wrote {OUT}")
