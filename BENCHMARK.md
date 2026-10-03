# Model-agnostic benchmark protocol

Submission contract: a process receives only `input.parquet` and writes `output.jsonl` records with `asset_id`, `window_start`, `window_end`, and `irregularity_score` in `[0,1]`. Optional `classification` and `evidence` are descriptive. The platform imports no detector implementation.

Future event evaluation will match scored intervals to independent ground-truth events with a documented overlap rule. It will report precision, recall, F1, PR-AUC, false positives per asset-hour/day, event detection rate, time to first detection, latency, and percentage of event duration detected. Aggregation will include per-asset and per-event-type slices; point metrics will supplement, not replace, event metrics.

Container challenge runs mount telemetry read-only and predictions write-only, exclude ground truth, disable host networking and Internet, and use fresh temporary cases from hidden runtime seeds. The current release has no evaluator/container sandbox yet; do not treat this document as evidence those controls already exist.
