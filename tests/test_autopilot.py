"""The autopilot: when it runs cycles, when it waits, and when it asks the owner.

run.py is replaced by a fake that writes the summary run.py would write, so these tests
make no API calls and need no approved core.
"""

import json
import unittest
from pathlib import Path
from unittest import mock

import autopilot
from core import killswitch
from loop.runlock import AlreadyRunning, RunLock
from tests.helpers import temp_dir

SETTINGS = {"every_hours": 3, "cycles_per_tick": 2, "provider_down_ticks": 3,
            "bad_cycles_in_a_row": 3, "publish": False}
LIMITS = {"autopilot_max_cycles_per_day": 6}


def cycle(n, outcome="productive", proposals=0):
    return {"cycle": n, "track": "mission", "outcome": outcome, "findings": 1,
            "proposals": proposals}


class FakeRunPy:
    """Stands in for run.py: answers --verify, and writes a summary for --cycles."""

    def __init__(self, summaries=None, verify_ok=True):
        self.summaries = list(summaries or [])
        self.verify_ok = verify_ok
        self.calls = []

    def __call__(self, args):
        self.calls.append(args)
        if "--verify" in args:
            return (0, "OK") if self.verify_ok else (1, "history chain broken before cycle 3")
        summary = self.summaries.pop(0)
        if summary is not None:
            Path(args[args.index("--summary") + 1]).write_text(json.dumps(summary))
        return 0, "run output"

    def runs(self):
        return [a for a in self.calls if "--cycles" in a]


class AutopilotTests(unittest.TestCase):
    def setUp(self):
        self.dir = temp_dir()
        self.notices = []
        patches = [mock.patch.object(killswitch, "STOP_FILE", self.dir / "STOP"),
                   mock.patch.object(autopilot.integrity, "check_core", return_value=[])]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def pilot(self, fake, today=0):
        p = autopilot.Autopilot(data_dir=self.dir, settings=SETTINGS, limits=LIMITS, run=fake,
                                notify=lambda t, x: self.notices.append(t), build_site=False)
        p.cycles_today = lambda: today
        return p

    def test_normal_tick_verifies_before_and_after(self):
        fake = FakeRunPy([{"status": "done", "cycles": [cycle(1), cycle(2)]}])
        result = self.pilot(fake).tick()
        self.assertIn("2 cycle(s)", result)
        self.assertEqual(["--verify" in a for a in fake.calls], [True, False, True])
        self.assertEqual(fake.runs()[0][:3], ["run.py", "--cycles", "2"])
        self.assertFalse((self.dir / autopilot.NOTICE).exists())

    def test_daily_ceiling_limits_the_cycles(self):
        fake = FakeRunPy([{"status": "done", "cycles": [cycle(6)]}])
        self.pilot(fake, today=5).tick()
        self.assertEqual(fake.runs()[0][2], "1")
        fake = FakeRunPy([])
        self.assertIn("used up", self.pilot(fake, today=6).tick())
        self.assertEqual(fake.runs(), [])

    def test_failed_verify_pauses_until_resumed(self):
        fake = FakeRunPy([], verify_ok=False)
        pilot = self.pilot(fake)
        pilot.tick()
        notice = (self.dir / autopilot.NOTICE).read_text(encoding="utf-8")
        self.assertIn("history chain broken", notice)
        self.assertEqual(fake.runs(), [])
        self.assertEqual(self.notices, ["Absolute Truth needs you"])

        fake.verify_ok = True
        self.assertIn("waiting", pilot.tick())          # still paused: nothing runs
        self.assertEqual(len(fake.calls), 1)
        pilot.resume()
        fake.summaries = [{"status": "done", "cycles": [cycle(1)]}]
        self.assertIn("1 cycle(s)", pilot.tick())

    def test_unapproved_core_asks_the_owner(self):
        with mock.patch.object(autopilot.integrity, "check_core", return_value=["limits.toml changed"]):
            fake = FakeRunPy([])
            self.pilot(fake).tick()
        self.assertIn("lock_core", (self.dir / autopilot.NOTICE).read_text(encoding="utf-8"))
        self.assertEqual(fake.calls, [])

    def test_quota_and_daily_cap_just_wait(self):
        for halted in ({"kind": "DailyQuotaReached", "message": "used its 20 requests"},
                       {"kind": "BudgetExceeded", "message": "spent $5 of the $5.00 cap per day."}):
            fake = FakeRunPy([{"status": "halted", "halted": halted, "cycles": []}])
            self.assertIn("no cycles", self.pilot(fake).tick())
            self.assertFalse((self.dir / autopilot.NOTICE).exists())

    def test_monthly_cap_asks_the_owner(self):
        halted = {"kind": "BudgetExceeded", "message": "spent $20 of the $20.00 cap per month."}
        self.pilot(FakeRunPy([{"status": "halted", "halted": halted, "cycles": []}])).tick()
        self.assertIn("spending cap", (self.dir / autopilot.NOTICE).read_text(encoding="utf-8"))

    def test_provider_down_three_ticks_in_a_row_asks(self):
        down = {"status": "halted", "cycles": [],
                "halted": {"kind": "ProviderUnavailable", "message": "every model failed"}}
        fake = FakeRunPy([down, down])
        pilot = self.pilot(fake)
        pilot.tick()
        pilot.tick()
        self.assertFalse(pilot.waiting_for_owner())
        fake.summaries = [{"status": "done", "cycles": [cycle(1)]}, down, down, down]
        pilot.tick()                                    # a working cycle resets the count
        pilot.tick()
        pilot.tick()
        self.assertFalse(pilot.waiting_for_owner())
        pilot.tick()
        self.assertTrue(pilot.waiting_for_owner())

    def test_bad_cycles_in_a_row_ask(self):
        fake = FakeRunPy([{"status": "done", "cycles": [cycle(1, "unproductive"), cycle(2, "failed")]},
                          {"status": "done", "cycles": [cycle(3, "unproductive")]}])
        pilot = self.pilot(fake)
        pilot.tick()
        self.assertFalse(pilot.waiting_for_owner())
        pilot.tick()
        self.assertIn("3 cycles in a row", (self.dir / autopilot.NOTICE).read_text(encoding="utf-8"))

    def test_crash_and_missing_model_ask(self):
        for summary, words in ((None, "unexpected error"),
                               ({"status": "model_missing", "message": "gone"}, "no longer available")):
            self.dir = temp_dir()
            self.pilot(FakeRunPy([summary])).tick()
            self.assertIn(words, (self.dir / autopilot.NOTICE).read_text(encoding="utf-8"))

    def test_new_proposals_notify_without_pausing(self):
        fake = FakeRunPy([{"status": "done", "cycles": [cycle(1, proposals=1)]}])
        pilot = self.pilot(fake)
        pilot.tick()
        self.assertEqual(self.notices, ["Absolute Truth: new resource proposal"])
        self.assertFalse(pilot.waiting_for_owner())

    def test_stop_file_means_nothing_runs(self):
        (self.dir / "STOP").touch()
        fake = FakeRunPy([])
        self.assertIn("STOP", self.pilot(fake).tick())
        self.assertEqual(fake.calls, [])

    def test_one_run_at_a_time(self):
        lock = self.dir / "run.lock"
        with RunLock(lock):
            with self.assertRaises(AlreadyRunning):
                with RunLock(lock):
                    pass
        with RunLock(lock):                              # released afterwards
            pass


if __name__ == "__main__":
    unittest.main()
