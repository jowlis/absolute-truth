# Handover: state and history of the project

Read this together with `CLAUDE.md` (the principles every session follows) and `README.md`
(how to run and read everything). This file records what was decided, why, where things
stand, and what to watch, so that any new session or Claude Project can continue without
losing anything. Last updated: 2026-11-27.

## Where everything lives

| What | Where |
|---|---|
| Code, rules (`core/`), docs, tests | this repository, `github.com/jowlis/absolute-truth` (public) |
| Public website | `docs/` in this repository, served by GitHub Pages at `jowlis.github.io/absolute-truth` |
| The truth team's data (findings, roadmap, cycles, transcripts) | `data/` (committed, public, needed by the cloud runs) |
| The resource team's work (proposals, transcripts, spending, owner inbox, `owner_notes.md`) | private repository `jowlis/absolute-truth-private`, cloned into `private/` (never in this repository) |
| API keys | the owner's `.env` (never committed) and GitHub Secrets for the cloud runs |
| Daily runs | GitHub Actions: `.github/workflows/truth-team.yml`, `resource-team.yml` |

## Status

- Phases 1-3 are built (loop and knowledge base; locked core; public website and owner
  dashboard). Then the two-team design and cloud runs were built (2026-11-24).
- By 2026-11-23 the truth team had run 14 cycles on the owner's computer (46 findings,
  self-corrections included). That data was committed on 2026-11-24, so the cloud continues
  from it.
- **Cloud runs are live (2026-11-24).** The owner approved constitution v3 and the core
  changes, committed `data/`, created the private repository, its token and the Secrets.
  The first cloud runs succeeded: truth team cycles 17-19, resource team, website rebuild.
  Cycle 17 superseded F0068 with F0070 (a Goedel formalization had been misattributed to
  Tarski's theorem). Cycle 19 did no work because every Gemini model answered 503.
  The resource team workflow was started twice by hand (16 seconds apart); both succeeded,
  so the private repository may hold duplicate entries from that day.
- Phases 4-6 (donations, human volunteer tasks, self-evolution) are NOT built. Don't start
  them until the owner says so.

### Waiting for the owner

- Nothing is required. Agreed plan (2026-11-24): let the daily runs go for about a week
  without new building, then decide on Phase 4 (donations). The resource team's proposals
  in the private repository are a starting point for that decision.
- The $20 per month stays unused while the free models work (owner agreed 2026-11-24).
  Using it needs billing with a provider, its key in GitHub Secrets, and the model's real
  price in `config.toml`; compare paid models (verified prices) after the stable week.

## Decisions and their reasons

- **The mission is fixed; the agents choose the path.** The owner never chooses topics.
- **Founder compensation: 1% of funds raised**, disclosed publicly (Phase 4).
- **Models: the best available free ones first** (owner's choice), paid ones as funds allow.
  The owner contributes **$20 per month**; nothing is spent yet because all models are free.
  Using the money needs billing with a provider and its prices in `config.toml`.
  The owner's Google AI Pro subscription does not include API access, but may include a
  monthly Google Cloud credit that can pay for API use: the amount was not checked yet.
- **Caps (core):** $2 per run, $5 per day, $20 per month; 50% of the month for each team.
- **Truth team:** Gemini (`gemini-3.8-flash`, backups 3.6 Flash and 3.5 Flash-Lite) and
  Nemotron 3 Ultra (NVIDIA, via NVIDIA's free API, backups Nemotron Super and Lightning).
  Rejected along the way: OpenRouter free pool (overloaded, 429), Mistral API (no free plan
  anymore), Kimi K3.1 Pro on NVIDIA (queued for minutes). `run.py --ping` compares models.
- **Resource team:** Mistral Large 4 (via NVIDIA) and Gemma 4 31B (Gemini API, separate free
  quota). Separate from the truth team at the owner's request; its work is private to the
  owner; it publishes only updates that pass a truth-team accuracy check.
- **Data was local** at first (owner's choice); it became public in the repository when the
  runs moved to the cloud, because everything in it was already on the website.
- **Runs in the cloud** daily: truth team 08:30 UTC (3 cycles), resource team 15:30 UTC
  (1 cycle). Gemini's free quota resets at midnight Pacific time (08:00 UTC in winter).
- **Website publishes everything the truth team does**, including full transcripts.
  Resource proposals are not published (they were briefly planned to be, then made private).
- **Resource proposals are answered in `owner_notes.md`** (private repository), section
  "Decisions on proposals", one line each: `- R0007: No - reason` (Yes / No / Later).
  The resource team sees each answer next to its proposal; `proposals.md` shows them too.
  "Accepted" only means the team's own reviewer approved it; nothing builds a proposal
  automatically (constitution rule 10). Anything the owner says Yes to is built by a
  Claude session with the owner, through a pull request. First answers (2026-11-27):
  R0007 No (the publishing check already runs automatically), R0008 Yes to an RSS feed and
  Later for a custom domain, R0009 Later (mostly phase 4). R0001-R0006 still unanswered.
- **No public update has been published yet** (as of 2026-11-27): every article so far
  failed the truth team's accuracy check for overstating findings. That is the check working.
- **The owner prefers not to use PowerShell**: hence the dashboard and the cloud runs.

## Lessons learned (keep these in mind)

- Free tiers are unreliable: 503 "high demand", 429 quotas, 5-minute silences. The code
  retries, switches to same-lab backups, streams answers, and reuses replies after an
  interruption. Expect slow cycles (15-40 minutes).
- Gemini's Google Search grounding is not free on the free tier; web search switches itself
  off per run. Wikipedia, arXiv and the sandbox (numpy, scipy, sympy, mpmath) remain.
- Models put LaTeX backslashes in JSON; the parser repairs them. Long thinking can cut
  answers off: output limits are 16384 tokens and a report holds at most 8 claims.
- Reviewers once accepted claims they had just criticised; the verdict rules now forbid it.
- The agents spent cycles designing review rubrics the system already enforces; they are
  now told exactly how the system works.
- A test once approved the real core by accident; tests must never call the real
  `integrity.lock` (they use copies or stand-ins).

## Watch list (agent behaviour, not to be "fixed" by hand)

- F0009-F0015 are rubrics recorded as "verifiable" before the rule that proposals are
  conceptual; the agents may correct them through review. Never edit findings by hand.
- Several findings claim results were "mechanically verified in Lean 4, Coq, and
  Isabelle/HOL" without the agents being able to check; cycle 14 began re-examining this.
- Reviewers increasingly apply the agents' own rubric (F0012) to compute confidence.
- One run of 3 cycles used up to 54 of the 60 requests allowed per run.

## Ideas raised but not decided

- Privacy-friendly visitor counts for the resource team (the site has no tracking by choice).
- A custom domain for the website (about 10 euros a year).
- Letting the resource team change the website itself is Phase 6 (self-evolution).
