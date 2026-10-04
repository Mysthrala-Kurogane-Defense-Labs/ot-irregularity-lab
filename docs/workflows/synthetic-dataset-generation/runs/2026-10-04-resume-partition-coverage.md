# Resumable partition coverage integrity

## Scope

Regenerate a full v0.6.0 training candidate after anomaly-parameter and process-model changes, verifying partition-local forced family coverage and exact scenario reconstruction during resume.

## Finding

The first 3,000-run resumable generation attempt completed run writes but failed finalization at `train-00046` because its saved scenario hash differed from the deterministic reconstruction. `train` should force 50 air-leak cases for its 2,100-run partition, but `_resume_batch` passed the final loop's partition size (450) for every run. It therefore forced only 45 train cases and let run 46 use the random suite distribution. Finalization correctly rejected the mismatched scenario.

The incomplete attempt has no final dataset manifest or release package and is not accepted as a dataset candidate. It remains a local ignored checkpoint under `datasets/ot-irregularity-training-v0.6.0-rc2`; do not use or publish it.

## Changes

- Resume scenario reconstruction now passes `counts[partition]`, preserving each partition's declared coverage limit.
- Existing complete checkpoint runs are checked against the expected deterministic scenario hash before reuse, in addition to their seed.
- Added a regression with 70/15/15 partitions, 50 requested coverage cases, an interruption after two runs, resume, partition coverage assertions, and a deliberately corrupted saved scenario hash.

## Validation

- Focused resume and coverage tests: passed.
- Full WSL suite with development, OPC UA, Modbus and lint dependencies: passed; one platform-specific test skipped.
- Ruff, `uv lock --check`, and `git diff --check`: passed.

## Next validation

Generate a fresh v0.6.0 candidate into a new empty output path, then verify the complete manifest, partition Parquet hashes, seeds, all configured event families, representative replays and release-package checksums. Keep the release private until those checks complete.
