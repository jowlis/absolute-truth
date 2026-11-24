"""The owner's command for approving changes to the protected core (core/).

  py lock_core.py "why the change was made"

It shows what changed, asks for confirmation, records the change in core/CHANGELOG.md
and writes new fingerprints to core/manifest.json. Until then, run.py refuses to run.
Commit core/ (including manifest.json and CHANGELOG.md) afterwards, so the change is
visible in the project's public history.
"""

import sys

from core import integrity


def version_problem(problems: list) -> str | None:
    """If the constitution changed, its 'Version:' line must have been raised."""
    manifest = integrity.read_manifest()
    if not manifest or "changed without approval: core/constitution.md" not in problems:
        return None
    old_version, new_version = manifest["constitution_version"], integrity.constitution_version()
    if new_version <= old_version:
        return (f"The constitution changed, but its 'Version:' line is still {new_version}. "
                f"Raise it to {old_version + 1} first, so every cycle log shows which "
                "version it ran under.")
    return None


def main() -> int:
    if len(sys.argv) != 2 or not sys.argv[1].strip():
        print('Usage: py lock_core.py "why the change was made"')
        return 1
    reason = sys.argv[1].strip()

    problems = integrity.check_core()
    if not problems:
        print("The core is unchanged since it was last approved. Nothing to lock.")
        return 0

    print("Changes to the protected core:")
    for p in problems:
        print("  -", p)

    problem = version_problem(problems)
    if problem:
        print("\n" + problem)
        return 1

    answer = input(f'\nApprove these changes with the reason "{reason}"? Type yes: ')
    if answer.strip().lower() != "yes":
        print("Not approved. Nothing was changed.")
        return 1
    print("Locked. New core fingerprint:", integrity.lock(reason))
    print("Now commit the core/ folder (GitHub Desktop: Commit, then Push).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
