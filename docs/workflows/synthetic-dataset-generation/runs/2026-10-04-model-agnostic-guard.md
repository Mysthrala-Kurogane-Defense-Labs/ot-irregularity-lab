# Model-agnostic architecture guard

## Scope

Turn the platform's model-agnostic requirement into a regression check without importing a detector library or detector code into the project.

## Changes

- Added a test that reads core and optional dependencies from `pyproject.toml` and rejects common detector frameworks.
- Added an AST scan over the `ot_lab` package that rejects imports from scikit-learn, PyOD, PyTorch, TensorFlow, XGBoost and LightGBM.
- Updated the roadmap's publication state and marked the existing model-agnostic invariant complete with its evidence boundary.

## Validation

- `tests/test_model_agnostic_architecture.py` — passed.
- Full WSL suite with development, OPC UA, Modbus and lint dependencies — passed; one platform-specific test skipped.
- Ruff, `uv lock --check`, and `git diff --check` — passed.

## Limits

This guard blocks common framework dependencies and imports. It cannot prove all future code is detector-independent; code review must continue to reject detector-specific branches and score-driven simulator tuning. External model comparison remains a separate protocol exercise.
