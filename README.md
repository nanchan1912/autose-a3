# AutoSE Assignment 3: an agentic issue-to-pull-request workflow

- **Repository (fork):** https://github.com/nanchan1912/autose-a3 - contains the full upstream history up to the pinned commit
- **Upstream:** https://github.com/Python-Markdown/markdown, pinned at commit
  `3f2c5510bd8d64a73ec18342f740371bcde9b20c` (short `3f2c551`, same commit as in A2). The fork's `main`
  starts at that commit; the commits after it only add the assignment material and the seeded bug below.
- **Seeded bug:** one line in `markdown/extensions/toc.py` (`remove_fnrefs`) is changed exactly as in A2
  task T1, for issue I1. The full existing test suite still passes with it. Issue I2 is a real bug at
  `3f2c551`; issues I3-I5 are features/vague requests.
- **Models:** analyst, implementer and tester on `claude-sonnet-5-5` (effort medium); reviewer on
  `claude-opus-5-5` (effort high). Agents run as headless Claude Code CLI `2.1.330` processes.
  Variants for the experiments are in [workflow/variants.json](workflow/variants.json).
- **Demo video:** https://drive.google.com/drive/folders/1gSMrcYYyEY3c_kF1WOZNoMxY_9WzCURW?usp=drive_link
- **ADRs:** all 10 decisions (D1-D10) have a full ADR in [architecture/decisions](architecture/decisions),
  not just the required 8. (Done all 10 for you, Aviral sir uwu.)

## Note on the git history

The design was done first, locally: the architecture views and the ADRs were written before the agent
code. The history was later squashed and replayed onto the pinned commit, which is why the ADR commit
(`1d8551c`) and the agent-code commit (`e64f472`) are one second apart. The sentence in ADR-006 about a
local Haiku plumbing run was added after that run, not at the time the ADR was first written.

## How to trigger the workflow

You need write access to the repository.

| What | How | What happens |
|---|---|---|
| Full pipeline on an issue | add the label `autose` to the issue, or comment `/autose` on it | stages 1-6, PR opened, independent review posted, hand-over comment on the issue |
| Full pipeline with a variant | comment `/autose variant=E2-self-test` on the issue | same, on its own branch `autose/issue-N-<variant>` |
| Review only (existing PR) | comment `/autose` on the pull request | stage 6 only |
| Either, from the Actions tab | *Actions -> autose -> Run workflow* (number, mode `full`/`review`, variant) | as above; used by `scripts/run_experiments.sh` |

The workflow never merges. Every run ends with a comment that hands the decision to a person.
Pull requests from forks are never reviewed (their code would run next to the API key), and
comments from people without write access are ignored.

## How it works (short)

`autose.yml` runs a **gate** job (authorisation, command parsing), then up to three **rounds**
(`autose-round.yml`), then **finalize**. A round is: a build job in which a Python orchestrator runs
stages 1-4 with three agents (analyst, implementer, tester) and deterministic checks between them,
then pushes the branch and opens the PR (stage 5); CI (`ci.yml`) and a release check; then the
independent **review** job (`autose-review.yml`, stage 6). If the reviewer requests changes, the next
round resumes at the stage it names. Details: [architecture/views](architecture/views) and
[architecture/decisions](architecture/decisions).

Each stage's artifact (`spec.md`, `design.md`, `diff.patch`, `test_report.md`, `pr.md`, `review.md`),
the full agent transcripts and the token ledgers are uploaded as workflow artifacts of the run.

## Repository layout

```
README.md               this file
ARCHITECTURE.md         A2 architecture document (read by the design agent)
report.pdf              the report
.github/workflows/      autose.yml, autose-round.yml, autose-review.yml, ci.yml
architecture/views/     component view, sequence view, stage map
architecture/decisions/ ADR-001.md ... (superseded ones kept)
workflow/               autose/ (orchestrator, checks, agent runner), prompts/, variants.json,
                        github-workflows/ (copy of .github/workflows), autose_tests/ (unit tests)
experiment/issues/      the 5 issue texts (I1-I5)
experiment/hidden_tests/ hidden acceptance tests (added after all runs were finished)
experiment/seeded_prs/  the 5 reviewer-check PRs (S1-S5.diff) + labels.json (ground truth)
experiment/variants.md  what each decision-experiment variant changes
results/results.csv     one row per run; results/runs.md links every run, PR and review
scripts/                setup, seeded PRs, experiment runner, hidden-test scoring, result collection
```

## Setting it up on a fresh fork

1. Fork Python-Markdown, then push this repository's `main` to the fork (it starts at `3f2c551`).
2. Install the GitHub CLI and run `gh auth login`.
3. `scripts/setup_github.sh OWNER/REPO settings` - enables issues and Actions, lets Actions
   open PRs, creates labels. Then store one model credential as a secret (see below).
4. `scripts/setup_github.sh OWNER/REPO issues` - opens I1-I5 (#1-#5).
5. `scripts/setup_github.sh OWNER/REPO protect` - main requires a PR for everybody.
6. `python scripts/open_seeded_prs.py OWNER/REPO` - opens the five reviewer-check PRs.

Unit tests of the deterministic checks: `PYTHONPATH=workflow python -m unittest discover -s workflow/autose_tests`.

## Model credentials: why a secret is needed

The agents run inside GitHub Actions, on GitHub's machines, not on a laptop. To call Claude from
there, the workflow needs a credential stored as an encrypted **repository secret** (Settings ->
Secrets and variables -> Actions). Exactly one of these is needed:

| Secret | What it is | Cost |
|---|---|---|
| `ANTHROPIC_API_KEY` | API key from console.anthropic.com | billed per token; a hard spending limit is set in the console |
| `CLAUDE_CODE_OAUTH_TOKEN` | long-lived token from `claude setup-token` (needs a Claude Pro/Max subscription) | counts against the subscription's usage limits |

The credential only reaches the steps that run agents (never a step with a GitHub token), and it is
never written to code, logs or prompts. Workflows triggered from forks do not receive secrets.

## Cost and tokens

The runs used a Claude subscription token (`CLAUDE_CODE_OAUTH_TOKEN`), not a pay-per-token API key. Extra
(pay-as-you-go) usage is disabled on the subscription, so spending is hard-capped at the plan price; on top
of that each agent call has a dollar cap (`--max-budget-usd`), each build job $8 and each run $20 (see
`workflow/autose/config.py`). The dollar figures in the results are the list-price equivalents computed by
Claude Code. Total tokens used over all 40 runs: 4,666,867 input tokens (including cache) and 203,264 output
tokens, about $6.79 at list price (per-run numbers in [results/runs.md](results/runs.md)).

## Use of AI

Following the course policy, substantial AI help is declared here. I designed the workflow and made every
architectural decision; I used a coding agent (Claude Code, Claude Opus 5.5) as a tool to implement that
design under my direction, and I reviewed everything it produced.

- **My own work (summary):** the architecture and every design decision behind it (the ADRs' reasoning),
  the experiment design and predictions, directing the build and the runs, reviewing all generated code and
  text, and the discussion parts of the report. Details in the last bullet below.
- **Implemented with a coding agent under my direction and reviewed by me:** the workflow files in
  `.github/workflows/`, the orchestrator and checks in `workflow/autose/`, the agent prompts in
  `workflow/prompts/` (the requirements prompt embeds my own A1 skill verbatim), the unit tests, the scripts
  in `scripts/`, the five issue texts, the seeded PRs, the hidden tests, and the architecture views.
  The agent also ran the GitHub setup, the experiment runs and the result collection on my instructions.
- **My own work:** the reasoning in every ADR (`architecture/decisions/`; I wrote the reasons, the agent put
  them into the Nygard template and added the factual description of what the code does), my predictions
  for E1 and E2 (recorded before the experiments), and the discussion parts of the report (the three most
  important decisions, the interpretation of E1 and E2, where the reviewer was wrong, hindsight and
  limitations). The tables and numbers in the report are generated from the run data by
  `scripts/make_report.py`.
- The answer to the clarification questions on issue #5 was written by me as the maintainer.
- **Added on 24 Nov by the coding agent at my request, after my own review of the submission:** the
  git-history note above, the correction of the E2 design-retry claim in the report (with the cause taken
  from the run logs), one-line explanations of the failed runs in `results/runs.md`, and the total token
  count in this README.
