import json
import unittest

from loop import schemas


class SchemaTests(unittest.TestCase):
    def test_every_example_matches_its_spec(self):
        for stage, spec in schemas.SPECS.items():
            with self.subTest(stage=stage):
                self.assertEqual(schemas.check(json.loads(schemas.EXAMPLES[stage]), spec), [])

    def test_parse_reply_takes_last_json_block(self):
        text = 'thinking...\n```json\n{"a": 1}\n```\nmore\n```json\n{"b": 2}\n```'
        self.assertEqual(schemas.parse_reply(text), ({"b": 2}, None))

    def test_parse_reply_without_fence(self):
        self.assertEqual(schemas.parse_reply('Answer: {"a": [1, 2]} done'), ({"a": [1, 2]}, None))
        self.assertIsNone(schemas.parse_reply("no json here")[0])

    def test_formulas_with_single_backslashes_are_repaired(self):
        single = '```json\n{"a": "E = \\hbar \\omega"}\n```'
        mixed = '```json\n{"a": "\\\\hbar and \\hbar", "b": "line\\nnext"}\n```'
        self.assertEqual(schemas.parse_reply(single)[0], {"a": "E = \\hbar \\omega"})
        self.assertEqual(schemas.parse_reply(mixed)[0], {"a": "\\hbar and \\hbar", "b": "line\nnext"})

    def test_cut_off_reply_is_reported_not_crashed(self):
        obj, error = schemas.parse_reply('Reasoning... ```json\n{"track": "miss')
        self.assertIsNone(obj)
        self.assertTrue(error)

    def test_invalid_json_error_says_where(self):
        obj, error = schemas.parse_reply('```json\n{"a": 1,, }\n```')
        self.assertIsNone(obj)
        self.assertIn("line 1, column 9", error)

    def test_check_reports_problems(self):
        bad = {"summary": "s", "claims": [{"statement": "x", "type": "maybe", "confidence": "high"}],
               "finding_updates": [], "task_complete": "yes", "open_questions": [],
               "suggested_next_step": ""}
        errors = schemas.check(bad, schemas.WORK)
        self.assertIn("'claims[1].type' must be one of ['verifiable', 'conceptual']", errors)
        self.assertIn("'claims[1].confidence' must be a number", errors)
        self.assertIn("missing field 'claims[1].refutation_condition'", errors)
        self.assertIn("'task_complete' must be of type bool", errors)


if __name__ == "__main__":
    unittest.main()
