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

from core.budget import Budget, DailyQuotaReached


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
    """The provider said "too many requests". Worth retrying after a wait."""


class Transient(Exception):
    """A temporary failure: server error (5xx), timeout or lost connection. Worth retrying."""


class ProviderUnavailable(Exception):
    """A provider kept failing after all retries. Ends the run; try again later."""


class Agent:
    def __init__(self, key: str, cfg: dict, budget: Budget, on_usage=None):
        self.key = key              # "A" or "B"
        self.cfg = dict(cfg)        # this model's section of config.toml (a copy)
        # The main model first, then backups from the same lab, used in order when the
        # current one stays unavailable or has used up its daily quota.
        self.models = [cfg["model"]] + list(cfg.get("fallback_models", []))
        self.budget = budget
        self.on_usage = on_usage    # callback(agent, purpose, in_tokens, out_tokens, cost)
        self.on_failure = None      # callback(agent, purpose, error) for failed attempts
        self.web_search_off = ""    # reason, once web search has failed for good in this run
        self.say = lambda message: None   # progress messages; the runner sets this

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
        """A tool, not the agent's main work: one attempt, no retries, no model switching.

        If the quota is used up ("too many requests"), web search is switched off for the
        rest of the run, so no time or quota is wasted on it.
        """
        if self.web_search_off:
            return f"[web search is unavailable for the rest of this run: {self.web_search_off}]"
        try:
            self.budget.before_call(self.cfg, estimate_tokens(query))
        except DailyQuotaReached as e:
            self.web_search_off = str(e)
            return f"[web search unavailable: {e}] Use wikipedia_search or arxiv_search instead."
        try:
            reply = self._web_search(query)
        except (RateLimited, Transient) as e:
            if self.on_failure:
                self.on_failure(self, "web_search", e)
            if isinstance(e, RateLimited):
                self.web_search_off = "quota used up"
            self.say(f"{self.cfg['model']}: web search failed ({type(e).__name__})"
                     + ("; switched off for this run" if self.web_search_off else ""))
            return (f"[web search failed: {type(e).__name__}: {str(e)[:120]}] "
                    "Use wikipedia_search or arxiv_search instead.")
        cost = self.budget.after_call(self.cfg, reply.input_tokens, reply.output_tokens)
        if self.on_usage:
            self.on_usage(self, "web_search", reply.input_tokens, reply.output_tokens, cost)
        return reply.text

    def _guarded(self, call, estimated_input_tokens: int, purpose: str) -> Reply:
        """Make one API call with retries; switch to a backup model if needed.

        `call` reads self.cfg["model"] when it runs, so after a switch it uses the backup.
        """
        limits = self.budget.limits
        waits = limits["retry_wait_seconds"]
        attempts = limits["retry_attempts"]
        while True:
            last_error = None
            for attempt in range(attempts + 1):
                try:
                    self.budget.before_call(self.cfg, estimated_input_tokens)
                except DailyQuotaReached as e:
                    last_error = e
                    break                      # try a backup model instead
                try:
                    reply = call()
                except (RateLimited, Transient) as e:
                    last_error = e
                    if self.on_failure:
                        self.on_failure(self, purpose, e)
                    if attempt == attempts:
                        break
                    wait = waits[min(attempt, len(waits) - 1)]
                    self.say(f"{self.cfg['model']}: {type(e).__name__} ({str(e)[:120]}); "
                             f"retrying in {wait} s")
                    time.sleep(wait)
                    continue
                cost = self.budget.after_call(self.cfg, reply.input_tokens, reply.output_tokens)
                if self.on_usage:
                    self.on_usage(self, purpose, reply.input_tokens, reply.output_tokens, cost)
                return reply

            if not self._switch_to_backup():
                if isinstance(last_error, DailyQuotaReached):
                    raise last_error
                raise ProviderUnavailable(
                    f"{self.cfg['label']} kept failing after {attempts} retries on every model "
                    f"({type(last_error).__name__}: {str(last_error)[:200]}). Try again later."
                ) from last_error

    def _switch_to_backup(self) -> bool:
        position = self.models.index(self.cfg["model"])
        if position + 1 >= len(self.models):
            return False
        old = self.cfg["model"]
        self.cfg["model"] = self.models[position + 1]
        self.say(f"{old} is unavailable; switching to backup model {self.cfg['model']}")
        return True

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
                    self.say(f"{self.cfg['label']} uses {call.name}: "
                             f"{str(next(iter(call.args.values()), ''))[:70]!r}")
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
