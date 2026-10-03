import json
import zipfile

import pytest

from ot_lab.datasets import package_dataset
from ot_lab.simulation import batch


def _source_dataset(tmp_path):
    suite = tmp_path / "suite.yaml"
    suite.write_text("""suite_id: package-test
suite_version: 1.0.0
data_license: CC-BY-4.0
partitions: {train: 0.5, validation: 0.25, test: 0.25}
scenario: {scenario_id: package-test, duration_s: 12, sampling_interval_ms: 1000, assets: [{asset_id: P-1, asset_class: pump}]}
""", encoding="utf-8")
    dataset = tmp_path / "dataset"
    batch(suite, 8, dataset, seed=42)
    license_file = tmp_path / "DATASET_LICENSE.txt"
    license_file.write_text("Creative Commons Attribution 4.0 International\n", encoding="utf-8")
    return dataset, license_file


def test_partition_packages_are_deterministic_and_do_not_include_run_truth_or_seeds(tmp_path):
    dataset, license_file = _source_dataset(tmp_path)
    first = package_dataset(dataset, "0.4.0", tmp_path / "release-a", license_file, "CC-BY-4.0", ["train", "test"])
    second = package_dataset(dataset, "0.4.0", tmp_path / "release-b", license_file, "CC-BY-4.0", ["train", "test"])
    first_manifest = json.loads((first / "release_manifest.json").read_text(encoding="utf-8"))
    second_manifest = json.loads((second / "release_manifest.json").read_text(encoding="utf-8"))
    assert first_manifest == second_manifest
    assert first_manifest["dataset_version"] == "0.4.0"
    assert set(first_manifest["partitions"]) == {"train", "test"}
    assert first_manifest["contains_run_seeds"] is False
    assert first_manifest["contains_ground_truth"] is False
    assert first_manifest["partitions"]["train"]["class_distribution"]["normal"] == 4
    assert first_manifest["partitions"]["train"]["asset_distribution"]["pump"] == 4
    for partition in ("train", "test"):
        package = first_manifest["partitions"][partition]["path"]
        assert (first / package).read_bytes() == (second / package).read_bytes()
        labels_info = first_manifest["partitions"][partition]["labels_artifact"]
        labels_package = labels_info["path"]
        assert (first / labels_package).read_bytes() == (second / labels_package).read_bytes()
        assert labels_info["run_count"] == first_manifest["partitions"][partition]["run_count"]
        with zipfile.ZipFile(first / package) as archive:
            assert archive.namelist() == [f"{partition}.parquet", "DATASET_LICENSE.txt", "release_manifest.json"]
            inner = json.loads(archive.read("release_manifest.json"))
            assert inner["partition"] == partition
            assert inner["contains_run_seeds"] is False
            assert inner["contains_ground_truth"] is False
            assert "master_seed" not in inner
            assert not any("ground_truth" in name or "scenario" in name or "run_metadata" in name for name in archive.namelist())
            assert archive.read("DATASET_LICENSE.txt") == license_file.read_bytes()
        with zipfile.ZipFile(first / labels_package) as archive:
            assert archive.testzip() is None
            names = archive.namelist()
            assert "release_manifest.json" in names
            assert not any("seed" in name or "scenario" in name for name in names)
            label_manifest = json.loads(archive.read("release_manifest.json"))
            assert label_manifest["contains_ground_truth"] is True
            assert label_manifest["contains_run_seeds"] is False
            assert label_manifest["contains_scenarios"] is False
            assert len(label_manifest["runs"]) == labels_info["run_count"]
            assert len([name for name in names if name.startswith("ground_truth/")]) == labels_info["run_count"]
            assert len([name for name in names if name.startswith("evaluation_metadata/")]) == labels_info["run_count"]
            for item in label_manifest["runs"]:
                safe_metadata = json.loads(archive.read(item["evaluation_metadata"]["path"]))
                assert safe_metadata["run_id"] == item["run_id"]
                assert "seed" not in safe_metadata
                assert "scenario_id" not in safe_metadata


def test_partition_package_refuses_corrupted_source_and_existing_output(tmp_path):
    dataset, license_file = _source_dataset(tmp_path)
    original = (dataset / "train.parquet").read_bytes()
    (dataset / "train.parquet").write_bytes(b"corrupt")
    with pytest.raises(ValueError, match="hash mismatch"):
        package_dataset(dataset, "0.4.0", tmp_path / "bad-release", license_file, "CC-BY-4.0", ["train"])
    (dataset / "train.parquet").write_bytes(original)
    existing = tmp_path / "existing"
    existing.mkdir()
    with pytest.raises(FileExistsError, match="must not already exist"):
        package_dataset(dataset, "0.4.0", existing, license_file, "CC-BY-4.0", ["train"])


def test_partition_package_requires_licensed_synthetic_non_customer_manifest(tmp_path):
    dataset, license_file = _source_dataset(tmp_path)
    manifest_path = dataset / "dataset_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["customer_data"] = True
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="synthetic non-customer"):
        package_dataset(dataset, "0.4.0", tmp_path / "release", license_file, "CC-BY-4.0", ["train"])


@pytest.mark.parametrize("partitions", [[], ["challenge"], ["train", "train"]])
def test_partition_package_rejects_invalid_selection(tmp_path, partitions):
    dataset, license_file = _source_dataset(tmp_path)
    with pytest.raises(ValueError, match="partitions must be unique values"):
        package_dataset(dataset, "0.4.0", tmp_path / "invalid", license_file, "CC-BY-4.0", partitions)


def test_partition_package_checks_license_against_suite_declaration(tmp_path):
    dataset, license_file = _source_dataset(tmp_path)
    with pytest.raises(ValueError, match="does not match suite license"):
        package_dataset(dataset, "0.4.0", tmp_path / "wrong-license", license_file, "CC0-1.0", ["train"])


@pytest.mark.parametrize("run_id", ["../outside", "..\\outside", "C:\\outside"])
def test_partition_package_rejects_unsafe_run_ids(tmp_path, run_id):
    dataset, license_file = _source_dataset(tmp_path)
    manifest_path = dataset / "dataset_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["runs"][0]["run_id"] = run_id
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ValueError, match="safe path component"):
        package_dataset(dataset, "0.4.0", tmp_path / "unsafe-run-id", license_file, "CC-BY-4.0", ["train"])


def test_partition_package_rejects_parquet_path_outside_dataset(tmp_path):
    dataset, license_file = _source_dataset(tmp_path)
    manifest_path = dataset / "dataset_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["partition_files"]["train"]["path"] = "../outside.parquet"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ValueError, match="no Parquet artifact"):
        package_dataset(dataset, "0.4.0", tmp_path / "unsafe-parquet-path", license_file, "CC-BY-4.0", ["train"])
