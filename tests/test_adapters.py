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


if __name__ == "__main__":
    unittest.main()
