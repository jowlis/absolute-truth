# Changes to the protected core

Every change to `core/` is approved by the owner with `lock_core.py`, which adds an
entry below and updates the fingerprints in `core/manifest.json`. `run.py` refuses to
run while the core differs from what was last approved.

## Before the lock (Phase 1, approved by the owner in conversation)

- 2026-11-20: constitution v1, limits, budget guard, kill switch, scoring rules.
  Cycles 1-5 ran under constitution v1.
- 2026-11-22: constitution v2. Rule 4: rules, procedures, definitions, recommendations
  and proposals are always conceptual. New status "superseded". Cycles 6-11 ran under v2.
- 2026-11-22/23: limits added: retries_before_backup, max_claims_per_report.

## 2026-11-23 06:58 UTC: constitution v2

Reason: Phase 2: initial lock of the protected core (caps: $2/run, $5/day, $20/month; refuse to run on unapproved changes)

- __init__.py
- budget.py
- constitution.md
- integrity.py
- killswitch.py
- limits.toml
- recorder.py
- verdicts.py
