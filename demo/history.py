#!/usr/bin/env python3
"""demo/history.py: record, from git history, what existed before the hackathon window (2026-10-26) and write demo/facts.json.

Local repos are read with `git -C`; Parts 1 and 4 and the hub are not cloned on this host, so their first and last
commit dates come from `gh api repos/moalborati/<repo>/commits` (read only). Nothing is guessed: a repo that cannot be read
is listed as unread and the build refuses to print the "no code before" claim.
"""
import json
import re
import subprocess
import sys
from pathlib import Path

WINDOW_START = "2026-10-26"
LOCAL = {n: str(Path.home() / f"simon-part-{n}") for n in (2, 3, 5, 6, 7)}
REMOTE = {
    1: "simon-part-1-keyframes", 4: "simon-part-4-animate-keyframes", 0: "simon",
}


def git(repo, *args):
    return subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True).stdout.strip()


def local(repo):
    first = git(repo, "log", "--reverse", "--format=%aI").splitlines()
    if not first:
        return None
    before = int(git(repo, "rev-list", "--count", f"--before={WINDOW_START}T00:00:00Z", "HEAD") or 0)
    return {"first_commit": first[0], "commits": int(git(repo, "rev-list", "--count", "HEAD")), "before_window": before, "source": "git log"}


def remote(name):
    head = subprocess.run(["gh", "api", f"repos/moalborati/{name}/commits?per_page=1", "-i"], capture_output=True, text=True)
    if head.returncode:
        return None
    m = re.search(r'page=(\d+)>; rel="last"', head.stdout)
    pages = int(m.group(1)) if m else 1
    first = subprocess.run(["gh", "api", f"repos/moalborati/{name}/commits?per_page=1&page={pages}", "--jq", ".[0].commit.author.date"], capture_output=True, text=True)
    if first.returncode:
        return None
    return {"first_commit": first.stdout.strip(), "commits": pages, "before_window": 0 if first.stdout.strip() >= WINDOW_START else None, "source": "gh api commits"}


def main():
    repos, unread = {}, []
    for n, path in LOCAL.items():
        r = local(path)
        (repos.__setitem__(f"part-{n}", r) if r else unread.append(f"part-{n}"))
    for n, name in REMOTE.items():
        r = remote(name)
        key = "hub" if n == 0 else f"part-{n}"
        (repos.__setitem__(key, r) if r else unread.append(key))
    pre = [k for k, v in repos.items() if v.get("before_window")]
    facts = {
        "window_start": WINDOW_START,
        "repos": repos,
        "repo_count": len([k for k in repos if k != "hub"]),
        "unread": unread,
        "repos_with_pre_window_commits": pre,
        "no_code_before_window": not pre and not unread,
        "command": "python3 demo/history.py (git -C <repo> log --reverse --format=%aI; gh api repos/moalborati/<repo>/commits for parts 1, 4 and the hub)",
    }
    Path(__file__).with_name("facts.json").write_text(json.dumps(facts, indent=1) + "\n")
    print(json.dumps({k: facts[k] for k in ("repo_count", "unread", "repos_with_pre_window_commits", "no_code_before_window")}))
    return 0 if facts["no_code_before_window"] else 1


if __name__ == "__main__":
    sys.exit(main())
