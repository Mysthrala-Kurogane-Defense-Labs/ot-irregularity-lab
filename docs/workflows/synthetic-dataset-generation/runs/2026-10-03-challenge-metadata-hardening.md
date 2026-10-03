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
- The changes were published in commit `459e5e27f325190981dcfeea3d19a9d40a42c392`; GitHub Actions run [37146984474](https://github.com/Mysthrala-Kurogane-Defense-Labs/ot-irregularity-lab/actions/runs/37146984474) passed both core and OPC UA jobs.

## Limits

The first hardening change checks artifact-level metadata disclosure across seeded repeated cases; it is not an external red-team review or a comprehensive challenge threat model. Docker resource limits and writable output remain subject to the boundaries recorded in `ROADMAP.md`.

## Independent challenge distribution follow-up

- Added `suites/challenge-v0.1.yaml`, with public weighted distributions that emphasize low-intensity degradation, multivariate novelty, data loss, communication loss, operating transitions, varied assets and sampling cadence.
- Added optional `--challenge-suite`; when selected, the evaluator samples from its `scenario` and `generation` blocks.
- Added a generator test verifying the separate profile controls generated duration/cadence and its scenario identifier is not exposed in model-visible metadata or ground truth.
- Removed `observed_start`/`observed_end` fields from challenge ground truth output as well; these evaluator-derived timestamps are unnecessary to the post-inference scoring path, which falls back to event start/end.
- Focused challenge tests and Ruff passed locally. These distribution changes have not yet been pushed or CI-verified.
- The independent distribution and metadata changes were published in commit `98944607c692cd9f0fa02ecdcead30a192fcf761`; Actions run [37147259217](https://github.com/Mysthrala-Kurogane-Defense-Labs/ot-irregularity-lab/actions/runs/37147259217) passed core and OPC UA.
