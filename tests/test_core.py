import unittest
from unittest import mock

from core import killswitch, verdicts
from core.budget import Budget, BudgetExceeded, DailyQuotaReached, load_limits
from tests.helpers import temp_dir

MODEL = {"model": "m", "input_price_per_mtok": 0.0, "output_price_per_mtok": 0.0,
         "max_output_tokens": 1000, "requests_per_minute": 600000, "requests_per_day": 3}


class VerdictTests(unittest.TestCase):
    def test_status_mapping(self):
        self.assertEqual(verdicts.finding_status("verifiable", "accept"), "supported")
        self.assertEqual(verdicts.finding_status("conceptual", "accept"), "conceptual")
        self.assertEqual(verdicts.finding_status("verifiable", "accept_lower_confidence"), "supported")
        self.assertEqual(verdicts.finding_status("verifiable", "contested"), "contested")
        self.assertIsNone(verdicts.finding_status("verifiable", "reject"))
        self.assertEqual(verdicts.finding_status("verifiable", None), "proposed")

    def test_review_never_raises_confidence(self):
        self.assertEqual(verdicts.final_confidence(0.5, 0.9), 0.5)
        self.assertEqual(verdicts.final_confidence(0.8, 0.3), 0.3)
        self.assertEqual(verdicts.final_confidence(1.7, None), 1.0)

    def test_status_update_needs_agreement(self):
        self.assertTrue(verdicts.status_update_allowed("refuted", True))
        self.assertFalse(verdicts.status_update_allowed("refuted", False))
        self.assertFalse(verdicts.status_update_allowed("proposed", True))



class BudgetTests(unittest.TestCase):
    def setUp(self):
        self.limits = load_limits()
        self.dir = temp_dir()

    def test_dollar_cap_blocks_call_before_it_happens(self):
        pricey = dict(MODEL, input_price_per_mtok=1000.0, output_price_per_mtok=1000.0)
        budget = Budget(dict(self.limits, budget_usd_per_run=0.5), self.dir / "d.json")
        with self.assertRaises(BudgetExceeded):
            budget.before_call(pricey, estimated_input_tokens=1000)  # worst case $2
        self.assertEqual(budget.requests, 0)

    def test_request_cap(self):
        budget = Budget(dict(self.limits, max_api_requests_per_run=2), self.dir / "d.json")
        budget.before_call(dict(MODEL, requests_per_day=99), 10)
        budget.before_call(dict(MODEL, requests_per_day=99), 10)
        with self.assertRaises(BudgetExceeded):
            budget.before_call(dict(MODEL, requests_per_day=99), 10)

    def test_daily_quota_persists_across_runs(self):
        Budget(self.limits, self.dir / "d.json").before_call(MODEL, 10)
        Budget(self.limits, self.dir / "d.json").before_call(MODEL, 10)
        third = Budget(self.limits, self.dir / "d.json")
        third.before_call(MODEL, 10)
        with self.assertRaises(DailyQuotaReached):
            third.before_call(MODEL, 10)

    def test_stop_file_halts_before_any_call(self):
        stop = self.dir / "STOP"
        stop.touch()
        budget = Budget(self.limits, self.dir / "d.json")
        with mock.patch.object(killswitch, "STOP_FILE", stop):
            with self.assertRaises(killswitch.StopRequested):
                budget.before_call(MODEL, 10)
        self.assertEqual(budget.requests, 0)


if __name__ == "__main__":
    unittest.main()
