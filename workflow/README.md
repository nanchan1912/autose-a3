# workflow/: the autose agent code and prompts

| Path | What it is |
|---|---|
| `autose/__main__.py` | Command line used by the workflow steps: `gate`, `fetch-issue`, `build`, `release`, `release-check`, `review-prepare`, `review`, `review-post`, `finalize`. |
| `autose/pipeline.py` | Stages 1-4 as a state machine: which agent runs next, retries, loop-backs, budgets. |
| `autose/checks.py` | The deterministic stage checks (spec testability, design names real files/functions, build, tests + AC coverage) and the path guards. |
| `autose/claude.py` | Starts one agent (`claude -p`) with its tool allow list, schema, turn and dollar limits, scrubbed environment; writes transcripts and the token ledger. |
| `autose/untrusted.py` | Cleaning, injection scan, delimiting of issue/PR text; @mention neutralising for posted text. |
| `autose/ghapi.py`, `gitops.py` | GitHub REST (only in token steps) and git helpers (only the orchestrator runs git). |
| `autose/schemas.py`, `render.py` | Output schema per agent; Markdown rendering of the stage artifacts. |
| `autose/config.py`, `variants.json` | Models, tools, budgets, limits; experiment variants. |
| `prompts/` | System prompts: `common.md` (all agents), `requirements.md` + `a1_requirements_skill.md` (the A1 skill, verbatim), `design.md`, `implement.md`, `test.md`, `test_self.md` (E2), `review.md`. |
| `github-workflows/` | Copy of `.github/workflows/` (`scripts/sync_workflow_copy.sh`). |
| `autose_tests/` | Offline unit tests: `PYTHONPATH=workflow python -m unittest discover -s workflow/autose_tests` |

Run stages 1-4 locally (needs Claude Code on PATH or `AUTOSE_CLAUDE_BIN`, and the project installed
in the active Python):

```bash
PYTHONPATH=workflow python -m autose build --issue-json issue.json --work <checkout> --out art --variant smoke-haiku
```
