import json
from pathlib import Path

import numpy as np
import polars as pl
import pytest
import yaml

from ot_lab.models import Scenario
from ot_lab.simulation import _generate_suite_scenario, generate_challenge


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
