"""Command line used by the workflow steps:  python -m autose <command> [options]

Commands that talk to GitHub (gate, fetch-issue, release, release-check, review-prepare,
review-post, finalize) run in steps that get a GITHUB_TOKEN. Commands that run agents (build,
review) run in steps that get only the model API key, so no agent process can see a GitHub token.
"""
from __future__ import annotations

import argparse
import base64
import datetime as dt
import glob
import hashlib
import json
import os
import re
import sys
from pathlib import Path

from . import checks, render, schemas, untrusted
from .claude import Ledger, run_agent
from .common import (log, read_json, run, run_url, set_output, step_summary, truncate, write_json,
                     write_text)
from .config import known_variants, load_variant
from .gitops import Repo

TRUSTED_ASSOC = {'OWNER', 'MEMBER', 'COLLABORATOR'}
WRITE_ROLES = {'admin', 'maintain', 'write'}
COMMAND_RE = re.compile(r'^/autose(?:\s+(?P<args>[^\n]*))?$', re.M)


def gh():
    from .ghapi import GitHub
    return GitHub()


# ================================================================ gate ==========================
def cmd_gate(a):
    """Decide whether this event may start a run, and in which mode. Posts an acknowledgement."""
    event = read_json(os.environ['GITHUB_EVENT_PATH'], {})
    name = os.environ.get('GITHUB_EVENT_NAME')
    g = gh()
    out = {'run': 'false', 'mode': '', 'issue': '', 'pr': '', 'variant': 'default', 'actor': '', 'reason': ''}

    def reject(reason, number=None, tell=False):
        out['reason'] = reason
        log(f'gate: not running: {reason}')
        if tell and number:
            g.comment(number, f'autose did not start: {reason}')
        set_output(**out)
        step_summary(f'### autose gate\nNot running: {reason}')

    if name == 'workflow_dispatch':
        inputs = event.get('inputs', {})
        actor, number, mode, variant = event.get('sender', {}).get('login', ''), inputs.get('number', ''), \
            inputs.get('mode', 'full'), inputs.get('variant') or 'default'
        is_pr = mode == 'review'
    elif name == 'issues':
        if event.get('label', {}).get('name') != 'autose':
            return reject('label is not "autose"')
        actor, number, mode, variant = event['sender']['login'], str(event['issue']['number']), 'full', 'default'
        is_pr = 'pull_request' in event['issue']
    elif name == 'issue_comment':
        comment = event['comment']
        m = COMMAND_RE.search(comment.get('body', '').strip().splitlines()[0] if comment.get('body') else '')
        if not m:
            return reject('comment is not an /autose command')
        if comment['user'].get('type') == 'Bot':
            return reject('comment by a bot')
        actor, number = comment['user']['login'], str(event['issue']['number'])
        if comment.get('author_association') not in TRUSTED_ASSOC:
            return reject(f'{actor} is not a maintainer of this repository (association '
                          f'{comment.get("author_association")})')
        is_pr = 'pull_request' in event['issue']
        args = (m.group('args') or '').split()
        mode = 'review' if is_pr else 'full'
        if 'review' in args and not is_pr:
            return reject('`/autose review` only works on a pull request', number, tell=True)
        variant = next((x.split('=', 1)[1] for x in args if x.startswith('variant=')), 'default')
    else:
        return reject(f'unsupported event {name}')

    perm = g.permission(actor)
    if perm is not None and perm not in WRITE_ROLES:
        return reject(f'{actor} has {perm} permission; write access is needed to start autose')
    if variant not in known_variants():
        return reject(f'unknown variant {variant!r}; known: {", ".join(known_variants())}', number, tell=True)

    if mode == 'review':
        pr = g.pr(number)
        if pr['head']['repo'] is None or pr['head']['repo']['full_name'] != g.repo:
            return reject('pull requests from forks are not reviewed: their code would run in a job that '
                          'holds the model API key', number, tell=True)
        if pr['state'] != 'open':
            return reject('the pull request is not open', number, tell=True)
        linked = re.search(r'(?i)\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?|refs?)\s+#(\d+)', pr.get('body') or '')
        out.update(pr=number, issue=linked.group(1) if linked else '')
    else:
        issue = g.issue(number)
        if is_pr:
            return reject('the full pipeline starts from an issue, not a pull request', number, tell=True)
        if issue['state'] != 'open':
            return reject('the issue is closed', number, tell=True)
        out.update(issue=number)

    out.update(run='true', mode=mode, variant=variant, actor=actor, reason='ok')
    set_output(**out)
    try:  # the acknowledgement is cosmetic; it must never block the run
        g.comment(number, f"autose run started by @{actor} (mode `{mode}`, variant `{variant}`).\n\n"
                          f"Follow it here: {run_url()}\n\n"
                          "Every stage uploads its artifact (spec.md, design.md, diff.patch, test_report.md, pr.md, "
                          "review.md) to the run. A person decides whether to merge; autose never merges.")
    except Exception as e:
        log(f'could not post the acknowledgement comment: {e}')
    step_summary(f"### autose gate\nStarted by `{actor}`: mode `{mode}`, variant `{variant}`, "
                 f"issue `{out['issue']}`, PR `{out['pr']}`")


# ================================================================ issue ==========================
def load_issue(g, number, max_chars=12000) -> dict:
    issue = g.issue(number)
    body, notes = untrusted.clean(issue.get('body') or '', max_chars)
    title, tnotes = untrusted.clean(issue.get('title') or '', 300)
    comments = []
    for c in g.comments(number):
        text = c.get('body') or ''
        if c.get('author_association') not in TRUSTED_ASSOC or c['user'].get('type') == 'Bot':
            continue
        if text.strip().startswith('/autose') or 'autose run started' in text:
            continue
        cb, cnotes = untrusted.clean(text, 4000)
        comments.append({'author': c['user']['login'], 'created_at': c['created_at'], 'body': cb})
        notes += [f'maintainer comment: {n}' for n in cnotes]
    hits = untrusted.scan(title + '\n' + body + '\n' + '\n'.join(c['body'] for c in comments))
    return {
        'number': issue['number'], 'title': title, 'body': body, 'author': issue['user']['login'],
        'author_association': issue.get('author_association'), 'url': issue['html_url'],
        'maintainer_comments': comments, 'cleaning_notes': notes + tnotes, 'injection_flags': hits,
        'blocked_by_injection': any(h['risk'] == 'high' for h in hits),
        'body_sha256': hashlib.sha256(body.encode()).hexdigest(),
        'fetched_at': dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds'),
    }


def cmd_fetch_issue(a):
    data = load_issue(gh(), a.issue)
    write_json(a.out, data)
    set_output(injection='high' if data['blocked_by_injection'] else ('flagged' if data['injection_flags'] else 'none'))
    log(f"issue #{data['number']}: {len(data['body'])} chars, {len(data['maintainer_comments'])} maintainer comments, "
        f"flags={data['injection_flags']}")


# ================================================================ build (stages 1-4) =============
def cmd_build(a):
    from .pipeline import Build, findings_block

    variant = load_variant(a.variant)
    art = Path(a.out)
    art.mkdir(parents=True, exist_ok=True)
    work = Path(a.work).resolve()
    repo = Repo(work)
    issue = read_json(a.issue_json)
    prev = Path(a.prev) if a.prev else None
    prior_ledgers = [p for p in glob.glob(str(Path(a.prior_ledgers) / '**' / 'ledger.json'), recursive=True)] \
        if a.prior_ledgers else []
    ledger = Ledger(art / 'ledger.json', variant['limits']['job_budget_usd'], variant['limits']['run_budget_usd'],
                    prior_spent=Ledger.spent_in(prior_ledgers))
    ledger.save()

    # Each variant gets its own branch and PR, so experiment runs on the same issue do not overwrite each other.
    branch = f"autose/issue-{issue['number']}" + ('' if variant['name'] == 'default' else f"-{variant['name']}")
    default = os.environ.get('AUTOSE_DEFAULT_BRANCH', 'main')
    if a.round == 0:
        repo.git('checkout', '-q', '-B', branch)
        base = repo.head()
    else:
        base = repo.git('merge-base', f'origin/{default}', 'HEAD').strip()

    spec = read_json(prev / 'spec.json') if prev else None
    design = read_json(prev / 'design.json') if prev else None
    review = read_json(a.review) if a.review else None
    review = review.get('review', review) if review else None  # review.json wraps the agent output
    start = a.resume_from or 'requirements'
    write_json(art / 'meta.json', {'issue': issue['number'], 'round': a.round, 'variant': variant['name'],
                                   'start': start, 'base': base, 'branch': branch, 'run': run_url(),
                                   'models': {r: c['model'] for r, c in variant['roles'].items()}})
    write_json(art / 'issue.json', issue)

    b = Build(issue=issue, variant=variant, work=work, art=art, base=base, ledger=ledger, round_no=a.round,
              spec=spec, design=design, review=review)
    if issue.get('blocked_by_injection'):
        from .pipeline import Outcome
        reason = ('the issue text contains high-risk instructions aimed at the automation '
                  f"({', '.join(h['match'] for h in issue['injection_flags'] if h['risk'] == 'high')}); "
                  'a maintainer must edit the issue before autose can run')
        b.note('requirements', f'STOP: {reason}')
        outcome = Outcome('stopped', 'requirements', reason, b.history)
        write_text(art / 'spec.md', f"# spec.md - issue #{issue['number']}\n\nNot written: {reason}\n")
    else:
        # Carry spec and design forward so that every round's artifact set is complete.
        for name in ('spec.json', 'spec.md', 'design.json', 'design.md'):
            if prev and (prev / name).exists() and start != 'requirements':
                write_text(art / name, (prev / name).read_text(encoding='utf-8'))
        outcome = b.run(start, findings_block(review) if review else '')

    state = {'status': outcome.status, 'stopped_at': outcome.stopped_at, 'reason': outcome.reason,
             'round': a.round, 'variant': variant['name'], 'start': start, 'history': outcome.history,
             'checks': b.checks, 'ledger': ledger.totals(), 'base': base, 'head': repo.head(), 'branch': branch}
    write_json(art / 'state.json', state)
    set_output(status=outcome.status, stopped_at=outcome.stopped_at, reason=outcome.reason, branch=branch,
               base=base, head=repo.head())
    rows = '\n'.join(f"| {h['stage']} | {h['outcome']} |" for h in outcome.history)
    step_summary(f"### autose build, round {a.round} (variant `{variant['name']}`)\n\n| Stage | Outcome |\n|---|---|\n{rows}\n\n"
                 f"Result: **{outcome.status}** {outcome.reason}  \nCost this job: ${ledger.job_spent:.2f}")


# ================================================================ release (stage 5) =============
def _push(repo: Repo, branch: str, force: bool):
    token = os.environ['GH_TOKEN']
    server = os.environ.get('GITHUB_SERVER_URL', 'https://github.com')
    basic = base64.b64encode(f'x-access-token:{token}'.encode()).decode()
    # The credential goes in through GIT_CONFIG_* variables, never on the command line, so it cannot
    # appear in an error message (the base64 form would not be masked in the Actions log).
    env = {**os.environ, 'GIT_CONFIG_COUNT': '1', 'GIT_CONFIG_KEY_0': f'http.{server}/.extraheader',
           'GIT_CONFIG_VALUE_0': f'AUTHORIZATION: basic {basic}', 'GIT_TERMINAL_PROMPT': '0'}
    cmd = ['git', 'push', '--quiet'] + (['--force'] if force else []) + ['origin', f'HEAD:refs/heads/{branch}']
    proc = run(cmd, cwd=repo.path, timeout=300, env=env)
    if proc.returncode != 0:
        raise SystemExit('git push failed: ' + proc.stdout.replace(token, '***').replace(basic, '***')[-2000:])


def cmd_release(a):
    g = gh()
    art = Path(a.art)
    repo = Repo(Path(a.work).resolve())
    state = read_json(art / 'state.json')
    issue = read_json(art / 'issue.json')
    prev = Path(a.prev) if a.prev else None
    spec = read_json(art / 'spec.json') or (read_json(prev / 'spec.json', {}) if prev else {})
    design = read_json(art / 'design.json') or (read_json(prev / 'design.json', {}) if prev else {})
    report = read_json(art / 'test_results.json', {})
    branch = state['branch']
    default = os.environ.get('AUTOSE_DEFAULT_BRANCH', 'main')
    _push(repo, branch, force=(a.round == 0))
    head = repo.head()
    body = render.pr_body(issue, spec, design, report, repo.diff_stat(state['base']), a.round)
    body = untrusted.no_mentions(body)
    title = f"[autose] {issue['title']} (#{issue['number']})"[:250]
    pr = g.find_open_pr(branch)
    if pr:
        pr = g.update_pr(pr['number'], body=body, title=title)
        if a.round > 0:
            g.comment(pr['number'], f"autose round {a.round}: pushed changes for the review findings "
                                    f"(resumed at stage `{state['start']}`). Run: {run_url()}")
    else:
        pr = g.create_pr(title, branch, default, body)
    try:
        g.add_labels(pr['number'], ['autose-pr'])
    except Exception as e:  # labels are cosmetic
        log(f'could not label PR: {e}')
    write_text(art / 'pr.md', f"# pr.md - issue #{issue['number']}, round {a.round}\n\n"
                              f"Pull request: {pr['html_url']}  \nBranch: `{branch}`  \nHead commit: `{head}`\n\n"
                              f"## Pull request description\n\n{body}")
    set_output(pr=pr['number'], pr_url=pr['html_url'], head_sha=head)
    step_summary(f"### autose release\nPull request: {pr['html_url']} (head `{head[:10]}`)")


def cmd_release_check(a):
    g = gh()
    pr = g.pr(a.pr)
    problems = []
    if pr['state'] != 'open':
        problems.append(f"the pull request is {pr['state']}")
    if pr['head']['sha'] != a.sha:
        problems.append(f"the pull request head moved ({pr['head']['sha'][:10]} != {a.sha[:10]})")
    if a.ci_result != 'success':
        problems.append(f'CI result: {a.ci_result}')
    passed = not problems
    try:
        g.set_status(a.sha, 'success' if passed else 'failure', 'autose/ci',
                     'CI passed on the autose PR' if passed else '; '.join(problems), run_url())
    except Exception as e:
        log(f'could not set commit status: {e}')
    text = (f"# Stage 5 check - PR #{a.pr}\n\n- PR open: {pr['state'] == 'open'}\n- CI (ci.yml on `{a.sha[:10]}`): "
            f"{a.ci_result}\n\n**{'PASS' if passed else 'FAIL'}**\n" + ''.join(f'\n- {p}' for p in problems))
    write_text(Path(a.out) / 'release_check.md', text)
    write_json(Path(a.out) / 'release_check.json', {'passed': passed, 'problems': problems, 'pr': a.pr,
                                                     'sha': a.sha, 'ci': a.ci_result, 'round': a.round})
    set_output(passed='true' if passed else 'false')
    step_summary(text)


# ================================================================ review (stage 6) ==============
def cmd_review_prepare(a):
    g = gh()
    pr = g.pr(a.pr)
    if pr['head']['repo'] is None or pr['head']['repo']['full_name'] != g.repo:
        raise SystemExit('refusing to review a pull request from a fork')
    out = Path(a.out)
    body, _ = untrusted.clean(pr.get('body') or '', 8000)
    write_json(out / 'pr.json', {'number': pr['number'], 'title': pr['title'], 'body': body,
                                 'base_sha': pr['base']['sha'], 'base_ref': pr['base']['ref'],
                                 'head_sha': pr['head']['sha'], 'head_ref': pr['head']['ref'],
                                 'url': pr['html_url']})
    if a.issue:
        write_json(out / 'issue.json', load_issue(g, a.issue))
    set_output(head_sha=pr['head']['sha'], base_sha=pr['base']['sha'])


def _review_prompt(issue, pr, diff, facts, variant):
    from .pipeline import issue_block
    parts = []
    if issue:
        parts.append('## The issue this pull request is meant to resolve\n\n' + issue_block(issue))
    else:
        parts.append(f"## No linked issue\n\nPull request title: {untrusted.wrap('pr-title', pr['title'])}")
    parts.append(f"## Pull request #{pr['number']} diff (base {pr['base_sha'][:10]} ... head {pr['head_sha'][:10]})\n\n"
                 f"```diff\n{truncate(diff, 60000)}\n```")
    parts.append('## Facts gathered by the review job before you started\n\n'
                 f"- Full test suite on the head commit: `{facts['suite_summary']}` ({facts['suite_ran']} tests)\n"
                 f"- Files changed: {', '.join(facts['files'])}\n"
                 f"- Existing test methods deleted by the diff: {', '.join(facts['removed_tests']) or 'none'}")
    if variant['reviewer_context'] == 'with_rationale':
        parts.append("## The author's description of this pull request\n\n" + untrusted.wrap('pr-description', pr['body']))
    parts.append('Review the pull request now. The repository in your working directory is at the head commit.')
    return '\n\n'.join(parts)


def cmd_review(a):
    from .pipeline import system_prompt
    variant = load_variant(a.variant)
    inp, art = Path(a.inp), Path(a.out)
    art.mkdir(parents=True, exist_ok=True)
    work = Path(a.work).resolve()
    repo = Repo(work)
    pr = read_json(inp / 'pr.json')
    issue = read_json(inp / 'issue.json')
    if run(['git', 'cat-file', '-e', pr['base_sha']], cwd=work).returncode != 0:
        repo.git('fetch', '-q', 'origin', pr['base_sha'])
    diff = repo.diff(pr['base_sha'], pr['head_sha'])
    files = repo.files_between(pr['base_sha'], pr['head_sha'])
    suite, report = checks.run_tests(work, [], 900)
    facts = {'suite_passed': report['exit_code'] == 0, 'suite_summary': report.get('summary'),
             'suite_ran': report.get('ran'), 'files': files, 'files_changed': len(files),
             'removed_tests': checks.removed_tests(diff),
             'forbidden': [f for f in files if checks.path_kind(f) == 'forbidden']}
    write_text(art / 'pr_diff.patch', diff)
    prior = [p for p in glob.glob(str(Path(a.prior_ledgers) / '**' / 'ledger.json'), recursive=True)] if a.prior_ledgers else []
    ledger = Ledger(art / 'ledger.json', variant['limits']['job_budget_usd'], variant['limits']['run_budget_usd'],
                    prior_spent=Ledger.spent_in(prior))
    res = run_agent(role='reviewer', role_cfg=variant['roles']['reviewer'], call_id=f'r{a.round}-review',
                    system_prompt=system_prompt('review.md'), user_prompt=_review_prompt(issue, pr, diff, facts, variant),
                    schema=schemas.REVIEW, cwd=work, log_dir=art / 'logs', ledger=ledger)
    review = res.structured or {'summary': f'The reviewer agent failed: {res.error}', 'findings': [],
                                'issue_requirements': [], 'checks_run': [], 'verdict': 'request_changes'}
    overrides = []
    if not facts['suite_passed']:
        overrides.append(f"the full test suite fails on the head commit (`{facts['suite_summary']}`)")
    if facts['removed_tests']:
        overrides.append(f"the diff deletes existing tests: {', '.join(facts['removed_tests'])}")
    if facts['forbidden']:
        overrides.append(f"the diff changes protected paths: {', '.join(facts['forbidden'])}")
    severe = [f for f in review.get('findings', []) if f.get('severity') in ('blocking', 'major')]
    if not res.ok:
        final = 'error'
    else:
        final = 'request_changes' if (severe or overrides) else 'approve'
    order = {'design': 0, 'implement': 1, 'test': 2}
    routes = [f.get('route', 'implement') for f in severe]
    if facts['removed_tests']:
        routes.append('test')
    if not facts['suite_passed']:
        routes.append('implement')
    route = min(routes, key=lambda r: order.get(r, 1)) if routes else ''
    review['_overrides'] = overrides
    data = {'pr': pr['number'], 'round': a.round, 'variant': variant['name'], 'model': res.model,
            'agent_ok': res.ok, 'agent_verdict': review.get('verdict'), 'final_verdict': final, 'route': route,
            'overrides': overrides, 'facts': facts, 'review': review, 'cost_usd': res.cost_usd,
            'head_sha': pr['head_sha'], 'issue': issue['number'] if issue else None}
    write_json(art / 'review.json', data)
    md = render.review_md(pr, review, {**facts, 'overrides': overrides}, final if final != 'error' else 'request_changes',
                          route, res.model)
    if final == 'error':
        md = f"**The reviewer agent failed ({res.error[:300]}). This is not a review; a person must review the PR.**\n\n" + md
    write_text(art / 'review.md', md)
    set_output(verdict=final, route=route)
    step_summary(f"### autose review (round {a.round})\nAgent verdict `{review.get('verdict')}`, final verdict "
                 f"**{final}**, route `{route}`, findings {len(review.get('findings', []))}, cost ${res.cost_usd:.2f}")


def cmd_review_post(a):
    g = gh()
    art = Path(a.art)
    data = read_json(art / 'review.json')
    body = untrusted.no_mentions((art / 'review.md').read_text(encoding='utf-8'))
    footer = (f"\n\n---\nReview by the autose reviewer agent ({data['model']}) in its own job: it saw only the issue, "
              f"the diff and the code at `{data['head_sha'][:10]}`, it could run code but not push. "
              "This is posted as a comment review; it does not approve anything. A person decides whether to merge.")
    g.create_review(data['pr'], data['head_sha'], truncate(body, 60000, 'end') + footer, 'COMMENT')
    want = {'approve': 'autose:approved', 'request_changes': 'autose:changes-requested'}.get(data['final_verdict'])
    for label in ('autose:approved', 'autose:changes-requested'):
        if label != want:
            g.remove_label(data['pr'], label)
    if want:
        try:
            g.add_labels(data['pr'], [want])
        except Exception as e:
            log(f'could not label: {e}')


# ================================================================ finalize ======================
def cmd_finalize(a):
    g = gh()
    root = Path(a.artifacts)
    needs = json.loads(a.needs or '{}')
    rounds = []
    tokens = {'input_tokens': 0, 'output_tokens': 0, 'cache_creation_input_tokens': 0, 'cache_read_input_tokens': 0,
              'cost_usd': 0.0, 'calls': 0}
    for led in sorted(root.glob('**/ledger.json')):
        t = (read_json(led, {}) or {}).get('totals', {})
        for k in tokens:
            tokens[k] += t.get(k, 0)
    for k in range(0, 4):
        b = read_json(root / f'autose-build-r{k}' / 'state.json')
        rc = read_json(root / f'autose-release-r{k}' / 'release_check.json')
        rv = read_json(root / f'autose-review-r{k}' / 'review.json')
        if b or rv:
            rounds.append({'round': k, 'build': b, 'release_check': rc, 'review': rv})
    issue_no = a.issue or None
    pr_no = a.pr or None
    for r in rounds:
        pr_no = pr_no or (r['release_check'] or {}).get('pr') or (r['review'] or {}).get('pr')

    # Final outcome in one line.
    outcome, detail = 'unknown', ''
    last = rounds[-1] if rounds else None
    if not rounds:
        outcome, detail = 'failed', 'no stage produced a result (see the run log)'
    elif last['review']:
        v = last['review']['final_verdict']
        if v == 'approve':
            outcome, detail = 'approved', f"the reviewer approved in review round {last['round'] + 1}"
        elif v == 'error':
            outcome, detail = 'reviewer_failed', 'the reviewer agent failed; a person must review'
        else:
            outcome = 'rounds_used_up' if a.mode == 'full' else 'changes_requested'
            detail = 'the reviewer still requests changes and no review rounds are left' if a.mode == 'full' \
                else 'the reviewer requests changes'
    elif last['build'] and last['build']['status'] == 'stopped':
        outcome, detail = f"stopped_at_{last['build']['stopped_at']}", last['build']['reason']
    elif last['release_check'] and not last['release_check']['passed']:
        outcome, detail = 'stopped_at_release', '; '.join(last['release_check']['problems'])
    else:
        outcome, detail = 'incomplete', 'a job failed or was cancelled; see the run log. Jobs: ' + \
            ', '.join(f"{k}={v.get('result')}" for k, v in needs.items())

    summary = {'run': run_url(), 'mode': a.mode, 'variant': a.variant, 'issue': issue_no, 'pr': pr_no,
               'outcome': outcome, 'detail': detail, 'tokens': tokens, 'jobs': {k: v.get('result') for k, v in needs.items()},
               'rounds': [{'round': r['round'],
                           'build_status': (r['build'] or {}).get('status'),
                           'stopped_at': (r['build'] or {}).get('stopped_at'),
                           'history': (r['build'] or {}).get('history'),
                           'release_check': (r['release_check'] or {}).get('passed'),
                           'agent_verdict': (r['review'] or {}).get('agent_verdict'),
                           'final_verdict': (r['review'] or {}).get('final_verdict'),
                           'route': (r['review'] or {}).get('route'),
                           'findings': len(((r['review'] or {}).get('review') or {}).get('findings', []))}
                          for r in rounds]}
    out = Path(a.out)
    write_json(out / 'run_summary.json', summary)

    lines = [f"## autose: {outcome.replace('_', ' ')}", '', detail, '', '| Round | Stages | Release check | Review |',
             '|---|---|---|---|']
    for r in summary['rounds']:
        stages = ' -> '.join(f"{h['stage']}: {h['outcome'][:40]}" for h in (r['history'] or []) if h['stage'] != 'guard')
        lines.append(f"| {r['round']} | {stages or '-'} | {r['release_check']} | {r['final_verdict'] or '-'} |")
    lines += ['', f"Tokens: input {tokens['input_tokens']:,}, output {tokens['output_tokens']:,}, cache write "
                  f"{tokens['cache_creation_input_tokens']:,}, cache read {tokens['cache_read_input_tokens']:,}; "
                  f"cost ${tokens['cost_usd']:.2f} over {tokens['calls']} agent calls.", '',
              f"Run and all artifacts: {run_url()}", '',
              '**A person decides what happens next** (merge, close, or answer questions and run `/autose` again). '
              'autose never merges.']
    text = '\n'.join(lines)
    write_text(out / 'summary.md', text)
    step_summary(text)

    # Clarification questions go to the issue so the maintainer can answer them there.
    if outcome == 'stopped_at_requirements' and issue_no:
        spec = read_json(root / f"autose-build-r{last['round']}" / 'spec.json', {}) or {}
        qs = spec.get('clarification_questions') or []
        if qs:
            q = '\n'.join(f"{i}. {x['question']}  \n   _Why:_ {x['why_it_matters']}  \n   _Options:_ {'; '.join(x.get('options') or [])}"
                          for i, x in enumerate(qs, 1))
            text = (f"### autose needs clarification before it can write a testable specification\n\n{untrusted.no_mentions(q)}\n\n"
                    "A maintainer can answer in a comment and then comment `/autose` to run again.\n\n" + text)
    if issue_no:
        g.comment(issue_no, text)
        g.remove_label(issue_no, 'autose')
    if pr_no and str(pr_no) != str(issue_no):
        g.comment(pr_no, text)


# ================================================================ main ==========================
def main(argv=None):
    p = argparse.ArgumentParser(prog='autose')
    sub = p.add_subparsers(dest='cmd', required=True)
    sub.add_parser('gate')
    s = sub.add_parser('fetch-issue'); s.add_argument('--issue', required=True); s.add_argument('--out', required=True)
    s = sub.add_parser('build')
    s.add_argument('--issue-json', required=True); s.add_argument('--work', required=True); s.add_argument('--out', required=True)
    s.add_argument('--round', type=int, default=0); s.add_argument('--variant', default='default')
    s.add_argument('--resume-from', default=''); s.add_argument('--prev', default=''); s.add_argument('--review', default='')
    s.add_argument('--prior-ledgers', default='')
    s = sub.add_parser('release')
    s.add_argument('--work', required=True); s.add_argument('--art', required=True); s.add_argument('--round', type=int, default=0)
    s.add_argument('--prev', default='')
    s = sub.add_parser('release-check')
    s.add_argument('--pr', required=True); s.add_argument('--sha', required=True); s.add_argument('--ci-result', required=True)
    s.add_argument('--round', type=int, default=0); s.add_argument('--out', required=True)
    s = sub.add_parser('review-prepare'); s.add_argument('--pr', required=True); s.add_argument('--issue', default='')
    s.add_argument('--out', required=True)
    s = sub.add_parser('review')
    s.add_argument('--work', required=True); s.add_argument('--in', dest='inp', required=True); s.add_argument('--out', required=True)
    s.add_argument('--round', type=int, default=0); s.add_argument('--variant', default='default'); s.add_argument('--prior-ledgers', default='')
    s = sub.add_parser('review-post'); s.add_argument('--art', required=True)
    s = sub.add_parser('finalize')
    s.add_argument('--artifacts', required=True); s.add_argument('--out', required=True); s.add_argument('--issue', default='')
    s.add_argument('--pr', default=''); s.add_argument('--mode', default='full'); s.add_argument('--variant', default='default')
    s.add_argument('--needs', default='{}')
    a = p.parse_args(argv)
    {'gate': cmd_gate, 'fetch-issue': cmd_fetch_issue, 'build': cmd_build, 'release': cmd_release,
     'release-check': cmd_release_check, 'review-prepare': cmd_review_prepare, 'review': cmd_review,
     'review-post': cmd_review_post, 'finalize': cmd_finalize}[a.cmd](a)


if __name__ == '__main__':
    sys.exit(main())
