"""Create the agents described in config.toml."""

import os

from agents.base import Agent


def make_agents(config: dict, budget, mock: bool = False) -> dict[str, Agent]:
    agents = {}
    for key, cfg in config["models"].items():
        if mock:
            from agents.mock_agent import MockAgent
            # The mock has no rate limits and its own daily counter.
            cfg = dict(cfg, model=f"mock-{cfg['model']}", requests_per_minute=600_000,
                       requests_per_day=10**9,
                       fallback_models=[f"mock-{m}" for m in cfg.get("fallback_models", [])])
            agents[key] = MockAgent(key, cfg, budget)
            continue

        api_key = os.environ.get(cfg["key_env"], "").strip()
        if not api_key:
            raise SystemExit(f"Missing API key: set {cfg['key_env']} in .env (model {key}).")
        if cfg["provider"] == "gemini":
            from agents.gemini_agent import GeminiAgent
            agents[key] = GeminiAgent(key, cfg, budget, api_key)
        elif cfg["provider"] == "openai_compatible":
            from agents.openai_compat_agent import OpenAICompatAgent
            agents[key] = OpenAICompatAgent(key, cfg, budget, api_key)
        else:
            raise SystemExit(f"Unknown provider {cfg['provider']!r} for model {key}.")
    if len(agents) != 2:
        raise SystemExit("config.toml must define exactly two models: [models.A] and [models.B].")
    return agents
