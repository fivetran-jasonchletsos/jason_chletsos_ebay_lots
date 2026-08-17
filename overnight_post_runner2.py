"""One-shot: wait for the Trading quota reset, post the 8 round-two mystery
pulls (7-card batch + Bucky copy 2 via --force duplicate title), then pull
fresh orders to backfill the blackout, and commit. See overnight_post_runner.py
for the pattern (2026-08-16 night edition)."""
import json, subprocess, sys, time
from pathlib import Path
import ebay_client, paths
from post_from_scan import upload_image

REPO = Path(__file__).parent
LOG = REPO / "output" / "overnight_post_log.txt"

def log(msg):
    line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(line, flush=True)
    with open(LOG, "a") as f: f.write(line + "\n")

def quota_open():
    cfg = json.loads(Path(paths.CONFIG).read_text())
    token = ebay_client.get_write_token(cfg)
    try:
        upload_image(Path("/tmp/myst_crop/theismann_chrome.jpg"), token, cfg)
        return True
    except RuntimeError as e:
        if "usage limit" in str(e): return False
        raise

def run(cmd, label):
    log(f"START {label}")
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=REPO, timeout=3600)
    log(f"DONE {label} (exit {r.returncode}):\n" + "\n".join((r.stdout + r.stderr).splitlines()[-8:]))

log("=== night runner 2 started; probing every 30 min ===")
waited = 0
while waited < 12 * 3600:
    try:
        if quota_open():
            log("QUOTA OPEN")
            break
    except Exception as e:
        log(f"probe error: {e}")
    time.sleep(1800); waited += 1800
else:
    log("gave up after 12h"); sys.exit(1)

py = sys.executable

def run_until_real(cmd, label):
    """A lone probe success can be a fluke (2026-08-16 20:58: one upload
    slipped through, the next call hit 518 again and the runner burned its
    whole sequence on failures). Retry the step itself until it stops dying
    on the usage limit."""
    while True:
        log(f"START {label}")
        r = subprocess.run(cmd, capture_output=True, text=True, cwd=REPO, timeout=3600)
        out = r.stdout + r.stderr
        log(f"DONE {label} (exit {r.returncode}):\n" + "\n".join(out.splitlines()[-8:]))
        if "usage limit" not in out:
            return r
        log(f"{label}: quota still capped -- back to waiting 30 min")
        time.sleep(1800)

run_until_real([py, "post_from_scan.py", "--batch", "output/_post_mystery2_batch_2026_08_16.json", "--apply"], "mystery2 batch")
run_until_real([py, "post_from_scan.py", "--image", "/tmp/myst_crop/bucky_chrome_2.jpg",
     "--title", "2024 Topps Chrome Bucky Irving RC Tampa Bay Buccaneers",
     "--price", "4.00", "--apply", "--force"], "Bucky copy 2 (force)")
run([py, "orders_watch_agent.py"], "orders backfill")
run([py, "fix_descriptions.py", "--apply"], "description sweep (finish ~380)")
run([py, "daily_digest_agent.py"], "digest")
subprocess.run(["git", "add", "-A"], cwd=REPO)
subprocess.run(["git", "commit", "-m", "Overnight run 2026-08-17: mystery round-2 posted, orders backfilled, sweep finished\n\nCo-Authored-By: Claude Fable 5 <noreply@anthropic.com>"], cwd=REPO)
subprocess.run(["git", "pull", "--no-edit", "--no-rebase"], cwd=REPO)
subprocess.run(["git", "push"], cwd=REPO)
log("=== night runner 2 complete ===")
