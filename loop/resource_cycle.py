"""One cycle of the resource team.

  PLAN    one resource-team model chooses what to work on (audience, presentation,
          funding ideas, how resources are divided, ...)
  DO      the other resource-team model writes proposals to the owner and, where
          useful, a public update about the truth team's work
  REVIEW  the planner's model reviews each proposal and update
  CHECK   each accepted update is checked against the findings by a truth-team model
          from a different lab than its author
  RECORD  core/recorder.py keeps accepted proposals (PRIVATE knowledge base) and
          publishes approved updates (PUBLIC knowledge base); nothing else is touched

Everything else (transcripts, logs, proposals, the owner inbox) is written to the private
folder only. The truth team never sees any of it.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

from core import recorder, verdicts
from loop import prompts, resource_prompts
from loop.cycle import CycleRunner, _merge, _numbering_errors, _party

OWNER_NOTES_TEMPLATE = """# Notes from the owner to the resource team

The resource team reads this file at the start of every cycle. Edit it to answer
proposals, give decisions or share what you know (on GitHub: open this file in the
private repository and click the pencil icon).

## The owner's view (from the start)

The more resources the project has, the better models and tools it can use and the
faster it can pursue the mission. Resources depend on an audience willing to take part,
by donating or by helping with tasks. Early on, effort on resources may be worth more;
over time the balance should move towards the mission itself. You decide what to propose.
"""


class ResourceRunner(CycleRunner):
    def __init__(self, *, public_kb, public_data_dir: Path, checkers: dict, truth_agents: dict,
                 **kwargs):
        super().__init__(roadmap=None, **kwargs)
        self.public_kb = public_kb        # the truth team's knowledge base (read; updates only)
        self.public_data_dir = Path(public_data_dir)
        self.checkers = checkers          # truth-team agents that may check accuracy
        self.truth_agents = truth_agents
        for agent in checkers.values():
            agent.on_usage = self.record_usage
            agent.on_failure = self.record_failure
            agent.say = self.say
        notes = self.data_dir / "owner_notes.md"
        if not notes.exists():
            self.data_dir.mkdir(parents=True, exist_ok=True)
            notes.write_text(OWNER_NOTES_TEMPLATE, encoding="utf-8")

    def _initial_track(self) -> str:
        return "resource"

    def _system_prompt(self, agent, other, role: str) -> str:
        if role == "checker":
            return resource_prompts.checker_system_prompt(agent)
        return resource_prompts.system_prompt(agent, other, role)

    # ---- the cycle -------------------------------------------------------------------

    def _body(self, n: int, roles: dict, log: dict, transcript: list) -> None:
        planner = self.agents[roles["planner"]]
        worker = self.agents[roles["worker"]]
        reviewer = self.agents[roles["reviewer"]]
        limits = self.limits
        max_p, max_u = limits["max_proposals_per_cycle"], limits["max_public_updates_per_cycle"]

        findings = self.public_kb.findings()
        roadmap_file = self.public_data_dir / "roadmap.json"
        roadmap = json.loads(roadmap_file.read_text(encoding="utf-8")) if roadmap_file.exists() else {}
        overview = resource_prompts.overview(roadmap, findings, self.public_kb.cycle_logs())
        status = resource_prompts.status({"truth": self.truth_agents, "resource": self.agents},
                                         self.budget, limits)
        proposals = resource_prompts.proposals_summary(self.kb.resource_proposals())
        updates = resource_prompts.updates_summary(self.public_kb.public_updates())
        notes = (self.data_dir / "owner_notes.md").read_text(encoding="utf-8")

        # PLAN
        plan = self._ask(planner, worker, "planner", "resource_plan", resource_prompts.plan(
            n, overview, status, prompts.recent_cycles(self.kb.cycle_logs(last=3)),
            proposals, updates, notes, max_p, max_u), None, transcript)
        if not plan:
            log["what_was_done"] = "The planner did not produce a valid plan."
            return
        log["task"] = plan["task_brief"]
        log["allocation_reasoning"] = plan["why_this_task"]

        # DO
        report = self._ask(
            worker, planner, "worker", "resource_work", resource_prompts.work(
                n, plan["task_brief"], overview, status, proposals, updates, notes,
                prompts.findings_summary(findings, self.config["context"]["max_findings_chars"]),
                max_p, max_u),
            lambda r: ([f"too many proposals ({len(r['proposals'])}): at most {max_p}"]
                       if len(r["proposals"]) > max_p else [])
                      + ([f"too many public updates ({len(r['public_updates'])}): at most {max_u}"]
                         if len(r["public_updates"]) > max_u else []),
            transcript)
        if not report:
            log["what_was_done"] = "The worker did not produce a valid report."
            return
        log["what_was_done"] = report["summary"]
        proposals_in, updates_in = report["proposals"][:max_p], report["public_updates"][:max_u]

        # REVIEW
        review = self._ask(
            reviewer, worker, "reviewer", "resource_review",
            resource_prompts.review(n, plan["task_brief"], worker.name, report),
            lambda r: (_numbering_errors(r["proposal_reviews"], "proposal", len(proposals_in))
                       + _numbering_errors(r["update_reviews"], "update", len(updates_in))),
            transcript)

        # RECORD proposals (private)
        out = recorder.record_proposals(self.kb, cycle=n, proposals=proposals_in, review=review,
                                        author=_party(worker), reviewer=_party(reviewer))
        accepted = out.pop("accepted")
        _merge(log, out)

        # CHECK and publish updates (public, only if every check passes)
        verdict_by_number = {r["update"]: r for r in (review or {}).get("update_reviews", [])}
        for i, update in enumerate(updates_in, start=1):
            r = verdict_by_number.get(i)
            checker = self._checker_for(worker)
            if checker is None:
                log["problems"].append(f"update '{update.get('title')}' not published: no "
                                       "truth-team model from another lab is available to check it")
                continue
            check = None
            if r and r["verdict"] == "accept":
                cited = [f for c in update.get("cites") or []
                         if (f := self.public_kb.finding(str(c).strip()))]
                check = self._ask(checker, worker, "checker", "accuracy_check",
                                  resource_prompts.accuracy_check(
                                      update, cited, findings,
                                      self.config["context"]["max_findings_chars"]),
                                  None, transcript)
            published = recorder.record_public_update(
                self.public_kb, update=update, review=r, check=check, author=_party(worker),
                reviewer=_party(reviewer), checker=_party(checker))
            log.setdefault("published_updates", [])
            log["published_updates"] += published["published"]
            log["problems"] += published["problems"]

        if review:
            log["disagreements"] += review["disagreements"]
        log["next_step"] = (review or {}).get("next_step") or report["suggested_next_step"]
        produced = accepted + len(log.get("published_updates", []))
        log["outcome"] = "productive" if verdicts.is_productive(0, 0, produced) else "unproductive"
        self._write_owner_files(n, log)

    def _checker_for(self, author):
        """A truth-team model from a different lab than the update's author."""
        for agent in self.checkers.values():
            if agent.cfg["lab"].lower() != author.cfg["lab"].lower():
                return agent
        return None

    # ---- private files for the owner ---------------------------------------------------

    def _write_owner_files(self, n: int, log: dict) -> None:
        """proposals.md (everything so far) and the inbox (what is new this cycle)."""
        lines = ["# Proposals from the resource team", "",
                 "Private to the owner. Agents cannot act on these; you decide.", ""]
        for p in reversed(self.kb.resource_proposals()):
            lines += [f"## {p['id']}: {p['title']} (resource cycle {p['cycle']})", "",
                      p["proposal"], "", f"- Expected benefit: {p['expected_benefit']}",
                      f"- Costs and risks: {p['costs_and_risks']}",
                      f"- Proposed by {p['proposed_by']}; accepted by {p['reviewed_by']}: "
                      f"{p['review_note']}", ""]
        (self.data_dir / "proposals.md").write_text("\n".join(lines), encoding="utf-8")

        new = [p for p in log.get("proposals", []) if " accepted: " in p]
        items = ([f"- New proposal {p}" for p in new]
                 + [f"- Published on the website: {u}" for u in log.get("published_updates", [])])
        if not items:
            return
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        entry = (f"## Resource cycle {n} ({stamp})\n\n" + "\n".join(items)
                 + "\n\nRead the details in proposals.md. Reply by editing owner_notes.md.\n\n")
        (self.data_dir / "latest_inbox.md").write_text(entry, encoding="utf-8")
        with open(self.data_dir / "inbox.md", "a", encoding="utf-8") as inbox:
            inbox.write(entry)
