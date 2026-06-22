#!/bin/zsh
# cron_site_refresh.sh — scheduled refresh of the public JC2 Cards showcase pages.
# Pulls latest, refreshes the eBay snapshot, recomputes the showcase stats
# (engine.html + stats.html), then commits and pushes to GitHub Pages.
# Wired to launchd (see com.jc2cards.siterefresh.plist). Logs to output/site_refresh.log.

export PATH="/Users/jason.chletsos/.pyenv/shims:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
REPO="/Users/jason.chletsos/Documents/GitHub/jason_chletsos_ebay_lots"
LOG="$REPO/output/site_refresh.log"
cd "$REPO" || exit 1

echo "===== site refresh $(date '+%Y-%m-%d %H:%M:%S %Z') =====" >> "$LOG"

# 1. get latest so we generate on top of any remote 'Site refresh' commits
git pull --rebase --autostash origin main >> "$LOG" 2>&1

# 2. refresh eBay snapshot (uses creds in configuration.json) then recompute stats
python3 refresh_snapshot.py >> "$LOG" 2>&1
python3 update_site_stats.py >> "$LOG" 2>&1

# 3. commit + push only the showcase pages (and the snapshot for next run)
git add docs/engine.html docs/stats.html output/listings_snapshot.json >> "$LOG" 2>&1
if git diff --cached --quiet; then
  echo "no changes to push" >> "$LOG" 2>&1
else
  git commit -m "Scheduled site stats refresh ($(date '+%Y-%m-%d %H:%M %Z'))" >> "$LOG" 2>&1
  git push origin main >> "$LOG" 2>&1 && echo "pushed OK" >> "$LOG" 2>&1 || echo "PUSH FAILED" >> "$LOG" 2>&1
fi
echo "" >> "$LOG"
