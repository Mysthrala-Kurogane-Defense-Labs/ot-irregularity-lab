# Scenarios

Scenario YAML is versioned with `scenario_version`; times are offsets from run start in seconds in v0.1. Assets define class and available regimes. Anomaly blocks define type, asset, start, duration, severity, and explicit numeric/string/bool parameters.

Supported initial scenario names: `sensor_drift`, `sudden_spike`, `bearing_degradation`, `cavitation`, `cooling_degradation`, `mechanical_overload`, `sensor_stuck`, `sensor_bias`, `missing_telemetry`, `single_signal_loss`, `asset_communication_loss`, `quality_degradation`, `regime_mismatch`, `multivariate_novelty`, and `maintenance_activity`.

There are no magical difficulty labels in the simulator. Suite authors may name a profile easy/medium/hard, but each resolved run must record numeric parameters. Example: `vibration_gain: 0.20` means a 20% increase; 0.10 is milder. A future suite resolver can publish ranges while drawing concrete values from its seed.

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
