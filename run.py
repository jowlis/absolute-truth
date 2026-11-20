"""Run the mission.

  python run.py --mock --cycles 6     dry run: no API calls, writes to data-mock/
  python run.py --list-models         show which models your keys can use
  python run.py --cycles 3            real run: writes to data/

Before any API call the runner checks for a STOP file (kill switch) and the budget
limits in core/limits.toml.
"""

import argparse
import sys
import tomllib
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

from agents import make_agents
from agents.base import RateLimited
from core import budget as budget_module
from core import killswitch
from core.budget import Budget, BudgetExceeded, DailyQuotaReached
from knowledge.db import KnowledgeBase
from knowledge.roadmap import Roadmap
from loop.cycle import CycleRunner
from tools.sandbox import docker_available

ROOT = Path(__file__).resolve().parent


def main() -> int:
    parser = argparse.ArgumentParser(description="Run cycles of the Absolute Truth mission.")
    parser.add_argument("--cycles", type=int, default=1, help="number of cycles to run")
    parser.add_argument("--mock", action="store_true", help="dry run with pretend models")
    parser.add_argument("--list-models", action="store_true", help="list models your keys can use")
    parser.add_argument("--data-dir", help="where to keep data (default: data/ or data-mock/)")
    args = parser.parse_args()

    load_dotenv(ROOT / ".env")
    config = tomllib.loads((ROOT / "config.toml").read_text(encoding="utf-8"))
    limits = budget_module.load_limits()
    data_dir = Path(args.data_dir) if args.data_dir else ROOT / ("data-mock" if args.mock else "data")

    try:
        killswitch.check()
    except killswitch.StopRequested as e:
        print(e)
        return 1

    budget = Budget(limits, data_dir / "daily_usage.json")
    agents = make_agents(config, budget, mock=args.mock)

    if args.list_models:
        for key, agent in agents.items():
            print(f"\n[{key}] {agent.cfg['provider']} models available to your key "
                  f"(configured: {agent.cfg['model']}):")
            models = agent.list_models()
            free = agent.free_models() if hasattr(agent, "free_models") else []
            for line in (free or models):
                print("  ", line)
            if free:
                print(f"   (only free models shown; {len(models) - len(free)} paid models hidden)")
        return 0

    if not args.mock:
        for key, agent in agents.items():
            available = agent.list_models()
            if agent.cfg["model"] not in available:
                print(f"Model {key}: {agent.cfg['model']!r} is not available to your key. "
                      f"Run 'python run.py --list-models' and fix config.toml.")
                return 1

    sandbox_ok = docker_available()
    if not sandbox_ok:
        print("Warning: Docker is not available, so the Python sandbox is switched off.")

    run_id = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S") + ("-mock" if args.mock else "")
    kb = KnowledgeBase(data_dir / "knowledge.db")
    runner = CycleRunner(config=config, limits=limits, agents=agents, kb=kb,
                         roadmap=Roadmap(data_dir), budget=budget, run_id=run_id,
                         data_dir=data_dir, sandbox_ok=sandbox_ok)

    print(f"Run {run_id}: up to {args.cycles} cycle(s); data in {data_dir}")
    for key, agent in agents.items():
        print(f"  model {key}: {agent.name}")
    for _ in range(args.cycles):
        try:
            log = runner.run_cycle()
        except (killswitch.StopRequested, BudgetExceeded, DailyQuotaReached, RateLimited) as e:
            print(f"Run halted: {e}")
            break
        u = log["usage"]
        print(f"  cycle {log['cycle']}: {log['track']}, {log['outcome']}, "
              f"{len(log['results'])} new finding(s), {u['api_calls']} calls, ${u['cost_usd']:.4f}")
        if log["problems"]:
            print("    problems:", "; ".join(log["problems"]))

    print(f"Done. Spent ${budget.spent_usd:.4f} of ${limits['budget_usd_per_run']:.2f}; "
          f"{budget.requests} API requests. See: python show.py --help")
    return 0


if __name__ == "__main__":
    sys.exit(main())
