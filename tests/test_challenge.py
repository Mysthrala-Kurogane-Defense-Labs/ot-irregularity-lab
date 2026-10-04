import json
from pathlib import Path

import numpy as np
import polars as pl
import pytest
import yaml

from ot_lab.evaluation import aggregate_challenge_metrics
from ot_lab.models import Scenario
from ot_lab.simulation import _generate_suite_scenario, generate_challenge


def test_challenge_aggregation_pools_counts_and_macro_averages_per_case_pr_auc():
    base = {
        "metric_version": "2.0.0", "threshold": 0.5, "overlap_threshold": 0.1,
        "alert_merge_gap_seconds": 0.0, "event_type_metrics": {},
    }
    cases = [
        {
            **base, "event_count": 2, "true_positive_events": 1, "missed_events": 1,
            "alert_episode_count": 3, "false_positive_windows": 5, "exposure_asset_hours": 2.5,
            "false_positive_duration_s": 20, "window_true_positives": 5,
            "window_false_positives": 5, "window_false_negatives": 5, "expected_sample_count": 15,
            "mean_event_coverage": 0.5, "mean_time_to_first_detection_s": 4,
            "pr_auc": 0.5,
            "event_type_metrics": {"bearing_degradation": {"event_count": 2, "detection_rate": 0.5, "mean_coverage": 0.5}},
        },
        {
            **base, "event_count": 1, "true_positive_events": 0, "missed_events": 1,
            "alert_episode_count": 2, "false_positive_windows": 3, "exposure_asset_hours": 1.5,
            "false_positive_duration_s": 10, "window_true_positives": 0,
            "window_false_positives": 3, "window_false_negatives": 10, "expected_sample_count": 13,
            "mean_event_coverage": 0.0, "mean_time_to_first_detection_s": None,
            "pr_auc": 0.25,
            "event_type_metrics": {"bearing_degradation": {"event_count": 1, "detection_rate": 0.0, "mean_coverage": 0.0}},
        },
        {
            **base, "event_count": 0, "true_positive_events": 0, "missed_events": 0,
            "alert_episode_count": 1, "false_positive_windows": 2, "exposure_asset_hours": 1.0,
            "false_positive_duration_s": 5, "window_true_positives": 0,
            "window_false_positives": 2, "window_false_negatives": 0, "expected_sample_count": 10,
            "mean_event_coverage": None, "mean_time_to_first_detection_s": None,
            "pr_auc": None,
        },
    ]

    result = aggregate_challenge_metrics(cases)

    assert result["challenge_case_count"] == 3
    assert result["event_count"] == 3
    assert result["true_positive_events"] == 1
    assert result["alert_episode_count"] == 6
    assert result["event_precision"] == pytest.approx(1 / 6)
    assert result["event_recall"] == pytest.approx(1 / 3)
    assert result["event_f1"] == pytest.approx(2 / 9)
    assert result["false_positives_per_asset_hour"] == pytest.approx(10 / 5)
    assert result["mean_event_coverage"] == pytest.approx(1 / 3)
    assert result["mean_time_to_first_detection_s"] == 4
    assert result["pr_auc"] == pytest.approx(0.375)
    assert result["pr_auc_case_count"] == 2
    assert result["event_type_metrics"]["bearing_degradation"]["event_count"] == 3
    assert "events" not in result and "run_id" not in result


def test_challenge_aggregation_rejects_mixed_metric_contracts():
    base = {
        "metric_version": "2.0.0", "threshold": 0.5, "overlap_threshold": 0.1,
        "alert_merge_gap_seconds": 0.0,
    }
    with pytest.raises(ValueError, match="identical metric versions and thresholds"):
        aggregate_challenge_metrics([base, {**base, "threshold": 0.6}])


def test_challenge_cli_runs_separate_cases_and_only_persists_aggregate(tmp_path, monkeypatch, capsys):
    import sys

    from ot_lab import cli

    observed_runs = []

    def fake_generate(_suite, root, challenge_suite_path=None):
        case = root / "run"
        case.mkdir(parents=True)
        (case / "telemetry.parquet").write_bytes(b"synthetic telemetry")
        truth = case / "ground_truth.json"
        truth.write_text('{"seed":"must-not-escape"}', encoding="utf-8")
        return case, truth

    def fake_container(_image, run_dir, output, *_args):
        assert (run_dir / "telemetry.parquet").is_file()
        output.write_text('{"prediction":true}', encoding="utf-8")
        observed_runs.append((run_dir, output))
        return output

    def fake_evaluate(_truth, _predictions, _output, threshold, overlap, *_args):
        return {
            "metric_version": "2.0.0", "threshold": threshold, "overlap_threshold": overlap,
            "alert_merge_gap_seconds": 0.0, "event_count": 1, "true_positive_events": 1,
            "missed_events": 0, "alert_episode_count": 1, "false_positive_windows": 0,
            "exposure_asset_hours": 1.0, "false_positive_duration_s": 0.0,
            "window_true_positives": 5, "window_false_positives": 0,
            "window_false_negatives": 0, "expected_sample_count": 5,
            "mean_event_coverage": 1.0, "mean_time_to_first_detection_s": 0.0,
            "pr_auc": 1.0, "event_type_metrics": {}, "run_id": "challenge-hidden",
            "events": [{"event_id": "secret-event"}],
        }

    monkeypatch.setattr(cli, "generate_challenge", fake_generate)
    monkeypatch.setattr(cli, "run_docker_submission", fake_container)
    monkeypatch.setattr(cli, "evaluate", fake_evaluate)
    output = tmp_path / "challenge-result"
    monkeypatch.setattr(sys, "argv", [
        "ot-lab", "challenge", "--suite", "suite.yaml", "--challenge-suite", "hidden.yaml",
        "--image", "model:local", "--cases", "3", "--output", str(output),
    ])

    cli.main()

    metrics = json.loads((output / "metrics.json").read_text(encoding="utf-8"))
    report = (output / "report.html").read_text(encoding="utf-8")
    assert len(observed_runs) == 3
    assert len({run for run, _ in observed_runs}) == 3
    assert metrics["challenge_case_count"] == 3
    assert metrics["true_positive_events"] == 3
    assert "challenge-hidden" not in json.dumps(metrics)
    assert "secret-event" not in json.dumps(metrics) + report
    assert "must-not-escape" not in json.dumps(metrics) + report
    assert sorted(path.name for path in output.iterdir()) == ["metrics.json", "report.html"]
    assert json.loads(capsys.readouterr().out)["challenge_case_count"] == 3


def test_challenge_uses_hidden_seed_and_does_not_persist_replay_seed(tmp_path):
    suite = tmp_path / "suite.yaml"
    suite.write_text(yaml.safe_dump({
        "scenario": {
            "scenario_id": "challenge-test", "duration_s": 10,
            "sampling_interval_ms": 1000,
            "assets": [{"asset_id": "P-1", "asset_class": "pump"}],
            "anomalies": [{"type": "sensor_bias", "asset": "P-1", "start": 2,
                           "duration": 4, "severity": {"min": 0.2, "max": 0.8},
                           "parameters": {"bias": {"min": 0.1, "max": 1.0}}}],
        }
    }))
    case, truth_path = generate_challenge(suite, tmp_path / "challenge", master_seed=123)
    metadata = json.loads((case / "run_metadata.json").read_text())
    truth = json.loads(truth_path.read_text())
    assert "seed" not in metadata
    assert not (case / "scenario.yaml").exists()
    assert "parameters" not in truth["events"][0]
    assert "seed" not in json.dumps(truth)


def test_difficulty_profiles_resolve_to_numeric_parameters():
    from ot_lab.simulation import resolve_profiles

    resolved = resolve_profiles({"anomalies": [{
        "type": "bearing_degradation", "difficulty": "hard",
        "parameters": {"vibration_gain": 1.0, "temperature_gain": 0.4},
    }]})["anomalies"][0]
    assert resolved["parameters"]["vibration_gain"] == 0.1
    assert resolved["parameters"]["temperature_gain"] == 0.04000000000000001
    assert resolved["resolved_difficulty"] == {"profile": "hard", "gain_scale": 0.1}


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
    with pytest.raises(ValueError, match="invalid numeric range"):
        generate_challenge(suite, tmp_path / "challenge", master_seed=11)


def test_challenge_samples_hidden_full_cases_from_generation_distribution(tmp_path):
    source = Path("suites/training-v0.2.yaml")
    suite = yaml.safe_load(source.read_text(encoding="utf-8"))
    suite["generation"]["vary"]["duration_s"] = {"min": 60, "max": 90}
    suite_path = tmp_path / "randomized-challenge.yaml"
    suite_path.write_text(yaml.safe_dump(suite, sort_keys=False), encoding="utf-8")
    case_dir, truth_path = generate_challenge(suite_path, tmp_path / "challenge", master_seed=903)
    metadata = json.loads((case_dir / "run_metadata.json").read_text(encoding="utf-8"))
    truth = json.loads(truth_path.read_text(encoding="utf-8"))
    assert 60 <= metadata["duration_s"] <= 90
    assert "seed" not in metadata and "scenario_sha256" not in metadata
    assert not (case_dir / "scenario.yaml").exists()
    assert all("parameters" not in event for event in truth["events"])
    assert truth["operating_regimes"]
    assert "scenario_id" not in json.dumps(truth)
    assert truth["run_id"] == metadata["run_id"] == "challenge-hidden"
    assert truth["events"]
    assert pl.read_parquet(case_dir / "telemetry.parquet").get_column("run_id").unique().to_list() == ["challenge-hidden"]


def test_randomized_challenge_sampling_covers_multiple_assets_and_event_families():
    suite = yaml.safe_load(Path("suites/training-v0.2.yaml").read_text(encoding="utf-8"))
    cases = [
        _generate_suite_scenario(
            suite["scenario"], suite["generation"], np.random.default_rng(seed), f"case-{seed}"
        )
        for seed in range(300)
    ]
    validated = [Scenario.model_validate(case) for case in cases]
    assert len({asset.asset_class for scenario in validated for asset in scenario.assets}) == 4
    assert len({event.type for scenario in validated for event in scenario.anomalies}) >= 12
    assert any(len(scenario.assets) > 1 for scenario in validated)


def test_repeated_challenges_vary_without_persisting_resolved_case_details(tmp_path):
    suite = yaml.safe_load(Path("suites/training-v0.2.yaml").read_text(encoding="utf-8"))
    suite_path = tmp_path / "suite.yaml"
    suite_path.write_text(yaml.safe_dump(suite, sort_keys=False), encoding="utf-8")
    public_cases = []
    for master_seed in range(20):
        case_dir, truth_path = generate_challenge(
            suite_path, tmp_path / f"challenge-{master_seed}", master_seed=master_seed
        )
        metadata = json.loads((case_dir / "run_metadata.json").read_text(encoding="utf-8"))
        truth = json.loads(truth_path.read_text(encoding="utf-8"))
        telemetry = pl.read_parquet(case_dir / "telemetry.parquet")
        assert metadata["run_id"] == truth["run_id"] == "challenge-hidden"
        assert "seed" not in metadata and "scenario_sha256" not in metadata
        assert "scenario_id" not in metadata and "scenario_version" not in metadata
        assert not (case_dir / "scenario.yaml").exists()
        assert all("parameters" not in event for event in truth["events"])
        assert all("observed_start" not in event and "observed_end" not in event for event in truth["events"])
        assert "scenario_id" not in json.dumps(metadata) + json.dumps(truth)
        assert "seed" not in json.dumps(metadata) + json.dumps(truth)
        assert telemetry.get_column("run_id").unique().to_list() == ["challenge-hidden"]
        public_cases.append((metadata["duration_s"], tuple(sorted(telemetry.get_column("asset_id").unique().to_list()))))

    # Runtime samples should explore more than one public-profile outcome across fresh seeds.
    assert len(set(public_cases)) > 1


def test_challenge_can_use_an_independent_hidden_distribution(tmp_path):
    public_suite = Path("suites/training-v0.2.yaml")
    hidden_suite = Path("suites/challenge-v0.1.yaml")
    case_dir, truth_path = generate_challenge(
        public_suite, tmp_path / "independent-challenge", master_seed=71, challenge_suite_path=hidden_suite
    )
    metadata = json.loads((case_dir / "run_metadata.json").read_text(encoding="utf-8"))
    truth = json.loads(truth_path.read_text(encoding="utf-8"))
    telemetry = pl.read_parquet(case_dir / "telemetry.parquet")
    assert metadata["duration_s"] in range(300, 901)
    assert metadata["sampling_interval_ms"] in {500, 1000, 2000}
    assert metadata["run_id"] == "challenge-hidden"
    assert truth["events"]
    assert all("observed_start" not in event and "observed_end" not in event for event in truth["events"])
    assert "hidden-ot-challenge" not in json.dumps(metadata) + json.dumps(truth)
    assert telemetry.get_column("asset_id").unique().to_list()


def test_normal_operation_suite_generates_only_normal_regime_ground_truth(tmp_path):
    suite_path = Path("suites/normal-operation-v0.1.yaml")
    from ot_lab.simulation import batch

    batch(suite_path, 30, tmp_path / "normal", seed=12)
    manifest = json.loads((tmp_path / "normal" / "dataset_manifest.json").read_text(encoding="utf-8"))
    assert manifest["class_distribution"] == {"normal": 30, "anomalous": 0}
    for item in manifest["runs"]:
        truth = json.loads((tmp_path / "normal" / item["partition"] / item["run_id"] / "ground_truth.json").read_text(encoding="utf-8"))
        assert not truth["events"]
        assert truth["operating_regimes"]
