"""A pretend model for dry runs: no API calls, no cost.

It returns obviously generic placeholder content in exactly the JSON shapes the real
models must use, so the whole loop (roadmap, findings, review, refutation cascade,
resource track, logs) can be tested without spending tokens.

Scripted behaviour, so tests can check every path:
  cycle 2: the reviewer rejects claim 2
  cycle 3: the reviewer contests claim 2
  cycle 4: the worker proposes refuting F0002; the reviewer agrees (dependents get flagged)
  cycle 5: the planner chooses the resource track (if the core allows it)
  every work turn: one run_python tool call first, if the tool is available
"""

import json
import re

from agents.base import Agent, Reply, ToolCall, estimate_tokens


class MockAgent(Agent):
    def _chat(self, system: str, messages: list, tools: list) -> Reply:
        first = messages[0]["content"]
        stage = re.search(r"STAGE: (\w+)", first).group(1)
        cycle = int(re.search(r"CYCLE: (\d+)", first).group(1))
        used_tool = any(m["role"] == "tool" for m in messages)
        if stage == "work" and not used_tool and any(t["name"] == "run_python" for t in tools):
            return Reply(text="", tool_calls=[ToolCall(id="mock-1", name="run_python",
                                                       args={"code": "print(6 * 7)"})],
                         input_tokens=estimate_tokens(system, messages), output_tokens=20)
        obj = getattr(self, f"_{stage}")(cycle, first)
        text = (f"(mock {self.cfg['label']}) Placeholder reasoning.\n"
                f"```json\n{json.dumps(obj, indent=2)}\n```")
        return Reply(text=text, input_tokens=estimate_tokens(system, messages),
                     output_tokens=len(text) // 4)

    def _web_search(self, query: str) -> Reply:
        return Reply(text=f"Mock search result for {query!r}.", input_tokens=10, output_tokens=10)

    def list_models(self) -> list[str]:
        return [self.cfg["model"]]

    # ---- placeholder replies, one per stage ----------------------------------

    def _claim(self, cycle: int, n: int, kind: str, builds_on: list) -> dict:
        return {"statement": f"Placeholder {kind} claim {n} from cycle {cycle} (mock)",
                "type": kind, "confidence": 0.7, "refutation_condition": "Placeholder condition",
                "evidence": "Placeholder evidence", "sources": [], "builds_on": builds_on}

    def _genesis_draft(self, cycle, prompt):
        label = self.cfg["label"]
        return {
            "interpretation": f"Placeholder interpretation by {label} (mock)",
            "knowable": ["Placeholder knowable item (mock)"],
            "unknowable": ["Placeholder unknowable item (mock)"],
            "method": "Placeholder method (mock)",
            "roadmap_ops": [
                {"op": "add", "kind": "milestone", "parent": "ROOT", "key": "m1",
                 "title": "Placeholder milestone (mock)", "goal": "Placeholder goal",
                 "why": "Placeholder reason"},
                {"op": "add", "kind": "task", "parent": "m1", "key": "t1",
                 "title": "Placeholder task (mock)", "goal": "Placeholder goal",
                 "why": "Placeholder reason"},
            ],
            "claims": [self._claim(cycle, 1, "conceptual", [])],
        }

    def _genesis_merge(self, cycle, prompt):
        return dict(self._genesis_draft(cycle, prompt),
                    disagreements=["Placeholder disagreement between drafts (mock)"])

    def _genesis_review(self, cycle, prompt):
        count = _count(prompt, "claims")
        return {"claim_reviews": [{"claim": i, "verdict": "accept", "reason": "Placeholder"}
                                  for i in range(1, count + 1)],
                "roadmap_concerns": [], "disagreements": [],
                "next_step": "Placeholder next step (mock)"}

    def _plan(self, cycle, prompt):
        resource_ok = "Resource track allowed now: yes" in prompt
        if cycle % 5 == 0 and resource_ok:
            return {"track": "resource", "allocation_reasoning": "Placeholder: time to look at resources (mock)",
                    "roadmap_ops": [], "task_id": "", "task_brief": "Placeholder resource question (mock)",
                    "why_this_task": "Placeholder"}
        return {"track": "mission", "allocation_reasoning": "Placeholder: mission work first (mock)",
                "roadmap_ops": [{"op": "add", "kind": "task", "parent": "M1", "key": "next",
                                 "title": f"Placeholder task from cycle {cycle} (mock)",
                                 "goal": "Placeholder goal", "why": "Placeholder reason"}],
                "task_id": "next", "task_brief": "Placeholder brief (mock)",
                "why_this_task": "Placeholder"}

    def _work(self, cycle, prompt):
        # Only look at the knowledge base section (the example JSON also mentions ids).
        section = re.search(r"# Knowledge base[^\n]*\n(.*?)\n# Roadmap", prompt, re.DOTALL)
        kb_text = section.group(1) if section else ""
        ids = re.findall(r"\bF(\d{4})\b", kb_text)
        latest = [f"F{max(int(i) for i in ids):04d}"] if ids else []
        updates = []
        if cycle == 4 and "F0002" in kb_text:
            updates = [{"finding_id": "F0002", "new_status": "refuted",
                        "reason": "Placeholder counter-evidence (mock)"}]
        return {"summary": f"Placeholder work summary for cycle {cycle} (mock)",
                "claims": [self._claim(cycle, 1, "verifiable", latest),
                           self._claim(cycle, 2, "conceptual", latest)],
                "finding_updates": updates, "task_complete": True,
                "open_questions": ["Placeholder open question (mock)"],
                "suggested_next_step": "Placeholder next step (mock)"}

    def _review(self, cycle, prompt):
        reviews = []
        for i in range(1, _count(prompt, "claims") + 1):
            verdict, conf = "accept_lower_confidence", 0.6
            if i == 2 and cycle == 2:
                verdict, conf = "reject", None
            elif i == 2 and cycle == 3:
                verdict, conf = "contested", None
            review = {"claim": i, "verdict": verdict, "reason": f"Placeholder {verdict} (mock)"}
            if conf is not None:
                review["confidence"] = conf
            reviews.append(review)
        updates = [{"update": i, "agree": True, "reason": "Placeholder agreement (mock)"}
                   for i in range(1, _count(prompt, "finding updates") + 1)]
        return {"claim_reviews": reviews, "update_reviews": updates, "task_complete": True,
                "appeal_check": "Placeholder: nothing looks shaped to impress (mock)",
                "disagreements": [], "next_step": "Placeholder next step (mock)"}

    def _resource_work(self, cycle, prompt):
        return {"summary": "Placeholder resource summary (mock)",
                "proposals": [{"title": f"Placeholder proposal {i} (mock)",
                               "proposal": "Placeholder", "expected_benefit": "Placeholder",
                               "costs_and_risks": "Placeholder"} for i in (1, 2)],
                "suggested_next_step": "Placeholder next step (mock)"}

    def _resource_review(self, cycle, prompt):
        return {"proposal_reviews": [
                    {"proposal": 1, "verdict": "accept", "reason": "Placeholder (mock)"},
                    {"proposal": 2, "verdict": "reject", "reason": "Placeholder (mock)"}],
                "disagreements": [], "next_step": "Placeholder next step (mock)"}


def _count(prompt: str, what: str) -> int:
    match = re.search(rf"Number of {what} to review: (\d+)", prompt)
    return int(match.group(1)) if match else 0
