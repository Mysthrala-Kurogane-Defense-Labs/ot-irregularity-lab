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
    assert result["data_quality"] == {
        "input_rows": 4,
        "usable_rows": 4,
        "rows_dropped_for_null_or_parse_errors": 0,
        "null_or_parse_error_counts_by_required_column": {
            "timestamp": 0, "motor_current_a": 0, "oil_temperature_c": 0,
            "pressure_bar": 0, "compressor_valve": 0, "load_valve": 0,
        },
        "duplicate_timestamp_extra_rows": 0,
        "out_of_order_timestamp_intervals": 0,
        "invalid_value_counts": {
            "negative_motor_current_rows": 0, "negative_pressure_rows": 0,
            "nonbinary_COMP_rows": 0, "nonbinary_load_valve_rows": 0,
        },
    }
    assert result["digital_state_combinations"]["COMP=0,DV=1"]["rows"] == 2
    assert result["digital_state_combinations"]["COMP=0,DV=1"]["motor_current_a_p50"] == 7.5
    report_text = json.dumps(result)
    assert len(report_text) < 4096
    assert "2020-02-01 00:00:10,7,31,9,0,1" not in report_text
    output = write_metropt_analysis(source, tmp_path / "report.json")
    assert json.loads(output.read_text(encoding="utf-8"))["source"]["sha256"] == result["source"]["sha256"]


def test_metropt_analysis_reports_bad_rows_and_digital_values(tmp_path):
    source = tmp_path / "quality.csv"
    source.write_text(
        "timestamp,Motor_current,Oil_temperature,TP3,COMP,DV_eletric\n"
        "2020-02-01 00:00:00,4,30,8,1,0\n"
        "2020-02-01 00:00:10,-1,31,9,0,1\n"
        "2020-02-01 00:00:20,5,31,-2,0.5,1\n"
        "2020-02-01 00:00:30,not-a-number,32,9,0,1\n"
        "2020-02-01 00:00:20,7,32,9,0,1\n",
        encoding="utf-8",
    )
    quality = analyze_metropt(source)["data_quality"]
    assert quality["input_rows"] == 5
    assert quality["usable_rows"] == 4
    assert quality["rows_dropped_for_null_or_parse_errors"] == 1
    assert quality["null_or_parse_error_counts_by_required_column"]["motor_current_a"] == 1
    assert quality["duplicate_timestamp_extra_rows"] == 1
    assert quality["out_of_order_timestamp_intervals"] == 1
    assert quality["invalid_value_counts"] == {
        "negative_motor_current_rows": 1,
        "negative_pressure_rows": 1,
        "nonbinary_COMP_rows": 1,
        "nonbinary_load_valve_rows": 0,
    }


def test_metropt_analysis_rejects_missing_sensor_columns(tmp_path):
    source = tmp_path / "incomplete.csv"
    source.write_text("timestamp,Motor_current\n2020-01-01,1\n", encoding="utf-8")
    with pytest.raises(ValueError, match="missing a required column"):
        analyze_metropt(source)
