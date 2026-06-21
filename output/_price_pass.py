import sys; sys.path.insert(0, ".")
import json, sys
from pathlib import Path
import card_price_agent as cpa
from repricing_agent import _round_psych

token = cpa.load_token()
batches = [f"output/batch_scan{n}_new.json" for n in range(212, 230)]
summary = []
priced = scp_hits = fallbacks = 0

for bf in batches:
    p = Path(bf)
    if not p.is_file():
        continue
    cards = json.loads(p.read_text())
    for c in cards:
        title = c["title"]
        tl = title.lower()
        # Caleb Williams base/non-insert pinned at 2.99
        if "caleb williams" in tl and not any(k in tl for k in
            ["numbers","prizm","optic","mosaic","select","downtown","kaboom","insert","parallel","silver","gold","orange","pink","green","auto"]):
            c["price"] = 2.99; c["price_src"] = "caleb_base_rule"; priced += 1; fallbacks += 1
            continue
        try:
            rec = cpa.price_listing({"title": title, "item_id": None}, token)
        except Exception as e:
            rec = None
        # Use the ORIGINAL identification tier estimate as the sanity basis, and
        # persist it (_tier) so re-running this pass stays idempotent — without
        # this, a second run would read the already-SCP'd c["price"] as the
        # "tier" and the 3x cap would drift upward each run.
        tier = max(2.99, float(c.get("_tier", c["price"])))
        c["_tier"] = tier
        conf = rec.get("confidence", 0) if rec else 0
        scp = float(rec["actual_price"]) if (rec and rec.get("actual_price")) else 0
        # Trust SCP only at HIGH confidence, AND sanity-cap against the tier:
        # a weak match that lands >3x the tier is almost always the wrong (graded/
        # numbered) variant — that produced $161 Keon Coleman etc. Fall back to tier.
        scp_trustworthy = scp and conf >= 0.80 and scp <= tier * 3.0
        if scp_trustworthy:
            lp = max(2.99, _round_psych(scp))
            c["price"] = lp
            c["price_src"] = f"scp:{scp:.2f}/conf{conf:.2f}"
            scp_hits += 1
        else:
            # keep rough tier price (already .99), floor 2.99
            c["price"] = tier
            c["price_src"] = "tier_fallback"
            fallbacks += 1
        priced += 1
    p.write_text(json.dumps(cards, indent=1))
    summary.append((bf.split("scan")[1].split("_")[0], len(cards),
                    sum(x["price"] for x in cards)))

print(f"\nPRICED {priced} cards  |  SCP-anchored: {scp_hits}  |  fallback: {fallbacks}")
print(f"Total list value: ${sum(s[2] for s in summary):.2f}")
