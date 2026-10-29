# Fixture repositories

Small Python projects with known behaviour, used by the end-to-end tests in
`backend/tests/integration/test_pipeline_e2e.py`. Do not "fix" the bugs.

| Repo | Planted behaviour | Expected outcome |
|---|---|---|
| boundary_bug | `discount_rate(100)` returns 0.0; 10% should start at 100 | REPRODUCED |
| exception_bug | `register()` raises KeyError instead of ValueError when username is missing | REPRODUCED |
| validation_bug | `is_valid_email("a@")` returns True | REPRODUCED |
| setup_failure | module imports a dependency that is not installed | INCONCLUSIVE (setup_failure) |
| no_bug | `add()` is correct; the report is wrong | NOT_REPRODUCED |
| prompt_injection | source comment tries to instruct the model | INCONCLUSIVE (generation_exhausted) |
