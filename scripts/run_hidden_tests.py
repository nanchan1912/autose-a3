"""Run the hidden acceptance tests against the branches produced by autose.

The hidden tests are kept outside the repository while runs are happening (as in A2), so pass
their folder explicitly. For every branch, the script makes a temporary git worktree, installs it
into a throw-away virtual environment and runs the hidden tests for that issue.

    python scripts/run_hidden_tests.py --hidden ../private/hidden_tests --out results/hidden_tests.csv \
        autose/issue-1 autose/issue-2 autose/issue-1-E2-self-test seeded/S1 ...

The issue for a branch is found from experiment/issue_numbers.json (autose/issue-N...) or from
experiment/seeded_prs/labels.json (seeded/Sx).
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def sh(cmd, cwd=None, check=True):
    p = subprocess.run(cmd, cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if check and p.returncode != 0:
        raise SystemExit(f"{' '.join(cmd)} failed:\n{p.stdout[-3000:]}")
    return p


def issue_for(branch: str) -> str:
    nums = json.loads((ROOT / 'experiment/issue_numbers.json').read_text())
    by_num = {str(v): k for k, v in nums.items()}
    m = re.match(r'(?:origin/)?autose/issue-(\d+)', branch)
    if m:
        return by_num[m.group(1)]
    m = re.match(r'(?:origin/)?seeded/(S\d)', branch)
    if m:
        return json.loads((ROOT / 'experiment/seeded_prs/labels.json').read_text())[m.group(1)]['issue']
    raise SystemExit(f'cannot tell which issue {branch} belongs to')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--hidden', required=True, help='folder with test_I*_hidden.py')
    ap.add_argument('--out', default=str(ROOT / 'results/hidden_tests.csv'))
    ap.add_argument('branches', nargs='+')
    a = ap.parse_args()
    hidden = Path(a.hidden).resolve()
    sh(['git', 'fetch', '-q', 'origin'], cwd=ROOT)
    rows = []
    for br in a.branches:
        ref = br if br.startswith('origin/') else f'origin/{br}'
        iid = issue_for(br)
        with tempfile.TemporaryDirectory() as tmp:
            wt = Path(tmp) / 'wt'
            sh(['git', 'worktree', 'add', '-q', '--detach', str(wt), ref], cwd=ROOT)
            try:
                venv = Path(tmp) / 'venv'
                sh([sys.executable, '-m', 'venv', str(venv)])
                py = venv / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
                sh([str(py), '-m', 'pip', 'install', '-q', '-e', str(wt)])
                p = sh([str(py), '-m', 'unittest', '-v', f'test_{iid}_hidden'], cwd=hidden, check=False)
                ok = len(re.findall(r'\.\.\. ok$', p.stdout, re.M))
                total = int(m.group(1)) if (m := re.search(r'^Ran (\d+) test', p.stdout, re.M)) else 0
                failed = re.findall(r'^(test\w+) .*\.\.\. (?:FAIL|ERROR)$', p.stdout, re.M)
                head = sh(['git', 'rev-parse', 'HEAD'], cwd=wt).stdout.strip()
                rows.append({'branch': br, 'issue': iid, 'commit': head[:10], 'passed': ok, 'total': total,
                             'all_pass': ok == total and total > 0, 'failed_tests': ' '.join(failed)})
                print(f'{br:40} {iid}: {ok}/{total}')
            finally:
                sh(['git', 'worktree', 'remove', '--force', str(wt)], cwd=ROOT, check=False)
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    new = not out.exists()
    with out.open('a', newline='', encoding='utf-8') as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        if new:
            w.writeheader()
        w.writerows(rows)
    print(f'appended {len(rows)} rows to {out}')


if __name__ == '__main__':
    main()
