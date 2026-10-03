# OT Irregularity Lab follow-up hardening

## Scope

Continued the authorized platform goal after public commit `c84167a`. This local change set adds configurable missing-tag selection, bounded external submission execution, and an optional OPC UA telemetry replay adapter. No new release has been published.

## Changes

- `missing_telemetry` supports `signal`, `signals`, `tag_selection: all|single|multiple`, and `tag_count`. `single_signal_loss` supports explicit signal lists. Selected tags remain fixed per event/run seed; 5%, 10%, 25%, 50%, and 100% rates have 40-seed aggregate tests.
- External model commands now have positive timeout validation, bounded captured stdout/stderr, and a configurable 64 MiB prediction output limit (`--max-output-bytes`). Docker retains no-network, read-only root, reduced capabilities, non-root user and cgroup limits. These settings are not a host/kernel security certification; local `run-model` is not an isolation boundary.
- Optional `opcua` extra provides read-only canonical telemetry Variables grouped by asset, with unit, class and engineering-bound properties. Default endpoint is loopback. The endpoint uses OPC UA None security; keep it isolated. Ground truth is not read by the adapter.

## Validation

- `uv run --extra opcua --python 3.12 pytest -q`: 95 passed.
- `uv run --extra opcua --python 3.12 ruff check src tests`: passed.
- `uv lock --check`: passed.
- `git diff --check`: passed.
- Real Docker CLI smoke with local image, no network and a 1,024-byte output limit: passed; prediction file contained `{}`. Temporary image was removed. The test directory remains under `%TEMP%` because environment policy rejected recursive cleanup.
- OPC UA async server/client integration on localhost read the generated tag value and engineering properties successfully.
- The previous public commit `c84167a` passed GitHub Actions run [37144939329](https://github.com/Mysthrala-Kurogane-Defense-Labs/ot-irregularity-lab/actions/runs/37144939329). This newer local change set has not yet been pushed or CI-verified.

## Remaining

Physical model calibration, event-score validation against multiple independent submissions, challenge threat-model review and adversarial resource tests, Modbus/OpenPLC, signed releases, and future dataset release controls remain open in `ROADMAP.md`.
