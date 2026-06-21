import sys; sys.path.insert(0, ".")
import json
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
        title = c.get("title") or ""          # guard missing title (don't crash the pass)
        if not title:
            c.setdefault("price", 2.99)        # keep the summary sum safe
            continue
        # Idempotency: a card already priced by an OLDER version (has price_src
        # but no persisted _tier) has lost its original tier estimate — leave it
        # untouched rather than guess (re-pricing would either ratchet up off the
        # inflated price or force it down to the floor). Cards priced by THIS
        # version carry _tier and re-price deterministically below.
        if c.get("price_src") and "_tier" not in c:
            priced += 1
            continue
        tl = title.lower()
        # Caleb Williams base/non-insert pinned at 2.99. Disqualify on any
        # PARALLEL/INSERT signal — color words (any common parallel color) or a
        # named insert — but NOT plain set/brand names, so a true base
        # "Panini Select Caleb Williams" still gets the $2.99 rule.
        CALEB_DISQUALIFY = (
            "numbers", "downtown", "kaboom", "insert", "parallel", "auto", "rated",
            "silver", "gold", "orange", "pink", "green", "red", "blue", "purple",
            "teal", "bronze", "copper", "black", "white", "aqua", "lime", "yellow",
            "neon", "camo", "tie-dye", "tie dye", "lava", "fluorescent", "snakeskin",
            "cracked", "prizmatic", "wave", "disco", "scope", "hyper", "velocity",
            "shimmer", "mojo", "flash", "ice", "dragon", "choice",
        )
        if "caleb williams" in tl and not any(k in tl for k in CALEB_DISQUALIFY):
            c["price"] = 2.99; c["price_src"] = "caleb_base_rule"; priced += 1; fallbacks += 1
            continue
        try:
            rec = cpa.price_listing({"title": title, "item_id": None}, token)
        except Exception:
            rec = None
        # Sanity basis = the ORIGINAL identification tier estimate, persisted as
        # _tier so re-runs stay idempotent (old-version cards were skipped above).
        if "_tier" in c:
            tier = max(2.99, float(c["_tier"]))
        else:
            tier = max(2.99, float(c.get("price") or 2.99))
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
            # fall back to the tier estimate, psych-rounded + floored at 2.99
            c["price"] = max(2.99, _round_psych(tier))
            c["price_src"] = "tier_fallback"
            fallbacks += 1
        priced += 1
    p.write_text(json.dumps(cards, indent=1))
    summary.append((bf.split("scan")[1].split("_")[0], len(cards),
                    sum(x.get("price", 0) for x in cards)))

print(f"\nPRICED {priced} cards  |  SCP-anchored: {scp_hits}  |  fallback: {fallbacks}")
print(f"Total list value: ${sum(s[2] for s in summary):.2f}")
