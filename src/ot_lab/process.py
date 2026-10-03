"""Coupled, deliberately simple process models for four common asset classes."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from .models import AssetSpec, Regime


SIGNAL_META: dict[str, dict[str, tuple[str, float, float]]] = {
    "cnc": {
        "spindle_rpm": ("rotational_speed", "rpm", 0, 12000),
        "spindle_power_kw": ("power", "kW", 0, 30),
        "spindle_temperature_c": ("temperature", "degC", 0, 120),
        "spindle_vibration_mm_s": ("vibration", "mm/s", 0, 25),
        "feed_rate": ("feed_rate", "mm/min", 0, 5000),
        "coolant_pressure_bar": ("pressure", "bar", 0, 10),
        "cycle_state": ("state", "code", 0, 4),
    },
    "pump": {
        "rpm": ("rotational_speed", "rpm", 0, 3600),
        "motor_current_a": ("current", "A", 0, 100),
        "motor_temperature_c": ("temperature", "degC", 0, 120),
        "vibration_mm_s": ("vibration", "mm/s", 0, 25),
        "flow_l_min": ("flow", "L/min", 0, 3000),
        "pressure_bar": ("pressure", "bar", 0, 30),
    },
    "compressor": {
        "motor_current_a": ("current", "A", 0, 160),
        "oil_temperature_c": ("temperature", "degC", 0, 150),
        "discharge_temperature_c": ("temperature", "degC", 0, 220),
        "pressure_bar": ("pressure", "bar", 0, 20),
        "vibration_mm_s": ("vibration", "mm/s", 0, 25),
        "load_pct": ("load", "%", 0, 100),
    },
    "conveyor": {
        "motor_current_a": ("current", "A", 0, 100),
        "motor_temperature_c": ("temperature", "degC", 0, 120),
        "speed_m_s": ("speed", "m/s", 0, 10),
        "vibration_mm_s": ("vibration", "mm/s", 0, 25),
        "load_pct": ("load", "%", 0, 100),
        "photoeye_rate": ("count_rate", "count/min", 0, 500),
    },
}

REGIME_LOAD = {
    "OFF": 0.0, "IDLE": 0.08, "WARMUP": 0.15, "LOW_LOAD": 0.3,
    "NORMAL_LOAD": 0.58, "HIGH_LOAD": 0.86, "COOLDOWN": 0.12,
    "MAINTENANCE": 0.04,
}


@dataclass
class ProcessState:
    temperature: float = 25.0
    load: float = 0.0
    rpm: float = 0.0
    vibration: float = 0.0
    previous_signals: dict[str, float] = field(default_factory=dict)


def regime_at(t: float, duration: float, regimes: list[Regime]) -> Regime:
    """Select repeatable operating phases, including warmup and cooldown."""
    available = [r for r in regimes if r != "OFF" and r != "MAINTENANCE"]
    if not available:
        return "IDLE"
    fraction = t / max(duration, 1)
    if fraction < 0.08:
        return "WARMUP" if "WARMUP" in available else available[0]
    if fraction > 0.93:
        return "COOLDOWN" if "COOLDOWN" in available else available[-1]
    # A deterministic recipe/load change every quarter of a run.
    phase = int(fraction * 4) % 4
    preferred = ["LOW_LOAD", "NORMAL_LOAD", "HIGH_LOAD", "NORMAL_LOAD"][phase]
    return preferred if preferred in available else available[min(phase, len(available) - 1)]


def _bounded(value: float, low: float, high: float) -> float:
    return float(np.clip(value, low, high))


def simulate_step(
    asset: AssetSpec,
    state: ProcessState,
    regime: Regime,
    dt: float,
    ambient_c: float,
    rng: np.random.Generator,
) -> dict[str, float]:
    """Advance one coupled process step; noise perturbs, never drives, the plant."""
    target = REGIME_LOAD[regime]
    # A first-order actuator response models process lag and loop settling.
    alpha = 1.0 - np.exp(-dt / (3.0 if regime == "WARMUP" else 1.5))
    state.load += (target - state.load) * alpha
    noise = lambda scale: float(rng.normal(0.0, scale))
    cooling = 0.07

    if asset.asset_class == "cnc":
        state.rpm += ((9000 * state.load) - state.rpm) * alpha
        power = 0.8 + 19 * state.load + noise(0.12)
        state.temperature += (ambient_c + 60 * state.load - state.temperature) * (1 - np.exp(-dt / 90))
        vibration = 0.35 + 1.5 * state.load + 0.00004 * state.rpm + noise(0.08)
        result = {
            "spindle_rpm": _bounded(state.rpm + noise(8), 0, 12000),
            "spindle_power_kw": _bounded(power, 0, 30),
            "spindle_temperature_c": _bounded(state.temperature, 0, 120),
            "spindle_vibration_mm_s": _bounded(vibration, 0, 25),
            "feed_rate": _bounded(4000 * state.load + noise(20), 0, 5000),
            "coolant_pressure_bar": _bounded(2 + 4 * state.load + noise(0.08), 0, 10),
            "cycle_state": float(0 if regime in ("OFF", "IDLE", "COOLDOWN") else 1),
        }
    elif asset.asset_class == "pump":
        state.rpm += (3000 * state.load - state.rpm) * alpha
        # Flow follows speed; pressure reflects flow against a simple quadratic system curve.
        flow = 2500 * state.rpm / 3000 * (1 - 0.20 * state.load)
        pressure = max(0, 8 + 12 * (state.rpm / 3000) - 5 * state.load)
        current = 4 + 56 * state.load + 0.012 * pressure + noise(0.4)
        state.temperature += (ambient_c + 45 * state.load - state.temperature) * (1 - np.exp(-dt / 100))
        result = {
            "rpm": _bounded(state.rpm + noise(5), 0, 3600),
            "motor_current_a": _bounded(current, 0, 100),
            "motor_temperature_c": _bounded(state.temperature, 0, 120),
            "vibration_mm_s": _bounded(0.35 + 1.3 * state.load + 0.0003 * state.rpm + noise(0.08), 0, 25),
            "flow_l_min": _bounded(flow + noise(10), 0, 3000),
            "pressure_bar": _bounded(pressure + noise(0.12), 0, 30),
        }
    elif asset.asset_class == "compressor":
        load = state.load
        state.temperature += (ambient_c + 80 * load - state.temperature) * (1 - np.exp(-dt / 120))
        discharge = ambient_c + 20 + 130 * load
        result = {
            "motor_current_a": _bounded(8 + 90 * load + noise(0.6), 0, 160),
            "oil_temperature_c": _bounded(state.temperature, 0, 150),
            "discharge_temperature_c": _bounded(discharge + noise(0.5), 0, 220),
            "pressure_bar": _bounded(2 + 12 * load + noise(0.15), 0, 20),
            "vibration_mm_s": _bounded(0.4 + 1.4 * load + noise(0.08), 0, 25),
            "load_pct": _bounded(100 * load + noise(1), 0, 100),
        }
    else:
        load = state.load
        state.temperature += (ambient_c + 48 * load - state.temperature) * (1 - np.exp(-dt / 100))
        speed = 2.2 * load
        result = {
            "motor_current_a": _bounded(3 + 55 * load + noise(0.4), 0, 100),
            "motor_temperature_c": _bounded(state.temperature, 0, 120),
            "speed_m_s": _bounded(speed + noise(0.03), 0, 10),
            "vibration_mm_s": _bounded(0.3 + 1.5 * load + noise(0.08), 0, 25),
            "load_pct": _bounded(100 * load + noise(1), 0, 100),
            "photoeye_rate": _bounded(180 * speed * load + noise(2), 0, 500),
        }
    state.previous_signals = result.copy()
    return result


def signal_metadata(asset_class: str) -> dict[str, tuple[str, str, float, float]]:
    return {name: (meta[0], meta[1], meta[2], meta[3]) for name, meta in SIGNAL_META[asset_class].items()}
