"""ODI demo build — TRAINER'S GUIDE, for the facilitator (Jason), across 3 sessions.

Audience flip: this is for the person running the session, not the novice.
Jason narrates, pastes prompts into chat; the boss copies them into Claude Code
and clicks Allow. Each step has:
  Say:        a short talk track to read to the room
  PASTE:      the exact prompt (blue box) to hand over
  You watch:  trainer-only notes (grey box) — what's happening, what can break

Maps the ~3-hour odi-demo-builder flow onto 3 one-hour sessions:
  S1 Foundation & first data   S2 dbt pipeline   S3 Frontend + tour

Reality baked in: AWS creds + the Fivetran API key are NOT set on the machine,
so S1 has a pre-session access setup the trainer handles.

Shaded callouts are single-cell Tables (ReportLab doesn't reserve a bordered
Paragraph's top padding, which makes boxes overlap the heading above).
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

LM = RM = 0.55 * inch
CW = letter[0] - LM - RM

INK = HexColor("#111111"); MID = HexColor("#444444"); WHITE = HexColor("#ffffff")
ACCENT = HexColor("#1a5fb4"); BOX = HexColor("#eef3fb"); BORD = HexColor("#c7d6ee")
GREEN = HexColor("#1a7f47"); GBOX = HexColor("#e8f5ee"); GBORD = HexColor("#bfe2cd")
AMBER = HexColor("#8a5a00"); ABOX = HexColor("#fbf2dd"); ABORD = HexColor("#ecd9a6")
SLATE = HexColor("#33415c")
GREYBOX = HexColor("#f1f3f5"); GREYBORD = HexColor("#d4d9de"); LINE = HexColor("#cccccc"); GREY = HexColor("#777777")

h2   = ParagraphStyle("h2", fontName="Helvetica-Bold", fontSize=11, textColor=ACCENT, spaceBefore=9, spaceAfter=4, leading=13)
body = ParagraphStyle("body", fontName="Helvetica", fontSize=9, textColor=INK, leading=12.5, spaceAfter=4)
small= ParagraphStyle("small", fontName="Helvetica", fontSize=8.3, textColor=MID, leading=10.5, spaceAfter=2)
plab = ParagraphStyle("plab", fontName="Helvetica-Bold", fontSize=9.4, textColor=ACCENT, leading=11, spaceBefore=4, spaceAfter=2)
say  = ParagraphStyle("say", fontName="Helvetica", fontSize=9, textColor=SLATE, leading=12, spaceAfter=3, leftIndent=2)
sesh_t   = ParagraphStyle("sesh_t", fontName="Helvetica-Bold", fontSize=12.5, textColor=WHITE, leading=15)
prompt_t = ParagraphStyle("prompt_t", fontName="Helvetica", fontSize=9, textColor=INK, leading=11.6)
note_t   = ParagraphStyle("note_t", fontName="Helvetica", fontSize=8.3, textColor=MID, leading=10.8)
warn_t   = ParagraphStyle("warn_t", fontName="Helvetica", fontSize=8.8, textColor=AMBER, leading=11.6)
done_t   = ParagraphStyle("done_t", fontName="Helvetica-Bold", fontSize=8.8, textColor=GREEN, leading=11.5)


def boxed(para, bg, border, pad=7, space_before=3, space_after=6, line_w=0.6):
    t = Table([[para]], colWidths=[CW])
    style = [
        ("BACKGROUND", (0, 0), (-1, -1), bg), ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), pad), ("RIGHTPADDING", (0, 0), (-1, -1), pad),
        ("TOPPADDING", (0, 0), (-1, -1), pad), ("BOTTOMPADDING", (0, 0), (-1, -1), pad),
    ]
    if border is not None:
        style.append(("BOX", (0, 0), (-1, -1), line_w, border))
    t.setStyle(TableStyle(style))
    t.spaceBefore = space_before; t.spaceAfter = space_after
    return t


def band(title):
    return boxed(Paragraph(title, sesh_t), ACCENT, None, pad=6, space_before=12, space_after=6)


def STEP(label, say_text, prompt_text, watch):
    """One facilitated step: talk track, the paste prompt, and trainer notes."""
    return KeepTogether([
        Paragraph(label, plab),
        Paragraph('Say:&nbsp; &ldquo;' + say_text + '&rdquo;', say),
        boxed(Paragraph("PASTE &rarr; he enters this in Claude Code:<br/><br/>" + prompt_text, prompt_t),
              BOX, BORD, space_before=1, space_after=2),
        boxed(Paragraph("<b>You watch for:</b> " + watch, note_t), GREYBOX, GREYBORD, space_before=1, space_after=7),
    ])


def DONE(text):
    return boxed(Paragraph("SESSION DONE — " + text, done_t), GBOX, GBORD, space_before=3, space_after=6)


flow = []

# =========================================================
# how to run it (trainer)
# =========================================================
flow.append(Paragraph("How to run these sessions", h2))
flow.append(Paragraph(
    "You facilitate; he stays hands-on so he learns by doing. <b>You</b> handle every login, credential, and any "
    "red error. <b>He</b> pastes each prompt into Claude Code and clicks <b>Allow</b> when it asks. Read the "
    "<b>Say</b> line to frame each step, paste the blue prompt into chat for him to copy, and keep the grey notes "
    "to yourself. Pause whenever he's curious — letting him ask Claude <i>\"explain that like I'm new to this\"</i> "
    "is the best moment in the whole demo.", body))

flow.append(Paragraph("Lock these before session 1 (fill the blanks in every prompt below)", h2))
flow.append(Paragraph(
    "&bull;&nbsp; <b>[VERTICAL]</b> — the industry story (e.g. Banking, Insurance)<br/>"
    "&bull;&nbsp; <b>[ORG]</b> — a made-up demo company name (generic; must not collide with a real entity)<br/>"
    "&bull;&nbsp; <b>[PERSONA]</b> — who the demo is for (e.g. a risk analyst)<br/>"
    "&bull;&nbsp; <b>[source]</b> — the app to pull from with OAuth (e.g. Salesforce, HubSpot, Google)", body))

flow.append(Paragraph("Your pre-session setup (every session, ~3 min)", h2))
flow.append(boxed(Paragraph(
    "&bull;&nbsp; Fivetran API key in the shell: <code>export FIVETRAN_API_KEY=key:secret</code> "
    "(re-do each session — it doesn't survive a new terminal)<br/>"
    "&bull;&nbsp; AWS: <code>aws configure</code> then verify <code>aws sts get-caller-identity</code> "
    "(both are currently NOT set on this machine)<br/>"
    "&bull;&nbsp; Open the Fivetran dashboard and the AWS Glue/Athena console in browser tabs so he sees things appear live<br/>"
    "&bull;&nbsp; <b>If a login won't cooperate:</b> don't burn the session — have Claude tour a finished demo in "
    "<code>~/Documents/GitHub/*-ODI-Demo</code> and provision next time", warn_t), ABOX, ABORD, line_w=0.8))

flow.append(Paragraph("If he asks what something means — your one-line answers", h2))
gloss = [
    ("Connector", "An automatic pipe that pulls data out of an app for you."),
    ("OAuth", "The \"Sign in with Google/Salesforce\" button — he logs in, no passwords shared."),
    ("Sync", "The connector copying the data over for the first time."),
    ("Data lake / MDLS", "Cloud storage where all the data lands, in an open format anyone can read."),
    ("Iceberg", "The modern open table format the data is stored as in the lake."),
    ("AWS", "Amazon's cloud — S3 stores files, Glue lists tables, Athena queries, IAM is permissions."),
    ("Terraform", "A tool that builds the cloud pieces automatically from a script Claude writes."),
    ("dbt", "A tool that cleans and reshapes raw data into tidy tables for analysis."),
    ("Connect Card", "A Fivetran browser link he opens to log into the source app with OAuth."),
]
gdata = [[Paragraph(f"<b>{t}</b>", small), Paragraph(d, small)] for t, d in gloss]
gt = Table(gdata, colWidths=[1.35*inch, CW - 1.35*inch])
gt.setStyle(TableStyle([
    ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ("LINEBELOW", (0, 0), (-1, -2), 0.3, HexColor("#e3e3e3")),
    ("TOPPADDING", (0, 0), (-1, -1), 2.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
    ("LEFTPADDING", (0, 0), (0, -1), 0),
]))
flow.append(gt)

# =========================================================
# SESSION 1
# =========================================================
flow.append(band("Session 1 (today) — set up the cloud and pull in the data"))
flow.append(Paragraph("Your goal: AWS lake provisioned, source connected, first sync started. The Terraform step "
                      "is the slow/risky one — protect time for it.", small))

flow.append(STEP("Step 1 — kick off the build",
    "We tell Claude the whole goal and point it at a finished demo to copy the conventions from — then it lays out "
    "the plan before doing anything.",
    "Help me build an ODI demo from scratch — no special tooling, just you and me. End goal: an AWS Managed Data "
    "Lake destination in Fivetran, a source connector, synced data, a dbt bronze/silver/gold pipeline, and a small "
    "React web app. Use one of the finished demos in ~/Documents/GitHub/*-ODI-Demo as the reference pattern for "
    "structure and conventions. Vertical: [VERTICAL]. Org name: [ORG]. Buyer persona: [PERSONA]. My AWS and "
    "Fivetran logins are configured. Lay out the plan, then walk me through it step by step in plain language.",
    "No skill needed — Claude reads a sibling demo in ~/Documents/GitHub/*-ODI-Demo to mirror its structure "
    "(bronze/silver/gold, deep links, frontend), prints a plan, then starts scaffolding. Teaching moment: it's "
    "writing infrastructure-as-code itself."))

flow.append(STEP("Step 2 — build the cloud storage (the risky one)",
    "Now it builds the storage on AWS automatically — this is the part that normally takes a team a day.",
    "Scaffold the Terraform for the S3 bucket, the Glue databases, and the Fivetran IAM role, then walk me through "
    "applying it. Tell me when you need anything from me.",
    "The MDLS handshake: you start the destination in the Fivetran UI to get aws_account_id + external_id, paste "
    "them into tfvars, then it runs terraform apply (S3 + Glue + IAM). Most likely failure point: AWS perms or a "
    "stale external_id. Budget the most time here."))

flow.append(STEP("Step 3 — create the data lake destination",
    "We point Fivetran at the lake we just built.",
    "Create the Managed Data Lake destination via the REST API using the Terraform outputs, and show me it "
    "connected successfully.",
    "POST /v1/destinations; expect code Created. A permission error here almost always means the external_id in "
    "tfvars doesn't match the one from the destination setup UI."))

flow.append(STEP("Step 4 — connect the source app (OAuth)",
    "Now we connect the source app. You'll sign in the normal way in your browser — no passwords go into Claude.",
    "Create the [source] connector via the REST API, then give me a Fivetran Connect Card link so I can sign in "
    "with OAuth.",
    "Claude creates the connector and mints a Connect Card token; he opens the URL, does OAuth consent, picks "
    "tables, Saves. Teaching moment: OAuth shares access, not passwords. If your key lacks connect-card scope, "
    "finish auth in the Fivetran UI instead."))

flow.append(STEP("Step 5 — start the data flowing",
    "Last step for today — kick off the first sync and watch the data land.",
    "Run the connector setup test (expect CONNECTED), then trigger the first sync and poll until it's SYNCED. Tell "
    "me which tables landed.",
    "Keep the source selection small so this finishes fast. While it syncs, this is the spot for the Hybrid "
    "deployment talking point (agent runs in the customer's network; only metadata leaves)."))

flow.append(DONE("the cloud lake is live, the app is connected, and data is flowing in. If Terraform ran long, "
                 "stopping after the connector is created and the sync is triggered is a fine session 1."))

# =========================================================
# SESSION 2
# =========================================================
flow.append(band("Session 2 — shape the raw data into clean tables"))
flow.append(Paragraph("Your prep: re-export the Fivetran key, re-verify aws sts get-caller-identity, confirm "
                      "session 1's sync finished.", small))

flow.append(STEP("Step 1 — pick up where we left off",
    "Let's make sure last session's data actually arrived before we build on it.",
    "Resume the ODI demo we started. Confirm the Fivetran sync from last session finished and list the tables that "
    "landed in the Glue bronze database.",
    "Re-orients Claude to the demo dir and proves the bronze tables exist. If the sync wasn't finished last time, "
    "this is where it completes."))

flow.append(STEP("Step 2 — build the data pipeline",
    "Now we turn those raw tables into clean, business-ready ones — bronze, silver, gold.",
    "Build the dbt project the same way the reference demo does — bronze sources, silver staging models, and one "
    "gold Iceberg fact/dimension. Keep it customer-ready: use the [ORG] name in anything user-facing, never raw "
    "table names. Explain each layer in plain language.",
    "Content standards: [ORG] everywhere, every connector keeps its Fivetran deep link, no raw table names exposed. "
    "Mirror the reference demo's dbt layout. Confirm the dbt-athena env vars (LAKE_BUCKET, ATHENA_WORKGROUP) are set."))

flow.append(STEP("Step 3 — run it and check the result",
    "Run the pipeline and let's look at the finished data.",
    "Run dbt build --select bronze silver gold and confirm the gold Iceberg tables were created in Glue. If it "
    "fails, explain the error simply and fix it, then show me a sample of the gold data via Athena.",
    "Common build failures: wrong awsdatacatalog database ref in profiles.yml, missing Athena workgroup, or an IAM "
    "gap. Claude diagnoses from the error message."))

flow.append(DONE("raw data has been turned into clean, query-ready gold Iceberg tables. Strong stopping point."))

# =========================================================
# SESSION 3
# =========================================================
flow.append(band("Session 3 — build the web app and tour the demo"))
flow.append(Paragraph("Your prep: same quick restart — re-export the key, re-verify the AWS login.", small))

flow.append(STEP("Step 1 — generate the web app",
    "Now we put a face on it — a small web app that presents the whole pipeline.",
    "Generate the React frontend shell — a Landing page with the [ORG] hero and a data-flow diagram "
    "(Fivetran to S3/Iceberg to dbt to Athena), and a Pipeline page listing the connector with its Fivetran deep link. "
    "Match the layout of the reference demo's frontend.",
    "Produces the frontend/ shell. Connector entries must carry the Fivetran deep link per our content standard."))

flow.append(STEP("Step 2 — make it look sharp",
    "Let's give it a real, distinctive look instead of a generic template.",
    "Give the web app a distinctive, professional design for the [VERTICAL] industry and [PERSONA] audience — strong "
    "typography, a cohesive color system, analytical charts instead of dense tables, and none of the generic "
    "AI-template look. Match the polish of the reference demo.",
    "Direct design pass, no skill required. Strong wow moment for a novice — the before/after is dramatic."))

flow.append(STEP("Step 3 — final quality check",
    "Quick polish pass so nothing looks unfinished in front of an audience.",
    "Do a content QA pass: [ORG] in every title, H1, and navbar; no raw table names exposed anywhere; every "
    "connector shows its Fivetran deep link.",
    "Catches the content-standard misses that read as sloppy in a customer demo."))

flow.append(STEP("Step 4 — walk the demo",
    "And here's the finished product — let's walk it end to end.",
    "Start the frontend and give me a guided tour from start to finish — the landing page, the data flow, and the "
    "data in the lake.",
    "Opens the app and narrates it. This is the artifact he'd actually show a customer; let him drive the click-through."))

flow.append(DONE("a demo-ready ODI app: live connector, cloud data lake, clean dbt pipeline, and a polished web app."))

flow.append(Paragraph("If a session stalls (trainer triage)", h2))
flow.append(boxed(Paragraph(
    "Protect the CORE path over polish. Priority order if time runs short: data in the lake (S1) &gt; clean gold "
    "tables (S2) &gt; web app (S3). Every green box above is a clean place to stop and resume next time. If AWS "
    "fights you, fall back to touring a finished demo and provision next session — never spend more than ~15 min "
    "debugging credentials live in front of him.", note_t), GREYBOX, GREYBORD, line_w=0.6))


# ---------- header / footer ----------
def header_footer(c, doc):
    w, h = letter
    c.saveState()
    if doc.page == 1:
        c.setFillColor(INK); c.setFont("Helvetica-Bold", 16)
        c.drawString(LM, h - 0.55*inch, "ODI Demo Build — Trainer's Guide (3 sessions)")
        c.setFillColor(MID); c.setFont("Helvetica", 9)
        c.drawString(LM, h - 0.72*inch,
                     "For you, the facilitator. You narrate and paste the prompts into chat; he copies them into "
                     "Claude Code and clicks Allow.")
        c.setStrokeColor(ACCENT); c.setLineWidth(1.2)
        c.line(LM, h - 0.80*inch, w - RM, h - 0.80*inch)
    c.setFillColor(GREY); c.setFont("Helvetica-Oblique", 7.5)
    c.drawString(LM, 0.4*inch, "Grey boxes are your notes — don't read them aloud.   ·   green = a safe place to stop")
    c.drawRightString(w - RM, 0.4*inch, f"page {doc.page}")
    c.restoreState()


doc = SimpleDocTemplate(str(OUT), pagesize=letter, leftMargin=LM, rightMargin=RM,
                        topMargin=0.95*inch, bottomMargin=0.6*inch,
                        title="ODI Demo Build - Trainer's Guide")
doc.build(flow, onFirstPage=header_footer, onLaterPages=header_footer)
print(f"wrote {OUT}")
