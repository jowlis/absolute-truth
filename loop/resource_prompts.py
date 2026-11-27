"""Everything the resource team (and the accuracy checker) is told.

The resource team works on the project's resources: audience and engagement, how the work
is presented, funding ideas, and how resources are divided. Its work is private to the
owner, except public updates, which are published only after a truth-team model from
another lab confirms they match the findings (constitution rules 9-12).
"""

import json
import re

from loop.prompts import CONSTITUTION, findings_summary
from loop.schemas import EXAMPLES

ROLES = {
    "planner": (
        "You are the resource team's PLANNER this cycle. You choose what the worker does, "
        "and later review the result critically."),
    "worker": (
        "You are the resource team's WORKER this cycle. You carry out the planner's brief "
        "and report proposals and, where useful, public updates."),
    "reviewer": (
        "You are the resource team's REVIEWER this cycle. Accept only proposals that are "
        "legal, honest, realistic and clearly serve the mission, and only public updates that "
        "are accurate, plain and not exaggerated."),
}

SYSTEM_EXPLAINED = """How this project works (set by the human owner; you cannot change it):
- The truth team (two models from different labs) works only on the mission. Everything
  it does is public. You may read its findings and cycles; you cannot change them, and it
  never sees your work.
- Your team (two models from different labs) works on the project's resources: audience
  and engagement, how the work is presented, funding ideas, volunteers, and how resources
  (money, models, effort) should be divided between the teams and tasks. In each cycle one
  of you plans and reviews, the other works; the roles swap every cycle.
- Your outputs:
  1. Proposals to the owner. They are private. Only the owner can act on them: spend
     money, change limits or models, contact anyone, or change the website.
  2. Public updates: short plain-language articles for the website about the truth
     team's work. One is published only if your reviewer accepts it AND a truth-team
     model from another lab confirms that every statement matches the cited findings.
- Your deliberations are private to the owner. You cannot post, email, contact anyone or
  spend money yourselves.
- Budget limits, models and rules are set by the owner in a locked core. You may
  recommend changes in a proposal.
- The owner answers proposals in the "Decisions" section of the owner's notes: Yes (the
  owner will act on it), No (do not propose it again) or Later (leave it until the owner
  raises it). Build on proposals marked Yes; a proposal with no answer is still waiting."""


def system_prompt(agent, other, role: str) -> str:
    return f"""{CONSTITUTION}

---

You are {agent.name}, a member of the resource team, working with {other.name}.

{ROLES[role]}

{SYSTEM_EXPLAINED}

How to reply: think as much as you need, then end your reply with exactly one JSON
object in a ```json code block, in the shape requested. Do not add other JSON blocks."""


def checker_system_prompt(agent) -> str:
    return f"""{CONSTITUTION}

---

You are {agent.name}, a member of the truth team. The resource team wants to publish an
article about the truth team's work. Your only job is to check its accuracy against the
findings: every statement must be supported by the cited findings, with their status
and confidence represented honestly (for example, a contested or conceptual finding must
not be presented as established fact). Exaggeration, hype or false urgency means reject.
Style is not your concern; accuracy is.

End your reply with exactly one JSON object in a ```json code block, in the shape requested."""


def _header(stage: str, cycle: int) -> str:
    return f"STAGE: {stage}\nCYCLE: {cycle}\n"


def _shape(stage: str) -> str:
    return f"Reply with JSON in this shape:\n```json\n{EXAMPLES[stage]}\n```"


def plan(cycle: int, overview: str, status: str, recent: str, proposals: str, updates: str,
         owner_notes: str, max_proposals: int, max_updates: int) -> str:
    return f"""{_header("resource_plan", cycle)}
Choose what the resource team does this cycle. Think about what would most help the
project gain resources for the mission now: audience, presentation, funding, volunteers,
better models, or a better division of the budget. The worker may produce at most
{max_proposals} proposals to the owner and at most {max_updates} public update(s).
Build on earlier cycles; avoid repeating proposals already made.

# The owner's notes to the team
{owner_notes}

# The project so far (public)
{overview}

# Resources and limits
{status}

# Your team's recent cycles
{recent}

# Proposals already made
{proposals}

# Public updates already published
{updates}

{_shape("resource_plan")}"""


def work(cycle: int, brief: str, overview: str, status: str, proposals: str, updates: str,
         owner_notes: str, findings: str, max_proposals: int, max_updates: int) -> str:
    return f"""{_header("resource_work", cycle)}
Planner's brief: {brief}

Report at most {max_proposals} proposals to the owner and at most {max_updates} public
update(s); empty lists are fine. A public update must cite the findings it relies on and
state nothing they don't support, with their status and confidence represented honestly.
Proposals must be legal, honest, realistic and serve the mission.

# The owner's notes to the team
{owner_notes}

# The project so far (public)
{overview}

# Resources and limits
{status}

# Proposals already made
{proposals}

# Public updates already published
{updates}

# The truth team's findings
{findings}

{_shape("resource_work")}"""


def review(cycle: int, brief: str, worker_name: str, report: dict) -> str:
    return f"""{_header("resource_review", cycle)}
{worker_name} carried out the brief below. Review every proposal and every public update
exactly once, by number (1 = first).

Number of proposals to review: {len(report.get("proposals", []))}
Number of public updates to review: {len(report.get("public_updates", []))}

Planner's brief: {brief}

# Report
```json
{json.dumps(report, indent=2, ensure_ascii=False)}
```

{_shape("resource_review")}"""


def accuracy_check(update: dict, cited: list, all_findings: list, max_chars: int) -> str:
    cited_text = "\n\n".join(
        f"{f['id']} [{f['status']}, {f['type']}, confidence {f['confidence']:.2f}]\n"
        f"Statement: {f['statement']}\nEvidence: {f['evidence']}" for f in cited) or "(none)"
    return f"""STAGE: accuracy_check
CYCLE: 0

# The article
Title: {update.get("title")}

{update.get("body")}

# The findings it cites
{cited_text}

# All findings (for context)
{findings_summary(all_findings, max_chars)}

Approve only if every statement in the article is supported by the cited findings and
their status and confidence are represented honestly. Otherwise reject, listing problems.

{_shape("accuracy_check")}"""


# ---- context builders --------------------------------------------------------------

def overview(roadmap: dict, findings: list, truth_logs: list) -> str:
    counts = {}
    for f in findings:
        counts[f["status"]] = counts.get(f["status"], 0) + 1
    latest = "\n".join(f"- Cycle {log['cycle']} ({log['outcome']}): {log.get('task') or '-'}"
                       for log in truth_logs[-5:]) or "- none yet"
    interpretation = roadmap.get("foundations", {}).get("interpretation") or "not set yet"
    return (f"Mission: Absolute Truth. The truth team's current interpretation: {interpretation}\n"
            f"Truth cycles so far: {len(truth_logs)}. Findings: {len(findings)} "
            f"({', '.join(f'{n} {s}' for s, n in sorted(counts.items())) or 'none'}).\n"
            f"Latest truth cycles:\n{latest}\n"
            "Public website: built from this data, with every transcript published.")


def status(agents_by_team: dict, budget, limits: dict) -> str:
    lines = []
    for team_name, agents in agents_by_team.items():
        lines.append(f"{team_name.capitalize()} team:")
        for agent in agents.values():
            cfg = agent.cfg
            free = cfg["input_price_per_mtok"] == 0 and cfg["output_price_per_mtok"] == 0
            price = ("free tier" if free else
                     f"${cfg['input_price_per_mtok']}/${cfg['output_price_per_mtok']} per million tokens")
            lines.append(f"- {agent.name}: {price}, up to {cfg['requests_per_day']} requests/day")
    ledger = budget._ledger()
    month = max(ledger["months"], default=None)
    monthly = limits["budget_usd_per_month"]
    share = limits["resource_team_budget_share"]
    spent = ledger["team_months"].get(month, {}) if month else {}
    lines.append(f"Monthly budget: ${monthly:.2f} (the owner's own contribution), split "
                 f"{share:.0%} resource team / {1 - share:.0%} truth team. Spent this month: "
                 f"truth ${spent.get('truth', 0):.2f}, resource ${spent.get('resource', 0):.2f}.")
    lines.append("Donations: none yet (not built; that is a later phase). Visitor statistics: "
                 "none (the website has no tracking, by the owner's choice).")
    return "\n".join(lines)


DECISION_LINE = re.compile(r"^\s*[-*]?\s*`?(R\d{4})`?\s*:\s*(.+?)\s*$", re.MULTILINE)


def owner_decisions(owner_notes: str) -> dict:
    """The owner's answers in owner_notes.md, one line each: "- R0007: No - reason".
    Returns {proposal id: answer}; a later line for the same id wins."""
    return {pid: answer.strip("` ") for pid, answer in DECISION_LINE.findall(owner_notes)}


def proposals_summary(proposals: list, decisions: dict | None = None) -> str:
    if not proposals:
        return "(none yet)"
    decisions = decisions or {}
    return "\n".join(f"- {p['id']} (cycle {p['cycle']}): {p['title']}. {p['proposal'][:300]}\n"
                     f"  Owner's answer: {decisions.get(p['id'], 'none yet')}"
                     for p in proposals[-20:])


def updates_summary(updates: list) -> str:
    if not updates:
        return "(none yet)"
    return "\n".join(f"- {u['id']}: {u['title']}" for u in updates[-20:])
