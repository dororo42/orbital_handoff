#!/usr/bin/env python3
"""Regression tests for the orbital_handoff scripts.

Runs on the stdlib (unittest) with zero dependencies; also collected by pytest.
Run from anywhere:
    python3 -m unittest discover -s <skill>/scripts/tests -v
Each test builds a throwaway git repo in a temp dir and drives the real
scripts end-to-end (the same scenarios that exposed the 2026-10-17 defects).
"""

import io
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stdout
from datetime import datetime
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))

import create_handoff as ch  # noqa: E402
import validate_handoff as vh  # noqa: E402


def run(cmd, cwd):
    return subprocess.run([str(c) for c in cmd], cwd=str(cwd),
                          capture_output=True, text=True)


def make_repo(root):
    root.mkdir(parents=True, exist_ok=True)
    run(["git", "init", "-q", "-b", "main", "."], root)
    run(["git", "config", "user.email", "t@t"], root)
    run(["git", "config", "user.name", "t"], root)
    (root / "src").mkdir()
    (root / "src" / "main.py").write_text("print('x')\n", encoding="utf-8")
    run(["git", "add", "-A"], root)
    run(["git", "commit", "-qm", "init"], root)
    return root


class KitTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="oh-test-"))
        self.repo = make_repo(self.tmp / "repo")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def create_kit(self, slug, *extra):
        r = run([sys.executable, SCRIPTS / "create_handoff.py", slug, *extra],
                self.repo)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        m = re.search(r"Created handoff kit: (\S+)", r.stdout)
        self.assertIsNotNone(m, r.stdout)
        return Path(m.group(1)), r.stdout

    @staticmethod
    def chain_of(kit):
        text = (kit / "HANDOFF.md").read_text(encoding="utf-8")
        m = re.search(r"Continues from\*\*: `([^`]+)`", text)
        return m.group(1) if m else None


class ChainTests(KitTestCase):
    def test_first_round_chain_is_none(self):
        kit, _ = self.create_kit("first")
        self.assertIsNone(self.chain_of(kit))
        text = (kit / "HANDOFF.md").read_text(encoding="utf-8")
        self.assertIn("None（首轮交接）", text)

    def test_second_round_chain_points_to_prev(self):
        k1, _ = self.create_kit("alpha")
        k2, _ = self.create_kit("beta")
        self.assertEqual(self.chain_of(k2),
                         f"handoffs/{k1.name}/HANDOFF.md")

    def test_self_reference_is_impossible(self):
        # Regression for the 2026-10-17 blocker: every kit used to claim
        # "Continues from" itself because mkdir ran before find_previous.
        for slug in ("s1", "s2", "s3"):
            kit, _ = self.create_kit(slug)
            ref = self.chain_of(kit)
            if ref is not None:
                self.assertNotIn(kit.name, ref)

    def test_chain_follows_kit_into_archive(self):
        # Regression: with --archive-old 1 the predecessor gets demoted during
        # the very create that links to it — the chain must follow the kit
        # into handoffs/archive/ instead of degrading to "首轮交接".
        k1, _ = self.create_kit("one", "--target", "skill", "--archive-old", "1")
        k2, _ = self.create_kit("two", "--target", "skill", "--archive-old", "1")
        ref = self.chain_of(k2)
        self.assertIsNotNone(ref)
        self.assertEqual(ref, f"handoffs/archive/{k1.name}/HANDOFF.md")
        self.assertTrue((self.repo / ref).exists())


class MetadataTests(KitTestCase):
    def test_untracked_files_listed(self):
        (self.repo / "draft.py").write_text("x = 1\n", encoding="utf-8")
        kit, _ = self.create_kit("with-untracked")
        text = (kit / "HANDOFF.md").read_text(encoding="utf-8")
        self.assertIn("draft.py", text)
        self.assertIn("untracked", text)

    def test_generated_files_are_0644(self):
        kit, _ = self.create_kit("perm", "--target", "all")
        for f in (kit / "HANDOFF.md", kit / "RESUME_PROMPT.md",
                  self.repo / "AGENTS.md"):
            self.assertEqual(oct(f.stat().st_mode & 0o777), "0o644",
                             f"unexpected mode on {f}")

    def test_same_second_same_slug_gets_suffix(self):
        class FakeDT:
            @staticmethod
            def now():
                return datetime(2026, 10, 17, 12, 0, 0)

        orig = ch.datetime
        ch.datetime = FakeDT
        buf = io.StringIO()
        try:
            with redirect_stdout(buf):
                k1 = ch.create(self.repo, "dup", "skill", None, "tester")
                k2 = ch.create(self.repo, "dup", "skill", None, "tester")
        finally:
            ch.datetime = orig
        self.assertNotEqual(k1, k2)
        self.assertTrue((Path(k2) / "HANDOFF.md").exists())
        self.assertTrue(Path(k1).name.endswith("dup") or "-2" in Path(k1).name)
        self.assertIn("-2", Path(k2).name)

    def test_preflight_flags_sensitive_files(self):
        (self.repo / ".env").write_text("X=1\n", encoding="utf-8")
        r = run([sys.executable, SCRIPTS / "create_handoff.py", "--check"],
                self.repo)
        self.assertEqual(r.returncode, 2)
        self.assertIn(".env", r.stdout)


class ArchiveTests(KitTestCase):
    def test_archived_index_shows_full_date(self):
        last = None
        for slug in "abcdef":
            last, _ = self.create_kit(slug, "--target", "skill",
                                      "--archive-old", "2")
        text = (last / "HANDOFF.md").read_text(encoding="utf-8")
        self.assertRegex(text, r"更早交接.*\(\d{4}-\d{2}-\d{2}\)")
        # the truncated year-only form from the split("-", 3) bug must be gone
        self.assertNotRegex(text, r"\(([0-9]{4})\)、")

    def test_archive_keeps_the_newest(self):
        kits = []
        for slug in ("a1", "a2", "a3"):
            kit, _ = self.create_kit(slug, "--target", "skill",
                                     "--archive-old", "2")
            kits.append(kit)
        # distinct seconds are not guaranteed; assert on the invariant that
        # the newest kit (the last created) is never archived
        self.assertTrue((kits[-1] / "HANDOFF.md").exists())
        archived = self.repo / "handoffs" / "archive"
        if archived.exists():
            names = {p.name for p in archived.iterdir()}
            self.assertNotIn(kits[-1].name, names)


class ValidateTests(KitTestCase):
    def test_broken_chain_is_flagged(self):
        cur = self.repo / "handoffs" / "cur"
        cur.mkdir(parents=True)
        (cur / "HANDOFF.md").write_text(
            "# Handoff: current\n## 元数据\n### 交接链\n"
            "- **Continues from**: `handoffs/9999-99-99-999999-ghost/HANDOFF.md`\n",
            encoding="utf-8")
        r = vh.validate(str(cur / "HANDOFF.md"))
        self.assertIsNotNone(r["chain_error"])
        self.assertIn("missing file", r["chain_error"])

    def test_closed_loop_deducts_for_unaccounted_items(self):
        prev = self.repo / "handoffs" / "prev"
        prev.mkdir(parents=True)
        (prev / "HANDOFF.md").write_text(
            "# Handoff: prev\n- [ ] migrate config format to toml completely\n",
            encoding="utf-8")
        cur = self.repo / "handoffs" / "cur"
        cur.mkdir(parents=True)
        (cur / "HANDOFF.md").write_text(
            "# Handoff: current\n## 元数据\n### 交接链\n"
            "- **Continues from**: `handoffs/prev/HANDOFF.md`\n",
            encoding="utf-8")
        r = vh.validate(str(cur / "HANDOFF.md"))
        self.assertEqual(len(r["unresolved_from_prev"]), 1)
        self.assertLessEqual(r["score"], 98)

    def test_sk_ant_style_key_is_detected(self):
        p = self.tmp / "sec.md"
        p.write_text('ANTHROPIC_KEY = "sk-ant-api03-aaaaaaaaaaaaaaaaaaaa-bbbbbbbbbbbb"\n',
                     encoding="utf-8")
        r = vh.validate(str(p))
        self.assertTrue(r["secrets"])
        self.assertTrue(any("Anthropic" in d for d, _ in r["secrets"]))


class StalenessTests(KitTestCase):
    def test_many_files_few_commits_is_stale(self):
        kit, _ = self.create_kit("stale-me", "--target", "skill")
        bulk = self.repo / "bulk"
        bulk.mkdir()
        for i in range(20):
            (bulk / f"f{i}.txt").write_text("1\n", encoding="utf-8")
        run(["git", "add", "-A"], self.repo)
        run(["git", "commit", "-qm", "bulk1"], self.repo)
        for i in range(20):
            (bulk / f"f{i}.txt").write_text("2\n", encoding="utf-8")
        run(["git", "add", "-A"], self.repo)
        run(["git", "commit", "-qm", "bulk2"], self.repo)
        r = run([sys.executable, SCRIPTS / "check_staleness.py",
                 kit / "HANDOFF.md"], self.repo)
        self.assertIn("Level: STALE", r.stdout)
        self.assertNotIn("SLIGHTLY_STALE", r.stdout)

    def test_fresh_right_after_creation(self):
        kit, _ = self.create_kit("fresh", "--target", "skill")
        r = run([sys.executable, SCRIPTS / "check_staleness.py",
                 kit / "HANDOFF.md"], self.repo)
        self.assertIn("Level: FRESH", r.stdout)
        self.assertEqual(r.returncode, 0)

    def test_unreachable_head_is_very_stale(self):
        kit, _ = self.create_kit("rewound", "--target", "skill")
        run(["git", "checkout", "-q", "--orphan", "fresh-start"], self.repo)
        run(["git", "add", "-A"], self.repo)
        run(["git", "commit", "-qm", "orphan"], self.repo)
        r = run([sys.executable, SCRIPTS / "check_staleness.py",
                 kit / "HANDOFF.md"], self.repo)
        self.assertIn("Level: VERY_STALE", r.stdout)


class CredentialRedactionTests(KitTestCase):
    def test_remote_url_credentials_are_redacted(self):
        # Regression: a credentialed origin URL used to be copied verbatim
        # into HANDOFF.md/RESUME_PROMPT.md (Project/位置 fields).
        run(["git", "remote", "add", "origin",
             "https://user:ghp_AAAABBBBCCCCDDDDEEEEFFFFGGGG1234@github.com/org/repo.git"],
            self.repo)
        kit, out = self.create_kit("leakcheck", "--target", "all")
        text = (kit / "HANDOFF.md").read_text(encoding="utf-8")
        self.assertNotIn("ghp_AAAABBBB", text)
        self.assertNotIn("user:ghp_", text)
        self.assertIn("https://github.com/org/repo.git", text)
        self.assertIn("redacted", out)
        # sanitizer unit behavior
        self.assertEqual(ch.sanitize_remote_url("https://tok@host/x/y.git"),
                         "https://host/x/y.git")
        self.assertEqual(ch.sanitize_remote_url("https://u:p@ss@host/x"),
                         "https://host/x")
        self.assertEqual(ch.sanitize_remote_url("git@host:path/repo.git"),
                         "git@host:path/repo.git")
        self.assertEqual(ch.sanitize_remote_url(""), "")
        self.assertEqual(ch.sanitize_remote_url("https://host/x/y.git"),
                         "https://host/x/y.git")

    def test_git_failure_no_longer_fails_open(self):
        # The local-only tripwire returned [] on git failure; an unknown
        # tracking state must warn, never read as clean.
        kit, _ = self.create_kit("tripwire")
        self.assertEqual(ch.handoffs_tracked(self.repo), [])
        broken = self.tmp / "broken"
        broken.mkdir()
        (broken / ".git").write_text("garbage", encoding="utf-8")
        self.assertIsNone(ch.handoffs_tracked(broken))


class GitParsingTests(KitTestCase):
    def test_porcelain_z_handles_unicode_and_arrow_names(self):
        # Regression: quoted porcelain output produced octal escapes for
        # non-ASCII paths and truncated rename targets containing " -> ".
        (self.repo / "文档 文件.md").write_text("x\n", encoding="utf-8")
        (self.repo / "old.txt").write_text("x\n", encoding="utf-8")
        run(["git", "add", "-A"], self.repo)
        run(["git", "mv", "old.txt", "weird -> name.txt"], self.repo)
        kit, _ = self.create_kit("zparse")
        text = (kit / "HANDOFF.md").read_text(encoding="utf-8")
        self.assertNotIn("\\346", text)           # no octal escapes
        self.assertIn("文档 文件.md", text)        # raw non-ASCII preserved
        self.assertIn("weird -> name.txt", text)  # rename target intact

    def test_slug_sanitization_never_traverses(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            for s in ("../../etc/passwd", "/abs/path", "..", "中文名", ""):
                kit = ch.create(self.repo, s, "skill", None, "tester")
                name = Path(kit).name
                self.assertNotIn("..", name)
                self.assertRegex(name, r"^[0-9a-zA-Z-]+$")


class ChainPathTests(KitTestCase):
    def test_continues_from_accepts_doc_path(self):
        # Regression: the usage string promised dir-or-file, but a path to
        # HANDOFF.md silently degraded the chain to "首轮交接".
        k1, _ = self.create_kit("prev")
        kit, out = self.create_kit(
            "next", "--target", "skill",
            "--continues-from", str(k1 / "HANDOFF.md"))
        self.assertEqual(self.chain_of(kit),
                         f"handoffs/{k1.name}/HANDOFF.md")
        self.assertNotIn("not found among active kits", out)

    def test_continues_from_accepts_kit_dir_path(self):
        k1, _ = self.create_kit("prevdir")
        kit, _ = self.create_kit("nextdir", "--target", "skill",
                                 "--continues-from", str(k1))
        self.assertEqual(self.chain_of(kit),
                         f"handoffs/{k1.name}/HANDOFF.md")


class RollbackTests(KitTestCase):
    def test_failed_pointer_update_rolls_back_kit(self):
        # Regression: only SystemExit was caught, so a UnicodeDecodeError from
        # a non-UTF-8 AGENTS.md leaked an orphan kit that the next create
        # would treat as the newest chain member.
        (self.repo / "AGENTS.md").write_bytes(
            "# AGENTS\n\n中文内容（GBK 编码）\n".encode("gbk"))
        r = run([sys.executable, SCRIPTS / "create_handoff.py", "gbk",
                 "--target", "all"], self.repo)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("[ABORT]", r.stdout)
        self.assertIn("[cleanup]", r.stdout)
        hd = self.repo / "handoffs"
        leftovers = [p for p in hd.iterdir() if p.is_dir()] if hd.is_dir() else []
        self.assertEqual(leftovers, [])
        # and the next create must not chain to an orphan
        k2, _ = self.create_kit("after-gbk", "--target", "skill")
        self.assertIsNone(self.chain_of(k2))

    def test_temp_sweep_spares_fresh_files(self):
        # Regression: the startup sweep unlinked ANY stray temp file, crashing
        # a concurrent create that still owned its fresh temp file.
        hd = self.repo / "handoffs"
        hd.mkdir(exist_ok=True)
        fresh = hd / ".tmp-handoff-fresh.md"
        fresh.write_text("x", encoding="utf-8")
        old = hd / ".tmp-handoff-old.md"
        old.write_text("x", encoding="utf-8")
        two_hours_ago = time.time() - 7200
        os.utime(old, (two_hours_ago, two_hours_ago))
        self.create_kit("sweep")
        self.assertTrue(fresh.exists())
        self.assertFalse(old.exists())


class SecretScanTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="oh-sec-"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_all_pattern_families_fire(self):
        samples = {
            "API key": 'api_key = "0123456789abcdef"',
            "Password": 'DB_PASSWORD="sup3rs3cret!"',
            "Secret": "client_secret: '0123456789abcdef0'",
            "Token": "token = 0123456789abcdef0123456789",
            "PEM private key": "-----BEGIN RSA PRIVATE KEY-----",
            "MongoDB URL with password": "mongodb://u:secretpw@host/db",
            "PostgreSQL URL with password": "postgresql://u:secretpw@h/db",
            "MySQL URL with password": "mysql://u:secretpw@h/db",
            "URL with embedded credentials": "https://u:secretpassword@host/x",
            "Bearer token": "Authorization: Bearer abcdefghijklmnopqrstuvwx",
            "GitHub PAT": "ghp_" + "a" * 36,
            "GitHub fine-grained PAT": "github_pat_" + "a" * 22,
            "OpenAI/Anthropic-style API key": "sk-" + "a" * 40,
            "Slack token": "xoxb-" + "a" * 20,
            "Zhipu-style key (id.secret)": "a" * 32 + "." + "b" * 16,
            "JWT (JSON Web Token)": "eyJ" + "a" * 12 + "." + "b" * 12 + "." + "c" * 6,
            "AWS access key id": "AKIA" + "2" * 16,
            "Google API key": "AIza" + "a" * 35,
        }
        for desc, sample in samples.items():
            with self.subTest(desc=desc):
                matched = [d for pat, d in vh.SECRET_PATTERNS
                           if re.search(pat, sample, re.IGNORECASE)]
                self.assertIn(desc, matched)

    def test_unquoted_kv_leak_detected(self):
        # Regression: `api_key: sk-...` without quotes escaped detection.
        p = self.tmp / "doc.md"
        p.write_text("api_key: sk-abcdefghijklmnopqrst\n"
                     "password: hunter2secret\n", encoding="utf-8")
        r = vh.validate(str(p))
        descs = [d for d, _ in r["secrets"]]
        self.assertIn("API key", descs)
        self.assertIn("Password", descs)

    def test_redos_is_bounded(self):
        # Regression: the unbounded credential-URL pattern needed >120 s on a
        # crafted ~600 KB line; the scan must stay well under seconds.
        evil = "a" * 4000 + " https://" + "b" * 2000 + ":" + "c" * 2000
        big = "a" * 100000 + "://" + "b" * 100000 + ":" + "c" * 100000
        t0 = time.perf_counter()
        vh.scan_secrets(evil + "\n" + evil)
        vh.scan_secrets(big)
        self.assertLess(time.perf_counter() - t0, 5.0)

    def test_undecodable_doc_fails_closed(self):
        p = self.tmp / "gbk.md"
        p.write_bytes("secret: 中文密钥内容\n".encode("gbk"))
        r = vh.validate(str(p))
        self.assertIn("error", r)
        self.assertIn("UTF-8", r["error"])

    def test_oversized_doc_is_refused(self):
        p = self.tmp / "big.md"
        p.write_text("x" * (vh.MAX_DOC_BYTES + 1), encoding="utf-8")
        r = vh.validate(str(p))
        self.assertIn("error", r)
        self.assertIn("too large", r["error"])


class ChainSecurityTests(KitTestCase):
    def test_chain_read_cannot_escape_project(self):
        # Regression: 'Continues from' accepted any path on disk and echoed
        # up to 60 chars of its content — an arbitrary-read vector.
        secret = self.tmp / "outside-secret.md"
        secret.write_text("- [ ] planted item for arbitrary read test\n",
                          encoding="utf-8")
        cur = self.repo / "handoffs" / "cur"
        cur.mkdir(parents=True)
        (cur / "HANDOFF.md").write_text(
            "# Handoff: cur\n### 交接链\n"
            "- **Continues from**: `../outside-secret.md`\n", encoding="utf-8")
        r = vh.validate(str(cur / "HANDOFF.md"))
        self.assertIsNotNone(r["chain_error"])
        self.assertIn("escapes the project root", r["chain_error"])
        self.assertEqual(r["unresolved_from_prev"], [])

    def test_gbk_previous_doc_does_not_crash(self):
        # Regression: a GBK-encoded predecessor killed validation with a bare
        # UnicodeDecodeError traceback.
        prev = self.repo / "handoffs" / "prev"
        prev.mkdir(parents=True)
        (prev / "HANDOFF.md").write_bytes(
            "# prev\n- [ ] GBK未完成条目测试ab\n".encode("gbk"))
        cur = self.repo / "handoffs" / "cur"
        cur.mkdir(parents=True)
        (cur / "HANDOFF.md").write_text(
            "# Handoff: cur\n### 交接链\n"
            "- **Continues from**: `handoffs/prev/HANDOFF.md`\n",
            encoding="utf-8")
        r = vh.validate(str(cur / "HANDOFF.md"))
        self.assertIsNone(r["chain_error"])  # lenient decode, no crash

    def test_mentioned_without_outcome_is_flagged(self):
        prev = self.repo / "handoffs" / "prev"
        prev.mkdir(parents=True)
        (prev / "HANDOFF.md").write_text(
            "# Handoff: prev\n- [ ] migrate config to toml completely\n",
            encoding="utf-8")
        cur = self.repo / "handoffs" / "cur"
        cur.mkdir(parents=True)
        (cur / "HANDOFF.md").write_text(
            "# Handoff: cur\n### 交接链\n"
            "- **Continues from**: `handoffs/prev/HANDOFF.md`\n"
            "## 当前状态摘要\n\nmigrate config to toml completely 被提及但没有结局。\n",
            encoding="utf-8")
        r = vh.validate(str(cur / "HANDOFF.md"))
        self.assertEqual(r["unresolved_from_prev"], [])
        self.assertEqual(len(r["mentioned_no_outcome"]), 1)

    def test_outcome_marker_closes_item(self):
        prev = self.repo / "handoffs" / "prev"
        prev.mkdir(parents=True)
        (prev / "HANDOFF.md").write_text(
            "# Handoff: prev\n- [ ] migrate config to toml completely\n",
            encoding="utf-8")
        cur = self.repo / "handoffs" / "cur"
        cur.mkdir(parents=True)
        (cur / "HANDOFF.md").write_text(
            "# Handoff: cur\n### 交接链\n"
            "- **Continues from**: `handoffs/prev/HANDOFF.md`\n"
            "## 立即下一步\n\n"
            "1. migrate config to toml completely\n"
            "   → 结局: [done 已在上一轮完成并验证]\n",
            encoding="utf-8")
        r = vh.validate(str(cur / "HANDOFF.md"))
        self.assertEqual(r["unresolved_from_prev"], [])
        self.assertEqual(r["mentioned_no_outcome"], [])


class VerdictGateTests(KitTestCase):
    def test_single_todo_is_not_ready(self):
        # Regression: one [TODO] landed at exactly 70 → READY, with [FAIL]
        # lines printed in the very same report.
        kit, _ = self.create_kit("onetodo")
        text = (kit / "HANDOFF.md").read_text(encoding="utf-8")
        todos = re.findall(r"\[TODO[^\]]*\]", text)
        for t in todos[1:]:
            text = text.replace(t, "filled-in content that is long enough")
        (kit / "HANDOFF.md").write_text(text, encoding="utf-8")
        r = vh.validate(str(kit / "HANDOFF.md"))
        self.assertEqual(r["todo_count"], 1)
        self.assertEqual(r["missing_required"], [])
        self.assertGreaterEqual(r["score"], 70)  # score alone would pass
        out = io.StringIO()
        with redirect_stdout(out):
            ok = vh.report(r)
        self.assertFalse(ok)
        self.assertIn("NEEDS WORK", out.getvalue())

    def test_filled_doc_becomes_ready(self):
        kit, _ = self.create_kit("readydoc")
        text = (kit / "HANDOFF.md").read_text(encoding="utf-8")
        text = text.replace("[TODO: 一句话任务标题]", "polyline autofollow")
        for placeholder in re.findall(r"\[TODO[^\]]*\]", text):
            text = text.replace(placeholder, "filled-in content, long enough")
        (kit / "HANDOFF.md").write_text(text, encoding="utf-8")
        r = run([sys.executable, SCRIPTS / "validate_handoff.py",
                 kit / "HANDOFF.md"], self.repo)
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn("READY", r.stdout)

    def test_preflight_reports_toolchain(self):
        r = run([sys.executable, SCRIPTS / "create_handoff.py", "--check"],
                self.repo)
        self.assertIn("toolchain found:", r.stdout)
        self.assertIn("git=yes", r.stdout)

    def test_tracked_handoff_still_warns(self):
        kit, _ = self.create_kit("tracked")
        run(["git", "add", "-f", str(kit / "HANDOFF.md")], self.repo)
        r = run([sys.executable, SCRIPTS / "create_handoff.py", "--check"],
                self.repo)
        self.assertEqual(r.returncode, 2)
        self.assertIn("git-tracked", r.stdout)

    def test_update_pointer_only_writes_project_relative_link(self):
        kit, _ = self.create_kit("ptr", "--target", "skill")
        r = run([sys.executable, SCRIPTS / "create_handoff.py",
                 "--update-pointer-only", kit.name], self.repo)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        agents = (self.repo / "AGENTS.md").read_text(encoding="utf-8")
        self.assertIn(f"handoffs/{kit.name}/HANDOFF.md", agents)


class StalenessExitTests(KitTestCase):
    def test_strict_exit_codes_do_not_collide(self):
        # Regression: SLIGHTLY_STALE used to exit 1 — the same code as a
        # missing file — so a CI could not tell advisory from fatal.
        kit, _ = self.create_kit("codes", "--target", "skill")
        r = run([sys.executable, SCRIPTS / "check_staleness.py", "/nonexistent"],
                self.repo)
        self.assertEqual(r.returncode, 1)
        r = run([sys.executable, SCRIPTS / "check_staleness.py",
                 kit / "HANDOFF.md", "--strict",
                 "--slightly-commits", "0", "--slightly-files", "100"],
                self.repo)
        self.assertEqual(r.returncode, 10)
        self.assertIn("SLIGHTLY_STALE", r.stdout)

    def test_created_line_is_timezone_aware(self):
        kit, _ = self.create_kit("tzcheck", "--target", "skill")
        text = (kit / "HANDOFF.md").read_text(encoding="utf-8")
        self.assertRegex(text,
                         r"- Created: \d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} [+-]\d{4}")
        r = run([sys.executable, SCRIPTS / "check_staleness.py",
                 kit / "HANDOFF.md"], self.repo)
        self.assertIn("source: doc", r.stdout)

    def test_age_falls_back_to_kit_dirname(self):
        kit, _ = self.create_kit("agecheck", "--target", "skill")
        text = (kit / "HANDOFF.md").read_text(encoding="utf-8")
        text = re.sub(r"- Created: .+", "- Created: (garbled)", text)
        (kit / "HANDOFF.md").write_text(text, encoding="utf-8")
        r = run([sys.executable, SCRIPTS / "check_staleness.py",
                 kit / "HANDOFF.md"], self.repo)
        self.assertIn("source: kit-dir", r.stdout)
        self.assertIn("Level: FRESH", r.stdout)

    def test_current_head_is_reported(self):
        kit, _ = self.create_kit("showhead", "--target", "skill")
        r = run([sys.executable, SCRIPTS / "check_staleness.py",
                 kit / "HANDOFF.md"], self.repo)
        self.assertIn("cur  HEAD  :", r.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
