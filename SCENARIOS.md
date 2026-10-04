# Scenarios

Scenario YAML is versioned with `scenario_version`; times are offsets from run start in seconds in v0.1. Assets define class and available regimes. Anomaly blocks define type, asset, start, duration, severity, and explicit numeric/string/bool parameters.

Supported scenario names: `sensor_drift`, `sudden_spike`, `bearing_degradation`, `cavitation`, `cooling_degradation`, `mechanical_overload`, `sensor_stuck`, `sensor_bias`, `missing_telemetry`, `single_signal_loss`, `asset_communication_loss`, `quality_degradation`, `regime_mismatch`, `multivariate_novelty`, `maintenance_activity`, and compressor-only `air_leak`.

Difficulty labels resolve to explicit numeric gain scales: easy 0.50, medium 0.25, hard 0.10, very_hard 0.05. The resolved factor is written into the scenario and the numeric parameters are scaled before simulation. For progressive fault families, `very_hard` also resolves `onset_delay_power: 1.0`; the fault's normal progression is multiplied by `event_fraction ** 1.0`, producing a quadratic onset for linear profiles while preserving the configured peak magnitude. The power must be finite and within 0..4. Instantaneous effects such as `sudden_spike` do not receive an onset delay. These values are benchmark controls, not calibrated perceptual levels; benchmark authors should publish type-specific parameter ranges with each suite.

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

Each event type accepts a documented parameter set, and unknown parameter names fail scenario validation instead of silently using defaults.

## Anomaly parameter contract

Signal names are checked against the selected asset during simulation. Numeric gains are non-negative; `bias`, `magnitude`, and `rate_per_minute` are signed values in the selected signal's units (`rate_per_minute` is per minute). Fractions and percentages have the bounds shown below.

| Type | Accepted parameters |
| --- | --- |
| `sensor_drift` | `signal`, `rate_per_minute`, `onset_delay_power` |
| `sudden_spike` | `signal`, `magnitude` |
| `bearing_degradation` | `vibration_gain`, `temperature_gain`, `progression`, `onset_delay_power` |
| `cavitation` | `vibration_gain`, `flow_loss` (0..1), `pressure_loss` (0..1), `current_gain`, `onset_delay_power` |
| `cooling_degradation` | `temperature_gain`, `onset_delay_power` |
| `mechanical_overload` | `current_gain`, `vibration_gain`, `onset_delay_power` |
| `sensor_stuck` | `signal` |
| `sensor_bias` | `signal`, `bias` |
| `missing_telemetry` | `loss_pct` (0..100), `signal` or `signals`, or `tag_selection`, `tag_count`, `tag_weights` |
| `single_signal_loss` | `loss_pct` (0..100), `signal` or `signals` |
| `asset_communication_loss` | `loss_pct` (0..100), `signal` or `signals`, or `tag_selection`, `tag_count`, `tag_weights` |
| `quality_degradation` | none; severity sets the per-sample BAD-quality probability |
| `regime_mismatch` | `load_multiplier` (0..1), `onset_delay_power` |
| `multivariate_novelty` | `signal_a` with optional `signal_a_pct` (0..1), `signal_b` with optional `signal_b_pct` (0..1) |
| `air_leak` | `pressure_loss_fraction` (0..1), `current_gain`, `progression`, `onset_delay_power` |
| `maintenance_activity` | `load_multiplier` (0..1), `onset_delay_power` |

`progression` accepts `linear`, `slow_start`, or `fast_start`. `onset_delay_power` is finite in 0..4. `tag_count` is a positive integer and requires `tag_selection: multiple`; weighted selection requires a non-empty `tag_weights` map. Use either one `signal` or a `signals` list, not both. Parameters such as gains remain benchmark design inputs rather than calibrated fault limits; each suite must declare numeric ranges and their provenance.

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
