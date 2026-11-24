"""Stages 1-4 as a small state machine.

The orchestrator (this code) decides every transition. Agents only produce artifacts; a stage moves
on only when its deterministic check passes. Failures move work back to an earlier stage within
fixed budgets:

    requirements --check--> design --check--> implement --build check--> test --tests pass--> done
         |  retry once           |  retry once       ^  retry (max 3 per design) |
         v                       v                   |---------------------------| failing tests
       BLOCKED: ask people     stop                  design revision (max 1) <---- still failing
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from . import checks, render, schemas
from .claude import Ledger, run_agent
from .common import log, truncate, write_json, write_text
from .config import PROMPTS_DIR
from .gitops import Repo
from .untrusted import wrap


def system_prompt(*names: str) -> str:
    return '\n\n'.join((PROMPTS_DIR / n).read_text(encoding='utf-8') for n in ('common.md',) + names)


def issue_block(issue: dict) -> str:
    parts = [f"Issue #{issue['number']}: {issue['title']}", '', wrap('issue', issue['body'])]
    for c in issue.get('maintainer_comments', []):
        parts += ['', f"Comment by maintainer @{c['author']} ({c['created_at']}):", wrap('maintainer-comment', c['body'])]
    return '\n'.join(parts)


def spec_block(spec: dict) -> str:
    acs = '\n'.join(f"- {a['id']} ({a.get('evidence')}): GIVEN {a['given']} WHEN {a['when']} THEN {a['then']}"
                    for a in spec.get('acceptance_criteria', []))
    return f"## Specification (spec.md)\n\nStatus: {spec.get('status')}\n\n{spec.get('summary', '')}\n\n" \
           f"### Acceptance criteria\n{acs}\n\n### Full specification\n{spec.get('spec_markdown', '')}"


def design_block(design: dict) -> str:
    files = '\n'.join(f"- {f['path']} ({f['action']}): " + ', '.join(f"{s['name']} [{s['status']}]" for s in f.get('symbols', []))
                      + f" - {f.get('change', '')}" for f in design.get('files', []))
    tests = '\n'.join(f"- {t['ac_id']}: {t['test_file']}::{t['test_name']}" for t in design.get('test_plan', []))
    return f"## Design (design.md)\n\n{design.get('approach', '')}\n\n### Files and symbols\n{files}\n\n" \
           f"### Test plan\n{tests}\n\n### Notes\n{design.get('design_markdown', '')}"


def findings_block(review: dict) -> str:
    lines = ['## Review findings to address (from the independent reviewer)']
    for f in review.get('findings', []):
        if f.get('severity') in ('blocking', 'major'):
            lines.append(f"- [{f['severity']}] {f.get('file')}:{f.get('line')} {f.get('description')}\n"
                         f"  Evidence: {f.get('evidence')}\n  Suggested fix: {f.get('suggested_fix')}")
    for o in review.get('_overrides', []):
        lines.append(f'- [deterministic] {o}')
    return '\n'.join(lines)


@dataclass
class Outcome:
    status: str                     # ready | stopped
    stopped_at: str = ''
    reason: str = ''
    history: list = field(default_factory=list)


class Build:
    def __init__(self, *, issue: dict, variant: dict, work: Path, art: Path, base: str,
                 ledger: Ledger, round_no: int, spec: dict | None = None, design: dict | None = None,
                 review: dict | None = None):
        self.issue, self.variant, self.work, self.art = issue, variant, Path(work), Path(art)
        self.repo = Repo(work)
        self.base = base
        self.ledger = ledger
        self.round = round_no
        self.limits = variant['limits']
        self.spec, self.design, self.review = spec, design, review
        self.logs = self.art / 'logs'
        self.history: list[dict] = []
        self.checks: dict[str, list] = {'requirements': [], 'design': [], 'implement': [], 'test': []}
        self.calls = 0
        self.impl_notes = ''
        self.test_report: dict = {}

    # -- helpers ---------------------------------------------------------------------------------
    def agent(self, role: str, stage: str, system: str, prompt: str, schema: dict):
        self.calls += 1
        cfg_role = 'implementer' if (role == 'tester' and self.variant['tester_mode'] == 'implementer') else role
        call_id = f"r{self.round}-{self.calls:02d}-{stage}-{role}"
        return run_agent(role=role, role_cfg=self.variant['roles'][cfg_role], call_id=call_id,
                         system_prompt=system, user_prompt=prompt, schema=schema, cwd=self.work,
                         log_dir=self.logs, ledger=self.ledger)

    def note(self, stage: str, outcome: str, **extra):
        row = {'round': self.round, 'stage': stage, 'outcome': outcome, **extra}
        self.history.append(row)
        log(f"[{stage}] {outcome}")
        write_json(self.art / 'history.json', self.history)

    def stop(self, stage: str, reason: str) -> Outcome:
        self.note(stage, f'STOP: {reason}')
        return Outcome('stopped', stage, reason, self.history)

    def guard(self, since: str, allowed: tuple[str, ...], who: str) -> list[str]:
        """Revert changes the agent was not allowed to make; return the reverted paths."""
        changed = self.repo.changed_since(since)
        _, bad = checks.split_by_permission(changed, allowed)
        if bad:
            self.repo.revert(bad, since)
            self.note('guard', f'reverted {who} changes outside its area: {", ".join(bad)}')
        return bad

    def write_spec(self, stop_reason=''):
        write_text(self.art / 'spec.md', render.spec_md(self.issue, self.spec or {}, self.checks['requirements'], stop_reason))
        write_json(self.art / 'spec.json', self.spec or {})

    def write_design(self, version, stop_reason=''):
        write_text(self.art / 'design.md', render.design_md(self.issue, self.design or {}, self.checks['design'], version, stop_reason))
        write_json(self.art / 'design.json', self.design or {})

    def write_diff(self):
        write_text(self.art / 'diff.patch', self.repo.diff(self.base))

    # -- stages ----------------------------------------------------------------------------------
    def requirements(self, feedback: str) -> dict | None:
        prompt = issue_block(self.issue)
        if feedback:
            prompt += f"\n\n## Your previous specification failed the testability check\n{feedback}\nFix these problems."
        prompt += '\n\nWrite the specification for this issue.'
        sysp = system_prompt('requirements.md', 'a1_requirements_skill.md')
        res = self.agent('analyst', 'requirements', sysp, prompt, schemas.SPEC)
        return res.structured if res.ok else None

    def make_design(self, feedback: str) -> dict | None:
        prompt = issue_block(self.issue) + '\n\n' + spec_block(self.spec)
        if self.design and feedback:
            prompt += '\n\n## Previous design\n' + design_block(self.design)
        if feedback:
            prompt += f"\n\n## Feedback on the previous attempt\n{feedback}"
        prompt += '\n\nRead ARCHITECTURE.md and the relevant code, then write the design.'
        res = self.agent('analyst', 'design', system_prompt('design.md'), prompt, schemas.DESIGN)
        return res.structured if res.ok else None

    def implement(self, feedback: str) -> tuple[bool, list]:
        prompt = spec_block(self.spec) + '\n\n' + design_block(self.design)
        if feedback:
            prompt += f"\n\n## Feedback from the previous attempt\n{feedback}"
        prompt += '\n\nImplement the change now.'
        res = self.agent('implementer', 'implement', system_prompt('implement.md'), prompt, schemas.IMPLEMENTATION)
        if res.ok:
            self.impl_notes = json.dumps(res.structured, indent=2)
            return True, res.structured.get('test_disputes') or []
        return False, []

    def write_tests(self, feedback: str) -> bool:
        changed = self.repo.files_between(self.base)
        prompt = spec_block(self.spec) + '\n\n### Test plan from the design\n' + \
            '\n'.join(f"- {t['ac_id']}: {t['test_file']}::{t['test_name']}" for t in self.design.get('test_plan', [])) + \
            '\n\n### Files changed by the implementation\n' + '\n'.join(f'- {p}' for p in changed)
        if self.variant['tester_mode'] == 'implementer':
            sysp = system_prompt('implement.md', 'test_self.md')
            prompt += '\n\n### Your own implementation notes\n' + self.impl_notes
        else:
            sysp = system_prompt('test.md')
        if feedback:
            prompt += f"\n\n## Feedback\n{feedback}"
        prompt += '\n\nWrite the tests now and run them.'
        res = self.agent('tester', 'test', sysp, prompt, schemas.TESTS)
        return res.ok

    # -- the state machine -----------------------------------------------------------------------
    def run(self, start: str, review_feedback: str = '') -> Outcome:
        L = self.limits
        stage = start
        feedback = {'requirements': '', 'design': '', 'implement': '', 'test': ''}
        if review_feedback:
            feedback[stage] = review_feedback
        spec_tries = design_tries = 0
        design_version = 1 if self.design else 0
        impl_tries = 0
        revisions = 0
        tester_fixes = 0
        # Tests already on the branch are kept when a review sends work back to implementation only.
        tests_written = (start == 'implement')
        disputes: list = []

        while True:
            if self.ledger.remaining() < 0.25:
                return self.stop(stage, f'budget exhausted (job ${self.ledger.job_spent:.2f}, '
                                        f'limits job ${L["job_budget_usd"]} / run ${L["run_budget_usd"]})')

            if stage == 'requirements':
                spec_tries += 1
                spec = self.requirements(feedback['requirements'])
                if spec is None:
                    if spec_tries < L['spec_attempts']:
                        self.note(stage, 'agent failed, retrying')
                        continue
                    self.write_spec('The requirements agent did not produce a specification.')
                    return self.stop(stage, 'the requirements agent did not produce a specification')
                self.spec = spec
                chk = checks.check_spec(spec)
                self.checks['requirements'].append(chk.as_dict())
                if chk.blocked:
                    self.write_spec('The specification is BLOCKED: the issue does not say enough to write testable '
                                    'acceptance criteria. The clarification questions above were posted on the issue. '
                                    'Answer them in a comment and start the workflow again with `/autose`.')
                    return self.stop(stage, 'needs clarification from a maintainer (spec BLOCKED)')
                if not chk.passed:
                    if spec_tries < L['spec_attempts']:
                        feedback['requirements'] = chk.feedback()
                        self.note(stage, 'check failed, retrying with feedback', problems=chk.problems)
                        continue
                    self.write_spec('The acceptance criteria are still not testable after a retry:\n' + chk.feedback())
                    return self.stop(stage, 'acceptance criteria not testable')
                self.write_spec()
                self.note(stage, 'PASS', acs=len(spec['acceptance_criteria']))
                stage = 'design'

            elif stage == 'design':
                design_tries += 1
                design = self.make_design(feedback['design'])
                if design is None:
                    if design_tries < L['design_attempts']:
                        continue
                    return self.stop(stage, 'the design agent did not produce a design')
                self.design = design
                chk = checks.check_design(design, self.spec, self.work)
                self.checks['design'].append(chk.as_dict())
                if not chk.passed:
                    if design_tries < L['design_attempts']:
                        feedback['design'] = 'The design failed the check:\n' + chk.feedback()
                        self.note(stage, 'check failed, retrying with feedback', problems=chk.problems)
                        continue
                    self.write_design(design_version + 1, 'The design still fails its check:\n' + chk.feedback())
                    return self.stop(stage, 'design does not name valid files and functions')
                design_version += 1
                design_tries = 0
                self.write_design(design_version)
                self.note(stage, f'PASS (design v{design_version})')
                impl_tries = 0
                if design_version > 1:
                    tests_written = False  # a revised design may need revised tests
                stage = 'implement'

            elif stage == 'implement':
                impl_tries += 1
                before = self.repo.head()
                ok, disputes = self.implement(feedback['implement'])
                reverted = self.guard(before, ('production',), 'implementer')
                chk = checks.check_build(self.work, self.base, L['max_diff_lines'], self.repo)
                if reverted:
                    chk.problems.append('changes outside production code were reverted: ' + ', '.join(reverted))
                self.checks['implement'].append(chk.as_dict())
                self.repo.commit_all(f"autose(#{self.issue['number']}): implementation r{self.round} "
                                     f"design v{design_version} attempt {impl_tries}")
                self.write_diff()
                write_text(self.art / 'build_check.md', f"# Build check (attempt {impl_tries})\n\n"
                           + ('PASS' if chk.passed else 'FAIL\n\n' + chk.feedback()) + '\n\n```\n' + chk.details + '\n```\n')
                if not ok and not chk.passed:
                    chk.problems.insert(0, 'the implementer agent did not finish')
                if not chk.passed:
                    if impl_tries < L['impl_attempts_per_design']:
                        feedback['implement'] = 'The build check failed:\n' + chk.feedback() + '\n\n' + truncate(chk.details, 4000)
                        self.note(stage, 'build check failed, retrying', problems=chk.problems)
                        continue
                    if revisions < L['design_revisions']:
                        revisions += 1
                        feedback['design'] = 'Implementing this design repeatedly failed the build check:\n' + chk.feedback()
                        self.note(stage, 'build keeps failing, back to design')
                        stage = 'design'
                        continue
                    return self.stop(stage, 'the code does not build: ' + '; '.join(chk.problems[:3]))
                self.note(stage, f'PASS (attempt {impl_tries})')
                feedback['implement'] = ''
                stage = 'test'

            elif stage == 'test':
                if not tests_written or disputes or feedback['test']:
                    before = self.repo.head()
                    fb = feedback['test']
                    if disputes:
                        fb += '\n\n## test_disputes from the implementer\n' + json.dumps(disputes, indent=2)
                    self.write_tests(fb)
                    self.guard(before, ('test',), 'tester')
                    deleted = checks.removed_tests(self.repo.git('diff', before))
                    if deleted:
                        self.repo.revert(self.repo.changed_since(before), before)
                        self.note(stage, f'tester deleted existing tests {deleted}; its changes were reverted')
                        if tester_fixes < L['tester_fix_rounds']:
                            tester_fixes += 1
                            feedback['test'] = f'You deleted existing tests ({", ".join(deleted)}). That is not allowed.'
                            continue
                        return self.stop(stage, 'the tester deleted existing tests')
                    self.repo.commit_all(f"autose(#{self.issue['number']}): tests r{self.round}")
                    tests_written = True
                    disputes = []
                    feedback['test'] = ''
                chk, report = checks.run_tests(self.work, self.spec['acceptance_criteria'], L['test_timeout_s'])
                self.test_report = report
                self.checks['test'].append(chk.as_dict())
                self.write_diff()
                write_json(self.art / 'test_results.json', report)
                if chk.passed:
                    self.note(stage, f'PASS ({report.get("summary")})')
                    write_text(self.art / 'test_report.md', render.test_report_md(self.issue, self.spec, report, chk.as_dict(), self.history))
                    return Outcome('ready', history=self.history)
                # Missing AC tests, or failures inside the new tests that look like broken tests -> tester.
                missing = [p for p in chk.problems if 'no test whose name' in p]
                broken_tests = 'ImportError' in report.get('tracebacks', '') or 'SyntaxError' in report.get('tracebacks', '')
                if (missing or broken_tests) and tester_fixes < L['tester_fix_rounds']:
                    tester_fixes += 1
                    feedback['test'] = 'The test check failed:\n' + chk.feedback() + '\n\n' + truncate(report.get('tracebacks', ''), 4000)
                    self.note(stage, 'tests missing or broken, back to the tester')
                    continue
                failure = 'The tests fail:\n' + chk.feedback() + '\n\n' + truncate(report.get('tracebacks', ''), 6000)
                if impl_tries < L['impl_attempts_per_design']:
                    feedback['implement'] = failure
                    self.note(stage, 'tests fail, back to implementation', problems=chk.problems[:5])
                    stage = 'implement'
                    continue
                if revisions < L['design_revisions']:
                    revisions += 1
                    feedback['design'] = 'The implementation of this design keeps failing its tests:\n' + truncate(failure, 5000)
                    self.note(stage, 'tests keep failing, back to design')
                    stage = 'design'
                    continue
                write_text(self.art / 'test_report.md', render.test_report_md(
                    self.issue, self.spec, report, chk.as_dict(), self.history,
                    'Tests still fail after all implementation retries and a design revision.'))
                return self.stop(stage, 'tests still fail after all retries')
            else:
                raise ValueError(stage)
