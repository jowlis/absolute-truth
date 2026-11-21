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

    def test_temporary_server_errors_are_retried(self):
        from agents.base import Transient
        d = temp_dir()
        runner = mock_runner(d, limits=dict(load_limits(), retry_wait_seconds=[0]))
        agent = runner.agents["A"]
        real_chat, failures = agent._chat, iter([True, True])

        def flaky_chat(system, messages, tools):
            if next(failures, False):
                raise Transient("503 UNAVAILABLE (test)")
            return real_chat(system, messages, tools)

        messages = []
        agent.say = messages.append
        with mock.patch.object(agent, "_chat", flaky_chat):
            log = runner.run_cycle()
        self.assertEqual(log["outcome"], "productive")
        self.assertEqual(sum("retrying" in m for m in messages), 2)

    def test_provider_that_stays_down_ends_the_run_cleanly(self):
        from agents.base import ProviderUnavailable, Transient
        d = temp_dir()
        runner = mock_runner(d, limits=dict(load_limits(), retry_wait_seconds=[0]))

        def always_down(system, messages, tools):
            raise Transient("503 UNAVAILABLE (test)")

        agent = runner.agents["A"]
        self.assertEqual(len(agent.models), 3)        # main model + 2 backups in config.toml
        with mock.patch.object(agent, "_chat", always_down):
            with self.assertRaises(ProviderUnavailable):
                runner.run_cycle()
        self.assertEqual(runner.budget.requests, 12)  # 3 models x (first try + 3 retries)
        # No model replied, so the attempt is kept on disk but gets no cycle number.
        self.assertEqual(runner.kb.cycle_logs(), [])
        self.assertTrue(list((d / "runs" / "test").glob("cycle_0001_not_counted")))
        self.assertEqual(runner.kb.next_cycle_number(), 1)

    def test_interrupted_genesis_reuses_finished_drafts(self):
        from agents.base import ProviderUnavailable, Transient
        d = temp_dir()
        limits = dict(load_limits(), retry_wait_seconds=[0])
        runner = mock_runner(d, limits=limits)

        def always_down(system, messages, tools):
            raise Transient("429 provider overloaded (test)")

        # Attempt 1: model A drafts, then model B is down for good.
        with mock.patch.object(runner.agents["B"], "_chat", always_down):
            with self.assertRaises(ProviderUnavailable):
                runner.run_cycle()
        self.assertEqual(runner.kb.cycle_logs(), [])          # nothing recorded: no number
        self.assertTrue((d / "reply_cache.json").exists())

        # Attempt 2 (a new run): A's draft is reused, so A only has to merge.
        runner2 = mock_runner(d, limits=limits)
        messages = []
        runner2.say = messages.append
        log = runner2.run_cycle()
        self.assertEqual(log["cycle"], 1)
        self.assertEqual(log["outcome"], "productive")
        self.assertEqual(sum("reusing" in m for m in messages), 1)
        transcript = json.loads((d / "runs" / "test" / "cycle_0001" / "transcript.json")
                                .read_text(encoding="utf-8"))
        self.assertIn("reused_from_run", transcript[0])
        self.assertFalse((d / "reply_cache.json").exists())  # cleared once the cycle completed

    def test_reply_from_backup_model_is_reused_on_next_run(self):
        from agents.base import ProviderUnavailable, Transient
        d = temp_dir()
        limits = dict(load_limits(), retry_wait_seconds=[0])
        runner = mock_runner(d, limits=limits)
        a = runner.agents["A"]
        main, real_chat = a.models[0], a._chat

        def main_down(system, messages, tools):
            if a.cfg["model"] == main:
                raise Transient("503 (test)")
            return real_chat(system, messages, tools)

        def always_down(system, messages, tools):
            raise Transient("timeout (test)")

        # Run 1: A's main model is busy, its backup drafts; then B is down for good.
        with mock.patch.object(a, "_chat", main_down), \
                mock.patch.object(runner.agents["B"], "_chat", always_down):
            with self.assertRaises(ProviderUnavailable):
                runner.run_cycle()

        # Run 2 starts on A's main model again, yet still reuses the backup's draft.
        runner2 = mock_runner(d, limits=limits)
        log = runner2.run_cycle()
        self.assertEqual(log["outcome"], "productive")
        transcript = json.loads((d / "runs" / "test" / "cycle_0001" / "transcript.json")
                                .read_text(encoding="utf-8"))
        self.assertEqual(transcript[0]["model"].split(", ")[-1].rstrip(")"), a.models[1])
        self.assertIn("reused_from_run", transcript[0])

    def test_failing_web_search_never_switches_the_model(self):
        from agents.base import RateLimited
        from tools.toolbox import Toolbox
        d = temp_dir()
        runner = mock_runner(d)
        agent = runner.agents["A"]
        main = agent.cfg["model"]

        def no_quota(query):
            raise RateLimited("429 RESOURCE_EXHAUSTED (test)")

        with mock.patch.object(agent, "_web_search", no_quota):
            first = agent.web_search("anything")
            second = agent.web_search("anything else")
        self.assertIn("wikipedia_search", first)
        self.assertIn("unavailable for the rest of this run", second)
        self.assertEqual(agent.cfg["model"], main)               # still the main model
        self.assertEqual(runner.budget.requests, 1)              # one attempt, no retries
        self.assertNotIn("web_search", Toolbox(agent, runner.config, False).names())

    def test_each_cycle_starts_on_the_main_model(self):
        d = temp_dir()
        runner = mock_runner(d)
        agent = runner.agents["A"]
        agent.cfg["model"] = agent.models[2]                     # left on a backup
        runner.run_cycle()
        self.assertEqual(runner.kb.cycle_usage(1)["models"].count(agent.models[0]), 1)

    def test_busy_model_switches_to_backup(self):
        from agents.base import Transient
        d = temp_dir()
        runner = mock_runner(d, limits=dict(load_limits(), retry_wait_seconds=[0]))
        agent = runner.agents["A"]
        main, real_chat = agent.models[0], agent._chat

        def main_model_down(system, messages, tools):
            if agent.cfg["model"] == main:
                raise Transient("503 high demand (test)")
            return real_chat(system, messages, tools)

        with mock.patch.object(agent, "_chat", main_model_down):
            log = runner.run_cycle()
        self.assertEqual(log["outcome"], "productive")
        self.assertIn(agent.models[1], log["usage"]["models"])
        self.assertNotIn(main, log["usage"]["models"])
        self.assertEqual(log["usage"]["failed_attempts"], 4)

    def test_used_up_daily_quota_switches_to_backup(self):
        d = temp_dir()
        runner = mock_runner(d)
        agent = runner.agents["A"]
        agent.cfg["requests_per_day"] = 2           # each model may make 2 requests a day...
        for _ in range(2):                          # ...and the main model has used both
            runner.budget._bump_daily(agent.models[0])
        log = runner.run_cycle()
        self.assertEqual(log["outcome"], "productive")
        self.assertEqual(agent.cfg["model"], agent.models[1])

    def test_stop_file_halts_before_any_api_call(self):
        d = temp_dir()
        runner = mock_runner(d)
        stop = d / "STOP"
        stop.touch()
        with mock.patch.object(killswitch, "STOP_FILE", stop):
            with self.assertRaises(killswitch.StopRequested):
                runner.run_cycle()
        self.assertEqual(runner.budget.requests, 0)
        self.assertEqual(runner.kb.cycle_logs(), [])          # nothing happened: no number
        log = json.loads(next((d / "runs" / "test").glob("cycle_0001_not_counted")).joinpath(
            "log.json").read_text(encoding="utf-8"))
        self.assertEqual(log["outcome"], "interrupted")

    def test_budget_cap_halts_run_and_logs_interruption(self):
        d = temp_dir()
        runner = mock_runner(d, limits=dict(load_limits(), budget_usd_per_run=0.05), price=1.0)
        with self.assertRaises(BudgetExceeded):
            for _ in range(10):
                runner.run_cycle()
        self.assertLessEqual(runner.budget.spent_usd, 0.05)
        # The stopped cycle is logged: numbered if it had recorded something, else not counted.
        last = runner.kb.cycle_logs()[-1]["outcome"] if runner.kb.cycle_logs() else None
        not_counted = list((d / "runs" / "test").glob("*_not_counted"))
        self.assertTrue(last == "interrupted" or not_counted)


if __name__ == "__main__":
    unittest.main()
