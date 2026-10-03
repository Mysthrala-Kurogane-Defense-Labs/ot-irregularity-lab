# OT Irregularity Lab

OT Irregularity Lab is an independent, open source preview toolkit for generating and replaying synthetic industrial telemetry with known, separately stored ground truth. It is model-agnostic: it contains no anomaly detector and makes no product, cloud, or customer-data integration a requirement.

All generated data is synthetic, generated, and non-customer data. Process simulation runs without OpenPLC or protocol services. Apache-2.0 applies to the software; dataset releases declare their own data license and version.

## Preview status

Python 3.12+, `uv`, NumPy, Polars, PyArrow, Pydantic, and PyYAML. It supports coupled process models for CNC, pump, compressor, and conveyor; seeded Parquet generation; independent event and operating-regime ground truth; run replay; resumable randomized train/validation/test datasets; event and expected-cadence evaluation; multi-model comparison; ephemeral challenges; and optional OPC UA replay. The Docker profile is a baseline isolation profile, not a security certification. Process models remain simplified and uncalibrated; read [CALIBRATION.md](CALIBRATION.md) and [ROADMAP.md](ROADMAP.md) for limits.

```bash
uv sync --extra dev
uv run ot-lab generate --scenario scenarios/cnc-bearing-medium.yaml --seed 42 --output runs/cnc-0042
uv run ot-lab replay runs/cnc-0042
uv run ot-lab batch --suite suites/training.yaml --runs 100 --seed 42 --output datasets/training
uv run ot-lab dataset create --suite suites/training-v0.2.yaml --runs 3000 --seed 20261003 --output datasets/ot-irregularity-training-v0.2
```

For long runs, add `--resume` to keep per-run checkpoints after interruption. Re-run with the same suite, run count, seed, and dedicated output directory to continue generation.

The randomized training suite mixes normal process variation with seeded events across all 15 supported event families. Its realized class, event, asset, and regime distributions are recorded in the dataset manifest. See [the synthetic dataset design and source analysis](SYNTHETIC_DATASET_DESIGN.md) for the sampling choices and limits.

The 1,000-run [OT Irregularity Training Dataset v0.3.0](https://github.com/Mysthrala-Kurogane-Defense-Labs/ot-irregularity-lab/releases/tag/dataset-v0.3.0) is published under CC BY 4.0; [v0.2.0](https://github.com/Mysthrala-Kurogane-Defense-Labs/ot-irregularity-lab/releases/tag/dataset-v0.2.0) remains available as a historical artifact. The merged `train.parquet`, `validation.parquet`, and `test.parquet` files contain telemetry only; per-run ground truth is stored separately. A more complete roadmap, including current limitations, lives in [ROADMAP.md](ROADMAP.md).

The model input is `telemetry.parquet`; never pass `ground_truth.json` or `run_metadata.json` to a model submission. The evaluator reads predictions and ground truth in a separate process. Do not mount ground truth into inference containers.

Optional protocol replay adapters are documented in [PROTOCOLS.md](PROTOCOLS.md). The core generator does not require protocol emulators.

Current public-source calibration evidence and its limits are recorded in [CALIBRATION.md](CALIBRATION.md); process dynamics remain illustrative until independently calibrated.

## Repository guide

- [Architecture](ARCHITECTURE.md)
- [Canonical telemetry schema](TELEMETRY_SCHEMA.md)
- [Scenario definitions](SCENARIOS.md)
- [Process models](PROCESS_MODELS.md)
- [Datasets and partitions](DATASETS.md)
- [Benchmark protocol](BENCHMARK.md)
- [Contributing](CONTRIBUTING.md)

## Scope

This is an independent project. It does not depend on Kurogane Hub, MKDL infrastructure, a cloud service, or an ML package. Protocol emulation (OpenPLC, Modbus, OPC UA, MQTT) may be added as optional adapters; the simulation core remains usable on its own.
