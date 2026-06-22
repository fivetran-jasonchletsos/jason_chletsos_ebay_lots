"""One-page cheat sheet for the 1-hour 'what I do with Claude' boss demo.

Flow: AWS MDLS destination (Terraform pre-staged, Claude creates the destination
via REST) + an OAuth source connector (Claude creates it and hands the boss a
Fivetran Connect Card link he signs into in the browser). Boss is hands-on; the
prompts are plain English so he never touches a curl command.

Outputs to output/ and is also copied to ~/Downloads (JC's standing pref).
"""
from pathlib import Path
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.lib.colors import HexColor
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import Paragraph, Frame, Table, TableStyle, Spacer
from reportlab.pdfgen import canvas

REPO = Path(__file__).parent
OUT = REPO / "output/boss_demo_cheatsheet.pdf"

PAGE_W, PAGE_H = letter
M = 0.5 * inch
INK = HexColor("#111111"); MID = HexColor("#444444")
ACCENT = HexColor("#1a5fb4"); BOX = HexColor("#eef3fb"); LINE = HexColor("#cccccc")
BOSS = HexColor("#1a5fb4"); YOU = HexColor("#777777")

c = canvas.Canvas(str(OUT), pagesize=letter)

# ---- header ----
c.setFillColor(INK); c.setFont("Helvetica-Bold", 17)
c.drawString(M, PAGE_H - M - 6, "Claude + Fivetran — 1-Hour Demo Cheat Sheet")
c.setFillColor(MID); c.setFont("Helvetica", 9)
c.drawString(M, PAGE_H - M - 22,
             "You describe intent in plain English; Claude writes the API/infra work and verifies it. "
             "Boss is hands-on at the keyboard.")
c.setStrokeColor(ACCENT); c.setLineWidth(1.2)
c.line(M, PAGE_H - M - 30, PAGE_W - M, PAGE_H - M - 30)
c.setFillColor(YOU); c.setFont("Helvetica-Oblique", 8)
c.drawRightString(PAGE_W - M, PAGE_H - M - 6, "blue = boss types  ·  grey = you drive")

# ---- styles ----
h2 = ParagraphStyle("h2", fontName="Helvetica-Bold", fontSize=10.5, textColor=ACCENT,
                    spaceBefore=2, spaceAfter=4, leading=12)
body = ParagraphStyle("body", fontName="Helvetica", fontSize=8.3, textColor=INK,
                      leading=10.6, spaceAfter=3)
small = ParagraphStyle("small", fontName="Helvetica", fontSize=7.6, textColor=MID, leading=9.4)
plabel = ParagraphStyle("plabel", fontName="Helvetica-Bold", fontSize=8.3, textColor=BOSS,
                        leading=10, spaceBefore=4, spaceAfter=1)
prompt = ParagraphStyle("prompt", fontName="Helvetica", fontSize=8.0, textColor=INK,
                        leading=10.2, backColor=BOX, borderColor=HexColor("#c7d6ee"),
                        borderWidth=0.6, borderPadding=5, spaceAfter=3)

def b(txt, n):
    return Paragraph(f"<b>{n}.</b>&nbsp; {txt}", body)

# ---- LEFT COLUMN: pre-flight + timeline ----
left = []
left.append(Paragraph("Before he arrives — your 15-min pre-flight", h2))
left.append(b("<code>export FIVETRAN_API_KEY=key:secret</code> and confirm a test call to "
              "<code>/v1/groups</code> returns 200.", 1))
left.append(b("Run the Terraform in <code>infra/</code> (S3 + Glue bronze/silver/gold + IAM role). "
              "Confirm <code>terraform output</code> shows <b>bucket_name</b> and <b>fivetran_role_arn</b>.", 2))
left.append(b("Verify the Fivetran <b>external_id</b> + AWS account id in <code>tfvars</code> are current — "
              "if stale, the destination create fails on permissions. Fix it now, not on stage.", 3))
left.append(b("Pre-create the OAuth source (e.g. a Google Sheet with sample data) and confirm you can "
              "sign into that provider from this machine.", 4))
left.append(b("Open the Fivetran dashboard in a browser tab so the connector appears live as he creates it.", 5))
left.append(b("Do one full dry run yourself end-to-end, then delete the throwaway group so the live run is clean.", 6))

left.append(Spacer(1, 6))
left.append(Paragraph("The hour", h2))
rows = [
    ["0:00", "Frame it: intent in English, Claude does the API + infra. Show your setup.", "You"],
    ["0:10", "Prompt 1 — create the AWS MDLS destination", "Boss"],
    ["0:16", "Prompt 2 — create OAuth connector; open Connect Card, sign in via OAuth", "Boss"],
    ["0:24", "Prompt 3 — trigger the initial sync", "Boss"],
    ["0:27", "While it syncs: Hybrid deployment talking point + range prompts", "You"],
    ["0:42", "Prompt 4 — verify tables + rows landed in the lake", "Boss"],
    ["0:52", "Cleanup prompt + Q&A", "Both"],
]
tdata = [[r[0], Paragraph(r[1], small),
          Paragraph(f"<font color='{'#1a5fb4' if r[2]=='Boss' else '#777777'}'><b>{r[2]}</b></font>", small)]
         for r in rows]
tbl = Table(tdata, colWidths=[0.32*inch, 2.05*inch, 0.45*inch])
tbl.setStyle(TableStyle([
    ("VALIGN", (0,0), (-1,-1), "TOP"),
    ("FONT", (0,0), (0,-1), "Helvetica-Bold", 7.6),
    ("TEXTCOLOR", (0,0), (0,-1), ACCENT),
    ("LINEBELOW", (0,0), (-1,-2), 0.4, LINE),
    ("TOPPADDING", (0,0), (-1,-1), 3),
    ("BOTTOMPADDING", (0,0), (-1,-1), 3),
    ("LEFTPADDING", (0,0), (-1,-1), 2),
]))
left.append(tbl)

left.append(Spacer(1, 6))
left.append(Paragraph("While it syncs — show the range (you)", h2))
left.append(Paragraph("&bull;&nbsp; \"Research [account] via the FivetranKnowledge MCP — open tickets, last Gong call.\"", small))
left.append(Paragraph("&bull;&nbsp; \"Draft a QBR deck outline for that account.\"", small))
left.append(Paragraph("&bull;&nbsp; \"This same flow scaffolds a whole ODI demo — Terraform, connector, dbt, frontend.\"", small))

# ---- RIGHT COLUMN: the prompts ----
right = []
right.append(Paragraph("The prompts he types", h2))
right.append(Paragraph("Paste one at a time; let Claude finish each before the next. Plain English on purpose — "
                       "he never touches a command.", small))
right.append(Spacer(1, 2))

right.append(Paragraph("Prompt 1 — AWS MDLS destination", plabel))
right.append(Paragraph("Create a new Fivetran Managed Data Lake destination on AWS. Make a new group called "
                       "boss-demo. Run terraform output in ./infra for the S3 bucket, IAM role ARN, and Glue "
                       "bronze database, and use those in us-east-1. Read the key from $FIVETRAN_API_KEY, call "
                       "the REST API, and show me the destination id and its setup status.", prompt))

right.append(Paragraph("Prompt 2 — OAuth source connector", plabel))
right.append(Paragraph("Create a Google Sheets connector in the boss-demo group via the REST API, then generate "
                       "a Fivetran Connect Card authorization link and give me the URL so I can sign in with OAuth.", prompt))
right.append(Paragraph("<b>Then in the browser:</b> open the Connect Card URL Claude returns, sign in with OAuth, "
                       "pick the data to sync, and click Save. No passwords typed. "
                       "<i>Swap \"Google Sheets\" for Salesforce, HubSpot, or GA4 — any OAuth source.</i>", small))
right.append(Spacer(1, 2))

right.append(Paragraph("Prompt 3 — trigger the sync", plabel))
right.append(Paragraph("Trigger the initial sync on that connector, then poll its status every 30 seconds until "
                       "the first sync finishes. Tell me when it's done and which tables landed.", prompt))

right.append(Paragraph("Prompt 4 — verify in the lake", plabel))
right.append(Paragraph("Query the Glue bronze database through Athena and show me the tables Fivetran created, "
                       "plus a sample of rows from the largest one, so we confirm the data actually arrived.", prompt))

right.append(Paragraph("Cleanup — after the demo", plabel))
right.append(Paragraph("Delete the boss-demo group and its connector and destination from Fivetran so we leave "
                       "the account clean. Confirm they're gone.", prompt))

# ---- lay out the two frames ----
top = PAGE_H - M - 40
col_w = (PAGE_W - 2*M - 0.30*inch) / 2
fh = top - M
fL = Frame(M, M, col_w, fh, leftPadding=0, rightPadding=6, topPadding=0, bottomPadding=0, showBoundary=0)
fR = Frame(M + col_w + 0.30*inch, M, col_w, fh, leftPadding=6, rightPadding=0, topPadding=0, bottomPadding=0, showBoundary=0)
fL.addFromList(left, c)
fR.addFromList(right, c)

c.showPage(); c.save()
print(f"wrote {OUT}")
