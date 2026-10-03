"""Scenario runner, canonical telemetry, and isolated ground truth writer."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import tempfile
from concurrent.futures import ProcessPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl
import yaml

from . import GROUND_TRUTH_SCHEMA_VERSION, SCHEMA_VERSION, __version__
from .models import GroundTruthEvent, Scenario
from .process import ProcessState, regime_at, signal_metadata, simulate_step

EPOCH = datetime(2025, 1, 1, tzinfo=UTC)


def _resolve_ranges(scenario_data: dict[str, Any], rng: np.random.Generator) -> dict[str, Any]:
    """Replace declared numeric ranges with seeded values and validate their bounds."""
    resolved = json.loads(json.dumps(scenario_data))
    for asset in resolved.get("assets", []):
        for key, value in list(asset.get("process_parameters", {}).items()):
            if isinstance(value, dict) and set(value) == {"min", "max"}:
                low, high = float(value["min"]), float(value["max"])
                if not np.isfinite([low, high]).all() or low > high:
                    raise ValueError(f"invalid numeric range for process parameter {key}")
                asset["process_parameters"][key] = float(rng.uniform(low, high))
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


def _draw(spec: Any, rng: np.random.Generator) -> Any:
    """Draw a reproducible scalar from a literal, numeric range, or choice specification."""
    if isinstance(spec, dict):
        if set(spec) == {"min", "max"}:
            low, high = spec["min"], spec["max"]
            if isinstance(low, int) and isinstance(high, int):
                if low > high:
                    raise ValueError("range min exceeds max")
                return int(rng.integers(low, high + 1))
            low, high = float(low), float(high)
            if not np.isfinite([low, high]).all() or low > high:
                raise ValueError("range min exceeds max or contains a non-finite value")
            return float(rng.uniform(low, high))
        if set(spec) == {"choices"}:
            if not spec["choices"]:
                raise ValueError("choice specification must not be empty")
            return spec["choices"][int(rng.integers(0, len(spec["choices"]))) ]
        raise ValueError("sample specifications must use exactly min/max or choices")
    return spec


def _weighted_choice(items: list[dict[str, Any]], rng: np.random.Generator, label: str) -> dict[str, Any]:
    if not items:
        raise ValueError(f"generation requires at least one {label}")
    weights = np.asarray([float(item.get("weight", 1.0)) for item in items])
    if not np.isfinite(weights).all() or np.any(weights < 0) or weights.sum() <= 0:
        raise ValueError(f"{label} weights must be finite, non-negative, and not all zero")
    return items[int(rng.choice(len(items), p=weights / weights.sum()))]


def _draw_parameter(spec: Any, rng: np.random.Generator, asset_class: str) -> Any:
    if isinstance(spec, dict) and set(spec) == {"signal_class"}:
        inventory = signal_metadata(asset_class)
        candidates = [name for name, metadata in inventory.items() if spec["signal_class"] == "any" or metadata[0] == spec["signal_class"]]
        if not candidates:
            raise ValueError(f"no {spec['signal_class']} signal exists for {asset_class}")
        return candidates[int(rng.integers(0, len(candidates)))]
    return _draw(spec, rng)


def _generate_suite_scenario(base: dict[str, Any], generation: dict[str, Any], rng: np.random.Generator, run_id: str) -> dict[str, Any]:
    """Sample a complete run definition from an explicit, versioned suite distribution."""
    data = json.loads(json.dumps(base))
    data["run_id"] = run_id
    probability = float(generation.get("anomaly_probability", 0.0))
    if not 0 <= probability <= 1:
        raise ValueError("anomaly_probability must be within 0..1")

    for key, spec in generation.get("vary", {}).items():
        data[key] = _draw(spec, rng)

    profiles = generation.get("asset_profiles", [])
    if profiles:
        profile = _weighted_choice(profiles, rng, "asset profiles")
        data["assets"] = profile["assets"]

    regime_profiles = generation.get("regime_profiles", [])
    if regime_profiles:
        regime = _weighted_choice(regime_profiles, rng, "regime profiles")
        data["shift_pattern"] = regime["shift_pattern"]

    data["anomalies"] = []
    if generation.get("anomaly_templates") and rng.random() < probability:
        count = int(_draw(generation.get("anomaly_count", {"min": 1, "max": 1}), rng))
        available_classes = {asset["asset_class"] for asset in data["assets"]}
        templates = [item for item in generation["anomaly_templates"] if available_classes & set(item.get("asset_classes", available_classes))]
        if count < 1 or count > len(templates):
            raise ValueError("anomaly_count must be between 1 and the number of compatible distinct templates")
        selected: list[dict[str, Any]] = []
        remaining = list(templates)
        while len(selected) < count:
            item = _weighted_choice(remaining, rng, "anomaly templates")
            selected.append(item)
            remaining.remove(item)
        duration = int(data["duration_s"])
        for item in selected:
            candidates = [asset for asset in data["assets"] if asset["asset_class"] in item.get("asset_classes", [asset["asset_class"] for asset in data["assets"]])]
            if not candidates:
                raise ValueError(f"no compatible asset for anomaly template {item['type']}")
            fraction = float(_draw(item.get("duration_fraction", {"min": 0.08, "max": 0.2}), rng))
            if not 0 < fraction <= 1:
                raise ValueError("duration_fraction must be within (0, 1]")
            event_duration = max(1, min(duration, round(duration * fraction)))
            event_start = None
            asset = None
            for _ in range(256):
                candidate_asset = candidates[int(rng.integers(0, len(candidates)))]
                start_fraction = float(_draw(item.get("start_fraction", {"min": 0.1, "max": 0.7}), rng))
                if not 0 <= start_fraction <= 1:
                    raise ValueError("start_fraction must be within 0..1")
                candidate_start = max(0, min(duration - event_duration, round(duration * start_fraction)))
                candidate_end = candidate_start + event_duration
                occupied = [event for event in data["anomalies"] if event["asset"] == candidate_asset["asset_id"]]
                if all(candidate_end <= event["start"] or candidate_start >= event["start"] + event["duration"] for event in occupied):
                    asset, event_start = candidate_asset, candidate_start
                    break
            if asset is None or event_start is None:
                raise ValueError("could not place non-overlapping sampled events within the run")
            parameters = {key: _draw_parameter(value, rng, asset["asset_class"]) for key, value in item.get("parameters", {}).items()}
            if any(isinstance(value, dict) for value in parameters.values()):
                raise ValueError(f"unresolved parameter specification in template {item['type']}")
            data["anomalies"].append({
                "type": item["type"], "asset": asset["asset_id"], "start": event_start,
                "duration": event_duration, "severity": float(_draw(item.get("severity", {"min": 0.2, "max": 0.8}), rng)),
                "parameters": parameters,
            })
    return data

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
    states: dict[str, ProcessState], asset_class: str, sample_index: int, run_seed: int,
    event_id: str = "event-0",
) -> tuple[dict[str, float], set[str], str]:
    """Apply a named physical/measurement/communications effect, returning label metadata."""
    affected: set[str] = set()
    quality = "GOOD"
    kind = event.type
    fraction = min(1.0, max(0.0, (seconds - event.start) / max(event.duration, 1)))
    p = event.parameters
    # Severity scales configured continuous magnitudes and probabilities.
    # Full-severity outages retain their categorical behavior.
    severity_scale = float(np.clip(event.severity, 0.0, 1.0))
    def draw_for(signal: str, label: str) -> float:
        token = f"{run_seed}|{event.asset}|{signal}|{sample_index}|{event.start}|{label}".encode()
        return int(hashlib.sha256(token).hexdigest()[:8], 16) / 0x100000000
    def pick(*names: str) -> list[str]:
        return [name for name in signals if name in names or any(fragment in name for fragment in names)]
    if kind == "bearing_degradation":
        vib = pick("vibration_mm_s", "spindle_vibration_mm_s")
        temp = pick("motor_temperature_c", "spindle_temperature_c")
        progression = str(p.get("progression", "linear"))
        progress = fraction if progression == "linear" else min(1.0, fraction**2) if progression == "slow_start" else fraction**0.5 if progression == "fast_start" else None
        if progress is None:
            raise ValueError(f"unsupported bearing progression {progression!r}")
        affected.update(vib + temp)
        gain = float(p.get("vibration_gain", 0.20)) * progress * severity_scale
        tgain = float(p.get("temperature_gain", 0.08)) * progress * severity_scale
        for name in vib:
            signals[name] *= 1 + gain
        for name in temp:
            signals[name] += 15 * tgain
    elif kind == "cavitation":
        for name in pick("vibration_mm_s", "spindle_vibration_mm_s"):
            signals[name] += float(p.get("vibration_gain", 0.8)) * fraction * severity_scale
            affected.add(name)
        for name in pick("flow_l_min"):
            signals[name] *= 1 - float(p.get("flow_loss", 0.12)) * fraction * severity_scale
            affected.add(name)
        for name in pick("pressure_bar", "coolant_pressure_bar"):
            signals[name] *= 1 - float(p.get("pressure_loss", 0.10)) * fraction * severity_scale
            affected.add(name)
        for name in pick("motor_current_a"):
            signals[name] *= 1 + float(p.get("current_gain", 0.05)) * fraction * severity_scale
            affected.add(name)
    elif kind == "cooling_degradation":
        for name in pick("temperature_c", "oil_temperature_c", "discharge_temperature_c", "spindle_temperature_c"):
            signals[name] += float(p.get("temperature_gain", 0.08)) * 35 * fraction * severity_scale
            affected.add(name)
    elif kind == "mechanical_overload":
        for name in pick("motor_current_a", "spindle_power_kw"):
            signals[name] *= 1 + float(p.get("current_gain", 0.12)) * fraction * severity_scale
            affected.add(name)
        for name in pick("vibration_mm_s"):
            signals[name] *= 1 + float(p.get("vibration_gain", 0.20)) * fraction * severity_scale
            affected.add(name)
    elif kind == "sensor_drift":
        names = [str(p["signal"])] if "signal" in p else list(signals)
        if any(name not in signals for name in names):
            raise ValueError("sensor_drift references a signal absent from the target asset")
        for name in names:
            if name in signals:
                signals[name] += float(p.get("rate_per_minute", 0.5)) * severity_scale * (seconds - event.start) / 60
                affected.add(name)
    elif kind == "sensor_bias":
        names = [str(p["signal"])] if "signal" in p else list(signals)
        if any(name not in signals for name in names):
            raise ValueError("sensor_bias references a signal absent from the target asset")
        for name in names:
            if name in signals:
                signals[name] += float(p.get("bias", 1.0)) * severity_scale
                affected.add(name)
    elif kind == "sudden_spike":
        names = [str(p["signal"])] if "signal" in p else [next(iter(signals))]
        if any(name not in signals for name in names):
            raise ValueError("sudden_spike references a signal absent from the target asset")
        for name in names:
            if name in signals:
                signals[name] += float(p.get("magnitude", 5.0)) * severity_scale
                affected.add(name)
    elif kind == "sensor_stuck":
        names = [str(p["signal"])] if "signal" in p else [next(iter(signals))]
        if any(name not in signals for name in names):
            raise ValueError("sensor_stuck references a signal absent from the target asset")
        state = states.setdefault("__sensor_stuck", ProcessState())
        for name in names:
            if name in signals:
                held_key = f"sensor_stuck:{event_id}:{name}"
                state.previous_signals.setdefault(held_key, signals[name])
                signals[name] = signals[name] * (1 - severity_scale) + state.previous_signals[held_key] * severity_scale
                if severity_scale > 0:
                    affected.add(name)
        states["__sensor_stuck"] = state
        if severity_scale > 0:
            quality = "UNCERTAIN"
    elif kind == "single_signal_loss":
        names = _select_loss_signals(signals, p, run_seed, event, sample_index, force_single=True)
        if any(name not in signals for name in names):
            raise ValueError("single_signal_loss references a signal absent from the target asset")
        loss_pct = float(p.get("loss_pct", 100))
        if not 0 <= loss_pct <= 100:
            raise ValueError("loss_pct must be within 0..100")
        for name in names:
            if draw_for(name, "single-signal-loss") < loss_pct * severity_scale / 100:
                signals.pop(name, None)
                affected.add(name)
    elif kind == "asset_communication_loss":
        loss_pct = float(p.get("loss_pct", 100))
        if not 0 <= loss_pct <= 100:
            raise ValueError("loss_pct must be within 0..100")
        for name in list(signals):
            if draw_for(name, "asset-communication-loss") < loss_pct * severity_scale / 100:
                signals.pop(name, None)
                affected.add(name)
    elif kind == "missing_telemetry":
        loss_pct = float(p.get("loss_pct", 100 if kind == "asset_communication_loss" else 25))
        if not 0 <= loss_pct <= 100:
            raise ValueError("loss_pct must be within 0..100")
        loss_pct *= severity_scale
        candidates = _select_loss_signals(signals, p, run_seed, event, sample_index)
        if loss_pct >= 100:
            affected.update(candidates)
            for name in candidates:
                signals.pop(name, None)
        else:
            for name in candidates:
                # Stable hashed selection per timestamp, no hidden state or extra RNG consumption.
                if draw_for(name, "missing-telemetry") < loss_pct / 100:
                    affected.add(name)
                    signals.pop(name)
    elif kind == "quality_degradation":
        if draw_for("__asset__", "quality-degradation") < severity_scale:
            quality = "BAD"
            affected.update(signals)
    elif kind == "regime_mismatch":
        targets = pick("load_pct", "spindle_power_kw", "motor_current_a", "feed_rate")
        for name in targets:
            signals[name] *= 1 - (1 - float(p.get("load_multiplier", 0.7))) * severity_scale
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
                signals[name] = lo + (pct * severity_scale) * (hi - lo)
                affected.add(name)
        else:
            # High-normal thermal/vibration values paired with low-normal power/current.
            for name in pick("temperature_c", "oil_temperature_c", "spindle_temperature_c"):
                _, _, lo, hi = signal_metadata(asset_class)[name]
                signals[name] = float(np.clip(signals[name] + severity_scale * max(0, lo + 0.78 * (hi - lo) - signals[name]), lo, hi))
                affected.add(name)
            for name in pick("vibration_mm_s", "spindle_vibration_mm_s"):
                _, _, lo, hi = signal_metadata(asset_class)[name]
                signals[name] = float(np.clip(signals[name] + severity_scale * max(0, lo + 0.75 * (hi - lo) - signals[name]), lo, hi))
                affected.add(name)
            for name in pick("spindle_power_kw", "motor_current_a"):
                bounds = signal_metadata(asset_class)[name]
                target = bounds[2] + 0.25 * (bounds[3] - bounds[2])
                signals[name] = float(np.clip(signals[name] + severity_scale * min(0, target - signals[name]), bounds[2], bounds[3]))
                affected.add(name)
    elif kind == "maintenance_activity":
        for name in pick("motor_current_a", "spindle_power_kw", "load_pct"):
            signals[name] *= 1 - (1 - float(p.get("load_multiplier", 0.1))) * severity_scale
            affected.add(name)
    return signals, affected, quality


def _select_loss_signals(
    signals: dict[str, float], parameters: dict[str, Any], run_seed: int, event: Any,
    sample_index: int, force_single: bool = False,
) -> list[str]:
    """Resolve an explicit tag list or a deterministic tag-selection policy."""
    available = list(signals)
    if "signal" in parameters:
        names = [str(parameters["signal"])]
    elif "signals" in parameters:
        raw = parameters["signals"]
        if not isinstance(raw, list) or any(not isinstance(name, str) for name in raw):
            raise ValueError("signals must be a list of tag names")
        names = list(dict.fromkeys(raw))
    else:
        mode = "single" if force_single else str(parameters.get("tag_selection", "all"))
        if mode not in {"all", "single", "multiple"}:
            raise ValueError("tag_selection must be all, single, or multiple")
        if mode == "all":
            names = available
        else:
            count = 1 if mode == "single" or force_single else int(parameters.get("tag_count", 2))
            if count < 1 or count > len(available):
                raise ValueError("tag_count must be between 1 and the number of available signals")
            token = f"{run_seed}|{event.asset}|{event.start}|tag-selection".encode()
            rng = np.random.default_rng(int(hashlib.sha256(token).hexdigest()[:16], 16))
            names = [available[index] for index in sorted(rng.choice(len(available), size=count, replace=False).tolist())]
    if not names:
        raise ValueError("at least one signal must be selected")
    unknown = set(names) - set(available)
    if unknown:
        raise ValueError(f"loss scenario references unknown signals: {', '.join(sorted(unknown))}")
    return names


def simulate(scenario: Scenario, seed: int) -> tuple[pl.DataFrame, dict[str, Any], dict[str, Any]]:
    rng = np.random.default_rng(seed)
    origin = EPOCH
    rows: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    affected_by_event: dict[str, set[str]] = {}
    regime_intervals: list[dict[str, str]] = []
    active_regimes: dict[str, dict[str, str]] = {}
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
        affected_by_event[f"evt-{index}"] = set()
    step_ms = scenario.sampling_interval_ms
    n_steps = int(scenario.duration_s * 1000 / step_ms)
    states = {
        asset.asset_id: ProcessState(
            temperature=scenario.ambient_temperature_c + asset.process_parameters.get("initial_temperature_offset_c", 0.0)
        )
        for asset in scenario.assets
    }
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
            regime_timestamp = origin + timedelta(seconds=seconds)
            active_regime = active_regimes.get(asset.asset_id)
            if active_regime is None or active_regime["regime"] != regime:
                if active_regime is not None:
                    active_regime["end"] = regime_timestamp.isoformat()
                active_regime = {"asset_id": asset.asset_id, "regime": regime, "start": regime_timestamp.isoformat(), "end": regime_timestamp.isoformat()}
                active_regimes[asset.asset_id] = active_regime
                regime_intervals.append(active_regime)
            else:
                active_regime["end"] = regime_timestamp.isoformat()
            ambient = scenario.ambient_temperature_c + scenario.ambient_temperature_drift_c * seconds / max(scenario.duration_s, 1)
            signals = simulate_step(asset, state, regime, step_ms / 1000, ambient, rng)
            quality_by_signal = {name: "GOOD" for name in signals}
            active_events: list[Any] = []
            for anomaly in scenario.anomalies:
                if anomaly.asset == asset.asset_id and _event_active(anomaly, seconds):
                    active_events.append(anomaly)
                    before = set(signals)
                    event_index = scenario.anomalies.index(anomaly) + 1
                    signals, affected, quality = _affect(anomaly, signals, seconds, states, asset.asset_class, step, seed, f"evt-{event_index}")
                    event_record = next(e for e in events if e["event_id"] == f"evt-{event_index}")
                    affected_by_event[event_record["event_id"]].update(affected)
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
                if event_record["severity"] > 0:
                    event_record.setdefault("observed_start", timestamp.isoformat())
                    event_record["observed_end"] = timestamp.isoformat()
    run_end = (origin + timedelta(seconds=scenario.duration_s)).isoformat()
    for active_regime in active_regimes.values():
        active_regime["end"] = run_end
    for event in events:
        event["affected_signals"] = sorted(affected_by_event[event["event_id"]])
    telemetry = pl.DataFrame(rows, schema={
        "schema_version": pl.String, "run_id": pl.String,
        "timestamp": pl.Datetime("ms", "UTC"), "asset_id": pl.String,
        "asset_class": pl.String, "tag_id": pl.String, "signal_class": pl.String,
        "value": pl.Float64, "unit": pl.String, "quality": pl.String,
        "sampling_interval_ms": pl.Int64, "operating_regime": pl.String,
        "engineering_min": pl.Float64, "engineering_max": pl.Float64,
        "protocol": pl.String, "device_id": pl.String, "site_id": pl.String,
        "zone_id": pl.String,
    })
    ground_truth = {
        "ground_truth_schema_version": GROUND_TRUTH_SCHEMA_VERSION,
        "run_id": scenario.run_id,
        "events": events,
        "operating_regimes": regime_intervals,
    }
    scenario_canonical = json.dumps(scenario.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    metadata = {
        "run_id": scenario.run_id, "scenario_id": scenario.scenario_id,
        "scenario_version": scenario.scenario_version, "seed": seed,
        "simulator_version": __version__, "schema_version": SCHEMA_VERSION,
        "ground_truth_schema_version": GROUND_TRUTH_SCHEMA_VERSION,
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


def batch(suite_path: Path, runs: int, output: Path, seed: int, resume: bool = False, workers: int = 1) -> None:
    if runs <= 0:
        raise ValueError("runs must be positive")
    if workers <= 0:
        raise ValueError("workers must be positive")
    if workers > (os.cpu_count() or 1):
        raise ValueError(f"workers cannot exceed available CPU count ({os.cpu_count() or 1})")
    if resume:
        _resume_batch(suite_path, runs, output, seed, workers)
        return
    if output.exists():
        raise FileExistsError(f"dataset output path must not already exist: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f".{output.name}.tmp-", dir=output.parent) as staging_root:
        staging_output = Path(staging_root) / output.name
        _batch_to_directory(suite_path, runs, staging_output, seed, command_output=output, workers=workers)
        staging_output.replace(output)


def _resume_batch(suite_path: Path, runs: int, output: Path, seed: int, workers: int = 1) -> None:
    """Continue a checkpointed batch in deterministic run order; publish only when complete."""
    if runs <= 0:
        raise ValueError("runs must be positive")
    if output.exists() and not output.is_dir():
        raise FileExistsError(f"dataset output path is not a directory: {output}")
    output.mkdir(parents=True, exist_ok=True)
    config = {
        "suite_sha256": hashlib.sha256(suite_path.read_bytes()).hexdigest(),
        "runs": runs,
        "seed": seed,
        "simulator_version": __version__,
        "schema_version": SCHEMA_VERSION,
    }
    config_path = output / ".resume.json"
    if config_path.exists():
        existing = json.loads(config_path.read_text(encoding="utf-8"))
        if {key: value for key, value in existing.items() if key != "workers"} != config:
            raise ValueError("resume configuration differs from checkpoint; use a fresh output directory")
        existing.setdefault("workers", workers)
        config_path.write_text(json.dumps(existing, indent=2) + "\n", encoding="utf-8")
    else:
        if any(output.iterdir()):
            raise FileExistsError(f"resume output contains files but no compatible checkpoint: {output}")
        config_path.write_text(json.dumps({**config, "workers": workers}, indent=2) + "\n", encoding="utf-8")
    suite = yaml.safe_load(suite_path.read_text(encoding="utf-8"))
    partitions = suite.get("partitions", {"train": 0.7, "validation": 0.15, "test": 0.15})
    if "challenge" in {name.lower() for name in partitions}:
        raise ValueError("challenge partitions must use ephemeral challenge generation")
    if not {"train", "validation", "test"}.issubset(partitions):
        raise ValueError("partitions must define train, validation, and test")
    if any(not np.isfinite(value) or value < 0 for value in partitions.values()) or abs(sum(partitions.values()) - 1.0) > 1e-9:
        raise ValueError("partition fractions must be finite, non-negative, and sum to 1")
    counts = {key: int(runs * value) for key, value in partitions.items()}
    counts[list(partitions)[-1]] += runs - sum(counts.values())
    seed_rng = np.random.default_rng(seed)
    used_seeds: set[int] = set()
    run_specs: list[tuple[str, int, str, int]] = []
    for partition, count in counts.items():
        for index in range(count):
            run_seed = int(seed_rng.integers(0, 2**63, dtype=np.int64))
            while run_seed in used_seeds:
                run_seed = int(seed_rng.integers(0, 2**63, dtype=np.int64))
            used_seeds.add(run_seed)
            run_specs.append((partition, index, f"{partition}-{index+1:05d}", run_seed))
    tasks = []
    for partition, index, run_id, run_seed in run_specs:
        run_dir = output / partition / run_id
        if all((run_dir / name).is_file() for name in ("run_metadata.json", "ground_truth.json", "telemetry.parquet", "scenario.yaml")):
            metadata = json.loads((run_dir / "run_metadata.json").read_text(encoding="utf-8"))
            if metadata.get("seed") != run_seed:
                raise ValueError(f"checkpoint run seed mismatch: {run_dir}")
            continue
        if run_dir.exists():
            shutil.rmtree(run_dir)
        local_rng = np.random.default_rng(run_seed)
        base = suite["scenario"]
        generation = suite.get("generation", {})
        scenario_data = _generate_suite_scenario(base, generation, local_rng, run_id) if generation else json.loads(json.dumps(base))
        scenario_data["run_id"] = run_id
        scenario_data = _resolve_ranges(scenario_data, local_rng)
        scenario_data["run_id"] = run_id
        scenario = Scenario.model_validate(resolve_profiles(scenario_data))
        tasks.append((scenario.model_dump(mode="json"), run_seed, str(run_dir)))
    if workers == 1:
        for task in tasks:
            _write_batch_run(*task)
    else:
        with ProcessPoolExecutor(max_workers=workers) as executor:
            list(executor.map(_write_batch_run_star, tasks, chunksize=max(1, len(tasks) // (workers * 4))))
    # Finalizing reuses the normal manifest and partition builder, then removes only temporary state.
    _finalize_resumable_batch(suite_path, runs, output, seed, workers)


def _finalize_resumable_batch(suite_path: Path, runs: int, output: Path, seed: int, workers: int = 1) -> None:
    """Build final files in a sibling staging directory, then atomically replace the checkpoint."""
    import shutil

    staging = Path(tempfile.mkdtemp(prefix=f".{output.name}.finalize-", dir=output.parent))
    try:
        for path in output.iterdir():
            if path.name == ".resume.json":
                continue
            target = staging / path.name
            if path.is_dir():
                shutil.copytree(path, target)
            else:
                shutil.copy2(path, target)
        _batch_to_directory(
            suite_path, runs, staging, seed, command_output=output,
            resume_existing=True, dataset_id=output.name,
            workers=workers,
        )
        (staging / ".resume.json").unlink(missing_ok=True)
        backup = output.with_name(f".{output.name}.checkpoint")
        if backup.exists():
            shutil.rmtree(backup)
        output.replace(backup)
        try:
            staging.replace(output)
        except Exception:
            backup.replace(output)
            raise
        shutil.rmtree(backup)
    finally:
        if staging.exists():
            shutil.rmtree(staging)


def _write_batch_run(scenario_data: dict[str, Any], run_seed: int, run_dir_text: str) -> None:
    """Write one isolated, already-resolved run; safe to dispatch to worker processes."""
    scenario = Scenario.model_validate(scenario_data)
    write_run(scenario, run_seed, Path(run_dir_text))


def _write_batch_run_star(args: tuple[dict[str, Any], int, str]) -> None:
    _write_batch_run(*args)


def _batch_to_directory(
    suite_path: Path, runs: int, output: Path, seed: int,
    command_output: Path | None = None, resume_existing: bool = False,
    dataset_id: str | None = None, workers: int = 1,
) -> None:
    if runs <= 0:
        raise ValueError("runs must be positive")
    if workers <= 0:
        raise ValueError("workers must be positive")
    if workers > (os.cpu_count() or 1):
        raise ValueError(f"workers cannot exceed available CPU count ({os.cpu_count() or 1})")
    output.mkdir(parents=True, exist_ok=True)
    suite = yaml.safe_load(suite_path.read_text(encoding="utf-8"))
    base = suite["scenario"]
    generation = suite.get("generation", {})
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
    partition_class_distribution = {partition: {"normal": 0, "anomalous": 0} for partition in partitions}
    asset_distribution: dict[str, int] = {}
    event_distribution: dict[str, int] = {}
    event_distribution_by_partition = {partition: {} for partition in partitions}
    regime_distribution: dict[str, int] = {}
    regime_duration_s: dict[str, float] = {}
    observation_total = 0
    tasks = []
    for partition, count in counts.items():
        for index in range(count):
            run_seed = int(seed_rng.integers(0, 2**63, dtype=np.int64))
            while run_seed in used_seeds:
                run_seed = int(seed_rng.integers(0, 2**63, dtype=np.int64))
            used_seeds.add(run_seed)
            local_rng = np.random.default_rng(run_seed)
            run_id = f"{partition}-{index+1:05d}"
            if generation:
                scenario_data = _generate_suite_scenario(base, generation, local_rng, run_id)
            else:
                scenario_data = json.loads(json.dumps(base))
                scenario_data["run_id"] = run_id
            scenario_data = _resolve_ranges(scenario_data, local_rng)
            scenario_data["run_id"] = run_id
            scenario = Scenario.model_validate(resolve_profiles(scenario_data))
            run_dir = output / partition / scenario.run_id
            is_complete = all((run_dir / name).is_file() for name in ("run_metadata.json", "ground_truth.json", "telemetry.parquet", "scenario.yaml"))
            if resume_existing and is_complete:
                metadata = json.loads((run_dir / "run_metadata.json").read_text(encoding="utf-8"))
                expected_hash = hashlib.sha256(json.dumps(scenario.model_dump(mode="json"), sort_keys=True, separators=(",", ":")).encode()).hexdigest()
                if metadata.get("seed") != run_seed or metadata.get("scenario_sha256") != expected_hash:
                    raise ValueError(f"checkpoint run does not match deterministic scenario: {run_dir}")
            else:
                if run_dir.exists():
                    shutil.rmtree(run_dir)
                tasks.append((scenario.model_dump(mode="json"), run_seed, str(run_dir)))
            manifest_runs.append({
                "partition": partition, "run_id": scenario.run_id, "seed": run_seed,
                "scenario_id": scenario.scenario_id,
                "scenario_version": scenario.scenario_version,
                "asset_ids": [asset.asset_id for asset in scenario.assets],
                "asset_classes": [asset.asset_class for asset in scenario.assets],
                "configured_shift_pattern": scenario.shift_pattern,
            })
            sample_class = "anomalous" if scenario.anomalies else "normal"
            class_distribution[sample_class] += 1
            partition_class_distribution[partition][sample_class] += 1
            for anomaly in scenario.anomalies:
                event_distribution[anomaly.type] = event_distribution.get(anomaly.type, 0) + 1
                partition_events = event_distribution_by_partition[partition]
                partition_events[anomaly.type] = partition_events.get(anomaly.type, 0) + 1
            for asset in scenario.assets:
                asset_distribution[asset.asset_class] = asset_distribution.get(asset.asset_class, 0) + 1
    if tasks:
        if workers == 1:
            for scenario_data, run_seed, run_dir_text in tasks:
                _write_batch_run(scenario_data, run_seed, run_dir_text)
        else:
            with ProcessPoolExecutor(max_workers=workers) as executor:
                list(executor.map(_write_batch_run_star, tasks, chunksize=max(1, len(tasks) // (workers * 4))))
    for run in manifest_runs:
        run_dir = output / run["partition"] / run["run_id"]
        run_meta = json.loads((run_dir / "run_metadata.json").read_text(encoding="utf-8"))
        run["observation_count"] = run_meta["observation_count"]
        run["scenario_sha256"] = run_meta["scenario_sha256"]
        run["ground_truth_sha256"] = hashlib.sha256((run_dir / "ground_truth.json").read_bytes()).hexdigest()
        run["metadata_sha256"] = hashlib.sha256((run_dir / "run_metadata.json").read_bytes()).hexdigest()
        run["telemetry_sha256"] = hashlib.sha256((run_dir / "telemetry.parquet").read_bytes()).hexdigest()
        observation_total += run_meta["observation_count"]
        truth = json.loads((run_dir / "ground_truth.json").read_text(encoding="utf-8"))
        for interval in truth.get("operating_regimes", []):
            regime = interval["regime"]
            regime_distribution[regime] = regime_distribution.get(regime, 0) + 1
            elapsed = (datetime.fromisoformat(interval["end"]) - datetime.fromisoformat(interval["start"])).total_seconds()
            regime_duration_s[regime] = regime_duration_s.get(regime, 0.0) + max(0.0, elapsed)
    partition_files: dict[str, dict[str, Any]] = {}
    for partition in partitions:
        partition_runs = [run for run in manifest_runs if run["partition"] == partition]
        if partition_runs:
            partition_path = output / f"{partition}.parquet"
            telemetry_paths = [str(output / partition / run["run_id"] / "telemetry.parquet") for run in partition_runs]
            pl.scan_parquet(telemetry_paths).sink_parquet(partition_path, compression="zstd", statistics=True)
            partition_files[partition] = {
                "path": partition_path.name,
                "sha256": hashlib.sha256(partition_path.read_bytes()).hexdigest(),
                "observation_count": sum(run["observation_count"] for run in partition_runs),
            }
        else:
            partition_files[partition] = {"path": None, "sha256": None, "observation_count": 0}
    lockfile = Path(__file__).resolve().parents[2] / "uv.lock"
    manifest = {
        "manifest_version": "1.0.0",
        "dataset_id": dataset_id or output.name, "suite_id": suite.get("suite_id", suite_path.stem),
        "suite_version": suite.get("suite_version", "1.0.0"),
        "data_license": suite.get("data_license"),
        "suite_sha256": hashlib.sha256(suite_path.read_bytes()).hexdigest(),
        "simulator_version": __version__, "schema_version": SCHEMA_VERSION,
        "ground_truth_schema_version": GROUND_TRUTH_SCHEMA_VERSION, "master_seed": seed,
        "generation_workers": workers,
        "generator_argv": [
            "uv", "run", "ot-lab", "dataset", "create", "--suite", str(suite_path),
            "--runs", str(runs), "--seed", str(seed), "--workers", str(workers), "--output", str(command_output or output),
        ],
        "uv_lock_sha256": hashlib.sha256(lockfile.read_bytes()).hexdigest() if lockfile.is_file() else None,
        "runtime": {"python": platform.python_version(), "numpy": np.__version__, "polars": pl.__version__},
        "run_count": runs, "observation_count": observation_total,
        "partition_counts": counts, "runs": manifest_runs,
        "partition_files": partition_files,
        "class_distribution": class_distribution,
        "class_distribution_by_partition": partition_class_distribution,
        "asset_distribution": asset_distribution,
        "event_distribution": event_distribution,
        "event_distribution_by_partition": event_distribution_by_partition,
        "regime_episode_distribution": regime_distribution,
        "regime_duration_s": regime_duration_s,
        "generation_complete": True,
        "synthetic": True, "generated": True, "customer_data": False,
    }
    (output / "dataset_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    (output / "suite.yaml").write_bytes(suite_path.read_bytes())


def generate_challenge(suite_path: Path, output: Path, master_seed: int | None = None, challenge_suite_path: Path | None = None) -> tuple[Path, Path]:
    """Generate an ephemeral case, optionally using a separate challenge distribution."""
    suite = yaml.safe_load(suite_path.read_text(encoding="utf-8"))
    challenge_suite = yaml.safe_load(challenge_suite_path.read_text(encoding="utf-8")) if challenge_suite_path else suite
    seed = int(np.random.SeedSequence().generate_state(1, dtype=np.uint64)[0]) if master_seed is None else master_seed
    case_dir = output / "case"
    base = json.loads(json.dumps(challenge_suite["scenario"]))
    generation = challenge_suite.get("generation", {})
    # A fixed opaque ID prevents the model input from revealing the hidden seed.
    run_id = "challenge-hidden"
    if generation:
        generation["anomaly_probability"] = 1.0
        scenario_data = _generate_suite_scenario(base, generation, np.random.default_rng(seed), run_id)
    else:
        scenario_data = base
    scenario_data["run_id"] = run_id
    rng = np.random.default_rng(seed)
    scenario_data = _resolve_ranges(scenario_data, rng)
    scenario_data["run_id"] = run_id
    scenario_data = resolve_profiles(scenario_data)
    scenario = Scenario.model_validate(scenario_data)
    write_run(scenario, seed, case_dir, persist_scenario=False)
    # Hidden seed and resolved scenario are not persisted in a challenge case.
    metadata_path = case_dir / "run_metadata.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata.pop("seed", None)
    metadata.pop("scenario_sha256", None)
    metadata.pop("scenario_id", None)
    metadata.pop("scenario_version", None)
    metadata_path.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    truth_path = case_dir / "ground_truth.json"
    truth = json.loads(truth_path.read_text(encoding="utf-8"))
    for event in truth["events"]:
        event.pop("parameters", None)
        event.pop("observed_start", None)
        event.pop("observed_end", None)
    truth_path.write_text(json.dumps(truth, indent=2) + "\n", encoding="utf-8")
    # The local evaluator receives truth only after the model has exited; seed is held in memory, not written.
    return case_dir, case_dir / "ground_truth.json"
