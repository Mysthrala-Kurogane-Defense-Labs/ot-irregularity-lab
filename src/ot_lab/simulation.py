"""Scenario runner, canonical telemetry, and isolated ground truth writer."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl
import yaml

from . import SCHEMA_VERSION, __version__
from .models import GroundTruthEvent, Scenario
from .process import ProcessState, regime_at, signal_metadata, simulate_step

EPOCH = datetime(2025, 1, 1, tzinfo=UTC)


def _resolve_ranges(scenario_data: dict[str, Any], rng: np.random.Generator) -> dict[str, Any]:
    """Replace declared numeric ranges with seeded values and validate their bounds."""
    resolved = json.loads(json.dumps(scenario_data))
    for anomaly in resolved.get("anomalies", []):
        for key, value in list(anomaly.get("parameters", {}).items()):
            if isinstance(value, dict) and set(value) == {"min", "max"}:
                low, high = float(value["min"]), float(value["max"])
                if not np.isfinite([low, high]).all() or low > high:
                    raise ValueError(f"invalid numeric range for parameter {key}")
                anomaly["parameters"][key] = float(rng.uniform(low, high))
        for field in ("start", "duration", "severity"):
            value = anomaly.get(field)
            if isinstance(value, dict) and set(value) == {"min", "max"}:
                low, high = float(value["min"]), float(value["max"])
                if not np.isfinite([low, high]).all() or low > high:
                    raise ValueError(f"invalid numeric range for {field}")
                anomaly[field] = float(rng.uniform(low, high))
    return resolved

def read_scenario(path: Path) -> Scenario:
    with path.open("r", encoding="utf-8") as stream:
        data = yaml.safe_load(stream)
    data = resolve_profiles(data)
    return Scenario.model_validate(data)


def resolve_profiles(data: dict[str, Any]) -> dict[str, Any]:
    """Resolve optional easy/medium/hard labels to explicit numeric parameters."""
    resolved = json.loads(json.dumps(data))
    profiles = {"easy": 0.50, "medium": 0.25, "hard": 0.10, "very_hard": 0.05}
    for anomaly in resolved.get("anomalies", []):
        profile_name = anomaly.pop("difficulty", None)
        if profile_name is None:
            continue
        if profile_name not in profiles:
            raise ValueError(f"unknown difficulty profile {profile_name!r}")
        gain_scale = profiles[profile_name]
        params = anomaly.setdefault("parameters", {})
        explicit_keys = ("vibration_gain", "temperature_gain", "current_gain", "flow_loss", "pressure_loss", "bias", "magnitude", "rate_per_minute")
        for key in explicit_keys:
            if key in params and isinstance(params[key], (int, float)):
                params[key] = float(params[key]) * gain_scale
        anomaly["resolved_difficulty"] = {"profile": profile_name, "gain_scale": gain_scale}
        if "progression" in params and params["progression"] == "linear":
            params["progression_rate_scale"] = 1.0 / gain_scale
    return resolved


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
        progression = str(p.get("progression", "linear"))
        progress = fraction if progression == "linear" else min(1.0, fraction**2) if progression == "slow_start" else fraction**0.5 if progression == "fast_start" else None
        if progress is None:
            raise ValueError(f"unsupported bearing progression {progression!r}")
        gain = float(p.get("vibration_gain", 0.20)) * progress
        tgain = float(p.get("temperature_gain", 0.08)) * progress
        for name in vib:
            signals[name] *= 1 + gain
        for name in temp:
            signals[name] += 15 * tgain
        affected.update(vib + temp)
    elif kind == "cavitation":
        for name in pick("vibration_mm_s", "spindle_vibration_mm_s"):
            signals[name] += float(p.get("vibration_gain", 0.8)) * fraction
            affected.add(name)
        for name in pick("flow_l_min"):
            signals[name] *= 1 - float(p.get("flow_loss", 0.12)) * fraction
            affected.add(name)
        for name in pick("pressure_bar", "coolant_pressure_bar"):
            signals[name] *= 1 - float(p.get("pressure_loss", 0.10)) * fraction
            affected.add(name)
        for name in pick("motor_current_a"):
            signals[name] *= 1 + float(p.get("current_gain", 0.05)) * fraction
            affected.add(name)
    elif kind == "cooling_degradation":
        for name in pick("temperature_c", "oil_temperature_c", "discharge_temperature_c", "spindle_temperature_c"):
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
        if any(name not in signals for name in names):
            raise ValueError("sensor_drift references a signal absent from the target asset")
        for name in names:
            if name in signals:
                signals[name] += float(p.get("rate_per_minute", 0.5)) * (seconds - event.start) / 60
                affected.add(name)
    elif kind == "sensor_bias":
        names = [str(p["signal"])] if "signal" in p else list(signals)
        if any(name not in signals for name in names):
            raise ValueError("sensor_bias references a signal absent from the target asset")
        for name in names:
            if name in signals:
                signals[name] += float(p.get("bias", 1.0))
                affected.add(name)
    elif kind == "sudden_spike":
        names = [str(p["signal"])] if "signal" in p else [next(iter(signals))]
        if any(name not in signals for name in names):
            raise ValueError("sudden_spike references a signal absent from the target asset")
        for name in names:
            if name in signals:
                signals[name] += float(p.get("magnitude", 5.0))
                affected.add(name)
    elif kind == "sensor_stuck":
        names = [str(p["signal"])] if "signal" in p else [next(iter(signals))]
        if any(name not in signals for name in names):
            raise ValueError("sensor_stuck references a signal absent from the target asset")
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
        if any(name not in signals for name in names):
            raise ValueError("single_signal_loss references a signal absent from the target asset")
        for name in names:
            signals.pop(name, None)
            affected.add(name)
    elif kind == "asset_communication_loss":
        affected.update(signals)
        signals.clear()
    elif kind == "missing_telemetry":
        loss_pct = float(p.get("loss_pct", 100 if kind == "asset_communication_loss" else 25))
        if not 0 <= loss_pct <= 100:
            raise ValueError("loss_pct must be within 0..100")
        if loss_pct >= 100:
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
        targets = pick("load_pct", "spindle_power_kw", "motor_current_a", "feed_rate")
        for name in targets:
            signals[name] *= float(p.get("load_multiplier", 0.7))
            affected.add(name)
    elif kind == "multivariate_novelty":
        # Each selected channel remains inside engineering bounds; the joint pattern is unusual.
        targets = [(str(p.get("signal_a", "")), float(p.get("signal_a_pct", 0.8))), (str(p.get("signal_b", "")), float(p.get("signal_b_pct", 0.8)))]
        configured = [(name, pct) for name, pct in targets if name]
        if configured:
            for name, pct in configured:
                if name not in signals:
                    raise ValueError(f"multivariate_novelty references unknown signal {name!r}")
                _, _, lo, hi = signal_metadata(asset_class)[name]
                if not 0 <= pct <= 1:
                    raise ValueError("multivariate_novelty signal percentages must be within 0..1")
                signals[name] = lo + pct * (hi - lo)
                affected.add(name)
        else:
            # High-normal thermal/vibration values paired with low-normal power/current.
            for name in pick("temperature_c", "oil_temperature_c", "spindle_temperature_c"):
                _, _, lo, hi = signal_metadata(asset_class)[name]
                signals[name] = float(np.clip(max(signals[name], lo + 0.78 * (hi - lo)), lo, hi))
                affected.add(name)
            for name in pick("vibration_mm_s", "spindle_vibration_mm_s"):
                _, _, lo, hi = signal_metadata(asset_class)[name]
                signals[name] = float(np.clip(max(signals[name], lo + 0.75 * (hi - lo)), lo, hi))
                affected.add(name)
            for name in pick("spindle_power_kw", "motor_current_a"):
                bounds = signal_metadata(asset_class)[name]
                signals[name] = float(np.clip(min(signals[name], bounds[2] + 0.25 * (bounds[3] - bounds[2])), bounds[2], bounds[3]))
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
        events.append(GroundTruthEvent(
            event_id=f"evt-{index}", asset_id=anomaly.asset, type=anomaly.type,
            start=origin + timedelta(seconds=anomaly.start),
            end=origin + timedelta(seconds=anomaly.start + anomaly.duration),
            affected_signals=[], severity=anomaly.severity, parameters=anomaly.parameters,
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
            regime = regime_at(seconds, scenario.duration_s, asset.regimes, scenario.shift_pattern)
            ambient = scenario.ambient_temperature_c + scenario.ambient_temperature_drift_c * seconds / max(scenario.duration_s, 1)
            signals = simulate_step(asset, state, regime, step_ms / 1000, ambient, rng)
            quality_by_signal = {name: "GOOD" for name in signals}
            active_events: list[Any] = []
            for anomaly in scenario.anomalies:
                if anomaly.asset == asset.asset_id and _event_active(anomaly, seconds):
                    active_events.append(anomaly)
                    before = set(signals)
                    signals, affected, quality = _affect(anomaly, signals, seconds, states, asset.asset_class)
                    event_index = scenario.anomalies.index(anomaly) + 1
                    event_record = next(e for e in events if e["event_id"] == f"evt-{event_index}")
                    event_record["affected_signals"] = sorted(set(event_record["affected_signals"]) | affected)
                    if anomaly.type == "quality_degradation":
                        for name in before & set(signals):
                            quality_by_signal[name] = quality
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
        "asset_count": len(scenario.assets), "asset_ids": [asset.asset_id for asset in scenario.assets], "synthetic": True,
        "generated": True, "customer_data": False,
    }
    return telemetry, ground_truth, metadata


def write_run(scenario: Scenario, seed: int, output: Path, csv: bool = False, jsonl: bool = False, persist_scenario: bool = True) -> dict[str, Any]:
    output.mkdir(parents=True, exist_ok=True)
    telemetry, ground_truth, metadata = simulate(scenario, seed)
    telemetry.write_parquet(output / "telemetry.parquet", compression="zstd", statistics=True)
    (output / "ground_truth.json").write_text(json.dumps(ground_truth, indent=2) + "\n", encoding="utf-8")
    (output / "run_metadata.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    if csv:
        telemetry.write_csv(output / "telemetry.csv")
    if jsonl:
        telemetry.write_ndjson(output / "telemetry.jsonl")
    if persist_scenario:
        (output / "scenario.yaml").write_text(yaml.safe_dump(scenario.model_dump(mode="json"), sort_keys=False), encoding="utf-8")
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
    if runs <= 0:
        raise ValueError("runs must be positive")
    suite = yaml.safe_load(suite_path.read_text(encoding="utf-8"))
    base = suite["scenario"]
    partitions = suite.get("partitions", {"train": 0.7, "validation": 0.15, "test": 0.15})
    if "challenge" in {name.lower() for name in partitions}:
        raise ValueError("challenge partitions must use ephemeral challenge generation")
    if not {"train", "validation", "test"}.issubset(partitions):
        raise ValueError("partitions must define train, validation, and test")
    if any(not np.isfinite(value) or value < 0 for value in partitions.values()):
        raise ValueError("partition fractions must be finite and non-negative")
    if abs(sum(partitions.values()) - 1.0) > 1e-9:
        raise ValueError("partition fractions must sum to 1")
    counts = {key: int(runs * value) for key, value in partitions.items()}
    for key in list(partitions)[-1:]:
        counts[key] += runs - sum(counts.values())
    seed_rng = np.random.default_rng(seed)
    used_seeds: set[int] = set()
    manifest_runs = []
    class_distribution = {"normal": 0, "anomalous": 0}
    asset_distribution: dict[str, int] = {}
    event_distribution: dict[str, int] = {}
    observation_total = 0
    for partition, count in counts.items():
        for index in range(count):
            run_seed = int(seed_rng.integers(0, 2**63, dtype=np.int64))
            while run_seed in used_seeds:
                run_seed = int(seed_rng.integers(0, 2**63, dtype=np.int64))
            used_seeds.add(run_seed)
            scenario_data = json.loads(json.dumps(base))
            scenario_data["run_id"] = f"{partition}-{index+1:05d}"
            local_rng = np.random.default_rng(run_seed)
            scenario_data = _resolve_ranges(scenario_data, local_rng)
            scenario_data["run_id"] = f"{partition}-{index+1:05d}"
            scenario = Scenario.model_validate(resolve_profiles(scenario_data))
            run_dir = output / partition / scenario.run_id
            write_run(scenario, run_seed, run_dir)
            (run_dir / "scenario.yaml").write_text(yaml.safe_dump(scenario.model_dump(mode="json"), sort_keys=False), encoding="utf-8")
            digest = hashlib.sha256((run_dir / "telemetry.parquet").read_bytes()).hexdigest()
            manifest_runs.append({
                "partition": partition, "run_id": scenario.run_id, "seed": run_seed,
                "telemetry_sha256": digest, "scenario_id": scenario.scenario_id,
                "scenario_version": scenario.scenario_version,
            })
            run_meta = json.loads((run_dir / "run_metadata.json").read_text(encoding="utf-8"))
            manifest_runs[-1]["observation_count"] = run_meta["observation_count"]
            manifest_runs[-1]["scenario_sha256"] = run_meta["scenario_sha256"]
            manifest_runs[-1]["ground_truth_sha256"] = hashlib.sha256((run_dir / "ground_truth.json").read_bytes()).hexdigest()
            manifest_runs[-1]["metadata_sha256"] = hashlib.sha256((run_dir / "run_metadata.json").read_bytes()).hexdigest()
            observation_total += run_meta["observation_count"]
            class_distribution["anomalous" if scenario.anomalies else "normal"] += 1
            for anomaly in scenario.anomalies:
                event_distribution[anomaly.type] = event_distribution.get(anomaly.type, 0) + 1
            for asset in scenario.assets:
                asset_distribution[asset.asset_class] = asset_distribution.get(asset.asset_class, 0) + 1
    manifest = {
        "dataset_id": output.name, "simulator_version": __version__, "schema_version": SCHEMA_VERSION,
        "run_count": runs, "observation_count": observation_total,
        "partition_counts": counts, "runs": manifest_runs,
        "class_distribution": class_distribution,
        "asset_distribution": asset_distribution,
        "event_distribution": event_distribution,
        "synthetic": True, "generated": True, "customer_data": False,
    }
    (output / "dataset_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


def generate_challenge(suite_path: Path, output: Path, master_seed: int | None = None) -> tuple[Path, Path]:
    """Generate an ephemeral challenge case; master seed is OS-random unless explicitly supplied for tests."""
    suite = yaml.safe_load(suite_path.read_text(encoding="utf-8"))
    seed = int(np.random.SeedSequence().generate_state(1, dtype=np.uint64)[0]) if master_seed is None else master_seed
    case_dir = output / "case"
    scenario_data = json.loads(json.dumps(suite["scenario"]))
    scenario_data["run_id"] = f"challenge-{hashlib.sha256(str(seed).encode()).hexdigest()[:12]}"
    rng = np.random.default_rng(seed)
    scenario_data = _resolve_ranges(scenario_data, rng)
    scenario_data["run_id"] = f"challenge-{hashlib.sha256(str(seed).encode()).hexdigest()[:12]}"
    scenario_data = resolve_profiles(scenario_data)
    scenario = Scenario.model_validate(scenario_data)
    write_run(scenario, seed, case_dir, persist_scenario=False)
    # Hidden seed and resolved scenario are not persisted in a challenge case.
    metadata_path = case_dir / "run_metadata.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata.pop("seed", None)
    metadata.pop("scenario_sha256", None)
    metadata_path.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    truth_path = case_dir / "ground_truth.json"
    truth = json.loads(truth_path.read_text(encoding="utf-8"))
    for event in truth["events"]:
        event.pop("parameters", None)
    truth_path.write_text(json.dumps(truth, indent=2) + "\n", encoding="utf-8")
    # The local evaluator receives truth only after the model has exited; seed is held in memory, not written.
    return case_dir, case_dir / "ground_truth.json"
