# MetroPT analysis QA and rail APU profile v1.1

## Scope

Improve the aggregate-only MetroPT-3 reference analysis and add a versioned, opt-in interpretation of the published compressor operating-current anchors. No third-party source rows or derived time series are committed.

## Evidence and analysis

- Re-ran `ot-lab calibration analyze-metropt` against the local UCI CSV, SHA-256 `db30ccb4ea402e3c8bf2c99db06e288d4f2a772f6928f9dbe26a920d69793e24` (218,300,507 bytes).
- All 1,516,948 source rows parsed; null/parse failures, duplicate timestamps, source-order reversals, negative current/pressure and non-binary digital values were each zero.
- `COMP`/`DV` state aggregation leaves operating states mixed: `COMP=1,DV=0` has current median 0.0425 A and p95 3.87 A; `COMP=0,DV=1` has median 5.8475 A and p95 6.2025 A. The UCI variable description qualitatively reports approximately 0 A stopped, 4 A offloaded, 7 A loaded and 9 A at startup.
- The expanded report `calibration/metropt-3-summary.json` is aggregate-only. The CSV remained in the user Temp directory.

## Changes

- Analyzer report v1.1.0 includes input/usable/dropped rows, per-column null/parse failures, duplicate and out-of-order timestamp counts, invalid physical/digital value counts, and per-digital-combination current/pressure summaries.
- Added a regression fixture covering invalid and out-of-order data while preserving the distinction between source-order checks and sorted cadence calculation.
- Added MetroPT rail APU profile v1.1.0: `OFF` uses the near-zero stopped anchor, `IDLE` uses the approximately 4 A offloaded anchor, and transition from inactive to an active regime emits approximately 9 A once. Profile v1.0.0 retains its earlier behavior.
- Added a runnable 600-second scenario; simulator package version is now 0.6.0. Generic compressor behavior and schemas are unchanged.
- Documented that the measured approximately 10-second cadence cannot establish startup pulse duration; one emitted sample is a model approximation, not inferred physics.

## Validation

- Focused Windows MetroPT and simulator tests: 10 passed.
- Full WSL suite with development, OPC UA, Modbus and lint dependencies: passed, one platform-specific test skipped.
- Ruff, `uv lock --check`, and `git diff --check`: passed.
- Windows CLI generated 3,600 observations with seed 42; replay succeeded. Regime medians were approximately 4.00 A for IDLE and 0.036 A for OFF; a startup sample reached 9.0 A.
- Full-source analysis completed with the counts and hash above.

## Limits

This is one railway air-production unit, not a generic industrial population. Digital-state semantics remain ambiguous and aggregate associations are not causal. Startup transient duration, thermal dynamics, vibration and failure progression remain simulator assumptions. No detector results were used to select or tune process behavior.
