"""Check the history chain of the Absolute Truth project. Uses only standard Python.

  python verify_chain.py cycles.json

Every cycle's record is hashed together with the hash of the cycle before it, so changing
any past cycle changes its hash and breaks every hash after it.
"""

import hashlib
import json
import sys

GENESIS_HASH = "0" * 64   # the "previous hash" of the first cycle


def chain_hash(previous_hash: str, log: dict) -> str:
    text = json.dumps(log, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256((previous_hash + text).encode("utf-8")).hexdigest()


def main(path: str) -> int:
    with open(path, encoding="utf-8") as f:
        cycles = json.load(f)
    previous, intact = GENESIS_HASH, True
    for cycle in cycles:
        if cycle["prev_hash"] != previous:
            print(f"Cycle {cycle['number']}: chain broken (its 'previous hash' does not match)")
            intact = False
        if chain_hash(cycle["prev_hash"], cycle["log"]) != cycle["log_hash"]:
            print(f"Cycle {cycle['number']}: its record was changed after it was hashed")
            intact = False
        previous = cycle["log_hash"]
    print(("OK" if intact else "PROBLEMS") + f": {len(cycles)} cycles checked; latest hash {previous}")
    return 0 if intact else 1


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python verify_chain.py cycles.json")
        sys.exit(2)
    sys.exit(main(sys.argv[1]))
