"""Coupled, deliberately simple process models for four common asset classes."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .models import AssetSpec, Regime

SIGNAL_META: dict[str, dict[str, tuple[str, str, float, float]]] = {
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
    previous_regime: Regime | None = None


def regime_at(t: float, duration: float, regimes: list[Regime], shift_pattern: list[Regime] | None = None) -> Regime:
    """Select repeatable operating phases, including warmup and cooldown."""
    available = [r for r in regimes if r != "OFF" and r != "MAINTENANCE"]
    fraction = t / max(duration, 1)
    if shift_pattern:
        if fraction < 0.08 and "WARMUP" in regimes:
            return "WARMUP"
        if fraction > 0.93 and "COOLDOWN" in regimes:
            return "COOLDOWN"
        operational_fraction = (fraction - 0.08) / 0.85
        phase = min(int(operational_fraction * len(shift_pattern)), len(shift_pattern) - 1)
        requested = shift_pattern[phase]
        if requested in regimes:
            return requested
        if "NORMAL_LOAD" in regimes:
            return "NORMAL_LOAD"
        if not available:
            return regimes[0] if regimes else "IDLE"
        return available[phase % len(available)]
    if not available:
        return regimes[0] if regimes else "IDLE"
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
    parameters = asset.process_parameters
    if asset.asset_class == "pump" and asset.process_profile == "centrifugal_vfd":
        target = float(np.clip(REGIME_LOAD[regime] * parameters.get("load_scale", 1.0), 0.0, 1.0))
        actuator_tau = parameters.get("actuator_tau_s", 3.0 if regime == "WARMUP" else 1.5)
        alpha = 1.0 - np.exp(-dt / actuator_tau)
        state.load += (target - state.load) * alpha
        result = _simulate_centrifugal_vfd(asset, state, regime, dt, ambient_c, rng)
        state.previous_signals = result.copy()
        return result
    target = float(np.clip(REGIME_LOAD[regime] * parameters.get("load_scale", 1.0), 0.0, 1.0))
    # A first-order actuator response models process lag and loop settling.
    actuator_tau = parameters.get("actuator_tau_s", 3.0 if regime == "WARMUP" else 1.5)
    alpha = 1.0 - np.exp(-dt / actuator_tau)
    noise_scale = parameters.get("sensor_noise_scale", 1.0)
    thermal_scale = parameters.get("thermal_time_constant_scale", 1.0)
    state.load += (target - state.load) * alpha
    noise = lambda scale: float(rng.normal(0.0, scale * noise_scale))
    if asset.asset_class == "cnc":
        state.rpm += ((9000 * state.load) - state.rpm) * alpha
        power = 0.8 + 19 * state.load + noise(0.12)
        state.temperature += (ambient_c + 60 * state.load - state.temperature) * (1 - np.exp(-dt / (90 * thermal_scale)))
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
        state.temperature += (ambient_c + 45 * state.load - state.temperature) * (1 - np.exp(-dt / (100 * thermal_scale)))
        result = {
            "rpm": _bounded(state.rpm + noise(5), 0, 3600),
            "motor_current_a": _bounded(current, 0, 100),
            "motor_temperature_c": _bounded(state.temperature, 0, 120),
            "vibration_mm_s": _bounded(0.35 + 1.3 * state.load + 0.0003 * state.rpm + noise(0.08), 0, 25),
            "flow_l_min": _bounded(flow + noise(10), 0, 3000),
            "pressure_bar": _bounded(pressure + noise(0.12), 0, 30),
        }
    elif asset.asset_class == "compressor":
        if asset.process_profile == "metropt3_rail_apu":
            return _simulate_metropt3_rail_apu(asset, state, regime, dt, ambient_c, rng)
        load = state.load
        state.temperature += (ambient_c + 80 * load - state.temperature) * (1 - np.exp(-dt / (120 * thermal_scale)))
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
        state.temperature += (ambient_c + 48 * load - state.temperature) * (1 - np.exp(-dt / (100 * thermal_scale)))
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


def _simulate_centrifugal_vfd(
    asset: AssetSpec,
    state: ProcessState,
    regime: Regime,
    dt: float,
    ambient_c: float,
    rng: np.random.Generator,
) -> dict[str, float]:
    """Simplified VFD centrifugal pump at a fixed system duty characteristic.

    Affinity relations set Q proportional to speed, head/pressure to speed
    squared, and hydraulic power to speed cubed. Efficiency is held constant;
    these assumptions are illustrative and are not a pump-specific curve fit.
    """
    parameters = {
        "pump_rated_speed_rpm": 2900.0,
        "pump_rated_flow_l_min": 750.0,
        "pump_rated_pressure_bar": 12.0,
        "pump_total_efficiency": 0.65,
        "pump_supply_voltage_v": 400.0,
        "pump_power_factor": 0.85,
        "pump_idle_current_a": 4.0,
        "pump_temperature_rise_c": 45.0,
        "pump_static_head_fraction": 0.0,
        "pump_shutoff_head_ratio": 1.25,
    }
    parameters.update(asset.process_parameters)
    noise_scale = asset.process_parameters.get("sensor_noise_scale", 1.0)
    thermal_scale = asset.process_parameters.get("thermal_time_constant_scale", 1.0)
    state.rpm = parameters["pump_rated_speed_rpm"] * state.load
    ratio = max(state.rpm, 0.0) / parameters["pump_rated_speed_rpm"]
    rated_flow = parameters["pump_rated_flow_l_min"]
    rated_pressure = parameters["pump_rated_pressure_bar"]
    if asset.process_profile_version == "1.0.0":
        flow_ratio = ratio
        pressure = rated_pressure * ratio**2
    else:
        # Fit a quadratic pump curve through the rated duty point and a
        # configurable shutoff head, then intersect it with the system curve.
        # This captures static head while retaining the affinity-law limit when
        # static_head_fraction is zero. Both curve shape inputs are explicit
        # scenario parameters, not estimates of any particular pump.
        static_head = rated_pressure * parameters["pump_static_head_fraction"]
        shutoff_head = rated_pressure * parameters["pump_shutoff_head_ratio"]
        denominator = shutoff_head - static_head
        available_head = shutoff_head * ratio**2 - static_head
        flow_ratio = float(np.sqrt(max(available_head, 0.0) / denominator))
        pressure = (
            static_head + (rated_pressure - static_head) * flow_ratio**2
            if available_head > 0
            else min(static_head, shutoff_head * ratio**2)
        )
    flow = rated_flow * flow_ratio
    hydraulic_power_kw = flow * pressure / 600.0
    rated_hydraulic_power_kw = rated_flow * rated_pressure / 600.0
    hydraulic_power_ratio = hydraulic_power_kw / rated_hydraulic_power_kw
    electrical_power_w = hydraulic_power_kw * 1000.0 / parameters["pump_total_efficiency"]
    current = parameters["pump_idle_current_a"] + electrical_power_w / (
        3**0.5 * parameters["pump_supply_voltage_v"] * parameters["pump_power_factor"]
    )
    state.temperature += (
        ambient_c + parameters["pump_temperature_rise_c"] * hydraulic_power_ratio - state.temperature
    ) * (1.0 - np.exp(-max(dt, 0.0) / (100.0 * thermal_scale)))
    noise = lambda scale: float(rng.normal(0.0, scale * noise_scale))
    result = {
        "rpm": _bounded(state.rpm + noise(5.0), 0, 5000),
        "motor_current_a": _bounded(current + noise(0.4), 0, 100),
        "motor_temperature_c": _bounded(state.temperature, 0, 120),
        "vibration_mm_s": _bounded(0.35 + 1.2 * ratio + noise(0.08), 0, 25),
        "flow_l_min": _bounded(flow + noise(3.0), 0, 3000),
        "pressure_bar": _bounded(pressure + noise(0.08), 0, 30),
    }
    state.previous_signals = result.copy()
    return result


def _simulate_metropt3_rail_apu(
    asset: AssetSpec,
    state: ProcessState,
    regime: Regime,
    dt: float,
    ambient_c: float,
    rng: np.random.Generator,
) -> dict[str, float]:
    """Illustrative APU profile bounded to MetroPT-3's observed envelopes.

    Digital regimes stand in for the dataset's ambiguous COMP/DV state labels;
    they do not claim to reconstruct the original control logic or dynamics.
    """
    parameters = {
        "load_tau_s": 8.0,
        "current_loaded_base_a": 4.76,
        "current_loaded_span_a": 1.44,
        "current_start_a": 9.0,
        "current_unloaded_a": 4.0,
        "current_off_a": 0.04,
        "current_noise_a": 0.35,
        "pressure_loaded_min_bar": 7.79,
        "pressure_loaded_span_bar": 2.264,
        "pressure_off_bar": 8.98,
        "pressure_noise_bar": 0.15,
        "oil_temperature_rise_c": 43.9,
        "oil_thermal_tau_s": 900.0,
        "discharge_temperature_rise_c": 20.0,
        "discharge_noise_c": 0.5,
        "vibration_base_mm_s": 0.4,
        "vibration_load_gain_mm_s": 0.8,
        "vibration_noise_mm_s": 0.08,
    }
    parameters.update(asset.process_parameters)
    loaded = regime in {"LOW_LOAD", "NORMAL_LOAD", "HIGH_LOAD"}
    target_load = {"LOW_LOAD": 0.55, "NORMAL_LOAD": 0.72, "HIGH_LOAD": 0.82}.get(regime, 0.0)
    alpha = 1 - np.exp(-max(dt, 0) / parameters["load_tau_s"])
    state.load += (target_load - state.load) * alpha
    if loaded:
        current = parameters["current_loaded_base_a"] + parameters["current_loaded_span_a"] * state.load + float(rng.normal(0, parameters["current_noise_a"]))
        pressure_target = parameters["pressure_loaded_min_bar"] + parameters["pressure_loaded_span_bar"] * state.load
    elif regime == "IDLE" and asset.process_profile_version == "1.1.0":
        # UCI's MetroPT variable description separates stopped (~0 A) from
        # offloaded operation (~4 A); the binary channels do not fully expose it.
        current = parameters["current_unloaded_a"] + float(rng.normal(0, parameters["current_noise_a"]))
        pressure_target = parameters["pressure_off_bar"]
    else:
        current = parameters["current_off_a"] + float(rng.normal(0, parameters["current_noise_a"] * 0.0714286))
        pressure_target = parameters["pressure_off_bar"]
    active_regimes = {"WARMUP", "LOW_LOAD", "NORMAL_LOAD", "HIGH_LOAD"}
    starting = (
        asset.process_profile_version == "1.1.0"
        and regime in active_regimes
        and state.previous_regime not in active_regimes
    )
    if starting:
        # UCI reports approximately 9 A at startup. Its measured cadence cannot
        # resolve transient duration, so v1.1 models one sample at the start
        # peak; the following sample returns to process current.
        current = parameters["current_start_a"]
    # The source supports observed oil-temperature envelopes, not a time constant.
    # This deliberately slow illustrative response is configurable in a future schema.
    state.temperature += (ambient_c + parameters["oil_temperature_rise_c"] - state.temperature) * (1 - np.exp(-max(dt, 0) / parameters["oil_thermal_tau_s"]))
    result = {
        "motor_current_a": _bounded(current, 0, 10),
        "oil_temperature_c": _bounded(state.temperature, 0, 110),
        "discharge_temperature_c": _bounded(ambient_c + parameters["discharge_temperature_rise_c"] + 80 * state.load + rng.normal(0, parameters["discharge_noise_c"]), 0, 160),
        "pressure_bar": _bounded(pressure_target + rng.normal(0, parameters["pressure_noise_bar"]), 0, 15),
        "vibration_mm_s": _bounded(parameters["vibration_base_mm_s"] + parameters["vibration_load_gain_mm_s"] * state.load + rng.normal(0, parameters["vibration_noise_mm_s"]), 0, 10),
        "load_pct": _bounded(100 * state.load + rng.normal(0, 1), 0, 100),
    }
    state.previous_signals = result.copy()
    state.previous_regime = regime
    return result


def signal_metadata(asset_class: str, process_profile: str = "generic") -> dict[str, tuple[str, str, float, float]]:
    result = {name: (meta[0], meta[1], meta[2], meta[3]) for name, meta in SIGNAL_META[asset_class].items()}
    if asset_class == "pump" and process_profile == "centrifugal_vfd":
        result["rpm"] = ("rotational_speed", "rpm", 0, 5000)
    return result
