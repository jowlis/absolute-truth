"""Full dry runs of the loop with mock agents: no API calls, no cost."""

import json
import unittest
from unittest import mock

from core import killswitch
from core.budget import BudgetExceeded, load_limits
from tests.helpers import mock_runner, temp_dir


class MockRunTests(unittest.TestCase):
    def test_six_cycles_cover_every_path(self):
        d = temp_dir()
        runner = mock_runner(d)
        logs = [runner.run_cycle() for _ in range(6)]

        self.assertEqual([l["track"] for l in logs],
                         ["genesis", "mission", "mission", "mission", "resource", "mission"])
        self.assertTrue(all(l["outcome"] == "productive" for l in logs))

        # Roles rotate: planner alternates, and the worker is never its own reviewer.
        planners = [l["roles"]["planner"] for l in logs[1:]]
        self.assertTrue(all(a != b for a, b in zip(planners, planners[1:])))
        self.assertTrue(all(l["roles"]["worker"] != l["roles"]["reviewer"] for l in logs[1:]))

        kb = runner.kb
        statuses = {f["id"]: f["status"] for f in kb.findings()}
        self.assertEqual(statuses["F0001"], "conceptual")      # genesis claim
        self.assertEqual(statuses["F0002"], "refuted")         # refuted in cycle 4
        self.assertEqual(len(logs[1]["rejected_claims"]), 1)   # cycle 2 rejection
        self.assertIn("contested", statuses.values())          # cycle 3
        flagged = {f["id"] for f in kb.findings() if f["needs_review"]}
        self.assertTrue({"F0003", "F0004", "F0005", "F0006"} <= flagged)
        self.assertTrue(all(f["confidence"] <= 0.7 for f in kb.findings()))

        # Resource work produced a proposal, but no findings.
        self.assertEqual(len(kb.resource_proposals()), 1)
        self.assertEqual(logs[4]["results"], [])
        self.assertTrue((d / "resource_proposals.md").exists())

        # One roadmap version per cycle that changed it, readable files, full logs.
        self.assertEqual(len(list((d / "roadmap_versions").glob("v*.json"))), 5)
        self.assertIn("# Roadmap", (d / "roadmap.md").read_text(encoding="utf-8"))
        for n in range(1, 7):
            cycle_dir = d / "runs" / "test" / f"cycle_{n:04d}"
            log = json.loads((cycle_dir / "log.json").read_text(encoding="utf-8"))
            for key in ("task", "what_was_done", "results", "disagreements",
                        "roadmap_changes", "next_step", "outcome", "usage"):
                self.assertIn(key, log)
            self.assertGreater(log["usage"]["input_tokens"], 0)
            self.assertTrue(json.loads((cycle_dir / "transcript.json").read_text(encoding="utf-8")))
        self.assertEqual((d / "path.md").read_text(encoding="utf-8").count("# Cycle "), 6)

    def test_invalid_json_gets_one_retry_with_the_problems_explained(self):
        d = temp_dir()
        runner = mock_runner(d)
        runner.run_cycle()                                  # genesis
        agent = runner.agents["B"]                          # cycle 2 planner
        real_chat = agent._chat
        replies = iter(["I forgot the JSON."])

        def flaky_chat(system, messages, tools):
            text = next(replies, None)
            if text is not None:
                from agents.base import Reply
                return Reply(text=text, input_tokens=10, output_tokens=5)
            return real_chat(system, messages, tools)

        with mock.patch.object(agent, "_chat", flaky_chat):
            log = runner.run_cycle()
        self.assertEqual(log["outcome"], "productive")
        transcript = json.loads((d / "runs" / "test" / "cycle_0002" / "transcript.json").read_text(encoding="utf-8"))
        plan_messages = transcript[0]["messages"]
        self.assertIn("could not be used", plan_messages[2]["content"])

    def test_stop_file_halts_before_any_api_call(self):
        d = temp_dir()
        runner = mock_runner(d)
        stop = d / "STOP"
        stop.touch()
        with mock.patch.object(killswitch, "STOP_FILE", stop):
            with self.assertRaises(killswitch.StopRequested):
                runner.run_cycle()
        self.assertEqual(runner.budget.requests, 0)
        self.assertEqual(runner.kb.cycle_logs()[0]["outcome"], "interrupted")

    def test_budget_cap_halts_run_and_logs_interruption(self):
        d = temp_dir()
        runner = mock_runner(d, limits=dict(load_limits(), budget_usd_per_run=0.05), price=1.0)
        with self.assertRaises(BudgetExceeded):
            for _ in range(10):
                runner.run_cycle()
        self.assertLessEqual(runner.budget.spent_usd, 0.05)
        self.assertEqual(runner.kb.cycle_logs()[-1]["outcome"], "interrupted")


if __name__ == "__main__":
    unittest.main()
