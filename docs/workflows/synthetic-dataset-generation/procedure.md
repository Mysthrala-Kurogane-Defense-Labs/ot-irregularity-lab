# Generate and validate an OT Irregularity dataset

## Purpose

Generate a reproducible, model-agnostic synthetic dataset from a versioned suite and verify its partitions, independent ground truth, hashes, and replay behavior.

## Procedure

1. Confirm a clean checkout on the intended simulator version; inspect `suites/training-v0.2.yaml` and its declared sampling weights/data license.
2. Select a fresh, empty output path. Do not overwrite a non-empty directory; the CLI fails closed to prevent stale runs from entering a new manifest.
3. Run `uv run ot-lab dataset create --suite <suite.yaml> --runs <N> --seed <seed> --output <dataset-path>`.
4. Verify the manifest run/observation counts, independent seeds, per-partition class and event distribution, and every partition Parquet row count/hash.
5. Verify event records resolve to affected signals, the actual regime intervals cover each run, and no same-asset events overlap in randomly composed runs.
6. Replay at least one normal run and one event-bearing run from different partitions; compare logical Parquet rows and ground-truth JSON.
7. Keep model inputs to `train.parquet`, `validation.parquet`, or `test.parquet`. Do not provide per-run `ground_truth.json`, scenario, or metadata to an evaluated model.
8. Record the suite, simulator, schema versions, command, seed, dataset path, hashes, results, and limitations in a dated run record.

## Evidence boundaries

The generated telemetry is synthetic and based on simplified process models. Real dataset studies inform coverage design, not plant-failure priors or physical calibration. Dataset publication requires the license declared in the suite and a separate artifact integrity check. Local tests do not substitute for GitHub Actions CI.
