import json

import polars as pl
import pytest

from ot_lab.evaluation import evaluate
from ot_lab.models import AssetSpec, Scenario
from ot_lab.process import ProcessState, simulate_step
from ot_lab.simulation import simulate, write_run
from ot_lab.submission import run_submission


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
    start, end = truth["events"][0]["start"], truth["events"][0]["end"]
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
    assert result["true_positive_windows"] == 1
    assert result["window_pr_auc"] == 1
    assert (tmp_path / "report" / "metrics.json").exists()
    assert (tmp_path / "report" / "report.html").exists()


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


def test_pump_load_couples_current_and_flow():
    asset = AssetSpec(asset_id="P-1", asset_class="pump")
    low = ProcessState(temperature=22)
    high = ProcessState(temperature=22)
    low_row = simulate_step(asset, low, "LOW_LOAD", 1, 22, __import__("numpy").random.default_rng(3))
    high_row = simulate_step(asset, high, "HIGH_LOAD", 1, 22, __import__("numpy").random.default_rng(3))
    assert high_row["motor_current_a"] > low_row["motor_current_a"]
    assert high_row["flow_l_min"] > low_row["flow_l_min"]


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


def test_run_submission_exposes_only_temporary_input(tmp_path):
    run_dir = tmp_path / "run"
    write_run(fixture_scenario(), 2, run_dir)
    out = tmp_path / "predictions.jsonl"
    cmd = "python -c \"import pathlib,os; pathlib.Path(os.environ['OT_LAB_OUTPUT']).write_text('{}\\n')\""
    result = run_submission(cmd, run_dir, out)
    assert result.read_text() == "{}\n"
