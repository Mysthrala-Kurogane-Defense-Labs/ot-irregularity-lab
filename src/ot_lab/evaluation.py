"""Model-independent interval scoring against isolated event ground truth."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl

PREDICTION_COLUMNS = {"asset_id", "window_start", "window_end", "irregularity_score"}


def _time(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value))


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
    # Predicted windows are false positives if they do not overlap any event for the same asset.
    fp = 0
    tp_windows = 0
    all_events_by_asset: dict[str, list[tuple[datetime, datetime]]] = {}
    for event in events:
        all_events_by_asset.setdefault(event["asset_id"], []).append((_time(event.get("observed_start", event["start"])), _time(event.get("observed_end", event["end"]))))
    for row in selected:
        a, b = _time(row["window_start"]), _time(row["window_end"])
        if any(max(a, c) < min(b, d) for c, d in all_events_by_asset.get(row["asset_id"], [])):
            tp_windows += 1
        else:
            fp += 1
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    window_precision = tp_windows / (tp_windows + fp) if tp_windows + fp else 0.0
    window_recall = tp_windows / len(selected) if selected else 0.0
    window_f1 = 2 * window_precision * window_recall / (window_precision + window_recall) if window_precision + window_recall else 0.0
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
        "window_precision": window_precision, "window_recall": window_recall,
        "window_f1": window_f1,
        "event_detection_rate": recall, "true_positive_events": int(tp),
        "false_positive_windows": fp, "missed_events": int(fn),
        "true_positive_windows": tp_windows,
        "false_positives_per_asset_hour": fp / exposure_hours,
        "false_positives_per_asset_day": fp / exposure_hours * 24,
        "mean_time_to_first_detection_s": float(np.mean(latencies)) if latencies else None,
        "mean_detection_latency_s": float(np.mean(latencies)) if latencies else None,
        "mean_event_coverage": float(np.mean([e["coverage"] for e in matched_events])) if matched_events else None,
        "percentage_of_event_detected": float(np.mean([e["coverage"] for e in matched_events])) if matched_events else None,
        "event_type_metrics": by_type,
        "events": matched_events,
    }


def _pr_auc(events: list[dict[str, Any]], predictions: pl.DataFrame, overlap: float, exposure_hours: float) -> float | None:
    if not events:
        return None
    intervals = []
    positive = 0
    for row in predictions.to_dicts():
        start, end = _time(row["window_start"]), _time(row["window_end"])
        duration = (end - start).total_seconds()
        covered = 0.0
        for event in events:
            if event["asset_id"] != row["asset_id"]:
                continue
            event_start = _time(event.get("observed_start", event["start"]))
            event_end = _time(event.get("observed_end", event["end"]))
            left, right = max(start, event_start), min(end, event_end)
            if right > left:
                covered += (right - left).total_seconds()
        label = covered / duration >= overlap
        positive += int(label)
        intervals.append((float(row["irregularity_score"]), label))
    if positive == 0:
        return None
    points = [(0.0, 1.0)]
    for threshold in sorted({score for score, _ in intervals}, reverse=True):
        selected = [label for score, label in intervals if score >= threshold]
        tp = sum(selected)
        fp = len(selected) - tp
        fn = positive - tp
        precision = tp / (tp + fp) if tp + fp else 1.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        points.append((recall, precision))
    points.sort(key=lambda point: point[0])
    return float(np.trapezoid([point[1] for point in points], [point[0] for point in points]))


def evaluate(ground_truth_path: Path, predictions_path: Path, output_dir: Path, threshold: float = 0.5, overlap: float = 0.1, telemetry_path: Path | None = None) -> dict[str, Any]:
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
    if telemetry_path is None:
        raise ValueError("telemetry_path is required to calculate false-positive rates per asset-hour/day")
    telemetry = pl.read_parquet(telemetry_path, columns=["asset_id", "timestamp"])
    bounds = telemetry.group_by("asset_id").agg(
        pl.col("timestamp").min().dt.epoch("ms").alias("start_ms"),
        pl.col("timestamp").max().dt.epoch("ms").alias("end_ms"),
    )
    exposure_hours = sum(max(row["end_ms"] - row["start_ms"], 0) for row in bounds.iter_rows(named=True)) / 3_600_000
    events = truth["events"]
    if telemetry.is_empty():
        raise ValueError("telemetry input must contain at least one observation")
    run_ids = telemetry.select("run_id").unique().get_column("run_id").to_list() if "run_id" in telemetry.columns else []
    if run_ids and run_ids != [truth["run_id"]]:
        raise ValueError("telemetry and ground truth run_id values do not match")
    telemetry_assets = set(telemetry.get_column("asset_id").unique().to_list())
    if any(row["asset_id"] not in telemetry_assets for row in predictions.to_dicts()):
        raise ValueError("predictions reference an asset absent from telemetry")
    result = _event_detection_metrics(events, predictions, threshold, overlap, exposure_hours)
    result["window_pr_auc"] = _pr_auc(events, predictions, overlap, exposure_hours)
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
