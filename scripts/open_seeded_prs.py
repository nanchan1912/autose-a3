"""Open the five reviewer-check pull requests (experiment/seeded_prs/S1..S5.diff) on the fork.

Each PR body is the confident "author rationale" from labels.json and links the issue it targets.
The defect/clean ground truth is NOT put on GitHub; it stays in labels.json.

    python scripts/open_seeded_prs.py <owner>/<repo>

Needs: the GitHub CLI, experiment/issue_numbers.json (written by setup_github.sh issues), and a
clean working tree on main.
"""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TITLES = {'I1': 'Fix TOC text lost around footnote references',
          'I2': 'abbr: load_glossary() overrides existing entries',
          'I3': 'WikiLinks: support [[Page|label]]',
          'I4': 'toc: skip headings with class no-toc'}


def run(*cmd):
    print('$', ' '.join(cmd))
    return subprocess.run(cmd, cwd=ROOT, check=True, text=True, stdout=subprocess.PIPE).stdout.strip()


def main():
    repo = sys.argv[1]
    labels = json.loads((ROOT / 'experiment/seeded_prs/labels.json').read_text(encoding='utf-8'))
    numbers = json.loads((ROOT / 'experiment/issue_numbers.json').read_text(encoding='utf-8'))
    run('git', 'fetch', '-q', 'origin', 'main')
    for sid in ('S1', 'S2', 'S3', 'S4', 'S5'):
        lab = labels[sid]
        n = numbers[lab['issue']]
        body = lab['rationale'].replace('#' + lab['issue'], f'#{n}')
        title = TITLES[lab['issue']]
        branch = f'seeded/{sid}'
        run('git', 'switch', '-q', '-C', branch, 'origin/main')
        run('git', 'apply', f'experiment/seeded_prs/{sid}.diff')
        run('git', 'commit', '-q', '-am', title)
        run('git', 'push', '-q', '-f', 'origin', branch)
        url = run('gh', 'pr', 'create', '--repo', repo, '--base', 'main', '--head', branch,
                  '--title', title, '--body', body, '--label', 'seeded')
        print(f'{sid} -> {url}')
    run('git', 'switch', '-q', 'main')
    print("Now start the reviewer on each PR: comment '/autose' on it, or use scripts/run_experiments.sh.")


if __name__ == '__main__':
    main()
