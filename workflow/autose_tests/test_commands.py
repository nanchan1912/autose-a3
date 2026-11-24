"""Offline tests for the gate (who may start what) and finalize (outcome logic), with a fake GitHub."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from autose import __main__ as cli


class FakeGitHub:
    repo = 'me/markdown'

    def __init__(self, perm='admin', pr_head_repo='me/markdown', pr_state='open', issue_state='open'):
        self.perm, self.pr_head_repo, self.pr_state, self.issue_state = perm, pr_head_repo, pr_state, issue_state
        self.comments, self.removed = [], []

    def permission(self, user):
        return self.perm

    def comment(self, number, body):
        self.comments.append((str(number), body))

    def remove_label(self, number, label):
        self.removed.append((str(number), label))

    def issue(self, number):
        return {'number': int(number), 'state': self.issue_state, 'title': 't', 'body': 'b',
                'user': {'login': 'u'}, 'html_url': ''}

    def pr(self, number):
        head = {'repo': {'full_name': self.pr_head_repo} if self.pr_head_repo else None, 'sha': 'h' * 40, 'ref': 'x'}
        return {'number': int(number), 'state': self.pr_state, 'head': head, 'body': 'Closes #3', 'title': 'x'}


class GateTests(unittest.TestCase):

    def gate(self, event_name, event, fake):
        with tempfile.TemporaryDirectory() as tmp:
            ev, out = Path(tmp) / 'event.json', Path(tmp) / 'out'
            ev.write_text(json.dumps(event))
            env = {'GITHUB_EVENT_PATH': str(ev), 'GITHUB_EVENT_NAME': event_name, 'GITHUB_OUTPUT': str(out)}
            with mock.patch.dict(os.environ, env), mock.patch.object(cli, 'gh', return_value=fake):
                cli.cmd_gate(None)
            text = out.read_text()
        values = {}
        lines = text.splitlines()
        for i, line in enumerate(lines):
            if '<<EOF_' in line:
                values[line.split('<<')[0]] = lines[i + 1] if not lines[i + 1].startswith('EOF_') else ''
        return values

    def comment_event(self, body, assoc='OWNER', pr=False):
        issue = {'number': 3, **({'pull_request': {}} if pr else {})}
        return {'comment': {'body': body, 'user': {'login': 'me', 'type': 'User'}, 'author_association': assoc},
                'issue': issue}

    def test_label_by_maintainer_starts_full_run(self):
        fake = FakeGitHub()
        out = self.gate('issues', {'label': {'name': 'autose'}, 'sender': {'login': 'me'}, 'issue': {'number': 3}}, fake)
        self.assertEqual((out['run'], out['mode'], out['issue']), ('true', 'full', '3'))
        self.assertEqual(len(fake.comments), 1)

    def test_comment_from_outsider_is_ignored_silently(self):
        fake = FakeGitHub()
        out = self.gate('issue_comment', self.comment_event('/autose', assoc='NONE'), fake)
        self.assertEqual(out['run'], 'false')
        self.assertEqual(fake.comments, [])

    def test_read_only_collaborator_is_refused(self):
        out = self.gate('issue_comment', self.comment_event('/autose'), FakeGitHub(perm='read'))
        self.assertEqual(out['run'], 'false')

    def test_comment_on_pr_starts_review_with_linked_issue(self):
        out = self.gate('issue_comment', self.comment_event('/autose variant=E1-same-model', pr=True), FakeGitHub())
        self.assertEqual((out['run'], out['mode'], out['pr'], out['issue'], out['variant']),
                         ('true', 'review', '3', '3', 'E1-same-model'))

    def test_fork_pr_is_refused(self):
        out = self.gate('issue_comment', self.comment_event('/autose', pr=True), FakeGitHub(pr_head_repo='evil/markdown'))
        self.assertEqual(out['run'], 'false')

    def test_unknown_variant_is_refused(self):
        out = self.gate('issue_comment', self.comment_event('/autose variant=nope'), FakeGitHub())
        self.assertEqual(out['run'], 'false')

    def test_other_comment_is_not_a_command(self):
        out = self.gate('issue_comment', self.comment_event('thanks! /autose is cool'), FakeGitHub())
        self.assertEqual(out['run'], 'false')


class FinalizeTests(unittest.TestCase):

    def run_finalize(self, files, mode='full'):
        fake = FakeGitHub()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'all'
            for rel, data in files.items():
                p = root / rel
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(json.dumps(data))
            args = mock.Mock(artifacts=str(root), out=str(Path(tmp) / 'o'), issue='3', pr='', mode=mode,
                             variant='default', needs='{}')
            with mock.patch.object(cli, 'gh', return_value=fake):
                cli.cmd_finalize(args)
            summary = json.loads((Path(tmp) / 'o' / 'run_summary.json').read_text())
        return summary, fake

    def test_blocked_spec_posts_questions(self):
        files = {'autose-build-r0/state.json': {'status': 'stopped', 'stopped_at': 'requirements',
                                                 'reason': 'needs clarification', 'history': [], 'start': 'requirements'},
                 'autose-build-r0/spec.json': {'clarification_questions': [
                     {'question': 'Which pages fail?', 'why_it_matters': 'x', 'options': ['a', 'b']}]}}
        summary, fake = self.run_finalize(files)
        self.assertEqual(summary['outcome'], 'stopped_at_requirements')
        self.assertIn('Which pages fail?', fake.comments[0][1])
        self.assertIn(('3', 'autose'), fake.removed)

    def test_rounds_used_up(self):
        files = {}
        for k in range(3):
            files[f'autose-build-r{k}/state.json'] = {'status': 'ready', 'history': [], 'start': 'implement'}
            files[f'autose-release-r{k}/release_check.json'] = {'passed': True, 'pr': 9}
            files[f'autose-review-r{k}/review.json'] = {'final_verdict': 'request_changes', 'pr': 9, 'review': {}}
        summary, fake = self.run_finalize(files)
        self.assertEqual(summary['outcome'], 'rounds_used_up')
        self.assertEqual(summary['pr'], 9)
        self.assertEqual({c[0] for c in fake.comments}, {'3', '9'})

    def test_approved(self):
        files = {'autose-build-r0/state.json': {'status': 'ready', 'history': []},
                 'autose-release-r0/release_check.json': {'passed': True, 'pr': 9},
                 'autose-review-r0/review.json': {'final_verdict': 'approve', 'pr': 9, 'review': {}},
                 'autose-build-r0/ledger.json': {'totals': {'input_tokens': 10, 'output_tokens': 5, 'cost_usd': 0.5, 'calls': 2}}}
        summary, _ = self.run_finalize(files)
        self.assertEqual(summary['outcome'], 'approved')
        self.assertEqual(summary['tokens']['cost_usd'], 0.5)


if __name__ == '__main__':
    unittest.main()
