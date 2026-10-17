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


def run_cmd(cmd, cwd=None, timeout=15, warn=True):
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=timeout, cwd=cwd,
                           text=True, encoding="utf-8", errors="replace")
        if warn and r.returncode != 0 and r.stderr.strip():
            tail = r.stderr.strip().splitlines()[-1][:200]
            print(f"[git] `{cmd[0]}` failed (rc={r.returncode}): {tail}")
        return r.returncode == 0, r.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as e:
        if warn:
            print(f"[git] `{cmd[0]}` failed: {e}")
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
    ap.add_argument("--very-stale-hours", type=int, default=720,
                    help="hours since creation to flag staleness by age alone "
                         "(default 720 = 30 days; age alone never escalates "
                         "past SLIGHTLY_STALE)")
    ap.add_argument("--slightly-files", type=int, default=5,
                    help="files changed to flag SLIGHTLY_STALE (default 5)")
    ap.add_argument("--stale-files", type=int, default=15,
                    help="files changed to flag STALE (default 15)")
    ap.add_argument("--strict", action="store_true",
                    help="exit code mirrors the level: 0 FRESH, 10 "
                         "SLIGHTLY_STALE, 20 STALE, 30 VERY_STALE — the level "
                         "codes can never collide with the operational codes "
                         "(1 file missing, 2 not a git repo / usage error)")
    args = ap.parse_args()

    path = Path(args.handoff)
    if not path.exists():
        print(f"Error: {path} not found")
        sys.exit(1)
    meta = parse_meta(path.read_text(encoding="utf-8", errors="replace"))
    root = find_project_root(path)

    ok, _ = run_cmd(["git", "rev-parse", "--git-dir"], cwd=root, warn=False)
    if not ok:
        print("VERY_STALE — not a git repo anymore; cannot verify anything. "
              "Treat the handoff as untrusted and rebuild it.")
        sys.exit(2)

    ok, cur_branch = run_cmd(["git", "branch", "--show-current"], cwd=root,
                             warn=False)
    # Detached HEAD exits 0 with empty output — the old `if ok` fallback was
    # dead code and left cur_branch as "" (never matching the doc branch).
    cur_branch = cur_branch if ok and cur_branch.strip() else "(detached)"
    branch_match = meta.get("branch") == cur_branch
    ok_head, cur_head = run_cmd(["git", "rev-parse", "--short", "HEAD"],
                                cwd=root, warn=False)

    doc_head = meta.get("head", "")
    commits_since = None
    files_changed = None
    if doc_head and doc_head not in ("(no commits yet)", "(detached or no branch)"):
        # rev-list A..B happily succeeds when A's object still exists but is no
        # longer an ancestor of HEAD (orphan branch, rebase, amend) — it just
        # counts as if A were an excluded root. Ask ancestry explicitly first;
        # only a true ancestor may feed the counters below.
        ok_anc, _ = run_cmd(["git", "merge-base", "--is-ancestor", doc_head, "HEAD"],
                            cwd=root, warn=False)
        if not ok_anc:
            commits_since = None  # doc head not reachable from current history
        else:
            ok_cnt, cnt = run_cmd(["git", "rev-list", "--count", f"{doc_head}..HEAD"],
                                  cwd=root)
            commits_since = int(cnt) if ok_cnt and cnt else None
            # A failed diff used to read as files_changed=0 and could mask a
            # huge change surface; None now keeps the file thresholds from
            # downgrading the level, and the report says so.
            ok_fc, fc = run_cmd(["git", "diff", "--name-only", f"{doc_head}..HEAD"],
                                cwd=root)
            files_changed = len(fc.splitlines()) if ok_fc else None

    # Parse the Created line timezone-aware when present (create_handoff now
    # writes "%Y-%m-%d %H:%M:%S %z"): a doc written on a UTC+8 machine used to
    # get a ~-8h "age" on a UTC machine and silently pass every check. Older
    # naive timestamps fall back to local time; when the line is missing or
    # garbled, the kit directory name (YYYY-MM-DD-HHMMSS-slug) is used instead
    # of silently disabling age checks.
    created = None
    age_src = "doc"
    if meta.get("created"):
        for fmt in ("%Y-%m-%d %H:%M:%S %z", "%Y-%m-%d %H:%M:%S"):
            try:
                created = datetime.strptime(meta["created"], fmt)
                break
            except ValueError:
                continue
        if created is None:
            age_src = "kit-dir"
    if created is None:
        m = re.match(r"(\d{4}-\d{2}-\d{2})-(\d{6})", path.parent.name)
        if m:
            try:
                created = datetime.strptime(m.group(1) + "-" + m.group(2),
                                            "%Y-%m-%d-%H%M%S")
                age_src = "kit-dir"
            except ValueError:
                created = None
    age_hours = None
    if created is not None:
        now_local = (datetime.now(created.tzinfo) if created.tzinfo
                     else datetime.now())
        age_hours = (now_local - created).total_seconds() / 3600

    print("== Staleness Report ==")
    print(f"  doc branch : {meta.get('branch', '?')}")
    print(f"  cur  branch: {cur_branch}  match={branch_match}")
    print(f"  doc HEAD   : {doc_head or '?'}")
    print(f"  cur  HEAD  : {cur_head if ok_head and cur_head else '?'}")
    print(f"  commits since handoff : {commits_since if commits_since is not None else 'UNKNOWN (head unreachable)'}")
    print(f"  files changed since   : {files_changed if files_changed is not None else '? (diff failed or unreachable)'}")
    print(f"  age: {round(age_hours, 1) if age_hours is not None else '?'} hours"
          f"  (source: {age_src})")

    reasons, level = [], "FRESH"
    if commits_since is None:
        level = "VERY_STALE"
        reasons.append("documented HEAD is not reachable from current history (rebase/rewrite?)")
    else:
        fc_txt = ("?" if files_changed is None else str(files_changed))
        if not branch_match:
            level = "STALE"
            reasons.append(f"branch drifted: {meta.get('branch')} -> {cur_branch}")
        if commits_since >= args.very_stale_commits:
            level = "VERY_STALE"
            reasons.append(f"{commits_since} commits since handoff")
        elif commits_since >= args.stale_commits or (
                files_changed is not None and files_changed >= args.stale_files):
            # Reaching this branch via the file-count threshold alone is still a
            # large diff surface ("明显变化") — it must not downgrade to
            # SLIGHTLY_STALE just because the commit count is low (squash/rebase
            # style histories commonly look exactly like that).
            if level != "VERY_STALE":
                level = "STALE"
            reasons.append(f"{commits_since} commits / {fc_txt} files changed")
        elif commits_since >= args.slightly_commits or (
                files_changed is not None and files_changed >= args.slightly_files):
            if level == "FRESH":
                level = "SLIGHTLY_STALE"
            reasons.append(f"{commits_since} commits / {fc_txt} files changed")
        elif files_changed is None:
            reasons.append("changed-files unknown (diff failed) — file-based "
                           "thresholds skipped, commit/time checks still apply")
    if age_hours is not None and age_hours >= args.very_stale_hours:
        if level == "FRESH":
            level = "SLIGHTLY_STALE"
        reasons.append(f"handoff is {round(age_hours / 24)} days old")
    if age_hours is not None and age_hours < -1:
        reasons.append("document timestamp lies in the future — the creating "
                       "machine ran a different clock/timezone; treat ages as "
                       "unreliable")

    # referenced files still present?
    refs = re.findall(r'`([a-zA-Z0-9_\-./]+\.[a-zA-Z0-9]{1,4})`',
                      path.read_text(encoding="utf-8", errors="replace"))
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
        # Level codes live at 10/20/30 so they can never collide with the
        # operational codes (1 missing file, 2 not-a-repo / argparse usage):
        # SLIGHTLY_STALE used to exit 1 — indistinguishable from a missing
        # file for any CI that only looks at exit status.
        sys.exit({"FRESH": 0, "SLIGHTLY_STALE": 10,
                  "STALE": 20, "VERY_STALE": 30}[level])
    sys.exit(0)


if __name__ == "__main__":
    main()
