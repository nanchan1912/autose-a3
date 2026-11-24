# Hidden acceptance tests

Two to four tests per issue, kept outside the repository while the runs were happening (as in A2) and
added here only after the last run. The agents never had access to them: they were not on the runner,
and the agents' checkout excludes `experiment/` anyway.

Run against a branch:  python scripts/run_hidden_tests.py --hidden experiment/hidden_tests <branch> ...
Results: results/hidden_tests.csv
