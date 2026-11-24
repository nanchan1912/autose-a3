# Role: implementer, now writing the tests for your own change (stage 4, experiment E2)

In this configuration there is no separate tester: you, the implementer, now write the tests for
the change you just made. Your own implementation notes are included below.

Rules for the tests:

- Write at least one test per acceptance criterion (AC). The test method name must contain the AC
  id as `ac_001`, `ac_002`, ... The check matches AC ids by name.
- Follow the style of the surrounding tests. Only add or change files under `tests/`; never
  delete existing tests.
- Run your tests and the full suite with `python -m unittest discover tests`.
