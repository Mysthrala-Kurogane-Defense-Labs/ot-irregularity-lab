import json

import pytest

from ot_lab.calibration import analyze_metropt, write_metropt_analysis


def test_metropt_analysis_records_aggregates_and_provenance_without_source_rows(tmp_path):
    source = tmp_path / "MetroPT3(AirCompressor).csv"
    source.write_text(
        "timestamp,Motor_current,Oil_temperature,TP3,COMP,DV_eletric\n"
        "2020-02-01 00:00:00,4,30,8,1,0\n"
        "2020-02-01 00:00:10,7,31,9,0,1\n"
        "2020-02-01 00:00:20,7.5,32,9.5,0,1\n"
        "2020-02-01 00:04:00,0,29,8,1,0\n",
        encoding="utf-8",
    )
    result = analyze_metropt(source)
    assert result["source"]["rows_used"] == 4
    assert result["source"]["sha256"]
    assert result["mode_conditioned_signals"]["loaded"]["rows"] == 2
    assert result["mode_conditioned_signals"]["off_or_unloaded"]["rows"] == 2
    assert result["cadence_seconds"]["p50_s"] == 10
    assert len(json.dumps(result)) < source.stat().st_size * 10
    output = write_metropt_analysis(source, tmp_path / "report.json")
    assert json.loads(output.read_text(encoding="utf-8"))["source"]["sha256"] == result["source"]["sha256"]


def test_metropt_analysis_rejects_missing_sensor_columns(tmp_path):
    source = tmp_path / "incomplete.csv"
    source.write_text("timestamp,Motor_current\n2020-01-01,1\n", encoding="utf-8")
    with pytest.raises(ValueError, match="missing a required column"):
        analyze_metropt(source)
