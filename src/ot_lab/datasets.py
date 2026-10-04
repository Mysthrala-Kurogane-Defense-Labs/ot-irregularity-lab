"""Deterministic, independently publishable dataset partition artifacts."""

from __future__ import annotations

import hashlib
import json
import re
import tempfile
import zipfile
from pathlib import Path
from typing import Any

PARTITIONS = ("train", "validation", "test")
_RUN_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")


def _contained_file(root: Path, *parts: str) -> Path:
    resolved_root = root.resolve()
    candidate = resolved_root.joinpath(*parts).resolve()
    if not candidate.is_relative_to(resolved_root):
        raise ValueError("dataset manifest path escapes the dataset directory")
    if not candidate.is_file():
        raise FileNotFoundError(candidate)
    return candidate


def _validate_run_id(run_id: Any) -> str:
    if not isinstance(run_id, str) or not _RUN_ID.fullmatch(run_id):
        raise ValueError("dataset manifest run_id must be a safe path component")
    return run_id


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _zip_bytes(archive: zipfile.ZipFile, name: str, content: bytes) -> None:
    entry = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    entry.compress_type = zipfile.ZIP_DEFLATED
    entry.external_attr = 0o100644 << 16
    entry.create_system = 3
    archive.writestr(entry, content, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)


def _zip_file(archive: zipfile.ZipFile, name: str, source: Path) -> None:
    entry = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    entry.compress_type = zipfile.ZIP_DEFLATED
    entry.external_attr = 0o100644 << 16
    entry.create_system = 3
    entry.file_size = source.stat().st_size
    with archive.open(entry, "w", force_zip64=True) as target, source.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            target.write(block)


def package_dataset(
    dataset: Path,
    dataset_version: str,
    output: Path,
    license_file: Path,
    data_license: str,
    partitions: list[str] | None = None,
) -> Path:
    """Build deterministic per-partition ZIPs with seed-free release manifests."""
    if not dataset_version.strip():
        raise ValueError("dataset_version must not be empty")
    if not data_license.strip():
        raise ValueError("data_license must not be empty")
    selected = list(PARTITIONS) if partitions is None else partitions
    if not selected or len(selected) != len(set(selected)) or any(item not in PARTITIONS for item in selected):
        raise ValueError(f"partitions must be unique values from {', '.join(PARTITIONS)}")
    if not dataset.is_dir():
        raise FileNotFoundError(dataset)
    if output.exists():
        raise FileExistsError(f"release output path must not already exist: {output}")
    if not license_file.is_file():
        raise FileNotFoundError(license_file)
    manifest_path = dataset / "dataset_manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(manifest_path)
    source_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if (
        source_manifest.get("generation_complete") is not True
        or source_manifest.get("synthetic") is not True
        or source_manifest.get("generated") is not True
        or source_manifest.get("customer_data") is not False
    ):
        raise ValueError("only completed synthetic non-customer datasets can be packaged")
    declared_license = source_manifest.get("data_license")
    if declared_license and declared_license != data_license:
        raise ValueError(f"selected data license {data_license!r} does not match suite license {declared_license!r}")
    if any(name not in PARTITIONS for name in source_manifest.get("partition_files", {})):
        raise ValueError("dataset manifest contains a non-public partition")
    license_text = license_file.read_text(encoding="utf-8").strip()
    if not license_text:
        raise ValueError("license file must not be empty")
    source_hash = _sha256(manifest_path)
    license_bytes = license_file.read_bytes()
    artifacts: dict[str, dict[str, Any]] = {}
    asset_distribution_by_partition: dict[str, dict[str, int]] = {name: {} for name in PARTITIONS}
    process_profile_distribution_by_partition: dict[str, dict[str, int]] = {name: {} for name in PARTITIONS}
    for run in source_manifest.get("runs", []):
        partition_name = run.get("partition")
        if partition_name in asset_distribution_by_partition:
            distribution = asset_distribution_by_partition[partition_name]
            for asset_class in run.get("asset_classes", []):
                distribution[asset_class] = distribution.get(asset_class, 0) + 1
            process_distribution = process_profile_distribution_by_partition[partition_name]
            for profile in run.get("process_profiles", []):
                key = f"{profile['asset_class']}:{profile['profile']}@{profile['version']}"
                process_distribution[key] = process_distribution.get(key, 0) + 1
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f".{output.name}.package-", dir=output.parent) as temporary:
        stage = Path(temporary)
        for partition in selected:
            details = source_manifest.get("partition_files", {}).get(partition, {})
            source_name = details.get("path")
            if source_name != f"{partition}.parquet":
                raise ValueError(f"dataset has no Parquet artifact for partition {partition}")
            source = _contained_file(dataset, source_name)
            if _sha256(source) != details.get("sha256"):
                raise ValueError(f"partition artifact hash mismatch: {source}")
            content_hash = _sha256(source)
            partition_runs = [run for run in source_manifest.get("runs", []) if run.get("partition") == partition]
            partition_meta = {
                "dataset_id": source_manifest["dataset_id"],
                "dataset_version": dataset_version,
                "source_dataset_manifest_sha256": source_hash,
                "simulator_version": source_manifest["simulator_version"],
                "schema_version": source_manifest["schema_version"],
                "suite_id": source_manifest["suite_id"],
                "suite_version": source_manifest["suite_version"],
                "data_license": data_license,
                "partition": partition,
                "run_count": source_manifest.get("partition_counts", {}).get(partition, 0),
                "observation_count": details.get("observation_count", 0),
                "class_distribution": source_manifest.get("class_distribution_by_partition", {}).get(partition, {}),
                "event_distribution": source_manifest.get("event_distribution_by_partition", {}).get(partition, {}),
                "asset_distribution": asset_distribution_by_partition.get(partition, {}),
                "process_profile_distribution": process_profile_distribution_by_partition.get(partition, {}),
                "artifact": {"path": f"{partition}.parquet", "sha256": content_hash, "bytes": source.stat().st_size},
                "labels_artifact": {"path": f"{partition}-labels.zip"},
                "contains_ground_truth": False,
                "contains_run_seeds": False,
                "synthetic": True,
                "generated": True,
                "customer_data": False,
            }
            archive_path = stage / f"{partition}.zip"
            with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
                _zip_file(archive, f"{partition}.parquet", source)
                _zip_bytes(archive, "DATASET_LICENSE.txt", license_bytes)
                _zip_bytes(archive, "release_manifest.json", (json.dumps(partition_meta, indent=2, sort_keys=True) + "\n").encode())
            label_manifest_runs: list[dict[str, Any]] = []
            labels_path = stage / f"{partition}-labels.zip"
            with zipfile.ZipFile(labels_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
                _zip_bytes(archive, "DATASET_LICENSE.txt", license_bytes)
                for run in partition_runs:
                    run_id = _validate_run_id(run.get("run_id"))
                    truth_path = _contained_file(dataset, partition, run_id, "ground_truth.json")
                    metadata_path = _contained_file(dataset, partition, run_id, "run_metadata.json")
                    if _sha256(truth_path) != run.get("ground_truth_sha256") or _sha256(metadata_path) != run.get("metadata_sha256"):
                        raise ValueError(f"ground-truth or metadata hash mismatch for run {run_id}")
                    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
                    if metadata.get("run_id") != run_id:
                        raise ValueError(f"run metadata id mismatch for {run_id}")
                    safe_metadata = {
                        key: metadata[key]
                        for key in (
                            "run_id", "started_at", "duration_s", "sampling_interval_ms",
                            "observation_count", "asset_count", "asset_ids", "synthetic",
                            "generated", "customer_data",
                        )
                    }
                    ground_truth_name = f"ground_truth/{run_id}.json"
                    evaluation_metadata_name = f"evaluation_metadata/{run_id}.json"
                    _zip_file(archive, ground_truth_name, truth_path)
                    _zip_bytes(archive, evaluation_metadata_name, (json.dumps(safe_metadata, indent=2, sort_keys=True) + "\n").encode())
                    label_manifest_runs.append({
                        "run_id": run_id,
                        "ground_truth": {"path": ground_truth_name, "sha256": _sha256(truth_path)},
                        "evaluation_metadata": {
                            "path": evaluation_metadata_name,
                            "sha256": hashlib.sha256((json.dumps(safe_metadata, indent=2, sort_keys=True) + "\n").encode()).hexdigest(),
                        },
                    })
                label_meta = {
                    "dataset_id": source_manifest["dataset_id"],
                    "dataset_version": dataset_version,
                    "source_dataset_manifest_sha256": source_hash,
                    "partition": partition,
                    "data_license": data_license,
                    "ground_truth_schema_version": source_manifest["ground_truth_schema_version"],
                    "runs": label_manifest_runs,
                    "contains_run_seeds": False,
                    "contains_scenarios": False,
                    "contains_ground_truth": True,
                }
                _zip_bytes(archive, "release_manifest.json", (json.dumps(label_meta, indent=2, sort_keys=True) + "\n").encode())
            artifacts[partition] = {
                "path": archive_path.name,
                "sha256": _sha256(archive_path),
                "bytes": archive_path.stat().st_size,
                "labels_artifact": {
                    "path": labels_path.name,
                    "sha256": _sha256(labels_path),
                    "bytes": labels_path.stat().st_size,
                    "run_count": len(label_manifest_runs),
                },
                "observation_count": details.get("observation_count", 0),
                "run_count": source_manifest.get("partition_counts", {}).get(partition, 0),
                "class_distribution": source_manifest.get("class_distribution_by_partition", {}).get(partition, {}),
                "event_distribution": source_manifest.get("event_distribution_by_partition", {}).get(partition, {}),
                "asset_distribution": asset_distribution_by_partition.get(partition, {}),
                "process_profile_distribution": process_profile_distribution_by_partition.get(partition, {}),
            }
        release_manifest = {
            "release_manifest_version": "1.0.0",
            "dataset_id": source_manifest["dataset_id"],
            "dataset_version": dataset_version,
            "source_dataset_manifest_sha256": source_hash,
            "simulator_version": source_manifest["simulator_version"],
            "schema_version": source_manifest["schema_version"],
            "suite_id": source_manifest["suite_id"],
            "suite_version": source_manifest["suite_version"],
            "data_license": data_license,
            "license_file": "DATASET_LICENSE.txt",
            "partitions": artifacts,
            "synthetic": True,
            "generated": True,
            "customer_data": False,
            "contains_run_seeds": False,
            "contains_ground_truth": False,
        }
        (stage / "release_manifest.json").write_text(json.dumps(release_manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        (stage / "DATASET_LICENSE.txt").write_bytes(license_bytes)
        checksums = [
            f"{_sha256(path)}  {path.name}"
            for path in sorted(stage.iterdir(), key=lambda item: item.name)
            if path.is_file()
        ]
        (stage / "SHA256SUMS.txt").write_text("\n".join(checksums) + "\n", encoding="utf-8")
        stage.replace(output)
    return output
