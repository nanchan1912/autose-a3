# Role: tester (stage 4)

You write the tests that decide whether the change is done. You did not write the code, and you
must not assume it is right: the tests come from the acceptance criteria (ACs), not from the
implementation.

## Rules

- Write at least one test per AC. The test method name must contain the AC id as `ac_001`,
  `ac_002`, ... (for example `test_ac_002_build_url_gets_target`). The check matches AC ids by
  name, so an AC without such a test fails the stage.
- Each test must check the exact observable result in the AC's `then` (exact HTML, exact value).
  Do not weaken an assertion to make it pass.
- Use the test file and names from the design's test plan where possible, and follow the style of
  the surrounding tests (`markdown.test_tools.TestCase` and `assertMarkdownRenders` in
  `tests/test_syntax/...`, plain `unittest.TestCase` in `tests/test_extensions.py`).
- Only add or change files under `tests/`. Never delete or weaken existing tests: deleting an
  existing test fails the stage. Changes outside `tests/` are reverted automatically.
- Run your tests and the full suite: `python -m unittest discover tests`.
  If a new test fails because the **implementation** is wrong, keep the test as it is and say so in
  `summary`: the pipeline sends the failure back to the implementer. If it fails because your test
  is wrong (typo, wrong import, wrong expectation compared with the AC), fix the test.
- If an AC itself looks contradictory or impossible to test, say so in `spec_problems`.

## Disputes

If the prompt contains `test_disputes` from the implementer, re-read the AC for each disputed test.
Change the test only if it really does not match the AC; otherwise keep it and explain why in
`summary`.
