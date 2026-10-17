#!/usr/bin/env python3
"""
orbital_handoff: validate a HANDOFF.md for completeness and safety.

Checks: TODO placeholders, required/recommended sections, secret patterns,
file references, quality score, and whether unresolved items from the
previous handoff (chain 'Continues from') carry a done/blocked/moved outcome.
Exit 0 only when score >= 70 and no secrets.

Usage: python3 validate_handoff.py handoffs/<kit>/HANDOFF.md
"""

import re
import sys
from pathlib import Path

SECRET_PATTERNS = [
    (r'["\']?[a-zA-Z_]*api[_-]?key["\']?\s*[:=]\s*["\'][^"\']{10,}["\']', "API key"),
    (r'["\']?[a-zA-Z_]*password["\']?\s*[:=]\s*["\'][^"\']+["\']', "Password"),
    (r'["\']?[a-zA-Z_]*secret["\']?\s*[:=]\s*["\'][^"\']{10,}["\']', "Secret"),
    (r'["\']?[a-zA-Z_]*token["\']?\s*[:=]\s*["\'][^"\']{20,}["\']', "Token"),
    (r'-----BEGIN [A-Z]+ PRIVATE KEY-----', "PEM private key"),
    (r'mongodb(\+srv)?://[^/\s]+:[^@\s]+@', "MongoDB URL with password"),
    (r'postgres://[^/\s]+:[^@\s]+@', "PostgreSQL URL with password"),
    (r'mysql://[^/\s]+:[^@\s]+@', "MySQL URL with password"),
    (r'Bearer\s+[a-zA-Z0-9_\-\.]{20,}', "Bearer token"),
    (r'ghp_[a-zA-Z0-9]{36}', "GitHub PAT"),
    (r'github_pat_[a-zA-Z0-9_]{22,}', "GitHub fine-grained PAT"),
    (r'sk-[a-zA-Z0-9]{40,}', "OpenAI-style API key"),
    (r'xox[baprs]-[a-zA-Z0-9-]+', "Slack token"),
    (r'[a-f0-9]{32}\.[a-f0-9]{16}', "Zhipu-style key (id.secret)"),
    (r'eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{5,}', "JWT (JSON Web Token)"),
    (r'AKIA[0-9A-Z]{16}', "AWS access key id"),
    (r'AIza[0-9A-Za-z_\-]{35}', "Google API key"),
]

REQUIRED = ["当前状态摘要", "重要上下文", "立即下一步"]
RECOMMENDED = ["关键文件", "决策记录", "假设", "已知坑", "构建 / 运行 / 测试命令", "元数据"]


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
    across generations. Soft check: a missing or unreadable previous handoff
    is informational, not a penalty; each unaccounted item costs 5 points
    (capped like files_missing). Returns (unaccounted_items, prev_ref|None).
    """
    m = re.search(r"Continues from\*\*:\s*`([^`]+)`", content)
    if not m:
        return [], None
    prev_ref = m.group(1).strip()
    prev_path = Path(prev_ref)
    if not prev_path.is_absolute():
        prev_path = base / prev_ref
    if not prev_path.exists():
        return [], prev_ref
    try:
        prev_text = prev_path.read_text(encoding="utf-8")
    except OSError:
        return [], prev_ref
    norm = re.sub(r"\s+", "", content)
    unaccounted = []
    for item in _prev_unresolved_items(prev_text):
        key = re.sub(r"\s+", "", item)[:14]
        if key and key not in norm:
            unaccounted.append(item[:60])
    return unaccounted, prev_ref


def validate(filepath):
    path = Path(filepath)
    if not path.exists():
        return {"error": f"file not found: {filepath}"}
    content = path.read_text(encoding="utf-8")
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

    secrets = [(d, "pattern matched") for p, d in SECRET_PATTERNS
               if re.search(p, content, re.IGNORECASE)]

    # file references like `src/x.rs` or `path/to/file.rs:88`
    refs = set()
    for pat in (r'`([a-zA-Z0-9_./-]+\.[a-zA-Z0-9]{1,4}(?::\d+)?)`',
                r'\|\s*([a-zA-Z0-9_./-]+\.[a-zA-Z0-9]{1,4}:\d+)\s*\|'):
        for m in re.findall(pat, content):
            f = m.split(":")[0]
            if "/" in f and not f.startswith("http") and not f.endswith(".md"):
                refs.add(f)
    files_missing = [f for f in sorted(refs) if not (base / f).exists()]
    unaccounted, prev_ref = check_previous_handover(content, base)

    score = 100
    if todos:
        score -= 30
    score -= 10 * len(missing_req)
    if secrets:
        score -= 20
    score -= 5 * min(len(files_missing), 4)
    score -= 5 * min(len(unaccounted), 4)
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
            "secrets": secrets, "files_checked": len(refs),
            "files_missing": files_missing[:8],
            "unresolved_from_prev": unaccounted, "prev_ref": prev_ref}


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
    if r["files_missing"]:
        print(f"[WARN] referenced files not found: {', '.join(r['files_missing'])}")
    elif r["files_checked"]:
        print(f"[INFO] {r['files_checked']} file reference(s) verified")
    if r.get("unresolved_from_prev"):
        print(f"[WARN] {len(r['unresolved_from_prev'])} unresolved item(s) from the "
              f"previous handoff ({r.get('prev_ref')}) lack an outcome here:")
        for t in r["unresolved_from_prev"]:
            print(f"       - {t}")
    if r["missing_recommended"]:
        print(f"[INFO] consider adding: {', '.join(r['missing_recommended'])}")
    print(f"{line}")
    if r["secrets"]:
        print("Verdict: BLOCKED — remove secrets before handoff")
        return False
    if r["score"] >= 70:
        print("Verdict: READY for handoff")
        return True
    print("Verdict: NEEDS WORK — complete required sections")
    return False


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 validate_handoff.py <HANDOFF.md>")
        sys.exit(1)
    ok = report(validate(sys.argv[1]))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
