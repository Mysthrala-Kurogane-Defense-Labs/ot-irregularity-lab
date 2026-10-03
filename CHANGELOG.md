# Changelog

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
