#!/usr/bin/env python3
"""
orbital_handoff: validate a HANDOFF.md for completeness and safety.

Checks: TODO placeholders, required/recommended sections, secret patterns,
file references, quality score, broken chain links ('Continues from' target
missing/unreadable), git-tracking policy (a tracked handoff document is a
policy violation — handoff docs never leave the machine), and whether
unresolved items from the previous handoff carry a done/blocked/moved outcome.
Exit 0 (READY) only when: no secrets, no [TODO] placeholders left, all
required sections complete, and score >= 70 — a leftover template scaffold
with [FAIL] lines must never read as READY. Exit 1 otherwise; undecodable or
oversized input is refused outright (fail closed).

Usage: python3 validate_handoff.py handoffs/<kit>/HANDOFF.md
"""

import re
import subprocess
import sys
from pathlib import Path

SECRET_PATTERNS = [
    # _kv shapes accept quoted AND bare values: `api_key: sk-...` without
    # quotes used to escape detection entirely. The key-name prefix is
    # bounded ({0,32}) and bare values carry a higher length floor than
    # quoted ones — an unbounded `[a-zA-Z_]*` prefix went quadratic on a
    # crafted all-letters line even inside the per-line scan window.
    (r'["\']?[a-zA-Z_]{0,32}api[_-]?key["\']?\s*[:=]\s*(?:"[^"\']{10,}"|\'[^\'\n]{10,}\'|[^\s"\'#]{10,})',
     "API key"),
    (r'["\']?[a-zA-Z_]{0,32}password["\']?\s*[:=]\s*(?:"[^"\']{2,}"|\'[^\'\n]{2,}\'|[^\s"\'#]{6,})',
     "Password"),
    (r'["\']?[a-zA-Z_]{0,32}secret["\']?\s*[:=]\s*(?:"[^"\']{10,}"|\'[^\'\n]{10,}\'|[^\s"\'#]{10,})',
     "Secret"),
    (r'["\']?[a-zA-Z_]{0,32}token["\']?\s*[:=]\s*(?:"[^"\']{20,}"|\'[^\'\n]{20,}\'|[^\s"\'#]{20,})',
     "Token"),
    (r'-----BEGIN [A-Z]+ PRIVATE KEY-----', "PEM private key"),
    # URL forms: literal scheme prefixes anchor the match, and bounded
    # classes keep backtracking finite — the unbounded `[^/\s:@]+:[^@\s]+@`
    # form went quadratic and stalled validation for minutes on a single
    # crafted line (measured >120 s on ~600 KB).
    (r'mongodb(\+srv)?://[^/\s:@]{1,128}:[^@\s]{1,256}@', "MongoDB URL with password"),
    (r'postgres(ql)?://[^/\s:@]{1,128}:[^@\s]{1,256}@', "PostgreSQL URL with password"),
    (r'mysql://[^/\s:@]{1,128}:[^@\s]{1,256}@', "MySQL URL with password"),
    (r'\b[a-zA-Z][a-zA-Z0-9+.\-]{0,31}://[^/\s:@]{1,128}:[^@\s]{1,256}@',
     "URL with embedded credentials"),
    # The remaining classes are bounded for the same reason: an adversarial
    # line of near-miss prefixes must degrade linearly, not quadratically.
    (r'Bearer\s+[a-zA-Z0-9_\-\.]{20,256}', "Bearer token"),
    (r'ghp_[a-zA-Z0-9]{36}', "GitHub PAT"),
    (r'github_pat_[a-zA-Z0-9_]{22,256}', "GitHub fine-grained PAT"),
    # Hyphen/underscore permissive: Anthropic-style keys (sk-ant-api03-…)
    # escape a strictly-alphanumeric character class.
    (r'sk-[a-zA-Z0-9\-_]{40,256}', "OpenAI/Anthropic-style API key"),
    (r'xox[baprs]-[a-zA-Z0-9\-]{1,256}', "Slack token"),
    (r'[a-f0-9]{32}\.[a-f0-9]{16}', "Zhipu-style key (id.secret)"),
    (r'eyJ[A-Za-z0-9_\-]{10,512}\.[A-Za-z0-9_\-]{10,512}\.[A-Za-z0-9_\-]{5,512}',
     "JWT (JSON Web Token)"),
    (r'AKIA[0-9A-Z]{16}', "AWS access key id"),
    (r'AIza[0-9A-Za-z_\-]{35}', "Google API key"),
]

REQUIRED = ["当前状态摘要", "重要上下文", "立即下一步"]
RECOMMENDED = ["关键文件", "决策记录", "假设", "已知坑", "构建 / 运行 / 测试命令", "元数据"]

MAX_DOC_BYTES = 4 * 1024 * 1024   # a handoff doc is a human document; refuse bigger
MAX_SCAN_LINE = 8192              # per-line cap: bounds regex backtracking (ReDoS)
MAX_PREV_BYTES = 1024 * 1024      # closed-loop read cap for the previous doc

# An unchecked item counts as closed only with an explicit outcome marker on
# (or right after) its line — "mentioned somewhere in the doc" used to pass
# the closed-loop check, which contradicted the documented convention.
OUTCOME_RE = re.compile(r"结局:\s*\[?(done|blocked|moved)\b", re.IGNORECASE)


def find_project_root(handoff_path):
    """Resolve the project root from a HANDOFF.md path.

    Prefers the ancestor that contains a `handoffs/` directory (where the
    HANDOFF.md lives under handoffs/<kit>/), then falls back to the nearest
    ancestor with a `.git`, and finally best-effort to the file's parent.
    """
    p = Path(handoff_path).resolve()
    for anc in [p, *p.parents]:
        if anc.name == "handoffs" and p.is_relative_to(anc):
            return anc.parent
    for anc in [p, *p.parents]:
        if (anc / ".git").exists():
            return anc
    return p.parent


def section_content(content, title):
    m = re.search(rf'(?:^|\n)##+\s*{re.escape(title)}', content)
    if not m:
        return None
    start = m.end()
    nxt = re.search(r'\n##+\s+', content[start:])
    end = start + nxt.start() if nxt else len(content)
    return content[start:end].strip()


def _prev_unresolved_items(prev_text):
    """Unchecked task items in a previous handoff, as short key strings."""
    items = []
    for ln in prev_text.splitlines():
        m = re.match(r"\s*-\s*\[\s*\]\s*(.+)", ln)
        if not m:
            continue
        text = re.sub(r"\[TODO[^\]]*\]", "", m.group(1)).strip(" -—→")
        if len(text) >= 6:
            items.append(text)
    return items


def check_previous_handover(content, base):
    """Best-effort closed loop across the handoff chain.

    Every unchecked '- [ ]' item in the previous handoff (the one this doc's
    chain points at via 'Continues from') must reappear in this document with
    an outcome (done / blocked / moved) — otherwise tasks silently drift
    across generations. Returns (unaccounted, prev_ref|None, chain_error|None,
    mentioned_no_outcome).

    Hardening over the first cut:
    - the reference is only read when it resolves INSIDE the project root —
      the field used to accept any path on disk, an arbitrary-read vector
      for a document that is untrusted input;
    - the previous doc is decoded leniently (errors="replace") and capped in
      size: a GBK-encoded predecessor used to kill the whole validation with
      a bare UnicodeDecodeError traceback;
    - mere mention no longer closes an item: the current doc must carry an
      explicit `→ 结局: done/blocked/moved` marker on or right after the
      item line (the convention the templates document). Such items are
      reported separately and cost less than fully unaccounted ones.
    """
    m = re.search(r"Continues from\*\*:\s*`([^`]+)`", content)
    if not m:
        return [], None, None, []
    prev_ref = m.group(1).strip()
    prev_path = Path(prev_ref)
    if not prev_path.is_absolute():
        prev_path = base / prev_ref
    try:
        prev_path = prev_path.resolve(strict=False)
    except OSError:
        return [], prev_ref, f"Continues from cannot be resolved: {prev_ref}", []
    root_res = base.resolve()
    if root_res != prev_path and root_res not in prev_path.parents:
        return [], prev_ref, (f"Continues from escapes the project root: {prev_ref} "
                              "— refusing to read outside the project"), []
    if not prev_path.exists():
        return [], prev_ref, (f"Continues from points to a missing file: {prev_ref} "
                              "— broken chain, closed-loop check skipped"), []
    try:
        prev_text = prev_path.read_bytes()[:MAX_PREV_BYTES].decode(
            "utf-8", errors="replace")
    except OSError:
        return [], prev_ref, (f"Continues from target is unreadable: {prev_ref} "
                              "— closed-loop check skipped"), []
    raw_lines = content.splitlines()
    norm_lines = [re.sub(r"\s+", "", ln) for ln in raw_lines]
    unaccounted, no_outcome = [], []
    for item in _prev_unresolved_items(prev_text):
        key = re.sub(r"\s+", "", item)[:14]
        if not key:
            continue
        hits = [i for i, ln in enumerate(norm_lines) if key in ln]
        if not hits:
            unaccounted.append(item[:60])
            continue
        closed = any(
            OUTCOME_RE.search(raw_lines[i])
            or (i + 1 < len(raw_lines) and OUTCOME_RE.search(raw_lines[i + 1]))
            for i in hits)
        if not closed:
            no_outcome.append(item[:60])
    return unaccounted, prev_ref, None, no_outcome


def git_tracked(path, base):
    """True when the handoff document is known to git (index or HEAD).

    orbital_handoff policy: handoff documents never leave the machine, so a
    tracked handoff is one `git push` away from leaking. Best-effort: any git
    failure counts as 'not tracked' (this is a policy tripwire, not a gate).
    """
    if not (base / ".git").exists():
        return False
    try:
        rel = path.resolve().relative_to(base.resolve())
    except ValueError:
        return False
    try:
        r = subprocess.run(["git", "ls-files", "--", str(rel)], cwd=str(base),
                           capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return bool(r.stdout.strip())


def scan_secrets(content):
    """Per-line secret scan with a per-line length cap.

    The scan used to run every pattern over the whole document at once: a
    single crafted long line could stall the regex engine for minutes
    (catastrophic backtracking on the credential-URL pattern). Scanning
    per-line with a cap bounds every pattern's input. Overlong lines are
    scanned for their first MAX_SCAN_LINE chars and the truncation is
    reported, never silent.
    """
    found, overlong = [], 0
    for ln in content.splitlines():
        if len(ln) > MAX_SCAN_LINE:
            ln = ln[:MAX_SCAN_LINE]
            overlong += 1
        for pat, desc in SECRET_PATTERNS:
            if desc not in found and re.search(pat, ln, re.IGNORECASE):
                found.append(desc)
    return [(d, "pattern matched") for d in found], overlong


def validate(filepath):
    path = Path(filepath)
    if not path.exists():
        return {"error": f"file not found: {filepath}"}
    try:
        size = path.stat().st_size
    except OSError as e:
        return {"error": f"unreadable: {e}"}
    if size > MAX_DOC_BYTES:
        return {"error": f"file too large ({size} bytes; limit {MAX_DOC_BYTES}) — "
                         "a handoff doc is a human document; trim it or "
                         "investigate before validating"}
    try:
        content = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        # Fail closed: mojibake can mask secrets, so this is BLOCKED-grade,
        # not a warning. (A GBK-encoded doc used to crash with a traceback.)
        return {"error": "document is not valid UTF-8 — cannot scan reliably "
                         "(undecodable bytes can mask secrets); re-encode it "
                         "as UTF-8 and re-run"}
    base = find_project_root(path)  # handoffs/<kit>/HANDOFF.md -> project root

    todos = re.findall(r'\[TODO[^\]]*\]', content)
    missing_req = []
    for sec in REQUIRED:
        c = section_content(content, sec)
        if c is None:
            missing_req.append(f"{sec} (missing)")
        elif len(c) < 30 or "[TODO" in c:
            missing_req.append(f"{sec} (incomplete)")
    missing_rec = [s for s in RECOMMENDED if section_content(content, s) is None]

    secrets, overlong_lines = scan_secrets(content)

    # file references like `src/x.rs` or `path/to/file.rs:88`
    refs = set()
    for pat in (r'`([a-zA-Z0-9_./~{}\-]+\.[a-zA-Z0-9]{1,4}(?::\d+)?)`',
                r'\|\s*([a-zA-Z0-9_./~{}\-]+\.[a-zA-Z0-9]{1,4}:\d+)\s*\|'):
        for m in re.findall(pat, content):
            f = m.split(":")[0]
            if "/" in f and not f.startswith("http") and not f.endswith(".md"):
                refs.add(f)
    files_missing, placeholder_refs = [], []
    for f in sorted(refs):
        if "{" in f:
            placeholder_refs.append(f)  # unresolved template placeholder
            continue
        target = Path(f).expanduser() if f.startswith("~") else base / f
        if not target.exists():
            files_missing.append(f)
    unaccounted, prev_ref, chain_error, no_outcome = \
        check_previous_handover(content, base)
    tracked = git_tracked(path, base)

    score = 100
    if todos:
        score -= 30
    score -= 10 * len(missing_req)
    if secrets:
        score -= 20
    score -= 5 * min(len(files_missing), 4)
    score -= 5 * min(len(unaccounted), 4)
    score -= 2 * min(len(no_outcome), 4)
    if chain_error:
        score -= 2  # a broken chain link must be visible, never silent
    if tracked:
        score -= 2  # a tracked handoff doc must be visible, never silent
    score -= 2 * len(missing_rec)
    score = max(0, score)

    if score >= 90:
        rating = "Excellent — ready for handoff"
    elif score >= 70:
        rating = "Good — minor gaps"
    elif score >= 50:
        rating = "Fair — needs attention before handoff"
    else:
        rating = "Poor — significant work needed"

    return {"filepath": str(path), "score": score, "rating": rating,
            "todos": todos[:8], "todo_count": len(todos),
            "missing_required": missing_req, "missing_recommended": missing_rec,
            "secrets": secrets, "overlong_lines": overlong_lines,
            "files_checked": len(refs),
            "files_missing": files_missing[:8],
            "placeholder_refs": placeholder_refs[:8],
            "unresolved_from_prev": unaccounted,
            "mentioned_no_outcome": no_outcome,
            "prev_ref": prev_ref, "chain_error": chain_error, "tracked": tracked}


def report(r):
    if "error" in r:
        print(f"Error: {r['error']}")
        return False
    line = "=" * 62
    print(f"\n{line}\nHandoff Validation Report\n{line}")
    print(f"File: {r['filepath']}")
    print(f"\nQuality Score: {r['score']}/100 — {r['rating']}\n{line}")
    if r["todo_count"] == 0:
        print("\n[PASS] no [TODO] placeholders remaining")
    elif r["secrets"]:
        # Echoing TODO lines would leak the very secrets we just flagged.
        print(f"\n[FAIL] {r['todo_count']} [TODO] placeholders "
              "(lines withheld — the document contains secrets)")
    else:
        print(f"\n[FAIL] {r['todo_count']} [TODO] placeholders, e.g.:")
        for t in r["todos"]:
            print(f"       - {t[:60]}")
    if not r["missing_required"]:
        print("[PASS] all required sections complete")
    else:
        print("[FAIL] required sections incomplete:")
        for s in r["missing_required"]:
            print(f"       - {s}")
    if not r["secrets"]:
        print("[PASS] no secret patterns detected")
    else:
        print("[FAIL] potential secrets detected:")
        for d, _ in r["secrets"]:
            print(f"       - {d}")
    if r.get("overlong_lines"):
        print(f"[WARN] {r['overlong_lines']} overlong line(s) — secret scan "
              f"covered only the first {MAX_SCAN_LINE} chars of each")
    if r["files_missing"]:
        print(f"[WARN] referenced files not found: {', '.join(r['files_missing'])}")
    elif r["files_checked"]:
        print(f"[INFO] {r['files_checked']} file reference(s) verified")
    if r.get("placeholder_refs"):
        print(f"[INFO] unresolved placeholder reference(s): "
              f"{', '.join(r['placeholder_refs'])}")
    if r.get("chain_error"):
        print(f"[WARN] {r['chain_error']}")
    if r.get("tracked"):
        print("[WARN] handoff document is git-tracked — policy violation: handoff "
              "docs never leave this machine (fix: git rm -r --cached handoffs/)")
    if r.get("unresolved_from_prev"):
        if r["secrets"]:
            print(f"[WARN] {len(r['unresolved_from_prev'])} unresolved item(s) "
                  f"from the previous handoff ({r.get('prev_ref')}) — items "
                  "withheld (document contains secrets)")
        else:
            print(f"[WARN] {len(r['unresolved_from_prev'])} unresolved item(s) from the "
                  f"previous handoff ({r.get('prev_ref')}) lack an outcome here:")
            for t in r["unresolved_from_prev"]:
                print(f"       - {t}")
    if r.get("mentioned_no_outcome"):
        print(f"[WARN] {len(r['mentioned_no_outcome'])} carried-over item(s) are "
              "mentioned but carry no `→ 结局: done/blocked/moved` marker:")
        for t in r["mentioned_no_outcome"]:
            print(f"       - {t[:60]}")
    if r["missing_recommended"]:
        print(f"[INFO] consider adding: {', '.join(r['missing_recommended'])}")
    print(f"{line}")
    if r["secrets"]:
        print("Verdict: BLOCKED — remove secrets before handoff")
        return False
    if r["todo_count"] or r["missing_required"]:
        # A leftover template scaffold must not read as READY: one [TODO]
        # used to land at exactly 70 and pass with [FAIL] lines printed above.
        print("Verdict: NEEDS WORK — fill every [TODO] and complete required "
              "sections before handoff")
        return False
    if r["score"] >= 70:
        print("Verdict: READY for handoff")
        return True
    print("Verdict: NEEDS WORK — quality score below 70")
    return False


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 validate_handoff.py <HANDOFF.md>")
        sys.exit(1)
    ok = report(validate(sys.argv[1]))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
