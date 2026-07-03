"""publish_pages.py — push the two showcase pages to GitHub via the Contents API.

Updating just docs/engine.html + docs/stats.html through the API (last-write-wins
on those exact files) avoids all git working-tree / rebase conflicts, which makes
it safe to run unattended on a schedule even while the repo has other churn.

Auth token is read from the existing `origin` remote URL (https://<token>@github.com/...).
Run after update_site_stats.py.
"""
from __future__ import annotations
import base64, json, re, subprocess, sys, urllib.request, urllib.error
from pathlib import Path

REPO = Path(__file__).parent
FILES = ["docs/engine.html", "docs/stats.html"]
BRANCH = "main"


def _remote_token_and_slug() -> tuple[str, str]:
    url = subprocess.run(["git", "-C", str(REPO), "remote", "get-url", "origin"],
                         capture_output=True, text=True).stdout.strip()
    m = re.match(r"https://([^@]+)@github\.com/(.+?)(?:\.git)?$", url)
    if not m:
        raise SystemExit("origin remote is not an https token URL; cannot publish via API")
    return m.group(1), m.group(2)  # token, "owner/repo"


def _api(method: str, url: str, token: str, body: dict | None = None) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"token {token}")
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("User-Agent", "jc2-site-publish")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return {}
        raise SystemExit(f"GitHub API {method} {url.split('/contents/')[-1]} -> {e.code}: {e.read().decode()[:300]}")


def publish() -> None:
    token, slug = _remote_token_and_slug()
    base = f"https://api.github.com/repos/{slug}/contents/"
    for rel in FILES:
        p = REPO / rel
        if not p.is_file():
            print(f"  skip (missing): {rel}")
            continue
        content_b64 = base64.b64encode(p.read_bytes()).decode()
        url = base + rel
        cur = _api("GET", f"{url}?ref={BRANCH}", token)
        sha = cur.get("sha")
        if sha and cur.get("content"):
            remote_b64 = cur["content"].replace("\n", "")
            if remote_b64 == content_b64:
                print(f"  unchanged: {rel}")
                continue
        body = {"message": f"Scheduled stats refresh: {rel}", "content": content_b64, "branch": BRANCH}
        if sha:
            body["sha"] = sha
        _api("PUT", url, token, body)
        print(f"  published: {rel}")


if __name__ == "__main__":
    publish()
