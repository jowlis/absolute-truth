"""Autopilot: run cycles on a schedule, and ask the owner only when something needs them.

  py autopilot.py --install     turn it on: Windows Task Scheduler runs a tick every few hours
  py autopilot.py --uninstall   turn it off
  py autopilot.py --status      what it did lately, and whether it is waiting for you
  py autopilot.py --resume      you have looked at the problem: let it carry on
  py autopilot.py               one tick now (this is what the scheduler runs)
  py autopilot.py --mock        one tick with pretend models (data-mock/)

One tick:
  1. Does nothing if STOP exists, if it is waiting for you, or if a tick is already running.
  2. Checks the locked core and runs `run.py --verify`.
  3. Runs `run.py --cycles K`. K is `cycles_per_tick` from config.toml, but never more than
     what is left of `autopilot_max_cycles_per_day` (core/limits.toml) today (UTC).
     Every API call still passes the budget guard in core/budget.py.
  4. Runs `run.py --verify` again, rebuilds the website and, only if you switched it on,
     publishes it (commit docs/, push).

The autopilot never writes findings or cycle logs; only run.py, through core/recorder.py,
does. It only reads the knowledge base, to count today's cycles.

When it needs you, it writes data/NEEDS_OWNER.md, shows a Windows notification, and
pauses until you resume it (dashboard button, or --resume). Its own notes are in
data/autopilot.log and data/autopilot.json.
"""

import argparse
import json
import os
import subprocess
import sys
import tomllib
from datetime import datetime, timezone
from pathlib import Path

from core import budget as budget_module
from core import integrity, killswitch
from knowledge.db import KnowledgeBase
from loop.runlock import AlreadyRunning, RunLock

ROOT = Path(__file__).resolve().parent
TASK_NAME = "AbsoluteTruthAutopilot"
NOTICE = "NEEDS_OWNER.md"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def run_python(args: list, cwd: Path = ROOT) -> tuple[int, str]:
    """Run `python <args>` and return (exit code, all output)."""
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    p = subprocess.run([sys.executable, "-u", *args], cwd=cwd, env=env, capture_output=True,
                       text=True, encoding="utf-8", errors="replace", **_no_window())
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def notify(title: str, text: str) -> None:
    """Show a Windows notification (best effort; elsewhere it only prints)."""
    print(f"[{title}] {text}")
    if os.name != "nt":
        return
    script = ("Add-Type -AssemblyName System.Windows.Forms; Add-Type -AssemblyName System.Drawing; "
              "$n = New-Object System.Windows.Forms.NotifyIcon; "
              "$n.Icon = [System.Drawing.SystemIcons]::Information; $n.Visible = $true; "
              "$n.ShowBalloonTip(15000, $env:AT_TITLE, $env:AT_TEXT, 'Info'); "
              "Start-Sleep -Seconds 15; $n.Dispose()")
    try:
        subprocess.Popen(["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command", script],
                         env=dict(os.environ, AT_TITLE=title[:60], AT_TEXT=text[:240]),
                         **_no_window())
    except OSError:
        pass


def _no_window() -> dict:
    return {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}


class Autopilot:
    def __init__(self, *, data_dir: Path, mock: bool = False, settings: dict | None = None,
                 limits: dict | None = None, run=run_python, notify=notify, build_site=True):
        config = tomllib.loads((ROOT / "config.toml").read_text(encoding="utf-8"))
        self.settings = settings or config["autopilot"]
        self.limits = limits or budget_module.load_limits()
        self.data_dir = Path(data_dir)
        self.mock = mock
        self.run = run
        self.notify = notify
        self.build_site = build_site
        self.notice_file = self.data_dir / NOTICE
        self.state_file = self.data_dir / "autopilot.json"
        self.log_file = self.data_dir / "autopilot.log"

    # ---- its own notes -------------------------------------------------------

    def state(self) -> dict:
        if self.state_file.exists():
            return json.loads(self.state_file.read_text(encoding="utf-8"))
        return {"provider_down_ticks": 0, "bad_cycles_in_a_row": 0, "last_tick": None,
                "last_result": None}

    def save_state(self, state: dict) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.state_file.write_text(json.dumps(state, indent=2), encoding="utf-8")

    def note(self, line: str) -> str:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        with open(self.log_file, "a", encoding="utf-8") as f:
            f.write(f"{utc_now().strftime('%Y-%m-%d %H:%M')} UTC  {line}\n")
        print(line)
        return line

    def waiting_for_owner(self) -> bool:
        return self.notice_file.exists()

    def ask_owner(self, problem: str, what_to_do: str, details: str = "") -> str:
        """Pause and tell the owner. Nothing runs again until they resume."""
        text = (f"# The autopilot needs you\n\n{utc_now().strftime('%Y-%m-%d %H:%M')} UTC\n\n"
                f"**What happened:** {problem}\n\n**What to do:** {what_to_do}\n\n"
                "When it is sorted out, press **Resume autopilot** on the dashboard, or run "
                "`py autopilot.py --resume`. Until then the autopilot runs no cycles.\n")
        if details:
            text += "\n## Details\n\n```\n" + details.strip()[-3000:] + "\n```\n"
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.notice_file.write_text(text, encoding="utf-8")
        self.notify("Absolute Truth needs you", problem)
        return self.note(f"PAUSED, waiting for the owner: {problem}")

    def resume(self) -> str:
        self.notice_file.unlink(missing_ok=True)
        state = self.state()
        state["provider_down_ticks"] = state["bad_cycles_in_a_row"] = 0
        self.save_state(state)
        return self.note("Resumed by the owner.")

    # ---- counting ------------------------------------------------------------

    def cycles_today(self) -> int:
        db = self.data_dir / "knowledge.db"
        if not db.exists():
            return 0
        today = utc_now().date().isoformat()
        kb = KnowledgeBase(db, read_only=True)
        return sum(1 for log in kb.cycle_logs() if str(log.get("started_at", ""))[:10] == today)

    # ---- one tick ------------------------------------------------------------

    def tick(self) -> str:
        """Do one scheduled step. Returns a one-line summary (also written to the log)."""
        if killswitch.STOP_FILE.exists():
            return self.note("STOP is set; nothing run.")
        if self.waiting_for_owner():
            return self.note(f"Still waiting for the owner (see {self.notice_file}); nothing run.")
        try:
            with RunLock(self.data_dir / "autopilot.lock"):
                result = self._tick()
        except AlreadyRunning:
            return self.note("Another tick is still running; nothing run.")
        state = self.state()
        state["last_tick"], state["last_result"] = utc_now().isoformat(timespec="seconds"), result
        self.save_state(state)
        return result

    def _tick(self) -> str:
        problems = integrity.check_core()
        if problems:
            return self.ask_owner(
                "The protected core (core/) changed without your approval.",
                'If you made or accepted the change, approve it with `py lock_core.py "reason"` '
                "(or the dashboard). If you did not, find out what changed before resuming.",
                "\n".join(problems))
        if not self._verify("before the run"):
            return "Verify failed."

        left = self.limits["autopilot_max_cycles_per_day"] - self.cycles_today()
        if left <= 0:
            return self.note("Today's autopilot cycles are used up "
                             f"({self.limits['autopilot_max_cycles_per_day']} per day, UTC); "
                             "nothing run.")
        k = max(0, min(int(self.settings["cycles_per_tick"]), left))
        summary_file = self.data_dir / "autopilot_run.json"
        summary_file.unlink(missing_ok=True)
        code, output = self.run(["run.py", "--cycles", str(k), "--data-dir", str(self.data_dir),
                                 "--summary", str(summary_file)] + (["--mock"] if self.mock else []))
        (self.data_dir / "autopilot_last_run.txt").write_text(output, encoding="utf-8")
        summary = (json.loads(summary_file.read_text(encoding="utf-8"))
                   if summary_file.exists() else None)
        outcome = self._handle(code, output, summary)
        if self.waiting_for_owner():
            return outcome

        cycles = (summary or {}).get("cycles", [])
        if not cycles:
            return outcome
        if not self._verify("after the run"):
            return "Verify failed after the run."
        self._build_and_publish(cycles)
        return outcome

    def _verify(self, when: str) -> bool:
        code, output = self.run(["run.py", "--verify", "--data-dir", str(self.data_dir)])
        if code == 0:
            return True
        self.ask_owner(
            f"`run.py --verify` found problems {when}.",
            "Read the details below. Nothing more will be recorded until you resume, so the "
            "history stays as it is now.", output)
        return False

    def _handle(self, code: int, output: str, summary: dict | None) -> str:
        """Decide from run.py's summary whether this is normal waiting or needs the owner."""
        state = self.state()
        status = (summary or {}).get("status", "crashed")
        message = (summary or {}).get("message", "") or output.strip()[-300:]
        cycles = (summary or {}).get("cycles", [])

        for c in cycles:
            state["bad_cycles_in_a_row"] = (0 if c["outcome"] == "productive"
                                            else state["bad_cycles_in_a_row"] + 1)
        if cycles:
            state["provider_down_ticks"] = 0
        halted = (summary or {}).get("halted") or {}
        if halted.get("kind") == "ProviderUnavailable":
            state["provider_down_ticks"] += 1
        self.save_state(state)

        done = (f"{len(cycles)} cycle(s): " + ", ".join(
            f"#{c['cycle']} {c['track']} {c['outcome']}" for c in cycles)) if cycles else "no cycles"
        new_proposals = sum(c.get("proposals", 0) for c in cycles)
        if new_proposals:
            self.notify("Absolute Truth: new resource proposal",
                        f"{new_proposals} new proposal(s) for you to read (show.py proposals).")

        if status == "crashed":
            return self.ask_owner("A run stopped with an unexpected error.",
                                  "Look at the details (and data/autopilot_last_run.txt). It may "
                                  "be a bug worth fixing before more cycles run.", output)
        if status == "core_changed":
            return self.ask_owner("run.py refused to run: the core changed without approval.",
                                  'Approve the change with `py lock_core.py "reason"`, or undo it.',
                                  message)
        if status == "model_missing":
            return self.ask_owner("A model in config.toml is no longer available to your key.",
                                  "Run `py run.py --list-models` and update config.toml.", message)
        if status in ("stopped", "already_running"):
            return self.note(f"Nothing run: {message}")
        if halted.get("kind") == "BudgetExceeded" and "per month" in halted.get("message", ""):
            return self.ask_owner("This month's spending cap is reached.",
                                  "Nothing to fix if that is expected: runs continue next month. "
                                  "To allow more, raise budget_usd_per_month in core/limits.toml "
                                  "and approve it.", halted["message"])
        if state["provider_down_ticks"] >= int(self.settings["provider_down_ticks"]):
            return self.ask_owner(
                f"A model has been unreachable for {state['provider_down_ticks']} ticks in a row.",
                "Check the provider (try `py run.py --ping A` and `--ping B`) and consider other "
                "models or backups in config.toml.", halted.get("message", message))
        if state["bad_cycles_in_a_row"] >= int(self.settings["bad_cycles_in_a_row"]):
            return self.ask_owner(
                f"{state['bad_cycles_in_a_row']} cycles in a row failed or were unproductive.",
                "Read the last cycle logs (`py show.py path`) to see why; the models may be "
                "stuck or a tool may be broken.", output)
        if halted:
            return self.note(f"{done}; then paused until a later tick: {halted['message']}")
        return self.note(f"{done}.")

    def _build_and_publish(self, cycles: list) -> None:
        if not self.build_site:
            return
        code, output = self.run(["website/build.py"] + (["--mock"] if self.mock else []))
        if code != 0:
            self.notify("Absolute Truth: website build failed", output.strip()[-200:])
            self.note("Website build failed; see data/autopilot_last_run.txt.")
            (self.data_dir / "autopilot_last_run.txt").write_text(output, encoding="utf-8")
            return
        if self.mock or not self.settings.get("publish"):
            return
        numbers = [c["cycle"] for c in cycles]
        label = (f"cycle {numbers[0]}" if len(numbers) == 1
                 else f"cycles {numbers[0]}-{numbers[-1]}")
        steps = [["git", "add", "docs"],
                 ["git", "commit", "-m", f"Autopilot: publish website after {label}"],
                 ["git", "push"]]
        for step in steps:
            p = subprocess.run(step, cwd=ROOT, capture_output=True, text=True, **_no_window())
            if p.returncode != 0 and not (step[1] == "commit" and "nothing to commit" in p.stdout):
                self.notify("Absolute Truth: publishing failed", (p.stderr or p.stdout)[-200:])
                self.note(f"Publishing failed at `{' '.join(step[:2])}`: "
                          f"{(p.stderr or p.stdout).strip()[-200:]}")
                return
        self.note(f"Published the website ({label}).")


# ---- turning the schedule on and off (Windows Task Scheduler) -----------------------

def scheduled() -> bool | None:
    """True if the scheduled task exists, False if not, None if this isn't Windows."""
    if os.name != "nt":
        return None
    p = subprocess.run(["schtasks", "/Query", "/TN", TASK_NAME], capture_output=True,
                       **_no_window())
    return p.returncode == 0


def install(every_hours: int) -> str:
    if os.name != "nt":
        return ("Task Scheduler is Windows only. On Mac/Linux add a cron line, for example:\n"
                f"  0 */{every_hours} * * *  cd {ROOT} && {sys.executable} autopilot.py")
    pythonw = Path(sys.executable).with_name("pythonw.exe")   # runs without a console window
    python = pythonw if pythonw.exists() else Path(sys.executable)
    command = f'"{python}" "{ROOT / "autopilot.py"}"'
    p = subprocess.run(["schtasks", "/Create", "/TN", TASK_NAME, "/SC", "HOURLY",
                        "/MO", str(every_hours), "/TR", command, "/F"],
                       capture_output=True, text=True, **_no_window())
    if p.returncode != 0:
        return f"Could not create the scheduled task: {(p.stderr or p.stdout).strip()}"
    return (f"Autopilot on: a tick every {every_hours} hour(s) while you are signed in to "
            "Windows and the computer is awake.")


def uninstall() -> str:
    if os.name != "nt":
        return "Task Scheduler is Windows only; remove the cron line instead."
    p = subprocess.run(["schtasks", "/Delete", "/TN", TASK_NAME, "/F"], capture_output=True,
                       text=True, **_no_window())
    return "Autopilot off." if p.returncode == 0 else "Autopilot was not on."


def status_text(pilot: Autopilot) -> str:
    on = scheduled()
    lines = [f"Schedule: {'on' if on else 'off' if on is False else 'not Windows (use cron)'}",
             f"Cycles today (UTC): {pilot.cycles_today()} of "
             f"{pilot.limits['autopilot_max_cycles_per_day']}"]
    if pilot.waiting_for_owner():
        lines.append(f"WAITING FOR YOU: see {pilot.notice_file}")
    if pilot.log_file.exists():
        lines += ["", "Recent notes:"] + pilot.log_file.read_text(
            encoding="utf-8").splitlines()[-10:]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run cycles on a schedule.")
    parser.add_argument("--mock", action="store_true", help="pretend models, data-mock/")
    parser.add_argument("--data-dir", help="where the data is (default: data/ or data-mock/)")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--install", action="store_true", help="turn the schedule on")
    group.add_argument("--uninstall", action="store_true", help="turn the schedule off")
    group.add_argument("--status", action="store_true", help="show what the autopilot is doing")
    group.add_argument("--resume", action="store_true", help="carry on after it asked for you")
    args = parser.parse_args()
    data_dir = Path(args.data_dir) if args.data_dir else ROOT / ("data-mock" if args.mock else "data")
    pilot = Autopilot(data_dir=data_dir, mock=args.mock)

    if args.install:
        print(install(int(pilot.settings["every_hours"])))
    elif args.uninstall:
        print(uninstall())
    elif args.status:
        print(status_text(pilot))
    elif args.resume:
        pilot.resume()
    else:
        pilot.tick()
    return 0


if __name__ == "__main__":
    sys.exit(main())
