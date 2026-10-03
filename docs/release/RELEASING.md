# Releasing OT Irregularity Lab

1. Run `uv sync --extra dev --group lint`, `uv run ruff check src tests`, `uv run pytest`, and `actionlint .github/workflows/ci.yml`.
2. Verify public GitHub Actions for the target commit succeed; local checks do not substitute for CI.
3. Update `CHANGELOG.md`, software version in `pyproject.toml` and `src/ot_lab/__init__.py`, and telemetry/schema versions when contracts change.
4. Create a software tag/release from the reviewed commit and sign it with an authorized signing key when available. If signing is unavailable, state that the tag is unsigned. Software release notes must distinguish implemented behavior from planned work.
5. For a dataset release, generate a manifest, independently validate seeds/partitions and file hashes, choose an explicit data license, and package only synthetic, generated, non-customer data.
6. Do not call a challenge isolated until the Docker workflow has been exercised against an active daemon and the image behavior is reviewed. Document that resource limits and read-only mounts are not a host/kernel security certification or hard disk quota.
