# Synthetic dataset design

## Evidence used

OT Irregularity Lab does not copy public dataset records, labels, process traces, or code. The following public sources inform the generator design:

- The [Tennessee Eastman Process reference data at DTU](https://data.dtu.dk/articles/dataset/Tennessee_Eastman_Reference_Data_for_Fault-Detection_and_Decision_Support_Systems/13385936) contains 28 process faults across six operating modes, 500 independent random-seed simulations per fault/mode, and separate setpoint-change and mode-transition runs. This supports independent replicas and variation in operating context instead of reusing a single canonical trace.
- The [Tennessee Eastman simulator repository](https://github.com/camaramm/tennessee-eastman-profBraatz) distinguishes normal training/testing runs from runs for each fault. Its documented test trajectories are longer than training trajectories, illustrating why datasets should vary onset and run context and why partitions should be separated by complete runs.
- The [iTrust SWaT dataset description](https://www.sutd.edu.sg/itrust/itrust-labs/datasets/dataset-characteristics/swat/) describes 7 normal operating days followed by 4 days with 41 attack scenarios across 51 sensor/actuator signals. It also records normal startup/maintenance effects, a later six-attack collection, and a 100-hour clean operating run. This motivates dedicated normal stress cases and separate attack episodes, rather than treating every operational transition as a fault.
- [SKAB](https://github.com/waico/skab) contains 35 independent multivariate experiments, each with one anomaly, and supports both point and collective/change-point labels. This motivates exact event intervals and separate event-level and timestamp-level ground truth.
- The [Tennessee Eastman benchmark implementation used in a public fault-detection project](https://github.com/juyeoput/industrial-anomaly-detection) reports that some faults present small mean shifts and unusual multivariate relationships. The generator therefore includes low-amplitude, slow-progressing, and multivariate cases as configurable strata.

These datasets differ in plant physics, collection methods, labels, and access terms. Their reported attack or fault percentages are not universal production priors. The included suite uses explicit, editable benchmark sampling weights; users should document a different distribution when their evaluation question requires one.

## Training suite v0.2

`suites/training-v0.2.yaml` defines a complete sampling distribution:

- 35% expected normal runs and 65% expected event-bearing runs (realized proportions vary by seed and run count).
- Weighted single-asset, machining-cell, and four-asset plant profiles spanning CNC, pump, compressor, and conveyor assets.
- Independent variation in duration, 500/1000 ms cadence, jitter, ambient temperature and drift, PLC regime exposure, and weighted shift patterns.
- Fifteen supported event families with type-specific compatible assets, event onset and duration fractions, severity ranges, and physical/measurement parameters. An event-bearing run samples one or two distinct compatible event templates.
- Fault onset is kept within its run; event dynamics are sampled numerically and remain reproducible from the run seed and resolved `scenario.yaml`.
- The suite declares generated outputs as CC BY 4.0, with attribution to Mysthrala Kurogane Defense Labs and OT Irregularity Lab.

The default weights are a benchmark coverage choice, not an estimate of real plant incident frequency. A suite manifest reports actual per-partition normal/anomalous runs, event families, asset classes, regimes, seeds, and hashes so every generated release can disclose its realized mix.

## Generate a dataset

```bash
uv run ot-lab dataset create \
  --suite suites/training-v0.2.yaml \
  --runs 3000 \
  --seed 20261003 \
  --output datasets/ot-irregularity-training-v0.2
```

Each run is an independent simulation, assigned to train/validation/test by the declared proportions. The suite file is copied into the dataset root. Each run keeps its resolved scenario, Parquet telemetry, isolated event and operating-regime ground truth, run metadata, and SHA-256 entries in `dataset_manifest.json`. `ot-lab replay` can reconstruct any run using its stored scenario and seed.

Never split rows from one run across partitions. For benchmarking, use independent suite seeds and do not publish challenge seeds or resolved challenge scenarios.

## Interpretation limits

This is generated telemetry from simplified process models. Randomness supplies run-to-run variation, not measured uncertainty calibration. These traces are appropriate for software development, controlled benchmark research, and detector stress testing; they do not establish field performance, real failure prevalence, or exact physical fault signatures. Public release of generated data must carry a separate dataset license.
