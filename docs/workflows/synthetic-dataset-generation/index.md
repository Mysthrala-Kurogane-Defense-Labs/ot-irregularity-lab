# Synthetic dataset generation records

- 2026-10-03 — [Normal process variation](runs/2026-10-03-normal-process-variation.md): randomized per-asset load setpoint, response time, and sensor-noise values with event-free 30-seed verification.
- 2026-10-03 — [Parallel run generation](runs/2026-10-03-parallel-run-generation.md): deterministic `--workers` support, byte-identical partitions, cross-worker resume, and measured 60-run throughput.
- 2026-10-03 — [Linux process-pool deadlock](runs/2026-10-03-linux-process-pool.md): replaced fork with spawn after a reproducible post-Polars worker hang; Linux WSL full suite passed after the fix.
- 2026-10-03 — [Deterministic partition packaging](runs/2026-10-03-partition-packaging.md): separate train/validation/test ZIPs with verified hashes, explicit license notices, and seed-free release manifests.
- 2026-10-03 — [MetroPT-3 calibration and severity semantics](runs/2026-10-03-metropt-calibration.md): full reference CSV integrity and aggregate analysis, opt-in rail APU profile, and severity behavior tests.
- 2026-10-03 — [Challenge container end-to-end smoke](runs/2026-10-03-challenge-container-smoke.md): single-file mounts and full short challenge verified with local Docker; container change published in `c34cb6c`, normal suite in `c30ea85`, both CI runs passed.
- 2026-10-03 — [Ephemeral challenge metadata hardening](runs/2026-10-03-challenge-metadata-hardening.md): hidden scenario metadata removed, 20-case regression and separate challenge distribution published; CI runs `37146984474` and `37147259217` passed.
- 2026-10-03 — [Docker submission output-limit hardening](runs/2026-10-03-docker-output-limit.md): hard process-tree file-size limit, daemon log suppression, and local Docker isolation/overflow smoke.
- 2026-10-03 — [External command conformance](runs/2026-10-03-external-command-conformance.md): two model-agnostic command fixtures exercise `run-model` and `compare`; no detector-quality claim.

- 2026-10-03 — [OT Irregularity Training Dataset v0.3.0, 1,000 runs](runs/2026-10-03-training-v0.3-1000.md): published under CC BY 4.0; the public archive download matched its recorded SHA-256.
- 2026-10-03 — [OT Irregularity Training Dataset v0.4.0, 1,000 runs](runs/2026-10-03-training-v0.4-1000.md): generated with 15 event types and four asset classes; telemetry and independent label archives built and locally verified under CC BY 4.0.
- 2026-10-03 — [OT Irregularity Training Dataset v0.2.0, 1,000 runs](runs/2026-10-03-training-v0.2-1000.md): generated, locally validated, and published under CC BY 4.0; archive SHA-256 is in the run record.

- 2026-10-04 — [Security review and remediations](runs/2026-10-04-security-review-and-remediations.md): scoped audit of all 12 source modules; fixed package-manifest path traversal and unescaped benchmark HTML, with Windows and WSL validation.
- 2026-10-04 — [External model results with event metrics v2](runs/2026-10-04-external-model-evaluation-metrics-v2.md): corrected event precision to one-to-one alert-episode matching and rescored the same 120 archived Isolation Forest, LOF, and ECOD outputs; no detector was retrained or retuned.
- 2026-10-04 — [Docker isolation and host evaluator review](runs/2026-10-04-isolation-and-evaluator-review.md): independent baseline and local container smoke found no container escape; fixed an O(P×S) host timestamp-scoring path and passed the full WSL suite.
- 2026-10-04 — [Multi-case ephemeral challenge](runs/2026-10-04-multi-case-hidden-challenge.md): `challenge --cases N` runs each hidden case in its own container and retains only pooled metrics; WSL suite and a three-case Docker Desktop smoke passed.
- 2026-10-04 — [Training v0.5 distribution validation](runs/2026-10-04-training-v0.5-distribution-validation.md): added compressor-containing randomized profiles, explicit rare-family coverage, and bounded backtracking; distribution and exact replay were checked.
- 2026-10-04 — [Training v0.5, 3,000-run package](runs/2026-10-04-training-v0.5-3000.md): release-size synthetic corpus, per-partition family coverage, exact replay, separate telemetry/label archives, and package hash/CRC verification.
