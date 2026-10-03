# Dataset generation

Each run writes `telemetry.parquet`, `ground_truth.json`, `run_metadata.json`, and the resolved `scenario.yaml`. CSV and JSONL telemetry exports are opt-in. Batch suites write independent seeded runs under `train/`, `validation/`, and `test/` (or configured non-challenge partition names) and a `dataset_manifest.json` with versions, counts, disjoint seeds, observations, per-run scenario and artifact hashes, and class, event, and asset distributions. Every concrete ranged parameter is recorded in its run scenario so `replay` can reproduce that run exactly. The manifest describes the generated dataset; it is not a signed provenance attestation.

Partitions use distinct seeds and run IDs. A release should additionally record resolved scenario hashes, observation counts, class and asset distributions, generator command, software lockfile, and data license. Public datasets contain synthetic, generated, non-customer data only.

The initial implementation does not include a resumable large-scale writer or public dataset release packaging. Challenge generation draws a hidden runtime seed and concrete ranged parameters in an evaluator-controlled process, does not persist the resolved scenario/seed, and discards the temporary case after scoring.
