"""
feedback_agent.py — leave positive feedback for buyers on completed orders.

Finds all transactions where the buyer has not yet received feedback,
picks a random comment from a pool, and submits via Trading API LeaveFeedback.
Runs in dry-run by default; pass --apply to actually post.

Usage:
    python3 feedback_agent.py              # dry-run
    python3 feedback_agent.py --apply      # post feedback
    python3 feedback_agent.py --limit 10   # cap how many to process
"""
from __future__ import annotations

import argparse
import json
import random
import re
import sys
import time
from pathlib import Path

import requests

import ebay_client
import promote

REPO_ROOT = Path(__file__).parent
NS = ebay_client.NS
TRADING_URL = ebay_client.TRADING_URL

POSITIVE_COMMENTS = [
    "Great buyer! Fast payment, smooth transaction. Thank you!",
    "Excellent buyer. Quick payment. Always welcome back!",
    "Fast payment, great communication. Highly recommended buyer!",
    "Perfect transaction. Thank you for your purchase!",
    "Wonderful buyer — paid immediately. Hope you love the card!",
    "Super fast payment. Great eBay buyer, thank you!",
    "Smooth and easy transaction. Thank you for buying!",
    "Highly recommended buyer. Fast payment, no issues. Thank you!",
    "Great buyer, quick payment. A pleasure to do business with!",
    "Excellent buyer! Hope you enjoy your purchase. Thank you!",
    "Fast payment, great buyer. Thank you for the transaction!",
    "Terrific buyer — immediate payment. Would sell to again!",
    "Outstanding buyer. Paid instantly. Thank you so much!",
    "A+ buyer! Payment received quickly. Thanks for the business!",
    "Easy transaction, fast payment. Thank you, great buyer!",
]


def get_unfeedback_transactions(token: str, cfg: dict) -> list[dict]:
    """Pull sold transactions where we haven't left feedback yet, using GetItemsAwaitingFeedback."""
    xml = f"""<?xml version="1.0" encoding="utf-8"?>
<GetItemsAwaitingFeedbackRequest xmlns="{NS}">
  <RequesterCredentials><eBayAuthToken>{token}</eBayAuthToken></RequesterCredentials>
  <Pagination><EntriesPerPage>200</EntriesPerPage><PageNumber>1</PageNumber></Pagination>
  <Sort>EndTime</Sort>
</GetItemsAwaitingFeedbackRequest>"""

    headers = ebay_client.trading_headers("GetItemsAwaitingFeedback", cfg, token)
    resp = requests.post(TRADING_URL, headers=headers, data=xml.encode(), timeout=30)
    root_text = resp.text

    pending = []
    transactions = re.findall(r"<TransactionArray>.*?</TransactionArray>", root_text, re.DOTALL)
    for block in transactions:
        tx_items = re.findall(r"<Transaction>(.*?)</Transaction>", block, re.DOTALL)
        for tx in tx_items:
            item_id_m  = re.search(r"<ItemID>(.*?)</ItemID>", tx)
            tx_id_m    = re.search(r"<TransactionID>(.*?)</TransactionID>", tx)
            buyer_m    = re.search(r"<Buyer>.*?<UserID>(.*?)</UserID>", tx, re.DOTALL)
            if not item_id_m or not tx_id_m or not buyer_m:
                continue
            pending.append({
                "item_id":        item_id_m.group(1),
                "transaction_id": tx_id_m.group(1),
                "buyer":          buyer_m.group(1),
            })
    return pending


def leave_feedback(item_id: str, transaction_id: str, buyer: str,
                   comment: str, token: str, cfg: dict) -> bool:
    xml = f"""<?xml version="1.0" encoding="utf-8"?>
<LeaveFeedbackRequest xmlns="{NS}">
  <RequesterCredentials><eBayAuthToken>{token}</eBayAuthToken></RequesterCredentials>
  <ItemID>{item_id}</ItemID>
  <TransactionID>{transaction_id}</TransactionID>
  <TargetUser>{buyer}</TargetUser>
  <CommentType>Positive</CommentType>
  <CommentText>{comment}</CommentText>
</LeaveFeedbackRequest>"""

    headers = ebay_client.trading_headers("LeaveFeedback", cfg, token)
    resp = requests.post(TRADING_URL, headers=headers, data=xml.encode(), timeout=30)
    ack = re.search(r"<Ack>(.*?)</Ack>", resp.text)
    errors = re.findall(r"<ShortMessage>(.*?)</ShortMessage>", resp.text)
    ok = ack and ack.group(1) in ("Success", "Warning")
    if not ok and errors:
        print(f"    Error: {errors[0]}")
    return ok


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--limit", type=int, default=200)
    args = ap.parse_args()

    cfg = json.loads((REPO_ROOT / "configuration.json").read_text())
    token = promote.get_access_token(cfg)

    print("  Fetching orders awaiting feedback (GetItemsAwaitingFeedback)...")
    pending = get_unfeedback_transactions(token, cfg)
    print(f"  Found {len(pending)} transaction(s) without buyer feedback.")

    if args.limit:
        pending = pending[:args.limit]

    ok_count = 0
    for p in pending:
        comment = random.choice(POSITIVE_COMMENTS)
        print(f"  {'[dry-run] would leave' if not args.apply else 'Leaving'} feedback for "
              f"{p['buyer']} on item {p['item_id']}: \"{comment[:50]}...\"")
        if args.apply:
            ok = leave_feedback(p["item_id"], p["transaction_id"],
                                p["buyer"], comment, token, cfg)
            if ok:
                ok_count += 1
            time.sleep(0.5)
        else:
            ok_count += 1

    if args.apply:
        print(f"\n  Result: {ok_count}/{len(pending)} feedback left successfully.")
    else:
        print(f"\n  Dry run: would leave feedback for {ok_count} buyer(s). Add --apply to post.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
