import json
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import polars as pl
import pytest

from ot_lab.evaluation import evaluate
from ot_lab.models import AssetSpec, Scenario
from ot_lab.process import ProcessState, regime_at, simulate_step
from ot_lab.simulation import EPOCH, batch, replay, simulate, write_run
from ot_lab.submission import run_docker_submission, run_submission


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
    baseline = simulate(fixture_scenario(), 17)[0]
    scenario = fixture_scenario(anomaly={
        "type": "missing_telemetry", "asset": "ASSET-01", "start": 5,
        "duration": 15, "parameters": {"loss_pct": loss_pct},
    })
    telemetry, _, _ = simulate(scenario, 17)
    # Compare the same seeded samples with a no-loss baseline.
    def in_event(frame):
        epoch_start = int(EPOCH.timestamp() * 1000)
        return frame.filter(
            (pl.col("timestamp").dt.epoch("ms") >= epoch_start + 6_000) &
            (pl.col("timestamp").dt.epoch("ms") < epoch_start + 20_000)
        ).height

    expected, actual = in_event(baseline), in_event(telemetry)
    observed_loss = (expected - actual) / expected
    assert abs(observed_loss - loss_pct / 100) <= 0.15
    # 100% loss means no rows in the event, lower percentages retain some rows.
    event_rows = telemetry.filter(
        (pl.col("timestamp") >= pl.datetime(2025, 1, 1, 0, 0, 6, time_zone="UTC")) &
        (pl.col("timestamp") < pl.datetime(2025, 1, 1, 0, 0, 20, time_zone="UTC"))
    ).height
    assert (event_rows == 0) if loss_pct == 100 else (event_rows > 0)


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
    with pytest.raises(ValueError, match="ephemeral challenge"):
        batch(suite, 10, tmp_path / "out", seed=1)


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


def test_docker_submission_passes_only_minimal_environment(tmp_path, monkeypatch):
    run_dir = tmp_path / "run"
    write_run(fixture_scenario(), 2, run_dir)
    captured = {}

    class Completed:
        returncode = 0
        stderr = ""

    def fake_run(args, **kwargs):
        captured["args"] = args
        # The test emulates the program writing inside the isolated output mount.
        mount_arg = args[args.index("--mount", args.index("--mount") + 1) + 1]
        host_dir = Path(mount_arg.split("src=", 1)[1].split(",dst=", 1)[0])
        (host_dir / "output.jsonl").write_text("{}\n")
        return Completed()

    monkeypatch.setattr("ot_lab.submission.shutil.which", lambda _: "docker")
    monkeypatch.setattr("ot_lab.submission.subprocess.run", fake_run)
    out = tmp_path / "predictions.jsonl"
    run_docker_submission("sample:latest", run_dir, out)
    command = captured["args"]
    assert "--network=none" in command
    assert "--read-only" in command
    assert "--cap-drop=ALL" in command
    assert "--security-opt=no-new-privileges:true" in command
    assert "--env" in command and "OT_LAB_INPUT=/ot-lab/input.parquet" in command
    mounts = [command[i + 1] for i, item in enumerate(command[:-1]) if item == "--mount"]
    assert len(mounts) == 2
    assert all("ground_truth" not in mount for mount in mounts)
    assert "GH_TOKEN" not in [command[i + 1] for i, item in enumerate(command[:-1]) if item == "--env"]
