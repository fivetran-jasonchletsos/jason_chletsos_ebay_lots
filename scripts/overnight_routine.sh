#!/bin/bash
# Overnight routine runner — replaces the per-night sed-cloned /tmp/<day>_routine.sh scripts.
# Derives everything from the clock: no per-day editing, one file to maintain.
#
# Usage:
#   scripts/overnight_routine.sh            # run the pipeline immediately
#   scripts/overnight_routine.sh --wait     # sleep until ~3:05am ET first (nohup-friendly)
#
# Known macOS quirk: `sleep` pauses during power nap, so the --wait loop uses
# short 60s sleeps — worst-case start lag after wake is ~1 minute instead of
# the 10-minute stalls the old `sleep 600` loop hit (manual kicks were needed
# on 2026-08-19 and 2026-08-20). A launchd StartCalendarInterval job would be
# strictly better (fires missed jobs on wake, survives reboot); template not
# installed — needs JC's explicit OK for auto-run persistence.

cd /Users/jason.chletsos/Documents/GitHub/jason_chletsos_ebay_lots || exit 1

if [ "$1" = "--wait" ]; then
  # Wait for the ~3am ET quota reset. Guard against an evening launch (hour > 20)
  # starting the run before midnight.
  while [ "$(date +%H%M)" -lt "0305" ] || [ "$(date +%H)" -gt "20" ]; do sleep 60; done
fi

DAY=$(date +%A)
LOG="output/$(echo "$DAY" | tr '[:upper:]' '[:lower:]')_routine_log.txt"

{
echo "=== ${DAY} RUN $(date) ==="
python3 oversell_guard.py --apply 2>&1 | tail -3
python3 sold_reconciler_agent.py --apply 2>&1 | tail -2
python3 _pull_over_60.py --days 30 --apply 2>&1 | tail -2
python3 refresh_snapshot.py 2>&1 | tail -1
python3 inventory_agent.py 2>&1 | tail -2
python3 cassini_score_agent.py 2>&1 | tail -3
python3 photo_audit_agent.py 2>&1 | tail -2
python3 price_consistency_agent.py 2>&1 | tail -2
python3 shipping_audit_agent.py 2>&1 | tail -4
python3 promotions_agent.py 2>&1 | tail -3
python3 best_offer_agent.py 2>&1 | tail -3
python3 card_price_agent.py 2>&1 | tail -2
python3 repricing_agent.py --apply 2>&1 | tail -3
python3 sell_inventory_reprice.py --apply 2>&1 | tail -2
python3 promotions_agent.py --apply 2>&1 | tail -3
python3 relist_agent.py --apply 2>&1 | tail -3
python3 best_offer_agent.py --apply 2>&1 | tail -2
python3 watchers_offer_agent.py --apply 2>&1 | tail -3
python3 promoted_listings_agent.py --apply 2>&1 | tail -4
python3 feedback_agent.py --apply 2>&1 | tail -3
python3 message_responder_agent.py --apply 2>&1 | tail -2
python3 tracking_responder_agent.py --apply 2>&1 | tail -2
python3 buyer_watchlist_agent.py 2>&1 | tail -2
python3 top_sellers_agent.py 2>&1 | tail -2
python3 under_10_agent.py 2>&1 | tail -2
python3 pokemon_news_agent.py 2>&1 | tail -2
python3 returns_agent.py 2>&1 | tail -2
python3 seller_hub_agent.py 2>&1 | tail -2
python3 orders_watch_agent.py 2>&1 | tail -3
python3 listing_performance_agent.py 2>&1 | tail -2
python3 pnl_agent.py 2>&1 | tail -1
python3 site_health_agent.py 2>&1 | tail -2
python3 daily_digest_agent.py 2>&1 | tail -4
git add -A
git commit -m "${DAY} routine outputs $(date +%F)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>" | tail -1
# Generated-state JSONs conflict routinely; local machine state wins.
git pull --no-edit --no-rebase -X ours 2>&1 | tail -1
git push 2>&1 | tail -1
} >> "$LOG" 2>&1
