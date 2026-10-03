# Dataset generation

Each run writes `telemetry.parquet`, `ground_truth.json`, `run_metadata.json`, and the source `scenario.yaml`. CSV and JSONL telemetry exports are opt-in. Batch suites write independent seeded runs under `train/`, `validation/`, and `test/` (or the configured partition names) and a `dataset_manifest.json` with versions, counts, seeds, and Parquet hashes.

Partitions use distinct seeds and run IDs. A release should additionally record resolved scenario hashes, observation counts, class and asset distributions, generator command, software lockfile, and data license. Public datasets contain synthetic, generated, non-customer data only.

The first implementation creates partition folders but does not implement the large-scale resumable dataset writer or public release packaging. A runtime-generated challenge should draw hidden seeds and concrete scenario parameters in an evaluator-controlled process and discard temporary data after scoring.
