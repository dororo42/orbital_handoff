#!/usr/bin/env python3
"""Regression tests for the orbital_handoff scripts.

Runs on the stdlib (unittest) with zero dependencies; also collected by pytest.
Run from anywhere:
    python3 -m unittest discover -s <skill>/scripts/tests -v
Each test builds a throwaway git repo in a temp dir and drives the real
scripts end-to-end (the same scenarios that exposed the 2026-10-17 defects).
"""

import io
import re
import shutil
import subprocess
import sys
import tempfile
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


if __name__ == "__main__":
    unittest.main(verbosity=2)
