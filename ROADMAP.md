# Roadmap after v0.2

OT Irregularity Lab v0.2.0 delivers a randomized suite and one public 1,000-run training dataset. This roadmap records remaining work from the broader platform vision. Items here are not implemented unless their status is explicitly changed in a later release.

## Dataset and simulator

- [x] Make event severity operational for continuous effects and sampled effects. Severity 0 leaves the process unchanged; severity 1 applies configured magnitudes or loss rates. `sensor_stuck` blends toward the held value, while communication loss, single-signal loss and quality degradation apply seeded per-sample probabilities. Discrete outcomes remain categorical, but their frequency responds to severity. More type-specific calibration remains needed.
- [x] Implement deterministic configured missingness rates from 5%, 10%, 25%, 50%, and 100%, with event ground truth covering selected affected tags; empirical rates are checked across 40 independent seeds per rate. Support fixed `single`, `multiple`, `all`, and explicit signal-list tag selection.
- [x] Add resumable generation via `ot-lab dataset create --resume`, with per-run checkpoints, suite/seed/version validation, deterministic recovery, hash-checked scenario reconstruction, and atomic final publication. Add process-parallel run generation via `--workers`, stable seeds/manifests, resumable cross-worker recovery, and measured throughput in [BENCHMARK.md](BENCHMARK.md). The 60-run host measurement is indicative only; broader storage/performance limits remain to be measured.
- [x] Support independently published partition ZIP artifacts and release manifests that link one dataset version, verify source hashes, and omit run/challenge seeds and ground truth. Signatures remain open under release governance below.
- [ ] Expand asset/control coverage and calibrate process parameters against authoritative published specifications or openly licensed data. Added a full UCI MetroPT-3 aggregate report and opt-in `metropt3_rail_apu` profile bounded to observed state-conditioned current/pressure/temperature envelopes; generic compressor behavior is unchanged. The profile's transient dynamics and several signals remain illustrative, so this is not a calibrated digital twin.

## Evaluation and challenge

- [x] Add reference fixtures covering full/partial overlap, duplicate alerts, fragmentation, no alerts, zero-observation assets, missing samples, threshold ties, class imbalance, mixed assets, and timestamp timezone validation; use consistent half-open event/window intervals and document metric semantics and limits. Additional mixed-asset edge cases remain useful.
- [ ] Evaluate the protocol with multiple independent external model commands and compare event and timestamp metrics. Scores must not feed back into simulator design or event parameters.
- [x] Sample hidden challenge asset profiles, regimes, event types/counts, durations, and parameters from the versioned training-suite distributions at runtime. Resolved seed/scenario/parameters remain outside model input.
- [x] Add a separate versioned challenge distribution (`suites/challenge-v0.1.yaml`), selectable with `ot-lab challenge --challenge-suite`, plus repeated-case artifact anti-leakage tests. Scenario IDs/versions, seed/hash, resolved parameters and evaluator-only observed timestamps are excluded from model-mounted inputs; the public distribution weights remain benchmark choices, not field prevalence.
- [x] Add a normal-only suite that samples cold/warm start, shutdown, shifts, ambient conditions, varied sampling cadence/jitter, per-asset load setpoint, actuator/thermal response, and sensor noise; includes maintenance/load transitions. A named false-positive stress suite covers expected hard normal behavior. Tests verify event-free labels, resolved numeric ranges, deterministic sampling and suite-distribution coverage. Physical model fidelity and broader transient types remain limited by the deliberately simple equations.
- [ ] Review container isolation against the intended threat model, including image network attempts, filesystem visibility, resource exhaustion, output validation, and host/runtime boundaries. Image pulls are disabled; inference sees only a copied telemetry file and a single mounted output file, not the run directory or ground truth. Timed-out containers are removed; a 64 MiB monitored output ceiling, bounded log retention, timeout, and cgroup limits are implemented. These are not a security certification or a hard filesystem quota. Local process execution is not a security sandbox.

## Optional plant and protocol adapters

- [x] Add optional OPC UA read-only telemetry replay (`opcua` extra), with one Object per asset, Variables and engineering metadata per tag, a loopback default, and client/server conformance coverage. Ground truth stays outside the adapter.
- [ ] Add Modbus/TCP or OpenPLC adapter and extend protocol conformance coverage. The OPC UA endpoint currently uses None security and is intended for isolated synthetic testing only.

## Release and governance

- [ ] Sign software tags and dataset manifests when an authorized signing key is available. Software and dataset tags through v0.3.1/v0.3.0 remain unsigned; the configured local SSH key rejected its passphrase. Revisit only when a usable authorized signing key is available.
- [x] Publish OT Irregularity Dataset v0.3.0 with a separate CC BY 4.0 notice, deterministic archive, release checksum, per-run and partition hashes, and reproducible generation record; public download hash verified.
- [ ] Preserve model-agnostic behavior and public definitions; never tune scenario behavior in response to a particular detector's score.

## Current evidence boundary

The v0.3 dataset has 1,000 runs, 8,477,689 telemetry rows, and all 15 configured event families. This demonstrates generator and artifact coverage for the declared suite; it does not establish real industrial failure prevalence, calibrated physical realism, security certification, or detector performance in production.
