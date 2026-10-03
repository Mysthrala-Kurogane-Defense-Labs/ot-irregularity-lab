import json

import yaml

from ot_lab.simulation import generate_challenge


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
