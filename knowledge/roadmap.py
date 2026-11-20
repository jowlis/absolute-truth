"""The roadmap: a tree with the mission at the root and milestones and tasks beneath it.

Agents never edit the roadmap directly. They send a list of operations; this file
checks each one and applies the valid ones. Every change needs a reason, and every
version is saved, so the evolution of the plan stays visible.

Changes made during a cycle are collected and saved as one new version at the end
of the cycle (`commit`).

Files (in the data folder):
  roadmap.json                  the current version
  roadmap.md                    readable rendering of the current version
  roadmap_versions/v0001.json   every version ever saved, with the changes that produced it

Operations agents may send:
  {"op": "add", "kind": "milestone" | "task", "parent": "ROOT" | <id> | <key>,
   "key": <optional temporary label>, "title": ..., "goal": ..., "why": ...}
  {"op": "set_status", "id": <id>, "status": <status>, "reason": ...}
  {"op": "edit", "id": <id>, "title"/"goal"/"why": <new text>, "reason": ...}
  {"op": "set_foundation", "field": "interpretation" | "knowable" | "unknowable" | "method",
   "value": <text or list of texts>, "reason": ...}
"""

import copy
import json
from pathlib import Path

STATUSES = ("proposed", "active", "done", "abandoned")
KINDS = ("milestone", "task")
FOUNDATION_FIELDS = ("interpretation", "knowable", "unknowable", "method")
STATUS_MARK = {"proposed": "○", "active": "▶", "done": "✓", "abandoned": "✗"}


def empty_roadmap() -> dict:
    return {
        "version": 0,
        "cycle": 0,
        "mission": "Absolute Truth",
        "foundations": {"interpretation": "", "knowable": [], "unknowable": [], "method": ""},
        "nodes": [],
    }


class Roadmap:
    def __init__(self, data_dir: Path):
        self.dir = Path(data_dir)
        self.json_path = self.dir / "roadmap.json"
        self.md_path = self.dir / "roadmap.md"
        self.versions_dir = self.dir / "roadmap_versions"
        self.data = json.loads(self.json_path.read_text(encoding="utf-8")) if self.json_path.exists() else empty_roadmap()
        self.pending: list[str] = []   # changes not yet saved as a version

    # ---- reading -------------------------------------------------------------

    def exists(self) -> bool:
        return bool(self.data["nodes"])

    def node(self, node_id: str) -> dict | None:
        return next((n for n in self.data["nodes"] if n["id"] == node_id), None)

    def children(self, parent_id: str) -> list[dict]:
        return [n for n in self.data["nodes"] if n["parent"] == parent_id]

    # ---- changing ------------------------------------------------------------

    def apply(self, ops: list, cycle: int, author: str) -> dict:
        """Apply operations. Returns {"changes": [...], "errors": [...], "keys": {key: id}}.

        Invalid operations are skipped and reported; valid ones are applied in memory.
        Call `commit` to save them as a new version.
        """
        changes, errors, keys = [], [], {}
        for i, op in enumerate(ops if isinstance(ops, list) else [], start=1):
            try:
                changes.append(self._apply_one(op, cycle, author, keys))
            except (ValueError, KeyError, TypeError) as e:
                errors.append(f"op {i} skipped: {e}")
        self.pending += [f"{author}: {c}" for c in changes]
        return {"changes": changes, "errors": errors, "keys": keys}

    def commit(self, cycle: int) -> None:
        """Save all pending changes as one new version (does nothing if nothing changed)."""
        if self.pending:
            self._save(cycle, self.pending)
            self.pending = []

    def resolve(self, ref: str, keys: dict) -> str | None:
        """Turn an id or a temporary key from the same batch into a real id."""
        if not ref:
            return None
        ref = keys.get(ref, ref)
        return ref if self.node(ref) else None

    def _apply_one(self, op: dict, cycle: int, author: str, keys: dict) -> str:
        if not isinstance(op, dict):
            raise TypeError("operation must be an object")
        kind = op.get("op")
        reason = _text(op.get("reason"))

        if kind == "add":
            node_kind = op.get("kind")
            if node_kind not in KINDS:
                raise ValueError(f"kind must be one of {KINDS}")
            parent = op.get("parent") or "ROOT"
            parent = keys.get(parent, parent)
            if parent != "ROOT":
                parent_node = self.node(parent)
                if parent_node is None:
                    raise ValueError(f"unknown parent {parent!r}")
                if parent_node["kind"] == "task":
                    raise ValueError("tasks cannot have children")
            title, goal, why = _text(op.get("title")), _text(op.get("goal")), _text(op.get("why"))
            if not (title and goal and why):
                raise ValueError("add needs title, goal and why")
            prefix = "M" if node_kind == "milestone" else "T"
            number = 1 + sum(1 for n in self.data["nodes"] if n["kind"] == node_kind)
            node_id = f"{prefix}{number}"
            self.data["nodes"].append({
                "id": node_id, "kind": node_kind, "parent": parent, "title": title,
                "goal": goal, "why": why, "status": "proposed",
                "history": [{"cycle": cycle, "by": author, "change": "created",
                             "reason": reason or why}],
            })
            if op.get("key"):
                keys[str(op["key"])] = node_id
            return f"added {node_kind} {node_id} under {parent}: {title}"

        if kind == "set_status":
            node = self._require_node(op.get("id"), keys)
            status = op.get("status")
            if status not in STATUSES:
                raise ValueError(f"status must be one of {STATUSES}")
            if not reason:
                raise ValueError("set_status needs a reason")
            if status == node["status"]:
                raise ValueError(f"{node['id']} is already {status}")
            old = node["status"]
            node["status"] = status
            node["history"].append({"cycle": cycle, "by": author,
                                    "change": f"{old} -> {status}", "reason": reason})
            return f"{node['id']} {old} -> {status}: {reason}"

        if kind == "edit":
            node = self._require_node(op.get("id"), keys)
            if not reason:
                raise ValueError("edit needs a reason")
            edited = [f for f in ("title", "goal", "why") if _text(op.get(f))]
            if not edited:
                raise ValueError("edit needs at least one of title, goal, why")
            for f in edited:
                node[f] = _text(op[f])
            node["history"].append({"cycle": cycle, "by": author,
                                    "change": "edited " + ", ".join(edited), "reason": reason})
            return f"{node['id']} edited ({', '.join(edited)}): {reason}"

        if kind == "set_foundation":
            field = op.get("field")
            if field not in FOUNDATION_FIELDS:
                raise ValueError(f"field must be one of {FOUNDATION_FIELDS}")
            if not reason:
                raise ValueError("set_foundation needs a reason")
            value = op.get("value")
            if field in ("knowable", "unknowable"):
                if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
                    raise ValueError(f"{field} must be a list of texts")
            elif not _text(value):
                raise ValueError(f"{field} must be a non-empty text")
            self.data["foundations"][field] = value
            return f"foundation '{field}' set: {reason}"

        raise ValueError(f"unknown op {kind!r}")

    def _require_node(self, ref, keys: dict) -> dict:
        node_id = self.resolve(str(ref or ""), keys)
        if node_id is None:
            raise ValueError(f"unknown id {ref!r}")
        return self.node(node_id)

    def _save(self, cycle: int, changes: list[str]) -> None:
        self.data["version"] += 1
        self.data["cycle"] = cycle
        self.dir.mkdir(parents=True, exist_ok=True)
        self.versions_dir.mkdir(exist_ok=True)
        snapshot = copy.deepcopy(self.data)
        snapshot["changes_in_this_version"] = {"cycle": cycle, "changes": changes}
        (self.versions_dir / f"v{self.data['version']:04d}.json").write_text(
            json.dumps(snapshot, indent=2, ensure_ascii=False), encoding="utf-8")
        self.json_path.write_text(json.dumps(self.data, indent=2, ensure_ascii=False), encoding="utf-8")
        self.md_path.write_text(self.render_md(), encoding="utf-8")

    # ---- rendering -----------------------------------------------------------

    def render_md(self) -> str:
        d = self.data
        f = d["foundations"]
        lines = [f"# Roadmap (version {d['version']}, cycle {d['cycle']})", "",
                 f"**Mission:** {d['mission']}", "",
                 "## Working interpretation", "", f["interpretation"] or "_not yet set_", ""]
        if f["method"]:
            lines += ["## Method", "", f["method"], ""]
        lines += ["## What may be knowable", ""] + [f"- {x}" for x in f["knowable"]] + [""]
        lines += ["## What may not be knowable", ""] + [f"- {x}" for x in f["unknowable"]] + [""]
        lines += ["## Plan", "",
                  "Legend: ○ proposed  ▶ active  ✓ done  ✗ abandoned", ""]
        lines += self._render_children("ROOT", 0) or ["_no milestones yet_"]
        return "\n".join(lines) + "\n"

    def _render_children(self, parent: str, depth: int) -> list[str]:
        lines = []
        for n in self.children(parent):
            pad = "  " * depth
            mark = STATUS_MARK[n["status"]]
            lines.append(f"{pad}- {mark} **[{n['id']}] {n['title']}** ({n['status']})")
            lines.append(f"{pad}  - Goal: {n['goal']}")
            lines.append(f"{pad}  - Why it matters: {n['why']}")
            last = n["history"][-1]
            if last["change"] != "created":
                lines.append(f"{pad}  - Last change (cycle {last['cycle']}, {last['by']}): "
                             f"{last['change']}. {last['reason']}")
            lines += self._render_children(n["id"], depth + 1)
        return lines


def _text(value) -> str:
    return value.strip() if isinstance(value, str) else ""
