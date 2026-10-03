# MetroPT-3 reference analysis and severity semantics

## Scope

Analyze the complete public MetroPT-3 compressor CSV using the repository's aggregate-only tool, confirm the input archive's published checksum, implement an explicitly opt-in APU profile, and verify severity behavior. The source ZIP/CSV stayed under the local user Temp directory; no source samples were added to this repository.

## Evidence

- UCI MetroPT-3 archive size: 218,381,995 bytes. ZIP SHA-256: `aab991a970e58210de853bb8078ce0e63abb4d9412fdc5c79792dae3d8e1721a`; matched the checksum documented by the public `machbase/neo-train-apu-demo` repository.
- CSV: 1,516,948 usable rows, 218,300,507 bytes, SHA-256 `db30ccb4ea402e3c8bf2c99db06e288d4f2a772f6928f9dbe26a920d69793e24`; timestamps span 2020-02-01 through 2020-09-01.
- Positive cadence p05/p50/p95: 9/10/10 seconds; fraction of positive intervals over 120 seconds: 0.000216.
- `DV_eletric > 0.5`: 243,638 rows, median motor current 5.835 A, oil temperature 65.9 °C, pressure 8.866 bar.
- Combined `COMP > 0.5` and `DV_eletric <= 0.5`: 1,263,084 rows, median motor current 0.0425 A, oil temperature 62.05 °C, pressure 8.978 bar.
- Aggregate output: `calibration/metropt-3-summary.json` (2,734 bytes). No source rows or time-series samples are stored.

## Changes

- Added `ot-lab calibration analyze-metropt` and aggregate/provenance tests.
- Added `AssetSpec.process_profile=metropt3_rail_apu` with parameterized process generation bounded to observed current/pressure/temperature envelopes. Generic compressor is unchanged. Discharge temperature, vibration, thermal time constant, state interpretation, and transition behavior are illustrative.
- Severity 0/1 and intermediate semantics now hold for communication loss, single-tag loss, quality degradation, and sensor-stuck blending. Deterministic frequency and blend tests cover those changes.

## Validation

- `uv run --python 3.12 pytest -q` — passed with core and OPC UA extras.
- `uv run --python 3.12 ruff check src tests` — passed.
- `git diff --check` — passed.
- `uv run ot-lab calibration analyze-metropt ...` — generated the report from the complete CSV.

## Limits

MetroPT-3 is one railway APU, not a universal industrial compressor. The report provides descriptive state-conditioned aggregates; binary state channels do not resolve all machine states, and these quantiles do not validate causality or dynamics. The APU profile is illustrative and is not a calibrated digital twin. See `CALIBRATION.md`.
