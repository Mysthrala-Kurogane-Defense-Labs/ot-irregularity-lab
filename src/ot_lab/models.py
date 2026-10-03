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
    "quality_degradation", "regime_mismatch", "multivariate_novelty",
    "maintenance_activity",
]


class Anomaly(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: AnomalyType
    asset: str
    start: float = Field(ge=0, description="Start offset in seconds")
    duration: float = Field(gt=0, description="Duration in seconds")
    parameters: dict[str, float | str | bool] = Field(default_factory=dict)
    severity: float = Field(default=0.4, ge=0, le=1)
    difficulty: Literal["easy", "medium", "hard", "very_hard"] | None = None
    resolved_difficulty: dict[str, float | str] | None = None


class AssetSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    asset_id: str
    asset_class: AssetType
    regimes: list[Regime] = Field(
        default_factory=lambda: ["WARMUP", "LOW_LOAD", "NORMAL_LOAD", "HIGH_LOAD", "COOLDOWN"]
    )
    device_id: str | None = None
    site_id: str | None = None
    zone_id: str | None = None


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
    parameters: dict[str, float | str | bool] = Field(default_factory=dict)
