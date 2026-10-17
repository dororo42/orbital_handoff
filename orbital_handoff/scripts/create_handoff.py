#!/usr/bin/env python3
"""
orbital_handoff: smart scaffold generator for cross-agent handoff kits.

Creates handoffs/YYYY-MM-DD-HHMM-<slug>/ under the current project with:
- HANDOFF.md        (always; git metadata pre-filled, [TODO] placeholders)
- RESUME_PROMPT.md  (when target mode includes 'prompt')

Also maintains the Current Handoff pointer section in root AGENTS.md
(when target mode includes 'rules').

Usage:
    python3 create_handoff.py <slug> [--target all|skill|rules|prompt]
                              [--continues-from <dir-or-file>]
                              [--archive-old N]
    python3 create_handoff.py --check        # read-only preflight, writes nothing

Exit codes: 0 ok, 1 error, 2 preflight warnings found (check mode),
            1 on [ABORT] when AGENTS.md changed on disk during pointer update.

Write safety: every write is atomic (temp file + os.replace); the AGENTS.md
pointer update additionally carries an mtime guard (optimistic concurrency),
so a concurrent external edit aborts instead of being clobbered.
"""

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

TARGET_MODES = ("skill", "rules", "prompt", "all")

# ---------------------------------------------------------------- git helpers

def run_cmd(cmd, cwd=None, timeout=15):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd, timeout=timeout)
        return r.returncode == 0, r.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return False, ""


def git_info(root):
    info = {"is_repo": False, "branch": None, "head": None, "remote": None,
            "commits": [], "modified": [], "staged": []}
    ok, _ = run_cmd(["git", "rev-parse", "--git-dir"], cwd=root)
    if not ok:
        return info
    info["is_repo"] = True
    ok, b = run_cmd(["git", "branch", "--show-current"], cwd=root)
    info["branch"] = b if ok and b else "(detached or no branch)"
    ok, h = run_cmd(["git", "rev-parse", "--short", "HEAD"], cwd=root)
    info["head"] = h if ok and h else "(no commits yet)"
    ok, remotes = run_cmd(["git", "remote", "get-url", "origin"], cwd=root)
    info["remote"] = remotes if ok and remotes else ""
    ok, log = run_cmd(["git", "log", "--oneline", "-5", "--no-decorate"], cwd=root)
    info["commits"] = log.split("\n") if ok and log else []
    ok, m = run_cmd(["git", "diff", "--name-only"], cwd=root)
    info["modified"] = m.split("\n") if ok and m else []
    ok, s = run_cmd(["git", "diff", "--name-only", "--cached"], cwd=root)
    info["staged"] = s.split("\n") if ok and s else []
    return info


# ---------------------------------------------------------------- safe writes

SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__",
             "dist", "build", ".tox", ".mypy_cache", ".pytest_cache"}


def atomic_write_text(path, text):
    """Write text atomically: temp file in the same directory + os.replace.

    Readers never observe a half-written file, and a crash mid-write leaves a
    stray temp file rather than a truncated target (the temp file is cleaned
    up on error). Same-directory replace is atomic on POSIX and on Windows.
    """
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp-handoff-", suffix=".md")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def overwrite_guarded(path, render):
    """Read-modify-write under optimistic concurrency control (OCC).

    Records mtime_ns before reading, renders the new content from what was
    read, then re-checks before writing. If anything else touched the file in
    between (the user's editor, another agent session), abort via SystemExit
    instead of silently clobbering that edit. `render` maps the current text
    to the new text.
    """
    before = path.stat().st_mtime_ns
    new_text = render(path.read_text(encoding="utf-8"))
    if path.stat().st_mtime_ns != before:
        print(f"[ABORT] {path} changed on disk while updating the Current Handoff "
              "pointer — another edit is in flight. Re-run once it settles, or merge "
              "the pointer section manually.")
        sys.exit(1)
    atomic_write_text(path, new_text)


# ---------------------------------------------------------------- preflight

AGENT_TRACES = ["AGENTS.md", "CLAUDE.md", ".claude", ".cursor", ".cursorrules",
                ".codex", ".agents", "handoffs"]
SENSITIVE = [".env", ".env.*", "*secret*", "*token*", "*credential*",
             "auth.json", "*.pem", "*.key", "id_rsa", "id_ed25519"]

def preflight(root):
    warns, lines = [], []
    g = git_info(root)
    lines.append(f"git repo: {g['is_repo']}")
    if g["is_repo"]:
        lines.append(f"branch: {g['branch']}  HEAD: {g['head']}")
        lines.append(f"remote: {g['remote'] or '(none)'}")
        lines.append(f"uncommitted: {len(g['modified'])} modified, {len(g['staged'])} staged")
    else:
        warns.append("not inside a git repository — handoff can still be created, "
                     "but only the local-folder channel is available")
    traces = [p for p in AGENT_TRACES if (root / p).exists()]
    lines.append(f"agent traces found: {traces or '(none)'}")
    hits = sorted(_iter_sensitive(root))
    for h in hits[:10]:
        warns.append(f"sensitive file present (must NOT enter the handoff): {h}")
    if len(hits) > 10:
        warns.append(f"...and {len(hits) - 10} more sensitive files (list truncated)")
    return lines, warns


def _iter_sensitive(root):
    """Yield sensitive files at ANY depth (a single-level glob missed nested
    ones like config/.env.production). Skips heavy/irrelevant directories and,
    inside a git repo, files that .gitignore already excludes (they never
    travel through the handoff channel)."""
    ignored = set()
    if (root / ".git").exists():
        ok, out = run_cmd(["git", "ls-files", "--others", "--ignored",
                           "--exclude-standard"], cwd=root)
        if ok and out:
            ignored = set(out.splitlines())
    for pat in SENSITIVE:
        for p in root.rglob(pat):
            if not p.is_file():
                continue
            rel = p.relative_to(root)
            if any(part in SKIP_DIRS for part in rel.parts):
                continue
            if rel.as_posix() in ignored:
                continue
            yield p


# ---------------------------------------------------------------- templates

HANDOFF_TMPL = """# Handoff: [TODO: 一句话任务标题]

## 元数据

- Created: {created}
- Source agent: {source_agent}
- Target agent: {target_agent}
- Target mode: {target_mode}
- Project: {project}
- Branch: {branch}
- HEAD: {head}
- OS: {os_hint}

### 交接链

{chain}

> 接手方：从本份读起，需要更早背景时再回溯链上前驱。

## 当前状态摘要

[TODO: 一段话——在做什么、进行到哪、停在哪。这是接手方读的第一段，也是最重要的一段。]

## 最近提交（上下文参考）

{commits}

## 未提交修改

{modified}

## 架构与关键文件

### 架构概览

[TODO: 本轮工作中摸清的系统结构——组件、数据流、模块边界。只写接手方需要的。]

### 关键文件

| 文件 | 作用 | 对当前任务为何重要 |
|---|---|---|
| [TODO: path/to/file.rs:88] | | |

## 已完成工作

### 任务清单

- [x] [TODO: 已完成项 + 一句结果说明]
- [ ] [TODO: 已开工未完成项——在下一节说明停在何处]

### 决策记录

| 决策 | 备选项 | 为什么选它 |
|---|---|---|
| [TODO] | | |

## 待办工作

### 立即下一步

1. [TODO: 接手后第一个动作——具体到可直接执行]
   → 结局: [done <一句话结果> / blocked <原因> / moved <新条目号>；接手方填写，未开始留空]
2. [TODO: 第二优先级]
   → 结局: [同上]
3. [TODO: 第三优先级]
   → 结局: [同上]

### Blocker / 未决问题

- [ ] [TODO: 阻塞项描述] —— 需要：[TODO: 解除条件]

### 延后项

- [TODO: 有意延后的事 + 原因]

## 接手方必读

### 重要上下文

[TODO: 全文档最重要的一节。写「看代码看不出来」的信息：坑、非显然行为、用户偏好、隐藏约定。]

### 假设

- [TODO: 本轮工作建立在其上的假设——接手方要逐条验证]

### 已知坑

- [TODO: 会绊倒新 agent 的东西]

## 环境

### 构建 / 运行 / 测试命令

[TODO: 完整命令 + 必须的工具链版本]

### 环境变量（只写名字，绝不写值）

- [TODO: VAR_NAME —— 作用]

---

**安全提醒**：定稿前运行 validate_handoff.py。检测到密钥或质量分 <70 时不得交付。
"""

RESUME_PROMPT_TMPL = """# 接手指令（把本文件全文粘贴给目标 agent 的对话框）

你即将接手一个由另一个 AI agent 移交的开发项目。你们相互隔离，你没有它的任何上下文——所有上下文都在下面的交接文档里。

**项目位置**：{project}
**交接文档**：{handoff_relpath}
**当前分支**：{branch}

请严格按以下顺序执行，任何一步失败就停下来向用户报告，不要跳步：

1. **读取交接文档**：完整读取上面的 HANDOFF.md（不要只扫标题），如有需要再回溯它引用的前一份交接。
2. **核验环境**：确认你在正确分支上；`git log` 的 HEAD 与文档记录的 HEAD 是否一致；不一致时报告差异并停止。
3. **报告继续计划**：基于文档「立即下一步」第 1 条，给出你的具体执行方案和风险点，等用户确认。
4. **确认后再动代码**：先跑文档里的构建/测试命令验证基线可用，再开始改动。
5. **持续维护交接文档**：完成事项随手打钩并补一行结局（`→ 结局: done <结果> / blocked <原因> / moved <新条目号>`）；尝试过但没做完的条目必须标 `blocked`，不留无结局条目；新发现的坑补进「已知坑」——你也是未来的导出方。

红线：不要提交/推送任何东西，除非用户明说；不要接触 .env、密钥、token；对文档假设与代码现实冲突的地方，以代码现实为准并报告。对 HANDOFF.md **只做加法和打钩**：不重排段落、不改章节标题、不动元数据与交接链——结构整理留给下一次 create_handoff。
"""

AGENTS_PTR = """
## Current Handoff

- Latest: `{latest}`
- Branch: {branch} @ {head}
- Status: [TODO: 进行中 / 等待决策 / …]

任何 agent 开始工作前，先读上面的 HANDOFF.md。这份指针由 orbital_handoff 维护，手工交接时请同步更新。
"""


# ---------------------------------------------------------------- create

def find_previous(root, ref):
    hd = root / "handoffs"
    if not hd.exists():
        return None
    # handoffs/archive/ holds demoted kits — they left the authority chain and
    # must never become its head.
    active = [d for d in hd.iterdir() if d.is_dir() and d.name != "archive"]
    if ref:
        cands = [d for d in active if ref in d.name]
        return cands[0] if cands else None
    dirs = sorted(active, reverse=True)
    return dirs[0] if dirs else None


def update_agents_pointer(root, relpath, branch, head):
    agents = root / "AGENTS.md"
    ptr = AGENTS_PTR.format(latest=relpath, branch=branch, head=head)

    def render(content):
        content = re.sub(r"\n## Current Handoff\n(?:(?!\n## ).)*", "", content, flags=re.S)
        if not content.endswith("\n"):
            content += "\n"
        return content + ptr

    if agents.exists():
        # AGENTS.md is a live file the user and other agents also edit: write
        # only if it is unchanged since we read it (OCC), and always atomically.
        overwrite_guarded(agents, render)
        return "updated"
    atomic_write_text(agents, "# AGENTS.md\n\n[TODO: 一句话项目说明与长期规则。]\n" + ptr)
    return "created"


def archive_old_kits(root, keep):
    """Demote the oldest handoff kits into handoffs/archive/ (never delete).

    Keeps the newest `keep` kits in the flat namespace; older ones move to
    handoffs/archive/ and leave the authority chain (find_previous and the
    staleness tooling skip them). Uses `git mv` so history follows the move
    when the kit is tracked; falls back to a plain move otherwise.
    Returns the list of moved kit names.
    """
    hd = root / "handoffs"
    if not hd.exists() or keep <= 0:
        return []
    arch = hd / "archive"
    active = sorted([d for d in hd.iterdir() if d.is_dir() and d.name != "archive"],
                    reverse=True)
    if len(active) <= keep:
        return []
    arch.mkdir(exist_ok=True)
    moved = []
    for d in active[keep:]:
        dest = arch / d.name
        if dest.exists():
            continue  # never overwrite anything
        ok, _ = run_cmd(["git", "mv", str(d), str(dest)], cwd=root)
        if not ok:
            shutil.move(str(d), str(dest))
        moved.append(d.name)
    return moved


def archived_index(root):
    """One-line summary index of archived kits, appended to the chain section
    so archived context stays discoverable from the newest handoff."""
    arch = root / "handoffs" / "archive"
    if not arch.exists():
        return ""
    names = sorted(p.name for p in arch.iterdir() if p.is_dir())
    if not names:
        return ""
    items = []
    for n in names:
        parts = n.split("-", 3)  # YYYY-MM-DD-HHMM-<slug>
        date = parts[0] if parts else n
        topic = parts[3] if len(parts) > 3 else n
        items.append(f"{topic}({date})")
    return "\n- 更早交接（已归档，按需回溯）: " + "、".join(items)


def create(root, slug, target, continues_from, source_agent, archive_old=5):
    now = datetime.now()
    stamp = now.strftime("%Y-%m-%d-%H%M")
    slug = re.sub(r"[^a-z0-9-]", "-", slug.lower().replace(" ", "-").replace("_", "-"))
    slug = re.sub(r"-+", "-", slug).strip("-") or "handoff"
    kit_dir = root / "handoffs" / f"{stamp}-{slug}"
    kit_dir.mkdir(parents=True, exist_ok=True)

    moved = archive_old_kits(root, archive_old)
    if moved:
        print(f"[archive] demoted {len(moved)} old kit(s) to handoffs/archive/: "
              + ", ".join(moved))

    g = git_info(root)
    prev = find_previous(root, continues_from)
    if continues_from and not prev:
        print(f"[WARN] --continues-from '{continues_from}' not found; chain not linked.")

    if prev:
        chain = (f"- **Continues from**: `{'handoffs/' + prev.name + '/HANDOFF.md'}`\n"
                 f"- **Supersedes**: [TODO: 列出本份取代的旧交接，或 None]")
    else:
        chain = "- **Continues from**: None（首轮交接）\n- **Supersedes**: None"
    arch_note = archived_index(root)
    if arch_note:
        chain += arch_note

    commits = "\n".join(f"- {c}" for c in g["commits"]) or "- [not a git repo / no commits]"
    allmod = sorted(set(g["modified"]) | set(g["staged"]))
    if allmod:
        mod = "\n".join(f"| {f} | [TODO: 改动说明] | [TODO: 原因] |" for f in allmod[:15])
        if len(allmod) > 15:
            mod += f"\n| …及另外 {len(allmod) - 15} 个文件 | | |"
    else:
        mod = "| （无未提交修改） | | |"

    project = g["remote"] or str(root)
    handoff = HANDOFF_TMPL.format(
        created=now.strftime("%Y-%m-%d %H:%M:%S"), source_agent=source_agent,
        target_agent="[TODO: 接收方 agent，未知则写 unknown]",
        target_mode=target, project=project, branch=g["branch"],
        head=g["head"], os_hint=sys.platform, chain=chain, commits=commits,
        modified=mod)
    atomic_write_text(kit_dir / "HANDOFF.md", handoff)

    made = [kit_dir / "HANDOFF.md"]
    if target in ("prompt", "all"):
        rp = RESUME_PROMPT_TMPL.format(project=project,
                                       handoff_relpath=f"handoffs/{kit_dir.name}/HANDOFF.md",
                                       branch=g["branch"])
        p = kit_dir / "RESUME_PROMPT.md"
        atomic_write_text(p, rp)
        made.append(p)

    agents_action = ""
    if target in ("rules", "all"):
        agents_action = update_agents_pointer(
            root, f"handoffs/{kit_dir.name}/HANDOFF.md", g["branch"], g["head"])

    print(f"Created handoff kit: {kit_dir}")
    for m in made:
        print(f"  - {m.name}: {m}")
    if agents_action:
        print(f"  - AGENTS.md: {agents_action} (Current Handoff pointer)")
    print("\nNext steps:")
    print(f"1. Fill every [TODO] in {kit_dir}/HANDOFF.md "
          "(prioritize: 当前状态摘要 / 重要上下文 / 立即下一步)")
    print(f"2. Run: python3 validate_handoff.py {kit_dir}/HANDOFF.md  "
          "(target: score >= 70, zero secrets)")
    if target in ("skill",):
        print("3. Target mode is 'skill' — deliver the repo/folder; the receiving agent's "
              "orbital_handoff skill handles RESUME.")
    if agents_action == "created":
        print("3. AGENTS.md was newly created — fill its [TODO] project description.")
    print("4. Do not commit/push until the user asks.")
    return str(kit_dir)


def main():
    ap = argparse.ArgumentParser(description="Create a cross-agent handoff kit")
    ap.add_argument("slug", nargs="?", default="handoff",
                    help="short slug, e.g. implementing-auth")
    ap.add_argument("--target", choices=TARGET_MODES, default="all",
                    help="receiving agent capability mode (default: all)")
    ap.add_argument("--continues-from", default=None,
                    help="previous handoff kit name to chain from")
    ap.add_argument("--source-agent", default="[TODO: 当前 agent 名称]")
    ap.add_argument("--archive-old", type=int, default=5, metavar="N",
                    help="keep the newest N kits in handoffs/ and demote older "
                         "ones to handoffs/archive/ (0 disables; default 5)")
    ap.add_argument("--check", action="store_true",
                    help="read-only preflight; creates nothing")
    args = ap.parse_args()

    root = Path.cwd()

    if args.check:
        lines, warns = preflight(root)
        print("== orbital_handoff preflight (read-only) ==")
        for l in lines:
            print(f"  {l}")
        if warns:
            print("\nWarnings:")
            for w in warns:
                print(f"  [WARN] {w}")
            sys.exit(2)
        print("\nNo blocking issues. Recommended next: create a handoff kit.")
        sys.exit(0)

    create(root, args.slug, args.target, args.continues_from, args.source_agent,
           archive_old=args.archive_old)


if __name__ == "__main__":
    main()
