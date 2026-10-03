import json

import polars as pl
import pytest

from ot_lab.models import Scenario
from ot_lab.simulation import simulate, write_run


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
    assert set(["timestamp", "asset_id", "tag_id", "value", "unit", "quality"]).issubset(telemetry.columns)
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
