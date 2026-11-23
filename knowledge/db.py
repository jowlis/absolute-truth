"""Knowledge base in SQLite: findings, their dependencies, cycles, API calls and resource proposals.

Tables
  findings            one row per finding (id like F0007)
  finding_deps        finding_id builds on depends_on
  finding_events      every status change, with the reason (history is never deleted)
  cycles              one row per cycle, with the structured log as JSON
  api_calls           tokens and cost of every API call
  resource_proposals  ideas for getting resources (separate from findings!)
"""

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from core import integrity

SCHEMA = """
CREATE TABLE IF NOT EXISTS findings (
    id TEXT PRIMARY KEY,
    cycle INTEGER NOT NULL,
    task_id TEXT,
    statement TEXT NOT NULL,
    type TEXT NOT NULL CHECK (type IN ('verifiable', 'conceptual')),
    confidence REAL NOT NULL CHECK (confidence BETWEEN 0 AND 1),
    refutation_condition TEXT,
    evidence TEXT,
    status TEXT NOT NULL CHECK (status IN
        ('proposed', 'contested', 'supported', 'refuted', 'conceptual', 'superseded')),
    superseded_by TEXT,
    needs_review INTEGER NOT NULL DEFAULT 0,
    sources TEXT NOT NULL DEFAULT '[]',
    created_by TEXT NOT NULL,
    reviewed_by TEXT,
    review_note TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS finding_deps (
    finding_id TEXT NOT NULL REFERENCES findings(id),
    depends_on TEXT NOT NULL REFERENCES findings(id),
    PRIMARY KEY (finding_id, depends_on)
);
CREATE TABLE IF NOT EXISTS finding_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    finding_id TEXT NOT NULL REFERENCES findings(id),
    cycle INTEGER NOT NULL,
    event TEXT NOT NULL,
    reason TEXT,
    at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS cycles (
    number INTEGER PRIMARY KEY,
    run_id TEXT NOT NULL,
    track TEXT NOT NULL,
    outcome TEXT NOT NULL,
    planner TEXT, worker TEXT, reviewer TEXT,
    task_id TEXT,
    log_json TEXT NOT NULL,
    prev_hash TEXT,
    log_hash TEXT,
    input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    cost_usd REAL NOT NULL DEFAULT 0,
    started_at TEXT NOT NULL,
    ended_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS api_calls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    cycle INTEGER NOT NULL,
    model_key TEXT NOT NULL,
    model TEXT NOT NULL,
    purpose TEXT NOT NULL,
    input_tokens INTEGER NOT NULL,
    output_tokens INTEGER NOT NULL,
    cost_usd REAL NOT NULL,
    at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS resource_proposals (
    id TEXT PRIMARY KEY,
    cycle INTEGER NOT NULL,
    title TEXT NOT NULL,
    proposal TEXT NOT NULL,
    expected_benefit TEXT,
    costs_and_risks TEXT,
    proposed_by TEXT NOT NULL,
    reviewed_by TEXT,
    review_note TEXT,
    at TEXT NOT NULL
);
"""

# Rules the database enforces itself, whatever code talks to it (Phase 2, locked core).
# History is append-only; a recorded finding's content can't be edited; confidence never rises.
TRIGGERS = {
    "findings_no_delete":
        "BEFORE DELETE ON findings BEGIN SELECT RAISE(ABORT, 'findings cannot be deleted'); END",
    "findings_content_fixed":
        "BEFORE UPDATE OF id, cycle, task_id, statement, type, refutation_condition, evidence,"
        " sources, created_by, reviewed_by, review_note, created_at ON findings"
        " BEGIN SELECT RAISE(ABORT, 'a recorded finding cannot be edited'); END",
    "findings_confidence_never_rises":
        "BEFORE UPDATE OF confidence ON findings WHEN NEW.confidence > OLD.confidence"
        " BEGIN SELECT RAISE(ABORT, 'confidence can never rise'); END",
    "deps_fixed":
        "BEFORE UPDATE ON finding_deps BEGIN SELECT RAISE(ABORT, 'dependencies are fixed'); END",
    "deps_no_delete":
        "BEFORE DELETE ON finding_deps BEGIN SELECT RAISE(ABORT, 'dependencies are fixed'); END",
    "events_no_update":
        "BEFORE UPDATE ON finding_events BEGIN SELECT RAISE(ABORT, 'history is append-only'); END",
    "events_no_delete":
        "BEFORE DELETE ON finding_events BEGIN SELECT RAISE(ABORT, 'history is append-only'); END",
    "cycles_no_delete":
        "BEFORE DELETE ON cycles BEGIN SELECT RAISE(ABORT, 'cycles cannot be deleted'); END",
    "cycles_fixed_once_chained":
        "BEFORE UPDATE ON cycles WHEN OLD.log_hash IS NOT NULL"
        " BEGIN SELECT RAISE(ABORT, 'a recorded cycle cannot be edited'); END",
    "api_calls_no_update":
        "BEFORE UPDATE ON api_calls BEGIN SELECT RAISE(ABORT, 'cost records are fixed'); END",
    "api_calls_no_delete":
        "BEFORE DELETE ON api_calls BEGIN SELECT RAISE(ABORT, 'cost records are fixed'); END",
    "proposals_no_update":
        "BEFORE UPDATE ON resource_proposals BEGIN SELECT RAISE(ABORT, 'proposals are fixed'); END",
    "proposals_no_delete":
        "BEFORE DELETE ON resource_proposals BEGIN SELECT RAISE(ABORT, 'proposals are fixed'); END",
}


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class KnowledgeBase:
    def __init__(self, path: Path, read_only: bool = False):
        self.path = Path(path)
        if read_only:
            self.conn = sqlite3.connect(f"file:{self.path}?mode=ro", uri=True)
        else:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.conn = sqlite3.connect(self.path)
            self.conn.executescript(SCHEMA)
            self._upgrade()
            for name, body in TRIGGERS.items():
                self.conn.execute(f"CREATE TRIGGER IF NOT EXISTS {name} {body}")
            self.conn.commit()
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")

    def _upgrade(self) -> None:
        """Bring a knowledge base made by an older version up to date. Keeps all data."""
        self._upgrade_findings()
        self._upgrade_cycles()

    def _upgrade_cycles(self) -> None:
        """Add the history chain (Phase 2) and chain the cycles recorded before it."""
        columns = [r[1] for r in self.conn.execute("PRAGMA table_info(cycles)")]
        with self.conn:
            for column in ("prev_hash", "log_hash"):
                if column not in columns:
                    self.conn.execute(f"ALTER TABLE cycles ADD COLUMN {column} TEXT")
            unchained = self.conn.execute(
                "SELECT number FROM cycles WHERE log_hash IS NULL ORDER BY number").fetchall()
            for (number,) in unchained:
                prev = self._last_hash(before=number)
                log_json = self.conn.execute(
                    "SELECT log_json FROM cycles WHERE number = ?", (number,)).fetchone()[0]
                self.conn.execute(
                    "UPDATE cycles SET prev_hash = ?, log_hash = ? WHERE number = ?",
                    (prev, integrity.chain_hash(prev, json.loads(log_json)), number))

    def _upgrade_findings(self) -> None:
        """Add the "superseded" status and the superseded_by column.

        SQLite cannot change a table's rules in place, so the findings table is rebuilt
        (SQLite's documented way).
        """
        sql = self.conn.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'findings'").fetchone()[0]
        if "superseded" in sql:
            return
        new_table = SCHEMA[SCHEMA.index("CREATE TABLE IF NOT EXISTS findings"):
                           SCHEMA.index("CREATE TABLE IF NOT EXISTS finding_deps")]
        new_table = new_table.replace("IF NOT EXISTS findings", "findings_upgraded")
        old_columns = [r[1] for r in self.conn.execute("PRAGMA table_info(findings)")]
        columns = ", ".join(old_columns)
        self.conn.execute("PRAGMA foreign_keys = OFF")
        with self.conn:
            self.conn.execute(new_table)
            self.conn.execute(f"INSERT INTO findings_upgraded ({columns}) SELECT {columns} FROM findings")
            self.conn.execute("DROP TABLE findings")
            self.conn.execute("ALTER TABLE findings_upgraded RENAME TO findings")
        self.conn.execute("PRAGMA foreign_keys = ON")

    # ---- findings ------------------------------------------------------------

    def add_finding(self, *, cycle: int, task_id: str | None, statement: str, type: str,
                    confidence: float, refutation_condition: str, evidence: str,
                    status: str, sources: list, builds_on: list, created_by: str,
                    reviewed_by: str | None, review_note: str | None) -> str:
        count = self.conn.execute("SELECT COUNT(*) FROM findings").fetchone()[0]
        fid = f"F{count + 1:04d}"
        stamp = now()
        with self.conn:
            self.conn.execute(
                "INSERT INTO findings (id, cycle, task_id, statement, type, confidence,"
                " refutation_condition, evidence, status, sources, created_by, reviewed_by,"
                " review_note, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (fid, cycle, task_id, statement, type, confidence, refutation_condition,
                 evidence, status, json.dumps(sources), created_by, reviewed_by, review_note,
                 stamp, stamp))
            for dep in builds_on:
                self.conn.execute("INSERT OR IGNORE INTO finding_deps VALUES (?, ?)", (fid, dep))
            self.conn.execute(
                "INSERT INTO finding_events (finding_id, cycle, event, reason, at)"
                " VALUES (?,?,?,?,?)", (fid, cycle, f"created as {status}", review_note, stamp))
        # Building on refuted or flagged work makes the new finding doubtful too.
        shaky = [d for d in builds_on if (f := self.finding(d))
                 and (f["status"] in ("refuted", "superseded") or f["needs_review"])]
        if shaky:
            with self.conn:
                self.conn.execute("UPDATE findings SET needs_review = 1 WHERE id = ?", (fid,))
                self.conn.execute(
                    "INSERT INTO finding_events (finding_id, cycle, event, reason, at)"
                    " VALUES (?,?,?,?,?)",
                    (fid, cycle, "flagged for review",
                     f"builds on refuted, superseded or flagged finding(s) {', '.join(shaky)}",
                     now()))
        return fid

    def finding(self, fid: str) -> dict | None:
        row = self.conn.execute("SELECT * FROM findings WHERE id = ?", (fid,)).fetchone()
        return self._finding_dict(row) if row else None

    def findings(self) -> list[dict]:
        rows = self.conn.execute("SELECT * FROM findings ORDER BY id").fetchall()
        return [self._finding_dict(r) for r in rows]

    def exists(self, fid: str) -> bool:
        return self.conn.execute("SELECT 1 FROM findings WHERE id = ?", (fid,)).fetchone() is not None

    def builds_on(self, fid: str) -> list[str]:
        rows = self.conn.execute(
            "SELECT depends_on FROM finding_deps WHERE finding_id = ? ORDER BY depends_on", (fid,))
        return [r[0] for r in rows]

    def dependents(self, fid: str) -> list[str]:
        rows = self.conn.execute(
            "SELECT finding_id FROM finding_deps WHERE depends_on = ? ORDER BY finding_id", (fid,))
        return [r[0] for r in rows]

    def events(self, fid: str) -> list[dict]:
        rows = self.conn.execute(
            "SELECT cycle, event, reason, at FROM finding_events WHERE finding_id = ? ORDER BY id",
            (fid,))
        return [dict(r) for r in rows]

    def set_status(self, fid: str, new_status: str, reason: str, cycle: int,
                   superseded_by: str | None = None) -> list[str]:
        """Change a finding's status. Returns the ids flagged for review as a result.

        Any status change after review clears the finding's own needs_review flag.
        If the new status is "refuted" (shown false) or "superseded" (replaced by a more
        precise or corrected finding, `superseded_by`), every finding that depends on it,
        directly or through a chain, is flagged needs_review.
        """
        old = self.finding(fid)
        if old is None:
            raise KeyError(fid)
        if new_status == "superseded" and not (superseded_by and self.exists(superseded_by)):
            raise ValueError("a superseded finding needs the id of the finding that replaces it")
        event = f"status {old['status']} -> {new_status}"
        if superseded_by:
            event += f" (replaced by {superseded_by})"
        with self.conn:
            self.conn.execute(
                "UPDATE findings SET status = ?, superseded_by = ?, needs_review = 0,"
                " updated_at = ? WHERE id = ?",
                (new_status, superseded_by if new_status == "superseded" else None, now(), fid))
            self.conn.execute(
                "INSERT INTO finding_events (finding_id, cycle, event, reason, at) VALUES (?,?,?,?,?)",
                (fid, cycle, event, reason, now()))
        if new_status == "refuted":
            return self._flag_dependents(fid, cycle, f"refuted finding {fid}")
        if new_status == "superseded":
            return self._flag_dependents(
                fid, cycle, f"superseded finding {fid} (check whether to rely on {superseded_by})")
        return []

    def _flag_dependents(self, changed_id: str, cycle: int, what: str) -> list[str]:
        flagged, queue = [], list(self.dependents(changed_id))
        while queue:
            fid = queue.pop(0)
            if fid in flagged:
                continue
            flagged.append(fid)
            with self.conn:
                self.conn.execute(
                    "UPDATE findings SET needs_review = 1, updated_at = ? WHERE id = ?", (now(), fid))
                self.conn.execute(
                    "INSERT INTO finding_events (finding_id, cycle, event, reason, at)"
                    " VALUES (?,?,?,?,?)",
                    (fid, cycle, "flagged for review",
                     f"depends (directly or indirectly) on {what}", now()))
            queue.extend(self.dependents(fid))
        return flagged

    def _finding_dict(self, row) -> dict:
        d = dict(row)
        d["sources"] = json.loads(d["sources"])
        d["builds_on"] = self.builds_on(d["id"])
        return d

    # ---- cycles and API calls ------------------------------------------------

    def next_cycle_number(self) -> int:
        return (self.conn.execute("SELECT MAX(number) FROM cycles").fetchone()[0] or 0) + 1

    def record_cycle(self, log: dict, run_id: str) -> str:
        """Add a cycle to the history chain. Returns its hash."""
        prev = self._last_hash()
        log_hash = integrity.chain_hash(prev, log)
        with self.conn:
            self.conn.execute(
                "INSERT INTO cycles (number, run_id, track, outcome, planner, worker,"
                " reviewer, task_id, log_json, prev_hash, log_hash, input_tokens, output_tokens,"
                " cost_usd, started_at, ended_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (log["cycle"], run_id, log["track"], log["outcome"], log["roles"].get("planner"),
                 log["roles"].get("worker"), log["roles"].get("reviewer"), log.get("task_id"),
                 json.dumps(log, ensure_ascii=False), prev, log_hash,
                 log["usage"]["input_tokens"], log["usage"]["output_tokens"],
                 log["usage"]["cost_usd"], log["started_at"], log["ended_at"]))
        return log_hash

    def _last_hash(self, before: int | None = None) -> str:
        query = "SELECT log_hash FROM cycles WHERE log_hash IS NOT NULL"
        args: tuple = ()
        if before is not None:
            query += " AND number < ?"
            args = (before,)
        row = self.conn.execute(query + " ORDER BY number DESC LIMIT 1", args).fetchone()
        return row[0] if row else integrity.GENESIS_HASH

    def verify(self) -> list[str]:
        """Check the database's own rules and the history chain. Empty list = all intact."""
        problems = []
        present = {r[0] for r in self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'trigger'")}
        problems += [f"database rule missing: {name}" for name in TRIGGERS if name not in present]

        prev = integrity.GENESIS_HASH
        for number, log_json, prev_hash, log_hash in self.conn.execute(
                "SELECT number, log_json, prev_hash, log_hash FROM cycles ORDER BY number"):
            if prev_hash != prev:
                problems.append(f"history chain broken before cycle {number}")
            if log_hash != integrity.chain_hash(prev_hash or "", json.loads(log_json)):
                problems.append(f"cycle {number} was changed after it was recorded")
            prev = log_hash

        for fid, status, superseded_by in self.conn.execute(
                "SELECT id, status, superseded_by FROM findings"):
            if status == "superseded" and not (superseded_by and self.exists(superseded_by)):
                problems.append(f"{fid} is superseded but names no recorded replacement")
            if not self.events(fid):
                problems.append(f"{fid} has no history")
        return problems

    def cycle_logs(self, last: int | None = None) -> list[dict]:
        rows = self.conn.execute("SELECT log_json FROM cycles ORDER BY number").fetchall()
        logs = [json.loads(r[0]) for r in rows]
        return logs[-last:] if last else logs

    def track_counts(self) -> tuple[int, int]:
        """(resource cycles, all cycles) recorded so far."""
        total = self.conn.execute("SELECT COUNT(*) FROM cycles").fetchone()[0]
        resource = self.conn.execute(
            "SELECT COUNT(*) FROM cycles WHERE track = 'resource'").fetchone()[0]
        return resource, total

    def record_api_call(self, *, run_id: str, cycle: int, model_key: str, model: str,
                        purpose: str, input_tokens: int, output_tokens: int, cost_usd: float) -> None:
        with self.conn:
            self.conn.execute(
                "INSERT INTO api_calls (run_id, cycle, model_key, model, purpose, input_tokens,"
                " output_tokens, cost_usd, at) VALUES (?,?,?,?,?,?,?,?,?)",
                (run_id, cycle, model_key, model, purpose, input_tokens, output_tokens,
                 cost_usd, now()))

    def cycle_usage(self, cycle: int) -> dict:
        row = self.conn.execute(
            "SELECT COUNT(*), COALESCE(SUM(input_tokens),0), COALESCE(SUM(output_tokens),0),"
            " COALESCE(SUM(cost_usd),0) FROM api_calls WHERE cycle = ?", (cycle,)).fetchone()
        models = [r[0] for r in self.conn.execute(
            "SELECT DISTINCT model FROM api_calls WHERE cycle = ? ORDER BY model", (cycle,))]
        return {"api_calls": row[0], "input_tokens": row[1], "output_tokens": row[2],
                "cost_usd": round(row[3], 6), "models": models}

    def total_usage(self) -> dict:
        row = self.conn.execute(
            "SELECT COUNT(*), COALESCE(SUM(input_tokens),0), COALESCE(SUM(output_tokens),0),"
            " COALESCE(SUM(cost_usd),0) FROM api_calls").fetchone()
        return {"api_calls": row[0], "input_tokens": row[1], "output_tokens": row[2],
                "cost_usd": round(row[3], 6)}

    # ---- resource proposals --------------------------------------------------

    def add_resource_proposal(self, *, cycle: int, title: str, proposal: str,
                              expected_benefit: str, costs_and_risks: str, proposed_by: str,
                              reviewed_by: str, review_note: str) -> str:
        count = self.conn.execute("SELECT COUNT(*) FROM resource_proposals").fetchone()[0]
        pid = f"R{count + 1:04d}"
        with self.conn:
            self.conn.execute(
                "INSERT INTO resource_proposals VALUES (?,?,?,?,?,?,?,?,?,?)",
                (pid, cycle, title, proposal, expected_benefit, costs_and_risks, proposed_by,
                 reviewed_by, review_note, now()))
        return pid

    def resource_proposals(self) -> list[dict]:
        rows = self.conn.execute("SELECT * FROM resource_proposals ORDER BY id").fetchall()
        return [dict(r) for r in rows]
