"""Offline checks of the real adapters' message conversion (no API calls)."""

import unittest

from agents.base import ToolCall
from agents.gemini_agent import _to_contents
from agents.openai_compat_agent import _to_openai

CONVERSATION = [
    {"role": "user", "content": "task"},
    {"role": "assistant", "content": "", "raw": None,
     "tool_calls": [ToolCall("c1", "run_python", {"code": "print(1)"}),
                    ToolCall("c2", "wikipedia_search", {"query": "q"})]},
    {"role": "tool", "tool_call_id": "c1", "name": "run_python", "content": "1"},
    {"role": "tool", "tool_call_id": "c2", "name": "wikipedia_search", "content": "result"},
    {"role": "assistant", "content": "final", "tool_calls": [], "raw": None},
]


class AdapterTests(unittest.TestCase):
    def test_gemini_groups_tool_results_into_one_turn(self):
        contents = _to_contents(CONVERSATION)
        self.assertEqual([c.role for c in contents], ["user", "model", "user", "model"])
        responses = contents[2].parts
        self.assertEqual([p.function_response.id for p in responses], ["c1", "c2"])
        self.assertEqual(responses[0].function_response.response, {"result": "1"})

    def test_openai_format(self):
        out = _to_openai(CONVERSATION)
        self.assertEqual([m["role"] for m in out], ["user", "assistant", "tool", "tool", "assistant"])
        self.assertEqual(out[1]["tool_calls"][0]["function"],
                         {"name": "run_python", "arguments": '{"code": "print(1)"}'})
        self.assertEqual(out[2], {"role": "tool", "tool_call_id": "c1", "content": "1"})



class FakeStream:
    """Pretends to be the openai library's stream of answer pieces."""

    def __init__(self, chunks, fail_after=None):
        self.chunks, self.fail_after = chunks, fail_after

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def __iter__(self):
        from agents.openai_compat_agent import _http
        for i, chunk in enumerate(self.chunks):
            if self.fail_after is not None and i == self.fail_after:
                raise _http.ReadTimeout("connection went quiet (test)")
            yield chunk


def chunk(content=None, tool_calls=None, reasoning=None, usage=None):
    from openai.types.chat import ChatCompletionChunk
    delta = {"content": content, "tool_calls": tool_calls}
    if reasoning:
        delta["reasoning_content"] = reasoning
    data = {"id": "x", "object": "chat.completion.chunk", "created": 1, "model": "m",
            "choices": [] if usage else [{"index": 0, "delta": delta, "finish_reason": None}]}
    if usage:
        data["usage"] = usage
    return ChatCompletionChunk.model_validate(data)


class StreamingTests(unittest.TestCase):
    def setUp(self):
        from unittest import mock
        from agents.openai_compat_agent import OpenAICompatAgent
        cfg = {"base_url": "https://example.invalid/v1", "label": "K", "lab": "L", "model": "m",
               "timeout_seconds": 5, "max_output_tokens": 100}
        self.agent = OpenAICompatAgent("B", cfg, budget=None, api_key="dummy")
        self.mock = mock

    def run_stream(self, stream):
        with self.mock.patch.object(self.agent.client.chat.completions, "create",
                                    return_value=stream):
            return self.agent._chat("system", [{"role": "user", "content": "hi"}], [])

    def test_text_tool_calls_and_usage_are_reassembled(self):
        stream = FakeStream([
            chunk(reasoning="thinking..."),
            chunk(content="<think>hidden</think>Hel"),
            chunk(content="lo"),
            chunk(tool_calls=[{"index": 0, "id": "c1", "type": "function",
                               "function": {"name": "run_python", "arguments": '{"co'}}]),
            chunk(tool_calls=[{"index": 0, "function": {"arguments": 'de": "print(1)"}'}}]),
            chunk(usage={"prompt_tokens": 11, "completion_tokens": 22, "total_tokens": 33}),
        ])
        reply = self.run_stream(stream)
        self.assertEqual(reply.text, "Hello")
        self.assertEqual(len(reply.tool_calls), 1)
        self.assertEqual(reply.tool_calls[0].id, "c1")
        self.assertEqual(reply.tool_calls[0].name, "run_python")
        self.assertEqual(reply.tool_calls[0].args, {"code": "print(1)"})
        self.assertEqual((reply.input_tokens, reply.output_tokens), (11, 22))

    def test_missing_usage_is_estimated(self):
        reply = self.run_stream(FakeStream([chunk(content="x" * 40)]))
        self.assertGreater(reply.input_tokens, 0)
        self.assertEqual(reply.output_tokens, 11)

    def test_connection_dropping_mid_stream_is_temporary(self):
        from agents.base import Transient
        with self.assertRaises(Transient):
            self.run_stream(FakeStream([chunk(content="a"), chunk(content="b")], fail_after=1))


if __name__ == "__main__":
    unittest.main()
