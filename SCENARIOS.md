# Scenarios

Scenario YAML is versioned with `scenario_version`; times are offsets from run start in seconds in v0.1. Assets define class and available regimes. Anomaly blocks define type, asset, start, duration, severity, and explicit numeric/string/bool parameters.

Supported initial scenario names: `sensor_drift`, `sudden_spike`, `bearing_degradation`, `cavitation`, `cooling_degradation`, `mechanical_overload`, `sensor_stuck`, `sensor_bias`, `missing_telemetry`, `single_signal_loss`, `asset_communication_loss`, `quality_degradation`, `regime_mismatch`, `multivariate_novelty`, and `maintenance_activity`.

Difficulty labels resolve to explicit numeric gain scales: easy 0.50, medium 0.25, hard 0.10, very_hard 0.05. The resolved factor is written into the scenario and the numeric parameters are scaled before simulation. This is a starting convention, not a universal perceptual calibration across unrelated anomaly types; benchmark authors should publish type-specific parameter ranges with each suite.

For generated multi-run datasets, `suites/training-v0.2.yaml` adds weighted asset/regime profiles and fault templates with numeric distributions for onset, duration, severity, and affected-signal behavior. The generator samples those settings from each run's independent seed and saves the resolved scenario beside that run. The suite's intended distribution and its evidence basis are described in [SYNTHETIC_DATASET_DESIGN.md](SYNTHETIC_DATASET_DESIGN.md).

```yaml
scenario_id: cnc-bearing-medium
scenario_version: 1.0.0
run_id: cnc-0042
duration_s: 600
sampling_interval_ms: 1000
sampling_jitter_ms: 10
assets:
  - asset_id: CNC-01
    asset_class: cnc
anomalies:
  - type: bearing_degradation
    asset: CNC-01
    start: 240
    duration: 180
    severity: 0.4
    parameters:
      vibration_gain: 0.20
      temperature_gain: 0.08
```

The initial implementation applies deterministic effects for each defined type; cadence/rate loss is configured by numeric parameters. Expand scenario coverage with tests and document the affected signals for each asset class.

For `missing_telemetry`, use `loss_pct` with optional `signal`, `signals`, or a deterministic tag-selection policy. `tag_selection` accepts `all` (default), `single`, or `multiple`; `tag_count` sets the number selected for `multiple`. Selection is stable for the same seed/event/sample. `single_signal_loss` accepts `signal` or `signals`; otherwise it selects one tag. Unknown tags and impossible counts fail validation during simulation. For a full asset communication outage, use `asset_communication_loss`.

```yaml
anomalies:
  - type: missing_telemetry
    asset: PUMP-01
    start: 120
    duration: 30
    parameters:
      loss_pct: 25
      tag_selection: multiple
      tag_count: 3
```
