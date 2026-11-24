"""The only code that writes findings, status changes, resource proposals and public updates.

Protected (CLAUDE.md principle 3). The loop hands over what the worker reported and what
the reviewer decided; this file applies the owner's rules, whatever the loop does:

- a claim becomes a finding only through a review by a model from a DIFFERENT lab;
  otherwise it is kept as "proposed" (unreviewed);
- the status comes from core/verdicts.py; review can lower confidence, never raise it;
- claims with an invalid type or confidence are not recorded;
- at most `max_claims` claims are recorded per report;
- a status change needs the reviewer's agreement; "superseded" needs a real replacement.

This file imports nothing outside core/ (the knowledge base is passed in).
"""

import re
from dataclasses import dataclass

from core import verdicts

SAME_REPORT = re.compile(r"(?:claim\s*|C)(\d+)", re.IGNORECASE)   # "claim 2" or "C2"


@dataclass
class Party:
    """A model taking part: its full name (for the record) and its lab."""
    name: str
    lab: str


def _independent(author: Party, reviewer: Party) -> bool:
    return author.lab.strip().lower() != reviewer.lab.strip().lower()


def record_claims(kb, *, cycle: int, task_id, claims: list, review: dict | None,
                  author: Party, reviewer: Party, max_claims: int) -> dict:
    """Turn reviewed claims into findings. Returns what happened, for the cycle log."""
    out = {"results": [], "rejected_claims": [], "disagreements": [], "problems": [],
           "claim_ids": {}}
    if review is not None and not _independent(author, reviewer):
        out["problems"].append(f"reviewer {reviewer.name} is from the same lab as the author; "
                               "the review is ignored and claims stay 'proposed'")
        review = None
    if len(claims) > max_claims:
        out["problems"].append(f"{len(claims)} claims; only the first {max_claims} are recorded")
        claims = claims[:max_claims]

    by_number = {r.get("claim"): r for r in (review or {}).get("claim_reviews", [])}
    for i, claim in enumerate(claims, start=1):
        r = by_number.get(i)
        verdict = r.get("verdict") if r else None
        if claim.get("type") not in verdicts.FINDING_TYPES:
            out["problems"].append(f"claim {i}: invalid type {claim.get('type')!r}; not recorded")
            continue
        if verdict is not None and verdict not in verdicts.CLAIM_VERDICTS:
            out["problems"].append(f"claim {i}: invalid verdict {verdict!r}; kept unreviewed")
            r, verdict = None, None
        try:
            confidence = verdicts.final_confidence(
                claim["confidence"], (r or {}).get("confidence") if r else None)
        except (TypeError, ValueError, KeyError):
            out["problems"].append(f"claim {i}: invalid confidence; not recorded")
            continue

        status = verdicts.finding_status(claim["type"], verdict)
        if status is None:
            out["rejected_claims"].append(f"{claim.get('statement')} (rejected: {r.get('reason')})")
            continue

        builds_on, dropped = [], []
        for ref in claim.get("builds_on") or []:
            ref = str(ref).strip()
            same = SAME_REPORT.fullmatch(ref)
            if same and int(same.group(1)) in out["claim_ids"]:
                builds_on.append(out["claim_ids"][int(same.group(1))])
            elif kb.exists(ref):
                builds_on.append(ref)
            else:
                dropped.append(ref)
        if dropped:
            out["problems"].append(
                f"claim {i}: builds_on ignored (unknown, rejected or later claim): {dropped}")

        fid = kb.add_finding(
            cycle=cycle, task_id=task_id, statement=str(claim.get("statement", "")),
            type=claim["type"], confidence=confidence,
            refutation_condition=str(claim.get("refutation_condition", "")),
            evidence=str(claim.get("evidence", "")), status=status,
            sources=[str(s) for s in claim.get("sources") or []], builds_on=builds_on,
            created_by=author.name, reviewed_by=reviewer.name if r else None,
            review_note=str(r.get("reason")) if r else "not reviewed")
        out["claim_ids"][i] = fid
        out["results"].append(f"{fid} ({status}): {claim.get('statement')}")
        if verdict == "contested":
            out["disagreements"].append(f"{fid} contested: {r.get('reason')}")
    return out


def record_updates(kb, *, cycle: int, updates: list, review: dict | None, author: Party,
                   reviewer: Party, claim_ids: dict) -> dict:
    """Apply agreed status changes to existing findings. Returns what happened."""
    out = {"status_changes": [], "flagged_for_review": [], "disagreements": [], "problems": []}
    if review is not None and not _independent(author, reviewer):
        review = None
    by_number = {r.get("update"): r for r in (review or {}).get("update_reviews", [])}
    for i, u in enumerate(updates, start=1):
        r = by_number.get(i)
        fid, new_status = str(u.get("finding_id", "")), u.get("new_status")
        if not kb.exists(fid):
            out["problems"].append(f"update {i}: unknown finding {fid}")
            continue
        if not verdicts.status_update_allowed(new_status, bool(r and r.get("agree") is True)):
            out["disagreements"].append(f"proposed {fid} -> {new_status} not applied: "
                                        f"{r.get('reason') if r else 'not reviewed'}")
            continue
        replacement = None
        if new_status == "superseded":
            ref = str(u.get("superseded_by") or "").strip()
            same = SAME_REPORT.fullmatch(ref)
            if same:
                replacement = claim_ids.get(int(same.group(1)))
            elif kb.exists(ref) and ref != fid:
                replacement = ref
            if replacement is None:
                out["problems"].append(f"update {i}: {fid} -> superseded not applied: "
                                       f"replacement {ref!r} is not a recorded finding")
                continue
        reason = f"{u.get('reason')} | reviewer: {r.get('reason')}"
        out["flagged_for_review"] += kb.set_status(fid, new_status, reason, cycle,
                                                   superseded_by=replacement)
        change = f"{fid} -> {new_status}" + (f" (replaced by {replacement})" if replacement else "")
        out["status_changes"].append(f"{change}: {u.get('reason')}")
    return out


def record_proposals(kb, *, cycle: int, proposals: list, review: dict | None, author: Party,
                     reviewer: Party) -> dict:
    """Keep the resource proposals the reviewer (from another lab) accepted."""
    out = {"proposals": [], "accepted": 0, "problems": []}
    if review is not None and not _independent(author, reviewer):
        out["problems"].append("reviewer is from the same lab as the author; nothing accepted")
        review = None
    by_number = {r.get("proposal"): r for r in (review or {}).get("proposal_reviews", [])}
    for i, p in enumerate(proposals, start=1):
        r = by_number.get(i)
        if r and r.get("verdict") == "accept":
            pid = kb.add_resource_proposal(
                cycle=cycle, title=str(p.get("title")), proposal=str(p.get("proposal")),
                expected_benefit=str(p.get("expected_benefit")),
                costs_and_risks=str(p.get("costs_and_risks")), proposed_by=author.name,
                reviewed_by=reviewer.name, review_note=str(r.get("reason")))
            out["proposals"].append(f"{pid} accepted: {p.get('title')}")
            out["accepted"] += 1
        else:
            out["proposals"].append(
                f"rejected: {p.get('title')} ({r.get('reason') if r else 'not reviewed'})")
    return out


def record_public_update(kb, *, update: dict, review: dict | None, check: dict | None,
                         author: Party, reviewer: Party, checker: Party) -> dict:
    """Publish a resource-team update only if all of these hold (constitution rule 11):
    - the resource-team reviewer (another lab) accepted it,
    - a truth-team model from another lab than the author checked it against the findings
      and approved it,
    - it cites at least one recorded finding (unknown citations are dropped).
    `kb` is the PUBLIC knowledge base; nothing else in it is touched.
    """
    out = {"published": [], "problems": []}
    title = str(update.get("title", "")).strip()
    if not (review and review.get("verdict") == "accept"):
        out["problems"].append(f"update '{title}' not published: the reviewer did not accept it")
        return out
    if not _independent(author, reviewer):
        out["problems"].append(f"update '{title}' not published: reviewer from the author's lab")
        return out
    if not _independent(author, checker):
        out["problems"].append(f"update '{title}' not published: checker from the author's lab")
        return out
    if not (check and check.get("verdict") == "approve"):
        reason = check.get("reason") if check else "no accuracy check"
        out["problems"].append(f"update '{title}' not published: accuracy check said no ({reason})")
        return out
    cites = [str(c).strip() for c in update.get("cites") or [] if kb.exists(str(c).strip())]
    if not cites:
        out["problems"].append(f"update '{title}' not published: it cites no recorded finding")
        return out
    uid = kb.add_public_update(title=title, body=str(update.get("body", "")), cites=cites,
                               written_by=author.name, reviewed_by=reviewer.name,
                               checked_by=checker.name, check_note=str(check.get("reason", "")))
    out["published"].append(f"{uid}: {title}")
    return out
