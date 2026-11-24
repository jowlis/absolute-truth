"""Phase 2: the locked core, protected recording, database rules, history chain, caps."""

import ast
import json
import shutil
import sqlite3
import sys
import unittest
from pathlib import Path
from unittest import mock

from core import integrity, killswitch, recorder
from core.budget import Budget, BudgetExceeded, load_limits
from knowledge.db import KnowledgeBase
from tests.helpers import ROOT, load_config, mock_runner, temp_dir
from tests.test_knowledge import add

MODEL = {"model": "m", "input_price_per_mtok": 1000.0, "output_price_per_mtok": 1000.0,
         "max_output_tokens": 100, "requests_per_minute": 600000, "requests_per_day": 10**6}


class LockedCoreTests(unittest.TestCase):
    def copy_core(self) -> Path:
        """A locked copy of the core (the real one may have changes awaiting approval)."""
        d = temp_dir() / "core"
        shutil.copytree(ROOT / "core", d, ignore=shutil.ignore_patterns("__pycache__"))
        integrity.lock("test baseline", d)
        return d

    def test_the_real_core_is_exactly_as_approved(self):
        self.assertEqual(integrity.check_core(), [],
                         'core/ changed without approval: run  py lock_core.py "reason"')

    def test_any_change_is_detected_and_lock_approves_it(self):
        core = self.copy_core()
        self.assertEqual(integrity.check_core(core), [])
        (core / "limits.toml").write_text("budget_usd_per_run = 1000\n", encoding="utf-8")
        (core / "extra.py").write_text("x = 1\n", encoding="utf-8")
        problems = integrity.check_core(core)
        self.assertIn("changed without approval: core/limits.toml", problems)
        self.assertIn("new file without approval: core/extra.py", problems)

        integrity.lock("test change", core)
        self.assertEqual(integrity.check_core(core), [])
        self.assertIn("Reason: test change", (core / "CHANGELOG.md").read_text(encoding="utf-8"))

    def test_windows_line_endings_do_not_count_as_changes(self):
        core = self.copy_core()
        path = core / "constitution.md"
        path.write_bytes(path.read_bytes().replace(b"\n", b"\r\n"))
        self.assertEqual(integrity.check_core(core), [])

    def test_run_refuses_when_the_core_was_changed(self):
        import run
        with mock.patch.object(run.integrity, "check_core", return_value=["changed: core/x"]), \
                mock.patch.object(sys, "argv", ["run.py", "--mock"]), \
                mock.patch("builtins.print"):
            self.assertEqual(run.main(), 1)

    def test_every_cycle_log_names_the_rules_it_ran_under(self):
        log = mock_runner(temp_dir()).run_cycle()
        self.assertEqual(log["rules"], integrity.rules_in_force())
        self.assertEqual(log["rules"]["constitution_version"], 3)


class DatabaseRuleTests(unittest.TestCase):
    def setUp(self):
        self.kb = KnowledgeBase(temp_dir() / "k.db")
        self.fid = add(self.kb)

    def test_findings_and_history_cannot_be_deleted_or_edited(self):
        for sql in ("DELETE FROM findings",
                    "UPDATE findings SET statement = 'rewritten'",
                    "UPDATE findings SET type = 'conceptual'",
                    "DELETE FROM finding_events",
                    "UPDATE finding_events SET reason = 'x'"):
            with self.subTest(sql=sql), self.assertRaises(sqlite3.DatabaseError):
                with self.kb.conn:
                    self.kb.conn.execute(sql)

    def test_confidence_can_fall_but_never_rise(self):
        with self.kb.conn:
            self.kb.conn.execute("UPDATE findings SET confidence = 0.1 WHERE id = ?", (self.fid,))
        with self.assertRaises(sqlite3.DatabaseError), self.kb.conn:
            self.kb.conn.execute("UPDATE findings SET confidence = 0.9 WHERE id = ?", (self.fid,))

    def test_status_changes_are_still_allowed(self):
        self.kb.set_status(self.fid, "contested", "reason", cycle=2)
        self.assertEqual(self.kb.finding(self.fid)["status"], "contested")


class HistoryChainTests(unittest.TestCase):
    def test_chain_verifies_and_detects_a_rewritten_cycle(self):
        d = temp_dir()
        runner = mock_runner(d)
        for _ in range(3):
            runner.run_cycle()
        kb = runner.kb
        self.assertEqual(kb.verify(), [])

        # Someone with access to the file removes a database rule and rewrites cycle 2.
        with kb.conn:
            kb.conn.execute("DROP TRIGGER cycles_fixed_once_chained")
            log = json.loads(kb.conn.execute(
                "SELECT log_json FROM cycles WHERE number = 2").fetchone()[0])
            log["outcome"] = "rewritten"
            kb.conn.execute("UPDATE cycles SET log_json = ? WHERE number = 2", (json.dumps(log),))
        problems = kb.verify()
        self.assertIn("database rule missing: cycles_fixed_once_chained", problems)
        self.assertIn("cycle 2 was changed after it was recorded", problems)

    def test_cycles_recorded_before_phase_2_are_chained_on_upgrade(self):
        d = temp_dir()
        runner = mock_runner(d)
        runner.run_cycle()
        runner.run_cycle()
        with runner.kb.conn:   # simulate a Phase 1 database: no hashes yet
            runner.kb.conn.execute("DROP TRIGGER cycles_fixed_once_chained")
            runner.kb.conn.execute("UPDATE cycles SET prev_hash = NULL, log_hash = NULL")
        kb = KnowledgeBase(d / "knowledge.db")
        self.assertEqual(kb.verify(), [])


class RecorderTests(unittest.TestCase):
    CLAIM = {"statement": "s", "type": "verifiable", "confidence": 0.6,
             "refutation_condition": "r", "evidence": "e", "sources": [], "builds_on": []}

    def record(self, claims, review, author_lab="Lab A", reviewer_lab="Lab B", max_claims=8):
        kb = KnowledgeBase(temp_dir() / "k.db")
        out = recorder.record_claims(
            kb, cycle=1, task_id=None, claims=claims, review=review,
            author=recorder.Party("Author", author_lab),
            reviewer=recorder.Party("Reviewer", reviewer_lab), max_claims=max_claims)
        return kb, out

    def test_same_lab_review_does_not_count(self):
        review = {"claim_reviews": [{"claim": 1, "verdict": "accept", "reason": "ok"}]}
        kb, out = self.record([self.CLAIM], review, reviewer_lab="lab a")
        self.assertEqual(kb.finding("F0001")["status"], "proposed")
        self.assertIn("same lab", out["problems"][0])

    def test_review_cannot_raise_confidence_and_bad_claims_are_skipped(self):
        review = {"claim_reviews": [{"claim": 1, "verdict": "accept", "confidence": 0.99,
                                     "reason": "ok"}]}
        bad = dict(self.CLAIM, type="certain")
        kb, out = self.record([self.CLAIM, bad], review)
        self.assertEqual(kb.finding("F0001")["confidence"], 0.6)
        self.assertIsNone(kb.finding("F0002"))
        self.assertIn("invalid type", out["problems"][0])

    def test_claim_limit_is_enforced_even_if_the_loop_lets_more_through(self):
        kb, out = self.record([self.CLAIM] * 5, None, max_claims=2)
        self.assertEqual(len(kb.findings()), 2)


class SpendingCapTests(unittest.TestCase):
    def test_daily_cap_holds_across_runs(self):
        d = temp_dir()
        limits = dict(load_limits(), budget_usd_per_run=100, budget_usd_per_day=0.5,
                      budget_usd_per_month=100)
        first = Budget(limits, d / "daily.json")
        first.before_call(MODEL, 10)
        first.after_call(MODEL, 400, 0)                      # $0.40 spent today
        second = Budget(limits, d / "daily.json")            # a new run, same day
        with self.assertRaises(BudgetExceeded) as caught:
            second.before_call(MODEL, 10)                    # worst case +$0.11 > $0.50
        self.assertIn("per day", str(caught.exception))

    def test_monthly_cap(self):
        d = temp_dir()
        limits = dict(load_limits(), budget_usd_per_run=100, budget_usd_per_day=100,
                      budget_usd_per_month=0.05)
        with self.assertRaises(BudgetExceeded) as caught:
            Budget(limits, d / "daily.json").before_call(MODEL, 10)
        self.assertIn("per month", str(caught.exception))


class BoundaryTests(unittest.TestCase):
    def test_core_imports_nothing_outside_core_and_the_standard_library(self):
        for path in (ROOT / "core").glob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                names = []
                if isinstance(node, ast.Import):
                    names = [a.name for a in node.names]
                elif isinstance(node, ast.ImportFrom):
                    names = [node.module or ""]
                for name in names:
                    top = name.split(".")[0]
                    with self.subTest(file=path.name, module=name):
                        self.assertTrue(top == "core" or top in sys.stdlib_module_names)

    def test_sandbox_gets_no_files_no_variables_and_no_network(self):
        from tools.sandbox import build_command
        command = build_command(load_config()["sandbox"], "test")
        for forbidden in ("-v", "--volume", "--mount", "-e", "--env", "--env-file", "--privileged"):
            self.assertNotIn(forbidden, command)
        self.assertIn("--network", command)
        self.assertEqual(command[command.index("--network") + 1], "none")

    def test_read_only_views_cannot_write(self):
        d = temp_dir()
        add(KnowledgeBase(d / "k.db"))
        reader = KnowledgeBase(d / "k.db", read_only=True)
        with self.assertRaises(sqlite3.OperationalError):
            reader.conn.execute("INSERT INTO finding_deps VALUES ('F0001', 'F0001')")

    def test_stop_file_halts_between_tool_calls(self):
        from tools.toolbox import Toolbox
        runner = mock_runner(temp_dir())
        stop = temp_dir() / "STOP"
        stop.touch()
        with mock.patch.object(killswitch, "STOP_FILE", stop):
            with self.assertRaises(killswitch.StopRequested):
                Toolbox(runner.agents["B"], runner.config, False).run("wikipedia_search", {})


if __name__ == "__main__":
    unittest.main()
