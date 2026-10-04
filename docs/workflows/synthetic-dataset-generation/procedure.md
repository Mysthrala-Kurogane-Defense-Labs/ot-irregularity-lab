# Generate and validate an OT Irregularity dataset

## Purpose

Generate a reproducible, model-agnostic synthetic dataset from a versioned suite and verify its partitions, independent ground truth, hashes, and replay behavior.

## Procedure

1. Confirm a clean checkout on the intended simulator version; inspect the exact versioned suite (currently `training-v0.3.yaml`) and its declared sampling weights/data license.
2. Select a fresh output path. Standard generation requires it to be empty and publishes atomically. For long runs, use `--resume`; it stores per-run checkpoints in the output directory. Resume only with the same suite contents, run count, seed, simulator version, and schema version.
3. Run `uv run ot-lab dataset create --suite <suite.yaml> --runs <N> --seed <seed> --output <dataset-path> [--resume]`.
4. Verify the manifest run/observation counts, independent seeds, per-partition class and event distribution, all required event families, and every partition Parquet row count/hash. If the suite declares `coverage_by_partition`, verify the minimum template count in each partition and review its effect on normal/anomalous proportions. Treat coverage constraints as benchmark design, not field prevalence.
5. Verify event records resolve to affected signals, the actual regime intervals cover each run, and no same-asset events overlap in randomly composed runs.
6. Replay at least one normal run and one event-bearing run from different partitions; compare logical Parquet rows and ground-truth JSON.
7. Keep model inputs to `train.parquet`, `validation.parquet`, or `test.parquet`. Do not provide per-run `ground_truth.json`, scenario, or metadata to an evaluated model.
8. Record the suite, simulator, schema versions, command, seed, dataset path, hashes, results, and limitations in a dated run record.
9. For a public partition release, run `ot-lab dataset package` with an explicit dataset version and license notice. Confirm the source hashes, telemetry and labels ZIPs, embedded seed-free manifests, and final archive hashes. Packaging accepts only the expected `<partition>.parquet` file, resolves manifest-derived files beneath the dataset root, and rejects unsafe run IDs. The telemetry ZIP has no ground truth; its paired labels ZIP contains independent ground truth and allowlisted evaluation metadata, without seeds, scenarios or generation metadata. Keep labels private for blind evaluations. The original local generation manifest includes run seeds for replay; publish the package release manifest instead of placing that file in an independently shared partition archive.

Anomaly severity 0 suppresses injection and severity 1 applies configured magnitudes or rates. Intermediate severity scales continuous effects and seeded dropout/quality probabilities. Outcomes remain discrete per observation; severity changes their probability.

## Evidence boundaries

The generated telemetry is synthetic and based on simplified process models. Real dataset studies inform coverage design, not plant-failure priors or physical calibration. Dataset publication requires the license declared in the suite and a separate artifact integrity check. Local tests do not substitute for GitHub Actions CI.

## Analyze an external reference dataset

For MetroPT-3, download the CSV directly from the official UCI record under its CC BY 4.0 terms. Keep the source outside the checkout. Run `uv run ot-lab calibration analyze-metropt --input <source.csv> --output <aggregate-report.json>`, record the CSV SHA-256, input row count and report hash, and review that the output has no source rows. Do not adopt parameters from aggregate values without matching asset configuration, operating-state definitions, units and uncertainty. See `CALIBRATION.md` for limits.

For the UCI ZeMA hydraulic-system archive, keep the ZIP outside the checkout, record its SHA-256 and license attribution, then run `uv run ot-lab calibration analyze-hydraulic --input <source.zip> --output <aggregate-report.json>`. Review label coverage and isolated-group sample counts. The report contains cycle aggregates only; do not use the condition labels or aggregate effects as time-aligned fault onsets or generic pump calibration.

For the Bosch CNC HDF5 data, install `uv sync --extra calibration`, keep the downloaded data outside the checkout, pin the source Git commit, and run `uv run ot-lab calibration analyze-bosch-cnc --input-dir <data-directory> --source-revision <commit> --output <aggregate-report.json>`. Confirm the analyzer's file count, source manifest hash, label counts and machine/operation/timeframe group coverage. Its labels are process annotations, not fault mechanisms; its HDF5 arrays do not provide the acceleration unit, and their RMS values must not be copied into the canonical `mm/s` signal.
