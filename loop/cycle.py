"""One cycle of the mission.

Cycle 1 (genesis): both models draft what "Absolute Truth" might mean and a first
roadmap; the planner merges the drafts; the other model reviews the merge.

Every later cycle:
  PLAN    the planner reviews roadmap + knowledge base and picks a task
  DO      the worker carries it out with tools
  REVIEW  the other model checks the work
  RECORD  core/verdicts.py decides what becomes a finding, and with what status

Every cycle ends with a structured log, a full transcript, and its token count and cost,
even if it was interrupted.
"""

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from agents.base import ProviderUnavailable, transcript_safe
from core import integrity, recorder, verdicts
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
        self.claim_ids: dict = {}                  # claim number -> finding id, current report
        self._parties = None                       # (author, reviewer) of the current report
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
        for agent in self.agents.values():   # a switch to a backup lasts one cycle at most
            agent.cfg["model"] = agent.models[0]
        roles = roles_for(n, tuple(self.agents))
        log = {
            "cycle": n, "run_id": self.run_id, "started_at": now(), "ended_at": None,
            "track": self._initial_track(),
            "outcome": "unproductive",
            "roles": {r: self.agents[k].name for r, k in roles.items()},
            "task_id": None, "task": None, "allocation_reasoning": None,
            "what_was_done": "", "results": [], "rejected_claims": [], "status_changes": [],
            "flagged_for_review": [], "proposals": [], "disagreements": [],
            "roadmap_changes": [], "roadmap_errors": [], "appeal_check": None,
            "next_step": "", "problems": [], "usage": {},
            "rules": integrity.rules_in_force(),
        }
        transcript = []
        try:
            self._body(n, roles, log, transcript)
        except HALTING as e:
            log["outcome"] = "interrupted"
            log["problems"].append(f"interrupted: {e}")
            raise
        except Exception as e:
            log["outcome"] = "failed"
            log["problems"].append(f"error: {type(e).__name__}: {e}")
            raise
        finally:
            if self.roadmap is not None:
                self.roadmap.commit(n)
            log["ended_at"] = now()
            log["usage"] = self.kb.cycle_usage(n)
            log["usage"]["failed_attempts"] = len(self.failures)
            log["problems"] += [f"failed attempt: {f}" for f in self.failures]
            # A cycle stopped before it recorded anything keeps its files, but gets no
            # number in the path: the next attempt reuses the number, and the replies
            # already received (see _ask).
            recorded = (log["results"] or log["status_changes"] or log["proposals"]
                        or log["roadmap_changes"] or log.get("published_updates"))
            log["counted"] = bool(recorded) or log["outcome"] not in ("interrupted", "failed")
            if log["outcome"] != "interrupted":
                self._cache_path().unlink(missing_ok=True)
            self._save(log, transcript)
        return log

    def _system_prompt(self, agent, other, role: str) -> str:
        return prompts.system_prompt(agent, other, role)

    def _initial_track(self) -> str:
        return "genesis" if not self.roadmap.exists() else "mission"

    def _body(self, n: int, roles: dict, log: dict, transcript: list) -> None:
        if log["track"] == "genesis":
            log["roles"] = {"planner": self.agents[roles["planner"]].name,
                            "worker": "both models (drafts)",
                            "reviewer": self.agents[roles["worker"]].name}
            self._genesis(n, roles, log, transcript)
        else:
            self._regular(n, roles, log, transcript)

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
        worker_tools = Toolbox(worker, self.config, self.sandbox_ok)

        # PLAN
        plan = self._ask(
            planner, worker, "planner", "plan",
            prompts.plan(n, self.roadmap.render_md(), findings_text(),
                         prompts.recent_cycles(self.kb.cycle_logs(last=ctx["recent_cycle_logs"])),
                         worker.name, worker_tools.names(), self.limits["max_claims_per_report"]),
            self._plan_check(), transcript)
        if not plan:
            log["what_was_done"] = "The planner did not produce a valid plan."
            return
        result = self.roadmap.apply(plan["roadmap_ops"], n, planner.cfg["label"])
        log["roadmap_changes"] += result["changes"]
        log["roadmap_errors"] += result["errors"]

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
        max_claims = self.limits["max_claims_per_report"]
        report = self._ask(worker, planner, "worker", "work",
                           prompts.work(n, task, plan["task_brief"], self.roadmap.render_md(),
                                        findings_text(), max_claims),
                           lambda r: [] if len(r["claims"]) <= max_claims else [
                               f"too many claims ({len(r['claims'])}): record at most {max_claims}, "
                               "the most solid ones, and say in the summary what remains"],
                           transcript, toolbox=worker_tools, keep_messages=work_messages)
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

    # ---- recording -----------------------------------------------------------

    def _record_claims(self, n, task_id, claims, review, author, reviewer, log) -> None:
        """Hand the claims and the verdicts to the protected recorder (core/recorder.py)."""
        self._parties = (_party(author), _party(reviewer))
        out = recorder.record_claims(
            self.kb, cycle=n, task_id=task_id, claims=claims, review=review,
            author=self._parties[0], reviewer=self._parties[1],
            max_claims=self.limits["max_claims_per_report"])
        self.claim_ids = out.pop("claim_ids")
        _merge(log, out)

    def _record_updates(self, n, updates, review, log) -> None:
        """Hand proposed status changes to the protected recorder."""
        out = recorder.record_updates(
            self.kb, cycle=n, updates=updates, review=review, author=self._parties[0],
            reviewer=self._parties[1], claim_ids=self.claim_ids)
        _merge(log, out)

    # ---- asking an agent for JSON --------------------------------------------

    def _ask(self, agent, other, role, stage, prompt, extra_check, transcript, toolbox=None,
             keep_messages=None) -> dict | None:
        """Ask for a JSON reply; if it is invalid, explain the problems and ask once more."""
        system = self._system_prompt(agent, other, role)

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
                if parse_error and agent.last_truncated:
                    parse_error = ("your reply was cut off at the length limit before the JSON "
                                   "was complete; reply again with a shorter answer (fewer or "
                                   "shorter claims, less text before the JSON)")
                errors = [parse_error] if parse_error else schemas.check(obj, schemas.SPECS[stage])
                if not errors and extra_check:
                    errors = extra_check(obj)
                if not errors:
                    if toolbox is None:
                        self._store_in_cache(key, text, agent)
                    self.last_author = agent.name
                    return obj
                self.say(f"{stage}: reply from {agent.cfg['label']} was not usable "
                         f"({errors[0][:90]}); asking again")
                messages.append({"role": "user", "content":
                                 "Your reply could not be used:\n- " + "\n- ".join(errors[:10]) +
                                 "\nReply again with the corrected JSON object in a ```json block."})
            return None
        finally:
            transcript.append({"stage": stage, "role": role, "model": agent.name,
                               "system": system, "messages": transcript_safe(messages),
                               "valid": not errors, "errors": errors})

    def _plan_check(self):
        def check(plan: dict) -> list[str]:
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


# ---- helpers -------------------------------------------------------------------

def _party(agent) -> recorder.Party:
    return recorder.Party(name=agent.name, lab=agent.cfg["lab"])


def _merge(log: dict, out: dict) -> None:
    """Add the recorder's lists (results, problems, ...) to the cycle log."""
    for key, items in out.items():
        log.setdefault(key, [])
        log[key] += items


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
- Rules: constitution v{log.get('rules', {}).get('constitution_version', '?')}, core fingerprint {log.get('rules', {}).get('core_fingerprint', 'not recorded')}
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

**Published updates:**
{bullets(log.get('published_updates', []))}

**Disagreements:**
{bullets(log['disagreements'])}

**Roadmap changes:**
{bullets(log['roadmap_changes'] + [f"(skipped) {e}" for e in log['roadmap_errors']])}

**Appeal check:** {log.get('appeal_check') or '-'}

**Next step:** {log.get('next_step') or '-'}

**Problems:**
{bullets(log['problems'])}
"""
