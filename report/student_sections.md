# Your own text for the report

Write under each heading (plain paragraphs; `- ` bullet lists and `code`/**bold** work).
Leave "TODO" to keep the yellow placeholder. Then run: python scripts/make_report.py --pdf

## Three decisions that mattered most
**1. Independent reviewer (ADR-008).** I think this is probably our most important decision. The reviewer runs separately, uses a different model, doesn't have access to the token or ability to push code, and has to justify its verdict with actual evidence. This is important because we don't want the same agent that wrote the code simply approving its own work. In our experiments, it got all 15 seeded PR verdicts right. More importantly, on PR #19, it actually caught a bug that the implementer's tests had missed and even provided a command to reproduce it.

**2. Fixed state machine (ADR-002).** We decided to control the entire workflow using a Python state machine rather than letting AI agents decide what happens next. I think this matters because it makes the process much more predictable and traceable. For example, in the E2/I2 run, the reviewer rejected the implementation and sent it back to the design stage. The system created a second design, re-implemented it, and only then got approval. All these steps were recorded in the run history, so we could actually see what happened instead of having an unpredictable agent conversation.

**3. Code-based checks instead of AI-based checks (ADR-007).** We wanted important checks to be deterministic rather than relying on another AI to decide whether something was correct. This worked well when the system encountered the vague issue I5: instead of making assumptions and guessing, it stopped and asked for clarification. However, we also discovered that deterministic checks aren't automatically perfect. One of our own build checks had a bug and rejected every first implementation attempt until PR #22. So the idea is good, but the checks themselves still need to be tested properly.

The other decisions, especially around security, are also important, but we don't have enough experimental evidence to make strong claims about them. We didn't actually attempt an attack, so I'd avoid presenting them as experimentally proven.

## E1 interpretation and design change
I initially expected that a reviewer using the same model as the implementer, or one that could read the author's explanation, would be more likely to miss bugs.

But surprisingly, all three configurations performed equally well. Every configuration caught all three planted defects and approved both clean PRs. So there wasn't really a performance difference in our results.

The interesting difference was cost. The Sonnet reviewer cost around $0.23 for all five reviews, compared to around $0.58 for Opus.

My interpretation is that using a different, larger model didn't give us a measurable advantage in this experiment. However, I wouldn't immediately conclude that Sonnet is always just as good. The defects might have been too easy, and five PRs with only one run each is a very small sample.

My decision: I'd lean towards switching to Sonnet to reduce costs, but I'd first test it on harder, more realistic bugs to make sure we're not sacrificing review quality.

## E2 interpretation and design change
I expected that when the implementer wrote its own tests, more bugs would slip through the hidden tests.

Interestingly, that didn't happen. Both E2 and the default configuration passed all 19 hidden tests (I1-I5).

However, I don't think this means the two approaches are equally good. E2 needed a design retry in three out of five issues, while the default configuration got approved in the first review every time.

The clearest example was I2. The implementer's tests missed a case where `load_glossary` was called twice before the extension was loaded. The reviewer caught this, sent the implementation back, and an additional round was needed.

So I'd say my prediction was partially supported. We didn't see more failures in the final results, but the reviewer had to do more work to catch problems that the implementer's own tests missed.

There was also a cost difference: E2 on I2 cost $0.77 compared to $0.43 for the default configuration.

One important limitation is that even our hidden tests didn't cover the missed case. So we can't claim the reviewer caught something that the hidden test suite independently verified.

## Where the reviewer was wrong
We didn't observe any incorrect reviewer verdicts in our experiments. It got all 15 seeded PR verdicts right, and every PR it approved in the pipeline passed the hidden tests.

However, I wouldn't say the reviewer is completely reliable just because we didn't observe a mistake.

There were a couple of minor issues:

- It flagged a missing changelog entry as a minor issue, even though the original issue never asked for one.
- One of our deterministic checks incorrectly reported a test as deleted when it wasn't. This was a problem with our check, not the reviewer, and it didn't affect the final verdict.

Overall, the reviewer performed well, but our sample is too small to establish that it will always make the right decision.

## Hindsight
If I were to repeat the project, these would be my first changes:

- **Use harder seeded bugs.** Our E1 experiment had all configurations scoring 5/5, so it was difficult to distinguish their actual capabilities. I'd introduce more subtle and realistic bugs.
- **Test the complete workflow on GitHub earlier.** We encountered three infrastructure issues during the experiments: an empty secret, missing gate permissions, and a bug in our build check. Testing the entire setup earlier would have saved time and prevented some misleading results.
- **Run each configuration multiple times.** AI models aren't deterministic, so a single run isn't enough to draw strong conclusions. Repeated runs would give us more confidence in the results.

I'd also reconsider using Opus for the reviewer. Based on E1, Sonnet seems like a reasonable cheaper alternative, although I'd want harder experiments before making that change permanent.

## Limitations
- **Small sample size:** We only tested five issues and five seeded PRs, with mostly one run per configuration. This makes it difficult to generalise our results, especially because AI models can produce different outputs across runs.
- **Possible experimenter bias:** The issues, seeded bugs and hidden tests were all created by the same team that built the workflow. This means our experiments might unintentionally favour our own system.
- **Limited independence of issues:** Issue I1 reused the A2 bug, and the clarification for I5 was provided by the experimenter. This means the issues weren't entirely independent of the people conducting the experiment.
- **Build-check bug:** One of our own checks was faulty before PR #22. This caused unnecessary implementation failures and increased the number of attempts, potentially affecting our measurements.
- **Same model family:** Although we used different Claude models for the implementer and reviewer, they belong to the same model family. So we haven't really established whether using a completely different model family would perform better.
- **Cost estimates:** Our costs are based on Claude Code's list-price equivalents. We used a subscription token rather than an API key with actual billed usage, so these are estimates rather than directly measured expenses.

My overall position: I think the strongest takeaway from this project is that separating implementation, testing and review can make an AI coding workflow more controlled and accountable. Our experiments show promising results, particularly with the independent reviewer, but they don't yet prove that the system will work equally well on larger or more difficult real-world projects. I'd rather make that distinction clear than overclaim based on a small number of successful runs.
