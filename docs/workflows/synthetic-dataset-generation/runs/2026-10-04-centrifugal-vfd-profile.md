# Centrifugal pump VFD process profile

## Scope

Add an opt-in, versioned process profile for a simplified variable-speed centrifugal pump. Preserve the generic pump equations and keep the simulator independent of anomaly detectors.

## Changes

- Added `process_profile: centrifugal_vfd` for pump assets, with explicit version `1.0.0`, parameter and engineering-envelope validation, and a normal-operation YAML example.
- Coupled first-order load response to speed; used approximate fixed-duty affinity relations for flow, pressure/head, and hydraulic power; derived a three-phase current estimate and thermal response from normalized power.
- Documented assumptions and official Grundfos references. No catalog curve values, third-party data, or proprietary curve digitization were included. Parameters are simulator examples, not manufacturer ratings.
- Bumped the simulator package version from `0.4.0` to `0.5.0`; telemetry and ground-truth schemas remain unchanged.

## Validation

- Focused WSL profile tests: passed (four tests covering affinity ratios, coupling, invalid parameters, and generation/replay).
- Full WSL suite with `dev`, `opcua`, `modbus`, and `lint` extras: passed; one Windows-only test was skipped.
- Ruff, `uv lock --check`, and `git diff --check`: passed. UV emitted a non-fatal cross-filesystem hardlink fallback warning.
- Windows CLI smoke used seed 42 and the committed scenario: generated 3,600 observations. Replay telemetry Parquet SHA-256 matched (`9862d2c32279b437a1f4f5428caa38e1ae7ae3c6ae0b10bccc8da2557c60a540`); ground-truth JSON hash also matched exactly.

## Limits

Affinity laws are approximate, and constant efficiency plus a fixed system duty characteristic do not substitute for a model-specific Q-H/system curve. The profile is not a digital twin or physical calibration. No detector was used to tune process behavior.
