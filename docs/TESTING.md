# Public and restricted test boundaries

## Public commands

Use an isolated Python3.12 environment and install requirements-dev.txt. Keep real service credentials and endpoint settings out of the test environment. Public fixtures are artificial; no live Tencent, CloudBase or model call is required.

```bash
# A. Public backend/runtime tests. The 22 exclusions are explicit deselections.
python -m pytest tests -m "not requires_restricted_registry" -q
# B. Agent intake, including the three previously failing route tests.
python -m pytest tests/test_poc_validation_agent.py tests/test_agent_intake_api.py -q
# C. CloudFunction synthetic contract tests, separate from A and B.
python -m pytest cloudfunction/tests -q
# D. Full collection, no marker filter.
python -m pytest tests cloudfunction/tests --collect-only -q
# E. Full execution, including the restricted-resource tests.
python -m pytest tests cloudfunction/tests -q
```

B is a subset of A. C is separate. Do not sum overlapping command totals. The default pytest.ini does not filter tests or auto-skip missing resources. Full execution is still expected to fail without the required authorized registry; report FULL_TEST_SUITE and its actual failure count.

## Historical restricted tests

22 existing tests carry requires_restricted_registry. Their bodies and assertions are unchanged. Six exercise benchmark API flows: without evaluation resources, 422 is a correct precondition rejection, and an old test expecting an accepted run may subsequently fail on a missing result URL. Sixteen directly require evaluator-side registry entries. Some assert historical exact outcomes, pass rates or a formal acceptance contract; those values must not be reverse-engineered into a public answer file.

For an authorized private verification run, the responsible data owner must supply the correct licensed/versioned registry outside the repository. Set CASE_REGISTRY_PATH explicitly in a separate controlled environment, keep real network executors disabled, and run the unmodified tests with `python -m pytest tests -m requires_restricted_registry -q`. A matching external data version and the corresponding public inputs are prerequisites; this candidate neither supplies nor validates that restricted data. Never upload it, and do not infer an all-pass result without running it.

## Independent synthetic coverage

tests/fixtures/synthetic_registry contains independently authored SYNTHETIC_DEMO_DATA, with a new case ID and an arbitrary CLARIFY rule. The canned runner returns a different action, so evaluation must reject it. Tests validate explicit loading, public/evaluator separation, binding checks, no evaluation rules reaching the executor, repeat aggregation, API rejection without rules, and completion with a rejected synthetic evaluation. These tests are not replacements for historical benchmark outcomes and never mount their files for historical tests.

The API's LIVE_POC context means an explicit acceptance contract; it does not turn a FIXTURE experiment into real model execution. Agent tests verify actual local asynchronous pipeline completion and error reporting, not enterprise efficacy.

Publication preserves existing Git history and uses a public-showcase mode without a general project license. Historical risk and separate contributor/media rights are not resolved by passing tests; see RIGHTS_AND_LICENSING.md.
