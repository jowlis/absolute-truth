"""Shared setup for tests: a temporary data folder and a mock runner."""

import tempfile
import tomllib
from pathlib import Path

from agents import make_agents, team
from core.budget import Budget, load_limits
from knowledge.db import KnowledgeBase
from knowledge.roadmap import Roadmap
from loop.cycle import CycleRunner

ROOT = Path(__file__).resolve().parent.parent


def load_config() -> dict:
    return tomllib.loads((ROOT / "config.toml").read_text(encoding="utf-8"))


def mock_runner(data_dir: Path, limits: dict | None = None, price: float = 0.0,
                sandbox_ok: bool = False) -> CycleRunner:
    config = load_config()
    for cfg in config["models"].values():
        cfg["input_price_per_mtok"] = price
        cfg["output_price_per_mtok"] = price
    limits = limits or load_limits()
    budget = Budget(limits, data_dir / "daily_usage.json")
    agents = team(make_agents(config, budget, mock=True), config, "truth")
    return CycleRunner(config=config, limits=limits, agents=agents,
                       kb=KnowledgeBase(data_dir / "knowledge.db"), roadmap=Roadmap(data_dir),
                       budget=budget, run_id="test", data_dir=data_dir, sandbox_ok=sandbox_ok)


def temp_dir() -> Path:
    return Path(tempfile.mkdtemp(prefix="truth-test-"))


def resource_runner(data_dir: Path, private_dir: Path, limits: dict | None = None):
    """A mock resource-team runner reading the public data in data_dir."""
    from loop.resource_cycle import ResourceRunner
    config = load_config()
    limits = limits or load_limits()
    budget = Budget(limits, private_dir / "daily_usage.json", team="resource")
    agents = make_agents(config, budget, mock=True)
    truth = team(agents, config, "truth")
    return ResourceRunner(config=config, limits=limits, agents=team(agents, config, "resource"),
                          kb=KnowledgeBase(private_dir / "resources.db"),
                          public_kb=KnowledgeBase(data_dir / "knowledge.db"),
                          public_data_dir=data_dir, checkers=truth, truth_agents=truth,
                          budget=budget, run_id="test", data_dir=private_dir, sandbox_ok=False)
