"""One cycle of the mission.

Cycle 1 (genesis): both models draft what "Absolute Truth" might mean and a first
roadmap; the planner merges the drafts; the other model reviews the merge.

Every later cycle:
  PLAN    the planner reviews roadmap + knowledge base and picks a task (or resource work)
  DO      the worker carries it out with tools
  REVIEW  the other model checks the work
  RECORD  core/verdicts.py decides what becomes a finding, and with what status

Every cycle ends with a structured log, a full transcript, and its token count and cost,
even if it was interrupted.
"""

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from agents.base import ProviderUnavailable, transcript_safe
from core import verdicts
from core.budget import BudgetExceeded, DailyQuotaReached
from core.killswitch import StopRequested
from loop import prompts, schemas
from loop.roles import roles_for
from tools.toolbox import Toolbox

# Exceptions that end the run (they are re-raised after the cycle log is saved).
HALTING = (StopRequested, BudgetExceeded, DailyQuotaReached, ProviderUnavailable)


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class CycleRunner:
    def __init__(self, *, config: dict, limits: dict, agents: dict, kb, roadmap, budget,
                 run_id: str, data_dir: Path, sandbox_ok: bool, say=None):
        self.config = config
        self.limits = limits
        self.agents = agents            # {"A": Agent, "B": Agent}
        self.kb = kb
        self.roadmap = roadmap
        self.budget = budget
        self.run_id = run_id
        self.data_dir = Path(data_dir)
        self.sandbox_ok = sandbox_ok
        self.current_cycle = 0
        self.say = say or (lambda message: None)   # progress messages (run.py prints them)
        self.failures: list[str] = []              # failed API attempts in this cycle
        self.last_author = ""                      # model that wrote the last accepted reply
        for agent in agents.values():
            agent.on_usage = self.record_usage
            agent.on_failure = self.record_failure
            agent.say = self.say

    def record_usage(self, agent, purpose: str, input_tokens: int, output_tokens: int,
                     cost: float) -> None:
        self.kb.record_api_call(run_id=self.run_id, cycle=self.current_cycle, model_key=agent.key,
                                model=agent.cfg["model"], purpose=purpose,
                                input_tokens=input_tokens, output_tokens=output_tokens,
                                cost_usd=cost)

    def record_failure(self, agent, purpose: str, error: Exception) -> None:
        self.failures.append(f"{agent.cfg['model']} ({purpose}): {type(error).__name__}: "
                             f"{str(error)[:150]}")

    # ---- running a cycle -----------------------------------------------------

    def run_cycle(self) -> dict:
        n = self.kb.next_cycle_number()
        self.current_cycle = n
        self.failures = []
        roles = roles_for(n, tuple(self.agents))
        log = {
            "cycle": n, "run_id": self.run_id, "started_at": now(), "ended_at": None,
            "track": "genesis" if not self.roadmap.exists() else "mission",
            "outcome": "unproductive",
            "roles": {r: self.agents[k].name for r, k in roles.items()},
            "task_id": None, "task": None, "allocation_reasoning": None,
            "what_was_done": "", "results": [], "rejected_claims": [], "status_changes": [],
            "flagged_for_review": [], "proposals": [], "disagreements": [],
            "roadmap_changes": [], "roadmap_errors": [], "appeal_check": None,
            "next_step": "", "problems": [], "usage": {},
        }
        transcript = []
        try:
            if log["track"] == "genesis":
                log["roles"] = {"planner": self.agents[roles["planner"]].name,
                                "worker": "both models (drafts)",
                                "reviewer": self.agents[roles["worker"]].name}
                self._genesis(n, roles, log, transcript)
            else:
                self._regular(n, roles, log, transcript)
        except HALTING as e:
            log["outcome"] = "interrupted"
            log["problems"].append(f"interrupted: {e}")
            raise
        except Exception as e:
            log["outcome"] = "failed"
            log["problems"].append(f"error: {type(e).__name__}: {e}")
            raise
        finally:
            self.roadmap.commit(n)
            log["ended_at"] = now()
            log["usage"] = self.kb.cycle_usage(n)
            log["usage"]["failed_attempts"] = len(self.failures)
            log["problems"] += [f"failed attempt: {f}" for f in self.failures]
            # A cycle stopped before it recorded anything keeps its files, but gets no
            # number in the path: the next attempt reuses the number, and the replies
            # already received (see _ask).
            recorded = (log["results"] or log["status_changes"] or log["proposals"]
                        or log["roadmap_changes"])
            log["counted"] = bool(recorded) or log["outcome"] not in ("interrupted", "failed")
            if log["outcome"] != "interrupted":
                self._cache_path().unlink(missing_ok=True)
            self._save(log, transcript)
        return log

    # ---- genesis -------------------------------------------------------------

    def _genesis(self, n: int, roles: dict, log: dict, transcript: list) -> None:
        merger = self.agents[roles["planner"]]
        reviewer = self.agents[roles["worker"]]

        drafts = {}
        for agent in (merger, reviewer):
            draft = self._ask(agent, self._other(agent), "drafter", "genesis_draft",
                              prompts.genesis_draft(n), None, transcript)
            if draft:
                drafts[self.last_author] = draft
            else:
                log["problems"].append(f"{agent.name} produced no valid draft")
        if not drafts:
            log["what_was_done"] = "Neither model produced a valid draft."
            return

        merged = self._ask(merger, reviewer, "planner", "genesis_merge",
                           prompts.genesis_merge(n, drafts), None, transcript)
        if not merged:
            log["what_was_done"] = "Drafts were made but could not be merged."
            return

        reason = "genesis: merged from both models' drafts"
        ops = list(merged["roadmap_ops"]) + [
            {"op": "set_foundation", "field": field, "value": merged[field], "reason": reason}
            for field in ("interpretation", "knowable", "unknowable", "method")]
        result = self.roadmap.apply(ops, n, merger.cfg["label"])
        log["roadmap_changes"], log["roadmap_errors"] = result["changes"], result["errors"]

        review = self._ask(reviewer, merger, "reviewer", "genesis_review",
                           prompts.genesis_review(n, drafts, merged, merger.name,
                                                  self.roadmap.render_md()),
                           self._review_check(len(merged["claims"]), 0), transcript)

        self._record_claims(n, None, merged["claims"], review, merger, reviewer, log)
        log["what_was_done"] = (
            f"{len(drafts)} independent draft(s) of what 'Absolute Truth' might mean and a first "
            f"roadmap; merged by {merger.name}; reviewed by {reviewer.name}.")
        log["task"] = "Genesis: interpret the mission and draft the first roadmap"
        log["disagreements"] += merged["disagreements"]
        if review:
            log["disagreements"] += review["disagreements"]
            log["disagreements"] += [f"roadmap concern: {c}" for c in review["roadmap_concerns"]]
            log["next_step"] = review["next_step"]
        log["outcome"] = "productive" if verdicts.is_productive(
            len(log["results"]), 0, 0, roadmap_created=self.roadmap.exists()) else "unproductive"

    # ---- regular cycles ------------------------------------------------------

    def _regular(self, n: int, roles: dict, log: dict, transcript: list) -> None:
        planner = self.agents[roles["planner"]]
        worker = self.agents[roles["worker"]]
        reviewer = self.agents[roles["reviewer"]]
        ctx = self.config["context"]
        findings_text = lambda: prompts.findings_summary(self.kb.findings(), ctx["max_findings_chars"])
        resource_cycles, total_cycles = self.kb.track_counts()
        resource_allowed = verdicts.resource_track_allowed(
            resource_cycles, total_cycles, self.limits["resource_share_ceiling"])
        resources_text = prompts.resource_status(
            {k: a.cfg for k, a in self.agents.items()}, self.budget, resource_cycles,
            total_cycles, self.limits["resource_share_ceiling"])
        worker_tools = Toolbox(worker, self.config, self.sandbox_ok)

        # PLAN
        plan = self._ask(
            planner, worker, "planner", "plan",
            prompts.plan(n, self.roadmap.render_md(), findings_text(),
                         prompts.recent_cycles(self.kb.cycle_logs(last=ctx["recent_cycle_logs"])),
                         resources_text, resource_allowed, worker.name, worker_tools.names()),
            self._plan_check(resource_allowed), transcript)
        if not plan:
            log["what_was_done"] = "The planner did not produce a valid plan."
            return
        log["allocation_reasoning"] = plan["allocation_reasoning"]
        log["track"] = plan["track"]
        result = self.roadmap.apply(plan["roadmap_ops"], n, planner.cfg["label"])
        log["roadmap_changes"] += result["changes"]
        log["roadmap_errors"] += result["errors"]

        if plan["track"] == "resource":
            self._resource_cycle(n, plan, planner, worker, reviewer, resources_text, log, transcript)
            return

        task_id = self.roadmap.resolve(plan.get("task_id") or "", result["keys"])
        task = self.roadmap.node(task_id) if task_id else None
        if task is None or task["kind"] != "task":
            log["what_was_done"] = f"The chosen task {plan.get('task_id')!r} could not be found."
            return
        log["task_id"], log["task"] = task_id, f"{task['title']}: {task['goal']}"
        if task["status"] == "proposed":
            r = self.roadmap.apply([{"op": "set_status", "id": task_id, "status": "active",
                                     "reason": f"chosen by the planner: {plan['why_this_task']}"}],
                                   n, planner.cfg["label"])
            log["roadmap_changes"] += r["changes"]

        # DO
        work_messages: list = []
        report = self._ask(worker, planner, "worker", "work",
                           prompts.work(n, task, plan["task_brief"], self.roadmap.render_md(),
                                        findings_text()),
                           None, transcript, toolbox=worker_tools, keep_messages=work_messages)
        if not report:
            log["what_was_done"] = "The worker did not produce a valid report."
            return
        log["what_was_done"] = report["summary"]

        # REVIEW
        review = self._ask(reviewer, worker, "reviewer", "review",
                           prompts.review(n, task, plan["task_brief"], worker.name, report,
                                          _tool_log(work_messages), findings_text()),
                           self._review_check(len(report["claims"]), len(report["finding_updates"])),
                           transcript, toolbox=Toolbox(reviewer, self.config, self.sandbox_ok))

        # RECORD
        self._record_claims(n, task_id, report["claims"], review, worker, reviewer, log)
        self._record_updates(n, report["finding_updates"], review, log)
        if review:
            log["appeal_check"] = review["appeal_check"]
            log["disagreements"] += review["disagreements"]
            if review["task_complete"] and report["task_complete"]:
                r = self.roadmap.apply([{"op": "set_status", "id": task_id, "status": "done",
                                         "reason": "worker and reviewer agree the goal was met"}],
                                       n, reviewer.cfg["label"])
                log["roadmap_changes"] += r["changes"]
            elif report["task_complete"]:
                log["disagreements"].append(
                    "worker considered the task complete; the reviewer did not")
        log["next_step"] = (review or {}).get("next_step") or report["suggested_next_step"]
        log["outcome"] = "productive" if verdicts.is_productive(
            len(log["results"]), len(log["status_changes"]), 0) else "unproductive"

    def _resource_cycle(self, n, plan, planner, worker, reviewer, resources_text, log,
                        transcript) -> None:
        log["task"] = f"Resource work: {plan['task_brief']}"
        report = self._ask(
            worker, planner, "worker", "resource_work",
            prompts.resource_work(n, plan["task_brief"], resources_text,
                                  prompts.proposals_summary(self.kb.resource_proposals()),
                                  prompts.findings_summary(self.kb.findings(),
                                                           self.config["context"]["max_findings_chars"])),
            None, transcript, toolbox=Toolbox(worker, self.config, self.sandbox_ok))
        if not report:
            log["what_was_done"] = "The worker did not produce valid resource proposals."
            return
        log["what_was_done"] = report["summary"]
        count = len(report["proposals"])
        review = self._ask(
            reviewer, worker, "reviewer", "resource_review",
            prompts.resource_review(n, plan["task_brief"], worker.name, report),
            lambda obj: _numbering_errors(obj["proposal_reviews"], "proposal", count),
            transcript)
        accepted = 0
        verdict_by_number = {r["proposal"]: r for r in (review or {}).get("proposal_reviews", [])}
        for i, p in enumerate(report["proposals"], start=1):
            r = verdict_by_number.get(i)
            if r and r["verdict"] == "accept":
                pid = self.kb.add_resource_proposal(
                    cycle=n, title=p["title"], proposal=p["proposal"],
                    expected_benefit=p["expected_benefit"], costs_and_risks=p["costs_and_risks"],
                    proposed_by=worker.name, reviewed_by=reviewer.name, review_note=r["reason"])
                log["proposals"].append(f"{pid} accepted: {p['title']}")
                accepted += 1
            else:
                why = r["reason"] if r else "not reviewed"
                log["proposals"].append(f"rejected: {p['title']} ({why})")
        self._write_proposals_md()
        if review:
            log["disagreements"] += review["disagreements"]
        log["next_step"] = (review or {}).get("next_step") or report["suggested_next_step"]
        log["outcome"] = "productive" if verdicts.is_productive(0, 0, accepted) else "unproductive"

    # ---- recording -----------------------------------------------------------

    def _record_claims(self, n, task_id, claims, review, author, reviewer, log) -> None:
        by_number = {r["claim"]: r for r in (review or {}).get("claim_reviews", [])}
        for i, claim in enumerate(claims, start=1):
            r = by_number.get(i)
            verdict = r["verdict"] if r else None
            status = verdicts.finding_status(claim["type"], verdict)
            if status is None:
                log["rejected_claims"].append(f"{claim['statement']} (rejected: {r['reason']})")
                continue
            builds_on = [str(b) for b in claim["builds_on"] if self.kb.exists(str(b))]
            dropped = [str(b) for b in claim["builds_on"] if not self.kb.exists(str(b))]
            if dropped:
                log["problems"].append(f"claim {i}: unknown builds_on ids ignored: {dropped}")
            fid = self.kb.add_finding(
                cycle=n, task_id=task_id, statement=claim["statement"], type=claim["type"],
                confidence=verdicts.final_confidence(claim["confidence"], (r or {}).get("confidence")),
                refutation_condition=claim["refutation_condition"], evidence=claim["evidence"],
                status=status, sources=[str(s) for s in claim["sources"]], builds_on=builds_on,
                created_by=author.name, reviewed_by=reviewer.name if r else None,
                review_note=r["reason"] if r else "not reviewed")
            log["results"].append(f"{fid} ({status}): {claim['statement']}")
            if verdict == "contested":
                log["disagreements"].append(f"{fid} contested: {r['reason']}")

    def _record_updates(self, n, updates, review, log) -> None:
        by_number = {r["update"]: r for r in (review or {}).get("update_reviews", [])}
        for i, u in enumerate(updates, start=1):
            r = by_number.get(i)
            fid = u["finding_id"]
            if not self.kb.exists(fid):
                log["problems"].append(f"update {i}: unknown finding {fid}")
                continue
            if not verdicts.status_update_allowed(u["new_status"], bool(r and r["agree"])):
                log["disagreements"].append(
                    f"proposed {fid} -> {u['new_status']} not applied: "
                    f"{r['reason'] if r else 'not reviewed'}")
                continue
            reason = f"{u['reason']} | reviewer: {r['reason']}"
            flagged = self.kb.set_status(fid, u["new_status"], reason, n)
            log["status_changes"].append(f"{fid} -> {u['new_status']}: {u['reason']}")
            log["flagged_for_review"] += flagged

    # ---- asking an agent for JSON --------------------------------------------

    def _ask(self, agent, other, role, stage, prompt, extra_check, transcript, toolbox=None,
             keep_messages=None) -> dict | None:
        """Ask for a JSON reply; if it is invalid, explain the problems and ask once more."""
        system = prompts.system_prompt(agent, other, role)

        # Reuse a valid reply received for exactly this request before an interruption.
        # (Only for turns without tools; those cannot be replayed from one reply.)
        # The key leaves out the system prompt, which names the current (maybe backup) model.
        key = hashlib.sha256(f"{stage}|{agent.key}|{role}|{prompt}".encode("utf-8")).hexdigest()
        cache = self._load_cache() if toolbox is None else {}
        if key in cache:
            obj, parse_error = schemas.parse_reply(cache[key]["text"])
            if not parse_error and not schemas.check(obj, schemas.SPECS[stage]) and (
                    not extra_check or not extra_check(obj)):
                self.say(f"{stage}: reusing {agent.cfg['label']}'s reply from an interrupted "
                         f"attempt (run {cache[key]['run_id']})")
                self.last_author = cache[key]["model"]
                transcript.append({"stage": stage, "role": role, "model": cache[key]["model"],
                                   "system": system, "reused_from_run": cache[key]["run_id"],
                                   "messages": [{"role": "user", "content": prompt},
                                                {"role": "assistant", "content": cache[key]["text"]}],
                                   "valid": True, "errors": []})
                return obj

        self.say(f"{stage}: {agent.cfg['label']} is working ({role})")
        messages = keep_messages if keep_messages is not None else []
        messages.append({"role": "user", "content": prompt})
        obj, errors = None, ["no reply"]
        try:
            for _attempt in range(2):
                text = agent.converse(system, messages, toolbox,
                                      self.limits["max_tool_steps_per_turn"], purpose=stage)
                obj, parse_error = schemas.parse_reply(text)
                errors = [parse_error] if parse_error else schemas.check(obj, schemas.SPECS[stage])
                if not errors and extra_check:
                    errors = extra_check(obj)
                if not errors:
                    if toolbox is None:
                        self._store_in_cache(key, text, agent)
                    self.last_author = agent.name
                    return obj
                self.say(f"{stage}: reply from {agent.cfg['label']} was not usable; asking again")
                messages.append({"role": "user", "content":
                                 "Your reply could not be used:\n- " + "\n- ".join(errors[:10]) +
                                 "\nReply again with the corrected JSON object in a ```json block."})
            return None
        finally:
            transcript.append({"stage": stage, "role": role, "model": agent.name,
                               "system": system, "messages": transcript_safe(messages),
                               "valid": not errors, "errors": errors})

    def _plan_check(self, resource_allowed: bool):
        def check(plan: dict) -> list[str]:
            if plan["track"] == "resource":
                return [] if resource_allowed else [
                    "the resource track is not allowed now (owner's ceiling); choose a mission task"]
            ref = plan.get("task_id") or ""
            node = self.roadmap.node(ref)
            if node is not None:
                if node["kind"] != "task":
                    return [f"{ref} is a milestone; task_id must be a task"]
                if node["status"] in ("done", "abandoned"):
                    return [f"{ref} is {node['status']}; choose a proposed or active task, or add one"]
                return []
            added = [op.get("key") for op in plan["roadmap_ops"]
                     if isinstance(op, dict) and op.get("op") == "add" and op.get("kind") == "task"]
            if ref and ref in added:
                return []
            return [f"task_id {ref!r} is neither an existing task nor the key of a task you add"]
        return check

    @staticmethod
    def _review_check(claims: int, updates: int):
        def check(review: dict) -> list[str]:
            return (_numbering_errors(review["claim_reviews"], "claim", claims)
                    + _numbering_errors(review.get("update_reviews", []), "update", updates))
        return check

    def _other(self, agent):
        return next(a for a in self.agents.values() if a is not agent)

    # ---- saving ----------------------------------------------------------------

    def _save(self, log: dict, transcript: list) -> None:
        name = f"cycle_{log['cycle']:04d}" + ("" if log["counted"] else "_not_counted")
        cycle_dir = self.data_dir / "runs" / self.run_id / name
        cycle_dir.mkdir(parents=True, exist_ok=True)
        (cycle_dir / "transcript.json").write_text(
            json.dumps(transcript, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
        (cycle_dir / "log.json").write_text(json.dumps(log, indent=2, ensure_ascii=False), encoding="utf-8")
        md = render_log_md(log)
        (cycle_dir / "log.md").write_text(md, encoding="utf-8")
        if not log["counted"]:
            return
        with open(self.data_dir / "path.md", "a", encoding="utf-8") as path_file:   # the whole path, cycle by cycle
            path_file.write(md + "\n---\n\n")
        self.kb.record_cycle(log, self.run_id)

    def _cache_path(self) -> Path:
        return self.data_dir / "reply_cache.json"

    def _load_cache(self) -> dict:
        """Replies from an interrupted attempt at the current cycle number, if any."""
        path = self._cache_path()
        if not path.exists():
            return {}
        data = json.loads(path.read_text(encoding="utf-8"))
        return data["replies"] if data.get("cycle") == self.current_cycle else {}

    def _store_in_cache(self, key: str, text: str, agent) -> None:
        replies = self._load_cache()
        replies[key] = {"text": text, "model": agent.name, "run_id": self.run_id}
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._cache_path().write_text(json.dumps(
            {"cycle": self.current_cycle, "replies": replies}, indent=2, ensure_ascii=False),
            encoding="utf-8")

    def _write_proposals_md(self) -> None:
        lines = ["# Resource proposals for the owner", "",
                 "Ideas from the agents for getting resources that would advance the mission.",
                 "Agents cannot act on these; the owner decides.", ""]
        for p in self.kb.resource_proposals():
            lines += [f"## {p['id']}: {p['title']} (cycle {p['cycle']})", "", p["proposal"], "",
                      f"- Expected benefit: {p['expected_benefit']}",
                      f"- Costs and risks: {p['costs_and_risks']}",
                      f"- Proposed by {p['proposed_by']}; accepted by {p['reviewed_by']}: "
                      f"{p['review_note']}", ""]
        (self.data_dir / "resource_proposals.md").write_text("\n".join(lines), encoding="utf-8")


# ---- helpers -------------------------------------------------------------------

def _numbering_errors(items: list, label: str, expected: int) -> list[str]:
    numbers = [it[label] for it in items]
    wanted = list(range(1, expected + 1))
    if sorted(numbers) != wanted:
        return [f"review each {label} exactly once: expected {label} numbers {wanted}, got {numbers}"]
    return []


def _tool_log(messages: list) -> str:
    """The worker's tool calls and results, for the reviewer."""
    calls = {}
    lines = []
    for m in messages:
        for c in m.get("tool_calls") or []:
            calls[c.id] = c
        if m["role"] == "tool":
            c = calls.get(m["tool_call_id"])
            args = json.dumps(c.args, ensure_ascii=False) if c else "?"
            lines.append(f"## {m['name']} {args}\n{m['content'][:3000]}")
    return "\n\n".join(lines)


def render_log_md(log: dict) -> str:
    def bullets(items):
        return "\n".join(f"- {x}" for x in items) if items else "- none"
    u = log["usage"]
    return f"""# Cycle {log['cycle']}: {log['track']} ({log['outcome']})

- Planner: {log['roles'].get('planner')}
- Worker: {log['roles'].get('worker')}
- Reviewer: {log['roles'].get('reviewer')}
- Time: {log['started_at']} to {log['ended_at']}
- Models that replied: {', '.join(u.get('models', [])) or 'none'}
- Usage: {u.get('api_calls', 0)} API calls ({u.get('failed_attempts', 0)} failed attempts), {u.get('input_tokens', 0)} input tokens, {u.get('output_tokens', 0)} output tokens, ${u.get('cost_usd', 0):.4f}

**Task:** {log.get('task') or '-'}

**Why this allocation:** {log.get('allocation_reasoning') or '-'}

**What was done:** {log.get('what_was_done') or '-'}

**Results (new findings):**
{bullets(log['results'])}

**Rejected claims:**
{bullets(log['rejected_claims'])}

**Status changes:**
{bullets(log['status_changes'])}

**Flagged for review (depend on refuted findings):**
{bullets(log['flagged_for_review'])}

**Resource proposals:**
{bullets(log['proposals'])}

**Disagreements:**
{bullets(log['disagreements'])}

**Roadmap changes:**
{bullets(log['roadmap_changes'] + [f"(skipped) {e}" for e in log['roadmap_errors']])}

**Appeal check:** {log.get('appeal_check') or '-'}

**Next step:** {log.get('next_step') or '-'}

**Problems:**
{bullets(log['problems'])}
"""
