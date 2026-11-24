"""Build the sequence view of one real run from its downloaded artifacts.

    gh run download <run-id> --repo <owner>/<repo> --dir runs/<run-id>
    python scripts/make_sequence_view.py runs/<run-id> --run-url <url> >> architecture/views/sequence_view.md

Every message in the diagram comes from the run's ledgers (agent calls: model, turns, cost) and
history (check outcomes), so the diagram shows what actually happened.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def load(p):
    p = Path(p)
    return json.loads(p.read_text(encoding='utf-8')) if p.exists() else None


ROLE = {'analyst': 'A', 'implementer': 'I', 'tester': 'T', 'reviewer': 'R'}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('run_dir')
    ap.add_argument('--run-url', default='')
    a = ap.parse_args()
    d = Path(a.run_dir)
    summ = load(d / 'autose-summary' / 'run_summary.json') or {}
    out = [f"\n## Sequence of run {a.run_url}\n",
           f"Issue #{summ.get('issue')}, PR #{summ.get('pr')}, variant `{summ.get('variant')}`, outcome **{summ.get('outcome')}**.\n",
           '```mermaid', 'sequenceDiagram', '    autonumber', '    actor M as Maintainer', '    participant G as gate',
           '    participant O as Orchestrator', '    participant A as Analyst', '    participant I as Implementer',
           '    participant T as Tester', '    participant CI as CI + release check', '    participant R as Reviewer',
           '    participant F as finalize',
           f"    M->>G: trigger on issue #{summ.get('issue')}"]
    for k in range(3):
        state = load(d / f'autose-build-r{k}' / 'state.json')
        ledger = load(d / f'autose-build-r{k}' / 'ledger.json') or {'calls': []}
        if not state:
            break
        out.append(f"    G->>O: round {k} (start at {state['start']})" if k == 0 else f"    R-->>O: round {k}: resume at {state['start']}")
        hist = iter([h for h in state['history'] if h['stage'] != 'guard'])
        for call in ledger['calls']:
            who = ROLE.get(call['role'], 'O')
            stage = call['call_id'].split('-')[2]
            out.append(f"    O->>{who}: {stage} ({call['model'].replace('claude-', '')})")
            out.append(f"    {who}-->>O: {call['num_turns']} turns, ${call['cost_usd']:.2f}{'' if call['ok'] else ', FAILED'}")
            h = next(hist, None)
            if h:
                out.append(f"    Note over O: {h['stage']}: {h['outcome'][:60]}")
        rc = load(d / f'autose-release-r{k}' / 'release_check.json')
        if rc:
            out.append(f"    O->>CI: push branch, PR #{rc['pr']}")
            out.append(f"    CI-->>O: CI {rc['ci']}, stage 5 {'PASS' if rc['passed'] else 'FAIL'}")
        rv = load(d / f'autose-review-r{k}' / 'review.json')
        if rv:
            n = len(rv['review'].get('findings', []))
            out.append(f"    CI->>R: PR #{rv['pr']} (issue + diff + code only)")
            out.append(f"    R-->>F: {rv['final_verdict']} ({n} findings, {rv['model'].replace('claude-', '')}, ${rv['cost_usd']:.2f})")
    out += [f"    F->>M: hand-over comment ({summ.get('outcome')})", '```',
            f"\nTotal: {summ.get('tokens', {}).get('calls')} agent calls, ${summ.get('tokens', {}).get('cost_usd', 0):.2f}.\n"]
    print('\n'.join(out))


if __name__ == '__main__':
    main()
