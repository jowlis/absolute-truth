"""The owner's command for approving changes to the protected core (core/).

  py lock_core.py "why the change was made"

It shows what changed, asks for confirmation, records the change in core/CHANGELOG.md
and writes new fingerprints to core/manifest.json. Until then, run.py refuses to run.
Commit core/ (including manifest.json and CHANGELOG.md) afterwards, so the change is
visible in the project's public history.
"""

import sys

from core import integrity


def main() -> int:
    if len(sys.argv) != 2 or not sys.argv[1].strip():
        print('Usage: py lock_core.py "why the change was made"')
        return 1
    reason = sys.argv[1].strip()

    problems = integrity.check_core()
    manifest = integrity.read_manifest()
    if not problems:
        print("The core is unchanged since it was last approved. Nothing to lock.")
        return 0

    print("Changes to the protected core:")
    for p in problems:
        print("  -", p)

    old_version = manifest["constitution_version"] if manifest else 0
    new_version = integrity.constitution_version()
    if manifest and "changed without approval: core/constitution.md" in problems \
            and new_version <= old_version:
        print(f"\nThe constitution changed, but its 'Version:' line is still {new_version}. "
              f"Raise it to {old_version + 1} first, so every cycle log shows which "
              "version it ran under.")
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
