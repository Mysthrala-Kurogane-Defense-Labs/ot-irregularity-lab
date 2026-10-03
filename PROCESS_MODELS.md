# Process models

These are low-cost engineering relationships for reproducible dataset generation, not high-fidelity plant or safety models. Each asset has load, actuator, temperature, and vibration states. Regime load is an input to coupled equations; noise perturbs sensor/process values and never replaces the process equations.

- CNC: load drives spindle speed, power, feed, coolant pressure, vibration, and thermal target; temperature follows a first-order lag.
- Pump: RPM drives flow; a simple system curve relates RPM/load to pressure; load and pressure drive current; motor temperature lags its target.
- Compressor: load drives current, pressure, discharge/oil temperatures, and vibration.
- Conveyor: load drives current, speed, temperature, vibration, and photoeye rate.

## Versioned compressor profiles

`AssetSpec.process_profile` selects a model independently of the anomaly or evaluator. `generic` is the default and uses the illustrative generic compressor equations. `metropt3_rail_apu` opts into a profile informed by the aggregate MetroPT-3 report in `calibration/metropt-3-summary.json`; it is valid only for compressor assets. Each asset records `process_profile_version` (`1.0.0`) and may override explicit `process_parameters` in scenario YAML. Supported overrides include loaded/off current and pressure anchors, load and thermal time constants, and sensor-noise scales. Unknown parameters, non-finite values and non-positive time constants are rejected. A resolved scenario preserves overrides for replay and dataset provenance.

The MetroPT profile's mode-conditioned current and pressure envelopes are descriptive. The load mapping, thermal time constant, discharge-temperature and vibration equations remain clearly identified simulator assumptions; this profile is not a digital twin.

Generic process assets support reproducible per-asset overrides for `load_scale`, `actuator_tau_s`, `thermal_time_constant_scale`, and `sensor_noise_scale`. The normal-operation suite samples these in declared ranges so otherwise normal runs include distinct production setpoints, response speeds, and sensor variability. The numeric ranges are a benchmark design choice, not inferred industrial population distributions.

OFF, IDLE, WARMUP, LOW_LOAD, NORMAL_LOAD, HIGH_LOAD, COOLDOWN, and MAINTENANCE are scenario regime options. The baseline schedule has startup, load transitions/recipe changes, and shutdown. Add validated shift schedules and environmental profiles in the next phase.
