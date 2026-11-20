"""Adapter for any API that speaks OpenAI's chat-completions format.

Many free providers do (OpenRouter, Groq, Mistral, NVIDIA, ...), so switching the
second model to another provider is only a change in config.toml.
"""

import json
import re

import openai

from agents.base import Agent, RateLimited, Reply, ToolCall

THINK_BLOCK = re.compile(r"<think>.*?</think>", re.DOTALL)


class OpenAICompatAgent(Agent):
    def __init__(self, key, cfg, budget, api_key: str, on_usage=None):
        super().__init__(key, cfg, budget, on_usage)
        self.client = openai.OpenAI(base_url=cfg["base_url"], api_key=api_key)

    def _chat(self, system: str, messages: list, tools: list) -> Reply:
        request = {
            "model": self.cfg["model"],
            "messages": [{"role": "system", "content": system}] + _to_openai(messages),
            "max_tokens": self.cfg["max_output_tokens"],
        }
        if tools:
            request["tools"] = [{"type": "function", "function": t} for t in tools]
        try:
            response = self.client.chat.completions.create(**request)
        except openai.RateLimitError as e:
            raise RateLimited(str(e)) from e

        if not response.choices:
            raise RuntimeError(f"Empty response from {self.cfg['model']}")
        message = response.choices[0].message
        text = THINK_BLOCK.sub("", message.content or "").strip()
        calls = []
        for c in message.tool_calls or []:
            try:
                args = json.loads(c.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {"_unparseable_arguments": c.function.arguments}
            calls.append(ToolCall(id=c.id, name=c.function.name, args=args))
        usage = response.usage
        return Reply(text=text, tool_calls=calls,
                     input_tokens=getattr(usage, "prompt_tokens", 0) or 0,
                     output_tokens=getattr(usage, "completion_tokens", 0) or 0)

    def list_models(self) -> list[str]:
        return sorted(m.id for m in self.client.models.list())


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
