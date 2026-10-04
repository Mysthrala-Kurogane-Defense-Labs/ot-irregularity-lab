import json
import zipfile

import pytest

from ot_lab.calibration import (
    analyze_bosch_cnc,
    analyze_metropt,
    analyze_zema_hydraulic,
    write_bosch_cnc_analysis,
    write_metropt_analysis,
    write_zema_hydraulic_analysis,
)


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
    report_text = json.dumps(result)
    assert len(report_text) < 4096
    assert "2020-02-01 00:00:10,7,31,9,0,1" not in report_text
    output = write_metropt_analysis(source, tmp_path / "report.json")
    assert json.loads(output.read_text(encoding="utf-8"))["source"]["sha256"] == result["source"]["sha256"]


def test_metropt_analysis_rejects_missing_sensor_columns(tmp_path):
    source = tmp_path / "incomplete.csv"
    source.write_text("timestamp,Motor_current\n2020-01-01,1\n", encoding="utf-8")
    with pytest.raises(ValueError, match="missing a required column"):
        analyze_metropt(source)


def test_zema_hydraulic_analysis_emits_conditioned_aggregates_only(tmp_path):
    source = tmp_path / "hydraulic.zip"
    profile = "100\t100\t0\t130\t0\n100\t100\t1\t130\t0\n"
    sensors = ["PS1", "PS2", "PS3", "PS4", "PS5", "PS6", "EPS1", "FS1", "FS2", "TS1", "TS2", "TS3", "TS4", "VS1", "CE", "CP", "SE"]
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr("profile.txt", profile)
        for index, sensor in enumerate(sensors):
            archive.writestr(f"{sensor}.txt", f"{index}\t{index + 2}\n{index + 4}\t{index + 6}\n")

    result = analyze_zema_hydraulic(source)
    assert result["source"]["cycles"] == 2
    assert result["source"]["archive_sha256"]
    assert result["nominal_baseline_cycles"] == 1
    leakage = result["conditioned_cycle_mean_summary"]["internal_pump_leakage"]["levels"]
    assert leakage["0"]["cycles"] == leakage["1"]["cycles"] == 1
    assert leakage["1"]["signals"]["FS1"]["cycle_mean"]["p50"] == pytest.approx(12.0)
    assert "motor_current" not in leakage["1"]["signals"]
    report = json.dumps(result)
    assert profile not in report
    assert "Motor current is measured" not in report
    output = write_zema_hydraulic_analysis(source, tmp_path / "aggregate.json")
    assert json.loads(output.read_text(encoding="utf-8"))["source"]["archive_sha256"] == result["source"]["archive_sha256"]


def test_zema_hydraulic_analysis_rejects_missing_sensor_files(tmp_path):
    source = tmp_path / "incomplete.zip"
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr("profile.txt", "100\t100\t0\t130\t0\n")
    with pytest.raises(ValueError, match="missing files"):
        analyze_zema_hydraulic(source)


def test_bosch_cnc_analysis_emits_source_group_aggregates_only(tmp_path):
    h5py = pytest.importorskip("h5py")
    import numpy as np

    source = tmp_path / "M01" / "OP07" / "good" / "M01_Aug_2019_OP07_000.h5"
    source.parent.mkdir(parents=True)
    with h5py.File(source, "w") as archive:
        archive.create_dataset("vibration_data", data=np.array([[3.0, 4.0, 0.0], [3.0, 4.0, 0.0]]))
    repeated = tmp_path / "M01" / "OP07" / "good" / "M01_Aug_2019_OP07_001.h5"
    with h5py.File(repeated, "w") as archive:
        archive.create_dataset("vibration_data", data=np.array([[4.0, 3.0, 0.0], [4.0, 3.0, 0.0]]))
    bad = tmp_path / "M01" / "OP07" / "bad" / "M01_Aug_2019_OP07_000.h5"
    bad.parent.mkdir(parents=True)
    with h5py.File(bad, "w") as archive:
        archive.create_dataset("vibration_data", data=np.array([[0.0, 0.0, 12.0], [0.0, 0.0, 12.0]]))

    report = analyze_bosch_cnc(tmp_path, "test-revision")
    assert report["source"]["input_files"] == 3
    assert report["label_counts"] == {"good": 2, "bad": 1}
    assert report["privacy_suppression"] == {"minimum_segments_per_group": 2, "suppressed_singleton_groups": 1}
    good, = report["segment_aggregates"]
    assert good["source_label"] == "good"
    assert good["vector_rms_p05_p50_p95"]["p50"] == pytest.approx(5.0)
    assert "source samples" in " ".join(report["interpretation"])
    output = write_bosch_cnc_analysis(tmp_path, tmp_path / "report.json", "test-revision")
    assert json.loads(output.read_text(encoding="utf-8"))["source"]["source_revision"] == "test-revision"
    assert b"\r\n" not in output.read_bytes()


def test_bosch_cnc_analysis_rejects_unexpected_hdf5_paths(tmp_path):
    pytest.importorskip("h5py")
    (tmp_path / "other.h5").write_bytes(b"not an HDF5 file")
    with pytest.raises(ValueError, match="unexpected Bosch CNC HDF5 path"):
        analyze_bosch_cnc(tmp_path)
