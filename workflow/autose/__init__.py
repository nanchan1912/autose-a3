"""autose: an agentic issue-to-pull-request pipeline for GitHub Actions.

The package is only standard library code. Agents are Claude Code CLI processes started in headless
mode (`claude -p`); everything around them (control flow, checks, git, GitHub calls) is ordinary,
deterministic Python so that the pass/fail decision of every stage is made by code, not by a model.
"""
