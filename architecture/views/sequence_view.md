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
