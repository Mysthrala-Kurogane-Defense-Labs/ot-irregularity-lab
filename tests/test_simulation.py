import io
import json
import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from itertools import pairwise
from pathlib import Path

import numpy as np
import polars as pl
import pytest

from ot_lab.evaluation import _timestamp_scores, evaluate
from ot_lab.models import Anomaly, AssetSpec, Scenario
from ot_lab.process import ProcessState, regime_at, simulate_step
from ot_lab.simulation import (
    EPOCH,
    _affect,
    _generate_suite_scenario,
    batch,
    replay,
    simulate,
    write_run,
)
from ot_lab.submission import _run_bounded, run_docker_submission, run_submission


def fixture_scenario(asset_class="cnc", anomaly=None):
    return Scenario.model_validate({
        "scenario_id": "test", "run_id": "test-001", "duration_s": 30,
        "sampling_interval_ms": 1000,
        "assets": [{"asset_id": "ASSET-01", "asset_class": asset_class}],
        "anomalies": [anomaly] if anomaly else [],
    })


@pytest.mark.parametrize("asset_class", ["cnc", "pump", "compressor", "conveyor"])
def test_process_models_emit_canonical_rows(asset_class):
    telemetry, truth, metadata = simulate(fixture_scenario(asset_class), seed=13)
    assert telemetry.height > 0
    assert {"timestamp", "asset_id", "tag_id", "value", "unit", "quality"}.issubset(telemetry.columns)
    assert truth["events"] == []
    assert metadata["synthetic"] is True


def test_same_seed_reproduces_telemetry_and_ground_truth():
    scenario = fixture_scenario(anomaly={
        "type": "bearing_degradation", "asset": "ASSET-01", "start": 5,
        "duration": 10, "parameters": {"vibration_gain": 0.2},
    })
    left = simulate(scenario, 42)
    right = simulate(scenario, 42)
    assert left[0].equals(right[0])
    assert left[1] == right[1]


def test_replay_reproduces_parquet_and_ground_truth(tmp_path):
    scenario = fixture_scenario(anomaly={
        "type": "bearing_degradation", "asset": "ASSET-01", "start": 5,
        "duration": 10,
    })
    source = tmp_path / "source"
    write_run(scenario, 22, source)
    replay(source)
    assert pl.read_parquet(source / "telemetry.parquet").equals(pl.read_parquet(source / "replayed" / "telemetry.parquet"))
    assert json.loads((source / "ground_truth.json").read_text()) == json.loads((source / "replayed" / "ground_truth.json").read_text())


def test_ground_truth_is_separate_file(tmp_path):
    scenario = fixture_scenario()
    write_run(scenario, 4, tmp_path)
    frame = pl.read_parquet(tmp_path / "telemetry.parquet")
    truth = json.loads((tmp_path / "ground_truth.json").read_text())
    assert "events" not in frame.columns
    assert "severity" not in frame.columns
    assert truth["run_id"] == "test-001"


def test_event_benchmark_reports_detection_and_artifacts(tmp_path):
    scenario = fixture_scenario(anomaly={
        "type": "bearing_degradation", "asset": "ASSET-01", "start": 5,
        "duration": 10, "parameters": {"vibration_gain": 0.2},
    })
    run_dir = tmp_path / "run"
    write_run(scenario, 7, run_dir)
    truth = json.loads((run_dir / "ground_truth.json").read_text())
    start, end = truth["events"][0]["observed_start"], truth["events"][0]["observed_end"]
    predictions = tmp_path / "predictions.jsonl"
    predictions.write_text(json.dumps({
        "asset_id": "ASSET-01", "window_start": start, "window_end": end,
        "irregularity_score": 0.9,
    }) + "\n")
    result = evaluate(run_dir / "ground_truth.json", predictions, tmp_path / "report", telemetry_path=run_dir / "telemetry.parquet")
    assert result["event_detection_rate"] == 1
    assert result["mean_event_coverage"] == 1
    assert result["f1"] == 1
    assert result["event_type_metrics"]["bearing_degradation"]["detection_rate"] == 1
    assert result["event_overlapping_alert_windows"] == 1
    assert result["metric_version"] == "2.0.0"
    assert result["alert_episode_count"] == 1
    assert result["false_positive_alert_episodes"] == 0
    assert result["false_positive_windows"] == 0
    assert result["window_recall"] == 1
    assert result["window_pr_auc"] == 1
    assert (tmp_path / "report" / "metrics.json").exists()
    assert (tmp_path / "report" / "report.html").exists()


def test_event_precision_counts_alert_episodes_and_merges_configured_gaps(tmp_path):
    scenario = fixture_scenario(anomaly={
        "type": "sensor_bias", "asset": "ASSET-01", "start": 5,
        "duration": 10, "parameters": {"signal": "spindle_power_kw", "bias": 1.0},
    })
    run_dir = tmp_path / "run"
    write_run(scenario, 78, run_dir)
    event = json.loads((run_dir / "ground_truth.json").read_text(encoding="utf-8"))["events"][0]
    start = datetime.fromisoformat(event["observed_start"])
    predictions = tmp_path / "fragmented-alerts.jsonl"
    windows = [(start, start + timedelta(seconds=4)), (start + timedelta(seconds=5), start + timedelta(seconds=9))]
    predictions.write_text("".join(json.dumps({
        "asset_id": "ASSET-01", "window_start": left.isoformat(),
        "window_end": right.isoformat(), "irregularity_score": 0.9,
    }) + "\n" for left, right in windows), encoding="utf-8")

    separate = evaluate(run_dir / "ground_truth.json", predictions, tmp_path / "separate",
                        telemetry_path=run_dir / "telemetry.parquet")
    merged = evaluate(run_dir / "ground_truth.json", predictions, tmp_path / "merged",
                      telemetry_path=run_dir / "telemetry.parquet", alert_merge_gap_seconds=1)

    assert separate["event_detection_rate"] == 1
    assert separate["alert_episode_count"] == 2
    assert separate["true_positive_alert_episodes"] == 1
    assert separate["false_positive_alert_episodes"] == 1
    assert separate["event_precision"] == pytest.approx(0.5)
    assert separate["event_recall"] == 1
    assert separate["event_f1"] == pytest.approx(2 / 3)
    assert separate["false_positive_windows"] == 0
    assert merged["alert_episode_count"] == 1
    assert merged["event_precision"] == 1
    assert merged["event_recall"] == 1


def test_fragmented_alerts_must_individually_meet_event_coverage_threshold(tmp_path):
    scenario = fixture_scenario(anomaly={
        "type": "sensor_bias", "asset": "ASSET-01", "start": 5,
        "duration": 10, "parameters": {"signal": "spindle_power_kw", "bias": 1.0},
    })
    run_dir = tmp_path / "run"
    write_run(scenario, 79, run_dir)
    event = json.loads((run_dir / "ground_truth.json").read_text(encoding="utf-8"))["events"][0]
    start = datetime.fromisoformat(event["observed_start"])
    event_duration_s = (
        datetime.fromisoformat(event["observed_end"]) - start
    ).total_seconds()
    fragment_s = event_duration_s * 0.05
    predictions = tmp_path / "subthreshold-fragments.jsonl"
    windows = [
        (start, start + timedelta(seconds=fragment_s)),
        (start + timedelta(seconds=2), start + timedelta(seconds=2 + fragment_s)),
    ]
    predictions.write_text("".join(json.dumps({
        "asset_id": "ASSET-01", "window_start": left.isoformat(),
        "window_end": right.isoformat(), "irregularity_score": 0.9,
    }) + "\n" for left, right in windows), encoding="utf-8")

    result = evaluate(run_dir / "ground_truth.json", predictions, tmp_path / "report",
                      telemetry_path=run_dir / "telemetry.parquet", overlap=0.1)

    assert result["events"][0]["coverage_threshold_met"] is True
    assert result["event_detection_rate"] == 0
    assert result["true_positive_alert_episodes"] == 0
    assert result["false_positive_alert_episodes"] == 2


def test_one_alert_episode_cannot_claim_multiple_ground_truth_events(tmp_path):
    scenario = Scenario.model_validate({
        "scenario_id": "two-events-one-alert", "run_id": "two-events-one-alert-1",
        "duration_s": 60, "sampling_interval_ms": 1000,
        "assets": [{"asset_id": "ASSET-01", "asset_class": "cnc"}],
        "anomalies": [
            {"type": "sensor_bias", "asset": "ASSET-01", "start": 10, "duration": 10,
             "parameters": {"signal": "spindle_power_kw", "bias": 1.0}},
            {"type": "sensor_bias", "asset": "ASSET-01", "start": 40, "duration": 10,
             "parameters": {"signal": "spindle_power_kw", "bias": 1.0}},
        ],
    })
    run_dir = tmp_path / "run"
    write_run(scenario, 79, run_dir)
    events = json.loads((run_dir / "ground_truth.json").read_text(encoding="utf-8"))["events"]
    predictions = tmp_path / "broad-alert.jsonl"
    predictions.write_text(json.dumps({
        "asset_id": "ASSET-01", "window_start": events[0]["observed_start"],
        "window_end": events[1]["observed_end"], "irregularity_score": 0.9,
    }) + "\n", encoding="utf-8")

    result = evaluate(run_dir / "ground_truth.json", predictions, tmp_path / "report",
                      telemetry_path=run_dir / "telemetry.parquet")

    assert result["alert_episode_count"] == 1
    assert result["event_overlapping_alert_windows"] == 1
    assert result["true_positive_events"] == 1
    assert result["missed_events"] == 1
    assert result["event_precision"] == 1
    assert result["event_recall"] == pytest.approx(0.5)
    assert result["event_f1"] == pytest.approx(2 / 3)
    assert sum(item["coverage_threshold_met"] for item in result["events"]) == 2
    assert sum(item["detected"] for item in result["events"]) == 1


def test_event_evaluation_rejects_negative_alert_merge_gap(tmp_path):
    run_dir = tmp_path / "run"
    write_run(fixture_scenario(), 80, run_dir)
    predictions = tmp_path / "predictions.jsonl"
    predictions.write_text(json.dumps({
        "asset_id": "ASSET-01", "window_start": EPOCH.isoformat(),
        "window_end": (EPOCH + timedelta(seconds=1)).isoformat(), "irregularity_score": 0.2,
    }) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="finite non-negative"):
        evaluate(run_dir / "ground_truth.json", predictions, tmp_path / "out",
                 telemetry_path=run_dir / "telemetry.parquet", alert_merge_gap_seconds=-1)


def test_benchmark_html_escapes_scenario_identifiers(tmp_path):
    run_id = '<script>alert("run")</script>'
    asset_id = '<img src=x onerror=alert("asset")>'
    scenario = Scenario.model_validate({
        "scenario_id": "html-escape",
        "run_id": run_id,
        "duration_s": 30,
        "sampling_interval_ms": 1000,
        "assets": [{"asset_id": asset_id, "asset_class": "cnc"}],
        "anomalies": [{
            "type": "bearing_degradation", "asset": asset_id, "start": 5,
            "duration": 10, "parameters": {"vibration_gain": 0.2},
        }],
    })
    run_dir = tmp_path / "run"
    write_run(scenario, 7, run_dir)
    truth = json.loads((run_dir / "ground_truth.json").read_text(encoding="utf-8"))
    event = truth["events"][0]
    predictions = tmp_path / "predictions.jsonl"
    predictions.write_text(json.dumps({
        "asset_id": asset_id,
        "window_start": event["observed_start"],
        "window_end": event["observed_end"],
        "irregularity_score": 0.9,
    }) + "\n", encoding="utf-8")

    evaluate(run_dir / "ground_truth.json", predictions, tmp_path / "report", telemetry_path=run_dir / "telemetry.parquet")
    report = (tmp_path / "report" / "report.html").read_text(encoding="utf-8")
    assert "&lt;script&gt;alert(&quot;run&quot;)&lt;/script&gt;" in report
    assert "&lt;img src=x onerror=alert(&quot;asset&quot;)&gt;" in report
    assert run_id not in report
    assert asset_id not in report


@pytest.mark.parametrize(
    ("prediction_windows", "expected_recall", "expected_coverage", "expected_false_positives"),
    [
        ([(10, 15)], 1.0, 0.5, 0),
        ([(0, 4), (10, 15), (10, 15)], 1.0, 0.5, 1),
        ([(0, 4), (4, 5)], 0.0, 0.0, 2),
        ([], 0.0, 0.0, 0),
    ],
)
def test_event_metric_reference_cases(tmp_path, prediction_windows, expected_recall, expected_coverage, expected_false_positives):
    scenario = fixture_scenario(anomaly={
        "type": "sensor_bias", "asset": "ASSET-01", "start": 10,
        "duration": 10, "parameters": {"signal": "spindle_power_kw", "bias": 1.0},
    })
    run_dir = tmp_path / "run"
    write_run(scenario, 77, run_dir)
    predictions = tmp_path / "reference.jsonl"
    predictions.write_text("".join(json.dumps({
        "asset_id": "ASSET-01",
        "window_start": (EPOCH + timedelta(seconds=start)).isoformat(),
        "window_end": (EPOCH + timedelta(seconds=end)).isoformat(),
        "irregularity_score": 0.9,
    }) + "\n" for start, end in prediction_windows), encoding="utf-8")
    if not prediction_windows:
        predictions.write_text(json.dumps({
            "asset_id": "ASSET-01", "window_start": EPOCH.isoformat(),
            "window_end": (EPOCH + timedelta(seconds=1)).isoformat(),
            "irregularity_score": 0.0,
        }) + "\n", encoding="utf-8")
    result = evaluate(run_dir / "ground_truth.json", predictions, tmp_path / "report", telemetry_path=run_dir / "telemetry.parquet")
    assert result["event_recall"] == expected_recall
    assert result["mean_event_coverage"] == pytest.approx(expected_coverage, abs=0.06)
    assert result["false_positive_windows"] == expected_false_positives


def test_event_benchmark_rejects_invalid_prediction_scores(tmp_path):
    truth = tmp_path / "ground_truth.json"
    truth.write_text(json.dumps({"run_id": "x", "events": []}))
    predictions = tmp_path / "predictions.jsonl"
    predictions.write_text(json.dumps({
        "asset_id": "A", "window_start": "2025-01-01T00:00:00+00:00",
        "window_end": "2025-01-01T00:01:00+00:00", "irregularity_score": 2,
    }) + "\n")
    with pytest.raises(ValueError, match="between 0 and 1"):
        evaluate(truth, predictions, tmp_path / "out", telemetry_path=tmp_path / "missing.parquet")


def test_event_benchmark_rejects_reversed_prediction_interval(tmp_path):
    run_dir = tmp_path / "run"
    write_run(fixture_scenario(), 5, run_dir)
    predictions = tmp_path / "predictions.jsonl"
    predictions.write_text(json.dumps({
        "asset_id": "ASSET-01", "window_start": "2025-01-01T00:01:00+00:00",
        "window_end": "2025-01-01T00:00:00+00:00", "irregularity_score": 0.8,
    }) + "\n")
    with pytest.raises(ValueError, match="end after start"):
        evaluate(run_dir / "ground_truth.json", predictions, tmp_path / "out", telemetry_path=run_dir / "telemetry.parquet")


def test_event_benchmark_threshold_tie_is_included_and_naive_timestamps_rejected(tmp_path):
    run_dir = tmp_path / "run"
    write_run(fixture_scenario(), 5, run_dir)
    predictions = tmp_path / "predictions.jsonl"
    predictions.write_text(json.dumps({
        "asset_id": "ASSET-01", "window_start": "2025-01-01T00:00:00+00:00",
        "window_end": "2025-01-01T00:00:01+00:00", "irregularity_score": 0.5,
    }) + "\n", encoding="utf-8")
    result = evaluate(run_dir / "ground_truth.json", predictions, tmp_path / "out", threshold=0.5, telemetry_path=run_dir / "telemetry.parquet")
    assert result["false_positive_windows"] == 1
    predictions.write_text(json.dumps({
        "asset_id": "ASSET-01", "window_start": "2025-01-01T00:00:00",
        "window_end": "2025-01-01T00:00:01", "irregularity_score": 0.5,
    }) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="must include a timezone"):
        evaluate(run_dir / "ground_truth.json", predictions, tmp_path / "out-naive", telemetry_path=run_dir / "telemetry.parquet")


def test_event_benchmark_rejects_non_string_asset_id(tmp_path):
    run_dir = tmp_path / "run"
    write_run(fixture_scenario(), 5, run_dir)
    predictions = tmp_path / "predictions.jsonl"
    predictions.write_text(json.dumps({
        "asset_id": ["ASSET-01"], "window_start": "2025-01-01T00:00:00+00:00",
        "window_end": "2025-01-01T00:00:01+00:00", "irregularity_score": 0.8,
    }) + "\n")
    with pytest.raises(ValueError, match="asset_id values must be non-null strings"):
        evaluate(run_dir / "ground_truth.json", predictions, tmp_path / "out", telemetry_path=run_dir / "telemetry.parquet")


def test_event_benchmark_accepts_declared_asset_with_zero_observations(tmp_path):
    scenario = Scenario.model_validate({
        "scenario_id": "communication-loss", "run_id": "loss-1", "duration_s": 10,
        "assets": [{"asset_id": "P-1", "asset_class": "pump"}],
        "anomalies": [{"type": "asset_communication_loss", "asset": "P-1", "start": 0, "duration": 10}],
    })
    run_dir = tmp_path / "run"
    write_run(scenario, 5, run_dir)
    assert pl.read_parquet(run_dir / "telemetry.parquet").columns
    predictions = tmp_path / "predictions.jsonl"
    predictions.write_text(json.dumps({
        "asset_id": "P-1", "window_start": "2025-01-01T00:00:00+00:00",
        "window_end": "2025-01-01T00:00:10+00:00", "irregularity_score": 0.8,
    }) + "\n")
    result = evaluate(run_dir / "ground_truth.json", predictions, tmp_path / "out", telemetry_path=run_dir / "telemetry.parquet")
    assert result["event_detection_rate"] == 1
    assert result["exposure_asset_hours"] == pytest.approx(10 / 3600)


def test_full_horizon_prediction_gets_normal_asset_false_positives(tmp_path):
    scenario = Scenario.model_validate({
        "scenario_id": "two-asset", "run_id": "two-asset-1", "duration_s": 30,
        "assets": [
            {"asset_id": "CNC-01", "asset_class": "cnc"},
            {"asset_id": "PUMP-01", "asset_class": "pump"},
        ],
        "anomalies": [{"type": "bearing_degradation", "asset": "CNC-01", "start": 10, "duration": 5}],
    })
    run_dir = tmp_path / "run"
    write_run(scenario, 13, run_dir)
    telemetry = pl.read_parquet(run_dir / "telemetry.parquet")
    epoch = telemetry.select(pl.col("timestamp").dt.epoch("ms").min().alias("first"), pl.col("timestamp").dt.epoch("ms").max().alias("last")).row(0, named=True)
    first, last = datetime.fromtimestamp(epoch["first"] / 1000, UTC), datetime.fromtimestamp(epoch["last"] / 1000, UTC)
    predictions = tmp_path / "predictions.jsonl"
    predictions.write_text("\n".join(json.dumps({
        "asset_id": asset, "window_start": str(first), "window_end": str(last), "irregularity_score": 0.9,
    }) for asset in ["CNC-01", "PUMP-01"]) + "\n")
    result = evaluate(run_dir / "ground_truth.json", predictions, tmp_path / "report", telemetry_path=run_dir / "telemetry.parquet")
    assert result["false_positive_windows"] == 1
    assert result["window_precision"] < 0.5
    assert result["window_pr_auc"] < 1


def test_benchmark_class_imbalance_and_mixed_assets_use_half_open_intervals(tmp_path):
    scenario = Scenario.model_validate({
        "scenario_id": "imbalanced-mixed-assets", "run_id": "imbalanced-mixed-1", "duration_s": 40,
        "sampling_interval_ms": 1000,
        "assets": [
            {"asset_id": "CNC-01", "asset_class": "cnc"},
            {"asset_id": "PUMP-01", "asset_class": "pump"},
        ],
        "anomalies": [{"type": "sensor_bias", "asset": "CNC-01", "start": 9, "duration": 11,
                       "parameters": {"signal": "spindle_power_kw", "bias": 1.0}}],
    })
    run_dir = tmp_path / "run"
    write_run(scenario, 29, run_dir)
    truth = json.loads((run_dir / "ground_truth.json").read_text(encoding="utf-8"))
    event = truth["events"][0]
    event_start = event["observed_start"]
    event_end = event["observed_end"]
    predictions = tmp_path / "predictions.jsonl"
    records = [
        {"asset_id": "PUMP-01", "window_start": EPOCH.isoformat(),
         "window_end": (EPOCH + timedelta(seconds=1)).isoformat(), "irregularity_score": 0.9},
        {"asset_id": "CNC-01", "window_start": event_start,
         "window_end": event_end, "irregularity_score": 0.8},
    ]
    predictions.write_text("".join(json.dumps(row) + "\n" for row in records), encoding="utf-8")
    result = evaluate(run_dir / "ground_truth.json", predictions, tmp_path / "report",
                      telemetry_path=run_dir / "telemetry.parquet")
    assert result["event_detection_rate"] == 1
    assert result["false_positive_windows"] == 1
    # 10 positive samples out of 80 expected asset samples. One higher-scored
    # false alarm precedes those positives, so average precision is 10/11.
    assert result["window_pr_auc"] == pytest.approx(10 / 11)
    _scores, labels = _timestamp_scores(
        truth["events"], pl.read_ndjson(predictions), pl.read_parquet(run_dir / "telemetry.parquet"),
        json.loads((run_dir / "run_metadata.json").read_text(encoding="utf-8")),
    )
    event_end_dt = datetime.fromisoformat(event_end)
    timestamps = [EPOCH + timedelta(seconds=i) for i in range(40)]
    assert sum(labels) == 10
    assert not labels[timestamps.index(event_end_dt)]


def test_timestamp_scoring_uses_highest_active_score_with_half_open_windows():
    start = EPOCH
    records = [
        {"asset_id": "ASSET-01", "window_start": start.isoformat(),
         "window_end": (start + timedelta(seconds=2)).isoformat(), "irregularity_score": 0.4},
        {"asset_id": "ASSET-01", "window_start": start.isoformat(),
         "window_end": (start + timedelta(seconds=4)).isoformat(), "irregularity_score": 0.9},
        {"asset_id": "ASSET-01", "window_start": (start + timedelta(seconds=1)).isoformat(),
         "window_end": (start + timedelta(seconds=3)).isoformat(), "irregularity_score": 0.8},
    ]
    predictions = pl.read_ndjson(io.BytesIO("".join(json.dumps(row) + "\n" for row in records).encode()))
    metadata = {
        "started_at": start.isoformat(), "duration_s": 4, "sampling_interval_ms": 1000,
        "asset_ids": ["ASSET-01", "ASSET-02"],
    }

    scores, labels = _timestamp_scores([], predictions, pl.DataFrame(), metadata)

    assert scores == [0.9, 0.9, 0.9, 0.9, 0.0, 0.0, 0.0, 0.0]
    assert labels == [False] * 8


def test_timestamp_scoring_labels_overlapping_events_with_half_open_windows():
    start = EPOCH
    events = [
        {"asset_id": "ASSET-01", "start": (start + timedelta(seconds=offset)).isoformat(),
         "end": (start + timedelta(seconds=offset + 2)).isoformat()}
        for offset in (3, 0, 1, 4)
    ]
    metadata = {
        "started_at": start.isoformat(), "duration_s": 8, "sampling_interval_ms": 1000,
        "asset_ids": ["ASSET-01"],
    }

    scores, labels = _timestamp_scores(events, pl.DataFrame(), pl.DataFrame(), metadata)

    assert scores == [0.0] * 8
    assert labels == [True, True, True, True, True, True, False, False]


def test_normal_only_benchmark_reports_pr_auc_as_undefined(tmp_path):
    run_dir = tmp_path / "normal-run"
    write_run(fixture_scenario(), 30, run_dir)
    predictions = tmp_path / "predictions.jsonl"
    predictions.write_text(json.dumps({
        "asset_id": "ASSET-01", "window_start": EPOCH.isoformat(),
        "window_end": (EPOCH + timedelta(seconds=1)).isoformat(), "irregularity_score": 0.9,
    }) + "\n", encoding="utf-8")
    result = evaluate(run_dir / "ground_truth.json", predictions, tmp_path / "report",
                      telemetry_path=run_dir / "telemetry.parquet")
    assert result["event_type_metrics"] == {}
    assert result["precision"] is None
    assert result["recall"] is None
    assert result["f1"] is None
    assert result["event_detection_rate"] is None
    assert result["false_positive_windows"] == 1
    assert result["window_pr_auc"] is None
    assert result["pr_auc"] is None


def test_benchmark_scores_missing_samples_on_expected_cadence(tmp_path):
    scenario = fixture_scenario(anomaly={
        "type": "missing_telemetry", "asset": "ASSET-01", "start": 5,
        "duration": 15, "parameters": {"loss_pct": 100},
    })
    run_dir = tmp_path / "run"
    write_run(scenario, 18, run_dir)
    truth = json.loads((run_dir / "ground_truth.json").read_text())
    event = truth["events"][0]
    predictions = tmp_path / "predictions.jsonl"
    predictions.write_text(json.dumps({
        "asset_id": "ASSET-01", "window_start": event["start"],
        "window_end": event["end"], "irregularity_score": 0.9,
    }) + "\n")
    result = evaluate(run_dir / "ground_truth.json", predictions, tmp_path / "report", telemetry_path=run_dir / "telemetry.parquet")
    assert result["event_detection_rate"] == 1
    assert result["window_recall"] > 0
    assert result["window_pr_auc"] > 0
    assert result["exposure_asset_hours"] == pytest.approx(30 / 3600)


def test_pump_load_couples_current_and_flow():
    asset = AssetSpec(asset_id="P-1", asset_class="pump")
    low = ProcessState(temperature=22)
    high = ProcessState(temperature=22)
    low_row = simulate_step(asset, low, "LOW_LOAD", 1, 22, __import__("numpy").random.default_rng(3))
    high_row = simulate_step(asset, high, "HIGH_LOAD", 1, 22, __import__("numpy").random.default_rng(3))
    assert high_row["motor_current_a"] > low_row["motor_current_a"]
    assert high_row["flow_l_min"] > low_row["flow_l_min"]


@pytest.mark.parametrize("asset_class,signal", [
    ("cnc", "spindle_power_kw"), ("pump", "motor_current_a"),
    ("compressor", "motor_current_a"), ("conveyor", "motor_current_a"),
])
def test_each_process_model_couples_high_load_to_power_or_current(asset_class, signal):
    asset = AssetSpec(asset_id="A-1", asset_class=asset_class)
    low, high = ProcessState(temperature=22), ProcessState(temperature=22)
    low_signals = simulate_step(asset, low, "LOW_LOAD", 10, 22, np.random.default_rng(33))
    high_signals = simulate_step(asset, high, "HIGH_LOAD", 10, 22, np.random.default_rng(33))
    assert high_signals[signal] > low_signals[signal]
    assert high.temperature > low.temperature


def test_metropt_rail_apu_profile_stays_inside_observed_mode_envelopes():
    asset = AssetSpec(asset_id="APU-1", asset_class="compressor", process_profile="metropt3_rail_apu")
    loaded = [simulate_step(asset, ProcessState(temperature=65), "NORMAL_LOAD", 10, 22, np.random.default_rng(seed)) for seed in range(200)]
    off = [simulate_step(asset, ProcessState(temperature=65), "OFF", 10, 22, np.random.default_rng(seed)) for seed in range(200)]
    loaded_currents = np.array([sample["motor_current_a"] for sample in loaded])
    off_currents = np.array([sample["motor_current_a"] for sample in off])
    loaded_pressure = np.array([sample["pressure_bar"] for sample in loaded])
    assert 4.7 < np.quantile(loaded_currents, 0.5) < 6.3
    assert np.quantile(off_currents, 0.95) < 0.1
    assert 8 < np.quantile(loaded_pressure, 0.5) < 10
    assert all(0 <= sample["oil_temperature_c"] <= 110 for sample in loaded + off)


def test_metropt_rail_apu_profile_is_rejected_for_non_compressor_assets():
    with pytest.raises(ValueError, match="requires asset_class=compressor"):
        AssetSpec(asset_id="P-1", asset_class="pump", process_profile="metropt3_rail_apu")


def test_metropt_rail_apu_profile_parameters_are_explicit_and_change_outputs():
    default = AssetSpec(asset_id="APU-1", asset_class="compressor", process_profile="metropt3_rail_apu")
    adjusted = AssetSpec(
        asset_id="APU-1", asset_class="compressor", process_profile="metropt3_rail_apu",
        process_profile_version="1.0.0", process_parameters={"current_loaded_base_a": 5.2},
    )
    default_row = simulate_step(default, ProcessState(temperature=65), "NORMAL_LOAD", 10, 22, np.random.default_rng(13))
    adjusted_row = simulate_step(adjusted, ProcessState(temperature=65), "NORMAL_LOAD", 10, 22, np.random.default_rng(13))
    assert adjusted_row["motor_current_a"] - default_row["motor_current_a"] == pytest.approx(0.44)
    assert adjusted.model_dump()["process_profile_version"] == "1.0.0"


def test_metropt_rail_apu_profile_rejects_nonpositive_time_constants():
    with pytest.raises(ValueError, match="must be positive"):
        AssetSpec(
            asset_id="APU-1", asset_class="compressor", process_profile="metropt3_rail_apu",
            process_parameters={"oil_thermal_tau_s": 0},
        )


def test_sampling_jitter_changes_intervals_deterministically():
    scenario = Scenario.model_validate({
        "scenario_id": "jitter", "duration_s": 20, "sampling_interval_ms": 1000,
        "sampling_jitter_ms": 50, "assets": [{"asset_id": "P-1", "asset_class": "pump"}],
    })
    left = simulate(scenario, 55)[0]
    right = simulate(scenario, 55)[0]
    assert left.equals(right)
    assert left.filter((pl.col("sampling_interval_ms") < 950) | (pl.col("sampling_interval_ms") > 1050)).is_empty()
    assert left.get_column("sampling_interval_ms").n_unique() > 1


def test_shift_pattern_changes_regime_deterministically():
    regimes = ["LOW_LOAD", "NORMAL_LOAD", "HIGH_LOAD"]
    assert regime_at(100, 10000, regimes, regimes) == "LOW_LOAD"
    assert regime_at(5000, 10000, regimes, regimes) == "NORMAL_LOAD"
    assert regime_at(9000, 10000, regimes, regimes) == "HIGH_LOAD"
    assert regime_at(3, 10, ["OFF"]) == "OFF"
    assert regime_at(3, 10, ["MAINTENANCE"]) == "MAINTENANCE"


def test_shift_pattern_falls_back_to_supported_asset_regimes():
    assert regime_at(50, 100, ["LOW_LOAD", "NORMAL_LOAD"], ["MAINTENANCE"]) == "NORMAL_LOAD"


def test_ground_truth_records_actual_regime_intervals_even_when_plc_hides_them():
    telemetry, truth, _ = simulate(fixture_scenario(), 14)
    assert telemetry.get_column("operating_regime").null_count() == telemetry.height
    intervals = truth["operating_regimes"]
    assert intervals and {row["asset_id"] for row in intervals} == {"ASSET-01"}
    assert all(row["start"] <= row["end"] for row in intervals)
    assert intervals[0]["start"] == EPOCH.isoformat()
    assert intervals[-1]["end"] == (EPOCH.replace(second=30)).isoformat()


def test_training_suite_samples_reproducible_mixed_run_definitions():
    import yaml

    suite = yaml.safe_load(Path("suites/training-v0.2.yaml").read_text(encoding="utf-8"))
    sampled_a = _generate_suite_scenario(suite["scenario"], suite["generation"], np.random.default_rng(87), "same-run")
    sampled_b = _generate_suite_scenario(suite["scenario"], suite["generation"], np.random.default_rng(87), "same-run")
    assert sampled_a == sampled_b
    assert Scenario.model_validate(sampled_a)
    assert sampled_a["duration_s"] in range(300, 601)
    assert sampled_a["sampling_interval_ms"] in {500, 1000}
    assert len(sampled_a["assets"]) in {1, 2, 4}
    assert all(0 <= event["start"] < sampled_a["duration_s"] for event in sampled_a["anomalies"])


def test_training_v03_distribution_samples_compressor_air_leaks():
    import yaml

    suite = yaml.safe_load(Path("suites/training-v0.3.yaml").read_text(encoding="utf-8"))
    assets_by_id = {}
    sampled_air_leak = None
    for seed in range(300):
        sampled = _generate_suite_scenario(
            suite["scenario"], suite["generation"], np.random.default_rng(seed), f"air-leak-{seed}"
        )
        assets_by_id.update({asset["asset_id"]: asset["asset_class"] for asset in sampled["assets"]})
        sampled_air_leak = next((event for event in sampled["anomalies"] if event["type"] == "air_leak"), None)
        if sampled_air_leak:
            break

    assert sampled_air_leak is not None
    assert assets_by_id[sampled_air_leak["asset"]] == "compressor"
    assert 0.04 <= sampled_air_leak["parameters"]["pressure_loss_fraction"] <= 0.35
    assert 0.05 <= sampled_air_leak["parameters"]["current_gain"] <= 0.40
    assert Scenario.model_validate({**sampled, "anomalies": [sampled_air_leak]})

    compressor_event_count = 0
    anomalous_run_count = 0
    for seed in range(300):
        sampled = _generate_suite_scenario(
            suite["scenario"], suite["generation"], np.random.default_rng(seed), f"mix-{seed}"
        )
        anomalous_run_count += bool(sampled["anomalies"])
        compressor_event_count += sum(event["type"] == "air_leak" for event in sampled["anomalies"])
    assert compressor_event_count >= 15
    assert anomalous_run_count >= 150

    # Event placement must remain feasible and deterministic over independent seeds.
    for seed in range(120):
        first = _generate_suite_scenario(
            suite["scenario"], suite["generation"], np.random.default_rng(seed), f"stability-{seed}"
        )
        second = _generate_suite_scenario(
            suite["scenario"], suite["generation"], np.random.default_rng(seed), f"stability-{seed}"
        )
        assert first == second
        Scenario.model_validate(first)
        for asset_id in {event["asset"] for event in first["anomalies"]}:
            asset_events = sorted(
                (event for event in first["anomalies"] if event["asset"] == asset_id),
                key=lambda event: event["start"],
            )
            assert all(a["start"] + a["duration"] <= b["start"] for a, b in pairwise(asset_events))


def test_challenge_v02_can_generate_ephemeral_compressor_air_leak(tmp_path):
    import yaml

    from ot_lab.simulation import generate_challenge

    training_path = Path("suites/training-v0.3.yaml")
    challenge_path = Path("suites/challenge-v0.2.yaml")
    challenge = yaml.safe_load(challenge_path.read_text(encoding="utf-8"))
    generation = {**challenge["generation"], "anomaly_probability": 1.0}
    seed = None
    for candidate_seed in range(500):
        sampled = _generate_suite_scenario(
            challenge["scenario"], generation, np.random.default_rng(candidate_seed), "challenge-hidden"
        )
        if any(event["type"] == "air_leak" for event in sampled["anomalies"]):
            seed = candidate_seed
            break
    assert seed is not None

    case_dir, truth_path = generate_challenge(
        training_path, tmp_path, master_seed=seed, challenge_suite_path=challenge_path
    )
    truth = json.loads(truth_path.read_text(encoding="utf-8"))
    metadata = json.loads((case_dir / "run_metadata.json").read_text(encoding="utf-8"))

    assert any(event["type"] == "air_leak" for event in truth["events"])
    assert "seed" not in metadata and "scenario_sha256" not in metadata
    assert not (case_dir / "scenario.yaml").exists()


def test_normal_suite_samples_reproducible_process_variation_ranges():
    import yaml

    from ot_lab.simulation import _resolve_ranges

    suite = yaml.safe_load(Path("suites/normal-operation-v0.1.yaml").read_text(encoding="utf-8"))
    generation = suite["generation"]
    draws = []
    for seed in range(30):
        rng = np.random.default_rng(seed)
        sampled = _generate_suite_scenario(suite["scenario"], generation, rng, f"normal-{seed}")
        sampled = _resolve_ranges(sampled, rng)
        validated = Scenario.model_validate(sampled)
        assert validated.anomalies == []
        parameters = [asset.process_parameters for asset in validated.assets]
        assert parameters
        assert all(0.85 <= item["load_scale"] <= 1.15 for item in parameters)
        assert all(0.8 <= item["sensor_noise_scale"] <= 1.25 for item in parameters)
        assert all(0.75 <= item["thermal_time_constant_scale"] <= 1.4 for item in parameters)
        draws.append(parameters[0])
    assert len({tuple(sorted(item.items())) for item in draws}) > 1
    # A single seeded generator must drive both scenario-profile and range selection in batch.
    same_rng = np.random.default_rng(11)
    first = _resolve_ranges(_generate_suite_scenario(suite["scenario"], generation, same_rng, "repeat"), same_rng)
    same_rng = np.random.default_rng(11)
    second = _resolve_ranges(_generate_suite_scenario(suite["scenario"], generation, same_rng, "repeat"), same_rng)
    assert first == second


def test_false_positive_stress_suite_samples_event_free_normal_transitions():
    import yaml

    from ot_lab.simulation import _resolve_ranges

    suite = yaml.safe_load(Path("suites/false-positive-stress-v0.1.yaml").read_text(encoding="utf-8"))
    patterns = set()
    sampled_assets = set()
    for seed in range(120):
        rng = np.random.default_rng(seed)
        data = _generate_suite_scenario(suite["scenario"], suite["generation"], rng, f"fp-{seed}")
        data = _resolve_ranges(data, rng)
        scenario = Scenario.model_validate(data)
        assert scenario.anomalies == []
        patterns.add(tuple(scenario.shift_pattern))
        sampled_assets.update(asset.asset_class for asset in scenario.assets)
        assert 600 <= scenario.duration_s <= 2400
        assert -5 <= scenario.ambient_temperature_c <= 38
        assert all(0 <= asset.process_parameters["initial_temperature_offset_c"] <= 25 for asset in scenario.assets)
    assert len(patterns) >= 5
    assert {"cnc", "pump"}.issubset(sampled_assets)
    assert any("MAINTENANCE" in pattern for pattern in patterns)
    assert any("OFF" in pattern for pattern in patterns)


def test_warm_start_asset_begins_above_ambient_temperature():
    scenario = Scenario.model_validate({
        "scenario_id": "warm-start", "run_id": "warm-start-1", "duration_s": 30,
        "ambient_temperature_c": 10,
        "assets": [{
            "asset_id": "PUMP-01", "asset_class": "pump",
            "process_parameters": {"initial_temperature_offset_c": 20.0},
        }],
    })
    telemetry, _, _ = simulate(scenario, 77)
    first = telemetry.filter(pl.col("tag_id") == "motor_temperature_c").sort("timestamp").select(pl.col("value").first()).item()
    assert first > scenario.ambient_temperature_c


def test_randomized_training_dataset_has_mixed_faults_and_auditable_partitions(tmp_path):
    import yaml

    suite_data = yaml.safe_load(Path("suites/training-v0.2.yaml").read_text(encoding="utf-8"))
    suite_data["generation"]["vary"]["duration_s"] = {"min": 60, "max": 60}
    suite_path = tmp_path / "training-suite.yaml"
    suite_path.write_text(yaml.safe_dump(suite_data, sort_keys=False), encoding="utf-8")
    output = tmp_path / "randomized-dataset"
    batch(suite_path, 300, output, seed=20261003)

    manifest = json.loads((output / "dataset_manifest.json").read_text(encoding="utf-8"))
    assert (output / "suite.yaml").read_text(encoding="utf-8") == suite_path.read_text(encoding="utf-8")
    assert manifest["class_distribution"]["normal"] > 0
    assert manifest["class_distribution"]["anomalous"] > 0
    assert manifest["data_license"] == "CC-BY-4.0"
    assert manifest["generator_argv"][-1] == str(output)
    assert len(manifest["asset_distribution"]) == 4
    assert len(manifest["event_distribution"]) >= 12
    assert len(manifest["regime_episode_distribution"]) >= 4
    assert manifest["master_seed"] == 20261003
    assert len({run["seed"] for run in manifest["runs"]}) == 300
    assert len({run["scenario_sha256"] for run in manifest["runs"]}) == 300
    for run in manifest["runs"]:
        truth = json.loads((output / run["partition"] / run["run_id"] / "ground_truth.json").read_text(encoding="utf-8"))
        assert all(event["affected_signals"] == [] for event in truth["events"] if event["severity"] == 0)
        assert all(
            event["affected_signals"]
            or (event["type"] == "missing_telemetry" and event["parameters"].get("loss_pct", 0) < 100)
            for event in truth["events"] if event["severity"] > 0
        )
        assert truth["ground_truth_schema_version"] == "1.1.0"
        by_asset = {}
        for event in truth["events"]:
            by_asset.setdefault(event["asset_id"], []).append(event)
        for events in by_asset.values():
            ordered = sorted(events, key=lambda event: event["start"])
            assert all(left["end"] <= right["start"] for left, right in pairwise(ordered))
    for partition, counts in manifest["class_distribution_by_partition"].items():
        assert counts["normal"] > 0 and counts["anomalous"] > 0
        assert manifest["partition_counts"][partition] == sum(counts.values())


def test_false_positive_stress_suite_reaches_warmup_high_load_maintenance_and_cooldown():
    from pathlib import Path

    from ot_lab.simulation import read_scenario

    scenario = read_scenario(Path("scenarios/normal-false-positive-stress.yaml"))
    telemetry, ground_truth, _ = simulate(scenario, 3)
    assert {"WARMUP", "HIGH_LOAD", "MAINTENANCE", "COOLDOWN"}.issubset(set(telemetry["operating_regime"].drop_nulls().unique().to_list()))
    assert ground_truth["events"] == []


def test_missing_telemetry_uses_configured_loss_and_records_event_interval():
    scenario = fixture_scenario(anomaly={
        "type": "missing_telemetry", "asset": "ASSET-01", "start": 5,
        "duration": 15, "parameters": {"loss_pct": 100},
    })
    telemetry, truth, _ = simulate(scenario, 11)
    assert telemetry.filter(pl.col("timestamp") < pl.datetime(2025, 1, 1, 0, 0, 6, time_zone="UTC")).height > 0
    assert telemetry.filter(pl.col("timestamp") >= pl.datetime(2025, 1, 1, 0, 0, 6, time_zone="UTC")).height < telemetry.height
    assert truth["events"][0]["observed_start"]
    assert truth["events"][0]["observed_end"]


@pytest.mark.parametrize("loss_pct", [5, 10, 25, 50, 100])
def test_missing_telemetry_accepts_required_loss_rates(loss_pct):
    baseline = simulate(Scenario.model_validate({**fixture_scenario().model_dump(), "sampling_jitter_ms": 0}), 17)[0]
    scenario = Scenario.model_validate({**fixture_scenario().model_dump(), "sampling_jitter_ms": 0, "anomalies": [{
        "type": "missing_telemetry", "asset": "ASSET-01", "start": 5,
        "duration": 15, "severity": 1.0, "parameters": {"loss_pct": loss_pct},
    }]})
    telemetry, _, _ = simulate(scenario, 17)
    # Count missing signal/timestamp pairs against the expected grid.
    event_start_ms = int(EPOCH.timestamp() * 1000) + 6_000
    event_end_ms = int(EPOCH.timestamp() * 1000) + 20_000
    expected_rows = baseline.filter(
        (pl.col("timestamp").dt.epoch("ms") >= event_start_ms) &
        (pl.col("timestamp").dt.epoch("ms") < event_end_ms)
    ).select("timestamp", "tag_id")
    actual_rows = telemetry.select("timestamp", "tag_id")
    missing = expected_rows.join(actual_rows, on=["timestamp", "tag_id"], how="anti")
    expected = expected_rows.height
    observed_loss = missing.height / expected
    if loss_pct == 100:
        assert missing.height > 0
    else:
        assert abs(observed_loss - loss_pct / 100) <= 0.28
    if loss_pct == 100:
        assert telemetry.filter(
            (pl.col("timestamp").dt.epoch("ms") >= event_start_ms) &
            (pl.col("timestamp").dt.epoch("ms") < event_end_ms)
        ).height == 0
    else:
        assert telemetry.filter(
            (pl.col("timestamp").dt.epoch("ms") >= event_start_ms) &
            (pl.col("timestamp").dt.epoch("ms") < event_end_ms)
        ).height > 0


@pytest.mark.parametrize("severity", [0.0, 0.5, 1.0])
def test_severity_scales_sensor_bias_monotonically(severity):
    signal = "spindle_power_kw"
    scenario = Scenario.model_validate({**fixture_scenario().model_dump(), "sampling_jitter_ms": 0, "anomalies": [{
        "type": "sensor_bias", "asset": "ASSET-01", "start": 5,
        "duration": 10, "severity": severity,
        "parameters": {"signal": signal, "bias": 100.0},
    }]})
    baseline = simulate(Scenario.model_validate({**fixture_scenario().model_dump(), "sampling_jitter_ms": 0}), 23)[0]
    telemetry, truth, _ = simulate(scenario, 23)
    joined = baseline.join(telemetry, on=["timestamp", "tag_id"], suffix="_anomalous")
    affected = joined.filter(pl.col("tag_id") == signal)
    event_start_ms = int(EPOCH.timestamp() * 1000) + 5_000
    event_end_ms = int(EPOCH.timestamp() * 1000) + 15_000
    affected = affected.filter(
        (pl.col("timestamp").dt.epoch("ms") >= event_start_ms) &
        (pl.col("timestamp").dt.epoch("ms") < event_end_ms)
    )
    delta = (affected["value_anomalous"] - affected["value"]).mean()
    assert delta == pytest.approx(100 * severity, abs=10)
    assert truth["events"][0]["severity"] == severity


def test_missing_telemetry_severity_scales_loss_probability():
    baseline = simulate(Scenario.model_validate({**fixture_scenario().model_dump(), "sampling_jitter_ms": 0}), 31)[0]
    observed = []
    for severity in (0.25, 0.5, 1.0):
        scenario = Scenario.model_validate({**fixture_scenario().model_dump(), "sampling_jitter_ms": 0, "anomalies": [{
            "type": "missing_telemetry", "asset": "ASSET-01", "start": 5,
            "duration": 15, "severity": severity,
            "parameters": {"loss_pct": 80},
        }]})
        telemetry, _, _ = simulate(scenario, 31)
        baseline = simulate(Scenario.model_validate({**fixture_scenario().model_dump(), "sampling_jitter_ms": 0}), 31)[0]
        event_start = pl.datetime(2025, 1, 1, 0, 0, 6, time_zone="UTC")
        event_end = pl.datetime(2025, 1, 1, 0, 0, 20, time_zone="UTC")
        expected = baseline.filter((pl.col("timestamp") >= event_start) & (pl.col("timestamp") < event_end)).height
        actual = telemetry.filter((pl.col("timestamp") >= event_start) & (pl.col("timestamp") < event_end)).height
        observed.append((expected - actual) / expected)
    assert observed == sorted(observed)
    assert observed[0] < observed[1] < observed[2]
    assert observed[0] == pytest.approx(0.2, abs=0.15)
    assert observed[-1] == pytest.approx(0.8, abs=0.15)


def test_missing_telemetry_masks_vary_by_run_seed_and_reproduce_with_same_seed():
    scenario = Scenario.model_validate({**fixture_scenario().model_dump(), "sampling_jitter_ms": 0, "anomalies": [{
        "type": "missing_telemetry", "asset": "ASSET-01", "start": 5,
        "duration": 15, "severity": 1.0, "parameters": {"loss_pct": 50},
    }]})
    first = simulate(scenario, 101)[0]
    repeated = simulate(scenario, 101)[0]
    second_seed = simulate(scenario, 102)[0]
    assert first.equals(repeated)
    first_keys = set(first.with_columns(pl.col("timestamp").dt.epoch("ms")).select("timestamp", "tag_id").iter_rows())
    second_keys = set(second_seed.with_columns(pl.col("timestamp").dt.epoch("ms")).select("timestamp", "tag_id").iter_rows())
    assert first_keys != second_keys


@pytest.mark.parametrize("kind", ["single_signal_loss", "asset_communication_loss", "quality_degradation"])
def test_discrete_effect_severity_scales_effect_frequency(kind):
    signals = {f"tag_{index}": float(index) for index in range(8)}
    observed = []
    for severity in (0.0, 0.25, 0.5, 1.0):
        affected_total = 0
        event = Anomaly(
            type=kind, asset="P-1", start=0, duration=10,
            severity=severity,
            parameters={"loss_pct": 80, "tag_selection": "single"} if kind == "single_signal_loss" else {"loss_pct": 80},
        )
        for sample_index in range(2000):
            _row, affected, quality = _affect(
                event, signals.copy(), 1,
                {"process": ProcessState(temperature=20)}, "pump", sample_index, 123,
            )
            if kind == "quality_degradation":
                affected_total += quality == "BAD"
            elif kind == "single_signal_loss":
                affected_total += bool(affected)
            else:
                affected_total += len(affected)
        observed.append(affected_total)

    assert observed[0] == 0
    assert observed == sorted(observed)
    assert observed[-1] > observed[1] > 0


@pytest.mark.parametrize(("severity", "expected"), [(0.0, 20.0), (0.5, 15.0), (1.0, 10.0)])
def test_sensor_stuck_severity_scales_blend_with_held_value(severity, expected):
    event = Anomaly(
        type="sensor_stuck", asset="P-1", start=0, duration=10,
        severity=severity, parameters={"signal": "motor_current_a"},
    )
    row, affected, quality = _affect(
        event, {"motor_current_a": 20.0}, 1, {"__sensor_stuck": ProcessState(previous_signals={"sensor_stuck:event-0:motor_current_a": 10.0})}, "pump", 1, 123,
    )
    assert row["motor_current_a"] == pytest.approx(expected)
    assert bool(affected) is (severity > 0)
    assert quality == ("UNCERTAIN" if severity > 0 else "GOOD")


def test_sensor_stuck_holds_first_event_value_across_time():
    event = Anomaly(
        type="sensor_stuck", asset="P-1", start=0, duration=10, severity=0.5,
        parameters={"signal": "motor_current_a"},
    )
    states = {}
    first, _, _ = _affect(event, {"motor_current_a": 10.0}, 1, states, "pump", 1, 7, "evt-1")
    second, _, _ = _affect(event, {"motor_current_a": 30.0}, 2, states, "pump", 2, 7, "evt-1")
    assert first["motor_current_a"] == pytest.approx(10.0)
    assert second["motor_current_a"] == pytest.approx(20.0)


@pytest.mark.parametrize(("selection", "count"), [("single", 1), ("multiple", 3), ("all", 7)])
def test_missing_telemetry_supports_configurable_tag_selection(selection, count):
    scenario = Scenario.model_validate({**fixture_scenario().model_dump(), "sampling_jitter_ms": 0, "anomalies": [{
        "type": "missing_telemetry", "asset": "ASSET-01", "start": 5,
        "duration": 5, "severity": 1.0,
        "parameters": {"loss_pct": 100, "tag_selection": selection, "tag_count": count},
    }]})
    telemetry, truth, _ = simulate(scenario, 88)
    selected = truth["events"][0]["affected_signals"]
    assert len(selected) == count
    remaining = telemetry.filter(
        (pl.col("timestamp") >= pl.datetime(2025, 1, 1, 0, 0, 6, time_zone="UTC")) &
        (pl.col("timestamp") < pl.datetime(2025, 1, 1, 0, 0, 10, time_zone="UTC"))
    )
    assert not set(selected) & set(remaining.get_column("tag_id").unique().to_list())


def test_loss_selection_rejects_unknown_and_impossible_tag_counts():
    for parameters in ({"signal": "not_a_tag"}, {"tag_selection": "multiple", "tag_count": 99}):
        scenario = Scenario.model_validate({**fixture_scenario().model_dump(), "anomalies": [{
            "type": "missing_telemetry", "asset": "ASSET-01", "start": 5,
            "duration": 5, "parameters": parameters,
        }]})
        with pytest.raises(ValueError, match="unknown signals|tag_count"):
            simulate(scenario, 2)


@pytest.mark.parametrize("loss_pct", [5, 10, 25, 50, 100])
def test_missing_telemetry_empirical_rate_over_independent_seeds(loss_pct):
    scenario = Scenario.model_validate({**fixture_scenario().model_dump(), "sampling_jitter_ms": 0, "anomalies": [{
        "type": "missing_telemetry", "asset": "ASSET-01", "start": 5,
        "duration": 15, "severity": 1.0, "parameters": {"loss_pct": loss_pct},
    }]})
    expected = 0
    omitted = 0
    for seed in range(200, 240):
        baseline = simulate(Scenario.model_validate({**fixture_scenario().model_dump(), "sampling_jitter_ms": 0}), seed)[0]
        actual = simulate(scenario, seed)[0]
        start_ms = int(EPOCH.timestamp() * 1000) + 6_000
        end_ms = int(EPOCH.timestamp() * 1000) + 20_000
        expected_rows = baseline.filter(
            (pl.col("timestamp").dt.epoch("ms") >= start_ms) & (pl.col("timestamp").dt.epoch("ms") < end_ms)
        ).select("timestamp", "tag_id")
        actual_rows = actual.select("timestamp", "tag_id")
        expected += expected_rows.height
        omitted += expected_rows.join(actual_rows, on=["timestamp", "tag_id"], how="anti").height
    if loss_pct == 100:
        assert omitted == expected
    else:
        assert omitted / expected == pytest.approx(loss_pct / 100, abs=0.012)


@pytest.mark.parametrize("asset_class", ["cnc", "pump", "compressor", "conveyor"])
def test_process_simulation_is_reproducible_for_every_asset(asset_class):
    scenario = fixture_scenario(asset_class)
    left = simulate(scenario, 123)[0]
    right = simulate(scenario, 123)[0]
    assert left.equals(right)


def test_quality_degradation_is_exposed_in_canonical_quality():
    scenario = fixture_scenario(anomaly={
        "type": "quality_degradation", "asset": "ASSET-01", "start": 5,
        "duration": 10,
    })
    telemetry, _, _ = simulate(scenario, 9)
    assert telemetry.filter(pl.col("quality") == "BAD").height > 0


def test_scenario_rejects_anomaly_past_run_end():
    with pytest.raises(ValueError, match="ends after scenario duration"):
        fixture_scenario(anomaly={
            "type": "sensor_bias", "asset": "ASSET-01", "start": 20,
            "duration": 20,
        })


@pytest.mark.parametrize("kind", [
    "sensor_drift", "sudden_spike", "bearing_degradation", "cavitation",
    "cooling_degradation", "mechanical_overload", "sensor_stuck", "sensor_bias",
    "missing_telemetry", "single_signal_loss", "asset_communication_loss",
    "quality_degradation", "regime_mismatch", "multivariate_novelty", "maintenance_activity",
])
def test_all_anomaly_types_emit_independent_ground_truth(kind):
    params = {"loss_pct": 100} if kind == "missing_telemetry" else {}
    anomaly = {"type": kind, "asset": "ASSET-01", "start": 5, "duration": 10, "parameters": params}
    telemetry, truth, _ = simulate(fixture_scenario(anomaly=anomaly), 19)
    assert truth["events"][0]["type"] == kind
    assert truth["events"][0]["affected_signals"]
    assert telemetry.height > 0


def test_air_leak_couples_pressure_loss_and_compensating_current_with_ground_truth():
    anomaly = {
        "type": "air_leak", "asset": "ASSET-01", "start": 5, "duration": 10,
        "severity": 1.0,
        "parameters": {"pressure_loss_fraction": 0.4, "current_gain": 0.5},
    }
    normal = simulate(fixture_scenario("compressor"), 19)[0]
    affected, truth, _ = simulate(fixture_scenario("compressor", anomaly), 19)
    event_start = EPOCH + timedelta(seconds=5)
    event_end = EPOCH + timedelta(seconds=15)

    def values(frame, signal):
        return frame.filter(
            (pl.col("tag_id") == signal)
            & (pl.col("timestamp") >= event_start)
            & (pl.col("timestamp") < event_end)
        ).sort("timestamp").get_column("value")

    normal_pressure, affected_pressure = values(normal, "pressure_bar"), values(affected, "pressure_bar")
    normal_current, affected_current = values(normal, "motor_current_a"), values(affected, "motor_current_a")

    assert affected_pressure.mean() < normal_pressure.mean()
    assert affected_current.mean() > normal_current.mean()
    assert set(truth["events"][0]["affected_signals"]) == {"pressure_bar", "motor_current_a"}
    assert truth["events"][0]["type"] == "air_leak"


def test_air_leak_rejects_incompatible_assets_and_unbounded_effects():
    with pytest.raises(ValueError, match="requires a compressor asset"):
        simulate(fixture_scenario("pump", {
            "type": "air_leak", "asset": "ASSET-01", "start": 5, "duration": 10,
        }), 19)
    with pytest.raises(ValueError, match="must be within 0..1"):
        simulate(fixture_scenario("compressor", {
            "type": "air_leak", "asset": "ASSET-01", "start": 5, "duration": 10,
            "parameters": {"pressure_loss_fraction": 1.1},
        }), 19)


def test_multivariate_novelty_stays_inside_declared_engineering_bounds():
    telemetry, _, _ = simulate(fixture_scenario("cnc", {
        "type": "multivariate_novelty", "asset": "ASSET-01", "start": 5,
        "duration": 10,
    }), 5)
    assert telemetry.filter((pl.col("value") < pl.col("engineering_min")) | (pl.col("value") > pl.col("engineering_max"))).is_empty()


def test_batch_resolves_ranges_and_keeps_partition_seeds_disjoint(tmp_path):
    suite = tmp_path / "communications.yaml"
    suite.write_text("""suite_id: communications-test
partitions:
  train: 0.6
  validation: 0.2
  test: 0.2
scenario:
  scenario_id: comm-test
  duration_s: 20
  sampling_interval_ms: 1000
  assets:
    - asset_id: P-1
      asset_class: pump
  anomalies:
    - type: missing_telemetry
      asset: P-1
      start: {min: 2, max: 5}
      duration: {min: 3, max: 6}
      parameters:
        loss_pct: {min: 5, max: 50}
""", encoding="utf-8")
    out = tmp_path / "dataset"
    batch(suite, 10, out, seed=31)
    manifest = json.loads((out / "dataset_manifest.json").read_text())
    assert manifest["partition_counts"] == {"train": 6, "validation": 2, "test": 2}
    assert len({run["seed"] for run in manifest["runs"]}) == 10
    assert manifest["observation_count"] == sum(run["observation_count"] for run in manifest["runs"])
    assert len({run["telemetry_sha256"] for run in manifest["runs"]}) == 10
    assert all(len(run["ground_truth_sha256"]) == 64 and len(run["metadata_sha256"]) == 64 for run in manifest["runs"])
    assert all((out / run["partition"] / run["run_id"] / "scenario.yaml").exists() for run in manifest["runs"])
    sample = manifest["runs"][0]
    run_dir = out / sample["partition"] / sample["run_id"]
    replay(run_dir, tmp_path / "batch-replay")
    assert pl.read_parquet(run_dir / "telemetry.parquet").equals(pl.read_parquet(tmp_path / "batch-replay" / "telemetry.parquet"))


def test_batch_rejects_persistent_challenge_partition(tmp_path):
    suite = tmp_path / "suite.yaml"
    suite.write_text("""partitions: {train: 0.5, validation: 0.25, test: 0.15, challenge: 0.1}
scenario: {scenario_id: x, assets: [{asset_id: A, asset_class: pump}]}
""", encoding="utf-8")
    output = tmp_path / "out"
    with pytest.raises(ValueError, match="ephemeral challenge"):
        batch(suite, 10, output, seed=1)
    assert not output.exists()


def test_batch_refuses_existing_dataset_output_to_prevent_stale_runs(tmp_path):
    output = tmp_path / "dataset"
    output.mkdir()
    (output / "old-run").mkdir()
    with pytest.raises(FileExistsError, match="must not already exist"):
        batch(Path("suites/training-v0.2.yaml"), 2, output, seed=42)


def test_resumable_batch_recovers_completed_runs_and_matches_clean_generation(tmp_path, monkeypatch):
    from ot_lab import simulation

    suite = tmp_path / "suite.yaml"
    suite.write_text("""suite_id: resume-test
suite_version: 1
partitions: {train: 0.5, validation: 0.25, test: 0.25}
scenario:
  scenario_id: resume-test
  duration_s: 12
  sampling_interval_ms: 1000
  assets: [{asset_id: P-1, asset_class: pump}]
generation:
  vary: {ambient_temperature_c: {min: 18, max: 24}}
""", encoding="utf-8")
    resumable = tmp_path / "resumable"
    original = simulation.write_run
    completed = 0

    def interrupt_after_two(*args, **kwargs):
        nonlocal completed
        completed += 1
        if completed == 3:
            raise RuntimeError("simulated interruption")
        return original(*args, **kwargs)

    monkeypatch.setattr(simulation, "write_run", interrupt_after_two)
    with pytest.raises(RuntimeError, match="simulated interruption"):
        simulation.batch(suite, 8, resumable, seed=912, resume=True)
    checkpoint_dirs = [path for path in resumable.glob("*/train-*") if path.is_dir()]
    assert len(checkpoint_dirs) == 2
    monkeypatch.setattr(simulation, "write_run", original)
    simulation.batch(suite, 8, resumable, seed=912, resume=True, workers=2)
    clean = tmp_path / "clean"
    simulation.batch(suite, 8, clean, seed=912)
    resumed_manifest = json.loads((resumable / "dataset_manifest.json").read_text())
    clean_manifest = json.loads((clean / "dataset_manifest.json").read_text())
    assert resumed_manifest["dataset_id"] == "resumable"
    assert resumed_manifest["generator_argv"][-1] == str(resumable)
    assert [(run["run_id"], run["seed"], run["telemetry_sha256"]) for run in resumed_manifest["runs"]] == [
        (run["run_id"], run["seed"], run["telemetry_sha256"]) for run in clean_manifest["runs"]
    ]
    assert not (resumable / ".resume.json").exists()


def test_parallel_batch_matches_serial_runs_and_manifest(tmp_path):
    from ot_lab.simulation import batch

    suite = tmp_path / "suite.yaml"
    suite.write_text("""suite_id: parallel-test
suite_version: 1
partitions: {train: 0.5, validation: 0.25, test: 0.25}
scenario:
  scenario_id: parallel-test
  duration_s: 12
  sampling_interval_ms: 1000
  assets: [{asset_id: P-1, asset_class: pump}]
generation:
  vary: {ambient_temperature_c: {min: 18, max: 24}}
""", encoding="utf-8")
    serial = tmp_path / "serial"
    parallel = tmp_path / "parallel"
    batch(suite, 8, serial, seed=912)
    batch(suite, 8, parallel, seed=912, workers=2)
    serial_manifest = json.loads((serial / "dataset_manifest.json").read_text())
    parallel_manifest = json.loads((parallel / "dataset_manifest.json").read_text())
    assert [(run["run_id"], run["seed"], run["telemetry_sha256"], run["ground_truth_sha256"])
            for run in serial_manifest["runs"]] == [
        (run["run_id"], run["seed"], run["telemetry_sha256"], run["ground_truth_sha256"])
        for run in parallel_manifest["runs"]
    ]
    for partition in ("train", "validation", "test"):
        assert (serial / f"{partition}.parquet").read_bytes() == (parallel / f"{partition}.parquet").read_bytes()


def test_batch_rejects_nonpositive_workers(tmp_path):
    with pytest.raises(ValueError, match="workers must be positive"):
        batch(Path("suites/training-v0.2.yaml"), 1, tmp_path / "dataset", seed=1, workers=0)


def test_batch_rejects_workers_above_cpu_count(tmp_path, monkeypatch):
    from ot_lab import simulation

    monkeypatch.setattr(simulation.os, "cpu_count", lambda: 2)
    with pytest.raises(ValueError, match="cannot exceed available CPU count"):
        batch(Path("suites/training-v0.2.yaml"), 1, tmp_path / "dataset", seed=1, workers=3)


def test_resumable_batch_rejects_changed_suite_or_seed(tmp_path):
    suite = tmp_path / "suite.yaml"
    suite.write_text("""partitions: {train: 0.5, validation: 0.25, test: 0.25}
scenario: {scenario_id: x, duration_s: 5, sampling_interval_ms: 1000, assets: [{asset_id: A, asset_class: pump}]}
""", encoding="utf-8")
    output = tmp_path / "resume"
    from ot_lab import simulation
    from ot_lab.simulation import batch

    original = simulation.write_run
    def stop_run(*_args, **_kwargs):
        raise RuntimeError("stop with checkpoint")
    simulation.write_run = stop_run
    with pytest.raises(RuntimeError, match="stop with checkpoint"):
        batch(suite, 4, output, seed=7, resume=True)
    simulation.write_run = original
    with pytest.raises(ValueError, match="configuration differs"):
        batch(suite, 4, output, seed=8, resume=True)
    suite.write_text(suite.read_text(encoding="utf-8") + "# edited\n", encoding="utf-8")
    with pytest.raises(ValueError, match="configuration differs"):
        batch(suite, 4, output, seed=7, resume=True)


def test_range_resolution_rejects_invalid_challenge_bounds(tmp_path):
    suite = tmp_path / "suite.yaml"
    suite.write_text("""scenario:
  scenario_id: range-test
  duration_s: 10
  sampling_interval_ms: 1000
  assets: [{asset_id: P-1, asset_class: pump}]
  anomalies:
    - {type: sensor_bias, asset: P-1, start: 2, duration: 3, parameters: {bias: {min: 2, max: 1}}}
""", encoding="utf-8")
    from ot_lab.simulation import generate_challenge

    with pytest.raises(ValueError, match="invalid numeric range"):
        generate_challenge(suite, tmp_path / "challenge", master_seed=11)




@pytest.mark.parametrize("asset_class,kind", [
    ("pump", "cavitation"), ("cnc", "cooling_degradation"),
    ("compressor", "mechanical_overload"), ("conveyor", "mechanical_overload"),
    ("pump", "asset_communication_loss"),
])
def test_process_anomalies_fit_asset_signal_inventory(asset_class, kind):
    telemetry, truth, _ = simulate(fixture_scenario(asset_class, {
        "type": kind, "asset": "ASSET-01", "start": 5, "duration": 10,
    }), 29)
    assert truth["events"][0]["affected_signals"]
    if kind == "asset_communication_loss":
        assert telemetry.filter(pl.col("timestamp") >= pl.datetime(2025, 1, 1, 0, 0, 6, time_zone="UTC")).height < telemetry.height


def test_run_submission_exposes_only_temporary_input(tmp_path):
    run_dir = tmp_path / "run"
    write_run(fixture_scenario(), 2, run_dir)
    out = tmp_path / "predictions.jsonl"
    cmd = "python -c \"import pathlib,os; pathlib.Path(os.environ['OT_LAB_OUTPUT']).write_text('{}\\n')\""
    result = run_submission(cmd, run_dir, out)
    assert result.read_text() == "{}\n"


@pytest.mark.skipif(os.name != "nt", reason="Windows subprocesses require SystemRoot for Winsock")
def test_run_submission_preserves_windows_system_environment(tmp_path):
    run_dir = tmp_path / "run"
    write_run(fixture_scenario(), 3, run_dir)
    script = tmp_path / "winsock_model.py"
    script.write_text('''import socket, sys
from pathlib import Path
socket.getaddrinfo("localhost", 80)
Path(sys.argv[2]).write_text("{}\\n", encoding="utf-8")
''', encoding="utf-8")
    command = f'"{sys.executable}" "{script}" {{input}} {{output}}'
    result = run_submission(command, run_dir, tmp_path / "winsock.jsonl")
    assert result.read_text(encoding="utf-8") == "{}\n"


def test_independent_external_commands_run_and_compare_without_importing_lab(tmp_path, monkeypatch):
    from ot_lab.cli import main

    scenario = fixture_scenario(anomaly={
        "type": "sensor_bias", "asset": "ASSET-01", "start": 10,
        "duration": 5, "parameters": {"signal": "spindle_power_kw", "bias": 1.0},
    })
    run_dir = tmp_path / "run"
    write_run(scenario, 91, run_dir)
    prediction_paths = []
    for name, score in (("quiet-baseline", 0.1), ("always-alert", 0.9)):
        script = tmp_path / f"{name}.py"
        script.write_text(f'''import json, sys
from pathlib import Path
assert Path(sys.argv[1]).read_bytes()[:4] == b"PAR1"
score = {score}
with open(sys.argv[2], "w", encoding="utf-8") as output:
    output.write(json.dumps({{"asset_id": "ASSET-01", "window_start": "{EPOCH.isoformat()}", "window_end": "{(EPOCH + timedelta(seconds=30)).isoformat()}", "irregularity_score": score}}) + "\\n")
''', encoding="utf-8")
        output = tmp_path / f"{name}.jsonl"
        command = f'"{sys.executable}" "{script}" {{input}} {{output}}'
        run_submission(command, run_dir, output)
        prediction_paths.append(output)

    comparison_dir = tmp_path / "comparison"
    monkeypatch.setattr(sys, "argv", [
        "ot-lab", "compare", "--run", str(run_dir), "--predictions",
        *(str(path) for path in prediction_paths), "--output", str(comparison_dir),
        "--alert-merge-gap-seconds", "0.5",
    ])
    main()
    rows = json.loads((comparison_dir / "comparison.json").read_text(encoding="utf-8"))
    assert [row["model"] for row in rows] == ["quiet-baseline", "always-alert"]
    assert all(row["metric_version"] == "2.0.0" for row in rows)
    assert rows[1]["alert_episode_count"] == 1
    assert rows[1]["false_positive_alert_episodes"] == 0
    assert rows[0]["event_detection_rate"] == 0
    assert rows[1]["event_detection_rate"] == 1
    assert rows[1]["window_precision"] == pytest.approx(4 / 30)
    assert all(path.exists() for path in prediction_paths)


def test_run_submission_enforces_prediction_size_limit(tmp_path):
    run_dir = tmp_path / "run"
    write_run(fixture_scenario(), 2, run_dir)
    out = tmp_path / "predictions.jsonl"
    command = "python -c \"import os,pathlib; pathlib.Path(os.environ['OT_LAB_OUTPUT']).write_text('x'*10000)\""
    with pytest.raises(ValueError, match="exceeds 100 bytes"):
        run_submission(command, run_dir, out, max_output_bytes=100)


def test_run_submission_enforces_timeout(tmp_path):
    run_dir = tmp_path / "run"
    write_run(fixture_scenario(), 2, run_dir)
    command = "python -c \"import time; time.sleep(10)\""
    with pytest.raises(TimeoutError, match="timeout of 1 seconds"):
        run_submission(command, run_dir, tmp_path / "predictions.jsonl", timeout_s=1)


def test_bounded_runner_checks_the_actual_writable_output_path(tmp_path, monkeypatch):
    output = tmp_path / "mounted-output.jsonl"
    output.write_bytes(b"x" * 101)

    class RunningProcess:
        def __init__(self, *_args, **_kwargs):
            self.returncode = None
            self.stdout = io.BytesIO()
            self.stderr = io.BytesIO()
            self.killed = False

        def poll(self):
            return self.returncode

        def wait(self):
            return self.returncode

        def kill(self):
            self.killed = True
            self.returncode = -9

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    process = RunningProcess()
    monkeypatch.setattr("ot_lab.submission.subprocess.Popen", lambda *_args, **_kwargs: process)
    with pytest.raises(ValueError, match="exceeds 100 bytes"):
        _run_bounded(["model"], cwd=tmp_path, env={}, timeout_s=10, max_output_bytes=100, monitored_output=output)
    assert process.killed


def test_docker_submission_passes_only_minimal_environment(tmp_path, monkeypatch):
    run_dir = tmp_path / "run"
    write_run(fixture_scenario(), 2, run_dir)
    captured = {}

    class Completed:
        def __init__(self, args, **_kwargs):
            self.returncode = 0
            self.stdout = io.BytesIO()
            self.stderr = io.BytesIO()
            captured["args"] = args
            Path(args[args.index("--cidfile") + 1]).write_text("fake-container-id")
            mount_arg = args[args.index("--mount", args.index("--mount") + 1) + 1]
            Path(mount_arg.split("src=", 1)[1].split(",dst=", 1)[0]).write_text("{}\n")

        def poll(self):
            return self.returncode

        def wait(self):
            return self.returncode

        def kill(self):
            self.returncode = -9

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    monkeypatch.setattr("ot_lab.submission.shutil.which", lambda _: "docker")
    monkeypatch.setattr("ot_lab.submission.subprocess.Popen", Completed)
    removed = []
    def docker_side_effect(args, **kwargs):
        removed.append(args)
        return subprocess.CompletedProcess(args, 0, b"", b"")
    monkeypatch.setattr("ot_lab.submission.subprocess.run", docker_side_effect)
    out = tmp_path / "predictions.jsonl"
    run_docker_submission("sample:latest", run_dir, out)
    command = captured["args"]
    assert "--pull=never" in command
    assert "--cidfile" in command
    assert "--network=none" in command
    assert "--read-only" in command
    assert "--cap-drop=ALL" in command
    assert "--security-opt=no-new-privileges:true" in command
    assert "--env" in command and "OT_LAB_INPUT=/ot-lab/input.parquet" in command
    mounts = [command[i + 1] for i, item in enumerate(command[:-1]) if item == "--mount"]
    assert len(mounts) == 2
    assert all("ground_truth" not in mount and "run_metadata" not in mount and "scenario" not in mount for mount in mounts)
    assert all(",dst=" in mount and "type=bind" in mount for mount in mounts)
    assert any("dst=/ot-lab/input.parquet,readonly" in mount for mount in mounts)
    assert "fsize=67108864:67108864" in command
    assert "--log-driver=none" in command
    assert "OT_LAB_OUTPUT=/ot-lab/output.jsonl" in command
    assert "GH_TOKEN" not in [command[i + 1] for i, item in enumerate(command[:-1]) if item == "--env"]
    assert removed == [["docker", "rm", "--force", "fake-container-id"]]
    assert out.read_text() == "{}\n"


def test_docker_submission_enforces_prediction_size_limit(tmp_path, monkeypatch):
    run_dir = tmp_path / "run"
    write_run(fixture_scenario(), 2, run_dir)

    class Completed:
        returncode = 0
        stdout = io.BytesIO()
        stderr = io.BytesIO()

        def __init__(self, args, **_kwargs):
            Path(args[args.index("--cidfile") + 1]).write_text("fake-container-id")
            mount_arg = args[args.index("--mount", args.index("--mount") + 1) + 1]
            Path(mount_arg.split("src=", 1)[1].split(",dst=", 1)[0]).write_bytes(b"x" * 101)

        def poll(self): return self.returncode
        def wait(self): return self.returncode
        def kill(self): self.returncode = -9
        def __enter__(self): return self
        def __exit__(self, *_args): return False

    monkeypatch.setattr("ot_lab.submission.shutil.which", lambda _: "docker")
    monkeypatch.setattr("ot_lab.submission.subprocess.Popen", Completed)
    def docker_side_effect(args, **kwargs):
        return subprocess.CompletedProcess(args, 0, b"", b"")
    monkeypatch.setattr("ot_lab.submission.subprocess.run", docker_side_effect)
    with pytest.raises(ValueError, match="exceeds 100 bytes"):
        run_docker_submission("sample:latest", run_dir, tmp_path / "predictions.jsonl", max_output_bytes=100)


def test_docker_submission_timeout_force_removes_container(tmp_path, monkeypatch):
    run_dir = tmp_path / "run"
    write_run(fixture_scenario(), 2, run_dir)
    cleanup_commands = []

    class HangingContainer:
        returncode = None
        stdout = io.BytesIO()
        stderr = io.BytesIO()

        def __init__(self, args, **_kwargs):
            Path(args[args.index("--cidfile") + 1]).write_text("timed-out-container")

        def poll(self): return self.returncode
        def wait(self): return self.returncode
        def kill(self): self.returncode = -9
        def __enter__(self): return self
        def __exit__(self, *_args): return False

    monkeypatch.setattr("ot_lab.submission.shutil.which", lambda _: "docker")
    monkeypatch.setattr("ot_lab.submission.subprocess.Popen", HangingContainer)
    monkeypatch.setattr("ot_lab.submission.subprocess.run", lambda args, **kwargs: cleanup_commands.append(args))
    with pytest.raises(TimeoutError, match="timeout of 1 seconds"):
        run_docker_submission("sample:latest", run_dir, tmp_path / "predictions.jsonl", timeout_s=1)
    assert cleanup_commands == [["docker", "rm", "--force", "timed-out-container"]]
