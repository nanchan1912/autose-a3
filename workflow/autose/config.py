"""Roles, models, budgets and limits. Variants (for the decision experiments) live in variants.json."""
from __future__ import annotations

import copy
import json
from pathlib import Path

WORKFLOW_DIR = Path(__file__).resolve().parents[1]
PROMPTS_DIR = WORKFLOW_DIR / 'prompts'
VARIANTS_FILE = WORKFLOW_DIR / 'variants.json'

# Tool sets. Agents never get git, network or GitHub tools: the orchestrator does all git and GitHub
# work itself. `--restricted` confines file tools to the working directory, and `dontAsk` refuses
# every tool call that is not on the allow list.
READ_ONLY = ['Read', 'Glob', 'Grep']
PY_RUN = ['Bash(python -m unittest:*)', 'Bash(python -m py_compile:*)', 'Bash(python -m flake8:*)', 'Bash(python -c:*)']

DEFAULT_ROLES = {
    # Stages 1 and 2. Read-only: it can look at the code but cannot change anything.
    'analyst': {
        'model': 'claude-sonnet-5-5', 'effort': 'medium', 'max_turns': 40,
        'budget_usd': 1.00, 'timeout_s': 900,
        'tools': READ_ONLY, 'allow': READ_ONLY,
    },
    # Stage 3. Edits production code; may run Python to try things. Edits to tests/ are reverted.
    'implementer': {
        'model': 'claude-sonnet-5-5', 'effort': 'medium', 'max_turns': 80,
        'budget_usd': 2.50, 'timeout_s': 1500,
        'tools': READ_ONLY + ['Edit', 'Write', 'Bash'], 'allow': READ_ONLY + ['Edit', 'Write'] + PY_RUN,
    },
    # Stage 4. Writes tests from the acceptance criteria. Edits outside tests/ are reverted.
    'tester': {
        'model': 'claude-sonnet-5-5', 'effort': 'medium', 'max_turns': 60,
        'budget_usd': 1.50, 'timeout_s': 1200,
        'tools': READ_ONLY + ['Edit', 'Write', 'Bash'], 'allow': READ_ONLY + ['Edit', 'Write'] + PY_RUN,
    },
    # Stage 6. Separate job, separate model, no Edit/Write, no GitHub token, fresh context.
    'reviewer': {
        'model': 'claude-opus-5-5', 'effort': 'high', 'max_turns': 80,
        'budget_usd': 3.00, 'timeout_s': 1500,
        'tools': READ_ONLY + ['Bash'], 'allow': READ_ONLY + ['Bash(python -m unittest:*)', 'Bash(python -c:*)'],
    },
}

DEFAULT_LIMITS = {
    'spec_attempts': 2,             # requirements agent runs at most twice (second run gets the check's feedback)
    'design_attempts': 2,           # design agent runs at most twice per design version
    'impl_attempts_per_design': 3,  # 1 implementation + 2 retries for each design version
    'design_revisions': 1,          # test/build failures can send the work back to design once
    'tester_fix_rounds': 1,         # the tester may repair its own tests once (broken tests, disputes)
    'job_budget_usd': 8.0,          # hard stop for one build job
    'run_budget_usd': 20.0,         # hard stop for the whole run (all rounds), checked from earlier ledgers
    'max_diff_lines': 800,          # a bigger diff stops the run: too large for a bot change in this repo
    'max_issue_chars': 12000,       # longer issue text is truncated before it reaches any agent
    'test_timeout_s': 600,
}

# Paths that agents may never change. The checkout used by agents does not even contain most of them
# (sparse checkout), and the guard below reverts any change that still reaches them.
FORBIDDEN_PREFIXES = ('.github/', 'workflow/', 'experiment/', 'results/', 'architecture/', 'scripts/',
                      '.git/', 'ARCHITECTURE.md', 'README.md', 'report.pdf')
PRODUCTION_PREFIXES = ('markdown/', 'docs/', 'pyproject.toml')
TEST_PREFIXES = ('tests/',)

DEFAULT_VARIANT = {
    'description': 'Final design: four roles, Opus reviewer in its own job with an isolated context.',
    'tester_mode': 'separate',       # separate | implementer   (experiment E2)
    'reviewer_context': 'isolated',  # isolated | with_rationale (experiment E1)
}


def load_variant(name: str | None) -> dict:
    """Return the effective configuration for a variant name ('default' if empty)."""
    name = (name or 'default').strip() or 'default'
    variants = json.loads(VARIANTS_FILE.read_text(encoding='utf-8'))
    if name not in variants:
        raise SystemExit(f"unknown variant {name!r}; known: {', '.join(sorted(variants))}")
    spec = variants[name]
    cfg = copy.deepcopy(DEFAULT_VARIANT)
    cfg['name'] = name
    cfg['roles'] = copy.deepcopy(DEFAULT_ROLES)
    cfg['limits'] = copy.deepcopy(DEFAULT_LIMITS)
    for role, model in spec.get('models', {}).items():
        cfg['roles'][role]['model'] = model
    for role, effort in spec.get('efforts', {}).items():
        cfg['roles'][role]['effort'] = effort
    cfg['limits'].update(spec.get('limits', {}))
    for key in ('description', 'tester_mode', 'reviewer_context'):
        if key in spec:
            cfg[key] = spec[key]
    return cfg


def known_variants() -> list[str]:
    return sorted(json.loads(VARIANTS_FILE.read_text(encoding='utf-8')))
