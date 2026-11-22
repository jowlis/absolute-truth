"""Scoring rules: how review verdicts turn into finding statuses and confidence.

Protected (CLAUDE.md principle 3): agents can never change these rules.
This file imports nothing from agent-facing or presentation code.
"""

FINDING_TYPES = ("verifiable", "conceptual")
FINDING_STATUSES = ("proposed", "contested", "supported", "refuted", "conceptual", "superseded")
CLAIM_VERDICTS = ("accept", "accept_lower_confidence", "contested", "reject")
PROPOSAL_VERDICTS = ("accept", "reject")


def finding_status(claim_type: str, verdict: str | None) -> str | None:
    """Status for a new finding, or None if it must not be recorded.

    - no review happened  -> "proposed" (kept, but clearly unreviewed)
    - reject              -> not recorded (stays only in the cycle log)
    - contested           -> "contested"
    - accept / lowered    -> "supported" for verifiable claims,
                             "conceptual" for conceptual ones
    """
    if verdict is None:
        return "proposed"
    if verdict == "reject":
        return None
    if verdict == "contested":
        return "contested"
    if verdict in ("accept", "accept_lower_confidence"):
        return "conceptual" if claim_type == "conceptual" else "supported"
    raise ValueError(f"Unknown verdict: {verdict!r}")


def final_confidence(worker_confidence: float, reviewer_confidence: float | None) -> float:
    """Review may lower confidence, never raise it. Result is clamped to [0, 1]."""
    worker = min(max(float(worker_confidence), 0.0), 1.0)
    if reviewer_confidence is None:
        return worker
    reviewer = min(max(float(reviewer_confidence), 0.0), 1.0)
    return min(worker, reviewer)


def status_update_allowed(new_status: str, reviewer_agrees: bool) -> bool:
    """A change to an existing finding needs the reviewer's agreement and a valid status.

    "proposed" is excluded: it only describes work that was never reviewed.
    """
    return reviewer_agrees and new_status in FINDING_STATUSES and new_status != "proposed"


def resource_track_allowed(resource_cycles: int, total_cycles: int, ceiling: float) -> bool:
    """Would one more resource cycle keep the resource share at or under the ceiling?"""
    return (resource_cycles + 1) / (total_cycles + 1) <= ceiling + 1e-9


def is_productive(new_findings: int, status_changes: int, accepted_proposals: int,
                  roadmap_created: bool = False) -> bool:
    """A cycle is productive if it produced something concrete.

    Roadmap edits alone do not count, except creating the first roadmap (genesis).
    """
    return roadmap_created or (new_findings + status_changes + accepted_proposals) > 0
