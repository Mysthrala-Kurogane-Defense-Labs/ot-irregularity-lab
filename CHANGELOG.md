# Changelog

## Unreleased

- Add `metropt3_rail_apu` process profile v1.1.0, which distinguishes stopped `OFF` current from approximately 4 A offloaded `IDLE` current and samples one approximately 9 A startup value using UCI's published variable description; profile v1.0.0 retains its prior output for replay compatibility. Startup pulse duration remains an explicit one-sample approximation because source cadence is about 10 seconds.
- Bump simulator package to `0.6.0` for the versioned process-model change; telemetry and ground-truth schemas remain unchanged.
- Add seeded per-asset process-profile sampling for versioned training and hidden-challenge suites. Training v0.4 and challenge v0.3 sample generic or centrifugal VFD pump models with numeric ranges; manifests record realized profile distributions.
- Stop suite asset-profile sampling from mutating the reusable suite definition; add regression coverage for multi-seed generation.
- Record per-run and aggregate process-profile counts in dataset manifests and publish these aggregate counts with partition packages.
- Generate a deterministic `SHA256SUMS.txt` for the dataset release manifest, license, telemetry archives, and separate labels archives.
- Add optional `centrifugal_vfd` pump process profile with parameter validation, coupled speed/flow/pressure/power/temperature behavior, and a runnable normal-operation scenario. Existing generic pump behavior is unchanged.
- Bump simulator package to `0.5.0`; telemetry and ground-truth schema versions remain unchanged.
- Add `ot-lab challenge --cases N` to evaluate independent runtime-generated hidden cases and persist pooled event/window metrics plus macro per-case PR-AUC only.
- Include expected-grid confusion counts in benchmark metrics so multi-case window scores can be pooled without retaining per-case outputs.
- Published OT Irregularity Training Dataset v0.5.0 with 3,000 independently seeded runs under CC BY 4.0; telemetry and label partitions are separate and remote asset hashes were verified.
- Added a MetroPT-3-informed compressor `air_leak` event that couples configurable pressure loss and compensating motor-current increase; added versioned training v0.3 and challenge v0.2 distributions without changing older suites.
- Added compressor-containing randomized asset profiles, increased the explicit `air_leak` sampling weight for suite coverage, and bounded seeded backtracking for multi-event placement; a 300-run validation draw records 26 air leaks across train/validation/test, with one in test.
- Compared public industrial datasets and repositories with explicit license and transfer limits; no third-party data or detector implementation was added.
- Replaced multiplicative per-sample scans in timestamp PR-AUC scoring with ordered active-interval heaps for prediction scores and event labels.
- Versioned event precision and recall against one-to-one matching of alert episodes to eligible ground-truth events.
- Added aggregate-only, provenance-hashed analysis for the full public MetroPT-3 compressor dataset and an opt-in rail APU compressor profile bounded to its observed mode-conditioned signal envelopes.
- Made severity control sampled communication loss, single-signal loss, quality degradation, and the blend strength of sensor-stuck effects; documented and tested those semantics.
- Added versioned, scenario-recorded numeric overrides for the MetroPT rail APU process profile, with validation for unsupported/non-finite parameters and invalid time constants.
- Added reproducible normal-run variation for per-asset load setpoint, actuator/thermal response, and sensor noise; resolved values are preserved for replay and dataset manifests.
- Added a false-positive stress suite for event-free cold/warm starts, load/recipe changes, high load, maintenance, restart/shutdown, environmental shifts, and network-like sampling jitter.
- Kept the generic compressor process model unchanged; the new MetroPT-specific profile does not claim unmeasured transient calibration.

## 0.3.1 — 2026-10-03

- Prevent the Docker daemon from pulling submission images during evaluation; submissions must use a locally available image.
- Force-remove the evaluation container if the Docker CLI exits on timeout or output-size enforcement.
- Added daemon-backed regression evidence showing a timed-out container does not remain running.

## 0.3.0 — 2026-10-03

- Made configured anomaly severity scale continuous signal effects and telemetry-loss probability; added deterministic multi-tag loss selection and 40-seed empirical rate checks.
- Added deterministic resumable dataset generation with validated per-run checkpoints and atomic final publication.
- Expanded challenge case sampling from versioned suite distributions and kept seed/scenario details out of model input.
- Added event metric reference fixtures and timezone-aware prediction validation.
- Added bounded model/container execution with timeout, log retention and configurable prediction output ceiling; documented the host/runtime threat boundary.
- Added optional OPC UA telemetry replay (`opcua` extra), read-only variables and metadata, plus a loopback-only default endpoint.
- Added source-backed calibration evidence notes; process dynamics remain simplified and uncalibrated.
- Added CI matrix coverage for core installation and OPC UA optional adapter.

## 0.2.0 — 2026-10-03

- Added a weighted suite generator for mixed normal/fault datasets with variable assets, regimes, run duration, cadence, jitter, ambient conditions, event onset, duration, severity, and parameters.
- Added all 15 supported fault families to `suites/training-v0.2.yaml`, with compatible asset classes and explicit numeric/choice distributions.
- Added `ot-lab dataset create`, dataset suite/runtime/version metadata, per-partition class/event distributions, regime distributions, and fail-closed handling of non-empty output paths.
- Added actual operating-regime intervals to independent ground truth (ground-truth schema v1.1.0), including runs where the PLC hides regime tags.
- Prevented randomized multi-event scenarios from placing simultaneous events on one asset; unsupported requested regimes now fall back to a regime available on the asset.
- Generated and published a 1,000-run training dataset with all 15 event families, eight observed regimes, train/validation/test partitions, separate ground truth, and CC BY 4.0 terms. The dataset archive is a separate release asset.
- Documented source dataset analysis and generator sampling limits. The release does not redistribute SWaT, TEP, SKAB, or other third-party traces.

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
