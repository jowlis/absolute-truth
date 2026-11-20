"""Read-only views of the roadmap, findings and path. This file never changes any data.

  python show.py roadmap              the current roadmap
  python show.py findings             all findings
  python show.py finding F0003        one finding with its history and dependencies
  python show.py path                 every cycle, one line each
  python show.py cycle 4              the full log of one cycle
  python show.py versions             how the roadmap changed, version by version
  python show.py proposals            resource proposals for the owner
  python show.py costs                tokens and cost per cycle

Add --mock to read the dry-run data (data-mock/) instead of data/.
"""

import argparse
import json
import sys
from pathlib import Path

from knowledge.db import KnowledgeBase

ROOT = Path(__file__).resolve().parent


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("view", choices=["roadmap", "findings", "finding", "path", "cycle",
                                         "versions", "proposals", "costs"])
    parser.add_argument("id", nargs="?", help="finding id or cycle number")
    parser.add_argument("--mock", action="store_true", help="read data-mock/ instead of data/")
    parser.add_argument("--data-dir")
    args = parser.parse_args()
    data = Path(args.data_dir) if args.data_dir else ROOT / ("data-mock" if args.mock else "data")

    if args.view == "roadmap":
        path = data / "roadmap.md"
        print(path.read_text(encoding="utf-8") if path.exists() else "No roadmap yet. Run: python run.py")
        return 0
    if args.view == "versions":
        for f in sorted((data / "roadmap_versions").glob("v*.json")):
            v = json.loads(f.read_text(encoding="utf-8"))["changes_in_this_version"]
            print(f"{f.stem} (cycle {v['cycle']}):")
            for c in v["changes"]:
                print(f"   {c}")
        return 0

    if not (data / "knowledge.db").exists():
        print("No knowledge base yet. Run: python run.py")
        return 1
    kb = KnowledgeBase(data / "knowledge.db", read_only=True)

    if args.view == "findings":
        for f in kb.findings():
            flag = "  NEEDS REVIEW" if f["needs_review"] else ""
            deps = f"  <- {', '.join(f['builds_on'])}" if f["builds_on"] else ""
            print(f"{f['id']} [{f['status']:<10} {f['type']:<10} conf {f['confidence']:.2f}]"
                  f"{flag} {f['statement']}{deps}")
    elif args.view == "finding":
        f = kb.finding(args.id or "")
        if not f:
            print(f"No finding {args.id}")
            return 1
        for key in ("id", "statement", "type", "status", "confidence", "refutation_condition",
                    "evidence", "sources", "builds_on", "created_by", "reviewed_by", "review_note"):
            print(f"{key:>21}: {f[key]}")
        print(f"{'needed by':>21}: {kb.dependents(f['id'])}")
        print(f"{'needs review':>21}: {bool(f['needs_review'])}")
        print("              history:")
        for e in kb.events(f["id"]):
            print(f"   cycle {e['cycle']}: {e['event']}. {e['reason'] or ''}")
    elif args.view == "path":
        for log in kb.cycle_logs():
            print(f"cycle {log['cycle']:>3}  {log['track']:<8} {log['outcome']:<12} "
                  f"{(log.get('task') or '-')[:70]}")
            if log.get("next_step"):
                print(f"           next: {log['next_step'][:90]}")
    elif args.view == "cycle":
        logs = [l for l in kb.cycle_logs() if str(l["cycle"]) == str(args.id)]
        if not logs:
            print(f"No cycle {args.id}")
            return 1
        from loop.cycle import render_log_md
        print(render_log_md(logs[0]))
    elif args.view == "proposals":
        path = data / "resource_proposals.md"
        print(path.read_text(encoding="utf-8") if path.exists() else "No resource proposals yet.")
    elif args.view == "costs":
        print(f"{'cycle':>5} {'calls':>5} {'input':>9} {'output':>9} {'cost $':>9}")
        for log in kb.cycle_logs():
            u = log["usage"]
            print(f"{log['cycle']:>5} {u['api_calls']:>5} {u['input_tokens']:>9} "
                  f"{u['output_tokens']:>9} {u['cost_usd']:>9.4f}")
        t = kb.total_usage()
        print(f"{'total':>5} {t['api_calls']:>5} {t['input_tokens']:>9} {t['output_tokens']:>9} "
              f"{t['cost_usd']:>9.4f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
