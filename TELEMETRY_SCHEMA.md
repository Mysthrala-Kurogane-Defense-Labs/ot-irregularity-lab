# Canonical telemetry schema

Telemetry schema is versioned independently from software and ground truth (`schema_version: 1.0.0`). Ground truth JSON carries its own `ground_truth_schema_version` so changes to labels do not imply telemetry contract changes.

Schema version `1.0.0`. One row represents one observed tag value, not one asset snapshot.

| Field | Type | Meaning |
|---|---|---|
| `schema_version` | string | Canonical schema version |
| `run_id` | string | Run identifier |
| `timestamp` | UTC datetime | Observation time |
| `asset_id` | string | Stable asset identifier within scenario |
| `asset_class` | string | CNC, PUMP, COMPRESSOR, CONVEYOR |
| `tag_id` | string | Canonical signal name |
| `signal_class` | string | Engineering category |
| `value` | float64 | Engineering-unit measurement |
| `unit` | string | Unit label |
| `quality` | string | GOOD, UNCERTAIN, BAD; absence represents missing observation |
| `sampling_interval_ms` | int64 | Expected interval, actual elapsed interval after jitter |
| `operating_regime` | nullable string | Optional PLC-visible regime; default hidden |
| `engineering_min`, `engineering_max` | float64 | Declared engineering bounds, not statistical normal limits |
| `protocol`, `device_id`, `site_id`, `zone_id` | nullable string | Optional interoperable context |

Missing expected samples are represented by the difference from the declared cadence and event metadata, not synthetic null rows. Ground truth is stored in another file and must not be joined into model input.
