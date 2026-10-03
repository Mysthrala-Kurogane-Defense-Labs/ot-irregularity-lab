# Changelog

## 0.1.0 — 2026-10-03

- Completed the v0.1 acceptance path for normal CNC/PUMP generation, anomaly runs, independent ground truth, replay, seeded train/validation/test batches, and model-agnostic evaluation.
- Preserved every resolved batch scenario and strengthened its manifest with disjoint seeds, counts, distributions, and artifact hashes.
- Scored timestamp metrics on the expected sampling cadence so missing samples and full asset outages remain measurable.
- Added regression coverage for all supported anomaly families, zero-observation communication loss, range validation, batch replay, false-positive stress, and challenge alerts across assets.
- Verified the Docker submission and runtime-generated challenge flow locally; this baseline profile is not a security certification.
- Replaced the abbreviated license with the complete Apache-2.0 license text. No public dataset release is included.

## 0.1.0-alpha.2

- Verified Docker submission and ephemeral challenge flows locally with a smoke container.
- Container wrapper uses a minimal environment, no network, read-only root, dropped capabilities, and separated telemetry/output mounts.
- Added regression checks for container flags and documented preview validation limits.

## 0.1.0-alpha.1

- Initial independent synthetic telemetry generator for CNC, pump, compressor, and conveyor process models.
- Canonical telemetry schema v1.0.0, independent ground truth, replay, and seeded batch partitions.
- Event- and window-based benchmarking, metrics JSON, HTML reports, and multi-model comparison.
- Ephemeral challenge generation with hidden runtime seed and Docker submission profile.
- False-positive stress, four-asset normal plant, communication-loss, and challenge suites.
- CI checks for Python 3.12, Ruff, and pytest.
- Docker isolation has not been verified against a running daemon in this release environment.
