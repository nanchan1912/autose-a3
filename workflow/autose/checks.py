"""Deterministic stage checks. A stage hands over only when its check passes; the check is code.

Stage 1  check_spec    every acceptance criterion is testable (structure, concrete expected result,
                       no vague words, nothing resting on an analyst ASSUMPTION), or the spec is BLOCKED.
Stage 2  check_design  every planned file exists (or is marked new), every named function/class exists
                       (or is marked new), only allowed paths, and every AC has a planned test.
Stage 3  check_build   package installs, compiles, imports and converts a document; no new flake8
                       findings in changed files; diff within size limit; paths allowed.
Stage 4  run_tests     full suite passes (old + new tests) and every AC has at least one passing test.
"""
from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

from .common import run, truncate
from .config import FORBIDDEN_PREFIXES, PRODUCTION_PREFIXES, TEST_PREFIXES

# Words that make an expected result unverifiable (adapted from the A1 skill's lexicon, NASA SE
# handbook App. C) plus the usual "works correctly" family.
VAGUE = ['correctly', 'properly', 'as expected', 'appropriate', 'appropriately', 'reasonable', 'nice',
         'better', 'user-friendly', 'intuitive', 'robust', 'fast', 'quickly', 'easily', 'seamless',
         'should work', 'works fine', 'sufficient', 'adequate', 'etc', 'and so on']
AC_ID = re.compile(r'^AC-\d{3}$')


@dataclass
class Check:
    name: str
    passed: bool
    problems: list[str] = field(default_factory=list)
    details: str = ''
    blocked: bool = False

    def as_dict(self):
        return {'name': self.name, 'passed': self.passed, 'blocked': self.blocked,
                'problems': self.problems, 'details': self.details}

    def feedback(self) -> str:
        return '\n'.join(f'- {p}' for p in self.problems)


# ---------------------------------------------------------------- stage 1 -------------------------
def check_spec(spec: dict) -> Check:
    c = Check('spec: all acceptance criteria are testable', passed=False)
    status = spec.get('status')
    acs = spec.get('acceptance_criteria') or []
    if status == 'BLOCKED':
        c.blocked = True
        c.problems.append('the requirements agent marked the specification BLOCKED: it needs answers from a person')
        if not spec.get('clarification_questions'):
            c.problems.append('BLOCKED but no clarification questions were given')
        return c
    if not acs:
        c.problems.append('no acceptance criteria')
    seen = set()
    for ac in acs:
        aid = ac.get('id', '?')
        if not AC_ID.match(aid):
            c.problems.append(f'{aid}: id must look like AC-001')
        if aid in seen:
            c.problems.append(f'{aid}: duplicate id')
        seen.add(aid)
        for part in ('given', 'when', 'then'):
            if len((ac.get(part) or '').strip()) < 5:
                c.problems.append(f'{aid}: "{part}" is missing or too short')
        then = (ac.get('then') or '').lower()
        for word in VAGUE:
            if re.search(r'\b' + re.escape(word) + r'\b', then):
                c.problems.append(f'{aid}: expected result uses the unverifiable word "{word}"; state the exact observable result')
        if not re.search(r'[`"\'<>=0-9]|\b(true|false|none|empty|raises?|equal|contains?|not contain)\b', then):
            c.problems.append(f'{aid}: expected result has no concrete observable value (quote the exact output, value or exception)')
        if ac.get('evidence') == 'ASSUMPTION':
            c.problems.append(f'{aid}: rests on an analyst ASSUMPTION; either ground it in the issue/code (STATED or INFERRED) '
                              'or mark the spec BLOCKED and ask')
    c.passed = not c.problems
    c.details = f'{len(acs)} acceptance criteria, status {status}'
    return c


# ---------------------------------------------------------------- stage 2 -------------------------
def _norm(path: str) -> str:
    p = (path or '').replace('\\', '/').strip()
    while p.startswith('./'):
        p = p[2:]
    return p.lstrip('/')


def path_kind(path: str) -> str:
    p = _norm(path)
    if p.startswith(FORBIDDEN_PREFIXES) or p in FORBIDDEN_PREFIXES or '..' in p.split('/'):
        return 'forbidden'
    if p.startswith(TEST_PREFIXES):
        return 'test'
    if p.startswith(PRODUCTION_PREFIXES) or p in PRODUCTION_PREFIXES:
        return 'production'
    return 'other'


def symbol_exists(source: str, name: str) -> bool:
    """`func`, `Class`, `Class.method`, `CONSTANT`; for non-Python files a plain substring."""
    parts = name.strip().strip('`').replace('()', '').split('.')
    if not parts or not parts[-1]:
        return False

    def defined(n):
        return re.search(rf'^\s*(async\s+def|def|class)\s+{re.escape(n)}\b', source, re.M) or \
            re.search(rf'^\s*{re.escape(n)}\s*[:=]', source, re.M)
    if len(parts) == 1:
        return bool(defined(parts[0]))
    return bool(defined(parts[0])) and bool(defined(parts[-1]))


def check_design(design: dict, spec: dict, repo: Path) -> Check:
    c = Check('design: names the files and functions to change', passed=False)
    files = design.get('files') or []
    if not files:
        c.problems.append('no files listed')
    prod = 0
    for f in files:
        path = _norm(f.get('path', ''))
        kind = path_kind(path)
        action = f.get('action')
        target = repo / path
        if kind == 'forbidden':
            c.problems.append(f'{path}: this path may not be changed by the pipeline')
            continue
        if kind == 'other':
            c.problems.append(f'{path}: only markdown/, docs/, pyproject.toml and tests/ may be changed')
            continue
        if kind == 'production':
            prod += 1
        if action == 'modify' and not target.is_file():
            c.problems.append(f'{path}: marked "modify" but the file does not exist')
            continue
        if action == 'create' and target.exists():
            c.problems.append(f'{path}: marked "create" but the file already exists')
        if action not in ('modify', 'create'):
            c.problems.append(f'{path}: action must be "modify" or "create"')
        symbols = f.get('symbols') or []
        if kind == 'production' and not symbols:
            c.problems.append(f'{path}: name the functions/classes/sections to change')
        source = target.read_text(encoding='utf-8', errors='replace') if target.is_file() else ''
        for s in symbols:
            name, status = s.get('name', ''), s.get('status')
            if status == 'existing':
                ok = symbol_exists(source, name) if path.endswith('.py') else (name.strip('`') in source)
                if not ok:
                    c.problems.append(f'{path}: "{name}" is marked existing but was not found in the file')
            elif status == 'new':
                if path.endswith('.py') and '.' not in name and symbol_exists(source, name):
                    c.problems.append(f'{path}: "{name}" is marked new but already exists')
            else:
                c.problems.append(f'{path}: symbol "{name}" needs status "existing" or "new"')
    if files and prod == 0:
        c.problems.append('the plan changes no production code (markdown/, docs/ or pyproject.toml)')
    planned = {t.get('ac_id') for t in design.get('test_plan') or []}
    for ac in spec.get('acceptance_criteria') or []:
        if ac.get('id') not in planned:
            c.problems.append(f"{ac.get('id')}: no test planned for this acceptance criterion")
    c.passed = not c.problems
    c.details = f'{len(files)} files, {prod} production files, {len(planned)} ACs with planned tests'
    return c


# ---------------------------------------------------------------- guards ---------------------------
def split_by_permission(changed: list[str], allowed_kinds: tuple[str, ...]) -> tuple[list[str], list[str]]:
    ok, bad = [], []
    for p in changed:
        (ok if path_kind(p) in allowed_kinds else bad).append(p)
    return ok, bad


def removed_tests(diff_text: str) -> list[str]:
    """Names of test methods that a diff deletes (and does not add back)."""
    # [ \t]* and not \s*: \s would also match a newline, so a removed blank line followed by an
    # unchanged `def test_...` context line was wrongly counted as a deleted test.
    removed = set(re.findall(r'^-[ \t]*def (test\w*)\(', diff_text, re.M))
    added = set(re.findall(r'^\+[ \t]*def (test\w*)\(', diff_text, re.M))
    return sorted(removed - added)


# ---------------------------------------------------------------- stage 3 -------------------------
def _flake8_findings(repo: Path, files: list[str], config: Path) -> list[str]:
    """flake8 messages without line numbers, so that base and head can be compared."""
    if not files:
        return []
    cfg = [f'--config={config}'] if config.is_file() else []
    proc = run([sys.executable, '-m', 'flake8', *cfg, '--format=%(path)s|%(code)s|%(text)s', *files], cwd=repo)
    out = []
    for line in proc.stdout.splitlines():
        if line.count('|') >= 2:
            out.append(line.strip())
    return out


def check_build(repo: Path, base: str, max_diff_lines: int, git) -> Check:
    c = Check('implementation: the code builds', passed=False)
    log = []
    pip = run([sys.executable, '-m', 'pip', 'install', '--quiet', '--no-deps', '-e', '.'], cwd=repo, timeout=600)
    log.append(f'$ pip install -e .  (exit {pip.returncode})\n{truncate(pip.stdout, 2000)}')
    if pip.returncode != 0:
        c.problems.append('pip install -e . failed')
    comp = run([sys.executable, '-m', 'compileall', '-q', 'markdown'], cwd=repo)
    log.append(f'$ python -m compileall -q markdown  (exit {comp.returncode})\n{truncate(comp.stdout, 3000)}')
    if comp.returncode != 0:
        c.problems.append('compileall failed (syntax error)')
    smoke = run([sys.executable, '-c',
                 'import markdown; print(markdown.markdown("# T\\n\\n*a* [b](c)", '
                 'extensions=["extra", "toc", "wikilinks", "abbr", "admonition", "meta"]))'], cwd=repo)
    log.append(f'$ import + convert smoke test  (exit {smoke.returncode})\n{truncate(smoke.stdout, 2000)}')
    if smoke.returncode != 0:
        c.problems.append('importing markdown or converting a small document failed')
    changed_py = [p for p in git.changed_since(base) if p.endswith('.py') and (repo / p).is_file()]
    config = (repo / 'tox.ini').resolve()
    head_f = _flake8_findings(repo, changed_py, config)
    # Pre-existing findings in the same files do not count: compare with the base versions.
    base_f = []
    if changed_py:
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            stash = []
            for p in changed_py:
                src = git.show(base, p)
                if src is not None:
                    dst = Path(tmp) / p
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    dst.write_text(src, encoding='utf-8')
                    stash.append(p)
            base_f = [ln.split('|', 1)[1] for ln in _flake8_findings(Path(tmp), stash, config)]
    new = []
    pool = list(base_f)
    for f in head_f:
        key = f.split('|', 1)[1]
        if key in pool:
            pool.remove(key)
        else:
            new.append(f)
    log.append(f'$ flake8 on changed files: {len(head_f)} findings, {len(new)} new\n' + '\n'.join(new[:30]))
    if new:
        c.problems.append(f'{len(new)} new flake8 findings: ' + '; '.join(new[:8]))
    git.git("add", "-A", "-N")  # make new files visible to git diff
    diff = git.git("diff", base)  # working tree vs base: the check runs before the commit
    n = sum(1 for ln in diff.splitlines() if ln[:1] in '+-' and ln[:3] not in ('+++', '---'))
    if n > max_diff_lines:
        c.problems.append(f'diff has {n} changed lines, more than the limit of {max_diff_lines}')
    if not diff.strip():
        c.problems.append('no code was changed')
    c.passed = not c.problems
    c.details = '\n\n'.join(log)
    return c


# ---------------------------------------------------------------- stage 4 -------------------------
_TEST_LINE = re.compile(r'^(test\w*) \(([\w.]+)\)(?:\n(?!test\w* \()[^\n]*)?? \.\.\. ([^\n]+)$', re.M)


def run_tests(repo: Path, acs: list[dict], timeout: int = 600) -> tuple[Check, dict]:
    c = Check('testing: all new and existing tests pass', passed=False)
    proc = run([sys.executable, '-m', 'unittest', 'discover', '-v', 'tests'], cwd=repo, timeout=timeout)
    out = proc.stdout
    results = []
    for m in _TEST_LINE.finditer(out):
        status = m.group(3).strip()
        norm = 'ok' if status == 'ok' else ('skipped' if status.startswith('skipped') else
                                            'fail' if status.startswith(('FAIL', 'ERROR', 'unexpected')) else status)
        results.append({'name': m.group(1), 'id': m.group(2), 'status': norm})
    ran = re.search(r'^Ran (\d+) tests?', out, re.M)
    summary_line = re.search(r'^(OK.*|FAILED.*)$', out, re.M)
    failing = [r for r in results if r['status'] == 'fail']
    coverage = {}
    for ac in acs:
        num = int(ac['id'].split('-')[1]) if AC_ID.match(ac.get('id', '')) else -1
        pat = re.compile(rf'ac_?0*{num}(?!\d)', re.I)
        hits = [r for r in results if pat.search(r['name'])]
        coverage[ac['id']] = hits
        if not hits:
            c.problems.append(f"{ac['id']}: no test whose name contains ac_{num:03d}")
        elif not all(h['status'] == 'ok' for h in hits):
            c.problems.append(f"{ac['id']}: its test(s) do not pass: " +
                              ', '.join(f"{h['name']}={h['status']}" for h in hits))
    if proc.returncode != 0:
        c.problems.insert(0, f"test suite failed ({summary_line.group(1) if summary_line else 'exit ' + str(proc.returncode)})")
    # Failure/traceback section of unittest output, for feedback to the implementer.
    tb_start = out.find('\n======')
    tracebacks = out[tb_start:] if tb_start >= 0 else ''
    c.passed = not c.problems
    c.details = f"ran {ran.group(1) if ran else '?'} tests: {summary_line.group(1) if summary_line else '?'}"
    report = {
        'exit_code': proc.returncode, 'ran': int(ran.group(1)) if ran else None,
        'summary': summary_line.group(1) if summary_line else None,
        'failing': failing, 'coverage': coverage, 'tracebacks': truncate(tracebacks, 12000),
        'output_tail': truncate(out, 4000, 'start'),
    }
    return c, report
