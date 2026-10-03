# Normal process variation

## Scope

Increase event-free process diversity for training and false-positive stress without adding anomaly labels or detector-specific behavior.

## Changes

- Generic assets accept scenario-recorded per-asset `load_scale`, `actuator_tau_s`, `thermal_time_constant_scale`, and `sensor_noise_scale` parameters.
- Suite generation resolves numeric ranges from the run seed before Pydantic validation and writes concrete values into each run's preserved `scenario.yaml` and scenario hash.
- `normal-operation-v0.1.yaml` varies load setpoint (0.85–1.15), sensor-noise scale (0.8–1.25), and thermal-time-constant scale (0.75–1.4), in addition to already sampled assets, regimes, environment, cadence, and jitter.
- Added a separate `false-positive-stress-v0.1.yaml` suite with cold/warm initial temperatures, rapid recipe/load changes, high load, planned maintenance, shutdown/restart, broad ambient ranges, and up to 80 ms sampling jitter. It has no anomaly templates.
- Documented that these ranges are synthetic benchmark design choices, not industrial population estimates.

## Validation

- Thirty independent seeds stayed within all declared parameter ranges and emitted no anomalies.
- Same-seed sampled process profiles and resolved values reproduced exactly.
- Generated a 20-run false-positive smoke dataset: 147,963 observations, 20 normal runs, zero events; all eight configured regimes were represented in ground truth.
- Full `uv run --python 3.12 pytest -q`, Ruff, and `git diff --check` passed locally before commit.

## Limits

The ranges create controlled variability around simple coupled equations; they do not establish field distributions or validate high-fidelity process physics. Normal-operation false-positive stress scenarios remain distinct from anomaly labels.
