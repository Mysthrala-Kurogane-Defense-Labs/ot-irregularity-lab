# External model-command protocol conformance

## Change

Added a test fixture that launches two separate Python commands through the public `run-model` process contract. Each command reads only the temporary `input.parquet` path and writes valid prediction JSONL; neither imports `ot_lab` or receives ground truth. The test sends both output files to `ot-lab compare` and checks event detection and expected-cadence precision.

The two commands intentionally produce control outputs (quiet scores and full-horizon alerts). They are not detectors, do not measure model quality, and their scores are not used to tune simulator parameters.

## Evidence

- The quiet control has zero event detections; the always-alert control detects the event but yields low expected-sample precision.
- The fixture uses the event's observed interval for its metric expectation. The configured interval is five seconds, while the sampled process exposes four event-positive cadence points.
- The focused protocol test and Ruff pass on Windows; full cross-platform suite results for the commit containing it are pending.

## Remaining validation

Run independently maintained model commands on a fixed test partition or fresh challenge samples and publish model/version/command provenance with the results. Do not feed scores back into simulator design.
