# Runtime challenge and Docker smoke, 2026-10-04

## Command and environment

- Command: `ot-lab challenge --suite suites/training-v0.4.yaml --challenge-suite suites/challenge-v0.3.yaml --image ot-lab-ext-iforest:local --cases 3 --output %TEMP%\ot-lab-challenge-v03-smoke`.
- Host used the Windows CI virtual environment, local Docker daemon, and an already-present local reference adapter image. No image pull or external network access was requested by the runner.
- The output directory contains only pooled `metrics.json` and `report.html`; challenge case files and predictions were temporary.

## Observed result

- Three independently generated hidden cases were run in separate containers. The aggregate contains five events, all matched; 227 thresholded alert episodes (222 unmatched), 1,318 false-positive windows, and 1.735 asset-hours of exposure.
- Pooled event recall was 1.0 and event precision 0.0220. These numbers describe this single smoke run and this local adapter image; they are not general detector-quality evidence and were not used to tune scenarios.
- Mean event coverage was 0.7113 and mean time to first detection was 9.6434 seconds. Expected-sample macro PR-AUC was 0.2565 across three cases.

## Isolation contract inspected

The challenge invokes a fresh Docker container per case. The runner uses `--pull=never`, `--network=none`, `--read-only`, `--cap-drop=ALL`, `no-new-privileges`, non-root UID/GID 65534, PID/memory/CPU limits, and a bounded no-exec temporary filesystem. The only bind mounts are that case's copied telemetry file (read-only) and a bounded prediction file. Ground truth, run metadata, scenario, seed, and other cases are not mounted. Each case directory is cleaned with the enclosing temporary directory on normal completion; abrupt host termination may leave host temporary files behind. These controls reduce exposure but are not a guarantee against host, Docker daemon, kernel, or malicious image compromise.
