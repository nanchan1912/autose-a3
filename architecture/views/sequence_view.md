# Sequence view

The assignment asks for the sequence of **one real run**, from the trigger to the posted review.
Generate it from that run's artifacts after the run (so every step and number in it is real):

```bash
gh run download <run-id> --repo <owner>/<repo> --dir runs/<run-id>
python scripts/make_sequence_view.py runs/<run-id> --run-url https://github.com/<owner>/<repo>/actions/runs/<run-id> \
    >> architecture/views/sequence_view.md
```

The generic shape of a run (no real data) is shown below for orientation only.

```mermaid
sequenceDiagram
    autonumber
    actor M as Maintainer
    participant GH as GitHub
    participant G as gate job
    participant O as Orchestrator (build job)
    participant A as Analyst
    participant I as Implementer
    participant T as Tester
    participant CI as ci.yml
    participant RC as release_check
    participant R as Reviewer (review job)
    participant F as finalize

    M->>GH: add label "autose" to issue #N
    GH->>G: issues.labeled event
    G->>GH: check permission, comment "run started"
    G->>O: round 0 (issue N, variant)
    O->>A: issue (untrusted) -> spec schema
    A-->>O: spec.json
    O->>O: check_spec (pass / retry / BLOCKED -> stop)
    O->>A: spec + ARCHITECTURE.md -> design schema
    A-->>O: design.json
    O->>O: check_design
    O->>I: spec ACs + design
    I-->>O: edits in markdown/
    O->>O: guard paths, check_build, commit
    O->>T: spec ACs + test plan + changed file names
    T-->>O: tests in tests/
    O->>O: guard, run full suite, AC coverage (fail -> back to I / A)
    O->>GH: push autose/issue-N, open PR
    GH->>CI: ci.yml on PR head
    CI-->>RC: result
    RC->>GH: commit status autose/ci
    RC->>R: PR number (no build artifacts)
    R->>GH: read issue + PR (token step)
    R->>R: agent reviews diff, runs probes and tests
    R->>GH: COMMENT review + label
    alt request changes and rounds left
        R-->>O: round k+1 resumes at design / implement / test
    end
    F->>GH: hand-over comment on issue and PR, remove label
    M->>GH: merge or close
```

## Sequence of run https://github.com/nanchan1912/autose-a3/actions/runs/45375233794

Issue #1, PR #13, variant `default`, outcome **approved**.

```mermaid
sequenceDiagram
    autonumber
    actor M as Maintainer
    participant G as gate
    participant O as Orchestrator
    participant A as Analyst
    participant I as Implementer
    participant T as Tester
    participant CI as CI + release check
    participant R as Reviewer
    participant F as finalize
    M->>G: trigger on issue #1
    G->>O: round 0 (start at requirements)
    O->>A: requirements (sonnet-5-5)
    A-->>O: 5 turns, $0.05
    Note over O: requirements: PASS
    O->>A: design (sonnet-5-5)
    A-->>O: 5 turns, $0.07
    Note over O: design: PASS (design v1)
    O->>I: implement (sonnet-5-5)
    I-->>O: 5 turns, $0.03
    Note over O: implement: PASS (attempt 1)
    O->>T: test (sonnet-5-5)
    T-->>O: 6 turns, $0.05
    Note over O: test: PASS (OK (skipped=52))
    O->>CI: push branch, PR #13
    CI-->>O: CI success, stage 5 PASS
    CI->>R: PR #13 (issue + diff + code only)
    R-->>F: approve (1 findings, opus-5-5, $0.09)
    F->>M: hand-over comment (approved)
```

Total: 5 agent calls, $0.29.

