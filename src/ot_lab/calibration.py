"""Reproducible, data-minimal analyses of openly licensed process datasets."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

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
    )
    input_rows = frame.height
    required_columns = ["timestamp", "motor_current_a", "oil_temperature_c", "pressure_bar", "compressor_valve", "load_valve"]
    null_or_parse_error_counts = {
        name: frame.get_column(name).null_count() for name in required_columns
    }
    source_order_timestamps = frame.get_column("timestamp").drop_nulls()
    source_order_deltas = source_order_timestamps.diff().dt.total_microseconds()
    out_of_order_intervals = int((source_order_deltas < 0).sum() or 0)
    valid_frame = frame.drop_nulls(required_columns)
    dropped_rows = input_rows - valid_frame.height
    if valid_frame.is_empty():
        raise ValueError("MetroPT input has no usable rows after timestamp and sensor validation")
    duplicate_timestamp_extra_rows = int(
        valid_frame.group_by("timestamp").len()
        .filter(pl.col("len") > 1)
        .select((pl.col("len") - 1).sum())
        .item() or 0
    )
    invalid_ranges = {
        "negative_motor_current_rows": int((valid_frame.get_column("motor_current_a") < 0).sum()),
        "negative_pressure_rows": int((valid_frame.get_column("pressure_bar") < 0).sum()),
        "nonbinary_COMP_rows": int((~valid_frame.get_column("compressor_valve").is_in([0.0, 1.0])).sum()),
        "nonbinary_load_valve_rows": int((~valid_frame.get_column("load_valve").is_in([0.0, 1.0])).sum()),
    }
    frame = valid_frame.sort("timestamp").with_columns(
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
    digital_state_stats: dict[str, Any] = {}
    state_groups = frame.group_by(["compressor_valve", "load_valve"]).agg(
        pl.len().alias("rows"),
        pl.col("motor_current_a").quantile(0.05).alias("motor_current_a_p05"),
        pl.col("motor_current_a").quantile(0.50).alias("motor_current_a_p50"),
        pl.col("motor_current_a").quantile(0.95).alias("motor_current_a_p95"),
        pl.col("pressure_bar").quantile(0.50).alias("pressure_bar_p50"),
        (pl.col("motor_current_a") >= 8.5).mean().alias("fraction_current_at_least_8p5_a"),
    )
    for row in state_groups.iter_rows(named=True):
        state_key = f"COMP={row['compressor_valve']:g},DV={row['load_valve']:g}"
        digital_state_stats[state_key] = {
            key: (round(value, 6) if isinstance(value, float) else value)
            for key, value in row.items()
            if key not in {"compressor_valve", "load_valve"}
        }
    cadence = frame.filter(pl.col("cadence_s") > 0).select(
        pl.len().alias("positive_intervals"),
        pl.col("cadence_s").quantile(0.05).alias("p05_s"),
        pl.col("cadence_s").quantile(0.50).alias("p50_s"),
        pl.col("cadence_s").quantile(0.95).alias("p95_s"),
        (pl.col("cadence_s") > 120).mean().alias("fraction_over_120s"),
    ).row(0, named=True)
    result = {
        "analysis_version": "1.1.0",
        "data_quality": {
            "input_rows": input_rows,
            "usable_rows": frame.height,
            "rows_dropped_for_null_or_parse_errors": dropped_rows,
            "null_or_parse_error_counts_by_required_column": null_or_parse_error_counts,
            "duplicate_timestamp_extra_rows": duplicate_timestamp_extra_rows,
            "out_of_order_timestamp_intervals": out_of_order_intervals,
            "invalid_value_counts": invalid_ranges,
        },
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
        "digital_state_combinations": digital_state_stats,
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
