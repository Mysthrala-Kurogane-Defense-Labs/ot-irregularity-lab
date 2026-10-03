# Roadmap after v0.2

OT Irregularity Lab v0.2.0 delivers a randomized suite and one public 1,000-run training dataset. This roadmap records remaining work from the broader platform vision. Items here are not implemented unless their status is explicitly changed in a later release.

## Dataset and simulator

- [x] Make event severity operational for continuous effects and missingness probability, while retaining categorical outages/quality as discrete states. Severity 0 leaves continuous effects unchanged; severity 1 applies configured magnitudes. Categorical event severity remains descriptive. More type-specific calibration remains needed.
- [x] Implement deterministic configured missingness rates from 5%, 10%, 25%, 50%, and 100%, with event ground truth covering selected affected tags; empirical rates are checked across 40 independent seeds per rate. Support fixed `single`, `multiple`, `all`, and explicit signal-list tag selection.
- [x] Add resumable generation via `ot-lab dataset create --resume`, with per-run checkpoints, suite/seed/version validation, deterministic recovery, hash-checked scenario reconstruction, and atomic final publication. [ ] Add chunked parallel generation and document measured storage/performance limits.
- [ ] Support independently published partition artifacts and release manifests that link one dataset version without leaking challenge seeds.
- [ ] Expand asset/control coverage and calibrate process parameters against authoritative published specifications or openly licensed data. Current process models are simplified, plausible examples, not calibrated digital twins.

## Evaluation and challenge

- [x] Add reference fixtures covering full/partial overlap, duplicate alerts, fragmentation, no alerts, zero-observation assets, missing samples, threshold ties, and timestamp timezone validation; document metric semantics and limits. [ ] Extend hand-checked fixture coverage for class imbalance and additional mixed-asset edge cases.
- [ ] Evaluate the protocol with multiple independent external model commands and compare event and timestamp metrics. Scores must not feed back into simulator design or event parameters.
- [x] Sample hidden challenge asset profiles, regimes, event types/counts, durations, and parameters from the versioned training-suite distributions at runtime. Resolved seed/scenario/parameters remain outside model input.
- [ ] Add explicit challenge-only distributions and anti-leakage checks across repeated cases; current challenge samples the public training suite distribution.
- [ ] Review container isolation against the intended threat model, including image network attempts, filesystem visibility, resource exhaustion, output validation, and host/runtime boundaries. A 64 MiB output ceiling, bounded log retention, timeout, and cgroup limits are implemented; these are not a security certification or a filesystem quota. Local process execution is not a security sandbox.

## Optional plant and protocol adapters

- [x] Add optional OPC UA read-only telemetry replay (`opcua` extra), with one Object per asset, Variables and engineering metadata per tag, a loopback default, and client/server conformance coverage. Ground truth stays outside the adapter.
- [ ] Add Modbus/TCP or OpenPLC adapter and extend protocol conformance coverage. The OPC UA endpoint currently uses None security and is intended for isolated synthetic testing only.

## Release and governance

- [ ] Sign software tags and dataset manifests when an authorized signing key is available. v0.2.0 is published and CI-verified, but its tag is unsigned because the configured local SSH key rejected the passphrase.
- [x] Publish OT Irregularity Dataset v0.3.0 with a separate CC BY 4.0 notice, deterministic archive, release checksum, per-run and partition hashes, and reproducible generation record; public download hash verified.
- [ ] Preserve model-agnostic behavior and public definitions; never tune scenario behavior in response to a particular detector's score.

## Current evidence boundary

The v0.3 dataset has 1,000 runs, 8,477,689 telemetry rows, and all 15 configured event families. This demonstrates generator and artifact coverage for the declared suite; it does not establish real industrial failure prevalence, calibrated physical realism, security certification, or detector performance in production.
