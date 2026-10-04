# Type-specific anomaly parameter contract

## Scope

Make scenario fault inputs explicit and reject misspelled, out-of-domain or ineffective combinations before simulation.

## Changes

- Added an allowed-parameter registry for all 16 anomaly types. Unknown keys now fail Pydantic scenario validation instead of silently using defaults.
- Validate finite numeric inputs, gain/fraction bounds, loss percentage, load multiplier, progression curves, onset power, tag counts, tag selection policies and weighted signal maps.
- Keep `sensor_drift.rate_per_minute` and bias/magnitude signed where the effect supports either direction. `single_signal_loss` cannot select multiple tags; `signals` remains useful when it contains exactly one selected tag.
- Added the public parameter table in `SCENARIOS.md`.

## Validation

- Focused anomaly, selection, severity, challenge and difficulty tests: 29 passed.
- Full WSL suite with development, OPC UA, Modbus and lint dependencies: passed; one platform-specific test skipped.
- Ruff, `uv lock --check`, and `git diff --check`: passed.
- Existing versioned training/challenge suite generation tests passed under the new parameter registry.

## Limits

Signal compatibility depends on the selected asset and is checked during simulation. The accepted numeric ranges define safe simulator controls, not industrial limits or calibrated failure magnitudes. Versioned suites must continue to declare their sampling ranges and evidence boundaries.
