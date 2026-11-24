# Component view

Agents, their tools, and who calls whom. Solid arrows are calls/hand-offs, dotted arrows are
reads. Boxes inside a job share a runner; different jobs share nothing except uploaded artifacts.

```mermaid
flowchart TB
    subgraph GH["GitHub (repository)"]
        ISSUE["Issue + label 'autose' /<br/>comment '/autose'"]
        PR["Pull request<br/>autose/issue-N"]
        ART[("Workflow artifacts<br/>spec.md, design.md, diff.patch,<br/>test_report.md, pr.md, review.md,<br/>transcripts, ledgers")]
        MAIN["main (protected)"]
    end

    subgraph RUN["autose.yml (one workflow run)"]
        GATE["gate job<br/>authorisation, command parsing,<br/>fork-PR refusal, ack comment<br/><i>token: issues write</i>"]

        subgraph ROUND["autose-round.yml (round 0, and rounds 1-2 only on 'request changes')"]
            subgraph BUILD["build job"]
                FETCH["fetch-issue step<br/>sanitise + injection scan<br/><i>token: issues read</i>"]
                ORCH["Orchestrator (Python state machine)<br/>stage checks, retries, budgets,<br/>git, path guards<br/><i>no GitHub token</i>"]
                AN["Analyst agent<br/>Sonnet 5.5<br/>stages 1+2<br/>tools: Read Glob Grep"]
                IM["Implementer agent<br/>Sonnet 5.5<br/>stage 3<br/>Read Glob Grep Edit Write<br/>python -m unittest/-c/flake8"]
                TE["Tester agent<br/>Sonnet 5.5<br/>stage 4<br/>same tools, tests/ only"]
                REL["release step (stage 5)<br/>push branch, open/update PR<br/><i>token: contents+PR write</i>"]
            end
            CI["ci.yml<br/>tests py3.11+3.13, flake8"]
            RC["release_check job<br/>PR open + CI green,<br/>commit status autose/ci<br/><i>token: statuses write</i>"]
            subgraph REVIEWJOB["autose-review.yml (review job, fresh runner)"]
                PREP["review-prepare step<br/><i>token: PR/issues read</i>"]
                RV["Reviewer agent<br/>Opus 5.5<br/>stage 6<br/>Read Glob Grep,<br/>python -m unittest / -c<br/><i>no token, no Edit/Write</i>"]
                POST["review-post step<br/>COMMENT review + label<br/><i>token: PR write</i>"]
            end
        end
        FIN["finalize job<br/>run_summary.json, hand-over comment,<br/>clarification questions, remove label"]
    end

    HUMAN(["Maintainer<br/>decides merge / close"])
    ANTH[("Anthropic API<br/>(Claude Code CLI, headless)")]

    ISSUE --> GATE --> FETCH --> ORCH
    ORCH -- "claude -p, spec schema" --> AN
    ORCH -- "claude -p, implementation schema" --> IM
    ORCH -- "claude -p, tests schema" --> TE
    AN & IM & TE & RV -.-> ANTH
    ORCH -- "state ready" --> REL --> PR
    REL --> CI --> RC --> PREP --> RV --> POST --> PR
    RC -.-> PR
    BUILD -- "upload" --> ART
    REVIEWJOB -- "upload" --> ART
    ART -- "next round downloads spec, design,<br/>review findings, ledgers" --> ORCH
    PR -.-> RV
    ISSUE -.-> PREP
    FIN -.-> ART
    FIN --> ISSUE
    PR --> HUMAN
    HUMAN --> MAIN
```

## Notes

- **Four agent roles, one orchestrator.** The orchestrator is ordinary Python. It calls each agent as a
  separate headless Claude Code process with its own system prompt, tool allow list, JSON output schema,
  turn limit and dollar budget. Agents never call each other; they only hand over structured artifacts
  through the orchestrator.
- **Stage 5 has no agent.** Pushing, opening the PR and checking CI are deterministic.
- **Where tokens live.** Steps that run agents never get a GitHub token. Steps that hold a token never
  run an agent. The reviewer's job downloads no build artifacts.
- **Trusted code.** The orchestrator and prompts are always checked out from the default branch
  (`tool/`); the agents work in a separate sparse checkout (`work/`) that does not contain
  `workflow/`, `.github/`, `experiment/`, `results/`, `architecture/` or `scripts/`.
