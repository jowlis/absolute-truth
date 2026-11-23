"""Tamper-evidence for the protected core and for the history of cycles.

1. Locked core: core/manifest.json holds a fingerprint (SHA-256) of every file in core/.
   run.py refuses to run if a file changed, appeared or disappeared without the owner's
   approval. The owner approves a change with:  py lock_core.py "reason"
   which records it in core/CHANGELOG.md and writes a new manifest.

2. History chain: every recorded cycle stores the hash of its log combined with the hash
   of the cycle before it. Changing any past cycle breaks every hash after it.

This file imports nothing outside the standard library.
"""

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

CORE_DIR = Path(__file__).resolve().parent
MANIFEST_NAME = "manifest.json"
GENESIS_HASH = "0" * 64           # the "previous hash" of the very first cycle


# ---- locked core -------------------------------------------------------------

def core_files(core_dir: Path = CORE_DIR) -> list[Path]:
    """Every file in core/ except the manifest itself and Python's cache files."""
    return sorted(p for p in Path(core_dir).rglob("*")
                  if p.is_file() and p.name != MANIFEST_NAME
                  and "__pycache__" not in p.parts and p.suffix != ".pyc")


def file_hash(path: Path) -> str:
    # Line endings are normalised, so Windows (CRLF) and Mac/Linux (LF) copies match.
    data = Path(path).read_bytes().replace(b"\r\n", b"\n")
    return hashlib.sha256(data).hexdigest()


def current_hashes(core_dir: Path = CORE_DIR) -> dict:
    return {p.relative_to(core_dir).as_posix(): file_hash(p) for p in core_files(core_dir)}


def fingerprint(hashes: dict) -> str:
    """One short fingerprint for the whole core."""
    text = json.dumps(hashes, sort_keys=True)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def read_manifest(core_dir: Path = CORE_DIR) -> dict | None:
    path = Path(core_dir) / MANIFEST_NAME
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def check_core(core_dir: Path = CORE_DIR) -> list[str]:
    """Problems with the core (empty list = the core is exactly as the owner approved it)."""
    manifest = read_manifest(core_dir)
    if manifest is None:
        return ["core/manifest.json is missing: the core has never been locked"]
    approved, now = manifest["files"], current_hashes(core_dir)
    problems = [f"changed without approval: core/{name}"
                for name in sorted(approved) if name in now and now[name] != approved[name]]
    problems += [f"missing: core/{name}" for name in sorted(approved) if name not in now]
    problems += [f"new file without approval: core/{name}" for name in sorted(now)
                 if name not in approved]
    return problems


def constitution_version(core_dir: Path = CORE_DIR) -> int:
    text = (Path(core_dir) / "constitution.md").read_text(encoding="utf-8")
    match = re.search(r"^Version:\s*(\d+)\s*$", text, re.MULTILINE)
    return int(match.group(1)) if match else 0


def rules_in_force(core_dir: Path = CORE_DIR) -> dict:
    """What every cycle log records about the rules it ran under."""
    return {"core_fingerprint": fingerprint(current_hashes(core_dir)),
            "constitution_version": constitution_version(core_dir)}


def lock(reason: str, core_dir: Path = CORE_DIR) -> str:
    """Approve the core as it is now: add a CHANGELOG entry, then write the manifest.

    Returns the new fingerprint. Only lock_core.py (the owner's command) calls this.
    """
    core_dir = Path(core_dir)
    manifest = read_manifest(core_dir)
    before = manifest["files"] if manifest else {}
    now = current_hashes(core_dir)
    changed = sorted(n for n in set(before) | set(now)
                     if before.get(n) != now.get(n) and n != "CHANGELOG.md")
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    changelog = core_dir / "CHANGELOG.md"
    entry = (f"\n## {stamp}: constitution v{constitution_version(core_dir)}\n\n"
             f"Reason: {reason}\n\n"
             + "".join(f"- {name}\n" for name in changed or ["(no file changes)"]))
    if not changelog.exists():
        changelog.write_text("# Changes to the protected core\n\nEvery change to `core/` is "
                             "approved by the owner with `lock_core.py`.\n", encoding="utf-8")
    with open(changelog, "a", encoding="utf-8") as f:
        f.write(entry)

    hashes = current_hashes(core_dir)                 # includes the updated CHANGELOG
    (core_dir / MANIFEST_NAME).write_text(json.dumps({
        "locked_at": stamp, "reason": reason,
        "constitution_version": constitution_version(core_dir),
        "fingerprint": fingerprint(hashes), "files": hashes}, indent=2) + "\n",
        encoding="utf-8")
    return fingerprint(hashes)


# ---- history chain -----------------------------------------------------------

def chain_hash(previous_hash: str, log: dict) -> str:
    """Hash of a cycle log, chained to the hash of the cycle before it."""
    text = json.dumps(log, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256((previous_hash + text).encode("utf-8")).hexdigest()
