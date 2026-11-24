"""The two teams: the truth team works only on the mission; the resource team works privately
and publishes only updates that pass the truth team's accuracy check."""

import json
import sys
import unittest
from unittest import mock

from core import recorder
from core.budget import Budget, BudgetExceeded, load_limits
from knowledge.db import KnowledgeBase
from tests.helpers import mock_runner, resource_runner, temp_dir
from tests.test_knowledge import add

MODEL = {"model": "m", "input_price_per_mtok": 1000.0, "output_price_per_mtok": 1000.0,
         "max_output_tokens": 100, "requests_per_minute": 600000, "requests_per_day": 10**6}


def project_with_findings():
    data, private = temp_dir(), temp_dir()
    truth = mock_runner(data)
    for _ in range(3):
        truth.run_cycle()
    return data, private, truth


class ResourceTeamTests(unittest.TestCase):
    def test_proposals_stay_private_and_checked_updates_are_published(self):
        data, private, _ = project_with_findings()
        log = resource_runner(data, private).run_cycle()
        self.assertEqual(log["outcome"], "productive")

        public = KnowledgeBase(data / "knowledge.db")
        secret = KnowledgeBase(private / "resources.db")
        self.assertEqual(public.resource_proposals(), [])                 # nothing private leaks
        self.assertEqual(len(secret.resource_proposals()), 1)
        updates = public.public_updates()
        self.assertEqual(len(updates), 1)
        self.assertIn("Nemotron", updates[0]["checked_by"])               # other lab than Gemma
        self.assertTrue((private / "latest_inbox.md").exists())
        self.assertTrue((private / "owner_notes.md").exists())
        self.assertTrue(list((private / "runs").glob("*/cycle_0001/transcript.json")))
        self.assertFalse((data / "proposals.md").exists())
        self.assertEqual(len(public.cycle_logs()), 3)                     # truth history untouched

    def test_update_is_not_published_if_the_accuracy_check_rejects_it(self):
        data, private, _ = project_with_findings()
        runner = resource_runner(data, private)
        for agent in runner.checkers.values():
            agent._accuracy_check = lambda cycle, prompt: {
                "verdict": "reject", "problems": ["overstates F0001"], "reason": "overstated"}
        log = runner.run_cycle()
        self.assertEqual(KnowledgeBase(data / "knowledge.db").public_updates(), [])
        self.assertTrue(any("accuracy check said no" in p for p in log["problems"]))

    def test_recorder_rules_for_public_updates(self):
        kb = KnowledgeBase(temp_dir() / "k.db")
        fid = add(kb)
        update = {"title": "t", "body": "b", "cites": [fid]}
        ok_review, ok_check = {"verdict": "accept"}, {"verdict": "approve", "reason": "fine"}
        author = recorder.Party("Gemma", "Google")
        reviewer = recorder.Party("Mistral", "Mistral AI")

        same_lab = recorder.record_public_update(
            kb, update=update, review=ok_review, check=ok_check, author=author,
            reviewer=reviewer, checker=recorder.Party("Gemini", "google"))
        self.assertIn("checker from the author's lab", same_lab["problems"][0])

        no_cites = recorder.record_public_update(
            kb, update=dict(update, cites=["F9999"]), review=ok_review, check=ok_check,
            author=author, reviewer=reviewer, checker=recorder.Party("Nemotron", "NVIDIA"))
        self.assertIn("cites no recorded finding", no_cites["problems"][0])

        ok = recorder.record_public_update(
            kb, update=update, review=ok_review, check=ok_check, author=author,
            reviewer=reviewer, checker=recorder.Party("Nemotron", "NVIDIA"))
        self.assertEqual(ok["published"], ["U0001: t"])
        self.assertEqual(len(kb.public_updates()), 1)

    def test_truth_team_never_sees_resource_information(self):
        data, private, truth = project_with_findings()
        resource_runner(data, private).run_cycle()
        truth.run_cycle()                                                   # after resource work
        transcripts = "".join(p.read_text(encoding="utf-8")
                              for p in (data / "runs").glob("*/cycle_*/transcript.json"))
        for secret in ("Monthly budget", "Placeholder proposal", "owner's notes", "Spent this month"):
            self.assertNotIn(secret, transcripts)


class TeamBudgetTests(unittest.TestCase):
    def test_each_team_has_its_share_of_the_month(self):
        d = temp_dir()
        limits = dict(load_limits(), budget_usd_per_run=100, budget_usd_per_day=100,
                      budget_usd_per_month=1.0, resource_team_budget_share=0.5)
        resource = Budget(limits, d / "daily.json", team="resource")
        resource.before_call(MODEL, 10)
        resource.after_call(MODEL, 450, 0)                                  # $0.45 of its $0.50
        with self.assertRaises(BudgetExceeded) as caught:
            Budget(limits, d / "daily.json", team="resource").before_call(MODEL, 10)
        self.assertIn("resource team", str(caught.exception))
        Budget(limits, d / "daily.json", team="truth").before_call(MODEL, 10)   # truth half is free


class RunTests(unittest.TestCase):
    def run_main(self, *args):
        import run
        with mock.patch.object(run.integrity, "check_core", return_value=[]), \
                mock.patch.object(sys, "argv", ["run.py", *args]), mock.patch("builtins.print") as out:
            code = run.main()
        return code, " ".join(str(c.args[0]) for c in out.call_args_list if c.args)

    def test_resource_team_runs_at_most_its_daily_cycles(self):
        data, private, _ = project_with_findings()
        args = ("--mock", "--team", "resource", "--data-dir", str(data), "--private-dir", str(private))
        self.assertEqual(self.run_main(*args, "--cycles", "3")[0], 0)
        self.assertEqual(len(KnowledgeBase(private / "resources.db").cycle_logs()), 1)
        code, output = self.run_main(*args)
        self.assertIn("already had", output)

    def test_real_runs_only_in_the_cloud_when_configured(self):
        with mock.patch.dict("os.environ", {"GITHUB_ACTIONS": ""}):
            code, output = self.run_main("--data-dir", str(temp_dir()), "--private-dir", str(temp_dir()))
        self.assertEqual(code, 1)
        self.assertIn("Runs happen in the cloud", output)

    def test_dashboard_does_not_start_local_runs_in_cloud_mode(self):
        import dashboard
        with mock.patch.object(dashboard, "runs_in_cloud", return_value=True):
            self.assertIn("in the cloud", dashboard.act({"action": "run"}))


if __name__ == "__main__":
    unittest.main()
