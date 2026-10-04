# Numeric difficulty profiles for progressive faults

## Scope

Implement the original `very_hard` requirement as an explicit numeric, reproducible slow-onset profile while keeping the simulator independent of detector outcomes.

## Changes

- `resolve_profiles` already scaled configured magnitudes for easy/medium/hard/very_hard to 0.50/0.25/0.10/0.05. It also wrote an unused `progression_rate_scale`; removed that dead parameter.
- `very_hard` now resolves `onset_delay_power: 1.0` for progressive fault types. The normal progression is multiplied by `event_fraction ** onset_delay_power`, so a linear effect becomes quadratic in time, remains at its full resolved peak at the end, and does not slow instantaneous spikes.
- Validate `onset_delay_power` as a finite number in 0..4 and apply the onset curve to bearing degradation, cavitation, air leaks, cooling degradation, mechanical overload, sensor drift, regime mismatch and maintenance activity.
- Documented that these profiles are benchmark controls, not a perceptually or physically calibrated universal difficulty scale.

## Validation

- Targeted difficulty, air-leak and onset tests: 11 passed.
- Full WSL suite with development, OPC UA, Modbus and lint dependencies: passed; one platform-specific test skipped.
- Ruff, `uv lock --check`, and `git diff --check`: passed.
- Regression asserts that the very-hard bearing effect is 25% of its resolved 5% peak halfway through the event and reaches that peak at event end; malformed onset powers are rejected.
- A subsecond regression verifies progression uses the actual event duration rather than a one-second floor.

## Limits

Severity and difficulty remain separate multipliers: severity scales event magnitude; difficulty scales authored magnitudes and, for very-hard progressive faults, delays the curve. Effect ranges still require asset/type-specific evidence. This profile does not model detector sensitivity or alter parameters based on detector scores.
