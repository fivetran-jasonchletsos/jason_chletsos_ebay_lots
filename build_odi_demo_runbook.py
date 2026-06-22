"""ODI demo build for a Claude-Code NOVICE, across three 1-hour sessions.

Written for a boss who is new to AI and Claude Code. Heavy hand-holding:
a plain-English primer on how Claude Code works, a glossary, a clear
"your job vs the driver's job" split, and under every prompt a "what it does /
what you'll see" line. Maps the ~3-hour odi-demo-builder flow onto 3 sessions:
  S1 Foundation & first data   S2 dbt pipeline   S3 Frontend + tour

Reality baked in: AWS creds + the Fivetran API key are NOT set on the machine,
so S1 opens with a 5-minute access check and a no-AWS fallback.
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
GREYBOX = HexColor("#f1f3f5"); LINE = HexColor("#cccccc"); GREY = HexColor("#777777")

sesh = ParagraphStyle("sesh", fontName="Helvetica-Bold", fontSize=12.5, textColor=HexColor("#ffffff"),
                      backColor=ACCENT, borderPadding=5, spaceBefore=10, spaceAfter=6, leading=15)
h2   = ParagraphStyle("h2", fontName="Helvetica-Bold", fontSize=11, textColor=ACCENT,
                      spaceBefore=8, spaceAfter=4, leading=13)
body = ParagraphStyle("body", fontName="Helvetica", fontSize=9, textColor=INK, leading=12.5, spaceAfter=4)
small= ParagraphStyle("small", fontName="Helvetica", fontSize=8.3, textColor=MID, leading=10.5, spaceAfter=2)
plab = ParagraphStyle("plab", fontName="Helvetica-Bold", fontSize=9.2, textColor=ACCENT,
                      leading=11, spaceBefore=7, spaceAfter=2)
prompt = ParagraphStyle("prompt", fontName="Helvetica", fontSize=9, textColor=INK, leading=11.6,
                        backColor=BOX, borderColor=BORD, borderWidth=0.6, borderPadding=6, spaceAfter=2)
expl = ParagraphStyle("expl", fontName="Helvetica-Oblique", fontSize=8.2, textColor=MID, leading=10.4,
                      spaceAfter=5, leftIndent=4)
done = ParagraphStyle("done", fontName="Helvetica-Bold", fontSize=8.8, textColor=GREEN, leading=11.5,
                      backColor=GBOX, borderColor=GBORD, borderWidth=0.6, borderPadding=6, spaceBefore=3, spaceAfter=5)
warn = ParagraphStyle("warn", fontName="Helvetica", fontSize=8.8, textColor=AMBER, leading=11.6,
                      backColor=ABOX, borderColor=ABORD, borderWidth=0.8, borderPadding=7, spaceBefore=2, spaceAfter=6)
tipbox = ParagraphStyle("tipbox", fontName="Helvetica", fontSize=8.7, textColor=INK, leading=11.4,
                        backColor=GREYBOX, borderColor=LINE, borderWidth=0.6, borderPadding=7, spaceBefore=2, spaceAfter=6)

def S(title):   return Paragraph(title, sesh)

def PROMPT(label, text, does):
    """A prompt the boss types, with a plain-English 'what it does' line under it."""
    return KeepTogether([
        Paragraph(label, plab),
        Paragraph(text, prompt),
        Paragraph("What it does: " + does, expl),
    ])

def DONE(text):
    return Paragraph("SESSION DONE — " + text, done)

flow = []

# =========================================================
# PAGE 1 — orientation for a first-time Claude Code user
# =========================================================
flow.append(Paragraph("What you're building", h2))
flow.append(Paragraph(
    "A working data demo. Over three short sessions you'll pull data out of a cloud app (like Salesforce), land "
    "it automatically in a data lake on Amazon's cloud, tidy it up, and show it in a small web app. You won't "
    "write any code yourself — you describe what you want in plain English and Claude does the work.", body))

flow.append(Paragraph("How Claude Code works — read this first (you're new to it, that's fine)", h2))
flow.append(Paragraph(
    "<b>1. It's a chat in a terminal window.</b> You type a request in plain English and press Enter. There is "
    "nothing to memorize and no special syntax — full sentences are perfect.<br/>"
    "<b>2. It does real work for you.</b> It writes code, runs commands, and sets up cloud services on its own. "
    "You watch it happen and approve along the way.<br/>"
    "<b>3. It asks permission before doing anything that matters.</b> When it wants to run a command, a box pops "
    "up asking you to allow it. Read the one-line summary and choose <b>Yes / Allow</b>. If you're unsure, ask "
    "the person next to you before allowing.<br/>"
    "<b>4. Let it finish.</b> It works in steps and will often pause, show progress, or ask you a question. Wait "
    "until it stops and hands the turn back to you before typing the next thing.<br/>"
    "<b>5. You can always just talk to it.</b> If you don't understand something on screen, type "
    "<i>\"explain that to me like I'm new to this\"</i> or <i>\"what did that just do?\"</i> It will answer in "
    "plain language. This is the best habit to build today.", body))

flow.append(Paragraph("Your job vs. the driver's job", h2))
flow.append(Paragraph(
    "<b>You (hands on keyboard):</b> read each prompt below, type or paste it, press Enter, and choose "
    "<b>Allow</b> when asked. Ask questions freely.<br/>"
    "<b>The driver next to you:</b> handles logins and passwords, anything that turns up as a red error, and any "
    "decision about cost or accounts. If anything looks confusing or alarming, hand it to them — nothing you type "
    "can cause real damage.", body))

flow.append(Paragraph("If you get stuck (keep this handy)", h2))
flow.append(Paragraph(
    "&bull;&nbsp; A box asks to run a command and you don't know what it is &rarr; it's normal; choose Allow (or ask the driver).<br/>"
    "&bull;&nbsp; Claude asks you a question you don't understand &rarr; type: <i>\"I'm new to this — explain what you need in simple terms.\"</i><br/>"
    "&bull;&nbsp; You see red error text &rarr; don't worry, hand it to the driver, or type: <i>\"that looks like an error — can you fix it?\"</i><br/>"
    "&bull;&nbsp; Claude seems frozen &rarr; it's probably still working; give it a minute before typing again.<br/>"
    "&bull;&nbsp; You lost track of where you are &rarr; type: <i>\"summarize what we've done so far and what's next.\"</i>", tipbox))

flow.append(Paragraph("Plain-English glossary (skim it, refer back as needed)", h2))
gloss = [
    ("Prompt", "What you type to Claude — a plain-English instruction."),
    ("Connector", "An automatic pipe that pulls data out of an app (e.g. Salesforce) for you."),
    ("OAuth", "The \"Sign in with Google/Salesforce\" button. You log in; no passwords are shared."),
    ("Sync", "The connector copying the data over for the first time."),
    ("Data lake / MDLS", "Cloud storage where all the data lands, in an open format anyone can read."),
    ("Iceberg", "The modern table format the data is stored as inside the lake."),
    ("AWS", "Amazon's cloud. S3 stores the files, Glue lists the tables, Athena runs queries, IAM is permissions."),
    ("Terraform", "A tool that sets up those cloud pieces automatically from a script Claude writes."),
    ("dbt", "A tool that cleans and reshapes raw data into tidy tables for analysis."),
    ("Connect Card", "A Fivetran link you open in your browser to log into the source app with OAuth."),
]
gdata = [[Paragraph(f"<b>{t}</b>", small), Paragraph(d, small)] for t, d in gloss]
gt = Table(gdata, colWidths=[1.35*inch, 5.7*inch])
gt.setStyle(TableStyle([
    ("VALIGN", (0,0), (-1,-1), "TOP"),
    ("LINEBELOW", (0,0), (-1,-2), 0.3, HexColor("#e3e3e3")),
    ("TOPPADDING", (0,0), (-1,-1), 2.5), ("BOTTOMPADDING", (0,0), (-1,-1), 2.5),
    ("LEFTPADDING", (0,0), (0,-1), 0),
]))
flow.append(gt)

# ---------- ACCESS GATE ----------
flow.append(Paragraph("Session 1 opens with a 5-minute access check (done by the driver)", h2))
flow.append(Paragraph(
    "<b>This must happen first, or the cloud build can't start.</b> The programs are installed; the logins are not.<br/>"
    "&bull;&nbsp; <b>Fivetran:</b> log in, generate an API key, then in the terminal "
    "<code>export FIVETRAN_API_KEY=key:secret</code><br/>"
    "&bull;&nbsp; <b>AWS:</b> run <code>aws configure</code> (paste an admin access key + secret, or use SSO), then "
    "confirm with <code>aws sts get-caller-identity</code><br/>"
    "&bull;&nbsp; <b>If a login isn't available:</b> don't burn the hour on it. Instead, open one of the finished "
    "demos in <code>~/Documents/GitHub/*-ODI-Demo</code> and have Claude give you a guided tour — you'll still see "
    "exactly what we're building — then provision for real next session.", warn))

flow.append(Paragraph("Carry into each session (no homework between sessions)", h2))
flow.append(Paragraph(
    "&bull;&nbsp; The <b>Fivetran API key</b> — re-paste the <code>export</code> line at the start of each session "
    "(it doesn't carry over to a new terminal window).<br/>"
    "&bull;&nbsp; The driver re-runs the AWS login if needed.<br/>"
    "&bull;&nbsp; If you forget where things are, just ask Claude: <i>\"list the demo we built and where it lives.\"</i>", body))

# =========================================================
# SESSION 1
# =========================================================
flow.append(S("Session 1 (today) — set up the cloud and pull in the data"))
flow.append(Paragraph("Goal: stand up the AWS data lake, connect the source app, and start the first data sync. "
                      "Before you provision, decide the three blanks below.", small))
flow.append(Paragraph("<b>Fill these in first:</b> [VERTICAL] = the industry story (e.g. Banking). "
                      "[ORG] = a made-up company name for the demo. [PERSONA] = who the demo is for (e.g. a risk "
                      "analyst). [source] = the app to pull from (e.g. Salesforce).", small))

flow.append(PROMPT("Prompt 1 — kick off the build",
    "Let's build a new ODI demo with the odi-demo-builder skill. Vertical: [VERTICAL]. Org name: [ORG]. Buyer "
    "persona: [PERSONA]. Nothing is set up yet and my AWS and Fivetran logins are now configured. Walk me through "
    "it step by step, and explain what each step does in plain language as you go.",
    "Starts the guided build. Claude will lay out the plan and begin writing the cloud setup. Expect it to ask you "
    "to allow a few commands — choose Allow."))

flow.append(PROMPT("Prompt 2 — build the cloud storage",
    "Scaffold the Terraform for the S3 bucket, the Glue databases, and the Fivetran permissions role, then walk me "
    "through applying it. Tell me when you need anything from me.",
    "Claude writes a setup script and runs it to create the storage and permissions on AWS. The driver may need to "
    "paste two values from the Fivetran screen when asked. You'll see a list of created resources at the end."))

flow.append(PROMPT("Prompt 3 — create the data lake destination",
    "Create the Managed Data Lake destination in Fivetran using what Terraform just set up, and show me that it "
    "connected successfully.",
    "Tells Fivetran where to put the data (our new lake). You'll see a confirmation with a status of connected."))

flow.append(PROMPT("Prompt 4 — connect the source app",
    "Create the [source] connector, then give me a Connect Card link so I can sign in to [source] with OAuth.",
    "Claude sets up the pipe from the source app and hands you a link. Open it in your browser, sign in the normal "
    "way, pick the data, and click Save. No passwords are typed into Claude."))

flow.append(PROMPT("Prompt 5 — start the data flowing",
    "Test the connection, then start the first sync and tell me when it has finished and which tables came across.",
    "Kicks off the first copy of data into the lake. This can take a few minutes; Claude will watch it and report "
    "when it's done."))

flow.append(DONE("the cloud lake is live, the app is connected, and data is flowing in. If the AWS setup ran long, "
                 "stopping here is a perfectly good session 1 — we model the data next time."))

# =========================================================
# SESSION 2
# =========================================================
flow.append(S("Session 2 — shape the raw data into clean tables"))
flow.append(Paragraph("At the start: re-paste the Fivetran key line, the driver re-checks the AWS login, and "
                      "confirm last session's data arrived.", small))

flow.append(PROMPT("Prompt 1 — pick up where we left off",
    "Resume the ODI demo we started. Confirm the data sync from last session finished and show me the tables that "
    "landed in the lake.",
    "Re-orients Claude and proves the data from session 1 is really there before we build on it."))

flow.append(PROMPT("Prompt 2 — build the data pipeline",
    "Build the dbt pipeline to the portfolio standard — a raw layer, a cleaned layer, and a final reporting layer "
    "of tables. Apply Niraj's content rules, and explain each layer in plain language.",
    "Claude generates the data-cleaning project that turns raw rows into tidy, business-ready tables."))

flow.append(PROMPT("Prompt 3 — run it and check the result",
    "Run the pipeline and confirm the final tables were created. If anything fails, explain the error simply and "
    "fix it. Then show me a sample of the finished data.",
    "Executes the pipeline and shows you the polished tables. You'll see a short sample of real data at the end."))

flow.append(DONE("raw data has been turned into clean, query-ready tables in the lake. Strong stopping point."))

# =========================================================
# SESSION 3
# =========================================================
flow.append(S("Session 3 — build the web app and tour the demo"))
flow.append(Paragraph("Same quick restart at the top: re-paste the key, re-check the AWS login.", small))

flow.append(PROMPT("Prompt 1 — generate the web app",
    "Generate the React frontend for the demo — a landing page with the [ORG] name and a simple diagram of the "
    "data flow, and a page that lists the connector with a link to it in Fivetran.",
    "Claude builds a small website that presents the demo. You'll get pages you can open in a browser."))

flow.append(PROMPT("Prompt 2 — make it look sharp",
    "Run the frontend-design pass for the [VERTICAL] industry and [PERSONA] audience — a distinctive, professional "
    "look, clean charts, and no generic AI styling.",
    "Polishes the look and feel so it's presentation-ready rather than plain."))

flow.append(PROMPT("Prompt 3 — final quality check",
    "Do a content quality pass: make sure the [ORG] name appears everywhere it should, no raw technical names are "
    "showing, and the connector link works.",
    "A final cleanup so nothing looks unfinished in front of an audience."))

flow.append(PROMPT("Prompt 4 — walk the demo",
    "Start the web app and give me a guided tour from start to finish — the landing page, the data flow, and the "
    "data in the lake.",
    "Opens the finished demo and narrates it end to end. This is the version you'd show a customer."))

flow.append(DONE("a demo-ready ODI app: a live connector, a cloud data lake, a clean data pipeline, and a polished "
                 "web app you can present."))

# ---------- header / footer ----------
def header_footer(c, doc):
    w, h = letter
    c.saveState()
    if doc.page == 1:
        c.setFillColor(INK); c.setFont("Helvetica-Bold", 16)
        c.drawString(0.55*inch, h - 0.55*inch, "Building an ODI Demo with Claude Code — A Beginner's Guide")
        c.setFillColor(MID); c.setFont("Helvetica", 9)
        c.drawString(0.55*inch, h - 0.72*inch,
                     "Three 1-hour sessions. Written for a first-time Claude Code user. You type plain English; "
                     "Claude does the work.")
        c.setStrokeColor(ACCENT); c.setLineWidth(1.2)
        c.line(0.55*inch, h - 0.80*inch, w - 0.55*inch, h - 0.80*inch)
    c.setFillColor(GREY); c.setFont("Helvetica-Oblique", 7.5)
    c.drawString(0.55*inch, 0.4*inch, "Tip: at any time, type \"explain that like I'm new to this.\"  ·  green = a safe place to stop")
    c.drawRightString(w - 0.55*inch, 0.4*inch, f"page {doc.page}")
    c.restoreState()

doc = SimpleDocTemplate(str(OUT), pagesize=letter,
                        leftMargin=0.55*inch, rightMargin=0.55*inch,
                        topMargin=0.95*inch, bottomMargin=0.6*inch,
                        title="Building an ODI Demo with Claude Code - Beginner's Guide")
doc.build(flow, onFirstPage=header_footer, onLaterPages=header_footer)
print(f"wrote {OUT}")
