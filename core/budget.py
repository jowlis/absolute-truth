"""Budget guard. Every API call must pass `before_call` first and report back via `after_call`.

It enforces, in this order:
  1. the kill switch (STOP file),
  2. the per-run request cap,
  3. the dollar caps per run, per day and per month, and each team's share of the monthly
     budget (using the worst case: full input + max output tokens). Spending is kept in
     spending.json next to the daily usage file (in the private folder: it is resource status),
  4. each model's daily request limit (free tiers), persisted across runs,
  5. spacing between calls to respect each model's requests-per-minute.
"""

import datetime
import json
import time
import tomllib
from pathlib import Path

from core import killswitch

LIMITS_FILE = Path(__file__).resolve().parent / "limits.toml"


class BudgetExceeded(Exception):
    """The run's dollar or request cap would be exceeded."""


class DailyQuotaReached(Exception):
    """A model's daily free-tier request limit has been used up."""


def load_limits() -> dict:
    return tomllib.loads(LIMITS_FILE.read_text(encoding="utf-8"))


def _today() -> str:
    return datetime.datetime.now(datetime.timezone.utc).date().isoformat()


def cost_usd(model_cfg: dict, input_tokens: int, output_tokens: int) -> float:
    return (input_tokens * model_cfg["input_price_per_mtok"]
            + output_tokens * model_cfg["output_price_per_mtok"]) / 1_000_000


class Budget:
    def __init__(self, limits: dict, daily_usage_file: Path, team: str = "truth"):
        self.limits = limits
        self.team = team            # "truth" or "resource": each has its share of the month
        self.daily_usage_file = daily_usage_file
        self.spending_file = Path(daily_usage_file).parent / "spending.json"
        self.spending_file.parent.mkdir(parents=True, exist_ok=True)
        self.spent_usd = 0.0
        self.requests = 0
        self._last_call_at: dict[str, float] = {}

    # ---- checks before a call ------------------------------------------------

    def before_call(self, model_cfg: dict, estimated_input_tokens: int) -> None:
        killswitch.check()

        if self.requests >= self.limits["max_api_requests_per_run"]:
            raise BudgetExceeded(
                f"Request cap reached ({self.limits['max_api_requests_per_run']} per run).")

        worst_case = cost_usd(model_cfg, estimated_input_tokens, model_cfg["max_output_tokens"])
        day, month = _today(), _today()[:7]
        ledger = self._ledger()
        team_cap = self.limits["budget_usd_per_month"] * self.team_share()
        team_spent = ledger["team_months"].get(month, {}).get(self.team, 0.0)
        for label, spent, cap in (
                ("run", self.spent_usd, self.limits["budget_usd_per_run"]),
                ("day", ledger["days"].get(day, 0.0), self.limits["budget_usd_per_day"]),
                ("month", ledger["months"].get(month, 0.0), self.limits["budget_usd_per_month"]),
                (f"month for the {self.team} team", team_spent, team_cap)):
            if spent + worst_case > cap:
                raise BudgetExceeded(
                    f"Next call could cost up to ${worst_case:.4f}; spent ${spent:.4f} of the "
                    f"${cap:.2f} cap per {label}.")

        model = model_cfg["model"]
        used_today = self._daily_counts().get(model, 0)
        if used_today >= model_cfg["requests_per_day"]:
            raise DailyQuotaReached(
                f"{model} has used its {model_cfg['requests_per_day']} requests for today (UTC).")

        min_gap = 60.0 / model_cfg["requests_per_minute"]
        waited = time.monotonic() - self._last_call_at.get(model, -1e9)
        if waited < min_gap:
            time.sleep(min_gap - waited)
            killswitch.check()

        # Count the attempt now: failed attempts also use up quota.
        self.requests += 1
        self._bump_daily(model)
        self._last_call_at[model] = time.monotonic()

    # ---- accounting after a call ---------------------------------------------

    def after_call(self, model_cfg: dict, input_tokens: int, output_tokens: int) -> float:
        cost = cost_usd(model_cfg, input_tokens, output_tokens)
        self.spent_usd += cost
        if cost:
            ledger = self._ledger()
            day, month = _today(), _today()[:7]
            ledger["days"][day] = ledger["days"].get(day, 0.0) + cost
            ledger["months"][month] = ledger["months"].get(month, 0.0) + cost
            teams = ledger["team_months"].setdefault(month, {})
            teams[self.team] = teams.get(self.team, 0.0) + cost
            self.spending_file.write_text(json.dumps(ledger, indent=2), encoding="utf-8")
        return cost

    # ---- spending per day and month (UTC) ------------------------------------

    def team_share(self) -> float:
        share = float(self.limits["resource_team_budget_share"])
        return share if self.team == "resource" else 1.0 - share

    def _ledger(self) -> dict:
        ledger = {"days": {}, "months": {}, "team_months": {}}
        if self.spending_file.exists():
            ledger.update(json.loads(self.spending_file.read_text(encoding="utf-8")))
        return ledger

    # ---- daily request counts (UTC day) --------------------------------------

    def _daily_counts(self) -> dict:
        today = datetime.datetime.now(datetime.timezone.utc).date().isoformat()
        if self.daily_usage_file.exists():
            data = json.loads(self.daily_usage_file.read_text(encoding="utf-8"))
            if data.get("date") == today:
                return data["counts"]
        return {}

    def _bump_daily(self, model: str) -> None:
        today = datetime.datetime.now(datetime.timezone.utc).date().isoformat()
        counts = self._daily_counts()
        counts[model] = counts.get(model, 0) + 1
        self.daily_usage_file.parent.mkdir(parents=True, exist_ok=True)
        self.daily_usage_file.write_text(json.dumps({"date": today, "counts": counts}, indent=2), encoding="utf-8")
