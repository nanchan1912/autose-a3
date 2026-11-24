"""Collect every autose run from GitHub into results/results.csv and results/runs.md.

Needs the GitHub CLI. Downloads each run's artifacts into results/raw/<run-id>/ (git-ignored),
reads run_summary.json, state.json, review.json and the ledgers, and writes one CSV row per run.

    python scripts/collect_results.py <owner>/<repo>
"""
from __future__ import annotations

import csv
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / 'results' / 'raw'


def gh(*args) -> str:
    return subprocess.run(['gh', *args], check=True, text=True, stdout=subprocess.PIPE).stdout


def load(p: Path):
    return json.loads(p.read_text(encoding='utf-8')) if p.exists() else None


def stage_result(history, stage):
    rows = [h for h in history or [] if h['stage'] == stage]
    if not rows:
        return ''
    if any(r['outcome'].startswith('PASS') for r in rows):
        return f"pass({len(rows)})"
    return 'stop' if any(r['outcome'].startswith('STOP') for r in rows) else f"fail({len(rows)})"


def main():
    repo = sys.argv[1]
    labels = load(ROOT / 'experiment/seeded_prs/labels.json') or {}
    issue_numbers = load(ROOT / 'experiment/issue_numbers.json') or {}
    issue_ids = {str(v): k for k, v in issue_numbers.items()}
    seeded_prs = {str(p['number']): p['headRefName'].split('/')[-1] for p in json.loads(
        gh('pr', 'list', '--repo', repo, '--label', 'seeded', '--state', 'all', '--json', 'number,headRefName'))}
    runs = json.loads(gh('run', 'list', '--repo', repo, '--workflow', 'autose.yml', '--limit', '300',
                         '--json', 'databaseId,url,event,status,conclusion,createdAt,displayTitle'))
    rows, md = [], ['# All autose runs', '', '| Run | Date | Mode | Variant | Issue | PR | Outcome | Cost $ | Notes |',
                    '|---|---|---|---|---|---|---|---|---|']
    for r in sorted(runs, key=lambda x: x['createdAt']):
        if r['status'] != 'completed':
            continue
        rid = str(r['databaseId'])
        d = RAW / rid
        if not d.exists():
            d.mkdir(parents=True)
            subprocess.run(['gh', 'run', 'download', rid, '--repo', repo, '--dir', str(d)], check=False)
        summ = load(d / 'autose-summary' / 'run_summary.json')
        if not summ:
            md.append(f"| [{rid}]({r['url']}) | {r['createdAt'][:10]} | - | - | - | - | skipped/no summary ({r['conclusion']}) | - | |")
            continue
        b0 = load(d / 'autose-build-r0' / 'state.json') or {}
        hist = sum(((load(d / f'autose-build-r{k}' / 'state.json') or {}).get('history', []) for k in range(3)), [])
        reviews = [load(d / f'autose-review-r{k}' / 'review.json') for k in range(3)]
        reviews = [x for x in reviews if x]
        rel = [load(d / f'autose-release-r{k}' / 'release_check.json') for k in range(3)]
        rel = [x for x in rel if x]
        pr = summ.get('pr')
        seeded = seeded_prs.get(str(pr), '') if summ['mode'] == 'review' else ''
        t = summ['tokens']
        row = {
            'run_id': rid, 'run_url': r['url'], 'date': r['createdAt'][:10], 'mode': summ['mode'], 'variant': summ['variant'],
            'issue_number': summ.get('issue'), 'issue_id': issue_ids.get(str(summ.get('issue')), ''), 'pr': pr,
            'outcome': summ['outcome'],
            'requirements': stage_result(hist, 'requirements'), 'design': stage_result(hist, 'design'),
            'implement': stage_result(hist, 'implement'), 'test': stage_result(hist, 'test'),
            'release': ' '.join('pass' if x['passed'] else 'fail' for x in rel),
            'review_rounds': len(reviews),
            'review_verdicts': ' '.join(x['final_verdict'] for x in reviews),
            'agent_verdicts': ' '.join(str(x['agent_verdict']) for x in reviews),
            'review_findings': ' '.join(str(len(x['review'].get('findings', []))) for x in reviews),
            'reviewer_model': reviews[0]['model'] if reviews else '',
            'input_tokens': t['input_tokens'], 'output_tokens': t['output_tokens'],
            'cache_write_tokens': t['cache_creation_input_tokens'], 'cache_read_tokens': t['cache_read_input_tokens'],
            'cost_usd': round(t['cost_usd'], 4), 'agent_calls': t['calls'],
            'branch': b0.get('branch', ''), 'seeded_pr': seeded,
            'seeded_label': labels.get(seeded, {}).get('label', '') if seeded else '',
        }
        rows.append(row)
        md.append(f"| [{rid}]({r['url']}) | {row['date']} | {row['mode']} | {row['variant']} | {row['issue_id'] or row['issue_number']} "
                  f"| {'#' + str(pr) if pr else '-'} | {row['outcome']} | {row['cost_usd']} | {row['review_verdicts']} |")
    out = ROOT / 'results' / 'results.csv'
    if rows:
        with out.open('w', newline='', encoding='utf-8') as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)
    tot_in = sum(r['input_tokens'] + r['cache_write_tokens'] + r['cache_read_tokens'] for r in rows)
    tot_out = sum(r['output_tokens'] for r in rows)
    md += ['', f"Total over {len(rows)} runs: input tokens (incl. cache) {tot_in:,}, output tokens {tot_out:,}, "
               f"cost ${sum(r['cost_usd'] for r in rows):.2f}."]
    (ROOT / 'results' / 'runs.md').write_text('\n'.join(md) + '\n', encoding='utf-8')
    print(f'wrote {len(rows)} rows to {out} and results/runs.md')


if __name__ == '__main__':
    main()
