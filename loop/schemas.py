"""The JSON each role must return, a readable example of each, and a small checker.

Spec mini-language (kept deliberately tiny):
  "field": str | int | float | bool | list   required field of that type
  "field?": ...                               optional field
  "field": ("enum", "a", "b")                 one of these values
  "field": [SUBSPEC]                          list of objects that each match SUBSPEC
"""

import json
import re

from core.verdicts import CLAIM_VERDICTS, PROPOSAL_VERDICTS

CLAIM = {
    "statement": str, "type": ("enum", "verifiable", "conceptual"), "confidence": float,
    "refutation_condition": str, "evidence": str, "sources": list, "builds_on": list,
}
FINDING_UPDATE = {
    "finding_id": str,
    "new_status": ("enum", "supported", "contested", "refuted", "conceptual", "superseded"),
    "superseded_by?": str, "reason": str,
}
CLAIM_REVIEW = {"claim": int, "verdict": ("enum",) + CLAIM_VERDICTS, "confidence?": float,
                "reason": str}
UPDATE_REVIEW = {"update": int, "agree": bool, "reason": str}
PROPOSAL = {"title": str, "proposal": str, "expected_benefit": str, "costs_and_risks": str}
PROPOSAL_REVIEW = {"proposal": int, "verdict": ("enum",) + PROPOSAL_VERDICTS, "reason": str}

GENESIS_DRAFT = {"interpretation": str, "knowable": list, "unknowable": list, "method": str,
                 "roadmap_ops": list, "claims": [CLAIM]}
GENESIS_MERGE = dict(GENESIS_DRAFT, disagreements=list)
GENESIS_REVIEW = {"claim_reviews": [CLAIM_REVIEW], "roadmap_concerns": list,
                  "disagreements": list, "next_step": str}
PLAN = {"track": ("enum", "mission", "resource"), "allocation_reasoning": str,
        "roadmap_ops": list, "task_id?": str, "task_brief": str, "why_this_task": str}
WORK = {"summary": str, "claims": [CLAIM], "finding_updates": [FINDING_UPDATE],
        "task_complete": bool, "open_questions": list, "suggested_next_step": str}
REVIEW = {"claim_reviews": [CLAIM_REVIEW], "update_reviews": [UPDATE_REVIEW],
          "task_complete": bool, "appeal_check": str, "disagreements": list, "next_step": str}
RESOURCE_WORK = {"summary": str, "proposals": [PROPOSAL], "suggested_next_step": str}
RESOURCE_REVIEW = {"proposal_reviews": [PROPOSAL_REVIEW], "disagreements": list,
                   "next_step": str}

# ---- examples shown to the agents (tests check they match the specs) ----------

_CLAIM_EXAMPLE = """{
      "statement": "<one clear, self-contained claim>",
      "type": "verifiable",
      "confidence": 0.7,
      "refutation_condition": "<what would prove this wrong>",
      "evidence": "<how it was established: reasoning steps, calculations, sources>",
      "sources": ["<url or reference>"],
      "builds_on": ["<id of an existing finding, e.g. F0003, or 'claim 1' for an earlier claim in this reply>"]
    }"""

EXAMPLES = {
    "genesis_draft": """{
  "interpretation": "<working interpretation of 'Absolute Truth' you can act on>",
  "knowable": ["<something that can be known, and why>"],
  "unknowable": ["<something that cannot or may not be known, and why>"],
  "method": "<how the search should proceed>",
  "roadmap_ops": [
    {"op": "add", "kind": "milestone", "parent": "ROOT", "key": "m1",
     "title": "<milestone>", "goal": "<what reaching it means>", "why": "<why it matters for the mission>"},
    {"op": "add", "kind": "task", "parent": "m1", "key": "t1",
     "title": "<small concrete task>", "goal": "<what done looks like>", "why": "<why it matters>"}
  ],
  "claims": [
    %s
  ]
}""" % _CLAIM_EXAMPLE,
    "genesis_merge": """{
  "interpretation": "<merged working interpretation>",
  "knowable": ["<...>"],
  "unknowable": ["<...>"],
  "method": "<...>",
  "roadmap_ops": [
    {"op": "add", "kind": "milestone", "parent": "ROOT", "key": "m1",
     "title": "<milestone>", "goal": "<...>", "why": "<...>"}
  ],
  "claims": [
    %s
  ],
  "disagreements": ["<where the drafts differed, and how it was resolved or that it is unresolved>"]
}""" % _CLAIM_EXAMPLE,
    "genesis_review": """{
  "claim_reviews": [
    {"claim": 1, "verdict": "accept_lower_confidence", "confidence": 0.5,
     "reason": "<why this verdict>"}
  ],
  "roadmap_concerns": ["<problem with the roadmap, if any>"],
  "disagreements": ["<anything you disagree with>"],
  "next_step": "<what the first planner should consider>"
}""",
    "plan": """{
  "track": "mission",
  "allocation_reasoning": "<why mission work (or resource work) is the better use of this cycle>",
  "roadmap_ops": [
    {"op": "add", "kind": "task", "parent": "M1", "key": "new1",
     "title": "<small concrete task>", "goal": "<what done looks like>", "why": "<why it matters>"},
    {"op": "set_status", "id": "T2", "status": "abandoned", "reason": "<why>"}
  ],
  "task_id": "new1",
  "task_brief": "<precise instructions for the worker: what to do and what counts as done>",
  "why_this_task": "<why this task, now>"
}""",
    "work": """{
  "summary": "<what you did, step by step, including tool results that matter>",
  "claims": [
    %s
  ],
  "finding_updates": [
    {"finding_id": "F0002", "new_status": "superseded", "superseded_by": "claim 1",
     "reason": "<why the replacement is more precise or correct>"}
  ],
  "task_complete": true,
  "open_questions": ["<what remains unclear>"],
  "suggested_next_step": "<a concrete next step>"
}""" % _CLAIM_EXAMPLE,
    "review": """{
  "claim_reviews": [
    {"claim": 1, "verdict": "accept", "reason": "<why>"},
    {"claim": 2, "verdict": "accept_lower_confidence", "confidence": 0.4, "reason": "<why>"}
  ],
  "update_reviews": [
    {"update": 1, "agree": true, "reason": "<why>"}
  ],
  "task_complete": true,
  "appeal_check": "<did any claim look shaped to impress rather than to be true?>",
  "disagreements": ["<points where you disagree with the worker>"],
  "next_step": "<what should happen next>"
}""",
    "resource_work": """{
  "summary": "<what you examined and how>",
  "proposals": [
    {"title": "<short title>", "proposal": "<what the owner could do>",
     "expected_benefit": "<how this advances the mission>",
     "costs_and_risks": "<money, time, legal or reputational risks>"}
  ],
  "suggested_next_step": "<...>"
}""",
    "resource_review": """{
  "proposal_reviews": [
    {"proposal": 1, "verdict": "accept", "reason": "<why>"}
  ],
  "disagreements": ["<...>"],
  "next_step": "<...>"
}""",
}

SPECS = {
    "genesis_draft": GENESIS_DRAFT, "genesis_merge": GENESIS_MERGE,
    "genesis_review": GENESIS_REVIEW, "plan": PLAN, "work": WORK, "review": REVIEW,
    "resource_work": RESOURCE_WORK, "resource_review": RESOURCE_REVIEW,
}


# ---- parsing and checking ----------------------------------------------------

FENCED_JSON = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)


def parse_reply(text: str) -> tuple[dict | None, str | None]:
    """Find the JSON object in a reply: the last ```json block, else the outermost {...}."""
    blocks = FENCED_JSON.findall(text or "")
    candidates = blocks[::-1]
    text = text or ""
    if not candidates and "{" in text and "}" in text[text.index("{"):]:
        candidates = [text[text.index("{"): text.rindex("}") + 1]]
    error = "no JSON object found in the reply"
    for candidate in candidates:
        obj, problem = _loads(candidate)
        if isinstance(obj, dict):
            return obj, None
        error = problem or "the JSON is not an object"
    return None, error


# A backslash and the character after it, read in pairs as JSON reads them.
ESCAPE_PAIR = re.compile(r"\\(.)", re.DOTALL)
VALID_ESCAPES = set('"\\/bfnrtu')


def _fix_backslashes(text: str) -> str:
    """Double every backslash that does not start a valid JSON escape (e.g. LaTeX \\hbar)."""
    return ESCAPE_PAIR.sub(
        lambda m: m.group(0) if m.group(1) in VALID_ESCAPES else "\\\\" + m.group(1), text)


def _loads(candidate: str):
    """json.loads, repairing stray backslashes (common in formulas) if needed."""
    try:
        return json.loads(candidate), None
    except json.JSONDecodeError:
        pass
    try:
        return json.loads(_fix_backslashes(candidate)), None
    except json.JSONDecodeError as e:
        return None, f"invalid JSON: {e.msg} at line {e.lineno}, column {e.colno}"


def check(obj, spec: dict, path: str = "") -> list[str]:
    """Return a list of problems (empty if `obj` matches `spec`)."""
    if not isinstance(obj, dict):
        return [f"{path or 'reply'} must be an object"]
    errors = []
    for raw_key, rule in spec.items():
        optional = raw_key.endswith("?")
        key = raw_key.rstrip("?")
        where = f"{path}.{key}" if path else key
        if key not in obj or obj[key] is None:
            if not optional:
                errors.append(f"missing field '{where}'")
            continue
        value = obj[key]
        if isinstance(rule, tuple) and rule[0] == "enum":
            if value not in rule[1:]:
                errors.append(f"'{where}' must be one of {list(rule[1:])}")
        elif isinstance(rule, list):
            if not isinstance(value, list):
                errors.append(f"'{where}' must be a list")
            else:
                for i, item in enumerate(value, start=1):
                    errors += check(item, rule[0], f"{where}[{i}]")
        elif rule is float:
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                errors.append(f"'{where}' must be a number")
        elif rule is int:
            if isinstance(value, bool) or not isinstance(value, int):
                errors.append(f"'{where}' must be a whole number")
        elif not isinstance(value, rule):
            errors.append(f"'{where}' must be of type {rule.__name__}")
    return errors
