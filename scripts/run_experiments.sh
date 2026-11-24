#!/usr/bin/env bash
# Start experiment runs through workflow_dispatch and wait for them, one variant at a time.
# Runs on different issues/PRs run in parallel; the same issue/PR never gets two runs at once
# (the workflow's concurrency group would cancel a second queued run).
#
#   scripts/run_experiments.sh <owner>/<repo> review <variant> <pr> [<pr> ...]   # E1: reviewer only
#   scripts/run_experiments.sh <owner>/<repo> full   <variant> <issue> [...]     # E2 / main runs
#
# Example (E1, 5 seeded PRs x 3 variants):
#   for v in default E1-same-model E1-sees-rationale; do scripts/run_experiments.sh me/markdown review $v 6 7 8 9 10; done
set -euo pipefail
REPO="${1:?}"; MODE="${2:?}"; VARIANT="${3:?}"; shift 3
[ "$#" -gt 0 ] || { echo "give at least one issue/PR number" >&2; exit 2; }
for n in "$@"; do
  gh workflow run autose.yml --repo "$REPO" -f number="$n" -f mode="$MODE" -f variant="$VARIANT"
  echo "dispatched $MODE #$n ($VARIANT)"
  sleep 3
done
echo "waiting for the runs to finish..."
sleep 20
while [ "$(gh run list --repo "$REPO" --workflow autose.yml --json status --jq '[.[] | select(.status != "completed")] | length')" != "0" ]; do
  sleep 30
done
gh run list --repo "$REPO" --workflow autose.yml --limit "$#" --json databaseId,displayTitle,conclusion,url
