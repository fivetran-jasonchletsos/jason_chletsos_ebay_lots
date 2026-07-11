"""build_chrome_pull_pdf.py — one-line-per-card pull sheet for every Topps
Chrome card scanned (scans 314-317), read from output/_chrome_scan.json.
Grouped by value tier (numbered hits, Gold, inserts, Pink X-Fractor, X-Fractor,
base), alphabetical within tier. Prints clean (name, team, parallel, serial,
price, scan-position, posted?). Writes docs/chrome_pull_all.pdf + ~/Downloads.
"""
import json, shutil
from pathlib import Path
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.platypus import (SimpleDocTemplate, Table, TableStyle, Paragraph,
                                Spacer)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

CARDS = json.loads(Path("output/_chrome_scan.json").read_text())
INSERTS = {"All-Chrome", "Future Stars", "Fortune", "Legends of the Gridiron", "Powers"}

# cards already posted live (scan 317 batch + the 4 numbered/gold hits)
POSTED = {(c["scan"], c["pos"]) for c in CARDS if c["scan"] == 317}
POSTED |= {(316, 4), (314, 1), (316, 3), (315, 1)}

def low_serial(serial):
    if not serial or "/" not in serial: return False
    try: return int(serial.split("/")[1]) <= 99
    except Exception: return False

def price(c):
    par, ser = c["parallel"], c["serial"]
    if ser and low_serial(ser): return 12.99
    if ser: return 7.99                       # Aqua / other numbered
    if par == "Gold X-Fractor": return 6.99
    if par in INSERTS: return 4.99
    if par == "Green": return 5.99
    if par == "Pink X-Fractor": return 4.49
    if par == "X-Fractor": return 3.49
    return 2.49                               # base

def tier(c):
    par, ser = c["parallel"], c["serial"]
    if ser and low_serial(ser): return (0, "Numbered hits (/99 or lower)")
    if ser: return (1, "Numbered / Aqua")
    if par == "Gold X-Fractor": return (2, "Gold X-Fractor")
    if par in INSERTS: return (3, "Inserts")
    if par in ("Green",): return (3, "Inserts")
    if par == "Pink X-Fractor": return (4, "Pink X-Fractor")
    if par == "X-Fractor": return (5, "X-Fractor")
    return (6, "Base")

def last(name): return name.split()[-1].lower()

styles = getSampleStyleSheet()
h1 = ParagraphStyle("h1", parent=styles["Title"], fontSize=20, spaceAfter=4)
sub = ParagraphStyle("sub", parent=styles["Normal"], fontSize=10, textColor=colors.HexColor("#6b7280"), spaceAfter=14)
grp = ParagraphStyle("grp", parent=styles["Heading2"], fontSize=13, textColor=colors.HexColor("#1a3d6d"), spaceBefore=12, spaceAfter=4)

out = Path("docs/chrome_pull_all.pdf")
doc = SimpleDocTemplate(str(out), pagesize=letter, topMargin=0.6*inch,
                        bottomMargin=0.6*inch, leftMargin=0.6*inch, rightMargin=0.6*inch)
flow = [Paragraph("Topps Chrome pull sheet", h1),
        Paragraph(f"harpua2001 &middot; scans 314-317 &middot; {len(CARDS)} cards &middot; POSTED = live on eBay", sub)]

groups = {}
for c in CARDS:
    t = tier(c); groups.setdefault(t, []).append(c)

for t in sorted(groups):
    rows = [["Player", "Team", "Parallel", "Serial", "$", "Scan", "Live?"]]
    for c in sorted(groups[t], key=lambda x: last(x["player"])):
        rc = " RC" if c.get("rc") else ""
        rows.append([c["player"] + rc, c["team"], c["parallel"], c["serial"] or "-",
                     f'{price(c):.2f}', f'{c["scan"]}-{c["pos"]}',
                     "POSTED" if (c["scan"], c["pos"]) in POSTED else ""])
    n_posted = sum(1 for c in groups[t] if (c["scan"], c["pos"]) in POSTED)
    flow.append(Paragraph(f'{t[1]} &mdash; {len(groups[t])} cards ({n_posted} live)', grp))
    tbl = Table(rows, colWidths=[1.5*inch, 1.5*inch, 1.5*inch, 0.7*inch, 0.5*inch, 0.6*inch, 0.65*inch])
    tbl.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1a3d6d")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f4f6f9")]),
        ("TEXTCOLOR", (6, 1), (6, -1), colors.HexColor("#1a7d3d")),
        ("FONTNAME", (6, 1), (6, -1), "Helvetica-Bold"),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#d5dae3")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    flow.append(tbl)

doc.build(flow)
dl = Path.home() / "Downloads" / "chrome_pull_all.pdf"
shutil.copy(out, dl)
print(f"wrote {out}  ({len(CARDS)} cards)  ->  {dl}")
