"""Build report/report.html (and report.pdf with a headless Edge/Chrome) from the real run data.

    python scripts/make_report.py [--pdf]

Data: results/results.csv, results/hidden_tests.csv, results/raw/<run>/... (from collect_results.py),
experiment/seeded_prs/labels.json, architecture/decisions/README.md.
Sections that need the author's own judgement are read from report/student_sections.md
(## headings below); empty sections are shown as a highlighted box.
"""
from __future__ import annotations

import csv
import html
import json
import re
import shutil
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / 'results' / 'raw'
REPO_URL = 'https://github.com/nanchan1912/autose-a3'
SEQ_RUN = '45375233794'          # the run shown in the sequence view
EXCLUDE_FROM_COMPARISON = {SEQ_RUN}  # verification run after the build-check fix
VARIANTS_E1 = ['default', 'E1-same-model', 'E1-sees-rationale']
SEEDED = {'S1': 8, 'S2': 9, 'S3': 10, 'S4': 11, 'S5': 12}


def esc(s):
    return html.escape(str(s))


def load(p):
    p = Path(p)
    return json.loads(p.read_text(encoding='utf-8')) if p.exists() else None


def student_sections():
    p = ROOT / 'report' / 'student_sections.md'
    out = {}
    if p.exists():
        cur = None
        for line in p.read_text(encoding='utf-8').splitlines():
            m = re.match(r'^## (.+)$', line)
            if m:
                cur = m.group(1).strip()
                out[cur] = []
            elif cur:
                out[cur].append(line)
    return {k: '\n'.join(v).strip() for k, v in out.items()}


def md_inline(text):
    t = esc(text)
    t = re.sub(r'`([^`]+)`', r'<code>\1</code>', t)
    t = re.sub(r'\*\*([^*]+)\*\*', r'<b>\1</b>', t)
    return t


def paragraphs(text):
    blocks = [b.strip() for b in re.split(r'\n\s*\n', text) if b.strip()]
    out = []
    for b in blocks:
        if all(ln.strip().startswith('- ') for ln in b.splitlines()):
            out.append('<ul>' + ''.join(f'<li>{md_inline(ln.strip()[2:])}</li>' for ln in b.splitlines()) + '</ul>')
        else:
            out.append(f'<p>{md_inline(" ".join(b.splitlines()))}</p>')
    return '\n'.join(out)


def slot(sections, name, hint):
    text = sections.get(name, '')
    if text and not text.startswith('TODO'):
        return paragraphs(text)
    return f'<div class="todo"><b>To write (your own words) - section "{esc(name)}" in report/student_sections.md:</b> {esc(hint)}</div>'


def main():
    rows = list(csv.DictReader(open(ROOT / 'results/results.csv', encoding='utf-8')))
    hidden = list(csv.DictReader(open(ROOT / 'results/hidden_tests.csv', encoding='utf-8')))
    labels = load(ROOT / 'experiment/seeded_prs/labels.json')
    sec = student_sections()
    real = [r for r in rows if float(r['cost_usd'] or 0) > 0]   # runs in which agents actually ran

    # ---------------- totals
    tok_in = sum(int(r['input_tokens']) + int(r['cache_write_tokens']) + int(r['cache_read_tokens']) for r in rows)
    tok_out = sum(int(r['output_tokens']) for r in rows)
    cost = sum(float(r['cost_usd']) for r in rows)

    # ---------------- stage pass rates over full runs with agent calls
    full = [r for r in real if r['mode'] == 'full']
    stage_rows = []
    for st in ('requirements', 'design', 'implement', 'test'):
        reached = [r for r in full if r[st]]
        passed = [r for r in reached if r[st].startswith('pass')]
        first = [r for r in passed if r[st] == 'pass(1)']
        stage_rows.append((st, len(reached), len(passed), len(first)))
    rel = [r for r in full if r['release']]
    rel_pass = [r for r in rel if 'fail' not in r['release']]
    rev = [r for r in real if r['review_verdicts']]

    # ---------------- E1
    e1 = defaultdict(dict)
    for r in real:
        if r['mode'] == 'review' and r['seeded_pr'] and r['variant'] in VARIANTS_E1:
            d = RAW / r['run_id'] / 'autose-review-r0' / 'review.json'
            rv = load(d) or {}
            e1[r['seeded_pr']][r['variant']] = {
                'final': r['review_verdicts'], 'agent': r['agent_verdicts'], 'cost': float(r['cost_usd']),
                'url': r['run_url'], 'model': r['reviewer_model'],
                'blocking': sum(1 for f in rv.get('review', {}).get('findings', []) if f['severity'] in ('blocking', 'major')),
                'override': bool(rv.get('overrides')),
            }

    def correct(sid, v):
        want = 'request_changes' if labels[sid]['label'] == 'defect' else 'approve'
        return v == want

    e1_score = {v: (sum(1 for s in e1 if v in e1[s] and correct(s, e1[s][v]['final'])),
                    sum(1 for s in e1 if v in e1[s]),
                    sum(e1[s][v]['cost'] for s in e1 if v in e1[s]),
                    sum(1 for s in e1 if v in e1[s] and correct(s, e1[s][v]['agent']))) for v in VARIANTS_E1}

    # ---------------- E2 (one run per issue and variant: last run that got past stage 1, else last run)
    hid = {}
    for h in hidden:
        hid[h['branch']] = h
    e2 = defaultdict(dict)
    for r in real:
        if r['mode'] != 'full' or r['run_id'] in EXCLUDE_FROM_COMPARISON or r['variant'] not in ('default', 'E2-self-test'):
            continue
        prev = e2[r['issue_id']].get(r['variant'])
        if prev is None or r['outcome'] != 'stopped_at_requirements' or prev['outcome'] == 'stopped_at_requirements':
            e2[r['issue_id']][r['variant']] = r

    # ---------------- what the reviewer found in pipeline PRs
    found = []
    for r in real:
        if r['mode'] != 'full':
            continue
        for k in range(3):
            rv = load(RAW / r['run_id'] / f'autose-review-r{k}' / 'review.json')
            if not rv:
                continue
            for f in rv['review'].get('findings', []):
                found.append((r, k, f, rv['final_verdict']))
    sev_count = defaultdict(int)
    for _, _, f, _ in found:
        sev_count[f['severity']] += 1

    seq = subprocess.run([sys.executable, str(ROOT / 'scripts/make_sequence_view.py'), str(ROOT / 'runs' / SEQ_RUN),
                          '--run-url', f'{REPO_URL}/actions/runs/{SEQ_RUN}'], text=True, stdout=subprocess.PIPE).stdout
    seq_mermaid = re.search(r'```mermaid\n(.*?)```', seq, re.S)
    seq_mermaid = seq_mermaid.group(1) if seq_mermaid else ''

    adr_rows = []
    for line in (ROOT / 'architecture/decisions/README.md').read_text(encoding='utf-8').splitlines():
        if line.startswith('| [ADR'):
            cells = [c.strip() for c in line.strip('|').split('|')]
            cells[0] = re.sub(r'\[(ADR-\d+)\]\([^)]*\)', r'\1', cells[0])
            adr_rows.append(cells)

    H = []
    a = H.append
    a(f'''<!doctype html><html><head><meta charset="utf-8"><title>AutoSE A3 report</title>
<style>
@page {{ size: A4; margin: 15mm 14mm 15mm 14mm; }}
body {{ font-family: "Segoe UI", Arial, sans-serif; font-size: 9.6pt; line-height: 1.33; color: #111; }}
h1 {{ font-size: 15pt; margin: 0 0 2mm 0; }} h2 {{ font-size: 12pt; margin: 4mm 0 1.5mm; border-bottom: 1px solid #999; }}
h3 {{ font-size: 10.2pt; margin: 3mm 0 1mm; }} p {{ margin: 1mm 0 1.6mm; }} ul {{ margin: 1mm 0 1.6mm 4mm; padding-left: 3mm; }}
table {{ border-collapse: collapse; width: 100%; margin: 1.5mm 0 2.5mm; font-size: 8.4pt; }}
th, td {{ border: 1px solid #aaa; padding: 1.2mm 1.5mm; vertical-align: top; text-align: left; }} th {{ background: #eee; }}
code {{ font-family: Consolas, monospace; font-size: 8.4pt; }} .small {{ font-size: 8.2pt; color: #333; }}
.ok {{ color: #0a6b1f; font-weight: 600; }} .bad {{ color: #a10b0b; font-weight: 600; }}
.todo {{ background: #fff3b0; border: 1px solid #d9b500; padding: 2mm; margin: 2mm 0; }}
.mermaid {{ margin: 1mm 0; text-align: center; }} .mermaid svg {{ max-height: 125mm; }} .pb {{ page-break-before: always; }}
a {{ color: #0645ad; text-decoration: none; }}
</style>
<script src="https://cdn.jsdelivr.net/npm/mermaid@11.4.1/dist/mermaid.min.js"></script>
<script>mermaid.initialize({{startOnLoad: true, theme: 'neutral', flowchart: {{useMaxWidth: true}}, sequence: {{useMaxWidth: true, mirrorActors: false}}}});</script>
</head><body>
<h1>AutoSE Assignment 3: an agentic issue-to-pull-request workflow</h1>
<p class="small">Repository: <a href="{REPO_URL}">{REPO_URL}</a> (Python-Markdown pinned at <code>3f2c551</code>).
All runs, PRs and reviews: <a href="{REPO_URL}/blob/main/results/runs.md">results/runs.md</a>. ADRs:
<a href="{REPO_URL}/tree/main/architecture/decisions">architecture/decisions/</a>.</p>

<h2>1. Architecture</h2>
<p>A label <code>autose</code> or a comment <code>/autose</code> by a maintainer starts <code>autose.yml</code>: a <b>gate</b> job
(authorisation, command parsing), then up to three <b>rounds</b> (reusable <code>autose-round.yml</code>), then <b>finalize</b>.
In a round, a Python orchestrator runs stages 1-4 as a fixed state machine with three agents and a deterministic check
after every stage, then pushes the branch and opens the PR (stage 5, no agent); <code>ci.yml</code> and a release check
follow; the independent reviewer runs in its own job (<code>autose-review.yml</code>, stage 6). If it requests changes,
the next round resumes at the stage its findings point to. Agents are headless Claude Code processes with fixed tool
allow lists, JSON output schemas, turn and dollar limits; none of them holds a GitHub token.</p>
<h3>Component view</h3>
<div class="mermaid">
flowchart TB
  ISS["Issue: label autose or /autose"] --> G["gate job: authorisation, command"]
  G --> O
  subgraph BUILD["build job (agent step has no GitHub token)"]
    direction LR
    O["Orchestrator: state machine + deterministic checks + git"]
    AN["Analyst, Sonnet 5.5: stages 1-2, read-only"]
    IM["Implementer, Sonnet 5.5: stage 3, production code"]
    TE["Tester, Sonnet 5.5: stage 4, tests/ only"]
    O --> AN
    O --> IM
    O --> TE
  end
  O --> REL["Release step: push branch, open PR (token)"]
  REL --> CI["ci.yml + release check: stage 5"]
  CI --> RV
  subgraph REVIEW["review job, fresh runner (no build artifacts)"]
    RV["Reviewer, Opus 5.5: stage 6, read + run code, no token, no push"] --> POST["post COMMENT review"]
  end
  POST --> HUM(["Maintainer decides: merge or close"])
  POST -. "request changes: next round, max 2" .-> O
  BUILD -. "artifacts: spec, design, diff, test report, transcripts, ledgers" .-> ART[("Workflow artifacts")]
</div>
<h3>Stage map</h3>
<table><tr><th>#</th><th>Stage</th><th>Agent</th><th>Artifact</th><th>Check (decided by code)</th><th>On failure</th></tr>
<tr><td>1</td><td>Requirements</td><td>Analyst (A1 skill)</td><td><code>spec.md</code></td><td>every AC has given/when/then, an exact observable result, no vague words, no ASSUMPTION; or BLOCKED with questions</td><td>retry once; BLOCKED: ask on the issue and stop</td></tr>
<tr><td>2</td><td>Design</td><td>Analyst (fresh session, A2 ARCHITECTURE.md)</td><td><code>design.md</code></td><td>named files exist or are new; named functions/classes exist or are new; allowed paths; a planned test per AC</td><td>retry once, then stop</td></tr>
<tr><td>3</td><td>Implementation</td><td>Implementer</td><td><code>diff.patch</code></td><td>installs, compiles, imports, converts; no new flake8 findings; diff non-empty and &lt; 800 lines; non-production edits reverted</td><td>retry (3 per design), then design once</td></tr>
<tr><td>4</td><td>Testing</td><td>Tester (separate)</td><td><code>test_report.md</code></td><td>full suite passes; every AC has a passing <code>test_ac_00N</code>; no deleted tests</td><td>implementer, then design once</td></tr>
<tr><td>5</td><td>Release</td><td>none</td><td><code>pr.md</code> + PR</td><td>PR open at the tested commit and <code>ci.yml</code> green (3.11, 3.13, flake8)</td><td>stop</td></tr>
<tr><td>6</td><td>Review</td><td>Reviewer (own job, Opus)</td><td><code>review.md</code></td><td>request changes iff a blocking/major finding with evidence, failing suite, deleted tests or protected paths</td><td>new round at the routed stage, max 2</td></tr></table>
<h3>Sequence view of one real run (<a href="{REPO_URL}/actions/runs/{SEQ_RUN}">run {SEQ_RUN}</a>, issue #1)</h3>
<div class="mermaid">
{seq_mermaid}
</div>

<h2>2. Design decisions</h2>
<table><tr><th>ADR</th><th>Decision</th><th>Chosen</th><th>Main option rejected</th><th>Main reason</th><th>Status</th></tr>
{''.join('<tr>' + ''.join(f'<td>{md_inline(c)}</td>' for c in r) + '</tr>' for r in adr_rows)}</table>
<h3>The three decisions that mattered most</h3>
{slot(sec, 'Three decisions that mattered most', 'Pick three ADRs and discuss each with evidence from the runs (about 1.5 pages). Data you can cite is in sections 3 and 4.')}
''')

    # ---------------- section 3 experiments
    a('<h2>3. Decision experiments</h2>')
    a('<h3>E1 - reviewer independence (ADR-006, ADR-008): 5 seeded PRs x 3 reviewer variants</h3>')
    a('<p>Each seeded PR passes the existing test suite and flake8; S1-S3 contain a planted defect, S4-S5 are correct '
      '(ground truth in <code>experiment/seeded_prs/labels.json</code>; the hidden tests independently confirm it). '
      'Variants: <code>default</code> = Opus 5.5, isolated context; <code>E1-same-model</code> = Sonnet 5.5 (the implementer\'s model); '
      '<code>E1-sees-rationale</code> = Opus 5.5 that also reads the author\'s confident PR description.</p>')
    a('<table><tr><th>PR</th><th>Ground truth</th>' + ''.join(f'<th>{v}</th>' for v in VARIANTS_E1) + '</tr>')
    for sid in sorted(e1):
        lab = labels[sid]
        cells = []
        for v in VARIANTS_E1:
            d = e1[sid].get(v)
            if not d:
                cells.append('<td>-</td>')
                continue
            ok = correct(sid, d['final'])
            extra = f" ({d['blocking']} blocking/major)" if d['blocking'] else ''
            cells.append(f'<td><a class="{"ok" if ok else "bad"}" href="{d["url"]}">{d["final"].replace("_", " ")}</a>{extra}<br>'
                         f'<span class="small">${d["cost"]:.2f}</span></td>')
        a(f'<tr><td>{sid} (<a href="{REPO_URL}/pull/{SEEDED[sid]}">#{SEEDED[sid]}</a>)</td><td>{lab["label"]}: {esc(lab["defect_class"])}</td>{"".join(cells)}</tr>')
    a('<tr><th colspan="2">Correct (final verdict) / agent verdict alone / total cost</th>' +
      ''.join(f'<th>{c}/{n} / {ag}/{n} / ${co:.2f}</th>' for c, n, co, ag in (e1_score[v] for v in VARIANTS_E1)) + '</tr></table>')
    a(slot(sec, 'E1 interpretation and design change',
           'Compare with your prediction (ADR-008: you expected fewer catches for same-model and sees-rationale). '
           'Say what the result means and what you changed or would change (e.g. a superseded ADR).'))

    a('<h3>E2 - separate tester (ADR-001): default vs implementer writes its own tests, issues I1-I5</h3>')
    a('<table><tr><th>Issue</th><th>Variant</th><th>Outcome</th><th>Stages (attempts)</th><th>Review verdicts</th><th>Hidden tests</th><th>Cost</th></tr>')
    for iid in sorted(e2):
        for v in ('default', 'E2-self-test'):
            r = e2[iid].get(v)
            if not r:
                continue
            br = r['branch']
            h = hid.get(br)
            hs = f"{h['passed']}/{h['total']}" if h else '-'
            stages = ', '.join(f"{s[:4]} {r[s]}" for s in ('requirements', 'design', 'implement', 'test') if r[s])
            a(f'<tr><td>{iid}</td><td>{v}</td><td><a href="{r["run_url"]}">{r["outcome"].replace("_", " ")}</a></td><td>{stages}</td>'
              f'<td>{r["review_verdicts"] or "-"}</td><td>{hs}</td><td>${float(r["cost_usd"]):.2f}</td></tr>')
    a('</table>')
    a(slot(sec, 'E2 interpretation and design change',
           'Compare with your prediction (ADR-001). Say what the result means and what you changed or would change.'))

    # ---------------- section 4 results
    a('<h2>4. Results</h2>')
    a(f'<p>{len(rows)} workflow runs in total; {len(real)} of them ran agents. The others are the infrastructure failures '
      'fixed during the first hour (missing model credential; the gate lacked permission to comment on PRs) and are kept '
      'in <code>results/results.csv</code> for completeness.</p>')
    a('<table><tr><th>Stage</th><th>Runs that reached it</th><th>Passed</th><th>Passed on the first attempt</th></tr>')
    for st, n, p, f1 in stage_rows:
        a(f'<tr><td>{st}</td><td>{n}</td><td>{p}</td><td>{f1}</td></tr>')
    a(f'<tr><td>release (PR open + CI)</td><td>{len(rel)}</td><td>{len(rel_pass)}</td><td>-</td></tr>')
    a(f'<tr><td>review (runs with a review)</td><td>{len(rev)}</td><td colspan="2">{sum(1 for r in rev if r["review_verdicts"].split()[-1] == "approve")} '
      f'ended approved, {sum(1 for r in rev if "request_changes" in r["review_verdicts"])} had at least one "request changes"</td></tr></table>')
    a('<p class="small">Requirements stops are the vague issue I5, which was BLOCKED with clarification questions as designed. '
      'In every run before the fix in PR #22, the first implementation attempt was rejected by a bug in the build check '
      '(it compared only committed changes); the agent\'s edit was correct and the second attempt passed. After the fix, '
      f'<a href="{REPO_URL}/actions/runs/{SEQ_RUN}">run {SEQ_RUN}</a> passed on the first attempt.</p>')
    a('<h3>Hidden acceptance tests</h3><table><tr><th>Branch</th><th>Issue</th><th>Passed</th><th>Failed tests</th></tr>')
    for h in hidden:
        cls = 'ok' if h['all_pass'] == 'True' else 'bad'
        a(f'<tr><td><code>{esc(h["branch"])}</code> @ {h["commit"]}</td><td>{h["issue"]}</td><td class="{cls}">{h["passed"]}/{h["total"]}</td><td class="small">{esc(h["failed_tests"])}</td></tr>')
    a('</table>')
    a('<h3>What the reviewer found on the pipeline\'s own PRs</h3>')
    a(f'<p>{len(found)} findings in total: ' + ', '.join(f'{n} {s}' for s, n in sorted(sev_count.items())) + '.</p><ul>')
    for r, k, f, verdict in found:
        if f['severity'] in ('blocking', 'major'):
            a(f'<li>{r["issue_id"]} {r["variant"]} round {k}: [{f["severity"]}] {md_inline(f["description"][:300])} '
              f'(<a href="{r["run_url"]}">run</a>)</li>')
    a('</ul>')
    a(slot(sec, 'Where the reviewer was wrong', 'Using the findings above and the hidden tests, say where the reviewer was wrong or missed something (or that it was not observed, and why that may be).'))
    a(f'<p><b>Tokens and cost.</b> All runs together: {tok_in:,} input tokens (incl. cache), {tok_out:,} output tokens; '
      f'model cost as computed by Claude Code ${cost:.2f}. The runs used a Claude subscription token, so this is the '
      'list-price equivalent, not an invoice.</p>')

    a('<h2>5. Hindsight</h2>')
    a(slot(sec, 'Hindsight', 'If you started again tomorrow, which decision would you change first, and why? (half a page)'))
    a('<h2>6. Limitations and threats to validity</h2>')
    a(slot(sec, 'Limitations', 'At least three. Candidates: small sample (5 issues, mostly one run each, non-deterministic models); '
           'the seeded defects, issues and hidden tests were written by the same people who built the workflow; I1 reuses the A2 bug; '
           'the build-check bug affected attempt counts before PR #22; the I5 clarification was answered by the experimenter; '
           'one model family for every role.'))
    a('</body></html>')

    out = ROOT / 'report'
    out.mkdir(exist_ok=True)
    (out / 'report.html').write_text('\n'.join(H), encoding='utf-8')
    print('wrote report/report.html')
    if '--pdf' in sys.argv:
        browser = next((b for b in [r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe',
                                    r'C:\Program Files\Google\Chrome\Application\chrome.exe',
                                    shutil.which('chromium'), shutil.which('google-chrome')] if b and Path(b).exists()), None)
        if not browser:
            sys.exit('no Edge/Chrome found for PDF output')
        pdf = ROOT / 'report.pdf'
        subprocess.run([browser, '--headless=new', '--disable-gpu', f'--user-data-dir={Path(__import__("tempfile").gettempdir()) / "autose_pdf_profile"}', '--no-pdf-header-footer', '--virtual-time-budget=15000',
                        f'--print-to-pdf={pdf}', (out / 'report.html').resolve().as_uri()], check=True)
        print(f'wrote {pdf}')


if __name__ == '__main__':
    main()
