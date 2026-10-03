# Ephemeral challenge metadata hardening

## Objective

Continue the platform goal by checking repeated runtime-generated cases for seed and scenario leakage while preserving randomized coverage.

## Finding and change

Inspection found that `generate_challenge` removed the seed and scenario hash from `run_metadata.json`, and omitted `scenario.yaml`, but still exposed `scenario_id` and `scenario_version`. The generator now removes both fields before returning the model input. Ground truth continues to be stored separately for the evaluator; event parameters are removed from challenge ground truth output as before.

## Validation

- Added a 20-seed regression that writes ephemeral cases and checks hidden run ID, no seed/scenario identifier/version/hash, no resolved scenario file, no event parameters, and variation in public-profile outcomes.
- `uv run --python 3.12 pytest tests/test_challenge.py -q`: 6 passed.
- `uv run --python 3.12 pytest -q`: full suite passed.
- `uv run --python 3.12 ruff check src tests`: passed.
- `uv lock --check`: passed.
- `git diff --check`: passed.
- Changes are local and not yet committed or CI-verified.

## Limits

The challenge still samples the public training suite distribution. This check covers artifact-level metadata disclosure across seeded repeated cases; it is not an external red-team review or a comprehensive challenge threat model. Docker resource limits and writable output remain subject to the boundaries recorded in `ROADMAP.md`.
