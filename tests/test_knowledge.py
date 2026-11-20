import json
import unittest

from knowledge.db import KnowledgeBase
from knowledge.roadmap import Roadmap
from tests.helpers import temp_dir


def add(kb, builds_on=(), status="supported"):
    return kb.add_finding(cycle=1, task_id=None, statement="placeholder", type="verifiable",
                          confidence=0.5, refutation_condition="x", evidence="x", status=status,
                          sources=[], builds_on=list(builds_on), created_by="a",
                          reviewed_by="b", review_note="ok")


class RefutationCascadeTests(unittest.TestCase):
    def test_refuting_flags_all_dependents_transitively(self):
        kb = KnowledgeBase(temp_dir() / "k.db")
        a = add(kb)
        b = add(kb, [a])
        c = add(kb, [b])
        unrelated = add(kb)
        flagged = kb.set_status(a, "refuted", "counter-evidence", cycle=2)
        self.assertEqual(sorted(flagged), [b, c])
        self.assertTrue(kb.finding(c)["needs_review"])
        self.assertFalse(kb.finding(unrelated)["needs_review"])
        self.assertEqual(kb.finding(a)["status"], "refuted")

    def test_new_finding_on_refuted_work_is_flagged(self):
        kb = KnowledgeBase(temp_dir() / "k.db")
        a = add(kb)
        kb.set_status(a, "refuted", "x", cycle=2)
        later = add(kb, [a])
        self.assertTrue(kb.finding(later)["needs_review"])

    def test_re_review_clears_flag_and_keeps_history(self):
        kb = KnowledgeBase(temp_dir() / "k.db")
        a = add(kb)
        b = add(kb, [a])
        kb.set_status(a, "refuted", "x", cycle=2)
        kb.set_status(b, "contested", "re-examined", cycle=3)
        self.assertFalse(kb.finding(b)["needs_review"])
        events = [e["event"] for e in kb.events(b)]
        self.assertEqual(events, ["created as supported", "flagged for review",
                                  "status supported -> contested"])


class RoadmapTests(unittest.TestCase):
    def test_ops_keys_versions_and_validation(self):
        d = temp_dir()
        rm = Roadmap(d)
        result = rm.apply([
            {"op": "add", "kind": "milestone", "parent": "ROOT", "key": "m", "title": "t",
             "goal": "g", "why": "w"},
            {"op": "add", "kind": "task", "parent": "m", "key": "t", "title": "t", "goal": "g",
             "why": "w"},
            {"op": "add", "kind": "task", "parent": "t", "title": "t", "goal": "g", "why": "w"},
            {"op": "set_status", "id": "t", "status": "active"},           # no reason
            {"op": "set_status", "id": "t", "status": "active", "reason": "start"},
            {"op": "bogus"},
        ], cycle=1, author="X")
        self.assertEqual(result["keys"], {"m": "M1", "t": "T1"})
        self.assertEqual(len(result["changes"]), 3)
        self.assertEqual(len(result["errors"]), 3)
        self.assertEqual(rm.node("T1")["status"], "active")

        self.assertFalse((d / "roadmap.json").exists())   # nothing saved before commit
        rm.commit(1)
        rm.apply([{"op": "set_status", "id": "T1", "status": "done", "reason": "finished"}], 2, "Y")
        rm.commit(2)
        rm.commit(3)                                        # nothing pending: no new version
        versions = sorted((d / "roadmap_versions").glob("v*.json"))
        self.assertEqual([v.stem for v in versions], ["v0001", "v0002"])
        v2 = json.loads(versions[1].read_text(encoding="utf-8"))
        self.assertEqual(v2["changes_in_this_version"]["changes"], ["Y: T1 active -> done: finished"])
        self.assertIn("✓ **[T1]", (d / "roadmap.md").read_text(encoding="utf-8"))
        self.assertEqual(Roadmap(d).node("T1")["status"], "done")   # reloads from disk


if __name__ == "__main__":
    unittest.main()
