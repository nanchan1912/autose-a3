#!/usr/bin/env bash
# One-time setup of the fork on GitHub. Needs the GitHub CLI (`gh auth login` done once).
#
#   scripts/setup_github.sh <owner>/<repo> settings   # repo settings, labels, API key secret
#   scripts/setup_github.sh <owner>/<repo> issues     # open the five experiment issues (#1-#5)
#   scripts/setup_github.sh <owner>/<repo> protect    # protect main (do this AFTER pushing everything)
#
# Nothing here pushes code; the README lists the order of steps.
set -euo pipefail
REPO="${1:?usage: setup_github.sh <owner>/<repo> settings|issues|protect}"
STEP="${2:?usage: setup_github.sh <owner>/<repo> settings|issues|protect}"
cd "$(dirname "$0")/.."

case "$STEP" in
settings)
  gh repo edit "$REPO" --enable-issues --default-branch main
  # Actions on, GITHUB_TOKEN read-only by default (each job asks for more), Actions may open PRs.
  gh api -X PUT "repos/$REPO/actions/permissions" -F enabled=true -f allowed_actions=all
  gh api -X PUT "repos/$REPO/actions/permissions/workflow" \
     -f default_workflow_permissions=read -F can_approve_pull_request_reviews=true
  while IFS='|' read -r name color desc; do
    gh label create "$name" --repo "$REPO" --color "$color" --description "$desc" --force
  done <<'LABELS'
autose|5319e7|Maintainer: start the autose pipeline on this issue
autose-pr|0e8a16|Pull request opened by autose
autose:approved|0e8a16|autose reviewer found no blocking or major problems
autose:changes-requested|d93f0b|autose reviewer requested changes
seeded|fbca04|Reviewer-check pull request with known ground truth (experiment)
LABELS
  echo "Now store ONE model credential as a secret (you will be asked to paste it):"
  echo "  gh secret set ANTHROPIC_API_KEY --repo $REPO        # API key, billed per token"
  echo "  gh secret set CLAUDE_CODE_OAUTH_TOKEN --repo $REPO  # token from 'claude setup-token' (subscription)"
  ;;
issues)
  out=experiment/issue_numbers.json
  echo "{" > "$out"
  for i in 1 2 3 4 5; do
    f="experiment/issues/I$i.md"
    title=$(sed -n 's/^title: "\(.*\)"$/\1/p' "$f")
    # body = everything after the second '---' line
    body=$(awk 'c>=2{print} /^---$/{c++}' "$f")
    url=$(gh issue create --repo "$REPO" --title "$title" --body "$body")
    num="${url##*/}"
    echo "created I$i as #$num: $title"
    sep=$([ "$i" = 5 ] && echo "" || echo ",")
    echo "  \"I$i\": $num$sep" >> "$out"
  done
  echo "}" >> "$out"
  echo "wrote $out"
  ;;
protect)
  # Pull request required for main, for everybody (enforce_admins). 0 approvals so that a single
  # maintainer can still merge after reviewing; the bot cannot push to main at all.
  gh api -X PUT "repos/$REPO/branches/main/protection" --input - <<'JSON'
{
  "required_status_checks": null,
  "enforce_admins": true,
  "required_pull_request_reviews": {"required_approving_review_count": 0, "dismiss_stale_reviews": true},
  "restrictions": null,
  "allow_force_pushes": false,
  "allow_deletions": false
}
JSON
  echo "main is protected"
  ;;
*)
  echo "unknown step $STEP" >&2; exit 2;;
esac
