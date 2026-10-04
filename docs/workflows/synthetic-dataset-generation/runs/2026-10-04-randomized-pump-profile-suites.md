# Randomized pump process-profile suites

## Scope

Make the optional centrifugal VFD pump profile available to synthetic training and hidden challenge generation, with explicit numeric parameter distributions, deterministic replay, manifest provenance, and no additional model input metadata.

## Changes

- Add `generation.asset_process_profiles`, which samples a versioned process profile and parameter ranges independently for each matching asset class.
- Add `training-v0.4.yaml` and `challenge-v0.3.yaml`; each samples generic or centrifugal VFD pump profiles at weights 3:1. VFD pump settings are resolved inside declared ranges for rated speed, flow, pressure, efficiency, voltage, power factor, idle current and thermal rise.
- Record per-run profile/version mappings and aggregate counts by profile in dataset manifests and seed-free partition release manifests.
- Copy selected asset definitions before applying sampled settings. Multi-seed testing caught and prevents mutation of reusable suite definitions across generated runs.

## Validation

- Focused tests passed for seeded profile sampling, at least 20 distinct VFD parameter sets over 240 seeds, old challenge metadata boundaries, package manifests and process-profile counts.
- Windows batch smoke: 80 runs, seed `20261004`, 2 workers; 925,812 observations. It realized 19 VFD and 42 generic pump assets, with VFD counts in train/validation/test of 14/3/2. Dataset-manifest SHA-256: `b868973c762b9a2ca79e3a051f53dd27f6102c688b9586dd59336c3d2e54a641`; suite SHA-256: `01751698ccb16153a98183d1f34ea18c77887593488a33ebd75a4e0d14e58a9b`.
- Replayed VFD run `train-00003`; both telemetry Parquet and ground-truth JSON hashes matched their generated artifacts.
- Four-case Docker Desktop challenge smoke with the local image generated only `metrics.json` and `report.html`. The aggregate metrics contain no process-profile names. Deterministic tests confirmed the challenge suite can sample VFD pump profiles; hidden case files were not retained.
- The fixed local example submission emitted many false alerts in this smoke. These results verify command execution only; they are not model-quality claims and were not used to tune simulator behavior.

## Limits

The numeric VFD parameter ranges are declared synthetic variation, not inferred population distributions or pump calibration. The small challenge smoke validates the artifact boundary for this implementation and is not a container escape assessment. The generated smoke dataset and challenge results remain outside the repository.
