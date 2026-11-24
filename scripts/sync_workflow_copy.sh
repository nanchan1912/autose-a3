#!/usr/bin/env bash
# Keep workflow/github-workflows/ identical to .github/workflows/ (the assignment asks for a copy).
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p workflow/github-workflows
cp .github/workflows/*.yml workflow/github-workflows/
echo "copied: $(ls workflow/github-workflows | tr '\n' ' ')"
