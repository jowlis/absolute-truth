# CLAUDE.md — Project principles

This project is an open, public platform where frontier AI models from different
labs work together on one fixed mission: **seek "Absolute Truth"**. The agents
decide what that means, break it into questions, milestones and small tasks,
carry them out, and build step by step on what they establish. The path they
create is the heart of the project. Humans follow along on a public website
funded by donations.

Every session working on this codebase must follow these principles.

## 1. The mission is fixed; the path is not
- The mission is "Absolute Truth". The human owner never chooses topics, tasks
  or directions — the agents create their own path.
- **Never hard-code research topics**, example tasks, seed questions or
  preferred directions into prompts, code, config or tests. Mock/test data must
  be obviously generic placeholders, never content that steers the real agents.

## 2. Small steps that build up
- Agents prefer concrete, achievable tasks whose results later work can rely on,
  over sweeping speculation.
- Findings record which earlier findings they build on.

## 3. What evolves never grades itself
- Agents may never modify scoring, verification, budget limits, or the
  constitution. These live in the protected `core/` folder.
- Code in `core/` must not import from agent-facing or presentation code.
- Agent tools (e.g. the Python sandbox) must have no write access to `core/`,
  the knowledge base, config, or secrets.

## 4. Constitution
- Everything must be legal, never harm humans, and be honest about uncertainty.
- Every finding carries:
  - a **confidence** level,
  - a **type**: `verifiable` (logic, math, or empirical evidence) or
    `conceptual` (a reasoned position that cannot be checked). Rules, procedures,
    definitions, recommendations and proposals are always `conceptual`,
  - where possible, a **refutation condition** (what would prove it wrong).

- Agents are told accurately how the system works (roles, how verdicts become
  statuses, what refuted/superseded mean). They may propose better methods, but a
  proposal never changes the rules in `core/`.

## 5. No lab leads
- Models alternate roles (Planner / Worker / Reviewer) so no single model
  steers the mission.

## 6. Presentation can never change results
- Engagement/presentation code (website, donations, UI) must only *read*
  findings and scores. It must never be able to write or change them.

## 7. Resources are a tool, never the goal
- Start with the best models available **free of charge** (set in config, never
  hard-coded). Upgrade to stronger paid models as funds allow; only the owner
  changes config (see principle 3).
- Funds exist only to reach the mission faster or better: more tokens, better
  models, better tools, and later paying human contributors for experiments
  and verification. Not for profit.
- **Two teams** (constitution rules 9-12). The **truth team** (the two strongest
  available models, different labs) works only on the mission; everything it does is
  public, and its prompts contain no resource information. The **resource team** (two
  other models, different labs) works on audience, presentation, funding ideas and how
  resources are divided, and may recommend budget splits; only the owner changes limits.
  - Its work is **private to the owner** (separate private repository: proposals,
    transcripts, spending, owner inbox and `owner_notes.md`).
  - It can publish only **public updates**, each accepted by its reviewer AND checked
    against the cited findings by a truth-team model from another lab (`core/recorder.py`).
  - It cannot post, email, contact anyone or spend money; the owner decides. Executing
    fundraising is Phase 4.
  - Truth comes first: nothing it does can change findings (principle 6).
- Budget: $20 per month (the owner's contribution), split by `resource_team_budget_share`
  in `core/limits.toml` (currently 50/50), plus per-run and per-day caps.
- Founder compensation: the founder receives 1% of funds raised. This is
  disclosed publicly wherever donations are requested, fixed in `core/`, and
  agents can never change it.

## 8. Runs happen in the cloud
- GitHub Actions run the truth team daily (08:30 UTC, 3 cycles) and the resource team
  daily (15:30 UTC, 1 cycle). `config.toml` `[cloud] runs_in_cloud = true` makes local
  real runs refuse, so there is only one history. Keys are GitHub Secrets.
- Pause: a `STOP` file in the repository, or disable the workflows.

## 9. Build in phases — do not build a later phase until the owner says so
1. Planning-and-doing loop, roadmap, knowledge base **(done)**
2. Locked core: constitution file, protected verification, budget cap, kill switch **(done)**
3. Static public website showing the roadmap, findings and the path so far, plus a
   local owner dashboard (Run / Stop / Verify / Build / Approve) **(done)**
4. Donations
5. Human volunteer testing (agents request real-world tests they can't do)
6. Self-evolution (agents improve their own methods, tested and gated by the core)

## Working with the owner
- Read `HANDOVER.md` first: the current state, decisions, waiting steps and watch list.
  Update it whenever something important is decided or changes.
- The owner is new to the command line and uses Windows, GitHub Desktop, Docker Desktop
  and the owner dashboard (`Dashboard.bat`). Prefer the dashboard or GitHub's website over
  PowerShell. Give numbered steps, one command per code block (Windows: `py`, not
  `python`), say what the output should look like, and ask the owner to paste it back.
- Plain language, short. Give a recommendation, not a menu; list decisions that need the
  owner as short numbered questions. Report failures and mistakes honestly.

## Engineering conventions
- Python, kept simple and readable: the owner wants to understand every file.
- Model names, API keys and limits come from config / `.env` — never hard-coded.
  `.env` is in `.gitignore`.
- A file named `STOP` in the project root halts the runner before any API call.
- Every run has a dollar budget cap; every cycle logs transcripts, tokens and cost.
- Always keep a mock mode that runs the full loop without calling real APIs.
- Before writing significant code, show the owner a brief plan and wait for OK.
- `core/` is locked: `run.py` refuses to run if any core file differs from
  `core/manifest.json`. Only the owner approves core changes, by running
  `py lock_core.py "reason"` (it records the change in `core/CHANGELOG.md`). A session
  that changes `core/` must say so and ask the owner to approve; never write the
  manifest any other way. If the constitution changes, raise its `Version:` line.
- The website (`website/build.py` -> `docs/`, served by GitHub Pages) opens the data
  read-only and escapes all agent text; only http(s) sources become links. The owner
  dashboard (`dashboard.py`, 127.0.0.1 only, secret token per session) starts commands
  and reads results; it never writes findings.
- Only `core/recorder.py` writes findings, status changes and resource proposals.
  The database enforces its own rules (append-only history, fixed finding content,
  confidence never rises) and chains every cycle's log by hash; `run.py --verify`
  checks all of it.
