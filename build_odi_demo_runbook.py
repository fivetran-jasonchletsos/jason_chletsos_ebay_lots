"""1-hour ODI demo build runbook for the boss session.

Goal: stand up a working ODI / Managed Data Lake demo with the odi-demo-builder
skill, getting as far as time allows. Strategy: pre-stage the slow/risky infra,
then run a CORE path (destination -> OAuth connector -> sync -> data in the
Iceberg lake) that yields a real demo by ~0:35, with dbt + frontend as stretch.

Boss is hands-on; prompts are plain English. Multi-page so nothing is dropped.
Outputs to output/ and is copied to ~/Downloads (JC's standing pref).
"""
from pathlib import Path
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.lib.colors import HexColor
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Table,
                                TableStyle, KeepTogether, HRFlowable)

REPO = Path(__file__).parent
OUT = REPO / "output/odi_demo_session_runbook.pdf"

INK = HexColor("#111111"); MID = HexColor("#444444")
ACCENT = HexColor("#1a5fb4"); BOX = HexColor("#eef3fb"); BORD = HexColor("#c7d6ee")
GREEN = HexColor("#1a7f47"); GBOX = HexColor("#e8f5ee"); GBORD = HexColor("#bfe2cd")
LINE = HexColor("#cccccc"); GREY = HexColor("#777777")

h2   = ParagraphStyle("h2", fontName="Helvetica-Bold", fontSize=12, textColor=ACCENT,
                      spaceBefore=8, spaceAfter=4, leading=14)
body = ParagraphStyle("body", fontName="Helvetica", fontSize=9, textColor=INK,
                      leading=12, spaceAfter=3)
small= ParagraphStyle("small", fontName="Helvetica", fontSize=8.2, textColor=MID, leading=10.5)
plab = ParagraphStyle("plab", fontName="Helvetica-Bold", fontSize=9, textColor=ACCENT,
                      leading=11, spaceBefore=5, spaceAfter=1)
prompt = ParagraphStyle("prompt", fontName="Helvetica", fontSize=8.8, textColor=INK,
                        leading=11.2, backColor=BOX, borderColor=BORD, borderWidth=0.6,
                        borderPadding=5, spaceAfter=2)
note = ParagraphStyle("note", fontName="Helvetica-Oblique", fontSize=8, textColor=MID,
                      leading=10, spaceAfter=4)
done = ParagraphStyle("done", fontName="Helvetica-Bold", fontSize=8.8, textColor=GREEN,
                      leading=11.5, backColor=GBOX, borderColor=GBORD, borderWidth=0.6,
                      borderPadding=5, spaceBefore=2, spaceAfter=4)

def bullet(txt, n):
    return Paragraph(f"<b>{n}.</b>&nbsp; {txt}", body)

def P(label, text, kind="prompt"):
    style = prompt if kind == "prompt" else done
    return KeepTogether([Paragraph(label, plab), Paragraph(text, style)])

flow = []

# ---------- PRE-FLIGHT ----------
flow.append(Paragraph("Before the call — your pre-flight (this is what makes 1 hour viable)", h2))
flow.append(bullet("<code>export FIVETRAN_API_KEY=key:secret</code> and confirm a call to "
                   "<code>/v1/groups</code> returns 200.", 1))
flow.append(bullet("Apply the Terraform in <code>infra/</code> (S3 bucket + Glue bronze/silver/gold + IAM role). "
                   "Confirm <code>terraform output</code> shows <b>bucket_name</b> and <b>fivetran_role_arn</b>.", 2))
flow.append(bullet("Verify the Fivetran <b>external_id</b> + AWS account id in <code>tfvars</code> are current — "
                   "if stale, the destination create fails on permissions. Fix it now, not on stage.", 3))
flow.append(bullet("Have an <b>OAuth source account</b> ready (Salesforce, HubSpot, or Google) that you can sign "
                   "into from this machine. SSO orgs can add a hop — test the sign-in beforehand.", 4))
flow.append(bullet("For the dbt stretch: confirm the dbt-athena env vars (<code>LAKE_BUCKET</code>, "
                   "<code>ATHENA_WORKGROUP</code>) and that the Athena workgroup exists. Node/npm installed for "
                   "the frontend stretch.", 5))
flow.append(bullet("Do one full dry run yourself, then delete that throwaway group so the live account is clean. "
                   "Keep the Fivetran dashboard and the AWS Glue/Athena console open in browser tabs.", 6))

# ---------- DECISIONS ----------
flow.append(Paragraph("Lock these before you start", h2))
flow.append(Paragraph("&bull;&nbsp; <b>Vertical / industry</b> (drives the demo story and the dbt + frontend content)"
                      "<br/>&bull;&nbsp; <b>Org name</b> — Niraj rule: used in every title, H1, and navbar; pick a generic name that won't collide with a real entity"
                      "<br/>&bull;&nbsp; <b>Buyer persona</b>"
                      "<br/>&bull;&nbsp; <b>OAuth source + which tables to sync</b> (keep it small so the first sync is fast)", body))

# ---------- TIMELINE ----------
flow.append(Paragraph("The hour — priority order (CORE first, STRETCH if time remains)", h2))
rows = [
    ["0:00", "Kickoff: invoke the skill, confirm vertical/persona/org + that infra is staged", "Both", ""],
    ["0:05", "GATHER: choose the OAuth source and the tables to sync", "Boss", ""],
    ["0:08", "Prompt 1 — create the AWS MDLS destination", "Boss", "CORE"],
    ["0:14", "Prompt 2 — create connector + open Connect Card, sign in via OAuth", "Boss", "CORE"],
    ["0:24", "Prompt 3 — run the setup test (expect CONNECTED)", "Boss", "CORE"],
    ["0:27", "Prompt 4 — trigger the first sync (runs in background)", "Boss", "CORE"],
    ["0:30", "While syncing: Hybrid-deployment talking point + confirm infra", "You", ""],
    ["0:35", "Prompt 5 — verify tables + rows in the Iceberg lake  =  MIN DEMO DONE", "Boss", "CORE"],
    ["0:42", "Prompt 6 — scaffold dbt bronze/silver/gold (+ Niraj rules)", "Boss", "STRETCH"],
    ["0:50", "Prompt 7 — dbt build (gold Iceberg tables)  =  GOOD DEMO DONE", "Boss", "STRETCH"],
    ["0:55", "Prompt 8 — React frontend shell + frontend-design pass", "Boss", "STRETCH"],
    ["0:58", "Wrap: what's done, what's a follow-up", "You", ""],
]
def who_color(w): return "#1a5fb4" if w == "Boss" else "#777777"
tdata = [[r[0],
          Paragraph(r[1], small),
          Paragraph(f"<font color='{who_color(r[2])}'><b>{r[2]}</b></font>", small),
          Paragraph(f"<b>{r[3]}</b>" if r[3] else "", small)]
         for r in rows]
tbl = Table(tdata, colWidths=[0.4*inch, 4.55*inch, 0.5*inch, 0.6*inch])
tbl.setStyle(TableStyle([
    ("VALIGN", (0,0), (-1,-1), "TOP"),
    ("FONT", (0,0), (0,-1), "Helvetica-Bold", 8),
    ("TEXTCOLOR", (0,0), (0,-1), ACCENT),
    ("LINEBELOW", (0,0), (-1,-2), 0.4, LINE),
    ("TOPPADDING", (0,0), (-1,-1), 3.5),
    ("BOTTOMPADDING", (0,0), (-1,-1), 3.5),
    ("LEFTPADDING", (0,0), (0,-1), 0),
]))
flow.append(tbl)

# ---------- PROMPTS ----------
flow.append(Paragraph("The prompts he types (paste one at a time; let Claude finish each)", h2))

flow.append(P("Kickoff — start the build",
    "Let's build a new ODI demo with the odi-demo-builder skill. Vertical: [VERTICAL]. Org name: [ORG]. "
    "Buyer persona: [PERSONA]. The Terraform in ./infra is already applied and $FIVETRAN_API_KEY is set — "
    "confirm the terraform outputs and the API connection, then take me through PROVISION and RUN, and as much "
    "of BUILD as we have time for."))

flow.append(P("GATHER — pick the source",
    "Use a [Salesforce / HubSpot / Google] OAuth source for this demo. Sync these tables: [list a few]. "
    "Keep the selection small so the first historical sync finishes quickly."))

flow.append(P("Prompt 1 — AWS MDLS destination  (CORE)",
    "Create the Fivetran Managed Data Lake destination on AWS now. Make a new group called boss-demo. Run "
    "terraform output in ./infra for the S3 bucket, IAM role ARN, and Glue bronze database, and use those in "
    "us-east-1. Call the REST API with the key from $FIVETRAN_API_KEY, and show me the destination id and setup status."))

flow.append(P("Prompt 2 — OAuth connector  (CORE)",
    "Create the [source] connector in the boss-demo group via the REST API, then generate a Fivetran Connect "
    "Card authorization link and give me the URL so I can sign in with OAuth."))
flow.append(Paragraph("In the browser: open the Connect Card URL Claude returns, sign in with OAuth, pick the data "
                      "to sync, click Save. No passwords typed.", note))

flow.append(P("Prompt 3 — test the connector  (CORE)",
    "Run the connector setup test and tell me whether it reports CONNECTED. If it's INCOMPLETE, surface the failure."))

flow.append(P("Prompt 4 — trigger the sync  (CORE)",
    "Trigger the first sync on that connector, then poll sync_state every 30 seconds until it's SYNCED. Tell me "
    "when it's done and which tables landed."))

flow.append(P("Prompt 5 — verify the lake  (CORE)",
    "List the S3 bronze prefix, then query the tables through Athena against the Glue catalog and show me a sample "
    "of rows from the largest table, so we confirm the data actually landed in the Iceberg lake."))
flow.append(P("Checkpoint — minimum demo done",
    "Live OAuth connector + first sync landed as Iceberg tables in the lake. That's a real ODI spine you can "
    "demo. Everything below is upside.", "done"))

flow.append(P("Prompt 6 — dbt scaffold  (STRETCH)",
    "Scaffold the dbt project to the portfolio standard: bronze sources.yml from the synced tables, silver staging "
    "models, and one gold Iceberg fact/dimension. Apply Niraj's content rules — org name [ORG] everywhere, every "
    "connector gets its Fivetran deep link, no raw table names exposed."))

flow.append(P("Prompt 7 — dbt build  (STRETCH)",
    "Run dbt build --select bronze silver gold and confirm the gold Iceberg tables are created in the Glue catalog. "
    "If it fails, diagnose from the error before fixing."))
flow.append(P("Checkpoint — good demo done",
    "Data flowing through a bronze/silver/gold dbt pipeline into gold Iceberg tables. Strong stopping point.", "done"))

flow.append(P("Prompt 8 — frontend shell  (STRETCH)",
    "Generate the React frontend shell — a Landing page with the [ORG] hero and a pipeline diagram "
    "(Fivetran -> S3/Iceberg -> dbt -> Athena), and a Pipeline page listing the connector with its Fivetran deep "
    "link. Then run the frontend-design pass for the [VERTICAL] vertical and [PERSONA] buyer."))

flow.append(P("After the demo — cleanup",
    "If boss-demo was a throwaway, tear down its group, connector, destination, and the Terraform resources so the "
    "account and AWS are clean. If we're keeping this as the real demo, leave it and just confirm what's deployed."))
flow.append(Paragraph("Keep the demo if it's the deliverable; only tear down throwaways. Don't delete the staged "
                      "infra you'll reuse.", note))

flow.append(Spacer(1, 4))
flow.append(Paragraph("While the sync runs — show the range (you drive)", h2))
flow.append(Paragraph("&bull;&nbsp; \"Research [account] via the FivetranKnowledge MCP — open tickets, last Gong call.\""
                      "<br/>&bull;&nbsp; \"Draft a QBR deck outline for that account.\""
                      "<br/>&bull;&nbsp; Hybrid deployment aside: the agent runs in the customer's network, only metadata "
                      "leaves their perimeter — same connector, destination, and pipeline. Answers the data-residency objection.", body))


# ---------- header / footer ----------
def header_footer(c, doc):
    w, h = letter
    c.saveState()
    if doc.page == 1:
        c.setFillColor(INK); c.setFont("Helvetica-Bold", 16)
        c.drawString(0.55*inch, h - 0.55*inch, "ODI Demo Build — 1-Hour Live Session with Claude")
        c.setFillColor(MID); c.setFont("Helvetica", 9)
        c.drawString(0.55*inch, h - 0.72*inch,
                     "Goal: stand up a working ODI / Managed Data Lake demo and get as far as time allows. "
                     "Boss is hands-on; you pre-stage the infra.")
        c.setStrokeColor(ACCENT); c.setLineWidth(1.2)
        c.line(0.55*inch, h - 0.80*inch, w - 0.55*inch, h - 0.80*inch)
    c.setFillColor(GREY); c.setFont("Helvetica-Oblique", 7.5)
    c.drawString(0.55*inch, 0.4*inch, "blue = boss types   ·   grey = you drive   ·   CORE = must-do   ·   STRETCH = if time remains")
    c.drawRightString(w - 0.55*inch, 0.4*inch, f"page {doc.page}")
    c.restoreState()

doc = SimpleDocTemplate(str(OUT), pagesize=letter,
                        leftMargin=0.55*inch, rightMargin=0.55*inch,
                        topMargin=0.95*inch, bottomMargin=0.6*inch,
                        title="ODI Demo Build - 1-Hour Session Runbook")
doc.build(flow, onFirstPage=header_footer, onLaterPages=header_footer)
print(f"wrote {OUT}")
