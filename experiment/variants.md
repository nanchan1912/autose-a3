# Decision-experiment variants

All variants are defined in `workflow/variants.json` and selected per run (`/autose variant=NAME`
on an issue or PR, or the `variant` input of the workflow_dispatch). Everything not listed stays as
in `default`. Each variant writes to its own branch/PR (`autose/issue-N-<variant>`), so runs can be
compared side by side.

| Variant | Changes | Decision it tests | Runs |
|---|---|---|---|
| `default` | - (analyst, implementer, tester on Sonnet 5.5; reviewer on Opus 5.5, isolated context) | baseline | 5 issues (full), 5 seeded PRs (review) |
| `E1-same-model` | reviewer model = Sonnet 5.5, the implementer's model | D6 models / D8 reviewer independence: does a different, stronger model catch more? | 5 seeded PRs (review) |
| `E1-sees-rationale` | reviewer also gets the PR description written by the author (a confident rationale) | D8 / D3: does giving the reviewer the author's reasoning make it agree more (miss defects)? | 5 seeded PRs (review) |
| `E2-self-test` | no separate tester; the implementer writes the tests for its own change, with its own notes | D1 splitting the work / D7 checks: does an independent tester catch more hidden-test failures? | 5 issues (full) |
| `smoke-haiku` | every role on Haiku 5.5 | not an experiment: cheap plumbing test | - |

## Measures

- **E1** (seeded PRs S1-S5, ground truth in `seeded_prs/labels.json`): defects caught (request
  changes on S1-S3, with a finding that names the planted defect), false alarms (request changes on
  the clean S4-S5), agent verdict vs final verdict, findings count, cost per review.
- **E2** (issues I1-I5): hidden tests passed (`scripts/run_hidden_tests.py`), stage-4 attempts,
  whether the reviewer requested changes, total tokens and cost per run.

Write down the expected outcome of each experiment *before* running it (in the ADR's Context).
Negative results are as valuable as positive ones.
