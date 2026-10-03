# OT Irregularity Lab

OT Irregularity Lab is an independent, open source toolkit for generating and replaying synthetic industrial telemetry with known, separately stored ground truth. It is model-agnostic: it contains no anomaly detector and makes no product, cloud, or customer-data integration a requirement.

All generated data is synthetic, generated, and non-customer data. Process simulation runs without OpenPLC or protocol services. Apache-2.0 applies to the software; a public dataset release will declare its own data license and version.

## First vertical slice

Python 3.12+, `uv`, NumPy, Polars, PyArrow, Pydantic, and PyYAML. It currently supports coupled process models for CNC, pump, compressor, and conveyor; seeded Parquet generation; independent `ground_truth.json`; run metadata; replay; and batch partition generation. Event evaluation and containerized challenge execution are planned interfaces, not implemented features in this first slice.

```bash
uv sync --extra dev
uv run ot-lab generate --scenario scenarios/cnc-bearing-medium.yaml --seed 42 --output runs/cnc-0042
uv run ot-lab replay runs/cnc-0042
uv run ot-lab batch --suite suites/training.yaml --runs 100 --seed 42 --output datasets/training
```

The model input is `telemetry.parquet`; never pass `ground_truth.json` or `run_metadata.json` to a model submission. The evaluator reads predictions and ground truth in a separate process. Do not mount ground truth into inference containers.

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
