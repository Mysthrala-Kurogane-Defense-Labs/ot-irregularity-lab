# Parallel dataset run generation

## Change

Added `--workers N` to `ot-lab batch` and `ot-lab dataset create`. Each worker receives an already seed-resolved scenario and writes only its own run directory. The parent process builds manifests and partition Parquet files in stable order after all workers finish. The default remains one worker. Worker count is recorded in the manifest and resumable checkpoint; a checkpoint can resume with a different worker count because it does not affect the seed plan or run outputs. Counts must be positive and no greater than the host-reported CPU count.

Workers use Python's `spawn` multiprocessing context rather than the platform default. Linux validation exposed a fork-after-NumPy/Polars-thread-pool hang in a parallel-batch test; `spawn` avoids inheriting those process-local locks while preserving the deterministic run plan.

## Validation

- 60 runs, normal-operation suite, seed 4242: one process 7.79 s (7.71 runs/s), two processes 5.15 s (11.66 runs/s), four processes 4.34 s (13.83 runs/s).
- Each mode produced 11,335,811 bytes, matching per-run telemetry and ground-truth hashes, and byte-identical train, validation and test Parquet files.
- Generated a 1,000-run normal dataset with four workers, seed 424242: 10,832,949 observations across 700/150/150 train/validation/test runs, all normal, 1,000 unique run seeds. Every run and partition hash and row count matched its manifest.
- Interrupted and resumed a 12-run checkpoint from one worker to four; per-run telemetry hashes matched a clean two-worker generation and the checkpoint was removed after finalization.
- Focused simulator tests and Ruff passed locally.

## Limits

The throughput measurements are from one Windows workstation and a small normal-operation suite. They do not establish a general speedup, large-storage bound, or performance envelope. Serial 1,000-run comparison was still running at the time this record was drafted. Docker challenge isolation is a separate open item in `ROADMAP.md` and is not closed by this change.
