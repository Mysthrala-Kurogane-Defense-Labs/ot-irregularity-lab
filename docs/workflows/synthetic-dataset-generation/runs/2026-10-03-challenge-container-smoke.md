# Challenge container end-to-end smoke

## Scope

Exercise the evaluator-controlled challenge path with a local Docker daemon and a locally built synthetic model image. This is an integration smoke, not a hostile-image security assessment.

## Change

The Docker runner previously mounted the entire output directory, which could expose neighboring host files if a caller chose an output path inside a run directory. It now creates a clean temporary sandbox, copies `telemetry.parquet`, mounts that input read-only, and mounts one writable `output.jsonl` file. Ground truth, metadata, scenarios, and sibling files are not in either bind mount. Prediction output is size-checked before it is copied to the requested destination.

## Validation

- `uv run --python 3.12 pytest -q`: passed.
- `uv run --python 3.12 ruff check src tests`: passed.
- `uv lock --check`: passed.
- `git diff --check`: passed.
- Built a local Python container that listed `/ot-lab` and verified only `input.parquet` and `output.jsonl` were visible; the Parquet magic bytes were `PAR1`.
- Ran `ot-lab challenge` with the local image and a short challenge suite; the container read telemetry and wrote model predictions, and the evaluator produced `metrics.json` and `report.html`.
- Docker container inventory for the image was empty after completion; the temporary image and smoke files were removed.
- Container regression, single-file mount documentation, and normal-suite generation checks pass locally. The code/doc changes are not yet in a commit.

## Limits

This confirms the intended mounts and successful orchestration on the active local Docker daemon. It does not test kernel escape, Docker daemon compromise, adversarial output-file behavior, hard disk quotas, or establish a security certification. The change awaits publication and remote CI.
