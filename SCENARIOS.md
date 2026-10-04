# Scenarios

Scenario YAML is versioned with `scenario_version`; times are offsets from run start in seconds in v0.1. Assets define class and available regimes. Anomaly blocks define type, asset, start, duration, severity, and explicit numeric/string/bool parameters.

Supported scenario names: `sensor_drift`, `sudden_spike`, `bearing_degradation`, `cavitation`, `cooling_degradation`, `mechanical_overload`, `sensor_stuck`, `sensor_bias`, `missing_telemetry`, `single_signal_loss`, `asset_communication_loss`, `quality_degradation`, `regime_mismatch`, `multivariate_novelty`, `maintenance_activity`, and compressor-only `air_leak`.

Difficulty labels resolve to explicit numeric gain scales: easy 0.50, medium 0.25, hard 0.10, very_hard 0.05. The resolved factor is written into the scenario and the numeric parameters are scaled before simulation. This is a starting convention, not a universal perceptual calibration across unrelated anomaly types; benchmark authors should publish type-specific parameter ranges with each suite.

For generated multi-run datasets, `suites/training-v0.2.yaml` preserves the original 15-family distribution. `suites/training-v0.3.yaml` adds seeded `air_leak` scenarios with numeric distributions for onset, duration, severity, progression and signal effects. The generator samples settings from each run's independent seed and saves the resolved scenario beside that run. Research and licensing boundaries are described in [DATASET_PATTERN_REVIEW.md](DATASET_PATTERN_REVIEW.md).

`suites/training-v0.4.yaml` adds a versioned per-asset process-profile distribution. It selects either the generic pump or the optional `centrifugal_vfd` model for each pump, and samples rated speed, flow, pressure, efficiency, electrical assumptions and thermal rise from explicit numeric ranges. Resolved values are stored in each run's scenario and the dataset manifest reports realized profile counts. `suites/challenge-v0.3.yaml` independently samples the same profile family and parameter ranges for ephemeral hidden cases; neither profile name nor parameters are exposed to the model container.

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

All three communication-loss types (`missing_telemetry`, `single_signal_loss`, and `asset_communication_loss`) use `loss_pct` as the per-sample base probability, multiplied by event `severity` (0..1). Thus `loss_pct: 40` and `severity: 0.5` yields a 20% expected loss rate on the selected tags. `asset_communication_loss` defaults to every tag; it can be scoped with `signal`, `signals`, or `tag_selection`. `tag_selection: weighted` chooses one tag deterministically for a given run seed and event from `tag_weights`, whose values are non-negative weights (omitted tags have weight zero):

```yaml
parameters:
  loss_pct: 40
  tag_selection: weighted
  tag_weights:
    motor_current_a: 3
    pressure_bar: 1
```

Weights control which tag is selected, while `loss_pct` controls how often that tag is omitted. The selection seed is independent of the sample index, so the same tag remains selected throughout the event. The per-sample loss mask is deterministic for a run seed, event, tag, and sample timestamp.

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
