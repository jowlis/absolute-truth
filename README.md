# Absolute Truth: Phase 1

Two AI models from different labs pursue one fixed mission, **"Absolute Truth"**.
They decide what it means, plan their own path as a roadmap, do small tasks with
tools, check each other's work, and record what holds up as findings. Nobody
chooses topics for them. The principles are in [CLAUDE.md](CLAUDE.md), and the
rules the agents follow are in [core/constitution.md](core/constitution.md).

Phases 1-3 are built: the planning-and-doing loop, the roadmap and the knowledge base; the locked core that guards them; and the public website with your owner dashboard.

## How a cycle works

**Cycle 1 (genesis):** each model drafts, on its own, what "Absolute Truth" might
mean, what can and cannot be known, and a first roadmap. The planner merges the
drafts; the other model reviews the merge.

**Every later cycle:**

1. **PLAN.** The planner reads the roadmap, findings and recent cycles. It picks one
   small task, or chooses resource work instead, and may revise the roadmap.
   Every change needs a reason.
2. **DO.** The worker (the other model) carries out the task with tools:
   - web search (Gemini's built-in Google Search),
   - Wikipedia and arXiv lookups,
   - a sandboxed Python executor.
3. **REVIEW.** The planner's model checks the work. It looks for errors, weak
   evidence, overconfidence, and claims shaped to impress rather than to be true.
4. **RECORD.** `core/verdicts.py` decides what becomes a finding and with what
   status. Review can lower confidence but never raise it.

Roles rotate every cycle: A plans and reviews while B works, then they swap.

**Resource work** is a separate track. The agents can think about how to get better
tools, models or funding, as a means to the mission. It produces proposals for you
in `data/resource_proposals.md`, never findings. A ceiling in `core/limits.toml`
(20% of cycles by default) stops it from crowding out mission work.

## The easy way: the owner dashboard

Double-click **`Dashboard.bat`** in the project folder. Your browser opens a page that only
your own computer can reach, with buttons to **Run** 1-5 cycles (with live progress),
**Stop** / **Allow runs again** (the kill switch), **Verify**, **Build website**, preview
the site, and **Approve core changes**. Keep the black Dashboard window open while you use
it. Everything below can also be done by typing commands.

## The public website (Phase 3)

`website/build.py` turns the data into a static website in `docs/`: home, roadmap (with
every version), findings (filterable, one page each), the path (every cycle, with full
transcripts), rules, resource proposals, and a "verify it yourself" page with the history
chain as open data (`data/cycles.json`) and a 40-line checker (`verify_chain.py`).
It opens the data read-only, escapes everything the agents wrote, uses no external
scripts, cookies or tracking, and works on phones and in dark mode.

- Build: `python website/build.py` (the dashboard does it after every run). Preview by
  opening `docs/index.html`.
- Publish: commit `docs/` and push. GitHub Pages serves it (Settings -> Pages -> Deploy
  from branch `main`, folder `/docs`). Site settings are in `config.toml` under `[site]`.

## Setup

1. Install the requirements:

   ```bash
   pip install -r requirements.txt
   ```

2. Copy `.env.example` to `.env` and add your free keys:
   - `GEMINI_API_KEY` from Google AI Studio (https://aistudio.google.com/apikey)
   - `NVIDIA_API_KEY` from NVIDIA's free developer API (https://build.nvidia.com)
   - `OPENROUTER_API_KEY` is optional (only if you switch model B back to OpenRouter)

3. Install Docker and start it. The Python sandbox needs it. Without Docker the runner
   still works, but the agents get no code execution. On the first run, the sandbox
   image (Python with numpy, scipy, sympy and mpmath, from `sandbox/Dockerfile`) is
   built automatically; this needs the internet once and takes a few minutes.

4. Check which models your keys can use, and fix `config.toml` if a model id is
   missing. Free model lineups change often.

   ```bash
   python run.py --list-models
   ```

## Running

On Windows, type `py` instead of `python` in the commands below.

```bash
python run.py --list-models        # which models your keys can use
python run.py --ping B             # does model B answer right now, and how fast?
python run.py --ping B some/model other/model   # compare candidate models
python run.py --mock --cycles 6    # dry run: pretend models, no API calls, writes to data-mock/
python run.py --cycles 3           # real run: writes to data/
python -m unittest discover -s tests -t .   # run the tests
```

- **Kill switch:** create a file named `STOP` (no extension) in this folder. The
  runner exits before its next API call. Delete it to allow runs again.
  Windows PowerShell: `New-Item STOP` to stop, `Remove-Item STOP` to allow runs.
  Mac/Linux: `touch STOP` and `rm STOP`.
- **Limits:** set in `core/limits.toml`: a dollar cap per run, a request cap per run,
  tool steps per turn, and the resource-work ceiling. Every call is checked first
  against the worst case.
- **Free-tier quotas:** each model's daily request limit in `config.toml` is counted
  across runs (UTC days). Gemini's free tier is small (about 20 requests a day on
  Flash), so expect only a few cycles a day.
- **Busy servers:** server errors, timeouts and "too many requests" are retried
  after 15, 45 and 90 seconds. If a model stays unavailable, or has used its daily
  quota, the agent switches to its `fallback_models` from the same lab (set in
  `config.toml`). The cycle log lists which models actually replied. If every model
  fails, the run stops cleanly; try again later.
- **Interrupted attempts:** if a cycle is stopped before it recorded anything (an
  outage, the kill switch, a used-up quota), its files are kept in a
  `cycle_NNNN_not_counted` folder, but it gets no cycle number. The next attempt
  reuses the number, and also reuses the replies already received
  (`data/reply_cache.json`), so finished work isn't thrown away.

## Autopilot: cycles on a schedule

`autopilot.py` runs a few cycles every few hours on its own, and asks you only when
something needs you. Turn it on with **Turn autopilot on** on the dashboard, or:

```bash
py autopilot.py --install     # Windows Task Scheduler: a tick every few hours
py autopilot.py --uninstall   # turn it off
py autopilot.py --status      # what it did lately, and whether it is waiting for you
py autopilot.py --resume      # carry on after it asked for you
py autopilot.py --mock        # one tick with pretend models (data-mock/)
```

Ticks run only while you are signed in to Windows and the computer is awake.

- **Each tick** checks the core and runs `run.py --verify`, then runs `run.py --cycles K`, verifies
  again and rebuilds the website. K is `cycles_per_tick` in `config.toml` (`[autopilot]`), but
  never more than what is left today of `autopilot_max_cycles_per_day` in `core/limits.toml`.
- **Budgets are unchanged.** Every call still passes `core/budget.py`: the dollar caps per run,
  day and month, and each model's daily quota. A used-up quota or daily cap just waits for a
  later tick.
- **History is unchanged.** The autopilot only reads the knowledge base. Runs still record
  through `core/recorder.py`, and only one run can write at a time (`data/run.lock`).
- **When it needs you**, it writes `data/NEEDS_OWNER.md`, shows a Windows notification and a
  banner on the dashboard, and runs nothing until you resume it. That happens when verify finds
  a problem, the core changed without approval, a model is gone from your key, the monthly cap
  is reached, a model is unreachable for several ticks in a row, several cycles in a row fail
  or produce nothing, or a run stops with an unexpected error. New resource proposals only
  get a notification.
- **Publishing** stays with you unless you set `publish = true` under `[autopilot]`. Then it
  commits `docs/` and pushes after each clean verify.
- Its notes are in `data/autopilot.log`; the output of the last run is in
  `data/autopilot_last_run.txt`.

## The locked core (Phase 2)

The rules live in `core/`: the constitution, limits, budget guard, kill switch, scoring
rules (`verdicts.py`) and the recorder (`recorder.py`, the only code that writes findings).

- **Locked.** `core/manifest.json` holds a fingerprint of every core file. `run.py`
  refuses to run if any of them changed without your approval. To approve a change:

  ```bash
  python lock_core.py "why the change was made"
  ```

  It shows what changed, asks you to type `yes`, records the change in
  `core/CHANGELOG.md` and writes new fingerprints. Then commit `core/`. If the
  constitution changed, raise its `Version:` line first.
- **Protected recording.** Whatever the rest of the code does, the recorder only accepts
  a review from a model of a *different lab*, never lets review raise confidence, skips
  claims with an invalid type, and records at most `max_claims_per_report` per cycle.
- **The database guards itself.** Findings and their history can't be deleted, a recorded
  finding's statement, type and author can't be edited, and confidence can never rise.
- **History chain.** Each cycle's log is hashed together with the previous cycle's hash.
  Each log also names the rules it ran under (constitution version and core fingerprint).
- **Spending caps** in `core/limits.toml`: per run, per day and per month (UTC), kept in
  `data/spending.json`. Every call is checked first against its worst-case cost.
- **Check everything:**

  ```bash
  python run.py --verify
  ```

  It reports the core fingerprint and constitution version, then checks the database
  rules and the whole history chain.

An honest limit: on your own computer nothing can be locked against you, since you
control the machine. The core makes every rule change deliberate and recorded, and
makes any quiet edit of the rules or of history detectable.

## Reading the results

Everything is in `data/` (or `data-mock/` for dry runs). These are read-only views:

```bash
python show.py roadmap          # the current plan
python show.py versions         # how the plan changed, version by version
python show.py findings         # all findings
python show.py finding F0003    # one finding: evidence, sources, dependencies, history
python show.py path             # every cycle, one line each
python show.py cycle 4          # the full log of one cycle
python show.py proposals        # resource proposals for you
python show.py costs            # tokens and cost per cycle
```

Add `--mock` to any of these to read the dry-run data.

**Roadmap** (`data/roadmap.md`): the agents' working interpretation of the mission,
what they think is and isn't knowable, then the tree of milestones (M1…) and
tasks (T1…). Status marks: ○ proposed, ▶ active, ✓ done, ✗ abandoned. Each
version, with the changes that produced it, is kept in `data/roadmap_versions/`.

**Findings** (`data/knowledge.db`, SQLite) carry:
- **type:** `verifiable` (logic, maths or evidence) or `conceptual` (a reasoned
  position that can't be checked);
- **confidence:** from 0 to 1;
- **status:**
  - `supported`: verifiable, and accepted by the reviewer;
  - `conceptual`: conceptual, and accepted;
  - `contested`: the reviewer has doubts;
  - `refuted`: shown wrong;
  - `superseded`: replaced by a more precise or corrected finding (shown with its
    replacement);
  - `proposed`: never reviewed (for example, the run stopped);
- **refutation condition, evidence, sources,** and the earlier findings it builds on.

When a finding is refuted or superseded, every finding that depends on it, even
indirectly, is marked **NEEDS REVIEW**. Rejected claims never become findings; they stay in the
cycle log.

**Cycle logs** (`data/runs/<run>/cycle_NNNN/`):
- `log.md`: the task, what was done, results, disagreements, roadmap changes and next
  step. A cycle that produced nothing concrete is marked `unproductive`.
- `transcript.json`: every message, tool call and result.

`data/path.md` collects all cycle logs in order: this is the path itself.

## Files

| Path | What it does |
|---|---|
| `run.py` | Starts a run; checks keys, models and the sandbox |
| `show.py` | Read-only views of the data |
| `dashboard.py`, `Dashboard.bat` | Your owner dashboard (local only) |
| `website/` | Builds the public website into `docs/` (read-only), plus `verify_chain.py` |
| `config.toml` | Models, prices, rate limits, sandbox and lookup settings |
| `core/` | **Locked:** constitution, limits, budget guard, kill switch, scoring rules, recorder, integrity checks |
| `lock_core.py` | Your command for approving changes to `core/` |
| `loop/cycle.py` | One cycle: genesis, or plan → do → review → record |
| `loop/prompts.py` | Everything the agents are told (no topics, only process) |
| `loop/schemas.py` | The JSON each role must return, and its checker |
| `loop/roles.py` | Role rotation |
| `agents/` | Adapters: Gemini, any OpenAI-format API (e.g. OpenRouter), and the mock |
| `tools/` | Sandbox (Docker), Wikipedia/arXiv lookups, the toolbox |
| `knowledge/db.py` | Findings, dependencies, the refutation cascade, cycles, costs |
| `knowledge/roadmap.py` | Roadmap tree, operations, versions, rendering |
| `tests/` | Unit tests and full mock runs |

## Changing models

Edit `config.toml`. Any provider with an OpenAI-format API needs only
`provider = "openai_compatible"`, its `base_url`, a model id and a key name. Set
the prices when you move to a paid model; the dollar cap then applies.
