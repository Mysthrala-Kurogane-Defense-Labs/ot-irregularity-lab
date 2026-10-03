"""Scenario runner, canonical telemetry, and isolated ground truth writer."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl
import yaml

from . import SCHEMA_VERSION, __version__
from .models import GroundTruthEvent, Scenario
from .process import ProcessState, regime_at, signal_metadata, simulate_step

EPOCH = datetime(2025, 1, 1, tzinfo=timezone.utc)

EVENT_SIGNALS = {
    "sensor_drift": ["*"], "sudden_spike": ["*"],
    "bearing_degradation": ["vibration_mm_s", "spindle_vibration_mm_s", "motor_temperature_c", "spindle_temperature_c"],
    "cavitation": ["vibration_mm_s", "flow_l_min", "pressure_bar", "motor_current_a"],
    "cooling_degradation": ["motor_temperature_c", "spindle_temperature_c", "oil_temperature_c", "discharge_temperature_c"],
    "mechanical_overload": ["motor_current_a", "spindle_power_kw", "vibration_mm_s", "load_pct"],
    "sensor_stuck": ["*"], "sensor_bias": ["*"], "missing_telemetry": ["*"],
    "single_signal_loss": ["*"], "asset_communication_loss": ["*"],
    "quality_degradation": ["*"], "regime_mismatch": ["*"],
    "multivariate_novelty": ["*"], "maintenance_activity": ["*"],
}


def read_scenario(path: Path) -> Scenario:
    with path.open("r", encoding="utf-8") as stream:
        data = yaml.safe_load(stream)
    return Scenario.model_validate(data)


def _event_active(event: Any, seconds: float) -> bool:
    return event.start <= seconds < event.start + event.duration


def _affect(
    event: Any, signals: dict[str, float], seconds: float,
    states: dict[str, ProcessState], asset_class: str,
) -> tuple[dict[str, float], set[str], str]:
    """Apply a named physical/measurement/communications effect, returning label metadata."""
    affected: set[str] = set()
    quality = "GOOD"
    kind = event.type
    fraction = min(1.0, max(0.0, (seconds - event.start) / max(event.duration, 1)))
    p = event.parameters
    def pick(*names: str) -> list[str]:
        return [name for name in signals if name in names or any(name in n for n in names)]
    if kind == "bearing_degradation":
        vib = pick("vibration_mm_s", "spindle_vibration_mm_s")
        temp = pick("motor_temperature_c", "spindle_temperature_c")
        gain = float(p.get("vibration_gain", 0.20)) * fraction
        tgain = float(p.get("temperature_gain", 0.08)) * fraction
        for name in vib:
            signals[name] *= 1 + gain
        for name in temp:
            signals[name] += 15 * tgain
        affected.update(vib + temp)
    elif kind == "cavitation":
        for name in pick("vibration_mm_s"):
            signals[name] += float(p.get("vibration_gain", 0.8)) * fraction
            affected.add(name)
        for name in pick("flow_l_min"):
            signals[name] *= 1 - float(p.get("flow_loss", 0.12)) * fraction
            affected.add(name)
        for name in pick("pressure_bar"):
            signals[name] *= 1 - float(p.get("pressure_loss", 0.10)) * fraction
            affected.add(name)
        for name in pick("motor_current_a"):
            signals[name] *= 1 + float(p.get("current_gain", 0.05)) * fraction
            affected.add(name)
    elif kind == "cooling_degradation":
        for name in pick("temperature_c", "oil_temperature_c", "discharge_temperature_c"):
            signals[name] += float(p.get("temperature_gain", 0.08)) * 35 * fraction
            affected.add(name)
    elif kind == "mechanical_overload":
        for name in pick("motor_current_a", "spindle_power_kw"):
            signals[name] *= 1 + float(p.get("current_gain", 0.12)) * fraction
            affected.add(name)
        for name in pick("vibration_mm_s"):
            signals[name] *= 1 + float(p.get("vibration_gain", 0.20)) * fraction
            affected.add(name)
    elif kind == "sensor_drift":
        names = [str(p["signal"])] if "signal" in p else list(signals)
        for name in names:
            if name in signals:
                signals[name] += float(p.get("rate_per_minute", 0.5)) * (seconds - event.start) / 60
                affected.add(name)
    elif kind == "sensor_bias":
        names = [str(p["signal"])] if "signal" in p else list(signals)
        for name in names:
            if name in signals:
                signals[name] += float(p.get("bias", 1.0))
                affected.add(name)
    elif kind == "sudden_spike":
        names = [str(p["signal"])] if "signal" in p else [next(iter(signals))]
        for name in names:
            if name in signals:
                signals[name] += float(p.get("magnitude", 5.0))
                affected.add(name)
    elif kind == "sensor_stuck":
        names = [str(p["signal"])] if "signal" in p else [next(iter(signals))]
        state = states.get("__sensor_stuck", ProcessState())
        for name in names:
            if name in signals:
                state.previous_signals.setdefault(name, signals[name])
                signals[name] = state.previous_signals[name]
                affected.add(name)
        states["__sensor_stuck"] = state
        quality = "UNCERTAIN"
    elif kind == "single_signal_loss":
        names = [str(p["signal"])] if "signal" in p else [next(iter(signals))]
        for name in names:
            signals.pop(name, None)
            affected.add(name)
    elif kind in ("missing_telemetry", "asset_communication_loss"):
        loss_pct = float(p.get("loss_pct", 100 if kind == "asset_communication_loss" else 25))
        if loss_pct >= 100 or kind == "asset_communication_loss":
            affected.update(signals)
            signals.clear()
        else:
            for name in list(signals):
                # Stable hashed selection per timestamp, no hidden state or extra RNG consumption.
                token = f"{event.asset}|{name}|{int(seconds * 1000)}|{event.start}".encode()
                if int(hashlib.sha256(token).hexdigest()[:8], 16) % 100 < loss_pct:
                    signals.pop(name)
                    affected.add(name)
    elif kind == "quality_degradation":
        quality = "BAD"
        affected.update(signals)
    elif kind == "regime_mismatch":
        for name in pick("load_pct"):
            signals[name] *= float(p.get("load_multiplier", 0.7))
            affected.add(name)
    elif kind == "multivariate_novelty":
        # Individually in-range but unusual: one or more high-normal process channels paired with low power.
        for name in pick("temperature_c", "oil_temperature_c", "spindle_temperature_c"):
            _, _, lo, hi = signal_metadata(asset_class)[name]
            signals[name] = max(signals[name], lo + 0.78 * (hi - lo))
            affected.add(name)
        for name in pick("vibration_mm_s", "spindle_vibration_mm_s"):
            _, _, lo, hi = signal_metadata(asset_class)[name]
            signals[name] = max(signals[name], lo + 0.75 * (hi - lo))
            affected.add(name)
        for name in pick("spindle_power_kw", "motor_current_a"):
            signals[name] = min(signals[name], signal_metadata(asset_class)[name][2] + 0.25 * (signal_metadata(asset_class)[name][3] - signal_metadata(asset_class)[name][2]))
            affected.add(name)
    elif kind == "maintenance_activity":
        for name in pick("motor_current_a", "spindle_power_kw", "load_pct"):
            signals[name] *= float(p.get("load_multiplier", 0.1))
            affected.add(name)
    return signals, affected, quality


def simulate(scenario: Scenario, seed: int) -> tuple[pl.DataFrame, dict[str, Any], dict[str, Any]]:
    rng = np.random.default_rng(seed)
    origin = EPOCH
    rows: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    jitter = scenario.sampling_jitter_ms
    for index, anomaly in enumerate(scenario.anomalies, 1):
        asset = next((item for item in scenario.assets if item.asset_id == anomaly.asset), None)
        if asset is None:
            raise ValueError(f"anomaly references unknown asset {anomaly.asset!r}")
        meta = signal_metadata(asset.asset_class)
        signals = [s for s in meta if s in EVENT_SIGNALS[anomaly.type] or "*" in EVENT_SIGNALS[anomaly.type]]
        events.append(GroundTruthEvent(
            event_id=f"evt-{index}", asset_id=anomaly.asset, type=anomaly.type,
            start=origin + timedelta(seconds=anomaly.start),
            end=origin + timedelta(seconds=anomaly.start + anomaly.duration),
            affected_signals=signals, severity=anomaly.severity, parameters=anomaly.parameters,
        ).model_dump(mode="json"))
    step_ms = scenario.sampling_interval_ms
    n_steps = int(scenario.duration_s * 1000 / step_ms)
    states = {asset.asset_id: ProcessState(temperature=scenario.ambient_temperature_c) for asset in scenario.assets}
    previous_sample_ms: dict[tuple[str, str], float] = {}
    timestamp_ms = 0.0
    for step in range(n_steps):
        jitter_value = float(rng.uniform(-jitter, jitter)) if jitter else 0.0
        timestamp_ms += step_ms + jitter_value
        seconds = step * step_ms / 1000
        timestamp = origin + timedelta(milliseconds=max(0, timestamp_ms))
        for asset in scenario.assets:
            state = states[asset.asset_id]
            regime = regime_at(seconds, scenario.duration_s, asset.regimes)
            signals = simulate_step(asset, state, regime, step_ms / 1000, scenario.ambient_temperature_c, rng)
            quality_by_signal = {name: "GOOD" for name in signals}
            active_events: list[Any] = []
            for anomaly in scenario.anomalies:
                if anomaly.asset == asset.asset_id and _event_active(anomaly, seconds):
                    active_events.append(anomaly)
                    signals, affected, quality = _affect(anomaly, signals, seconds, states, asset.asset_class)
                    for name in affected:
                        if name in quality_by_signal and quality != "GOOD":
                            quality_by_signal[name] = quality
                        elif name in signals and anomaly.type == "quality_degradation":
                            quality_by_signal[name] = "BAD"
            metadata = signal_metadata(asset.asset_class)
            for signal, value in signals.items():
                signal_class, unit, eng_min, eng_max = metadata[signal]
                key = (asset.asset_id, signal)
                last = previous_sample_ms.get(key)
                rows.append({
                    "schema_version": SCHEMA_VERSION, "run_id": scenario.run_id,
                    "timestamp": timestamp, "asset_id": asset.asset_id,
                    "asset_class": asset.asset_class.upper(), "tag_id": signal,
                    "signal_class": signal_class, "value": float(value), "unit": unit,
                    "quality": quality_by_signal.get(signal, "GOOD"),
                    "sampling_interval_ms": step_ms if last is None else max(1, int(timestamp_ms - last)),
                    "operating_regime": regime if scenario.expose_operating_regime else None,
                    "engineering_min": eng_min, "engineering_max": eng_max,
                    "protocol": None, "device_id": asset.device_id,
                    "site_id": asset.site_id, "zone_id": asset.zone_id,
                })
                previous_sample_ms[key] = timestamp_ms
            for event in active_events:
                event_index = scenario.anomalies.index(event) + 1
                event_record = next(e for e in events if e["event_id"] == f"evt-{event_index}")
                event_record.setdefault("observed_start", timestamp.isoformat())
                event_record["observed_end"] = timestamp.isoformat()
    telemetry = pl.DataFrame(rows, schema_overrides={
        "timestamp": pl.Datetime("ms", "UTC"), "value": pl.Float64,
        "engineering_min": pl.Float64, "engineering_max": pl.Float64,
    })
    ground_truth = {"run_id": scenario.run_id, "events": events}
    scenario_canonical = json.dumps(scenario.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    metadata = {
        "run_id": scenario.run_id, "scenario_id": scenario.scenario_id,
        "scenario_version": scenario.scenario_version, "seed": seed,
        "simulator_version": __version__, "schema_version": SCHEMA_VERSION,
        "scenario_sha256": hashlib.sha256(scenario_canonical.encode()).hexdigest(),
        "started_at": origin.isoformat(), "duration_s": scenario.duration_s,
        "sampling_interval_ms": step_ms, "observation_count": telemetry.height,
        "asset_count": len(scenario.assets), "synthetic": True,
        "generated": True, "customer_data": False,
    }
    return telemetry, ground_truth, metadata


def write_run(scenario: Scenario, seed: int, output: Path, csv: bool = False, jsonl: bool = False) -> dict[str, Any]:
    output.mkdir(parents=True, exist_ok=True)
    telemetry, ground_truth, metadata = simulate(scenario, seed)
    telemetry.write_parquet(output / "telemetry.parquet", compression="zstd", statistics=True)
    (output / "ground_truth.json").write_text(json.dumps(ground_truth, indent=2) + "\n", encoding="utf-8")
    (output / "run_metadata.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    if csv:
        telemetry.write_csv(output / "telemetry.csv")
    if jsonl:
        telemetry.write_ndjson(output / "telemetry.jsonl")
    return metadata


def replay(run_dir: Path, output: Path | None = None) -> Path:
    metadata = json.loads((run_dir / "run_metadata.json").read_text(encoding="utf-8"))
    scenario_path = run_dir / "scenario.yaml"
    if not scenario_path.exists():
        raise FileNotFoundError(f"replay requires the preserved {scenario_path.name}")
    scenario = read_scenario(scenario_path)
    target = output or run_dir / "replayed"
    write_run(scenario, int(metadata["seed"]), target)
    return target


def batch(suite_path: Path, runs: int, output: Path, seed: int) -> None:
    suite = yaml.safe_load(suite_path.read_text(encoding="utf-8"))
    base = Scenario.model_validate(suite["scenario"])
    partitions = suite.get("partitions", {"train": 0.7, "validation": 0.15, "test": 0.15})
    if abs(sum(partitions.values()) - 1.0) > 1e-9:
        raise ValueError("partition fractions must sum to 1")
    counts = {key: int(runs * value) for key, value in partitions.items()}
    for key in list(partitions)[-1:]:
        counts[key] += runs - sum(counts.values())
    seed_rng = np.random.default_rng(seed)
    manifest_runs = []
    for partition, count in counts.items():
        for index in range(count):
            run_seed = int(seed_rng.integers(0, 2**63, dtype=np.int64))
            scenario = base.model_copy(update={"run_id": f"{partition}-{index+1:05d}"})
            run_dir = output / partition / scenario.run_id
            write_run(scenario, run_seed, run_dir)
            (run_dir / "scenario.yaml").write_text(yaml.safe_dump(scenario.model_dump(mode="json"), sort_keys=False), encoding="utf-8")
            digest = hashlib.sha256((run_dir / "telemetry.parquet").read_bytes()).hexdigest()
            manifest_runs.append({"partition": partition, "run_id": scenario.run_id, "seed": run_seed, "sha256": digest})
    asset_distribution: dict[str, int] = {}
    for asset in base.assets:
        asset_distribution[asset.asset_class] = asset_distribution.get(asset.asset_class, 0) + runs
    manifest = {
        "dataset_id": output.name, "simulator_version": __version__, "schema_version": SCHEMA_VERSION,
        "run_count": runs, "partition_counts": counts, "runs": manifest_runs,
        "class_distribution": {"normal": runs if not base.anomalies else 0, "anomalous": runs if base.anomalies else 0},
        "asset_distribution": asset_distribution,
        "synthetic": True, "generated": True, "customer_data": False,
    }
    (output / "dataset_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
