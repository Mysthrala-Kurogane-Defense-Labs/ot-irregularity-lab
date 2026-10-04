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


class Anomaly(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: AnomalyType
    asset: str
    start: float = Field(ge=0, description="Start offset in seconds")
    duration: float = Field(gt=0, description="Duration in seconds")
    parameters: dict[str, float | str | bool | list[str]] = Field(default_factory=dict)
    severity: float = Field(default=0.4, ge=0, le=1)
    difficulty: Literal["easy", "medium", "hard", "very_hard"] | None = None
    resolved_difficulty: dict[str, float | str] | None = None


class AssetSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    asset_id: str
    asset_class: AssetType
    process_profile: Literal["generic", "metropt3_rail_apu"] = "generic"
    process_profile_version: Literal["1.0.0"] = "1.0.0"
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
        return value

    @field_validator("process_parameters")
    @classmethod
    def validate_process_parameters(cls, value: dict[str, float], info: Any) -> dict[str, float]:
        profile = info.data.get("process_profile", "generic")
        rail_apu_parameters = {
            "load_tau_s", "current_loaded_base_a", "current_loaded_span_a", "current_off_a",
            "current_noise_a", "pressure_loaded_min_bar", "pressure_loaded_span_bar",
            "pressure_off_bar", "pressure_noise_bar", "oil_temperature_rise_c",
            "oil_thermal_tau_s", "discharge_temperature_rise_c", "discharge_noise_c",
            "vibration_base_mm_s", "vibration_load_gain_mm_s", "vibration_noise_mm_s",
        }
        generic_parameters = {"load_scale", "actuator_tau_s", "thermal_time_constant_scale", "sensor_noise_scale", "initial_temperature_offset_c"}
        allowed = rail_apu_parameters if profile == "metropt3_rail_apu" else generic_parameters
        unknown = set(value) - allowed
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
    parameters: dict[str, float | str | bool | list[str]] = Field(default_factory=dict)
