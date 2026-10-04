"""Versioned scenario and asset models."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

AssetType = Literal["cnc", "pump", "compressor", "conveyor"]
Regime = Literal[
    "OFF", "IDLE", "WARMUP", "LOW_LOAD", "NORMAL_LOAD", "HIGH_LOAD",
    "COOLDOWN", "MAINTENANCE",
]
AnomalyType = Literal[
    "sensor_drift", "sudden_spike", "bearing_degradation", "cavitation",
    "cooling_degradation", "mechanical_overload", "sensor_stuck", "sensor_bias",
    "missing_telemetry", "single_signal_loss", "asset_communication_loss",
    "quality_degradation", "regime_mismatch", "multivariate_novelty", "air_leak",
    "maintenance_activity",
]

_ANOMALY_PARAMETER_KEYS = {
    "sensor_drift": {"signal", "rate_per_minute", "onset_delay_power"},
    "sudden_spike": {"signal", "magnitude"},
    "bearing_degradation": {"vibration_gain", "temperature_gain", "progression", "onset_delay_power"},
    "cavitation": {"vibration_gain", "flow_loss", "pressure_loss", "current_gain", "onset_delay_power"},
    "cooling_degradation": {"temperature_gain", "onset_delay_power"},
    "mechanical_overload": {"current_gain", "vibration_gain", "onset_delay_power"},
    "sensor_stuck": {"signal"},
    "sensor_bias": {"signal", "bias"},
    "missing_telemetry": {"loss_pct", "signal", "signals", "tag_selection", "tag_count", "tag_weights"},
    "single_signal_loss": {"loss_pct", "signal", "signals"},
    "asset_communication_loss": {"loss_pct", "signal", "signals", "tag_selection", "tag_count", "tag_weights"},
    "quality_degradation": set(),
    "regime_mismatch": {"load_multiplier", "onset_delay_power"},
    "multivariate_novelty": {"signal_a", "signal_b", "signal_a_pct", "signal_b_pct"},
    "air_leak": {"pressure_loss_fraction", "current_gain", "progression", "onset_delay_power"},
    "maintenance_activity": {"load_multiplier", "onset_delay_power"},
}


class Anomaly(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: AnomalyType
    asset: str
    start: float = Field(ge=0, description="Start offset in seconds")
    duration: float = Field(gt=0, description="Duration in seconds")
    parameters: dict[str, float | str | bool | list[str] | dict[str, float]] = Field(default_factory=dict)
    severity: float = Field(default=0.4, ge=0, le=1)
    difficulty: Literal["easy", "medium", "hard", "very_hard"] | None = None
    resolved_difficulty: dict[str, float | str] | None = None

    @field_validator("parameters")
    @classmethod
    def validate_parameter_maps(cls, value: dict[str, Any], info: Any) -> dict[str, Any]:
        anomaly_type = info.data.get("type")
        allowed = _ANOMALY_PARAMETER_KEYS.get(anomaly_type, set())
        unknown = set(value) - allowed
        if unknown:
            raise ValueError(f"unknown parameters for {anomaly_type}: {', '.join(sorted(unknown))}")
        numeric_keys = {
            "rate_per_minute", "magnitude", "vibration_gain", "temperature_gain", "flow_loss",
            "pressure_loss", "current_gain", "bias", "loss_pct", "tag_count", "load_multiplier",
            "signal_a_pct", "signal_b_pct", "pressure_loss_fraction",
        }
        for key in numeric_keys & value.keys():
            parameter = value[key]
            if isinstance(parameter, bool) or not isinstance(parameter, (int, float)) or not float("-inf") < parameter < float("inf"):
                raise ValueError(f"{key} must be a finite number")
        for key in {"vibration_gain", "temperature_gain", "flow_loss", "pressure_loss", "current_gain"} & value.keys():
            if value[key] < 0:
                raise ValueError(f"{key} must be non-negative")
        for key in {"flow_loss", "pressure_loss", "pressure_loss_fraction"} & value.keys():
            if value[key] > 1:
                raise ValueError(f"{key} must be within 0..1")
        for key in {"signal_a_pct", "signal_b_pct"} & value.keys():
            if not 0 <= value[key] <= 1:
                raise ValueError(f"{key} must be within 0..1")
        if "loss_pct" in value and not 0 <= value["loss_pct"] <= 100:
            raise ValueError("loss_pct must be within 0..100")
        if "load_multiplier" in value and not 0 <= value["load_multiplier"] <= 1:
            raise ValueError("load_multiplier must be within 0..1")
        if "tag_count" in value and (value["tag_count"] < 1 or int(value["tag_count"]) != value["tag_count"]):
            raise ValueError("tag_count must be a positive integer")
        if "progression" in value and (
            not isinstance(value["progression"], str)
            or value["progression"] not in {"linear", "slow_start", "fast_start"}
        ):
            raise ValueError("progression must be linear, slow_start, or fast_start")
        if "tag_selection" in value and (
            not isinstance(value["tag_selection"], str)
            or value["tag_selection"] not in {"all", "single", "multiple", "weighted"}
        ):
            raise ValueError("tag_selection must be all, single, multiple, or weighted")
        for key in {"signal", "signal_a", "signal_b"} & value.keys():
            if not isinstance(value[key], str) or not value[key]:
                raise ValueError(f"{key} must be a string")
        if "signals" in value and (
            not isinstance(value["signals"], list)
            or any(not isinstance(name, str) or not name for name in value["signals"])
        ):
            raise ValueError("signals must be a list of tag names")
        if anomaly_type == "single_signal_loss" and "signals" in value and len(value["signals"]) != 1:
            raise ValueError("single_signal_loss must select exactly one signal")
        if "signal" in value and "signals" in value:
            raise ValueError("use either signal or signals, not both")
        if ("signal" in value or "signals" in value) and any(key in value for key in ("tag_selection", "tag_count", "tag_weights")):
            raise ValueError("explicit signal selection cannot be combined with tag selection parameters")
        if "tag_weights" in value and value.get("tag_selection") != "weighted":
            raise ValueError("tag_weights requires tag_selection=weighted")
        if value.get("tag_selection") == "weighted" and "tag_weights" not in value and "signal" not in value and "signals" not in value:
            raise ValueError("weighted tag_selection requires tag_weights")
        if "tag_count" in value and value.get("tag_selection") != "multiple":
            raise ValueError("tag_count requires tag_selection=multiple")
        if "signal_a_pct" in value and "signal_a" not in value:
            raise ValueError("signal_a_pct requires signal_a")
        if "signal_b_pct" in value and "signal_b" not in value:
            raise ValueError("signal_b_pct requires signal_b")
        onset_delay_power = value.get("onset_delay_power")
        if onset_delay_power is not None and (
            isinstance(onset_delay_power, bool)
            or not isinstance(onset_delay_power, (int, float))
            or not float("-inf") < onset_delay_power < float("inf")
            or not 0 <= onset_delay_power <= 4
        ):
            raise ValueError("onset_delay_power must be finite and within 0..4")
        weights = value.get("tag_weights")
        if weights is not None and (
            not isinstance(weights, dict)
            or any(isinstance(weight, bool) or not isinstance(weight, (int, float)) or not float("-inf") < weight < float("inf") or weight < 0 for weight in weights.values())
            or sum(weights.values()) <= 0
        ):
            raise ValueError("tag_weights must contain finite, non-negative values with a positive total")
        return value


class AssetSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    asset_id: str
    asset_class: AssetType
    process_profile: Literal["generic", "metropt3_rail_apu", "centrifugal_vfd"] = "generic"
    process_profile_version: str = "1.0.0"
    process_parameters: dict[str, float] = Field(default_factory=dict)
    regimes: list[Regime] = Field(
        default_factory=lambda: ["WARMUP", "LOW_LOAD", "NORMAL_LOAD", "HIGH_LOAD", "COOLDOWN"]
    )
    device_id: str | None = None
    site_id: str | None = None
    zone_id: str | None = None

    @field_validator("process_profile")
    @classmethod
    def profile_matches_asset(cls, value: str, info: Any) -> str:
        asset_class = info.data.get("asset_class")
        if value == "metropt3_rail_apu" and asset_class != "compressor":
            raise ValueError("metropt3_rail_apu process_profile requires asset_class=compressor")
        if value == "centrifugal_vfd" and asset_class != "pump":
            raise ValueError("centrifugal_vfd process_profile requires asset_class=pump")
        return value

    @field_validator("process_profile_version")
    @classmethod
    def validate_process_profile_version(cls, value: str, info: Any) -> str:
        profile = info.data.get("process_profile", "generic")
        supported = {
            "generic": {"1.0.0"},
            "centrifugal_vfd": {"1.0.0"},
            "metropt3_rail_apu": {"1.0.0", "1.1.0"},
        }
        if value not in supported.get(profile, set()):
            raise ValueError(f"unsupported process_profile_version {value!r} for {profile}")
        return value

    @field_validator("process_parameters")
    @classmethod
    def validate_process_parameters(cls, value: dict[str, float], info: Any) -> dict[str, float]:
        profile = info.data.get("process_profile", "generic")
        rail_apu_parameters = {
            "load_tau_s", "current_loaded_base_a", "current_loaded_span_a", "current_start_a", "current_unloaded_a", "current_off_a",
            "current_noise_a", "pressure_loaded_min_bar", "pressure_loaded_span_bar",
            "pressure_off_bar", "pressure_noise_bar", "oil_temperature_rise_c",
            "oil_thermal_tau_s", "discharge_temperature_rise_c", "discharge_noise_c",
            "vibration_base_mm_s", "vibration_load_gain_mm_s", "vibration_noise_mm_s",
        }
        generic_parameters = {"load_scale", "actuator_tau_s", "thermal_time_constant_scale", "sensor_noise_scale", "initial_temperature_offset_c"}
        pump_parameters = {
            "pump_rated_speed_rpm", "pump_rated_flow_l_min", "pump_rated_pressure_bar",
            "pump_total_efficiency", "pump_supply_voltage_v", "pump_power_factor",
            "pump_idle_current_a", "pump_temperature_rise_c",
        }
        allowed = (
            rail_apu_parameters if profile == "metropt3_rail_apu"
            else generic_parameters | pump_parameters if profile == "centrifugal_vfd"
            else generic_parameters
        )
        unknown = set(value) - allowed
        if profile == "metropt3_rail_apu" and info.data.get("process_profile_version") != "1.1.0":
            incompatible = set(value) & {"current_start_a", "current_unloaded_a"}
            if incompatible:
                raise ValueError(f"{', '.join(sorted(incompatible))} only available in profile version 1.1.0")
        if unknown:
            raise ValueError(f"unknown process parameters: {', '.join(sorted(unknown))}")
        if any(not isinstance(parameter, (int, float)) or not float("-inf") < parameter < float("inf") for parameter in value.values()):
            raise ValueError("process parameter values must be finite numbers")
        for key, parameter in value.items():
            if key.endswith("tau_s") and parameter <= 0:
                raise ValueError(f"{key} must be positive")
            if key.endswith("_scale") and parameter <= 0:
                raise ValueError(f"{key} must be positive")
            if key == "load_scale" and parameter > 1.5:
                raise ValueError("load_scale must not exceed 1.5")
            if key == "initial_temperature_offset_c" and not -30 <= parameter <= 50:
                raise ValueError("initial_temperature_offset_c must be within -30..50 C")
            if key.endswith(("noise_a", "noise_bar", "noise_c", "noise_mm_s")) and parameter < 0:
                raise ValueError(f"{key} must be non-negative")
        pump_ranges = {
            "pump_rated_speed_rpm": (500, 3500),
            "pump_rated_flow_l_min": (100, 2000),
            "pump_rated_pressure_bar": (0.5, 13),
            "pump_total_efficiency": (0.1, 1),
            "pump_supply_voltage_v": (100, 1000),
            "pump_power_factor": (0.1, 1),
            "pump_idle_current_a": (0, 20),
            "pump_temperature_rise_c": (1, 100),
            "sensor_noise_scale": (0, 10),
            "thermal_time_constant_scale": (0.01, 100),
            "actuator_tau_s": (0.01, 100000),
        }
        rail_apu_ranges = {
            "load_tau_s": (0.01, 100000),
            "current_loaded_base_a": (0, 20),
            "current_loaded_span_a": (0, 20),
            "current_start_a": (0, 20),
            "current_unloaded_a": (0, 20),
            "current_off_a": (0, 2),
            "pressure_loaded_min_bar": (0, 20),
            "pressure_loaded_span_bar": (0, 20),
            "pressure_off_bar": (0, 20),
            "oil_thermal_tau_s": (0.01, 1000000),
            "oil_temperature_rise_c": (0, 150),
        }
        if profile == "metropt3_rail_apu":
            for key, limits in rail_apu_ranges.items():
                if key in value and not limits[0] <= value[key] <= limits[1]:
                    raise ValueError(f"{key} must be within {limits[0]}..{limits[1]}")
        for key, limits in pump_ranges.items():
            if key in value and not limits[0] <= value[key] <= limits[1]:
                raise ValueError(f"{key} must be within {limits[0]}..{limits[1]}")
        if profile == "centrifugal_vfd":
            params = {
                "pump_rated_speed_rpm": 2900.0,
                "pump_rated_flow_l_min": 750.0,
                "pump_rated_pressure_bar": 12.0,
                "pump_total_efficiency": 0.65,
                "pump_supply_voltage_v": 400.0,
                "pump_power_factor": 0.85,
                "pump_idle_current_a": 4.0,
            }
            params.update(value)
            hydraulic_power_kw = (
                params["pump_rated_flow_l_min"] * params["pump_rated_pressure_bar"] / 600
            )
            rated_current = params["pump_idle_current_a"] + (
                hydraulic_power_kw * 1000
                / params["pump_total_efficiency"]
                / (3 ** 0.5 * params["pump_supply_voltage_v"] * params["pump_power_factor"])
            )
            maximum_regime_current = params["pump_idle_current_a"] + (
                rated_current - params["pump_idle_current_a"]
            ) * (0.86 * 1.5) ** 3
            if maximum_regime_current > 100:
                raise ValueError("pump parameters exceed the pump motor_current_a engineering maximum at HIGH_LOAD")
        return value


class Scenario(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scenario_id: str
    scenario_version: str = "1.0.0"
    run_id: str = "run-0001"
    description: str = ""
    duration_s: int = Field(default=600, gt=0)
    sampling_interval_ms: int = Field(default=1000, gt=0)
    sampling_jitter_ms: int = Field(default=0, ge=0)
    ambient_temperature_c: float = 22.0
    ambient_temperature_drift_c: float = Field(default=0.0, ge=-20, le=20)
    shift_pattern: list[Regime] = Field(default_factory=list)
    assets: list[AssetSpec]
    anomalies: list[Anomaly] = Field(default_factory=list)
    expose_operating_regime: bool = False

    @field_validator("assets")
    @classmethod
    def assets_not_empty(cls, value: list[AssetSpec]) -> list[AssetSpec]:
        if not value:
            raise ValueError("scenario must include at least one asset")
        ids = [asset.asset_id for asset in value]
        if len(ids) != len(set(ids)):
            raise ValueError("asset_id values must be unique within a scenario")
        return value

    @field_validator("anomalies")
    @classmethod
    def anomalies_fit_run(cls, value: list[Anomaly], info: Any) -> list[Anomaly]:
        duration = info.data.get("duration_s")
        if duration is not None:
            for anomaly in value:
                if anomaly.start + anomaly.duration > duration:
                    raise ValueError(f"anomaly {anomaly.type} ends after scenario duration")
        return value


class GroundTruthEvent(BaseModel):
    event_id: str
    asset_id: str
    type: str
    start: datetime
    end: datetime
    affected_signals: list[str]
    severity: float
    parameters: dict[str, float | str | bool | list[str] | dict[str, float]] = Field(default_factory=dict)
