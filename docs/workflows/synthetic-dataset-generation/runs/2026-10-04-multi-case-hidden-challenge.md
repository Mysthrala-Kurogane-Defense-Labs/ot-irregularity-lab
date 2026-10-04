# Multi-case ephemeral challenge

## Objective and acceptance

Extend the runtime-generated hidden challenge from one case per invocation to a configurable batch while preserving a fresh model container and hidden-seed boundary for every case. Persist only aggregate metrics and an aggregate report. The pooled event/window counts, exposure rates, event-weighted means, and PR-AUC aggregation method must be explicit and covered by tests.

## Scope and environment

- Base revision: `d9ca1962d679f560fa26cc5f1cbd465b7932df88` on `feat/metropt-air-leak-pattern` (PR #5 remains open).
- Runtime: Windows PowerShell with Docker Desktop context `desktop-linux`; existing local image `ot-lab-ext-iforest:local`.
- Local validation: WSL/Linux Python 3.13 with core, OPC UA and Modbus extras; one Windows-only subprocess test is skipped in WSL.
- No generated challenge telemetry, event labels, predictions, seeds or resolved scenarios were added to the repository.

## Changes

- Add `ot-lab challenge --cases N`, plus common `--threshold` and `--overlap` values for all cases. Each sample receives a distinct temporary directory and a newly run Docker container. The temporary root is removed on success and on exceptions.
- Add expected-grid TP/FP/FN and sample-count fields to per-run metrics; these allow count pooling without concatenating hidden per-case prediction/label arrays.
- Pool event/episode counts and compute event precision/recall/F1 from pooled counts. Pool window confusion counts and asset-hour exposure before deriving window metrics and false-positive rates. Weight mean event coverage and detection latency by events/detections respectively. Macro-average per-case expected-sample average precision over cases that have positive samples; normal-only cases remain in the denominator for false-positive exposure, but not PR-AUC.
- Retain only `metrics.json` and `report.html`; case IDs, individual metrics, predictions, telemetry, ground truth, seeds and resolved scenarios are omitted.

## Validation

- WSL: `uv run --extra dev --group lint pytest -q` — passed (148 passed, 3 skipped: two protocol extras absent in this first run and one Windows-only test). Ruff, `uv lock --check` and `git diff --check` passed.
- WSL with both optional protocol extras: `uv run --extra dev --extra opcua --extra modbus --group lint pytest -q` — passed; only the Windows-only subprocess test is skipped.
- Real Docker smoke: `python.exe -m ot_lab.cli challenge --suite suites/training-v0.3.yaml --challenge-suite suites/challenge-v0.2.yaml --image ot-lab-ext-iforest:local --cases 3 --output <Temp>/ot-lab-challenge-batch-smoke-20261004` using the pre-existing Windows CI venv and current `src` via `PYTHONPATH`.
- Smoke result: 3 cases, 5 ground-truth events, 3 matched, 356 alert episodes, 1,410 false-positive windows, 6,340 expected sample positions. Metrics are execution evidence only and make no detector-quality or industrial-performance claim.
- The output directory contains exactly `metrics.json` and `report.html`. A scan found no seed, run ID, event ID, or scenario metadata. The three temporary case directories were removed when the command returned.
- The first Windows `uv run` attempt could not replace the existing `.venv/lib64` entry. WSL's Docker daemon did not contain the Windows-local model image. Using the pre-existing Windows CI venv with Docker Desktop succeeded; no repository environment was deleted.
- GitHub Actions run [37170499831](https://github.com/Mysthrala-Kurogane-Defense-Labs/ot-irregularity-lab/actions/runs/37170499831) passed core, OPC UA and Modbus on Python 3.12 for PR #6 commit `263f48363767ad8f8b181065c907f69889fcc835`.

## Limits and next action

- The smoke checks one local image and three cases, not a large challenge batch or a Docker escape. Docker boundary limits are recorded in [the isolation review](2026-10-04-isolation-and-evaluator-review.md).
- PR #6 is public and open, stacked on #5; CI for its implementation commit passed. Do not merge any layer without user instruction.
- Aggregated challenge results still disclose aggregate event-family metrics after inference. This implementation does not claim to prevent a challenge operator from instrumenting a locally controlled evaluator; an authoritative hidden benchmark must run in the evaluator operator's environment.
