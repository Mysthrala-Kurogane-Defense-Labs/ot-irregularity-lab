# Re-score external models with event metrics v2

## Objective

Correct the evaluator's event precision unit mismatch and compare the same three archived external-model outputs under a versioned, coherent event/alert-episode contract. No detector was retrained, retuned, or rerun.

## Scoring contract

- Metric version: `2.0.0`.
- Test partition: the lexical first 40 runs from OT Irregularity Dataset v0.4.0; 30 runs contain 44 events, and 10 are normal-only.
- Score threshold: `0.995`; event coverage threshold: `0.1`; alert merge gap: `0` seconds (overlapping and adjacent thresholded windows coalesce per asset).
- An event must meet the configured union-coverage threshold, and its matched alert episode must independently meet the same event coverage threshold. A deterministic maximum-cardinality one-to-one match assigns eligible events to qualifying episodes. Event precision is matched episodes / all episodes; event recall is matched events / all events. Full definitions are in [BENCHMARK.md](../../../../BENCHMARK.md).
- Window PR-AUC and false-positive-window definitions did not change; the former is carried forward from the original three-model run.

## Inputs and integrity

- Public test archive SHA-256: `21525ef7c9c70eb47c3d4cf55003ef74ef22f6dfa4c8db461d5d3dc7dd791ab2`.
- Public test-label archive SHA-256: `d07b6456e892388f12b3a753d96f27653b9b63dd6e173181f4f94d1d8ca23691`.
- Both hashes matched the v0.4.0 release manifest before re-scoring.
- Exactly 40 archived prediction JSONL files per model were found for the same run IDs; the JSON result records one SHA-256 manifest per model prediction set.
- The evaluator used ground truth and evaluation metadata only for scoring; no test labels were used for fitting or threshold selection.
- No telemetry rows, event records, or per-window model scores are included in the committed result.

## Results

| Model | Matched events / 44 | Alert episodes | Event precision v2 | Event recall v2 | Event F1 v2 | Unmatched episodes | Unmatched episodes / asset-hour | False-positive windows / asset-hour | Mean event coverage | Mean window PR-AUC |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Isolation Forest | 2 | 399 | 0.50% | 4.55% | 0.90% | 397 | 35.99 | 64.54 | 3.01% | 0.233 |
| Local Outlier Factor | 11 | 278 | 3.96% | 25.00% | 6.83% | 267 | 24.20 | 40.97 | 23.38% | 0.367 |
| ECOD | 0 | 450 | 0.00% | 0.00% | 0.00% | 450 | 40.79 | 47.05 | 0.91% | 0.184 |

Episode false-positive rates use all 40 runs, including ten normal-only runs. Their normal-only unmatched-episode rates are 37.09, 11.76, and 42.52 per asset-hour for Isolation Forest, LOF, and ECOD respectively. Window false-positive rates are unchanged from the original run. These remain exploratory results on a small synthetic subset, not industrial-performance evidence.

The machine-readable aggregate, source hashes, per-model prediction manifests, and per-run event counts are in [the v2 result JSON](2026-10-04-external-model-evaluation-v0.4.0-metrics-v2.json), SHA-256 `1d8ca3e63cabafd2e01a954e21fc8f87ee0c5b87f5e9c18104677497db82715b`.

## Validation

- Windows Python 3.12: 140 tests passed; Ruff, `uv lock --check`, and diff checks passed.
- WSL/Linux Python 3.12: 139 tests passed, one platform-specific test skipped; Ruff and `uv lock --check` passed.
- Metric fixtures cover individually sub-threshold fragmented alerts, gap merging, one broad alert spanning multiple events, episode counts, threshold validation, duplicates, normal-only runs, and half-open intervals.
