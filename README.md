# AutoSE Assignment 3: an agentic issue-to-pull-request workflow

- **Fork:** https://github.com/OWNER/markdown  <!-- TODO: replace OWNER with your GitHub user name -->
- **Upstream:** https://github.com/Python-Markdown/markdown, pinned at commit
  `3f2c5510bd8d64a73ec18342f740371bcde9b20c` (short `3f2c551`, same commit as in A2). The fork's `main`
  starts at that commit; the commits after it only add the assignment material and the seeded bug below.
- **Seeded bug:** one line in `markdown/extensions/toc.py` (`remove_fnrefs`) is changed exactly as in A2
  task T1, for issue I1. The full existing test suite still passes with it. Issue I2 is a real bug at
  `3f2c551`; issues I3-I5 are features/vague requests.
- **Models:** analyst, implementer and tester on `claude-sonnet-5-5` (effort medium); reviewer on
  `claude-opus-5-5` (effort high). Agents run as headless Claude Code CLI `2.1.330` processes.
  Variants for the experiments are in [workflow/variants.json](workflow/variants.json).
- **Demo video:** TODO link

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
3. `scripts/setup_github.sh OWNER/markdown settings` - enables issues and Actions, lets Actions
   open PRs, creates labels, stores `ANTHROPIC_API_KEY` as a repository secret.
4. `scripts/setup_github.sh OWNER/markdown issues` - opens I1-I5 (#1-#5).
5. `scripts/setup_github.sh OWNER/markdown protect` - main requires a PR for everybody.
6. `python scripts/open_seeded_prs.py OWNER/markdown` - opens the five reviewer-check PRs.

Unit tests of the deterministic checks: `PYTHONPATH=workflow python -m unittest discover -s workflow/autose_tests`.

## Cost and tokens

A hard monthly spending limit was set in the Anthropic console before the first run. Each agent call
also has a dollar cap (`--max-budget-usd`), each build job $8 and each run $20 (see
`workflow/autose/config.py`). Total tokens used: see the last line of [results/runs.md](results/runs.md).

## Use of AI

TODO: describe honestly which parts were written with a coding agent (for example the orchestrator,
workflows, scripts and prompts were drafted with Claude Code and reviewed by me) and which are my own
(the ADRs and their reasoning, the report). The course policy requires the ADRs and their reasoning
to be the student's own.
