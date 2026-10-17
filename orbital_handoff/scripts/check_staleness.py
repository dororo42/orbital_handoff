#!/usr/bin/env python3
"""
orbital_handoff: staleness check for an existing HANDOFF.md.

Compares the handoff document's recorded git state against the current
repository state and rates freshness:
  FRESH | SLIGHTLY_STALE | STALE | VERY_STALE

Usage: python3 check_staleness.py handoffs/<kit>/HANDOFF.md
       python3 check_staleness.py handoffs/<kit>/HANDOFF.md --strict
"""

import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
import argparse


def find_project_root(handoff_path):
    """Resolve the project root from a HANDOFF.md path.

    Prefers the ancestor that contains a `handoffs/` directory, then the
    nearest ancestor with a `.git`, finally best-effort to the file's parent.
    """
    p = Path(handoff_path).resolve()
    for anc in [p, *p.parents]:
        if anc.name == "handoffs" and p.is_relative_to(anc):
            return anc.parent
    for anc in [p, *p.parents]:
        if (anc / ".git").exists():
            return anc
    return p.parent


def run_cmd(cmd, cwd=None, timeout=15):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd, timeout=timeout)
        return r.returncode == 0, r.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return False, ""


def parse_meta(content):
    out = {}
    for key, pattern in (
        ("branch", r"(?:^|\n)-\s*Branch:\s*(.+)"),
        ("head", r"(?:^|\n)-\s*HEAD:\s*([0-9a-f]+)"),
        ("created", r"(?:^|\n)-\s*Created:\s*(.+)"),
    ):
        m = re.search(pattern, content)
        if m:
            out[key] = m.group(1).strip()
    return out


def main():
    ap = argparse.ArgumentParser(description="Rate handoff freshness vs current repo")
    ap.add_argument("handoff", help="path to HANDOFF.md")
    ap.add_argument("--slightly-commits", type=int, default=5,
                    help="commits since handoff to flag SLIGHTLY_STALE (default 5)")
    ap.add_argument("--stale-commits", type=int, default=20,
                    help="commits since handoff to flag STALE (default 20)")
    ap.add_argument("--very-stale-commits", type=int, default=100,
                    help="commits since handoff to flag VERY_STALE (default 100)")
    ap.add_argument("--slightly-files", type=int, default=5,
                    help="files changed to flag SLIGHTLY_STALE (default 5)")
    ap.add_argument("--stale-files", type=int, default=15,
                    help="files changed to flag STALE (default 15)")
    ap.add_argument("--strict", action="store_true",
                    help="exit code mirrors the level: 0 FRESH, 1 SLIGHTLY_STALE, "
                         "2 STALE, 3 VERY_STALE (the not-a-repo case still exits 2)")
    args = ap.parse_args()

    path = Path(args.handoff)
    if not path.exists():
        print(f"Error: {path} not found")
        sys.exit(1)
    meta = parse_meta(path.read_text(encoding="utf-8"))
    root = find_project_root(path)

    ok, _ = run_cmd(["git", "rev-parse", "--git-dir"], cwd=root)
    if not ok:
        print("VERY_STALE — not a git repo anymore; cannot verify anything. "
              "Treat the handoff as untrusted and rebuild it.")
        sys.exit(2)

    ok, cur_branch = run_cmd(["git", "branch", "--show-current"], cwd=root)
    cur_branch = cur_branch if ok else "(detached)"
    branch_match = meta.get("branch") == cur_branch

    doc_head = meta.get("head", "")
    commits_since = None
    files_changed = None
    if doc_head and doc_head not in ("(no commits yet)", "(detached or no branch)"):
        # rev-list A..B happily succeeds when A's object still exists but is no
        # longer an ancestor of HEAD (orphan branch, rebase, amend) — it just
        # counts as if A were an excluded root. Ask ancestry explicitly first;
        # only a true ancestor may feed the counters below.
        ok_anc, _ = run_cmd(["git", "merge-base", "--is-ancestor", doc_head, "HEAD"],
                            cwd=root)
        if not ok_anc:
            commits_since = None  # doc head not reachable from current history
        else:
            ok, cnt = run_cmd(["git", "rev-list", "--count", f"{doc_head}..HEAD"],
                              cwd=root)
            commits_since = int(cnt) if ok and cnt else None
            ok, fc = run_cmd(["git", "diff", "--name-only", f"{doc_head}..HEAD"],
                             cwd=root)
            files_changed = len(fc.split("\n")) if ok and fc else 0

    age_hours = None
    if meta.get("created"):
        try:
            created = datetime.strptime(meta["created"], "%Y-%m-%d %H:%M:%S")
            age_hours = (datetime.now() - created).total_seconds() / 3600
        except ValueError:
            pass

    print("== Staleness Report ==")
    print(f"  doc branch : {meta.get('branch', '?')}")
    print(f"  cur  branch: {cur_branch}  match={branch_match}")
    print(f"  doc HEAD   : {doc_head or '?'}")
    print(f"  commits since handoff : {commits_since if commits_since is not None else 'UNKNOWN (head unreachable)'}")
    print(f"  files changed since   : {files_changed if files_changed is not None else '?'}")
    print(f"  age: {round(age_hours, 1) if age_hours is not None else '?'} hours")

    reasons, level = [], "FRESH"
    if commits_since is None:
        level = "VERY_STALE"
        reasons.append("documented HEAD is not reachable from current history (rebase/rewrite?)")
    else:
        if not branch_match:
            level = "STALE"
            reasons.append(f"branch drifted: {meta.get('branch')} -> {cur_branch}")
        if commits_since > args.very_stale_commits:
            level = "VERY_STALE"
            reasons.append(f"{commits_since} commits since handoff")
        elif commits_since > args.stale_commits or (files_changed or 0) > args.stale_files:
            # Reaching this branch via the file-count threshold alone is still a
            # large diff surface ("明显变化") — it must not downgrade to
            # SLIGHTLY_STALE just because the commit count is low (squash/rebase
            # style histories commonly look exactly like that).
            if level != "VERY_STALE":
                level = "STALE"
            reasons.append(f"{commits_since} commits / {files_changed} files changed")
        elif commits_since > args.slightly_commits or (files_changed or 0) > args.slightly_files:
            if level == "FRESH":
                level = "SLIGHTLY_STALE"
            reasons.append(f"{commits_since} commits / {files_changed} files changed")
    if age_hours is not None and age_hours > 24 * 30:
        if level == "FRESH":
            level = "SLIGHTLY_STALE"
        reasons.append(f"handoff is {round(age_hours / 24)} days old")

    # referenced files still present?
    refs = re.findall(r'`([a-zA-Z0-9_\-./]+\.[a-zA-Z0-9]{1,4})`',
                      path.read_text(encoding="utf-8"))
    lost = [f for f in set(refs)
            if "/" in f and not f.startswith("http") and not f.endswith(".md")
            and not (root / f).exists()]
    if lost:
        level = "VERY_STALE"
        reasons.append(f"referenced files no longer exist: {', '.join(lost[:5])}")

    print(f"\nLevel: {level}")
    for r in reasons:
        print(f"  - {r}")
    advice = {
        "FRESH": "safe to resume directly from the handoff",
        "SLIGHTLY_STALE": "review new commits first, then resume",
        "STALE": "verify documented assumptions one by one before resuming",
        "VERY_STALE": "consider discarding this handoff and creating a fresh one",
    }
    print(f"Advice: {advice[level]}")
    if args.strict:
        sys.exit({"FRESH": 0, "SLIGHTLY_STALE": 1, "STALE": 2, "VERY_STALE": 3}[level])
    sys.exit(0)


if __name__ == "__main__":
    main()
