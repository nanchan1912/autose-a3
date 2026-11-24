# Architecture decision records

One file per decision, `ADR-001.md` ... in the Nygard format (`TEMPLATE.md`). If a run shows that a
decision was wrong, the old ADR stays with status `Superseded by ADR-0NN` and a new ADR explains
what was learned.

| ADR | Decision | Option chosen | Main option rejected | Main reason | Status |
|---|---|---|---|---|---|
| [ADR-001](ADR-001.md) | D1 Splitting the work | 4 roles: analyst, implementer, separate tester, reviewer | one agent for everything | separate tester reduces confirmation bias; more agents add cost and coordination overhead | Accepted |
| [ADR-002](ADR-002.md) | D2 Control flow | Python state machine decides every transition | AI manager / planner | predictable order, retries and transitions; easier to debug and reproduce | Accepted |
| [ADR-003](ADR-003.md) | D3 Hand-offs | structured stage documents, only what each stage needs | passing full conversations | less bias and blind agreement; fewer tokens | Accepted |
| [ADR-004](ADR-004.md) | D4 State | workflow artifacts + PR branch; restart from stage 1 | separate database / resuming partial runs | record of every stage without a database; clean, predictable restarts | Accepted |
| [ADR-005](ADR-005.md) | D5 Tools | read files + run Python; git/GitHub only in workflow code | agents with git/GitHub access | limits damage from wrong code or malicious instructions; auditable | Accepted |
| [ADR-006](ADR-006.md) | D6 Models | Sonnet 5.5 authors, Opus 5.5 reviewer | Opus everywhere | reviewing needs careful reasoning; Opus everywhere costs more without proportional gain | Accepted |
| [ADR-007](ADR-007.md) | D7 Checks | programmatic checks; verdict computed from findings | LLM judge | objective, reproducible; no subjective sole judgment | Accepted |
| [ADR-008](ADR-008.md) | D8 Reviewer independence | own job, other model, no token, no build artifacts, evidence required | reviewer in the implementer's context | reviewer must judge code and evidence, not the implementer's confidence | Accepted |
| [ADR-009](ADR-009.md) | D9 Safety and failures | budgets, timeouts, input checks, isolation | unlimited execution | predictable cost and security over occasionally finishing a run | Accepted |
| [ADR-010](ADR-010.md) | D10 Triggers | maintainers only; queue runs per issue | anyone can trigger; cancel running run | untrusted text and credits; avoid race conditions | Accepted |
