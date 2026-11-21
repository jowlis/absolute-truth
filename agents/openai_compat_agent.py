"""Adapter for any API that speaks OpenAI's chat-completions format.

Many free providers do (OpenRouter, Groq, Mistral, NVIDIA, ...), so switching the
second model to another provider is only a change in config.toml.
"""

import json
import re
import time

import openai

from agents.base import Agent, RateLimited, Reply, ToolCall, Transient, estimate_tokens

try:  # the HTTP library the openai package uses (httpx2 in recent versions, httpx before)
    import httpx2 as _http
except ImportError:
    import httpx as _http

THINK_BLOCK = re.compile(r"<think>.*?</think>", re.DOTALL)
NETWORK_ERRORS = (_http.TimeoutException, _http.TransportError, TimeoutError, ConnectionError)


class OpenAICompatAgent(Agent):
    def __init__(self, key, cfg, budget, api_key: str, on_usage=None):
        super().__init__(key, cfg, budget, on_usage)
        # The library's own retries are off: all retries happen in Agent._guarded.
        self.client = openai.OpenAI(base_url=cfg["base_url"], api_key=api_key,
                                    timeout=cfg["timeout_seconds"], max_retries=0)

    def _chat(self, system: str, messages: list, tools: list) -> Reply:
        """Ask the model and receive its answer as a stream.

        Streaming means the time limit applies to silence, not to the whole answer:
        a model that thinks and writes for 15 minutes is fine, as long as it keeps
        sending. `max_reply_seconds` caps the total.
        """
        sent = [{"role": "system", "content": system}] + _to_openai(messages)
        request = {
            "model": self.cfg["model"],
            "messages": sent,
            "max_tokens": self.cfg["max_output_tokens"],
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if tools:
            request["tools"] = [{"type": "function", "function": t} for t in tools]
        try:
            stream = self.client.chat.completions.create(**request)
            with stream:
                text, calls, usage = self._collect(stream)
        except openai.RateLimitError as e:
            raise RateLimited(str(e)) from e
        except (openai.InternalServerError, openai.APIConnectionError) as e:  # incl. timeouts
            raise Transient(f"{type(e).__name__}: {e}") from e
        except NETWORK_ERRORS as e:   # a connection problem in the middle of the stream
            raise Transient(f"{type(e).__name__}: {e}") from e

        text = THINK_BLOCK.sub("", text).strip()
        tool_calls = []
        for index in sorted(calls):
            c = calls[index]
            try:
                args = json.loads(c["arguments"] or "{}")
            except json.JSONDecodeError:
                args = {"_unparseable_arguments": c["arguments"]}
            tool_calls.append(ToolCall(id=c["id"] or f"call_{index}", name=c["name"], args=args))
        # Some providers don't report usage when streaming; then estimate it.
        input_tokens = getattr(usage, "prompt_tokens", 0) or estimate_tokens(sent)
        output_tokens = getattr(usage, "completion_tokens", 0) or len(text) // 4 + 1
        return Reply(text=text, tool_calls=tool_calls,
                     input_tokens=input_tokens, output_tokens=output_tokens)

    def _collect(self, stream) -> tuple[str, dict, object]:
        """Put the streamed pieces back together: text, tool calls and token usage."""
        parts, calls, usage = [], {}, None
        thinking_chars = 0
        started = last_note = time.monotonic()
        limit = self.cfg.get("max_reply_seconds", 1200)
        for chunk in stream:
            if chunk.usage:
                usage = chunk.usage
            for choice in chunk.choices or []:
                delta = choice.delta
                if delta.content:
                    parts.append(delta.content)
                thinking_chars += len(getattr(delta, "reasoning_content", None) or "")
                for tc in delta.tool_calls or []:
                    slot = calls.setdefault(tc.index, {"id": None, "name": "", "arguments": ""})
                    slot["id"] = slot["id"] or tc.id
                    if tc.function:
                        slot["name"] = slot["name"] or (tc.function.name or "")
                        slot["arguments"] += tc.function.arguments or ""
            now = time.monotonic()
            if now - started > limit:
                raise Transient(f"the reply took longer than {limit} seconds")
            if now - last_note > 60:
                written = sum(len(p) for p in parts)
                self.say(f"{self.cfg['model']} is still working "
                         f"({thinking_chars} characters of thinking, {written} of answer so far)")
                last_note = now
        return "".join(parts), calls, usage

    def list_models(self) -> list[str]:
        return sorted(m.id for m in self.client.models.list())

    def free_models(self) -> list[str]:
        """Free models with details, for `run.py --list-models`.

        Free means a ":free" id or a price of 0 (OpenRouter publishes prices per model).
        """
        lines = []
        for m in sorted(self.client.models.list(), key=lambda m: m.id):
            pricing = getattr(m, "pricing", None) or {}
            zero_price = (str(pricing.get("prompt")) in ("0", "0.0")
                          and str(pricing.get("completion")) in ("0", "0.0"))
            if not (m.id.endswith(":free") or zero_price):
                continue
            tools = "tools" in (getattr(m, "supported_parameters", None) or [])
            context = getattr(m, "context_length", None)
            lines.append(f"{m.id}   (context {context or '?'} tokens, "
                         f"{'supports tools' if tools else 'NO tool support'})")
        return lines


def _to_openai(messages: list) -> list:
    out = []
    for m in messages:
        if m["role"] == "user":
            out.append({"role": "user", "content": m["content"]})
        elif m["role"] == "assistant":
            item = {"role": "assistant", "content": m["content"] or ""}
            if m.get("tool_calls"):
                item["tool_calls"] = [
                    {"id": c.id, "type": "function",
                     "function": {"name": c.name, "arguments": json.dumps(c.args)}}
                    for c in m["tool_calls"]]
            out.append(item)
        elif m["role"] == "tool":
            out.append({"role": "tool", "tool_call_id": m["tool_call_id"], "content": m["content"]})
    return out
