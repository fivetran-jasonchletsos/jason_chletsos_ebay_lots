"""
overnight_post_runner.py -- one-shot: wait for the Trading API daily quota
reset (midnight PT), then post everything JC approved on 2026-08-15 and
finish the description sweep. Order matters: postings first so the sweep
can never starve them of quota again.

Sequence once the quota probe succeeds:
  1. random-pull batch (14 remaining; Jeanty dupe-blocked automatically)
  2. Judkins Mosaic copy 2 (--force, intentional duplicate title)
  3. Stadium Club batch (16, --sport Baseball)
  4. Resurgence boxes batch (19)
  5. fix_descriptions.py --apply (finish the ~1,260 remaining)
Logs to output/overnight_post_log.txt.
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

import ebay_client
import paths
from post_from_scan import upload_image

REPO = Path(__file__).parent
LOG = REPO / "output" / "overnight_post_log.txt"
PROBE_IMAGE = Path("/tmp/sc_crop/woo_green.jpg")
PROBE_INTERVAL_S = 1800
MAX_WAIT_S = 12 * 3600


def log(msg: str) -> None:
    line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(line, flush=True)
    with open(LOG, "a") as f:
        f.write(line + "\n")


def quota_open() -> bool:
    cfg = json.loads(Path(paths.CONFIG).read_text())
    token = ebay_client.get_write_token(cfg)
    try:
        upload_image(PROBE_IMAGE, token, cfg)
        return True
    except RuntimeError as exc:
        if "usage limit" in str(exc):
            return False
        raise


def run(cmd: list[str], label: str) -> None:
    log(f"START {label}: {' '.join(cmd)}")
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=REPO, timeout=7200)
    tail = "\n".join((r.stdout + r.stderr).splitlines()[-12:])
    log(f"DONE {label} (exit {r.returncode}):\n{tail}")


def main() -> int:
    log("=== overnight runner started; probing quota every 30 min ===")
    waited = 0
    while waited < MAX_WAIT_S:
        try:
            if quota_open():
                log("QUOTA OPEN — starting posting sequence")
                break
        except Exception as exc:
            log(f"probe error (will retry): {exc}")
        time.sleep(PROBE_INTERVAL_S)
        waited += PROBE_INTERVAL_S
    else:
        log("gave up after 12h — quota never opened")
        return 1

    py = sys.executable
    run([py, "post_from_scan.py", "--batch",
         "output/_post_random_batch_2026_08_15.json", "--apply"], "random-pull batch")
    run([py, "post_from_scan.py",
         "--image", "/tmp/rand_crop/judkins_mosaic_2.jpg",
         "--title", "2025 Panini Mosaic Quinshon Judkins RC Cleveland Browns",
         "--price", "4.00", "--apply", "--force"], "Judkins copy 2 (force)")
    run([py, "post_from_scan.py", "--batch",
         "output/_post_stadiumclub_batch_2026_08_15.json",
         "--sport", "Baseball", "--apply"], "Stadium Club batch")
    run([py, "post_from_scan.py", "--batch",
         "output/_post_resurgence_boxes_batch_2026_08_15.json", "--apply"], "Resurgence batch")
    run([py, "fix_descriptions.py", "--apply"], "description sweep (finish)")

    subprocess.run(["git", "add", "-A"], cwd=REPO)
    subprocess.run(["git", "commit", "-m",
                    "Overnight post run 2026-08-16: box-rip + random-pull batches "
                    "posted after quota reset; description sweep finished\n\n"
                    "Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"], cwd=REPO)
    subprocess.run(["git", "pull", "--no-edit", "--no-rebase"], cwd=REPO)
    subprocess.run(["git", "push"], cwd=REPO)
    log("=== overnight runner complete ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
