"""Reproducible, data-minimal analyses of openly licensed process datasets."""

from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def analyze_metropt(path: Path) -> dict[str, Any]:
    """Summarize mode-conditioned compressor channels without retaining source rows.

    The source CSV is read locally and never copied to the output. Results are
    descriptive calibration evidence for one railway APU, not generic priors.
    """
    if not path.is_file():
        raise FileNotFoundError(path)
    schema = pl.read_csv(path, n_rows=0).columns
    aliases = {
        "timestamp": ("timestamp",),
        "motor_current_a": ("Motor_current",),
        "oil_temperature_c": ("Oil_temperature",),
        "pressure_bar": ("TP3",),
        "compressor_valve": ("COMP",),
        "load_valve": ("DV_eletric", "DV_electric"),
    }
    selected: dict[str, str] = {}
    for canonical, options in aliases.items():
        actual = next((name for name in options if name in schema), None)
        if actual is None:
            raise ValueError(f"MetroPT input is missing a required column for {canonical}: expected {options}")
        selected[canonical] = actual
    frame = pl.read_csv(path, columns=list(dict.fromkeys(selected.values())), infer_schema_length=1000)
    rename = {actual: canonical for canonical, actual in selected.items() if actual != canonical}
    frame = frame.rename(rename).with_columns(
        pl.col("timestamp").cast(pl.String).str.to_datetime(strict=False, exact=False),
        *[pl.col(name).cast(pl.Float64, strict=False) for name in aliases if name != "timestamp"],
    ).drop_nulls(["timestamp", "motor_current_a", "oil_temperature_c", "pressure_bar", "compressor_valve", "load_valve"])
    if frame.is_empty():
        raise ValueError("MetroPT input has no usable rows after timestamp and sensor validation")
    frame = frame.sort("timestamp").with_columns(
        pl.col("timestamp").diff().dt.total_microseconds().truediv(1_000_000).alias("cadence_s")
    )
    frame = frame.with_columns(
        pl.when(pl.col("load_valve") > 0.5).then(pl.lit("loaded"))
        .when((pl.col("compressor_valve") > 0.5) & (pl.col("load_valve") <= 0.5)).then(pl.lit("off_or_unloaded"))
        .otherwise(pl.lit("other_or_transition")).alias("observed_mode")
    )
    mode_stats: dict[str, Any] = {}
    for mode in ("loaded", "off_or_unloaded", "other_or_transition"):
        group = frame.filter(pl.col("observed_mode") == mode)
        if group.is_empty():
            continue
        values = group.select(
            pl.len().alias("rows"),
            *[
                pl.col(signal).quantile(q, interpolation="linear").alias(f"{signal}_p{int(q * 100):02d}")
                for signal in ("motor_current_a", "oil_temperature_c", "pressure_bar")
                for q in (0.05, 0.50, 0.95)
            ],
            pl.corr("motor_current_a", "pressure_bar").alias("current_pressure_pearson_r"),
        ).row(0, named=True)
        mode_stats[mode] = {key: (round(value, 6) if isinstance(value, float) else value) for key, value in values.items()}
    cadence = frame.filter(pl.col("cadence_s") > 0).select(
        pl.len().alias("positive_intervals"),
        pl.col("cadence_s").quantile(0.05).alias("p05_s"),
        pl.col("cadence_s").quantile(0.50).alias("p50_s"),
        pl.col("cadence_s").quantile(0.95).alias("p95_s"),
        (pl.col("cadence_s") > 120).mean().alias("fraction_over_120s"),
    ).row(0, named=True)
    result = {
        "analysis_version": "1.0.0",
        "source": {
            "dataset": "MetroPT-3",
            "publisher": "UCI Machine Learning Repository",
            "doi": "10.24432/C5VW3R",
            "license": "CC BY 4.0",
            "sha256": _sha256(path),
            "bytes": path.stat().st_size,
            "input_filename": path.name,
            "rows_used": frame.height,
            "time_start": frame.item(0, "timestamp").isoformat(),
            "time_end": frame.item(frame.height - 1, "timestamp").isoformat(),
        },
        "mode_definition": {
            "loaded": f"{selected['load_valve']} > 0.5",
            "off_or_unloaded": f"{selected['compressor_valve']} > 0.5 and {selected['load_valve']} <= 0.5; these states are intentionally not separated",
            "other_or_transition": "remaining digital-state combinations",
        },
        "cadence_seconds": {key: round(value, 6) if isinstance(value, float) else value for key, value in cadence.items()},
        "mode_conditioned_signals": mode_stats,
        "interpretation": [
            "Descriptive statistics characterize one railway air-production unit; they are not universal compressor ranges or failure priors.",
            "The off_or_unloaded bucket combines states the available binary channels do not safely distinguish.",
            "No source observations or derived time-series rows are emitted; this report contains aggregate statistics and provenance only.",
            "These cross-sectional summaries do not estimate thermal time constants, control-loop dynamics, or causal effects.",
        ],
    }
    return result


def write_metropt_analysis(input_path: Path, output_path: Path) -> Path:
    report = analyze_metropt(input_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return output_path


_HYDRAULIC_SENSORS = {
    "PS1": ("pressure", "bar", 100), "PS2": ("pressure", "bar", 100),
    "PS3": ("pressure", "bar", 100), "PS4": ("pressure", "bar", 100),
    "PS5": ("pressure", "bar", 100), "PS6": ("pressure", "bar", 100),
    "EPS1": ("motor_power", "W", 100),
    "FS1": ("volume_flow", "l/min", 10), "FS2": ("volume_flow", "l/min", 10),
    "TS1": ("temperature", "C", 1), "TS2": ("temperature", "C", 1),
    "TS3": ("temperature", "C", 1), "TS4": ("temperature", "C", 1),
    "VS1": ("vibration", "mm/s", 1), "CE": ("cooling_efficiency", "%", 1),
    "CP": ("cooling_power", "kW", 1), "SE": ("efficiency_factor", "%", 1),
}
_HYDRAULIC_COMPONENTS = {
    "cooler": {"column": 0, "levels": [100, 20, 3], "nominal_others": {1: 100, 2: 0, 3: 130, 4: 0}, "signals": ["TS1", "TS2", "TS3", "TS4", "CE", "CP", "EPS1", "FS1", "FS2"]},
    "valve": {"column": 1, "levels": [100, 90, 80, 73], "nominal_others": {0: 100, 2: 0, 3: 130, 4: 0}, "signals": ["FS1", "FS2", "PS1", "PS2", "PS3", "PS4", "PS5", "PS6", "EPS1"]},
    "internal_pump_leakage": {"column": 2, "levels": [0, 1, 2], "nominal_others": {0: 100, 1: 100, 3: 130, 4: 0}, "signals": ["FS1", "FS2", "PS1", "PS2", "PS3", "PS4", "PS5", "PS6", "EPS1", "VS1", "TS1", "TS2", "TS3", "TS4"]},
    "accumulator": {"column": 3, "levels": [130, 115, 100, 90], "nominal_others": {0: 100, 1: 100, 2: 0, 4: 0}, "signals": ["FS1", "FS2", "PS1", "PS2", "PS3", "PS4", "PS5", "PS6", "EPS1"]},
}


def _quantiles(values: np.ndarray) -> dict[str, float]:
    return {f"p{quantile:02d}": round(float(np.percentile(values, quantile)), 6) for quantile in (5, 50, 95)}


def analyze_zema_hydraulic(path: Path) -> dict[str, Any]:
    """Aggregate condition-conditioned cycle summaries from the official UCI ZIP.

    The output retains source provenance and aggregate measurements only. It is
    evidence for one hydraulic test rig, not a general pump model or failure prior.
    """
    if not path.is_file():
        raise FileNotFoundError(path)
    digest = _sha256(path)
    try:
        with zipfile.ZipFile(path) as archive:
            by_basename: dict[str, str] = {}
            for name in archive.namelist():
                basename = Path(name).name
                if basename in {"profile.txt", "description.txt"} | {f"{sensor}.txt" for sensor in _HYDRAULIC_SENSORS}:
                    if basename in by_basename:
                        raise ValueError(f"hydraulic archive contains duplicate file name: {basename}")
                    by_basename[basename] = name
            required = {"profile.txt", *(f"{sensor}.txt" for sensor in _HYDRAULIC_SENSORS)}
            missing = required - set(by_basename)
            if missing:
                raise ValueError(f"hydraulic archive is missing files: {', '.join(sorted(missing))}")
            with archive.open(by_basename["profile.txt"]) as stream:
                profile = np.loadtxt(stream, delimiter="\t", ndmin=2)
            if profile.ndim != 2 or profile.shape[1] != 5 or profile.shape[0] == 0:
                raise ValueError("hydraulic profile.txt must contain five label columns and at least one cycle")
            if not np.isfinite(profile).all():
                raise ValueError("hydraulic profile labels must be finite")

            summaries: dict[str, dict[str, np.ndarray]] = {}
            for sensor in _HYDRAULIC_SENSORS:
                with archive.open(by_basename[f"{sensor}.txt"]) as stream:
                    matrix = np.loadtxt(stream, delimiter="\t", ndmin=2)
                if matrix.ndim != 2 or matrix.shape[0] != profile.shape[0] or matrix.shape[1] == 0:
                    raise ValueError(f"{sensor}.txt rows must align with profile.txt and contain samples")
                if not np.isfinite(matrix).all():
                    raise ValueError(f"{sensor}.txt contains non-finite samples")
                summaries[sensor] = {
                    "cycle_mean": matrix.mean(axis=1),
                    "within_cycle_sd": matrix.std(axis=1),
                }
    except zipfile.BadZipFile as exc:
        raise ValueError("hydraulic input must be the official UCI ZIP archive") from exc

    conditioned: dict[str, Any] = {}
    for component, specification in _HYDRAULIC_COMPONENTS.items():
        component_column = specification["column"]
        all_counts = {
            (str(int(level)) if float(level).is_integer() else str(level)): int(np.count_nonzero(profile[:, component_column] == level))
            for level in sorted(set(profile[:, component_column].tolist()))
        }
        isolated_mask = np.ones(profile.shape[0], dtype=bool)
        for column, level in specification["nominal_others"].items():
            isolated_mask &= profile[:, column] == level
        level_summaries: dict[str, Any] = {}
        for level in specification["levels"]:
            mask = isolated_mask & (profile[:, component_column] == level)
            signal_summaries: dict[str, Any] = {}
            if mask.any():
                for sensor in specification["signals"]:
                    signal_summaries[sensor] = {
                        "cycle_mean": _quantiles(summaries[sensor]["cycle_mean"][mask]),
                        "within_cycle_sd_p50": round(float(np.median(summaries[sensor]["within_cycle_sd"][mask])), 6),
                    }
            level_summaries[str(level)] = {"cycles": int(mask.sum()), "signals": signal_summaries}
        conditioned[component] = {
            "all_cycle_counts_by_label": all_counts,
            "other_conditions_nominal_and_stable": True,
            "levels": level_summaries,
        }

    return {
        "analysis_version": "1.0.0",
        "source": {
            "dataset": "Condition monitoring of hydraulic systems (ZeMA hydraulic test rig)",
            "publisher": "UCI Machine Learning Repository",
            "doi": "10.24432/C5CW21",
            "license": "CC BY 4.0",
            "archive_sha256": digest,
            "archive_bytes": path.stat().st_size,
            "cycles": int(profile.shape[0]),
            "cycle_duration_s": 60,
            "sampling_hz": {
                "pressure_and_motor_power": 100,
                "flow": 10,
                "temperature_vibration_efficiency": 1,
            },
        },
        "design": {
            "target_labels": ["cooler_condition_pct", "valve_condition_pct", "internal_pump_leakage_class", "accumulator_pressure_bar", "stable_flag"],
            "interpretation": "The four component condition values describe graded degradation rather than independent categorical faults; stable_flag=1 means steady state may not yet have been reached.",
        },
        "nominal_baseline_cycles": int(np.count_nonzero(np.all(profile == np.array([100, 100, 0, 130, 0]), axis=1))),
        "conditioned_cycle_mean_summary": conditioned,
        "interpretation": [
            "Profiles isolate one component label while holding other component labels at their nominal values and stable_flag at 0.",
            "Summaries describe one experimental hydraulic test rig and are not universal operating limits, causal effects, or failure prevalence estimates.",
            "Motor power is measured, but motor current and RPM are absent; those simulator signals cannot be calibrated from this dataset.",
            "Labels are cycle-wise, so they do not identify the onset time within a 60-second cycle.",
            "No raw source observations or time-series rows are emitted.",
        ],
    }


def write_zema_hydraulic_analysis(input_path: Path, output_path: Path) -> Path:
    report = analyze_zema_hydraulic(input_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return output_path


def analyze_bosch_cnc(input_dir: Path, source_revision: str | None = None) -> dict[str, Any]:
    """Summarize per-segment Bosch CNC acceleration RMS without retaining samples.

    h5py is an optional calibration dependency. Source labels are preserved as
    good/bad process annotations and must not be interpreted as fault types.
    """
    try:
        import h5py
    except ImportError as exc:
        raise RuntimeError("Bosch CNC analysis requires the optional dependency: uv sync --extra calibration") from exc
    if not input_dir.is_dir():
        raise FileNotFoundError(input_dir)

    import re

    pattern = re.compile(r"(M0[123])/(OP\d{2})/(good|bad)/\1_(Oct|Feb|Aug)_(\d{4})_\2_(\d+)\.h5")
    files = sorted(input_dir.rglob("*.h5"))
    if not files:
        raise ValueError("Bosch CNC input directory contains no .h5 files")
    grouped: dict[tuple[str, str, str, str], list[dict[str, Any]]] = {}
    manifest_digest = hashlib.sha256()
    total_bytes = 0
    label_counts = {"good": 0, "bad": 0}
    machine_counts: dict[str, dict[str, int]] = {}
    for path in files:
        relative = path.relative_to(input_dir).as_posix()
        match = pattern.fullmatch(relative)
        if not match:
            raise ValueError(f"unexpected Bosch CNC HDF5 path: {relative}")
        machine, operation, label, month, year, _example = match.groups()
        file_hash = _sha256(path)
        manifest_digest.update(relative.encode("utf-8") + b"\0" + bytes.fromhex(file_hash))
        total_bytes += path.stat().st_size
        try:
            with h5py.File(path, "r") as source:
                if "vibration_data" not in source:
                    raise ValueError(f"missing vibration_data dataset: {relative}")
                data = source["vibration_data"]
                if data.ndim != 2 or data.shape[1] != 3 or data.shape[0] < 2 or data.dtype.kind not in "fiu":
                    raise ValueError(f"expected an N x 3 numeric vibration array: {relative}")
                vector_square_sum = 0.0
                remaining = data.shape[0]
                chunk_size = 65_536
                for start in range(0, data.shape[0], chunk_size):
                    chunk = np.asarray(data[start : start + chunk_size], dtype=np.float64)
                    if not np.isfinite(chunk).all():
                        raise ValueError(f"non-finite vibration sample: {relative}")
                    if start == 0:
                        axis_sum = np.zeros(3, dtype=np.float64)
                    axis_sum += np.square(chunk).sum(axis=0)
                    vector_square_sum += np.square(chunk).sum()
                axis_rms = np.sqrt(axis_sum / remaining).tolist()
                vector_rms = float(np.sqrt(vector_square_sum / remaining))
        except OSError as exc:
            raise ValueError(f"invalid HDF5 source file: {relative}") from exc
        record = {
            "axis_rms": axis_rms,
            "vector_rms": vector_rms,
            "samples": int(data.shape[0]),
            "duration_s": data.shape[0] / 2000,
        }
        grouped.setdefault((machine, operation, label, f"{month}_{year}"), []).append(record)
        label_counts[label] += 1
        machine_counts.setdefault(machine, {"good": 0, "bad": 0})[label] += 1

    groups: list[dict[str, Any]] = []
    for (machine, operation, label, timeframe), items in sorted(grouped.items()):
        vector = np.array([item["vector_rms"] for item in items])
        axes = np.array([item["axis_rms"] for item in items])
        durations = np.array([item["duration_s"] for item in items])
        groups.append(
            {
                "machine": machine,
                "operation": operation,
                "source_label": label,
                "timeframe": timeframe,
                "files": len(items),
                "duration_s_p05_p50_p95": _quantiles(durations),
                "vector_rms_p05_p50_p95": _quantiles(vector),
                "axis_rms_p05_p50_p95": {
                    axis: _quantiles(axes[:, index]) for index, axis in enumerate(("x", "y", "z"))
                },
            }
        )
    return {
        "analysis_version": "1.0.0",
        "source": {
            "dataset": "Bosch CNC Machining Dataset",
            "repository": "https://github.com/boschresearch/CNC_Machining",
            "publisher": "Bosch Research; UCI Machine Learning Repository record 752",
            "doi": "10.1016/j.procir.2022.04.022",
            "license": "CC BY 4.0 for the data directory",
            "source_revision": source_revision,
            "input_files": len(files),
            "input_bytes": total_bytes,
            "input_manifest_sha256": manifest_digest.hexdigest(),
            "sampling_hz": 2000,
            "axis_count": 3,
            "sample_unit": "not specified in the HDF5 files; RMS values remain in source units",
        },
        "label_counts": label_counts,
        "machine_label_counts": machine_counts,
        "grouping": ["machine", "operation", "source good/bad label", "six-month timeframe identifier"],
        "segment_aggregates": groups,
        "interpretation": [
            "The source labels indicate manually annotated process condition and do not identify a specific fault mechanism or fault onset time.",
            "Vibration RMS is a descriptive feature of each operation segment; different machines, tools, and timeframes are not interchangeable baselines.",
            "The source provides acceleration data, not the Lab's velocity vibration signal in mm/s; absolute values must not be mapped to the canonical signal.",
            "The good/bad classes are strongly imbalanced and their counts are not failure prevalence estimates.",
            "This analysis emits group quantiles and provenance only; it does not emit source samples or segment-level measurements.",
        ],
    }


def write_bosch_cnc_analysis(input_dir: Path, output_path: Path, source_revision: str | None = None) -> Path:
    report = analyze_bosch_cnc(input_dir, source_revision)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    return output_path
