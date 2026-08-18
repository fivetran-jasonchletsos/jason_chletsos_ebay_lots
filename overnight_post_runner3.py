"""One-shot: wait for the Trading quota reset, post the 52-card Panini wave
(51 batch + Loveland --force duplicate), then run Tuesday's digest refresh
and commit. Uses the retry-through-false-open pattern from runner 2."""
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

def run_until_real(cmd, label):
    while True:
        log(f"START {label}")
        r = subprocess.run(cmd, capture_output=True, text=True, cwd=REPO, timeout=7200)
        out = r.stdout + r.stderr
        log(f"DONE {label} (exit {r.returncode}):\n" + "\n".join(out.splitlines()[-6:]))
        if "usage limit" not in out:
            return r
        log(f"{label}: quota still capped -- waiting 30 min")
        time.sleep(1800)

def quota_open():
    cfg = json.loads(Path(paths.CONFIG).read_text())
    token = ebay_client.get_write_token(cfg)
    try:
        upload_image(Path("docs/panini_boxes_pull_imgs/gibbs_tc.jpg"), token, cfg)
        return True
    except RuntimeError as e:
        if "usage limit" in str(e): return False
        raise

log("=== panini wave runner started; probing every 30 min ===")
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
run_until_real([py, "post_from_scan.py", "--batch", "output/_post_panini_wave_2026_08_18.json", "--apply"], "panini wave (51)")
run_until_real([py, "post_from_scan.py", "--batch", "output/_post_panini_force_2026_08_18.json", "--apply", "--force"], "Loveland copy 2 (force)")
run_until_real([py, "orders_watch_agent.py"], "orders refresh")
run_until_real([py, "daily_digest_agent.py"], "digest")
subprocess.run(["git", "add", "-A"], cwd=REPO)
subprocess.run(["git", "commit", "-m", "Overnight: 52-card Panini wave posted ($237.50)\n\nCo-Authored-By: Claude Fable 5 <noreply@anthropic.com>"], cwd=REPO)
subprocess.run(["git", "pull", "--no-edit", "--no-rebase"], cwd=REPO)
subprocess.run(["git", "push"], cwd=REPO)
log("=== panini wave runner complete ===")
