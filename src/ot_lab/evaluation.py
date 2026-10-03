"""Model-independent interval scoring against isolated event ground truth."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl

PREDICTION_COLUMNS = {"asset_id", "window_start", "window_end", "irregularity_score"}


def _time(value: Any) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    if parsed.tzinfo is None:
        raise ValueError("prediction and ground-truth timestamps must include a timezone")
    return parsed


def _event_detection_metrics(events: list[dict[str, Any]], predictions: pl.DataFrame, threshold: float, overlap: float, exposure_hours: float) -> dict[str, Any]:
    selected = [row for row in predictions.to_dicts() if float(row["irregularity_score"]) >= threshold]
    predicted_by_asset: dict[str, list[tuple[datetime, datetime]]] = {}
    for row in selected:
        predicted_by_asset.setdefault(row["asset_id"], []).append((_time(row["window_start"]), _time(row["window_end"])))
    matched_events: list[dict[str, Any]] = []
    for event in events:
        start, end = _time(event.get("observed_start", event["start"])), _time(event.get("observed_end", event["end"]))
        duration = max((end - start).total_seconds(), 1e-9)
        intervals = predicted_by_asset.get(event["asset_id"], [])
        covered: list[tuple[datetime, datetime]] = []
        first_hit: datetime | None = None
        for index, (pstart, pend) in enumerate(intervals):
            left, right = max(start, pstart), min(end, pend)
            if right > left:
                covered.append((left, right))
                if first_hit is None or left < first_hit:
                    first_hit = left
        covered.sort()
        merged: list[list[datetime]] = []
        for left, right in covered:
            if merged and left <= merged[-1][1]:
                merged[-1][1] = max(merged[-1][1], right)
            else:
                merged.append([left, right])
        covered_s = sum((right - left).total_seconds() for left, right in merged)
        coverage = min(1.0, covered_s / duration)
        matched_events.append({
            "event_id": event["event_id"], "asset_id": event["asset_id"], "type": event["type"],
            "detected": coverage >= overlap, "coverage": coverage,
            "time_to_first_detection_s": (first_hit - start).total_seconds() if first_hit else None,
            "severity": event.get("severity", 0),
        })
    tp = sum(e["detected"] for e in matched_events)
    fn = len(matched_events) - tp
    # A predicted alert window is an event-level false positive if too little of it overlaps ground truth.
    fp = 0
    tp_windows = 0
    false_positive_duration_s = 0.0
    all_events_by_asset: dict[str, list[tuple[datetime, datetime]]] = {}
    for event in events:
        all_events_by_asset.setdefault(event["asset_id"], []).append((_time(event.get("observed_start", event["start"])), _time(event.get("observed_end", event["end"]))))
    for row in selected:
        a, b = _time(row["window_start"]), _time(row["window_end"])
        duration = max((b - a).total_seconds(), 1e-9)
        overlaps = []
        for c, d in all_events_by_asset.get(row["asset_id"], []):
            left, right = max(a, c), min(b, d)
            if right > left:
                overlaps.append((left, right))
        overlaps.sort()
        union: list[list[datetime]] = []
        for left, right in overlaps:
            if union and left <= union[-1][1]:
                union[-1][1] = max(union[-1][1], right)
            else:
                union.append([left, right])
        event_overlap_s = sum((right - left).total_seconds() for left, right in union)
        false_positive_duration_s += max(0.0, duration - event_overlap_s)
        if event_overlap_s / duration >= overlap:
            tp_windows += 1
        else:
            fp += 1
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    exposure_hours = max(exposure_hours, 1e-9)
    latencies = [e["time_to_first_detection_s"] for e in matched_events if e["detected"] and e["time_to_first_detection_s"] is not None]
    event_types = sorted({event["type"] for event in events})
    by_type = {}
    for event_type in event_types:
        subset = [event for event in matched_events if event["type"] == event_type]
        by_type[event_type] = {
            "event_count": len(subset),
            "detection_rate": sum(event["detected"] for event in subset) / len(subset),
            "mean_coverage": float(np.mean([event["coverage"] for event in subset])),
        }
    return {
        "threshold": threshold, "overlap_threshold": overlap,
        "precision": precision, "recall": recall, "f1": f1,
        "event_precision": precision, "event_recall": recall, "event_f1": f1,
        "event_detection_rate": recall, "true_positive_events": int(tp),
        "false_positive_windows": fp, "missed_events": int(fn),
        "event_overlapping_alert_windows": tp_windows,
        "false_positive_duration_s": false_positive_duration_s,
        "false_positives_per_asset_hour": fp / exposure_hours,
        "false_positives_per_asset_day": fp / exposure_hours * 24,
        "mean_time_to_first_detection_s": float(np.mean(latencies)) if latencies else None,
        "mean_detection_latency_s": float(np.mean(latencies)) if latencies else None,
        "mean_event_coverage": float(np.mean([e["coverage"] for e in matched_events])) if matched_events else None,
        "percentage_of_event_detected": float(np.mean([e["coverage"] for e in matched_events])) if matched_events else None,
        "event_type_metrics": by_type,
        "events": matched_events,
    }


def _timestamp_scores(events: list[dict[str, Any]], predictions: pl.DataFrame, telemetry: pl.DataFrame, metadata: dict[str, Any]) -> tuple[list[float], list[bool]]:
    """Assign each expected asset sample the highest covering score and event label, including missing samples."""
    event_intervals = {
        asset_id: [(_time(item.get("observed_start", item["start"])), _time(item.get("observed_end", item["end"]))) for item in events if item["asset_id"] == asset_id]
        for asset_id in {event["asset_id"] for event in events}
    }
    pred_intervals: dict[str, list[tuple[datetime, datetime, float]]] = {}
    for row in predictions.to_dicts():
        pred_intervals.setdefault(row["asset_id"], []).append((_time(row["window_start"]), _time(row["window_end"]), float(row["irregularity_score"])))
    start = _time(metadata["started_at"])
    cadence = int(metadata["sampling_interval_ms"])
    total_samples = int(float(metadata["duration_s"]) * 1000 / cadence)
    asset_ids = metadata.get("asset_ids") or telemetry.get_column("asset_id").unique().to_list()
    samples = [
        {"asset_id": asset_id, "timestamp": start + timedelta(milliseconds=index * cadence)}
        for asset_id in asset_ids for index in range(total_samples)
    ]
    scores: list[float] = []
    labels: list[bool] = []
    for sample in samples:
        timestamp, asset_id = sample["timestamp"], sample["asset_id"]
        labels.append(any(start <= timestamp < end for start, end in event_intervals.get(asset_id, [])))
        scores.append(max((score for start, end, score in pred_intervals.get(asset_id, []) if start <= timestamp < end), default=0.0))
    return scores, labels


def _window_pr_auc(events: list[dict[str, Any]], predictions: pl.DataFrame, telemetry: pl.DataFrame, metadata: dict[str, Any]) -> float | None:
    scores, labels = _timestamp_scores(events, predictions, telemetry, metadata)
    positive = sum(labels)
    if positive == 0:
        return None
    precisions: list[float] = []
    recalls: list[float] = []
    for threshold in sorted(set(scores), reverse=True):
        selected = [label for score, label in zip(scores, labels, strict=True) if score >= threshold]
        tp = sum(selected)
        fp = len(selected) - tp
        fn = positive - tp
        precision = tp / (tp + fp) if tp + fp else 1.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        precisions.append(precision)
        recalls.append(recall)
    # Average precision integrates the right-continuous precision envelope at recall changes.
    previous_recall = 0.0
    area = 0.0
    for precision, recall in zip(precisions, recalls, strict=True):
        area += max(0.0, recall - previous_recall) * precision
        previous_recall = max(previous_recall, recall)
    return float(area)


def evaluate(ground_truth_path: Path, predictions_path: Path, output_dir: Path, threshold: float = 0.5, overlap: float = 0.1, telemetry_path: Path | None = None, metadata_path: Path | None = None) -> dict[str, Any]:
    truth = json.loads(ground_truth_path.read_text(encoding="utf-8"))
    predictions = pl.read_ndjson(predictions_path)
    missing = PREDICTION_COLUMNS - set(predictions.columns)
    if missing:
        raise ValueError(f"prediction output is missing columns: {', '.join(sorted(missing))}")
    if predictions.is_empty():
        raise ValueError("prediction output must contain at least one window")
    if predictions.filter((pl.col("irregularity_score") < 0) | (pl.col("irregularity_score") > 1) | pl.col("irregularity_score").is_nan() | pl.col("irregularity_score").is_infinite()).height:
        raise ValueError("irregularity_score must be between 0 and 1")
    if predictions.filter(pl.col("irregularity_score").is_null() | pl.col("window_start").is_null() | pl.col("window_end").is_null() | (pl.col("window_end") <= pl.col("window_start"))).height:
        raise ValueError("prediction windows must have finite scores and end after start")
    asset_ids = predictions.get_column("asset_id").to_list()
    if any(not isinstance(asset_id, str) or not asset_id for asset_id in asset_ids):
        raise ValueError("prediction asset_id values must be non-null strings")
    if telemetry_path is None:
        raise ValueError("telemetry_path is required to calculate false-positive rates per asset-hour/day")
    telemetry = pl.read_parquet(telemetry_path)
    meta_path = metadata_path or telemetry_path.with_name("run_metadata.json")
    metadata = json.loads(meta_path.read_text(encoding="utf-8"))
    exposure_hours = float(metadata["duration_s"]) * int(metadata.get("asset_count", 0)) / 3600
    events = truth["events"]
    if telemetry.is_empty() and int(metadata.get("observation_count", 0)) > 0:
        raise ValueError("telemetry input must contain at least one observation")
    run_ids = telemetry.select("run_id").unique().get_column("run_id").to_list() if "run_id" in telemetry.columns else []
    if run_ids and run_ids != [truth["run_id"]]:
        raise ValueError("telemetry and ground truth run_id values do not match")
    telemetry_assets = set(telemetry.get_column("asset_id").unique().to_list()) if "asset_id" in telemetry.columns else set()
    declared_assets = set(metadata.get("asset_ids", telemetry_assets))
    if any(row["asset_id"] not in declared_assets for row in predictions.to_dicts()):
        raise ValueError("predictions reference an asset absent from telemetry")
    result = _event_detection_metrics(events, predictions, threshold, overlap, exposure_hours)
    sample_scores, sample_labels = _timestamp_scores(events, predictions, telemetry, metadata)
    sample_predicted = [score >= threshold for score in sample_scores]
    sample_tp = sum(pred and label for pred, label in zip(sample_predicted, sample_labels, strict=True))
    sample_fp = sum(pred and not label for pred, label in zip(sample_predicted, sample_labels, strict=True))
    sample_fn = sum(not pred and label for pred, label in zip(sample_predicted, sample_labels, strict=True))
    result["window_precision"] = sample_tp / (sample_tp + sample_fp) if sample_tp + sample_fp else 0.0
    result["window_recall"] = sample_tp / (sample_tp + sample_fn) if sample_tp + sample_fn else 0.0
    result["window_f1"] = 2 * result["window_precision"] * result["window_recall"] / (result["window_precision"] + result["window_recall"]) if result["window_precision"] + result["window_recall"] else 0.0
    result["window_pr_auc"] = _window_pr_auc(events, predictions, telemetry, metadata)
    result["pr_auc"] = result["window_pr_auc"]
    result["run_id"] = truth["run_id"]
    result["prediction_count"] = predictions.height
    result["exposure_asset_hours"] = exposure_hours
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "metrics.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    event_rows = "".join(f"<tr><td>{e['event_id']}</td><td>{e['asset_id']}</td><td>{e['type']}</td><td>{e['detected']}</td><td>{e['coverage']:.1%}</td></tr>" for e in result["events"])
    html = f"""<!doctype html><html lang="en"><meta charset="utf-8"><title>OT Irregularity Lab benchmark</title>
<style>body{{font:16px system-ui;max-width:900px;margin:3rem auto;color:#16202a}}table{{border-collapse:collapse}}td,th{{padding:.6rem 1rem;border:1px solid #ccd}}</style>
<h1>Benchmark report</h1><p>Run: {result['run_id']} | threshold {threshold:.3f} | overlap {overlap:.1%}</p>
<ul><li>Precision: {result['precision']:.3f}</li><li>Recall: {result['recall']:.3f}</li><li>F1: {result['f1']:.3f}</li>
<li>PR-AUC: {result['pr_auc'] if result['pr_auc'] is not None else 'n/a'}</li><li>False positive windows: {result['false_positive_windows']}</li>
<li>Event coverage: {result['mean_event_coverage'] if result['mean_event_coverage'] is not None else 'n/a'}</li></ul>
<h2>Events</h2><table><thead><tr><th>Event</th><th>Asset</th><th>Type</th><th>Detected</th><th>Coverage</th></tr></thead><tbody>{event_rows}</tbody></table></html>"""
    (output_dir / "report.html").write_text(html, encoding="utf-8")
    return result
