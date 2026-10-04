# OT Irregularity Lab

OT Irregularity Lab is an independent, open source preview toolkit for generating and replaying synthetic industrial telemetry with known, separately stored ground truth. It is model-agnostic: it contains no anomaly detector and makes no product, cloud, or customer-data integration a requirement.

Current public software release: [v0.3.1](https://github.com/Mysthrala-Kurogane-Defense-Labs/ot-irregularity-lab/releases/tag/v0.3.1). The unreleased working tree targets v0.4.0 and adds randomized compressor air-leak cases; see the open [implementation PR](https://github.com/Mysthrala-Kurogane-Defense-Labs/ot-irregularity-lab/pull/5).

Current dataset release: [OT Irregularity Dataset v0.5.0 (3,000 runs)](https://github.com/Mysthrala-Kurogane-Defense-Labs/ot-irregularity-lab/releases/tag/dataset-v0.5.0). Telemetry and labels are distributed as separate archives. See the [generation and verification record](docs/workflows/synthetic-dataset-generation/runs/2026-10-04-training-v0.5-3000.md).

All generated data is synthetic, generated, and non-customer data. Process simulation runs without OpenPLC or protocol services. Apache-2.0 applies to the software; dataset releases declare their own data license and version.

## Preview status

Python 3.12+, `uv`, NumPy, Polars, PyArrow, Pydantic, and PyYAML. It supports coupled process models for CNC, pump, compressor, and conveyor; seeded Parquet generation; independent event and operating-regime ground truth; run replay; resumable randomized train/validation/test datasets; event and expected-cadence evaluation; multi-model comparison; ephemeral challenges; and optional OPC UA replay. The Docker profile is a baseline isolation profile, not a security certification. Process models remain simplified and uncalibrated; read [CALIBRATION.md](CALIBRATION.md) and [ROADMAP.md](ROADMAP.md) for limits.

```bash
uv sync --extra dev
uv run ot-lab generate --scenario scenarios/cnc-bearing-medium.yaml --seed 42 --output runs/cnc-0042
uv run ot-lab replay runs/cnc-0042
uv run ot-lab batch --suite suites/training.yaml --runs 100 --seed 42 --output datasets/training
uv run ot-lab dataset create --suite suites/training-v0.5.yaml --runs 1000 --seed 20261005 --output datasets/ot-irregularity-training-static-head-candidate
```

For long runs, add `--resume` to keep per-run checkpoints after interruption. Re-run with the same suite, run count, seed, and dedicated output directory to continue generation.

The v0.5 candidate suite is experimental until a release-scale manifest confirms adequate per-partition event coverage; its air-leak effect is qualitative and synthetic.

The versioned randomized training suites mix normal process variation with seeded events across 15 event families in v0.2 and 16 in v0.3. Its realized class, event, asset, and regime distributions are recorded in the dataset manifest. See [the synthetic dataset design](SYNTHETIC_DATASET_DESIGN.md) and [public dataset pattern review](DATASET_PATTERN_REVIEW.md) for sampling evidence and limits.

For event-free runs with randomized assets, shifts, startup/shutdown, ambient changes, cadence, and jitter, generate `suites/normal-operation-v0.1.yaml` with `uv run ot-lab dataset create --suite suites/normal-operation-v0.1.yaml --runs 1000 --seed 42 --output datasets/normal-v0.1`. This suite is useful for studying false alarms during ordinary transitions; it does not establish field-normal limits.

The 1,000-run [OT Irregularity Training Dataset v0.3.0](https://github.com/Mysthrala-Kurogane-Defense-Labs/ot-irregularity-lab/releases/tag/dataset-v0.3.0) is published under CC BY 4.0; [v0.2.0](https://github.com/Mysthrala-Kurogane-Defense-Labs/ot-irregularity-lab/releases/tag/dataset-v0.2.0) remains available as a historical artifact. The merged `train.parquet`, `validation.parquet`, and `test.parquet` files contain telemetry only; per-run ground truth is stored separately. A more complete roadmap, including current limitations, lives in [ROADMAP.md](ROADMAP.md).

The model input is `telemetry.parquet`; never pass `ground_truth.json` or `run_metadata.json` to a model submission. The evaluator reads predictions and ground truth in a separate process. Do not mount ground truth into inference containers.

Run fresh hidden Docker cases with a separate challenge distribution: `uv run ot-lab challenge --suite suites/training-v0.5.yaml --challenge-suite suites/challenge-v0.4.yaml --image MODEL_IMAGE --cases 100 --output results/model-a`. Every case gets a new container and OS-generated seed. The command retains only pooled metrics and an aggregate report; predictions, telemetry, ground truth and resolved case details are temporary.

Generate large train/validation/test datasets with deterministic process workers: `uv run ot-lab dataset create --suite suites/normal-operation-v0.1.yaml --runs 1000 --seed 424242 --workers 4 --output datasets/normal-v1`. The default worker count is one; see [BENCHMARK.md](BENCHMARK.md) for measured throughput and its limits.

Optional OPC UA and Modbus/TCP replay adapters are documented in [PROTOCOLS.md](PROTOCOLS.md). The core generator does not require protocol emulators.

Current public-source calibration evidence and its limits are recorded in [CALIBRATION.md](CALIBRATION.md); process dynamics remain illustrative until independently calibrated.

To analyze a locally obtained, CC BY 4.0 MetroPT-3 CSV without adding it to the repository, use `uv run ot-lab calibration analyze-metropt --input PATH_TO_CSV --output calibration/metropt-3-summary.json`. The report contains aggregate statistics and source hash only. An opt-in compressor `process_profile: metropt3_rail_apu` uses a limited, documented subset of those observations; it is not a digital twin and does not alter the generic compressor model.

## Repository guide

- [Architecture](ARCHITECTURE.md)
- [Canonical telemetry schema](TELEMETRY_SCHEMA.md)
- [Scenario definitions](SCENARIOS.md)
- [Process models](PROCESS_MODELS.md)
- [Datasets and partitions](DATASETS.md)
- [Dataset patterns and evidence](DATASET_PATTERN_REVIEW.md)
- [Benchmark protocol](BENCHMARK.md)
- [Contributing](CONTRIBUTING.md)

## Scope

This is an independent project. It does not depend on Kurogane Hub, MKDL infrastructure, a cloud service, or an ML package. Protocol emulation (OpenPLC, Modbus, OPC UA, MQTT) may be added as optional adapters; the simulation core remains usable on its own.
