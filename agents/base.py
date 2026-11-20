"""What every agent (model adapter) has in common.

Conversations use one simple, provider-neutral message format:
  {"role": "user", "content": "..."}
  {"role": "assistant", "content": "...", "tool_calls": [ToolCall, ...], "raw": <provider data>}
  {"role": "tool", "tool_call_id": "...", "name": "...", "content": "..."}

Each adapter (Gemini, OpenAI-compatible, mock) converts this format to its API.
"raw" holds the provider's own copy of an assistant message, which some APIs need
back unchanged; it is never written to transcripts.

Every API call goes through `_guarded`, which applies the budget guard and kill
switch before the call and records tokens and cost after it.
"""

import json
import time
from dataclasses import dataclass, field

from core.budget import Budget


@dataclass
class ToolCall:
    id: str
    name: str
    args: dict


@dataclass
class Reply:
    text: str
    tool_calls: list = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    raw: object = None


class RateLimited(Exception):
    """The provider said "too many requests"."""


class Agent:
    def __init__(self, key: str, cfg: dict, budget: Budget, on_usage=None):
        self.key = key              # "A" or "B"
        self.cfg = cfg              # this model's section of config.toml
        self.budget = budget
        self.on_usage = on_usage    # callback(agent, purpose, in_tokens, out_tokens, cost)

    @property
    def name(self) -> str:
        return f"{self.cfg['label']} ({self.cfg['lab']}, {self.cfg['model']})"

    # ---- to be implemented by each adapter -----------------------------------

    def _chat(self, system: str, messages: list, tools: list) -> Reply:
        raise NotImplementedError

    def _web_search(self, query: str) -> Reply:
        raise NotImplementedError("This model has no built-in web search.")

    def list_models(self) -> list[str]:
        raise NotImplementedError

    # ---- guarded calls -------------------------------------------------------

    def chat(self, system: str, messages: list, tools: list, purpose: str) -> Reply:
        estimate = estimate_tokens(system, messages, tools)
        return self._guarded(lambda: self._chat(system, messages, tools), estimate, purpose)

    def web_search(self, query: str) -> str:
        reply = self._guarded(lambda: self._web_search(query), estimate_tokens(query), "web_search")
        return reply.text

    def _guarded(self, call, estimated_input_tokens: int, purpose: str) -> Reply:
        limits = self.budget.limits
        waits = limits["rate_limit_wait_seconds"]
        for attempt in range(limits["rate_limit_retries"] + 1):
            self.budget.before_call(self.cfg, estimated_input_tokens)
            try:
                reply = call()
            except RateLimited:
                if attempt == limits["rate_limit_retries"]:
                    raise
                time.sleep(waits[min(attempt, len(waits) - 1)])
                continue
            cost = self.budget.after_call(self.cfg, reply.input_tokens, reply.output_tokens)
            if self.on_usage:
                self.on_usage(self, purpose, reply.input_tokens, reply.output_tokens, cost)
            return reply
        raise RateLimited("still rate limited after retries")

    # ---- a full turn, including tool use -------------------------------------

    def converse(self, system: str, messages: list, toolbox, max_tool_steps: int,
                 purpose: str) -> str:
        """Run one turn: call the model, carry out its tool calls, repeat until it answers.

        `messages` is extended in place, so the caller keeps the whole exchange.
        Returns the model's final text.
        """
        tools = toolbox.definitions if (toolbox and self.cfg.get("supports_tools", True)) else []
        steps = 0
        while True:
            reply = self.chat(system, messages, tools, purpose)
            messages.append({"role": "assistant", "content": reply.text,
                             "tool_calls": reply.tool_calls, "raw": reply.raw})
            if not reply.tool_calls:
                return reply.text
            for call in reply.tool_calls:
                steps += 1
                if steps > max_tool_steps:
                    result = "[limit] Tool step limit reached. Give your final answer now."
                else:
                    result = toolbox.run(call.name, call.args)
                messages.append({"role": "tool", "tool_call_id": call.id,
                                 "name": call.name, "content": result})
            if steps >= max_tool_steps:
                tools = []  # one last call without tools, so the model must answer


def estimate_tokens(*parts) -> int:
    """Rough token estimate (about 4 characters per token), used only for the budget check."""
    text = json.dumps(parts, default=str, ensure_ascii=False)
    return len(text) // 4 + 1


def transcript_safe(messages: list) -> list:
    """Messages without provider-internal data, ready to save as JSON."""
    safe = []
    for m in messages:
        item = {k: v for k, v in m.items() if k != "raw"}
        if item.get("tool_calls"):
            item["tool_calls"] = [{"id": c.id, "name": c.name, "args": c.args}
                                  for c in item["tool_calls"]]
        elif "tool_calls" in item:
            del item["tool_calls"]
        safe.append(item)
    return safe
