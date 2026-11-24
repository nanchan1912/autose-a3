"""Render the stage artifacts (spec.md, design.md, test_report.md, pr.md, review.md) as Markdown.
Each artifact ends with the result of its stage check, so a reader can see why the run moved on
or stopped without opening the logs."""
from __future__ import annotations

from .common import run_url, truncate


def _check_block(checks: list[dict]) -> str:
    if not checks:
        return ''
    lines = ['', '## Stage check', '']
    for i, c in enumerate(checks, 1):
        mark = 'PASS' if c['passed'] else ('BLOCKED' if c.get('blocked') else 'FAIL')
        lines.append(f"**Attempt {i}: {mark}** - {c['name']} ({c.get('details', '').splitlines()[0] if c.get('details') else ''})")
        for p in c.get('problems', []):
            lines.append(f'- {p}')
        lines.append('')
    return '\n'.join(lines)


def spec_md(issue: dict, spec: dict, checks: list[dict], stop_reason: str = '') -> str:
    acs = spec.get('acceptance_criteria') or []
    out = [f"# spec.md - issue #{issue['number']}: {spec.get('title') or issue['title']}", '',
           f"Status: **{spec.get('status')}**  ", f"Run: {run_url()}", '',
           '## Summary', '', spec.get('summary', ''), '',
           '## Acceptance criteria', '', '| ID | Given | When | Then | Evidence |', '|---|---|---|---|---|']
    for ac in acs:
        cells = [ac.get(k, '').replace('|', '\\|').replace('\n', ' ') for k in ('id', 'given', 'when', 'then', 'evidence')]
        out.append('| ' + ' | '.join(cells) + ' |')
    qs = spec.get('clarification_questions') or []
    if qs:
        out += ['', '## Clarification questions', '']
        for q in qs:
            out.append(f"- **{q.get('id')}** {q.get('question')}  \n  Why: {q.get('why_it_matters')}  \n"
                       f"  Options: {'; '.join(q.get('options') or [])}  \n  Blocks: {', '.join(q.get('blocks') or [])}")
    if spec.get('untrusted_instructions_seen'):
        out += ['', '## Instructions found in the issue text (ignored)', '']
        out += [f'- {x}' for x in spec['untrusted_instructions_seen']]
    out += ['', '## Full specification', '', spec.get('spec_markdown', '')]
    out.append(_check_block(checks))
    if stop_reason:
        out += ['', '## Run stopped here', '', stop_reason]
    return '\n'.join(out) + '\n'


def design_md(issue: dict, design: dict, checks: list[dict], version: int, stop_reason: str = '') -> str:
    out = [f"# design.md - issue #{issue['number']} (design version {version})", '', f"Run: {run_url()}", '',
           '## Approach', '', design.get('approach', ''), '',
           '## Files and functions to change', '', '| File | Action | Symbols | Change |', '|---|---|---|---|']
    for f in design.get('files') or []:
        syms = ', '.join(f"`{s.get('name')}` ({s.get('status')})" for s in f.get('symbols') or [])
        out.append(f"| `{f.get('path')}` | {f.get('action')} | {syms} | {f.get('change', '').replace('|', '/').replace(chr(10), ' ')} |")
    out += ['', '## Test plan', '', '| AC | Test file | Test name |', '|---|---|---|']
    for t in design.get('test_plan') or []:
        out.append(f"| {t.get('ac_id')} | `{t.get('test_file')}` | `{t.get('test_name')}` |")
    if design.get('architecture_rules'):
        out += ['', '## ARCHITECTURE.md rules that apply', ''] + [f'- {r}' for r in design['architecture_rules']]
    if design.get('risks'):
        out += ['', '## Risks', ''] + [f'- {r}' for r in design['risks']]
    out += ['', '## Design notes', '', design.get('design_markdown', '')]
    out.append(_check_block(checks))
    if stop_reason:
        out += ['', '## Run stopped here', '', stop_reason]
    return '\n'.join(out) + '\n'


def test_report_md(issue: dict, spec: dict, report: dict, check: dict, attempts: list[dict],
                   stop_reason: str = '') -> str:
    out = [f"# test_report.md - issue #{issue['number']}", '', f"Run: {run_url()}", '',
           f"**Result: {'PASS' if check['passed'] else 'FAIL'}** - {check.get('details', '')}", '',
           '## Acceptance criteria and their tests', '', '| AC | Then | Test(s) | Result |', '|---|---|---|---|']
    for ac in spec.get('acceptance_criteria') or []:
        hits = report.get('coverage', {}).get(ac['id'], [])
        tests = '<br>'.join(f"`{h['id']}`" for h in hits) or '(none)'
        res = 'PASS' if hits and all(h['status'] == 'ok' for h in hits) else 'FAIL'
        out.append(f"| {ac['id']} | {ac.get('then', '').replace('|', '/').replace(chr(10), ' ')} | {tests} | {res} |")
    out += ['', '## Full suite', '', f"- tests run: {report.get('ran')}", f"- summary: `{report.get('summary')}`",
            f"- failing: {len(report.get('failing', []))}"]
    for f in report.get('failing', [])[:30]:
        out.append(f"  - `{f['id']}`")
    if check.get('problems'):
        out += ['', '## Problems', ''] + [f'- {p}' for p in check['problems']]
    if attempts:
        out += ['', '## Attempt history', '', '| # | Stage | Outcome |', '|---|---|---|']
        for i, a in enumerate(attempts, 1):
            out.append(f"| {i} | {a['stage']} | {a['outcome']} |")
    if report.get('tracebacks'):
        out += ['', '<details><summary>Failure output</summary>', '', '```', truncate(report['tracebacks'], 8000), '```', '</details>']
    if stop_reason:
        out += ['', '## Run stopped here', '', stop_reason]
    return '\n'.join(out) + '\n'


def pr_body(issue: dict, spec: dict, design: dict, report: dict, diffstat: str, round_no: int) -> str:
    acs = spec.get('acceptance_criteria') or []
    out = [f"Closes #{issue['number']}", '',
           f"Automated change by the **autose** workflow (round {round_no}). "
           "A person must review it and decide whether to merge; the workflow never merges.", '',
           '## What the change should do', '', spec.get('summary', ''), '',
           '## Acceptance criteria', '']
    for ac in acs:
        res = report.get('coverage', {}).get(ac['id'], [])
        ok = res and all(h['status'] == 'ok' for h in res)
        out.append(f"- [{'x' if ok else ' '}] **{ac['id']}** {ac.get('then', '')}")
    out += ['', '## Files', '', '```', diffstat.strip(), '```', '',
            f"Tests: `{report.get('summary')}` ({report.get('ran')} tests run).", '',
            f"Stage artifacts (spec.md, design.md, diff.patch, test_report.md, agent transcripts): {run_url()}"]
    return '\n'.join(out) + '\n'


def review_md(pr: dict, review: dict, facts: dict, final_verdict: str, route: str, model: str) -> str:
    out = [f"# review.md - PR #{pr['number']}", '',
           f"Reviewer model: `{model}` | Verdict: **{final_verdict.replace('_', ' ').upper()}**"
           + (f" | send back to: **{route}**" if final_verdict == 'request_changes' else ''), '',
           f"Run: {run_url()}", '', '## Summary', '', review.get('summary', ''), '']
    if facts.get('overrides'):
        out += ['## Deterministic checks that changed the verdict', ''] + [f'- {x}' for x in facts['overrides']] + ['']
    out += ['## Does the change do what the issue asks?', '', '| Requirement (from the issue) | Met | Evidence |', '|---|---|---|']
    for r in review.get('issue_requirements') or []:
        out.append(f"| {r.get('requirement', '').replace('|', '/')} | {r.get('met')} | {r.get('evidence', '').replace('|', '/').replace(chr(10), ' ')} |")
    out += ['', '## Findings', '']
    findings = review.get('findings') or []
    if not findings:
        out.append('No findings.')
    for f in findings:
        loc = f"`{f.get('file')}`" + (f":{f.get('line')}" if f.get('line') else '')
        out += [f"### {f.get('id')} [{f.get('severity')}] {f.get('category')} - {loc}", '',
                f.get('description', ''), '', f"Evidence: {f.get('evidence', '')}", '',
                f"Suggested fix: {f.get('suggested_fix', '')}", f"Route: {f.get('route')}", '']
    out += ['## What the reviewer ran', '']
    for c in review.get('checks_run') or []:
        out.append(f"- `{truncate(c.get('command', ''), 200, 'end')}` -> {truncate(c.get('outcome', ''), 300, 'end')}")
    out += ['', f"Independent facts gathered by the review job: suite `{facts.get('suite_summary')}`, "
            f"{facts.get('files_changed')} files changed, removed tests: {facts.get('removed_tests') or 'none'}."]
    return '\n'.join(out) + '\n'
