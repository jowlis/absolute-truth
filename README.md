# Absolute Truth: Phase 1

Two AI models from different labs pursue one fixed mission, **"Absolute Truth"**.
They decide what it means, plan their own path as a roadmap, do small tasks with
tools, check each other's work, and record what holds up as findings. Nobody
chooses topics for them. The principles are in [CLAUDE.md](CLAUDE.md), and the
rules the agents follow are in [core/constitution.md](core/constitution.md).

This is Phase 1: the planning-and-doing loop, the roadmap and the knowledge base.

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
| `config.toml` | Models, prices, rate limits, sandbox and lookup settings |
| `core/` | **Protected:** constitution, limits, budget guard, kill switch, scoring rules |
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
